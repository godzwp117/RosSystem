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
import signal
import sys
import time
from typing import Any, Dict, Optional

import rclpy
from rclpy.action import ActionClient, ActionServer
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from rg_interfaces.action import PatrolNavigate
from rg_policy import reason_codes
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
from rg_policy.task_policy import PolicyProvider

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

        # Fail fast: an unwritable audit sink must stop the Gateway rather than
        # let it run without an audit trail.
        self._audit_log_path = os.path.abspath(str(audit_log_path))
        self._writer = EventWriter(self._audit_log_path, fsync=self.audit_fsync)

        self._policy_provider = PolicyProvider(str(policy_path))
        self._tracker = RequestTracker(
            duplicate_ttl_sec=duplicate_ttl_sec, rate_window_sec=rate_window_sec)
        self._audit_failures = 0
        self._blocked_count = 0
        self._allowed_count = 0
        self._forwarded_count = 0

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

        policy, policy_error = self._policy_provider.current()
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
    def _write_event(self, event: Any) -> bool:
        """Persist one audit record. Returns False when the sink is unusable."""
        try:
            self._writer.write(event)
        except Exception as exc:  # noqa: BLE001 - audit failure must never crash silently
            self._audit_failures += 1
            self.get_logger().error('AUDIT_WRITE_FAILED ' + json.dumps({
                'event_type': getattr(event, 'EVENT_TYPE', 'unknown'),
                'event_id': getattr(event, 'event_id', 'unknown'),
                'audit_log_path': self._audit_log_path,
                'error': str(exc),
                'effect': 'fail closed: the request will not be forwarded',
            }, ensure_ascii=False))
            return False
        return True

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

        # 4. Pure synchronous decision.
        request = NavRequest(
            request_id=request_id, task_id=task_id, frame_id=frame_id, x=x, y=y, z=z)
        decision = evaluate(request, policy)

        if decision.allowed and is_duplicate:
            decision = Decision(
                decision=reason_codes.DECISION_BLOCK,
                reason_code=reason_codes.DUPLICATE_REQUEST,
                detail='request_id {0!r} was already received within the duplicate window'.format(
                    request_id),
                policy_version=decision.policy_version,
            )
        elif decision.allowed and not self._tracker.admit(
                now_monotonic, policy.max_requests_per_minute):
            decision = Decision(
                decision=reason_codes.DECISION_BLOCK,
                reason_code=reason_codes.RATE_LIMIT,
                detail='more than {0} admitted requests within {1}s'.format(
                    policy.max_requests_per_minute, self._tracker.snapshot()['rate_window_sec']),
                policy_version=decision.policy_version,
            )

        if not comm_event_written:
            decision = Decision(
                decision=reason_codes.DECISION_BLOCK,
                reason_code=reason_codes.AUDIT_UNAVAILABLE,
                detail='audit sink {0} is unwritable; failing closed'.format(self._audit_log_path),
                policy_version=decision.policy_version,
            )

        self._write_event(DecisionEvent(
            event_id=event_id,
            request_id=request_id,
            task_id=task_id,
            policy_version=decision.policy_version,
            decision=decision.decision,
            reason_code=decision.reason_code,
            detail=decision.detail,
            decision_at=utc_now_iso(),
        ))

        # 5. BLOCK: return the business result and never touch the downstream client.
        if not decision.allowed:
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
        return self._forward(goal_handle, event_id, request_id, task_id, target)

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
            return self._finish_failure(
                goal_handle, event_id, request_id, task_id, downstream_goal_id,
                reason_codes.EXECUTION_TIMEOUT, str(exc), forwarded)
        except Exception as exc:  # noqa: BLE001 - transport failure is fail-closed
            return self._finish_failure(
                goal_handle, event_id, request_id, task_id, downstream_goal_id,
                reason_codes.EXECUTION_TIMEOUT,
                'downstream Goal could not be sent: {0}'.format(exc), forwarded)

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
            self._try_cancel(downstream_handle)
            return self._finish_failure(
                goal_handle, event_id, request_id, task_id, downstream_goal_id,
                reason_codes.EXECUTION_TIMEOUT, str(exc), forwarded)
        except Exception as exc:  # noqa: BLE001
            return self._finish_failure(
                goal_handle, event_id, request_id, task_id, downstream_goal_id,
                reason_codes.EXECUTION_FAILED,
                'downstream result unavailable: {0}'.format(exc), forwarded)

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
        ))

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
                        forwarded: bool) -> PatrolNavigate.Result:
        """Fail-closed completion: no Result is invented, the failure is audited."""
        self._write_event(ExecutionEvent(
            event_id=event_id,
            request_id=request_id,
            task_id=task_id,
            downstream_goal_id=downstream_goal_id,
            success=False,
            status_code=status_code,
            detail=detail,
            finished_at=utc_now_iso(),
        ))
        self.get_logger().error('EXECUTION_FAILURE ' + json.dumps({
            'event_id': event_id,
            'request_id': request_id,
            'downstream_goal_id': downstream_goal_id,
            'status_code': status_code,
            'forwarded': forwarded,
            'detail': detail,
        }, ensure_ascii=False))
        goal_handle.abort()
        return PatrolNavigate.Result(success=False, status_code=status_code, detail=detail)

    def _try_cancel(self, downstream_handle: Any) -> None:
        try:
            downstream_handle.cancel_goal_async()
        except Exception:  # noqa: BLE001 - best effort only
            pass

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
