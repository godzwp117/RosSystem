"""M3 状态持久化单元测试（C9）：原子替换、损坏检测、恢复规则。"""

import json
import os

import pytest

from rg_policy.state_store import STATE_FILENAME, StateStoreError, TaskStateStore
from rg_policy.task_policy import AllowedRegion
from rg_policy.task_state import (
    ActiveTaskSnapshot, STATE_ACTIVE, STATE_RECOVERY_REQUIRED, STATE_SCHEMA_VERSION,
    TaskPhase, TaskStateMachine,
)

ZONE_A = TaskPhase('patrol_a_001', 'ZONE_A', '1.0', 'map',
                   AllowedRegion(0.0, 4.0, 0.0, 4.0), 10.0, True)
ZONE_B = TaskPhase('patrol_a_001', 'ZONE_B', '1.1', 'map',
                   AllowedRegion(6.0, 10.0, 6.0, 10.0), 10.0, True)
PHASES = {'ZONE_A': ZONE_A, 'ZONE_B': ZONE_B}


def make(tmp_path):
    path = os.path.join(str(tmp_path), STATE_FILENAME)
    return TaskStateStore(path), path


def test_missing_file_is_cold_start_not_error(tmp_path):
    store, _ = make(tmp_path)
    snapshot, used, state = store.load()
    assert snapshot is None and used == {} and state == STATE_ACTIVE


def test_commit_then_load_roundtrip(tmp_path):
    store, _ = make(tmp_path)
    sm = TaskStateMachine(PHASES, 'ZONE_A')
    plan = sm.request_transition('t-1', 'patrol_a_001', 'ZONE_B', 0, 0)
    ok, detail = store.commit(plan, sm)
    assert ok, detail
    snapshot, used, state = store.load()
    assert snapshot.policy_epoch == 1
    assert snapshot.task_phase == 'ZONE_B'
    assert snapshot.policy_digest == ZONE_B.digest
    assert used == {'t-1': ZONE_B.digest}
    assert state == STATE_ACTIVE


def test_commit_leaves_no_temp_files(tmp_path):
    store, _ = make(tmp_path)
    sm = TaskStateMachine(PHASES, 'ZONE_A')
    store.commit(sm.request_transition('t-1', 'patrol_a_001', 'ZONE_B', 0, 0), sm)
    leftovers = [name for name in os.listdir(str(tmp_path)) if name.startswith('.task_state_')]
    assert leftovers == [], '原子替换后不应残留临时文件'


def test_commit_is_atomic_reader_never_sees_partial(tmp_path):
    """写入后文件必须是完整合法 JSON（不存在写一半被读到的可能）。"""
    store, path = make(tmp_path)
    sm = TaskStateMachine(PHASES, 'ZONE_A')
    store.commit(sm.request_transition('t-1', 'patrol_a_001', 'ZONE_B', 0, 0), sm)
    with open(path, encoding='utf-8') as handle:
        document = json.load(handle)
    assert document['state_schema_version'] == STATE_SCHEMA_VERSION
    assert document['snapshot']['task_phase'] == 'ZONE_B'


def test_corrupt_file_raises_state_store_error(tmp_path):
    store, path = make(tmp_path)
    with open(path, 'w', encoding='utf-8') as handle:
        handle.write('{not json at all')
    with pytest.raises(StateStoreError):
        store.load()


def test_schema_version_mismatch_is_rejected(tmp_path):
    store, path = make(tmp_path)
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump({'state_schema_version': '0.0', 'state': 'ACTIVE',
                   'snapshot': {}}, handle)
    with pytest.raises(StateStoreError):
        store.load()


def test_tampered_region_is_detected_by_digest(tmp_path):
    """篡改状态文件放大区域后必须被拒绝（digest 自校验）。"""
    store, path = make(tmp_path)
    sm = TaskStateMachine(PHASES, 'ZONE_A')
    store.commit(sm.request_transition('t-1', 'patrol_a_001', 'ZONE_B', 0, 0), sm)
    with open(path, encoding='utf-8') as handle:
        document = json.load(handle)
    document['snapshot']['allowed_region'] = {'x_min': -999.0, 'x_max': 999.0,
                                              'y_min': -999.0, 'y_max': 999.0}
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(document, handle)
    with pytest.raises(StateStoreError):
        store.load()


def test_unknown_state_value_is_rejected(tmp_path):
    store, path = make(tmp_path)
    sm = TaskStateMachine(PHASES, 'ZONE_A')
    store.commit(sm.request_transition('t-1', 'patrol_a_001', 'ZONE_B', 0, 0), sm)
    with open(path, encoding='utf-8') as handle:
        document = json.load(handle)
    document['state'] = 'SOMETHING_ELSE'
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(document, handle)
    with pytest.raises(StateStoreError):
        store.load()


def test_restore_after_reload_preserves_replay_protection(tmp_path):
    """重启后旧 transition_id 仍须被认作重放（重启不能重置重放保护）。"""
    store, path = make(tmp_path)
    sm = TaskStateMachine(PHASES, 'ZONE_A')
    store.commit(sm.request_transition('t-1', 'patrol_a_001', 'ZONE_B', 0, 0), sm)

    store2 = TaskStateStore(path)
    snapshot, used, state = store2.load()
    sm2 = TaskStateMachine(PHASES, 'ZONE_A')
    sm2.restore(snapshot, used, state)
    assert sm2.snapshot.policy_epoch == 1
    replay = sm2.request_transition('t-1', 'patrol_a_001', 'ZONE_A', 1, 0)
    assert not replay.accepted
    assert replay.reason_code == 'TRANSITION_REJECTED_REPLAY'


def test_restore_with_phase_not_in_catalog_goes_to_recovery(tmp_path):
    store, path = make(tmp_path)
    sm = TaskStateMachine(PHASES, 'ZONE_A')
    store.commit(sm.request_transition('t-1', 'patrol_a_001', 'ZONE_B', 0, 0), sm)
    snapshot, used, state = TaskStateStore(path).load()

    sm2 = TaskStateMachine({'ZONE_A': ZONE_A}, 'ZONE_A')  # 配置里已没有 ZONE_B
    with pytest.raises(Exception):
        sm2.restore(snapshot, used, state)
    assert sm2.state == STATE_RECOVERY_REQUIRED


def test_commit_failure_keeps_previous_state_file(tmp_path, monkeypatch):
    """写入失败时旧状态文件必须保持不变（不能出现"半个新状态"）。"""
    store, path = make(tmp_path)
    sm = TaskStateMachine(PHASES, 'ZONE_A')
    first = sm.request_transition('t-1', 'patrol_a_001', 'ZONE_B', 0, 0)
    store.commit(first, sm)
    sm.commit(first)  # 先让状态机也前进到 epoch=1，否则第二次请求是过期 epoch
    before = open(path, encoding='utf-8').read()

    def boom(*_args, **_kwargs):
        raise OSError('simulated disk failure')

    monkeypatch.setattr(os, 'replace', boom)
    plan = sm.request_transition('t-2', 'patrol_a_001', 'ZONE_A', 1, 0)
    ok, detail = store.commit(plan, sm)
    assert ok is False
    assert 'simulated disk failure' in detail
    assert open(path, encoding='utf-8').read() == before
    leftovers = [n for n in os.listdir(str(tmp_path)) if n.startswith('.task_state_')]
    assert leftovers == [], '失败后必须清理临时文件'


def test_snapshot_from_phase_matches_store(tmp_path):
    store, _ = make(tmp_path)
    sm = TaskStateMachine(PHASES, 'ZONE_A')
    store.commit(sm.request_transition('t-1', 'patrol_a_001', 'ZONE_B', 0, 0), sm)
    snapshot, _used, _state = store.load()
    assert snapshot == ActiveTaskSnapshot.from_phase(ZONE_B, 1)
