#!/usr/bin/env python3
"""security_gateway -- synchronous pre-execution admission control.

Role in the minimal closed loop (方案v1.2 §3.1)::

    Planner  --/rg/guarded_navigate (Action Goal)-->  Gateway
                                                       |  load trusted TaskPolicy
                                                       |  synchronous decision
                                        BLOCK ---------+---> reject (DecisionEvent only)
                                        ALLOW ---------+---> /rg/nav_execute (Action Client)
                                                                      |
                                                              NavigationSim
                                                                      |
                                   ExecutionEvent  <------------------ + Result back to Planner

Hard constraints implemented here
---------------------------------
* The Gateway never mutates the policy file; it only reads it (方案v1.2 §2.2).
* A missing / invalid / inactive policy is a fail-closed BLOCK. There is no
  bypass flag, no environment override, and no "assume the last good policy".
* BLOCK never creates a downstream Goal.
* Every received Goal produces a RosCommEvent and a DecisionEvent with the same
  ``event_id``; a successful forward additionally produces an ExecutionEvent.
* Every wait is bounded by an explicit timeout.

Deadlock safety (requirement 8)
-------------------------------
rclpy 7.1.12 (Jazzy) dispatches every waitable callback as an ``rclpy.task.Task``
onto ``MultiThreadedExecutor``'s own ``ThreadPoolExecutor`` worker threads
(``executors.py``: ``MultiThreadedExecutor._spin_once_impl`` ->
``self._executor.submit(handler)``). ``await_or_execute`` invokes a *synchronous*
callback inline on that worker thread rather than awaiting it. Consequently this
node uses:

  * ``MultiThreadedExecutor(num_threads=4)`` -- blocking here burns one worker,
    leaving three to service other callbacks;
  * ``ReentrantCallbackGroup`` for the Action **Server** and a *separate*
    ``ReentrantCallbackGroup`` for the Action **Client**, so client responses can
    be processed while ``_on_execute`` is blocked waiting for them.

That exact combination is what makes the blocking ``threading.Event.wait()`` in
``wait_for_future`` safe. A single-threaded executor, or one shared
mutually-exclusive group, would deadlock.
"""

from __future__ import annotations

import json
import os
import threading
import signal
import sys
import time
from typing import Any, Dict, Optional

import rclpy
from rclpy.action import ActionClient, ActionServer
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from rg_interfaces.srv import SwitchTask

from rg_interfaces.action import PatrolNavigate
from rg_policy import reason_codes, task_state
from rg_policy.task_state import (
    STATE_ACTIVE, TaskStateMachine, TaskTransitionEvent, parse_task_phases,
)
from rg_policy.state_store import StateStoreError, TaskStateStore
from rg_policy.task_policy import PolicySchemaError, PolicyProvider, TaskPolicy
from rg_policy.events import (
    AuditSinkError,
    DecisionEvent,
    EventWriter,
    ExecutionEvent,
    RosCommEvent,
    new_event_id,
    utc_now_iso,
)
from rg_policy.futures import WaitTimeout, wait_for_future
from rg_policy.policy_engine import Decision, NavRequest, evaluate
from rg_policy.request_tracker import RequestTracker

DEFAULT_UPSTREAM_ACTION = '/rg/guarded_navigate'
DEFAULT_DOWNSTREAM_ACTION = '/rg/nav_execute'
EXECUTOR_THREADS = 4


def action_goal_id_to_hex(goal_id: Any) -> str:
    """Render a ``unique_identifier_msgs/UUID`` as a stable hex string."""
    raw = getattr(goal_id, 'uuid', None)
    if raw is None:
        return str(goal_id)
    return bytes(raw).hex()


class SecurityGateway(Node):
    # --- 下游执行状态 / 取消状态的显式取值（任务 B4） -------------------------
    #: Goal 已创建并被接受，但结果未按时返回：执行状态未知，任务可能仍在运行。
    DOWNSTREAM_STATE_UNKNOWN = 'UNKNOWN_MAY_STILL_BE_RUNNING'
    #: 连 Goal 是否被下游接受都未确认。
    DOWNSTREAM_STATE_NOT_CONFIRMED = 'NOT_CONFIRMED_CREATED'
    #: 取消请求已发出，但未等待/未获得确认。
    CANCEL_REQUESTED_UNCONFIRMED = 'REQUESTED_UNCONFIRMED'
    #: 取消请求本身发送失败。
    CANCEL_REQUEST_FAILED = 'REQUEST_FAILED'
    #: 该场景不适用取消（例如 Goal 从未被接受）。
    CANCEL_NOT_APPLICABLE = 'NOT_APPLICABLE'

    def __init__(self) -> None:
        super().__init__('security_gateway')

        self.upstream_action = self.declare_parameter(
            'upstream_action', DEFAULT_UPSTREAM_ACTION).value
        self.downstream_action = self.declare_parameter(
            'downstream_action', DEFAULT_DOWNSTREAM_ACTION).value
        policy_path = self.declare_parameter(
            'policy_path', 'config/task_policy.yaml').value
        audit_log_path = self.declare_parameter(
            'audit_log_path', 'logs/audit.jsonl').value
        self.execution_timeout_sec = float(self.declare_parameter(
            'execution_timeout_sec', 10.0).value)
        self.downstream_accept_timeout_sec = float(self.declare_parameter(
            'downstream_accept_timeout_sec', 10.0).value)
        self.server_ready_timeout_sec = float(self.declare_parameter(
            'server_ready_timeout_sec', 15.0).value)
        duplicate_ttl_sec = float(self.declare_parameter(
            'duplicate_ttl_sec', 600.0).value)
        rate_window_sec = float(self.declare_parameter(
            'rate_window_sec', 60.0).value)
        self.audit_fsync = bool(self.declare_parameter('audit_fsync', False).value)
        # 仅用于故障注入测试（任务 B2）。取值 none|comm|decision|execution|all。
        # 安全性：该机制**只能制造审计写失败**，从而让请求被拒绝；它没有任何分支会放行请求，
        # 因此不构成"故障绕过"。默认 none；启用时会写显式告警。取值非法时拒绝启动，
        # 避免拼写错误导致"以为注入了、其实没有"。
        self.audit_fault_injection = str(
            self.declare_parameter('audit_fault_injection', 'none').value).strip().lower()
        if self.audit_fault_injection not in self.AUDIT_FAULT_CHOICES:
            raise ValueError(
                'audit_fault_injection must be one of {0}, got {1!r}'.format(
                    self.AUDIT_FAULT_CHOICES, self.audit_fault_injection))

        # Fail fast: an unwritable audit sink must stop the Gateway rather than
        # let it run without an audit trail.
        self._audit_log_path = os.path.abspath(str(audit_log_path))
        self._writer = EventWriter(self._audit_log_path, fsync=self.audit_fsync)

        self._policy_provider = PolicyProvider(str(policy_path))
        self._tracker = RequestTracker(
            duplicate_ttl_sec=duplicate_ttl_sec, rate_window_sec=rate_window_sec)
        self._audit_failures = 0
        self._post_execution_audit_failures = 0
        self._transition_audit_failures = 0
        self._blocked_count = 0
        self._allowed_count = 0
        self._forwarded_count = 0

        # M3：任务状态切换与 Goal 准入共享同一把可重入锁。
        # 用 RLock 是因为切换回调内部会再次读取状态，避免自锁死。
        self._transition_lock = threading.RLock()
        self._in_flight = 0
        self._admission_registered = False
        self._transition_count = 0
        self._rejected_transition_count = 0
        self._task_state = None
        self._persistence = None

        self._server_cb_group = ReentrantCallbackGroup()
        self._client_cb_group = ReentrantCallbackGroup()

        self._action_server = ActionServer(
            self,
            PatrolNavigate,
            self.upstream_action,
            execute_callback=self._on_execute,
            callback_group=self._server_cb_group,
        )
        self._client = ActionClient(
            self,
            PatrolNavigate,
            self.downstream_action,
            callback_group=self._client_cb_group,
        )
        # M3 管理接口：单独的回调组，避免与 Action 执行回调互相阻塞。
        self._admin_cb_group = ReentrantCallbackGroup()
        self._switch_service = self.create_service(
            SwitchTask, '/rg/task_control/switch', self._on_switch_task,
            callback_group=self._admin_cb_group)

        policy, policy_error = self._policy_provider.current()
        self._init_task_control(policy)
        self._downstream_available = self._client.wait_for_server(
            timeout_sec=self.server_ready_timeout_sec)

        self.get_logger().info('GATEWAY_START ' + json.dumps({
            'node': self.get_name(),
            'upstream_action': self.upstream_action,
            'downstream_action': self.downstream_action,
            'policy_path': self._policy_provider.path,
            'audit_log_path': self._audit_log_path,
            'execution_timeout_sec': self.execution_timeout_sec,
            'downstream_accept_timeout_sec': self.downstream_accept_timeout_sec,
            'duplicate_ttl_sec': duplicate_ttl_sec,
            'rate_window_sec': rate_window_sec,
            'audit_fault_injection': self.audit_fault_injection,
            'task_state_path': getattr(self, '_task_state_path', '') or None,
        }, ensure_ascii=False))

        if self.audit_fault_injection != 'none':
            self.get_logger().warning('AUDIT_FAULT_INJECTION_ACTIVE ' + json.dumps({
                'audit_fault_injection': self.audit_fault_injection,
                'purpose': 'test-only fault injection for task B2',
                'safety': 'this mechanism can only cause audit write failures and therefore more '
                          'rejections; it has no code path that can allow or bypass a request',
            }, ensure_ascii=False))

        if policy is None:
            self.get_logger().error('POLICY_UNAVAILABLE ' + json.dumps({
                'policy_path': self._policy_provider.path,
                'reason_code': reason_codes.POLICY_MISSING,
                'error': policy_error.message if policy_error else 'unknown',
                'effect': 'all Goal requests will be BLOCKed until a valid policy is loaded',
            }, ensure_ascii=False))

        self.get_logger().info('GATEWAY_READY ' + json.dumps({
            'downstream_server_available': bool(self._downstream_available),
            'policy_loaded': policy is not None,
            'policy_version': policy.policy_version if policy else reason_codes.POLICY_VERSION_UNKNOWN,
            'task_id': policy.task_id if policy else reason_codes.TASK_ID_UNKNOWN,
            'executor': 'MultiThreadedExecutor',
            'executor_threads': EXECUTOR_THREADS,
            'server_callback_group': 'ReentrantCallbackGroup',
            'client_callback_group': 'ReentrantCallbackGroup(separate)',
        }, ensure_ascii=False))

    # ------------------------------------------------------------------ audit
    #: 仅用于故障注入测试的取值。它**只能制造失败**，不能放行任何请求，
    #: 因此不具备"绕过"能力；默认 none，启用时启动日志会显式告警。
    AUDIT_FAULT_CHOICES = ('none', 'comm', 'decision', 'execution', 'all')

    # ---------------------------------------------------------- M3 任务状态
    def _init_task_control(self, policy: Any) -> None:
        """初始化可信任务状态机。配置不可信时**不静默降级**，而是进入限制性状态。"""
        enable = bool(self.declare_parameter('enable_task_control', True).value)
        self._enable_task_control = enable
        if not enable:
            self.get_logger().warning('TASK_CONTROL_DISABLED ' + json.dumps({
                'effect': 'M3 动态约束未启用，按静态策略运行；这是显式配置，不是降级'}))
            return

        document = getattr(self._policy_provider, 'document', None)
        try:
            phases = parse_task_phases(document) if document else {}
        except PolicySchemaError as exc:
            self.get_logger().error('TASK_CONTROL_INVALID ' + json.dumps({
                'error': str(exc),
                'effect': ('task_phases 非法：进入 RECOVERY_REQUIRED，'
                           '所有 Goal 将被拒绝（不会退回旧的宽松权限）')}))
            self._task_state = TaskStateMachine.__new__(TaskStateMachine)
            self._task_state.mark_recovery_required('invalid task_phases: {0}'.format(exc))
            return

        if not phases:
            self.get_logger().warning('TASK_CONTROL_SINGLE_PHASE ' + json.dumps({
                'reason': '策略中没有 task_phases，按单阶段运行（等同静态策略）'}))
            return

        initial = str(document.get('initial_task_phase') or '').strip()
        if not initial:
            # 没有明确初始阶段时，采用配置中**第一个**阶段，而不是任意猜测
            initial = sorted(phases)[0]
        try:
            self._task_state = TaskStateMachine(phases, initial)
        except PolicySchemaError as exc:
            self.get_logger().error('TASK_CONTROL_INVALID ' + json.dumps({
                'error': str(exc), 'effect': '进入 RECOVERY_REQUIRED'}))
            self._task_state = TaskStateMachine.__new__(TaskStateMachine)
            self._task_state.mark_recovery_required(str(exc))
            return

        # 持久化：状态文件是切换的**权威记录**（审计事件是第二个 sink，二者不构成
        # 跨文件原子性，提交顺序固定为"先状态、后审计"）。
        state_path = str(self.declare_parameter('task_state_path', '').value or '').strip()
        self._task_state_path = state_path
        if state_path:
            self._persistence = TaskStateStore(state_path)
            self._restore_or_cold_start(initial, phases, state_path)

        snapshot = self._task_state.snapshot
        self.get_logger().info('TASK_CONTROL_READY ' + json.dumps({
            'service': '/rg/task_control/switch',
            'task_id': snapshot.task_id,
            'task_phase': snapshot.task_phase,
            'policy_epoch': snapshot.policy_epoch,
            'policy_digest': snapshot.policy_digest,
            'available_phases': sorted(phases),
        }, ensure_ascii=False))

    def _restore_or_cold_start(self, initial: str, phases: Any, state_path: str) -> None:
        """按明确规则恢复：以状态文件为准；损坏即失败关闭；缺失即按可信配置冷启动。"""
        try:
            snapshot, used, state = self._persistence.load()
        except StateStoreError as exc:
            self.get_logger().error('TASK_STATE_CORRUPT ' + json.dumps({
                'state_path': state_path, 'error': str(exc),
                'effect': ('进入 RECOVERY_REQUIRED：所有 Goal 被拒绝，直到人工修复或删除'
                           '状态文件后重启；不会静默退回旧的宽松权限')}))
            self._task_state.mark_recovery_required(str(exc))
            self._write_event(_state_event(reason_codes.STATE_FILE_CORRUPT, str(exc)),
                              phase='task_transition')
            return

        if snapshot is None:
            # 文件缺失：按可信配置的初始阶段冷启动（epoch 0）。这是确定性的保守起点，
            # 不是"恢复到旧权限"。
            self.get_logger().warning('TASK_STATE_COLD_START ' + json.dumps({
                'state_path': state_path, 'initial_task_phase': initial,
                'effect': '状态文件不存在，按可信配置初始阶段启动，epoch=0'}))
            self._write_event(_state_event(
                reason_codes.STATE_RESTORED,
                'cold start at {0} (no state file)'.format(initial)),
                phase='task_transition')
            return

        try:
            self._task_state.restore(snapshot, used, STATE_ACTIVE)
        except PolicySchemaError as exc:
            self.get_logger().error('TASK_STATE_INCONSISTENT ' + json.dumps({
                'state_path': state_path, 'error': str(exc),
                'effect': '进入 RECOVERY_REQUIRED，不接受新 Goal 与切换'}))
            self._task_state.mark_recovery_required(str(exc))
            self._write_event(_state_event(reason_codes.STATE_FILE_CORRUPT, str(exc)),
                              phase='task_transition')
            return
        self.get_logger().info('TASK_STATE_RESTORED ' + json.dumps({
            'state_path': state_path,
            'task_phase': snapshot.task_phase,
            'policy_epoch': snapshot.policy_epoch,
            'policy_digest': snapshot.policy_digest,
            'used_transition_ids': len(used),
        }, ensure_ascii=False))
        self._write_event(_state_event(
            reason_codes.STATE_RESTORED,
            'restored {0} epoch={1}'.format(snapshot.task_phase, snapshot.policy_epoch)),
            phase='task_transition')

    def _admission_block_reason(self) -> Optional[str]:
        """状态机不允许准入时返回原因文本，否则返回 None。"""
        if self._task_state is None:
            return None
        state = self._task_state.state
        if state != STATE_ACTIVE:
            return ('task state machine is {0}; no new Goal is admitted until it '
                    'returns to ACTIVE'.format(state))
        return None

    def _effective_policy(self, policy: Any, snapshot: Any) -> Any:
        """把当前生效快照投影成 TaskPolicy，供纯函数 evaluate() 使用。"""
        if policy is None or snapshot is None:
            return None
        return TaskPolicy(
            task_id=snapshot.task_id,
            policy_version=snapshot.policy_version,
            active=snapshot.active,
            coordinate_frame=snapshot.coordinate_frame,
            region=snapshot.allowed_region,
            max_requests_per_minute=snapshot.max_requests_per_minute,
            source_path=policy.source_path,
            loaded_at=policy.loaded_at,
            extra_fields=policy.extra_fields,
        )

    def _release_in_flight(self) -> None:
        with self._transition_lock:
            if self._admission_registered:
                self._in_flight = max(0, self._in_flight - 1)
                self._admission_registered = False

    def _in_flight_count(self) -> int:
        with self._transition_lock:
            return self._in_flight

    def _on_switch_task(self, request: Any, response: Any) -> Any:
        """可信任务切换服务。所有校验都在共享同步边界内完成。"""
        transition_id = str(getattr(request, 'transition_id', '') or '').strip()
        target_task_id = str(getattr(request, 'target_task_id', '') or '').strip()
        target_phase = str(getattr(request, 'target_task_phase', '') or '').strip()
        expected_epoch = int(getattr(request, 'expected_epoch', -1))

        snapshot_before = self._task_state.snapshot if self._task_state is not None else None

        def respond(accepted: bool, reason: str, detail: str, snapshot) -> Any:
            response.accepted = bool(accepted)
            response.reason_code = reason
            response.current_epoch = snapshot.policy_epoch if snapshot else 0
            response.active_task_id = snapshot.task_id if snapshot else ''
            response.active_task_phase = snapshot.task_phase if snapshot else ''
            response.policy_digest = snapshot.policy_digest if snapshot else ''
            response.detail = detail
            return response

        if self._task_state is None:
            self._rejected_transition_count += 1
            return respond(False, reason_codes.TRANSITION_REJECTED_NOT_ACTIVE,
                           '任务状态机未启用（enable_task_control=false 或策略缺少 task_phases）',
                           snapshot_before)

        # 整段切换流程持锁：在途检查、状态迁移、持久化与提交相对于 Goal 准入是原子的。
        with self._transition_lock:
            plan = self._task_state.request_transition(
                transition_id, target_task_id, target_phase, expected_epoch,
                self._in_flight)

            if not plan.accepted:
                self._rejected_transition_count += 1
                snapshot = self._task_state.snapshot
                self._write_transition_event(plan, snapshot, snapshot,
                                             reason_codes.DECISION_BLOCK)
                self.get_logger().warning('TASK_TRANSITION_REJECTED ' + json.dumps({
                    'transition_id': transition_id,
                    'target_task_phase': target_phase,
                    'reason_code': plan.reason_code,
                    'in_flight': self._in_flight,
                    'current_epoch': snapshot.policy_epoch if snapshot else None,
                    'current_task_phase': snapshot.task_phase if snapshot else None,
                    'detail': plan.detail,
                }, ensure_ascii=False))
                return respond(False, plan.reason_code, plan.detail, snapshot)

            # 已通过全部校验：先持久化，再原子提交。持久化失败即回退，
            # 绝不把"尚未提交的新权限"暴露给后续请求。
            persisted, persist_detail = self._persist_transition(plan)
            if not persisted:
                self._task_state.abort(persist_detail, recovery=True)
                self._rejected_transition_count += 1
                snapshot = self._task_state.snapshot
                self._write_transition_event(plan, snapshot, snapshot,
                                             reason_codes.DECISION_BLOCK,
                                             reason_code=reason_codes.TRANSITION_FAILED_PERSIST)
                self.get_logger().error('TASK_TRANSITION_PERSIST_FAILED ' + json.dumps({
                    'transition_id': transition_id, 'detail': persist_detail,
                    'effect': '进入 RECOVERY_REQUIRED，保持旧快照，不接受新的切换'}))
                return respond(False, reason_codes.TRANSITION_FAILED_PERSIST,
                               persist_detail, snapshot)

            snapshot = self._task_state.commit(plan)
            self._transition_count += 1
            self._write_transition_event(plan, snapshot_before, snapshot,
                                         reason_codes.DECISION_ALLOW)
            self.get_logger().info('TASK_TRANSITION_COMMITTED ' + json.dumps({
                'transition_id': transition_id,
                'previous_task_phase': snapshot_before.task_phase if snapshot_before else None,
                'next_task_phase': snapshot.task_phase,
                'previous_epoch': snapshot_before.policy_epoch if snapshot_before else None,
                'next_epoch': snapshot.policy_epoch,
                'policy_digest': snapshot.policy_digest,
            }, ensure_ascii=False))
            return respond(True, reason_codes.TRANSITION_ACCEPTED,
                           '切换已提交，epoch={0}'.format(snapshot.policy_epoch), snapshot)

    def _persist_transition(self, plan: Any):
        """持久化钩子。M3 第 4 阶段接入原子状态文件；未接入时视为成功但不谎报已持久化。"""
        if self._persistence is None:
            return True, 'no persistent store configured'
        return self._persistence.commit(plan, self._task_state)

    def _write_transition_event(self, plan: Any, previous: Any, current: Any,
                                decision: str, reason_code: Optional[str] = None) -> None:
        event = TaskTransitionEvent(
            transition_id=plan.transition_id,
            previous_task_phase=previous.task_phase if previous else '',
            next_task_phase=(plan.target.task_phase if plan.target else
                             (current.task_phase if current else '')),
            previous_epoch=previous.policy_epoch if previous else -1,
            next_epoch=current.policy_epoch if current else -1,
            previous_policy_digest=previous.policy_digest if previous else '',
            next_policy_digest=(plan.target.digest if plan.target else
                                (current.policy_digest if current else '')),
            decision=decision,
            reason_code=reason_code or plan.reason_code,
            transition_at=utc_now_iso(),
            detail=plan.detail,
        )
        self._write_event(event, phase='task_transition')

    def _write_event(self, event: Any, phase: str = 'pre_execution') -> bool:
        """Persist one audit record. Returns False when the sink is unusable.

        ``phase`` 区分两类审计故障（任务 B2 要求不得混淆）：

        * ``pre_execution``  —— 执行**前**必须落库的事件（RosCommEvent / DecisionEvent）。
          写失败意味着"这次请求没有可审计的准入记录"，调用方必须 fail closed，
          不得创建下游 Goal。
        * ``post_execution`` —— 下游动作**已经发生**之后的执行结果记录（ExecutionEvent）。
          此时物理动作不可撤销，写失败只能如实记为"结果未能入库"，
          **绝不能**据此声称下游没有执行。
        """
        event_type = getattr(event, 'EVENT_TYPE', 'unknown')
        injected = self._audit_fault_target(event_type)
        if injected:
            return self._record_audit_failure(
                event, phase,
                'injected fault: simulated {0} write failure (test-only, fail-only)'.format(injected))

        try:
            self._writer.write(event)
        except Exception as exc:  # noqa: BLE001 - audit failure must never crash silently
            return self._record_audit_failure(event, phase, str(exc))
        return True

    def _audit_fault_target(self, event_type: str) -> str:
        """故障注入命中时返回被注入的事件类别，否则返回空串。"""
        if self.audit_fault_injection == 'none':
            return ''
        mapping = {'RosCommEvent': 'comm', 'DecisionEvent': 'decision', 'ExecutionEvent': 'execution'}
        target = mapping.get(event_type, '')
        if not target:
            return ''
        if self.audit_fault_injection == 'all' or self.audit_fault_injection == target:
            return target
        return ''

    def _record_audit_failure(self, event: Any, phase: str, error: str) -> bool:
        event_type = getattr(event, 'EVENT_TYPE', 'unknown')
        if phase == 'pre_execution':
            self._audit_failures += 1
            effect = 'fail closed: no downstream Goal will be created for this request'
        elif phase == 'task_transition':
            # 任务切换审计与"导航请求审计"是两套语义：既不能说"不会创建下游 Goal"，
            # 也不能说"动作已完成不可撤销"。状态文件才是切换的权威记录，
            # 因此这里只如实记账并暴露审计链缺口。
            self._transition_audit_failures += 1
            effect = ('task transition audit record could not be persisted; the authoritative '
                      'record is the persisted state file, but the audit chain now has a gap')
        else:
            self._post_execution_audit_failures += 1
            effect = ('downstream action may already have completed; the write failure is recorded, '
                      'but the physical action cannot be undone. This MUST NOT be read as '
                      '"downstream did not execute".')
        self.get_logger().error('AUDIT_WRITE_FAILED ' + json.dumps({
            'event_type': event_type,
            'event_id': getattr(event, 'event_id', 'unknown'),
            'request_id': getattr(event, 'request_id', None),
            'phase': phase,
            'audit_log_path': self._audit_log_path,
            'error': error,
            'effect': effect,
        }, ensure_ascii=False))
        return False

    # ------------------------------------------------------------- execution
    def _on_execute(self, goal_handle: Any) -> PatrolNavigate.Result:
        goal = goal_handle.request
        target = goal.target
        header = getattr(target, 'header', None)
        position = getattr(getattr(target, 'pose', None), 'position', None)

        request_id = str(goal.request_id)
        task_id = str(goal.task_id)
        frame_id = str(getattr(header, 'frame_id', '') or '')
        x = float(getattr(position, 'x', float('nan')))
        y = float(getattr(position, 'y', float('nan')))
        z = float(getattr(position, 'z', float('nan')))

        event_id = new_event_id()
        now_monotonic = time.monotonic()

        # 1. RosCommEvent: on reception, unconditionally, and before any decision.
        comm_event_written = self._write_event(RosCommEvent(
            event_id=event_id,
            request_id=request_id,
            task_id=task_id,
            observed_via='ros2_action',
            resource=self.upstream_action,
            frame_id=frame_id,
            x=x,
            y=y,
            z=z,
            received_at=utc_now_iso(),
        ))

        # 2. Duplicate accounting is recorded on arrival; the verdict is applied
        #    at its documented position in the rule sequence below.
        is_duplicate = self._tracker.note_received(request_id, now_monotonic)

        # 3. Authoritative policy (read-only; missing/invalid => fail closed).
        policy, policy_error = self._policy_provider.current()

        # 4. M3 同步边界：任务状态检查、策略判定与"登记在途"必须在同一临界区内完成。
        #    否则会出现这样的竞态：切换请求看到在途为 0 并通过校验，而此刻一个已经
        #    判定为 ALLOW 的 Goal 还没登记为在途，切换提交后它仍带着旧权限继续执行。
        with self._transition_lock:
            state_block = self._admission_block_reason()
            snapshot = self._task_state.snapshot if self._task_state is not None else None
            effective_policy = self._effective_policy(policy, snapshot)
            if effective_policy is not None:
                policy = effective_policy

            # 5. Pure synchronous decision.
            request = NavRequest(
                request_id=request_id, task_id=task_id, frame_id=frame_id, x=x, y=y, z=z)
            decision = evaluate(request, policy)

            # 状态机不处于 ACTIVE 时一律拒绝，且拒绝优先于任何放行判定。
            if state_block is not None:
                decision = Decision(
                    decision=reason_codes.DECISION_BLOCK,
                    reason_code=reason_codes.TASK_NOT_ACTIVE,
                    detail=state_block,
                    policy_version=decision.policy_version)
            elif decision.allowed and is_duplicate:
                decision = Decision(
                    decision=reason_codes.DECISION_BLOCK,
                    reason_code=reason_codes.DUPLICATE_REQUEST,
                    detail='request_id {0!r} was already received within the '
                           'duplicate window'.format(request_id),
                    policy_version=decision.policy_version,
                )
            elif decision.allowed and not self._tracker.admit(
                    now_monotonic, policy.max_requests_per_minute):
                decision = Decision(
                    decision=reason_codes.DECISION_BLOCK,
                    reason_code=reason_codes.RATE_LIMIT,
                    detail='more than {0} admitted requests within {1}s'.format(
                        policy.max_requests_per_minute,
                        self._tracker.snapshot()['rate_window_sec']),
                    policy_version=decision.policy_version,
                )

            # 准入成功的 Goal 必须在**解除同步保护之前**登记为在途。
            # 后续若审计失败会把结果改成 BLOCK，那时下游 Goal 从未创建，
            # 因此在 BLOCK 分支里会撤销这次登记（见下方）。
            self._admission_registered = bool(decision.allowed)
            if self._admission_registered:
                self._in_flight += 1

        if not comm_event_written:
            decision = Decision(
                decision=reason_codes.DECISION_BLOCK,
                reason_code=reason_codes.AUDIT_UNAVAILABLE,
                detail='audit sink {0} is unwritable; failing closed'.format(self._audit_log_path),
                policy_version=decision.policy_version,
            )

        decision_event_written = self._write_event(DecisionEvent(
            event_id=event_id,
            request_id=request_id,
            task_id=task_id,
            policy_version=decision.policy_version,
            decision=decision.decision,
            reason_code=decision.reason_code,
            detail=decision.detail,
            decision_at=utc_now_iso(),
            task_phase=snapshot.task_phase if snapshot is not None else None,
            policy_epoch=snapshot.policy_epoch if snapshot is not None else None,
            policy_digest=snapshot.policy_digest if snapshot is not None else None,
        ))

        # 执行前审计必须完整：RosCommEvent 或 DecisionEvent 任一未能落库，都不得创建下游 Goal。
        #
        # 这里**不补写**第二条 DecisionEvent：同一 event_id 只允许一条判定记录，
        # 否则审计链出现歧义（"到底哪条判定生效"）。审计链的缺口本身就是"审计不可用"的
        # 证据，而拒绝原因由 REJECTED 日志（另一个 sink）承载，可关联到 request_id/event_id。
        if decision.allowed and not decision_event_written:
            decision = Decision(
                decision=reason_codes.DECISION_BLOCK,
                reason_code=reason_codes.AUDIT_UNAVAILABLE,
                detail=('decision audit record could not be persisted to {0}; '
                        'failing closed before creating any downstream Goal').format(
                            self._audit_log_path),
                policy_version=decision.policy_version,
            )

        # 6. BLOCK: return the business result and never touch the downstream client.
        if not decision.allowed:
            # 判定阶段曾按"放行"登记过在途名额，但随后被审计失败改判为 BLOCK，
            # 此时下游 Goal 从未创建，必须撤销登记，否则在途计数永远无法归零、
            # 任务切换会被永久阻塞（拒绝服务）。
            self._release_in_flight()
            self._blocked_count += 1
            self.get_logger().warning('REJECTED ' + json.dumps({
                'event_id': event_id,
                'request_id': request_id,
                'task_id': task_id,
                'resource': self.upstream_action,
                'reason_code': decision.reason_code,
                'policy_version': decision.policy_version,
                'policy_error': policy_error.message if policy_error else None,
                'detail': decision.detail,
                'downstream_goal_created': False,
            }, ensure_ascii=False))
            goal_handle.abort()
            return PatrolNavigate.Result(
                success=False, status_code=decision.reason_code, detail=decision.detail)

        self._allowed_count += 1
        # 在途名额已在上面的临界区内登记完毕，因此切换请求不可能在
        # "已判定放行但尚未登记"的窗口里通过校验。用 try/finally 保证正常完成、
        # 下游拒绝、超时、取消未确认、异常退出等**所有**路径都会释放名额。
        try:
            return self._forward(goal_handle, event_id, request_id, task_id, target)
        finally:
            self._release_in_flight()

    # -------------------------------------------------------------- forwarding
    def _forward(self, goal_handle: Any, event_id: str, request_id: str,
                 task_id: str, target: Any) -> PatrolNavigate.Result:
        """Create exactly one downstream Goal and mirror its outcome upstream."""
        downstream_goal = PatrolNavigate.Goal()
        downstream_goal.request_id = request_id
        downstream_goal.task_id = task_id
        downstream_goal.target = target

        downstream_goal_id = reason_codes.DOWNSTREAM_GOAL_ID_NONE
        forwarded = False
        try:
            goal_handle.publish_feedback(PatrolNavigate.Feedback(progress=0.0, phase='FORWARDING'))
        except Exception:  # noqa: BLE001 - feedback is best effort
            pass

        self.get_logger().info('ALLOW_FORWARD ' + json.dumps({
            'event_id': event_id,
            'request_id': request_id,
            'task_id': task_id,
            'downstream_action': self.downstream_action,
        }, ensure_ascii=False))

        # --- downstream acceptance (bounded wait) -------------------------
        try:
            send_future = self._client.send_goal_async(
                downstream_goal,
                feedback_callback=lambda feedback_msg: self._on_downstream_feedback(
                    goal_handle, feedback_msg),
            )
            downstream_handle = wait_for_future(
                send_future,
                self.downstream_accept_timeout_sec,
                'downstream Goal acceptance from {0}'.format(self.downstream_action),
            )
        except WaitTimeout as exc:
            # 连"Goal 是否被下游接受"都未确认：不存在任何下游执行结果。
            detail = (
                'downstream Goal acceptance was NOT confirmed within {0:.3f}s; it is unknown whether '
                'the downstream Action Server {1} received the Goal. No downstream result exists. '
                'Cancel is not applicable.'.format(
                    self.downstream_accept_timeout_sec, self.downstream_action))
            return self._finish_failure(
                goal_handle, event_id, request_id, task_id, downstream_goal_id,
                reason_codes.EXECUTION_TIMEOUT, detail, forwarded,
                downstream_state=self.DOWNSTREAM_STATE_NOT_CONFIRMED,
                cancel_state=self.CANCEL_NOT_APPLICABLE, raw_error=str(exc))
        except Exception as exc:  # noqa: BLE001 - transport failure is fail-closed
            return self._finish_failure(
                goal_handle, event_id, request_id, task_id, downstream_goal_id,
                reason_codes.EXECUTION_TIMEOUT,
                'downstream Goal could not be sent: {0}'.format(exc), forwarded,
                downstream_state=self.DOWNSTREAM_STATE_NOT_CONFIRMED,
                cancel_state=self.CANCEL_NOT_APPLICABLE, raw_error=str(exc))

        if not downstream_handle.accepted:
            return self._finish_failure(
                goal_handle, event_id, request_id, task_id, downstream_goal_id,
                reason_codes.DOWNSTREAM_REJECTED,
                'downstream Action Server {0} rejected the Goal'.format(self.downstream_action),
                forwarded)

        forwarded = True
        self._forwarded_count += 1
        downstream_goal_id = action_goal_id_to_hex(downstream_handle.goal_id)

        # --- downstream result (bounded wait) -----------------------------
        try:
            result_future = downstream_handle.get_result_async()
            wrapped_result = wait_for_future(
                result_future,
                self.execution_timeout_sec,
                'downstream execution result from {0}'.format(self.downstream_action),
            )
        except WaitTimeout as exc:
            # 关键语义（任务 B4）：Goal 已经创建并被下游接受，超时只说明"结果未按时返回"，
            # 既不能推断下游已停止，也不能推断下游没有执行。
            cancel_state = self._try_cancel(downstream_handle)
            detail = (
                'downstream Goal {0} WAS created and accepted, but its execution result did not arrive '
                'within {1:.3f}s. Downstream execution state is UNKNOWN and the task may still be '
                'running. Cancel was {2} (request sent, confirmation NOT awaited). '
                'This timeout is NOT evidence that the downstream stopped, and NOT evidence that it '
                'never executed.'.format(
                    downstream_goal_id, self.execution_timeout_sec, cancel_state))
            return self._finish_failure(
                goal_handle, event_id, request_id, task_id, downstream_goal_id,
                reason_codes.EXECUTION_TIMEOUT, detail, forwarded,
                downstream_state=self.DOWNSTREAM_STATE_UNKNOWN,
                cancel_state=cancel_state, raw_error=str(exc))
        except Exception as exc:  # noqa: BLE001
            return self._finish_failure(
                goal_handle, event_id, request_id, task_id, downstream_goal_id,
                reason_codes.EXECUTION_FAILED,
                'downstream result unavailable: {0}'.format(exc), forwarded,
                downstream_state=self.DOWNSTREAM_STATE_UNKNOWN,
                cancel_state=self.CANCEL_NOT_APPLICABLE, raw_error=str(exc))

        downstream_result = wrapped_result.result
        success = bool(getattr(downstream_result, 'success', False))
        status_code = str(getattr(downstream_result, 'status_code', '') or '')
        if not reason_codes.is_known_status_code(status_code):
            status_code = reason_codes.EXECUTION_FAILED
        detail = str(getattr(downstream_result, 'detail', '') or '')

        self._write_event(ExecutionEvent(
            event_id=event_id,
            request_id=request_id,
            task_id=task_id,
            downstream_goal_id=downstream_goal_id,
            success=success,
            status_code=status_code,
            detail='downstream result: {0}'.format(detail),
            finished_at=utc_now_iso(),
        ), phase='post_execution')

        self.get_logger().info('EXECUTION_RESULT ' + json.dumps({
            'event_id': event_id,
            'request_id': request_id,
            'downstream_goal_id': downstream_goal_id,
            'success': success,
            'status_code': status_code,
        }, ensure_ascii=False))

        if success:
            goal_handle.succeed()
        else:
            goal_handle.abort()
        return PatrolNavigate.Result(success=success, status_code=status_code, detail=detail)

    def _finish_failure(self, goal_handle: Any, event_id: str, request_id: str, task_id: str,
                        downstream_goal_id: str, status_code: str, detail: str,
                        forwarded: bool, downstream_state: str = 'NOT_APPLICABLE',
                        cancel_state: str = 'NOT_APPLICABLE',
                        raw_error: str = '') -> PatrolNavigate.Result:
        """Fail-closed completion: no Result is invented, the failure is audited.

        ExecutionEvent 属于"下游动作已经发生之后"的记录（``phase='post_execution'``）：
        写失败不能再改变已经发生的物理动作，只如实记录。
        """
        self._write_event(ExecutionEvent(
            event_id=event_id,
            request_id=request_id,
            task_id=task_id,
            downstream_goal_id=downstream_goal_id,
            success=False,
            status_code=status_code,
            detail=detail,
            finished_at=utc_now_iso(),
        ), phase='post_execution')

        self.get_logger().error('EXECUTION_FAILURE ' + json.dumps({
            'event_id': event_id,
            'request_id': request_id,
            'downstream_goal_id': downstream_goal_id,
            'status_code': status_code,
            'forwarded': forwarded,
            'downstream_state': downstream_state,
            'cancel_state': cancel_state,
            'raw_error': raw_error or None,
            'detail': detail,
        }, ensure_ascii=False))

        # 与超时相关的状态单独再打一条机器可读日志，便于在对照实验中把
        # "DDS 层拒绝 / Action Server 不可达 / 业务阻断 / 执行状态未知" 区分开。
        if status_code == reason_codes.EXECUTION_TIMEOUT:
            self.get_logger().error('EXECUTION_TIMEOUT_STATE ' + json.dumps({
                'event_id': event_id,
                'request_id': request_id,
                'downstream_goal_id': downstream_goal_id,
                'downstream_state': downstream_state,
                'cancel_state': cancel_state,
                'execution_may_continue': downstream_state == self.DOWNSTREAM_STATE_UNKNOWN,
                'note': ('Gateway timeout does not prove the downstream stopped, nor that it never ran.'),
            }, ensure_ascii=False))

        goal_handle.abort()
        return PatrolNavigate.Result(success=False, status_code=status_code, detail=detail)

    def _try_cancel(self, downstream_handle: Any) -> str:
        """发出下游取消请求，但**不等待确认**，返回取消状态。

        刻意不再叠加一次有界等待：`cancel_goal_async()` 的结果本身也只是"服务端是否受理取消"，
        并不能证明执行已停止。因此对外只能声明"已请求、未确认"。
        """
        try:
            downstream_handle.cancel_goal_async()
        except Exception as exc:  # noqa: BLE001 - best effort only
            self.get_logger().warning('CANCEL_REQUEST_FAILED ' + json.dumps({
                'error': str(exc),
            }, ensure_ascii=False))
            return self.CANCEL_REQUEST_FAILED
        return self.CANCEL_REQUESTED_UNCONFIRMED

    def _on_downstream_feedback(self, upstream_goal_handle: Any, feedback_msg: Any) -> None:
        """Mirror downstream Feedback upstream. Best effort, never fatal."""
        try:
            feedback = feedback_msg.feedback
            upstream_goal_handle.publish_feedback(PatrolNavigate.Feedback(
                progress=float(getattr(feedback, 'progress', 0.0)),
                phase='DOWNSTREAM:{0}'.format(getattr(feedback, 'phase', '')),
            ))
        except Exception as exc:  # noqa: BLE001
            self.get_logger().debug('feedback mirroring skipped: {0}'.format(exc))

    # --------------------------------------------------------------- shutdown
    def counters(self) -> Dict[str, int]:
        return {
            'received': self._blocked_count + self._allowed_count,
            'blocked': self._blocked_count,
            'allowed': self._allowed_count,
            'forwarded': self._forwarded_count,
            'audit_failures': self._audit_failures,
            'post_execution_audit_failures': self._post_execution_audit_failures,
            'transition_audit_failures': self._transition_audit_failures,
            'in_flight': self._in_flight,
            'transitions_committed': self._transition_count,
            'transitions_rejected': self._rejected_transition_count,
            'task_state': self._task_state.state if self._task_state else None,
            'task_phase': (self._task_state.snapshot.task_phase
                           if self._task_state and self._task_state.snapshot else None),
            'policy_epoch': (self._task_state.snapshot.policy_epoch
                             if self._task_state and self._task_state.snapshot else None),
            'audit_fault_injection': self.audit_fault_injection,
            'audit_records': self._writer.written,
        }

    def destroy_node(self) -> bool:
        snapshot = self.counters()
        snapshot.update(self._tracker.snapshot())
        self.get_logger().info('GATEWAY_COUNTERS ' + json.dumps(snapshot, ensure_ascii=False))
        try:
            self._action_server.destroy()
        except Exception:  # noqa: BLE001
            pass
        try:
            self._client.destroy()
        except Exception:  # noqa: BLE001
            pass
        self._writer.close()
        return super().destroy_node()


def _state_event(reason_code: str, detail: str):
    """状态恢复/损坏的结构化事件（复用 TaskTransitionEvent 结构，语义由 reason_code 区分）。"""
    return TaskTransitionEvent(
        transition_id='state-{0}'.format(reason_code.lower()),
        previous_task_phase='', next_task_phase='',
        previous_epoch=-1, next_epoch=-1,
        previous_policy_digest='', next_policy_digest='',
        decision=reason_codes.DECISION_ALLOW, reason_code=reason_code,
        transition_at=utc_now_iso(), detail=detail)


def _install_sigterm_handler() -> None:
    def _raise_keyboard_interrupt(signum, frame):  # noqa: ARG001
        raise KeyboardInterrupt
    try:
        signal.signal(signal.SIGTERM, _raise_keyboard_interrupt)
    except (ValueError, OSError):
        pass


def main(argv: Optional[list] = None) -> int:
    _install_sigterm_handler()
    rclpy.init(args=argv)
    try:
        node = SecurityGateway()
    except AuditSinkError as exc:
        print('FATAL audit sink unavailable: {0}'.format(exc), file=sys.stderr, flush=True)
        _safe_shutdown()
        return 2
    except Exception as exc:  # noqa: BLE001
        print('FATAL gateway startup failed: {0}'.format(exc), file=sys.stderr, flush=True)
        _safe_shutdown()
        return 1

    # 4 workers: one may sit blocked inside _on_execute while the remaining
    # workers service this node's ActionClient responses. See module docstring.
    executor = MultiThreadedExecutor(num_threads=EXECUTOR_THREADS)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    except Exception as exc:  # noqa: BLE001
        print('FATAL executor error: {0}'.format(exc), file=sys.stderr, flush=True)
        node.destroy_node()
        _safe_shutdown()
        return 1
    finally:
        try:
            executor.shutdown(timeout_sec=2.0)
        except Exception:  # noqa: BLE001
            pass
        try:
            node.destroy_node()
        except Exception:  # noqa: BLE001
            pass
    _safe_shutdown()
    return 0


def _safe_shutdown() -> None:
    try:
        if rclpy.ok():
            rclpy.shutdown()
    except Exception:  # noqa: BLE001
        pass


if __name__ == '__main__':
    sys.exit(main())
