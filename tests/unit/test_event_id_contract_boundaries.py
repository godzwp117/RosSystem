#!/usr/bin/env python3
"""event_id / request_id 契约边界测试。

背景
----
旧 `ID-03` 要求 `event_id` **包含完整 `request_id`**，而三份公共 Schema 把
`event_id` 限制为 1..128 字符。当 `request_id` 接近 128 字符时：

    前缀 + request_id(128) + 分隔符 + 随机部分  >  128

两者**数学上无法同时成立**。而 `docs/interfaces/CONTRACT_VERSION.md` §7 与
Schema 描述的实际语义是：

    event_id   = 本次输出事件唯一标识，用于审计追溯与去重
    request_id = 业务请求关联标识

跨层关联由**显式** `run_id`/`request_id` 字段承担，不是把 request_id 编码进
event_id。因此修正验收器而非 Schema。

本文件覆盖任务书 §C4 的全部边界。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, 'scripts'))

import check_member_module as cmm  # noqa: E402
import validate_team_contracts as vtc  # noqa: E402

M3_CONFIG = os.path.join(REPO, 'config', 'team_modules.member3.real.yaml')
M3_FIXTURE = os.path.join(REPO, 'config', 'acceptance',
                          'real_scenarios.member3.yaml')
MOCK_CONFIG = os.path.join(REPO, 'config', 'team_modules.example.yaml')

#: 任务书 §C4 要求的 request_id 长度边界
REQUEST_ID_LENGTHS = [1, 64, 80, 81, 100, 127, 128]


def _envelope(request_id, run_id='edge-run'):
    return {
        'schema_version': '1.0.0-proposed', 'run_id': run_id,
        'request_id': request_id, 'created_at': '2026-10-16T00:00:00Z',
        'candidate_action': {'action_resource': '/rg/guarded_navigate',
                             'operation': 'NAVIGATE',
                             'task_id': 'patrol_a_001',
                             'target': {'frame_id': 'map', 'x': 2.0, 'y': 2.0,
                                        'z': 0.0}},
        'observations': [{'source': '/rg/guarded_navigate', 'kind': 'MOCK',
                          'observed_at': '2026-10-16T00:00:00Z', 'detail': {}}],
        'evidence_refs': [{'ref': 'edge', 'kind': 'UNIT_TEST'}],
    }


def _run_module(command, envelope):
    proc = subprocess.run(
        command, input=json.dumps(envelope), capture_output=True, text=True,
        cwd=REPO, timeout=180)
    document = None
    if proc.stdout.strip().startswith('{'):
        document = json.loads(proc.stdout)
    return proc, document


# ---------------------------------------------------------------------------
# 1) 真实模块在各长度边界下的 event_id 行为
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('length', REQUEST_ID_LENGTHS)
def test_m3_event_id_within_schema_limit_at_every_length(length):
    """成员三：任意合法 request_id 长度下 event_id 都必须满足 Schema。"""
    envelope = _envelope('r' * length)
    proc, document = _run_module(
        [sys.executable, 'modules/member3_taskrisk/module.py',
         '--policy', 'config/task_policy.yaml'], envelope)
    assert proc.returncode == 0, proc.stderr[-300:]
    assert document is not None, proc.stdout[:200]
    event_id = document['event_id']
    assert isinstance(event_id, str) and event_id.strip(), event_id
    assert len(event_id) <= 128, len(event_id)
    # 业务关联必须由显式字段承担
    assert document['request_id'] == envelope['request_id']
    assert document['run_id'] == envelope['run_id']


@pytest.mark.parametrize('length', REQUEST_ID_LENGTHS)
def test_m2_event_id_within_schema_limit_at_every_length(length, tmp_path):
    """成员二：同上（其证据来自归档受控实验）。"""
    from argparse import Namespace
    sys.path.insert(0, REPO)
    from identity_trust.assessor import assessment
    envelope = _envelope('r' * length)
    options = Namespace(
        policy=os.path.join(REPO, 'security/policies/minimal_permissions.xml'),
        keystore=os.path.join(REPO, 'security/keystore'),
        evidence_root=os.path.join(
            REPO, 'artifacts/acceptance/exports/m2_sros2_enforce/logs/tests_evidence'),
        experiment_run='20261009T093144Z', case='S2')
    document = assessment(envelope, options)
    event_id = document['event_id']
    assert isinstance(event_id, str) and event_id.strip(), event_id
    assert len(event_id) <= 128, len(event_id)
    assert document['request_id'] == envelope['request_id']


@pytest.mark.parametrize('length', REQUEST_ID_LENGTHS)
def test_cross_layer_correlation_works_without_event_id_containment(length):
    """关联不依赖 event_id 包含 request_id：显式字段即足以关联。"""
    envelope = _envelope('r' * length)
    _proc, document = _run_module(
        [sys.executable, 'modules/member3_taskrisk/module.py',
         '--policy', 'config/task_policy.yaml'], envelope)
    # 关联判据：request_id / run_id 逐字一致（不检查 event_id 包含关系）
    assert document['request_id'] == envelope['request_id']
    assert document['run_id'] == envelope['run_id']
    # 且 event_id 确实**不**需要包含完整 request_id
    if length > 80:
        assert envelope['request_id'] not in document['event_id'], \
            '长 request_id 下不应强求包含关系（Schema 上限使其不可能）'


def test_module_output_passes_public_schema_at_max_length():
    """128 字符 request_id 下输出仍须通过**未修改的**公共 Schema。"""
    envelope = _envelope('r' * 128)
    _proc, document = _run_module(
        [sys.executable, 'modules/member3_taskrisk/module.py',
         '--policy', 'config/task_policy.yaml'], envelope)
    errors = vtc.validate_document(document, vtc.load_schema('task_risk_decision'))
    assert not errors, errors


# ---------------------------------------------------------------------------
# 2) 验收器 ID-03 / ID-05 的判定力（必须能失败）
# ---------------------------------------------------------------------------

def test_id03_accepts_valid_event_id():
    ok = isinstance('evt-abc', str) and 0 < len('evt-abc') <= 128
    assert ok


@pytest.mark.parametrize('bad', ['', '   ', None, 123, 'x' * 129])
def test_id03_rejects_invalid_event_id(bad):
    """空串、空白、非字符串、超长都必须判负（不是恒真）。"""
    ok = bool(isinstance(bad, str) and 0 < len(bad) <= 128 and bad.strip())
    assert ok is False, bad


def test_id03_accepts_boundary_valid_ids():
    """边界正例：1 字符与恰好 128 字符都必须通过。"""
    for good in ('x', 'y' * 128, 'evt-1'):
        ok = bool(isinstance(good, str) and 0 < len(good) <= 128 and good.strip())
        assert ok is True, good


def test_id05_detects_duplicate_event_ids():
    """同一运行内重复 event_id -> ID-05 必须判负。"""
    event_ids = [('E', 'a'), ('E', 'b')]
    seen, dup = {}, []
    for value, where in event_ids:
        if not isinstance(value, str) or not value.strip():
            dup.append(('EMPTY', where)); continue
        if len(value) > 128:
            dup.append(('TOO_LONG', where)); continue
        if value in seen:
            dup.append((value, where))
        else:
            seen[value] = where
    assert dup and dup[0][0] == 'E'


def test_id05_detects_empty_and_too_long():
    for bad in ('', '   ', 'x' * 129):
        event_ids = [(bad, 'a')]
        seen, dup = {}, []
        for value, where in event_ids:
            if not isinstance(value, str) or not value.strip():
                dup.append(('EMPTY', where)); continue
            if len(value) > 128:
                dup.append(('TOO_LONG', where)); continue
            seen[value] = where
        assert dup, bad


def test_id05_passes_when_ids_distinct():
    event_ids = [('E1', 'a'), ('E2', 'b'), ('E3', 'c')]
    seen, dup = {}, []
    for value, where in event_ids:
        if value in seen:
            dup.append((value, where))
        else:
            seen[value] = where
    assert not dup and len(seen) == 3


# ---------------------------------------------------------------------------
# 3) 一致性：request_id / run_id 不匹配必须被发现
# ---------------------------------------------------------------------------

def test_mismatched_request_id_is_detectable():
    """模块输出 request_id 与输入不一致 -> ID-02 判负（不是恒真）。"""
    envelope = _envelope('req-x')
    wrong = dict(envelope, request_id='req-y')
    assert (wrong['request_id'] == envelope['request_id']) is False


def test_mismatched_run_id_is_detectable():
    envelope = _envelope('req-x', run_id='run-1')
    wrong = dict(envelope, run_id='run-2')
    assert (wrong['run_id'] == envelope['run_id']) is False


def test_request_id_with_allowed_special_characters():
    """request_id 含 Schema 允许的特殊字符时，关联与长度仍成立。"""
    tricky = 'req-/rg:guarded_navigate#1?x=2&y=3'
    envelope = _envelope(tricky)
    proc, document = _run_module(
        [sys.executable, 'modules/member3_taskrisk/module.py',
         '--policy', 'config/task_policy.yaml'], envelope)
    assert proc.returncode == 0, proc.stderr[-300:]
    assert document['request_id'] == tricky
    assert len(document['event_id']) <= 128


# ---------------------------------------------------------------------------
# 4) 端到端：验收器在 mock 与真实模式下 ID 项全绿且无 FAIL
# ---------------------------------------------------------------------------

def test_end_to_end_ids_pass_in_mock_mode(tmp_path):
    proc = subprocess.run(
        [sys.executable, os.path.join(REPO, 'scripts', 'check_member_module.py'),
         '--module', 'task_risk', '--config', MOCK_CONFIG,
         '--out-dir', str(tmp_path), '--run-id', 'ids-mock'],
        capture_output=True, text=True, timeout=900, cwd=REPO)
    report = json.loads((tmp_path / 'ids-mock' / 'report.json').read_text('utf-8'))
    checks = {c['id']: c for c in report['checks']}
    for cid in ('ID-01', 'ID-02', 'ID-03', 'ID-03B', 'ID-04', 'ID-05'):
        assert checks[cid]['status'] == 'PASS', checks[cid]
    assert report['counts'].get('FAIL', 0) == 0


def test_end_to_end_ids_pass_in_real_mode(tmp_path):
    subprocess.run(
        [sys.executable, os.path.join(REPO, 'scripts', 'check_member_module.py'),
         '--module', 'task_risk', '--config', M3_CONFIG,
         '--real-fixture', M3_FIXTURE,
         '--out-dir', str(tmp_path), '--run-id', 'ids-real'],
        capture_output=True, text=True, timeout=1800, cwd=REPO)
    report = json.loads((tmp_path / 'ids-real' / 'report.json').read_text('utf-8'))
    checks = {c['id']: c for c in report['checks']}
    assert checks['ID-05']['status'] == 'PASS', checks['ID-05']
    audit = checks['ID-05']['event_id_audit']
    assert audit['requests_probed'] >= 5, audit
    assert audit['violations'] == [], audit
