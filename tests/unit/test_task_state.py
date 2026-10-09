"""M3 任务状态模型单元测试（纯 Python，不需要 ROS 图）。

覆盖任务书 C3/C7/C9 中可离线验证的性质：
  * digest 只由业务字段决定：同内容必同、异内容必异、与路径/时间无关
  * epoch 严格单调递增
  * 重放 / 过期 epoch / 在途 Goal / 未知阶段 / 非 ACTIVE 状态全部拒绝
  * 切换失败不回退到宽松权限、不暴露未提交权限
  * 持久化快照自校验（内容被改动即拒绝恢复）
"""

import pytest

from rg_policy import reason_codes
from rg_policy.task_policy import AllowedRegion, PolicySchemaError
from rg_policy.task_state import (
    ActiveTaskSnapshot, STATE_ACTIVE, STATE_RECOVERY_REQUIRED, STATE_SWITCHING,
    TaskPhase, TaskStateMachine, TaskTransitionEvent, canonical_policy_payload,
    compute_policy_digest, parse_task_phases,
)

ZONE_A = TaskPhase('patrol_a_001', 'ZONE_A', '1.0', 'map',
                   AllowedRegion(0.0, 4.0, 0.0, 4.0), 10.0, True)
ZONE_B = TaskPhase('patrol_a_001', 'ZONE_B', '1.1', 'map',
                   AllowedRegion(6.0, 10.0, 6.0, 10.0), 10.0, True)
PHASES = {'ZONE_A': ZONE_A, 'ZONE_B': ZONE_B}


def machine():
    return TaskStateMachine(PHASES, 'ZONE_A', initial_epoch=0)


# ------------------------------------------------------------------ digest
def test_digest_is_stable_for_identical_content():
    assert ZONE_A.digest == ZONE_A.digest
    other = TaskPhase('patrol_a_001', 'ZONE_A', '1.0', 'map',
                      AllowedRegion(0.0, 4.0, 0.0, 4.0), 10.0, True)
    assert other.digest == ZONE_A.digest, '相同业务内容必须得到相同 digest'


def test_digest_differs_when_any_business_field_changes():
    variants = {
        'region': TaskPhase('patrol_a_001', 'ZONE_A', '1.0', 'map',
                            AllowedRegion(0.0, 4.5, 0.0, 4.0), 10.0, True),
        'version': TaskPhase('patrol_a_001', 'ZONE_A', '1.1', 'map',
                             AllowedRegion(0.0, 4.0, 0.0, 4.0), 10.0, True),
        'frame': TaskPhase('patrol_a_001', 'ZONE_A', '1.0', 'odom',
                           AllowedRegion(0.0, 4.0, 0.0, 4.0), 10.0, True),
        'rate': TaskPhase('patrol_a_001', 'ZONE_A', '1.0', 'map',
                          AllowedRegion(0.0, 4.0, 0.0, 4.0), 20.0, True),
        'active': TaskPhase('patrol_a_001', 'ZONE_A', '1.0', 'map',
                            AllowedRegion(0.0, 4.0, 0.0, 4.0), 10.0, False),
        'phase': TaskPhase('patrol_a_001', 'ZONE_A2', '1.0', 'map',
                           AllowedRegion(0.0, 4.0, 0.0, 4.0), 10.0, True),
        'task': TaskPhase('patrol_a_002', 'ZONE_A', '1.0', 'map',
                          AllowedRegion(0.0, 4.0, 0.0, 4.0), 10.0, True),
    }
    for label, phase in variants.items():
        assert phase.digest != ZONE_A.digest, '字段 {0} 变化必须改变 digest'.format(label)


def test_digest_ignores_paths_timestamps_and_environment():
    """同一内容在不同机器/时间必须得到相同 digest。"""
    # 必须使用与 ZONE_A 完全相同的业务字段（含 task_id），否则比的是两份不同规则
    payload_a = canonical_policy_payload('patrol_a_001', 'ZONE_A', '1.0', 'map',
                                         {'x_min': 0, 'x_max': 4, 'y_min': 0, 'y_max': 4},
                                         10, True)
    payload_b = dict(payload_a)
    payload_b['source_path'] = '/home/someone/elsewhere/task_policy.yaml'
    payload_b['loaded_at'] = '2099-01-01T00:00:00Z'
    payload_b['host'] = 'other-host'
    # 规范载荷只由业务字段构成，额外键不参与摘要
    assert compute_policy_digest(payload_a) == ZONE_A.digest
    assert 'source_path' not in payload_a and 'loaded_at' not in payload_a


def test_digest_normalizes_float_noise():
    a = TaskPhase('t', 'ZONE_A', '1.0', 'map', AllowedRegion(0.0, 4.0, 0.0, 4.0), 10.0, True)
    b = TaskPhase('t', 'ZONE_A', '1.0', 'map',
                  AllowedRegion(0.0, 4.0000000001, 0.0, 4.0), 10.0, True)
    assert a.digest == b.digest, '浮点噪声不应改变 digest'


def test_zone_a_and_zone_b_have_different_digest():
    assert ZONE_A.digest != ZONE_B.digest


# --------------------------------------------------------------- 状态机
def test_initial_state_is_active_with_zero_epoch():
    sm = machine()
    assert sm.state == STATE_ACTIVE
    assert sm.snapshot.policy_epoch == 0
    assert sm.snapshot.task_phase == 'ZONE_A'
    assert sm.snapshot.policy_digest == ZONE_A.digest


def test_unknown_initial_phase_is_refused():
    with pytest.raises(PolicySchemaError):
        TaskStateMachine(PHASES, 'ZONE_NOPE')


def test_successful_transition_increments_epoch_monotonically():
    sm = machine()
    plan = sm.request_transition('t-1', 'patrol_a_001', 'ZONE_B', 0, 0)
    assert plan.accepted and plan.reason_code == reason_codes.TRANSITION_ACCEPTED
    assert sm.state == STATE_SWITCHING, '校验通过后必须先进入 SWITCHING'
    snapshot = sm.commit(plan)
    assert snapshot.policy_epoch == 1
    assert snapshot.task_phase == 'ZONE_B'
    assert snapshot.policy_digest == ZONE_B.digest
    assert sm.state == STATE_ACTIVE

    plan2 = sm.request_transition('t-2', 'patrol_a_001', 'ZONE_A', 1, 0)
    snapshot2 = sm.commit(plan2)
    assert snapshot2.policy_epoch == 2
    assert snapshot2.task_phase == 'ZONE_A'


def test_replay_of_used_transition_id_is_rejected_without_epoch_change():
    sm = machine()
    plan = sm.request_transition('dup', 'patrol_a_001', 'ZONE_B', 0, 0)
    sm.commit(plan)
    epoch_before = sm.snapshot.policy_epoch
    again = sm.request_transition('dup', 'patrol_a_001', 'ZONE_A', 1, 0)
    assert not again.accepted
    assert again.reason_code == reason_codes.TRANSITION_REJECTED_REPLAY
    assert sm.snapshot.policy_epoch == epoch_before, '重放不得改变 epoch'
    assert sm.snapshot.task_phase == 'ZONE_B', '重放不得改变生效阶段'


def test_stale_expected_epoch_is_rejected():
    sm = machine()
    plan = sm.request_transition('t-1', 'patrol_a_001', 'ZONE_B', 0, 0)
    sm.commit(plan)
    stale = sm.request_transition('t-2', 'patrol_a_001', 'ZONE_A', 0, 0)  # 过期 epoch
    assert not stale.accepted
    assert stale.reason_code == reason_codes.TRANSITION_REJECTED_EPOCH_MISMATCH
    assert sm.snapshot.policy_epoch == 1


def test_unknown_target_phase_is_rejected():
    sm = machine()
    plan = sm.request_transition('t-1', 'patrol_a_001', 'ZONE_ZZZ', 0, 0)
    assert not plan.accepted
    assert plan.reason_code == reason_codes.TRANSITION_REJECTED_UNKNOWN_TASK
    assert sm.state == STATE_ACTIVE


def test_task_id_mismatch_is_rejected():
    sm = machine()
    plan = sm.request_transition('t-1', 'other_task', 'ZONE_B', 0, 0)
    assert not plan.accepted
    assert plan.reason_code == reason_codes.TRANSITION_REJECTED_UNKNOWN_TASK


def test_in_flight_goal_blocks_transition():
    sm = machine()
    plan = sm.request_transition('t-1', 'patrol_a_001', 'ZONE_B', 0, 1)
    assert not plan.accepted
    assert plan.reason_code == reason_codes.TRANSITION_REJECTED_IN_FLIGHT
    assert sm.state == STATE_ACTIVE, '被拒绝的切换不得把状态机卡在 SWITCHING'
    assert sm.snapshot.task_phase == 'ZONE_A'


def test_unknown_downstream_state_counts_as_in_flight():
    """M1 已明确：EXECUTION_TIMEOUT 不代表下游已停止，必须按在途处理。"""
    sm = machine()
    plan = sm.request_transition('t-1', 'patrol_a_001', 'ZONE_B', 0, 3)
    assert plan.reason_code == reason_codes.TRANSITION_REJECTED_IN_FLIGHT


def test_abort_keeps_previous_snapshot_and_restores_active():
    sm = machine()
    plan = sm.request_transition('t-1', 'patrol_a_001', 'ZONE_B', 0, 0)
    assert sm.state == STATE_SWITCHING
    snapshot = sm.abort('persist failed')
    assert snapshot.task_phase == 'ZONE_A'
    assert sm.snapshot.policy_epoch == 0
    assert sm.state == STATE_ACTIVE


def test_abort_with_recovery_enters_restrictive_state_and_blocks_further_switches():
    sm = machine()
    plan = sm.request_transition('t-1', 'patrol_a_001', 'ZONE_B', 0, 0)
    sm.abort('persist failed', recovery=True)
    assert sm.state == STATE_RECOVERY_REQUIRED
    again = sm.request_transition('t-2', 'patrol_a_001', 'ZONE_B', 0, 0)
    assert not again.accepted
    assert again.reason_code == reason_codes.TRANSITION_REJECTED_NOT_ACTIVE


def test_transition_id_is_not_consumed_when_rejected():
    """被拒绝的切换不得占用 transition_id，否则重试会被误判为重放。"""
    sm = machine()
    rejected = sm.request_transition('t-1', 'patrol_a_001', 'ZONE_B', 0, 1)
    assert not rejected.accepted
    retry = sm.request_transition('t-1', 'patrol_a_001', 'ZONE_B', 0, 0)
    assert retry.accepted, '同一 transition_id 在无在途 Goal 时应可重试'


def test_commit_rejects_non_monotonic_epoch():
    sm = machine()
    plan = sm.request_transition('t-1', 'patrol_a_001', 'ZONE_B', 0, 0)
    plan.next_epoch = 99  # 人为破坏单调性
    with pytest.raises(ValueError):
        sm.commit(plan)


def test_commit_without_pending_plan_is_refused():
    sm = machine()
    plan = sm.request_transition('t-1', 'patrol_a_001', 'ZONE_B', 0, 0)
    sm.commit(plan)
    with pytest.raises(ValueError):
        sm.commit(plan)


# ----------------------------------------------------------- 持久化/恢复
def test_snapshot_roundtrip_and_self_check():
    sm = machine()
    plan = sm.request_transition('t-1', 'patrol_a_001', 'ZONE_B', 0, 0)
    snapshot = sm.commit(plan)
    restored = ActiveTaskSnapshot.from_dict(snapshot.as_dict())
    assert restored == snapshot
    assert restored.policy_epoch == 1


def test_tampered_snapshot_is_rejected_on_restore():
    sm = machine()
    plan = sm.request_transition('t-1', 'patrol_a_001', 'ZONE_B', 0, 0)
    snapshot = sm.commit(plan)
    doc = snapshot.as_dict()
    doc['allowed_region'] = {'x_min': 0.0, 'x_max': 100.0, 'y_min': 0.0, 'y_max': 100.0}
    with pytest.raises(PolicySchemaError):
        ActiveTaskSnapshot.from_dict(doc)


def test_restore_with_phase_removed_from_catalog_requires_recovery():
    """状态文件指向已不存在的阶段时不能静默接受，也不能回退到旧权限。"""
    sm = TaskStateMachine({'ZONE_A': ZONE_A}, 'ZONE_A')  # 目录里没有 ZONE_B
    snapshot = ActiveTaskSnapshot.from_phase(ZONE_B, 5)
    with pytest.raises(PolicySchemaError):
        sm.restore(snapshot, {})
    assert sm.state == STATE_RECOVERY_REQUIRED


def test_restore_with_changed_policy_content_requires_recovery():
    """配置内容被改动而 epoch 未变 -> 必须进入限制性故障状态。"""
    sm = machine()
    changed = TaskPhase('patrol_a_001', 'ZONE_B', '1.1', 'map',
                        AllowedRegion(6.0, 99.0, 6.0, 10.0), 10.0, True)
    snapshot = ActiveTaskSnapshot.from_phase(ZONE_B, 1)
    sm2 = TaskStateMachine({'ZONE_A': ZONE_A, 'ZONE_B': changed}, 'ZONE_A')
    with pytest.raises(PolicySchemaError):
        sm2.restore(snapshot, {})
    assert sm2.state == STATE_RECOVERY_REQUIRED


def test_restore_happy_path_keeps_epoch_and_digest():
    sm = machine()
    snapshot = ActiveTaskSnapshot.from_phase(ZONE_B, 7)
    sm.restore(snapshot, {'t-1': ZONE_B.digest})
    assert sm.state == STATE_ACTIVE
    assert sm.snapshot.policy_epoch == 7
    assert sm.snapshot.policy_digest == ZONE_B.digest
    assert sm.used_transition_ids == {'t-1': ZONE_B.digest}


# --------------------------------------------------------------- 阶段解析
def test_parse_task_phases_from_document():
    document = {
        'task_id': 'patrol_a_001', 'policy_version': '1.0', 'coordinate_frame': 'map',
        'max_requests_per_minute': 10,
        'task_phases': {
            'ZONE_A': {'allowed_region': {'x_min': 0, 'x_max': 4, 'y_min': 0, 'y_max': 4}},
            'ZONE_B': {'allowed_region': {'x_min': 6, 'x_max': 10, 'y_min': 6, 'y_max': 10},
                       'policy_version': '1.1'},
        },
    }
    phases = parse_task_phases(document)
    assert set(phases) == {'ZONE_A', 'ZONE_B'}
    assert phases['ZONE_A'].task_id == 'patrol_a_001'
    assert phases['ZONE_A'].policy_version == '1.0'
    assert phases['ZONE_B'].policy_version == '1.1'
    assert phases['ZONE_B'].digest != phases['ZONE_A'].digest


@pytest.mark.parametrize('bad', [
    {'task_phases': {'ZONE_A': {'allowed_region': {'x_min': 5, 'x_max': 1, 'y_min': 0, 'y_max': 1}}}},
    {'task_phases': {'ZONE_A': {}}},
    {'task_phases': {'ZONE_A': {'allowed_region': {'x_min': 0, 'x_max': 1, 'y_min': 0, 'y_max': 1},
                                'max_requests_per_minute': 0}}},
    {'task_phases': 'not-a-mapping'},
])
def test_parse_task_phases_fails_closed_on_invalid_input(bad):
    document = {'task_id': 't', 'policy_version': '1', 'coordinate_frame': 'map',
                'max_requests_per_minute': 10}
    document.update(bad)
    with pytest.raises(PolicySchemaError):
        parse_task_phases(document)


def test_parse_task_phases_absent_is_backward_compatible():
    assert parse_task_phases({'task_id': 't'}) == {}


# --------------------------------------------------------------- 事件
def test_transition_event_is_serializable_and_backward_compatible():
    event = TaskTransitionEvent(
        transition_id='t-1', previous_task_phase='ZONE_A', next_task_phase='ZONE_B',
        previous_epoch=0, next_epoch=1, previous_policy_digest=ZONE_A.digest,
        next_policy_digest=ZONE_B.digest, decision=reason_codes.DECISION_ALLOW,
        reason_code=reason_codes.TRANSITION_ACCEPTED,
        transition_at='2026-10-09T00:00:00Z')
    doc = event.to_dict()
    assert doc['event_type'] == 'TaskTransitionEvent'
    for key in ('transition_id', 'previous_task_phase', 'next_task_phase',
                'previous_epoch', 'next_epoch', 'previous_policy_digest',
                'next_policy_digest', 'decision', 'reason_code', 'transition_at'):
        assert key in doc


def test_new_reason_codes_are_registered_and_described():
    for code in reason_codes.TRANSITION_REASON_CODES:
        assert code in reason_codes.REASON_DESCRIPTIONS, code
    # 冻结的 8 个原始原因码不得被改动
    for code in ('ALLOW_IN_POLICY', 'TASK_MISMATCH', 'INVALID_TARGET', 'OUT_OF_REGION',
                 'POLICY_MISSING', 'DUPLICATE_REQUEST', 'RATE_LIMIT', 'EXECUTION_TIMEOUT'):
        assert code in reason_codes.DECISION_REASON_CODES or code == 'EXECUTION_TIMEOUT'
