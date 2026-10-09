"""M3 可信任务状态模型：不可变任务快照、阶段目录、单调 epoch、策略摘要与状态机。

设计约束（对应任务书 C3/C7/C9）
-------------------------------
* **纯 Python**，不依赖 rclpy/ROS：状态机与摘要算法可以脱离 ROS 图独立单元测试，
  这也是"同一策略内容必然得到同一 digest"这一性质能被穷举验证的前提。
* **不可变**：`ActiveTaskSnapshot` 是 frozen dataclass；"切换"是产生新快照，
  而不是修改旧快照，避免并发读到一个半更新状态。
* **digest 只覆盖业务字段**：本地路径、加载时间、进程号等一律不参与摘要，
  否则同一套规则在不同机器/不同时间会算出不同 digest。
* **digest 不是签名**：它只能证明内容关联或检测意外变化，不能抵御拥有写权限的
  恶意主体，也不能替代数字签名。这一点在 README 与报告中都如实声明。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Mapping, Optional, Tuple

from . import reason_codes
from .task_policy import AllowedRegion, PolicySchemaError

STATE_SCHEMA_VERSION = '1.0'

# ---------------------------------------------------------------- 状态机状态
STATE_UNINITIALIZED = 'UNINITIALIZED'
STATE_ACTIVE = 'ACTIVE'
STATE_SWITCHING = 'SWITCHING'
STATE_RECOVERY_REQUIRED = 'RECOVERY_REQUIRED'
TASK_STATES: Tuple[str, ...] = (STATE_UNINITIALIZED, STATE_ACTIVE, STATE_SWITCHING,
                                STATE_RECOVERY_REQUIRED)

# digest 覆盖的业务字段（顺序无关，参与计算前会排序）
DIGEST_FIELDS: Tuple[str, ...] = (
    'task_id', 'task_phase', 'policy_version', 'coordinate_frame',
    'allowed_region', 'max_requests_per_minute', 'active',
)


def _normalize_number(value: float) -> float:
    """把浮点规整到固定精度，避免 1.0 与 1.0000000001 产生不同摘要。"""
    return round(float(value), 6)


def canonical_policy_payload(task_id: str, task_phase: str, policy_version: str,
                             coordinate_frame: str, region: Mapping[str, float],
                             max_requests_per_minute: float, active: bool) -> Dict[str, Any]:
    """构造用于摘要的规范化业务载荷。

    只包含业务规则字段：**不含**文件路径、加载时间、主机名、epoch 或任何环境信息。
    """
    return {
        'active': bool(active),
        'allowed_region': {
            'x_max': _normalize_number(region['x_max']),
            'x_min': _normalize_number(region['x_min']),
            'y_max': _normalize_number(region['y_max']),
            'y_min': _normalize_number(region['y_min']),
        },
        'coordinate_frame': str(coordinate_frame),
        'max_requests_per_minute': _normalize_number(max_requests_per_minute),
        'policy_version': str(policy_version),
        'task_id': str(task_id),
        'task_phase': str(task_phase),
    }


def compute_policy_digest(payload: Mapping[str, Any]) -> str:
    """对规范化业务载荷计算 SHA-256（稳定序列化：键排序 + 紧凑分隔符）。"""
    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':'),
                         ensure_ascii=True).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class TaskPhase:
    """一个可信任务阶段（同一 task_id 下的一套区域/速率规则）。"""

    task_id: str
    task_phase: str
    policy_version: str
    coordinate_frame: str
    region: AllowedRegion
    max_requests_per_minute: float
    active: bool = True

    @property
    def digest(self) -> str:
        return compute_policy_digest(self.payload())

    def payload(self) -> Dict[str, Any]:
        return canonical_policy_payload(
            self.task_id, self.task_phase, self.policy_version, self.coordinate_frame,
            self.region.as_dict(), self.max_requests_per_minute, self.active)

    def as_dict(self) -> Dict[str, Any]:
        return {'task_id': self.task_id, 'task_phase': self.task_phase,
                'policy_version': self.policy_version,
                'coordinate_frame': self.coordinate_frame,
                'allowed_region': self.region.as_dict(),
                'max_requests_per_minute': self.max_requests_per_minute,
                'active': self.active, 'policy_digest': self.digest}


@dataclass(frozen=True)
class ActiveTaskSnapshot:
    """当前生效的不可变任务快照（Gateway 的唯一授权依据）。"""

    task_id: str
    task_phase: str
    policy_version: str
    policy_epoch: int
    policy_digest: str
    coordinate_frame: str
    allowed_region: AllowedRegion
    max_requests_per_minute: float
    active: bool

    def contains(self, x: float, y: float) -> bool:
        return self.allowed_region.contains(x, y)

    def as_dict(self) -> Dict[str, Any]:
        return {
            'task_id': self.task_id,
            'task_phase': self.task_phase,
            'policy_version': self.policy_version,
            'policy_epoch': self.policy_epoch,
            'policy_digest': self.policy_digest,
            'coordinate_frame': self.coordinate_frame,
            'allowed_region': self.allowed_region.as_dict(),
            'max_requests_per_minute': self.max_requests_per_minute,
            'active': self.active,
        }

    @staticmethod
    def from_dict(document: Mapping[str, Any]) -> 'ActiveTaskSnapshot':
        try:
            region_raw = document['allowed_region']
            region = AllowedRegion(
                x_min=float(region_raw['x_min']), x_max=float(region_raw['x_max']),
                y_min=float(region_raw['y_min']), y_max=float(region_raw['y_max']))
            if region.x_min > region.x_max or region.y_min > region.y_max:
                raise PolicySchemaError('allowed_region has min > max')
            snapshot = ActiveTaskSnapshot(
                task_id=str(document['task_id']),
                task_phase=str(document['task_phase']),
                policy_version=str(document['policy_version']),
                policy_epoch=int(document['policy_epoch']),
                policy_digest=str(document['policy_digest']),
                coordinate_frame=str(document['coordinate_frame']),
                allowed_region=region,
                max_requests_per_minute=float(document['max_requests_per_minute']),
                active=bool(document['active']))
        except (KeyError, TypeError, ValueError) as exc:
            raise PolicySchemaError('持久化快照字段非法: {0}'.format(exc)) from exc
        # 自校验：快照声明的 digest 必须与业务字段重算结果一致，
        # 否则说明文件被篡改或写入不完整 —— 此时绝不能"照单全收"。
        expected = snapshot.recompute_digest()
        if expected != snapshot.policy_digest:
            raise PolicySchemaError(
                '快照 digest 与内容不一致（声明 {0}，重算 {1}）'.format(
                    snapshot.policy_digest[:16], expected[:16]))
        return snapshot

    def recompute_digest(self) -> str:
        return compute_policy_digest(canonical_policy_payload(
            self.task_id, self.task_phase, self.policy_version, self.coordinate_frame,
            self.allowed_region.as_dict(), self.max_requests_per_minute, self.active))

    @staticmethod
    def from_phase(phase: TaskPhase, epoch: int) -> 'ActiveTaskSnapshot':
        if epoch < 0:
            raise ValueError('policy_epoch must be >= 0, got {0}'.format(epoch))
        return ActiveTaskSnapshot(
            task_id=phase.task_id, task_phase=phase.task_phase,
            policy_version=phase.policy_version, policy_epoch=epoch,
            policy_digest=phase.digest, coordinate_frame=phase.coordinate_frame,
            allowed_region=phase.region,
            max_requests_per_minute=phase.max_requests_per_minute, active=phase.active)


def parse_task_phases(document: Mapping[str, Any]) -> Dict[str, TaskPhase]:
    """从策略文档解析 `task_phases` 段（M3）。条目不合法即失败关闭。"""
    raw_phases = document.get('task_phases')
    if raw_phases is None:
        return {}
    if not isinstance(raw_phases, Mapping):
        raise PolicySchemaError('task_phases must be a mapping')
    task_id = str(document.get('task_id', ''))
    frame = str(document.get('coordinate_frame', ''))
    version = str(document.get('policy_version', ''))
    phases: Dict[str, TaskPhase] = {}
    for name, raw in raw_phases.items():
        if not isinstance(raw, Mapping):
            raise PolicySchemaError('task_phases.{0} must be a mapping'.format(name))
        region_raw = raw.get('allowed_region')
        if not isinstance(region_raw, Mapping):
            raise PolicySchemaError('task_phases.{0}.allowed_region missing'.format(name))
        try:
            region = AllowedRegion(
                x_min=float(region_raw['x_min']), x_max=float(region_raw['x_max']),
                y_min=float(region_raw['y_min']), y_max=float(region_raw['y_max']))
        except (KeyError, TypeError, ValueError) as exc:
            raise PolicySchemaError(
                'task_phases.{0}.allowed_region 非法: {1}'.format(name, exc)) from exc
        if region.x_min > region.x_max or region.y_min > region.y_max:
            raise PolicySchemaError(
                'task_phases.{0}.allowed_region 出现 min > max'.format(name))
        rate = raw.get('max_requests_per_minute',
                       document.get('max_requests_per_minute', 0))
        try:
            rate = float(rate)
        except (TypeError, ValueError) as exc:
            raise PolicySchemaError(
                'task_phases.{0}.max_requests_per_minute 非法'.format(name)) from exc
        if rate <= 0:
            raise PolicySchemaError(
                'task_phases.{0}.max_requests_per_minute 必须 > 0'.format(name))
        phases[str(name)] = TaskPhase(
            task_id=str(raw.get('task_id', task_id)),
            task_phase=str(name),
            policy_version=str(raw.get('policy_version', version)),
            coordinate_frame=str(raw.get('coordinate_frame', frame)),
            region=region, max_requests_per_minute=rate,
            active=bool(raw.get('active', True)))
    return phases


@dataclass
class TransitionPlan:
    """已通过全部前置校验、等待持久化的切换计划。"""

    transition_id: str
    target: TaskPhase
    previous: Optional[ActiveTaskSnapshot]
    next_epoch: int
    accepted: bool
    reason_code: str
    detail: str = ''
    checks: List[Dict[str, str]] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {'transition_id': self.transition_id,
                'target_task_id': self.target.task_id if self.target else None,
                'target_task_phase': self.target.task_phase if self.target else None,
                'previous_epoch': self.previous.policy_epoch if self.previous else None,
                'next_epoch': self.next_epoch,
                'accepted': self.accepted, 'reason_code': self.reason_code,
                'detail': self.detail, 'checks': self.checks}


class TaskStateMachine:
    """可信任务状态机：UNINITIALIZED → ACTIVE ⇄ SWITCHING → RECOVERY_REQUIRED。

    状态与持久化解耦：本类只负责"在内存中一致地迁移状态"，落盘由 Gateway 负责。
    调用顺序固定为 `request_transition()` → 持久化 → `commit()`；
    任何一步失败都调用 `abort()`，旧快照保持生效，**绝不暴露未提交的新权限**。
    """

    def __init__(self, phases: Mapping[str, TaskPhase], initial_phase: str,
                 initial_epoch: int = 0):
        if initial_phase not in phases:
            raise PolicySchemaError(
                '初始阶段 {0!r} 不在 task_phases 中（可信配置缺失，拒绝启动）'.format(
                    initial_phase))
        self._phases = dict(phases)
        self._initial_phase = initial_phase
        self._state = STATE_ACTIVE
        self._snapshot: Optional[ActiveTaskSnapshot] = ActiveTaskSnapshot.from_phase(
            self._phases[initial_phase], initial_epoch)
        self._used_transition_ids: Dict[str, str] = {}
        self._last_transition_id: Optional[str] = None
        self._pending: Optional[TransitionPlan] = None

    # ------------------------------------------------------------ 只读访问
    @property
    def state(self) -> str:
        return self._state

    @property
    def snapshot(self) -> Optional[ActiveTaskSnapshot]:
        return self._snapshot

    @property
    def used_transition_ids(self) -> Dict[str, str]:
        return dict(self._used_transition_ids)

    @property
    def last_transition_id(self) -> Optional[str]:
        return self._last_transition_id

    def phases(self) -> Dict[str, TaskPhase]:
        return dict(self._phases)

    def restore(self, snapshot: ActiveTaskSnapshot, used_transition_ids: Mapping[str, str],
                state: str = STATE_ACTIVE):
        """从持久化状态恢复。快照内容与阶段目录不一致时进入限制性故障状态。"""
        phase = self._phases.get(snapshot.task_phase)
        if phase is None:
            self._state = STATE_RECOVERY_REQUIRED
            raise PolicySchemaError(
                '持久化阶段 {0!r} 已不在可信配置中'.format(snapshot.task_phase))
        if phase.digest != snapshot.policy_digest:
            # 策略内容变了而 epoch 没变：说明配置被改动或文件损坏。
            # 不能静默接受，也不能回退到旧的宽松权限 —— 进入 RECOVERY_REQUIRED。
            self._state = STATE_RECOVERY_REQUIRED
            raise PolicySchemaError(
                '持久化 digest 与当前策略不一致（{0} != {1}）'.format(
                    snapshot.policy_digest[:16], phase.digest[:16]))
        if state not in TASK_STATES:
            state = STATE_RECOVERY_REQUIRED
        self._snapshot = snapshot
        self._used_transition_ids = dict(used_transition_ids)
        self._state = state
        return snapshot

    def mark_recovery_required(self, detail: str = ''):
        """进入限制性故障状态：保持最后已提交快照，但不接受切换、不放大权限。"""
        self._state = STATE_RECOVERY_REQUIRED
        self._pending = None
        self._recovery_detail = detail

    # ------------------------------------------------------------ 切换
    def request_transition(self, transition_id: str, target_task_id: str,
                           target_task_phase: str, expected_epoch: int,
                           in_flight_goal_count: int) -> TransitionPlan:
        """按 C5 的顺序执行全部前置校验。任何一项不过都返回未接受的计划。"""
        checks: List[Dict[str, str]] = []

        def fail(reason: str, detail: str) -> TransitionPlan:
            checks.append({'check': reason, 'result': 'FAIL', 'detail': detail})
            return TransitionPlan(transition_id=transition_id, target=None,
                                  previous=self._snapshot, next_epoch=-1,
                                  accepted=False, reason_code=reason,
                                  detail=detail, checks=checks)

        def ok(name: str, detail: str):
            checks.append({'check': name, 'result': 'PASS', 'detail': detail})

        if not transition_id:
            return fail(reason_codes.TRANSITION_REJECTED_INVALID_POLICY,
                        'transition_id 不能为空')
        ok('transition_id_present', transition_id)

        if self._state != STATE_ACTIVE or self._snapshot is None:
            return fail(reason_codes.TRANSITION_REJECTED_NOT_ACTIVE,
                        '当前状态 {0} 不接受切换'.format(self._state))
        ok('state_active', self._state)

        phase = self._phases.get(target_task_phase)
        if phase is None or phase.task_id != target_task_id:
            return fail(reason_codes.TRANSITION_REJECTED_UNKNOWN_TASK,
                        '目标任务/阶段不在可信配置中: {0}/{1}'.format(
                            target_task_id, target_task_phase))
        ok('target_in_catalog', '{0}/{1}'.format(phase.task_id, phase.task_phase))

        if int(expected_epoch) != self._snapshot.policy_epoch:
            return fail(reason_codes.TRANSITION_REJECTED_EPOCH_MISMATCH,
                        'expected_epoch={0} 与当前 epoch={1} 不一致'.format(
                            expected_epoch, self._snapshot.policy_epoch))
        ok('epoch_matches', str(self._snapshot.policy_epoch))

        if transition_id in self._used_transition_ids:
            return fail(reason_codes.TRANSITION_REJECTED_REPLAY,
                        'transition_id 已被使用（重放）: {0}'.format(transition_id))
        ok('transition_id_unused', transition_id)

        if in_flight_goal_count > 0:
            return fail(reason_codes.TRANSITION_REJECTED_IN_FLIGHT,
                        '存在 {0} 个在途/状态未知的 Goal，拒绝切换'.format(in_flight_goal_count))
        ok('no_in_flight_goals', '0')

        if not phase.active:
            return fail(reason_codes.TRANSITION_REJECTED_INVALID_POLICY,
                        '目标阶段 active=false')
        ok('target_policy_valid', phase.digest[:16])

        plan = TransitionPlan(transition_id=transition_id, target=phase,
                              previous=self._snapshot,
                              next_epoch=self._snapshot.policy_epoch + 1,
                              accepted=True,
                              reason_code=reason_codes.TRANSITION_ACCEPTED,
                              detail='校验通过，等待持久化后提交', checks=checks)
        self._state = STATE_SWITCHING
        self._pending = plan
        return plan

    def commit(self, plan: TransitionPlan) -> ActiveTaskSnapshot:
        """持久化成功后原子切换有效快照并递增 epoch。"""
        if not plan.accepted or plan.target is None:
            raise ValueError('不能提交未接受的切换计划')
        if self._state != STATE_SWITCHING or self._pending is None:
            raise ValueError('当前状态 {0} 不允许提交切换'.format(self._state))
        if plan.transition_id != self._pending.transition_id:
            raise ValueError('提交的切换计划与待提交计划不一致')
        # epoch 单调递增：每次成功切换 +1，且只能从上一快照推导
        if self._snapshot is None or plan.next_epoch != self._snapshot.policy_epoch + 1:
            raise ValueError('epoch 非单调递增，拒绝提交')
        snapshot = ActiveTaskSnapshot.from_phase(plan.target, plan.next_epoch)
        self._snapshot = snapshot
        self._used_transition_ids[plan.transition_id] = snapshot.policy_digest
        self._last_transition_id = plan.transition_id
        self._state = STATE_ACTIVE
        self._pending = None
        return snapshot

    def abort(self, detail: str = '', recovery: bool = False):
        """切换失败：保留旧快照；必要时进入限制性故障状态。

        无论哪条路径都不会把"尚未提交的新权限"暴露出去。
        """
        self._pending = None
        self._state = STATE_RECOVERY_REQUIRED if recovery else STATE_ACTIVE
        self._abort_detail = detail
        return self._snapshot


@dataclass(frozen=True)
class TaskTransitionEvent:
    """结构化任务切换事件（C10）。"""

    transition_id: str
    previous_task_phase: str
    next_task_phase: str
    previous_epoch: int
    next_epoch: int
    previous_policy_digest: str
    next_policy_digest: str
    decision: str
    reason_code: str
    transition_at: str
    detail: str = ''

    EVENT_TYPE = 'TaskTransitionEvent'

    def to_dict(self) -> Dict[str, Any]:
        return {
            'event_type': self.EVENT_TYPE,
            'transition_id': self.transition_id,
            'previous_task_phase': self.previous_task_phase,
            'next_task_phase': self.next_task_phase,
            'previous_epoch': self.previous_epoch,
            'next_epoch': self.next_epoch,
            'previous_policy_digest': self.previous_policy_digest,
            'next_policy_digest': self.next_policy_digest,
            'decision': self.decision,
            'reason_code': self.reason_code,
            'transition_at': self.transition_at,
            'detail': self.detail,
        }
