#!/usr/bin/env python3
"""verify_m3_online_evidence.py 的反例（可证伪性）测试。

任务书要求：以下任一手工篡改都**必须**导致在线证据复核失败。
  1. 篡改 Gateway reason_code
  2. 移除对应的 NavigationSim Goal
  3. 修改其中一层的 request_id
  4. 在 BLOCK 请求中插入伪造 Goal

另加：删除必要审计事件、制造重复事件，确保工具不是"关键词检查"。
目的：证明该工具具备真实判别力，而不是恒真断言。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(REPO, 'scripts')
sys.path.insert(0, SCRIPTS)

import verify_m3_online_evidence as vme  # noqa: E402


def load_jsonl(path):
    rows = []
    if os.path.isfile(path):
        with open(path, encoding='utf-8') as handle:
            for line in handle:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    return rows


def dump_jsonl(path, rows):
    with open(path, 'w', encoding='utf-8') as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + '\n')


def build_clean_fixture(tmp_path):
    """构造一份**最小但自洽**的在线证据集（ON01 成功 + ON02 阻断）。"""
    root = tmp_path / 'run'
    root.mkdir()
    run_id = 'rev-run'
    on01 = 'on01-legal-' + run_id
    on02 = 'on02-block-' + run_id

    (root / 'f0_ON01.json').write_text(json.dumps({
        'decision': 'READY_FOR_GATEWAY_SUBMISSION', 'reason_code': 'ADAPTER_OK',
        'request_id': on01, 'run_id': run_id,
        'modules': [{'module': 'task_risk', 'status': 'ALLOW_RECOMMENDED'}],
        'online': {'enabled': True, 'outcome': 'PLANNER_RESULT_RECEIVED',
                   'planner_result': {'status_code': 'EXECUTED', 'success': True}},
    }, ensure_ascii=False), encoding='utf-8')
    (root / 'f0_ON02.json').write_text(json.dumps({
        'decision': 'ADAPTER_BLOCK',
        'reason_code': 'ADAPTER_MODULE_STATUS_NOT_PROCEED',
        'request_id': on02, 'run_id': run_id,
        'modules': [{'module': 'task_risk', 'status': 'BLOCK_RECOMMENDED'}],
        'online': {'enabled': True, 'outcome': 'NOT_SUBMITTED_ADAPTER_BLOCK'},
    }, ensure_ascii=False), encoding='utf-8')

    # 适配层记录（只保留复核需要的字段）
    for cid, rid, decision in (('ON01', on01, 'READY_FOR_GATEWAY_SUBMISSION'),
                               ('ON02', on02, 'ADAPTER_BLOCK')):
        with open(root / ('adapter_{0}.jsonl'.format(cid)), 'w',
                  encoding='utf-8') as handle:
            handle.write(json.dumps({
                'request_id': rid, 'run_id': run_id, 'decision': decision,
            }, ensure_ascii=False) + '\n')

    dump_jsonl(root / 'gateway_audit.jsonl', [
        {'event_type': 'RosCommEvent', 'request_id': on01,
         'received_at': '2026-10-16T00:00:00.000Z'},
        {'event_type': 'DecisionEvent', 'request_id': on01, 'decision': 'ALLOW',
         'reason_code': 'ALLOW_IN_POLICY',
         'decision_at': '2026-10-16T00:00:00.100Z'},
        {'event_type': 'ExecutionEvent', 'request_id': on01},
    ])
    dump_jsonl(root / 'navsim_goals.jsonl', [
        {'request_id': on01, 'goal_id': 'g1'},
    ])

    # 权威清单：由驱动器在场景**执行前**写入，为复核提供外部基准。
    # 若期望值取自适配层自身记录，篡改适配层即可通过 -> 自证循环。
    (root / 'manifest.json').write_text(json.dumps({
        'run_id': run_id,
        'scenarios': [
            {'cid': 'ON01', 'request_id': on01, 'run_id': run_id,
             'expected': 'ALLOW_AND_EXECUTE'},
            {'cid': 'ON02', 'request_id': on02, 'run_id': run_id,
             'expected': 'M3_BLOCK_NO_SUBMIT'},
        ],
    }, ensure_ascii=False), encoding='utf-8')
    return root


def verify(root):
    return vme.verify_run(str(root))


def test_clean_fixture_passes(tmp_path):
    """前置：未篡改时复核必须通过（否则反例测试无意义）。"""
    summary = verify(build_clean_fixture(tmp_path))
    assert summary['verdict'] == 'PASS', [
        f for f in summary['findings'] if not f['ok']]


# ---------------------------------------------------------------------------
# 反例 1：篡改 Gateway reason_code
# ---------------------------------------------------------------------------

def test_tampered_reason_code_fails(tmp_path):
    root = build_clean_fixture(tmp_path)
    rows = load_jsonl(root / 'gateway_audit.jsonl')
    for row in rows:
        if row.get('event_type') == 'DecisionEvent':
            row['reason_code'] = 'TOTALLY_MADE_UP_CODE'
    dump_jsonl(root / 'gateway_audit.jsonl', rows)
    summary = verify(root)
    assert summary['verdict'] == 'FAIL'
    codes = {f['code'] for f in summary['findings'] if not f['ok']}
    assert 'ILLEGAL_GATEWAY_REASON_CODE' in codes, codes


def test_tampered_decision_to_block_with_goal_fails(tmp_path):
    """把 ALLOW 改成 BLOCK 但保留 Goal -> 必须发现矛盾。"""
    root = build_clean_fixture(tmp_path)
    rows = load_jsonl(root / 'gateway_audit.jsonl')
    for row in rows:
        if row.get('event_type') == 'DecisionEvent':
            row['decision'] = 'BLOCK'
            row['reason_code'] = 'OUT_OF_REGION'
    dump_jsonl(root / 'gateway_audit.jsonl', rows)
    summary = verify(root)
    assert summary['verdict'] == 'FAIL'
    codes = {f['code'] for f in summary['findings'] if not f['ok']}
    assert 'BLOCK_BUT_GOAL_EXISTS' in codes, codes


# ---------------------------------------------------------------------------
# 反例 2：移除对应的 NavigationSim Goal
# ---------------------------------------------------------------------------

def test_missing_goal_for_executed_request_fails(tmp_path):
    root = build_clean_fixture(tmp_path)
    dump_jsonl(root / 'navsim_goals.jsonl', [])
    summary = verify(root)
    assert summary['verdict'] == 'FAIL'
    codes = {f['code'] for f in summary['findings'] if not f['ok']}
    assert 'ACTION_RESULT_GOAL_CONSISTENT' in codes, codes


# ---------------------------------------------------------------------------
# 反例 3：修改其中一层的 request_id
# ---------------------------------------------------------------------------

def test_modified_adapter_request_id_fails(tmp_path):
    root = build_clean_fixture(tmp_path)
    path = root / 'adapter_ON01.jsonl'
    with open(path, 'w', encoding='utf-8') as handle:
        handle.write(json.dumps({
            'request_id': 'somebody-elses-request', 'run_id': 'rev-run',
            'decision': 'READY_FOR_GATEWAY_SUBMISSION'}) + '\n')
    summary = verify(root)
    assert summary['verdict'] == 'FAIL'
    codes = {f['code'] for f in summary['findings'] if not f['ok']}
    # 适配层记录与权威清单不符 -> 必须被发现
    assert 'REQUEST_ID_MISMATCH' in codes, codes


def test_manifest_missing_fails_closed(tmp_path):
    """缺少权威清单时必须失败关闭，而不是放行（避免自证循环）。"""
    root = build_clean_fixture(tmp_path)
    os.unlink(root / 'manifest.json')
    summary = verify(root)
    assert summary['verdict'] == 'FAIL'
    codes = {f['code'] for f in summary['findings'] if not f['ok']}
    assert 'MANIFEST_MISSING' in codes, codes


def test_f0_request_id_tampering_fails(tmp_path):
    """只改 F0 输出的 request_id 也必须被发现。"""
    root = build_clean_fixture(tmp_path)
    path = root / 'f0_ON01.json'
    doc = json.loads(path.read_text(encoding='utf-8'))
    doc['request_id'] = 'tampered-in-f0-only'
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding='utf-8')
    summary = verify(root)
    assert summary['verdict'] == 'FAIL'
    codes = {f['code'] for f in summary['findings'] if not f['ok']}
    assert 'F0_REQUEST_ID_MISMATCH' in codes, codes


def test_orphan_goal_request_id_fails(tmp_path):
    """journal 中出现不属于任何场景的 request_id -> 必须失败。"""
    root = build_clean_fixture(tmp_path)
    rows = load_jsonl(root / 'navsim_goals.jsonl')
    rows.append({'request_id': 'ghost-request', 'goal_id': 'gX'})
    dump_jsonl(root / 'navsim_goals.jsonl', rows)
    summary = verify(root)
    assert summary['verdict'] == 'FAIL'
    codes = {f['code'] for f in summary['findings'] if not f['ok']}
    assert 'ORPHAN_GOAL_REQUEST' in codes, codes


# ---------------------------------------------------------------------------
# 反例 4：在 BLOCK 请求中插入伪造 Goal
# ---------------------------------------------------------------------------

def test_fake_goal_for_blocked_request_fails(tmp_path):
    root = build_clean_fixture(tmp_path)
    rows = load_jsonl(root / 'gateway_audit.jsonl')
    # 为被阻断的 ON02 伪造 arrival + BLOCK 决策
    rows.append({'event_type': 'RosCommEvent',
                 'request_id': 'on02-block-rev-run',
                 'received_at': '2026-10-16T00:00:01.000Z'})
    rows.append({'event_type': 'DecisionEvent',
                 'request_id': 'on02-block-rev-run', 'decision': 'BLOCK',
                 'reason_code': 'OUT_OF_REGION',
                 'decision_at': '2026-10-16T00:00:01.100Z'})
    dump_jsonl(root / 'gateway_audit.jsonl', rows)
    # 再为该被阻断请求插入一条伪造 Goal
    goals = load_jsonl(root / 'navsim_goals.jsonl')
    goals.append({'request_id': 'on02-block-rev-run', 'goal_id': 'fake'})
    dump_jsonl(root / 'navsim_goals.jsonl', goals)
    summary = verify(root)
    assert summary['verdict'] == 'FAIL'
    codes = {f['code'] for f in summary['findings'] if not f['ok']}
    assert 'BLOCK_NO_GATEWAY_ARRIVAL' in codes or 'BLOCK_BUT_GOAL_EXISTS' in codes, codes


# ---------------------------------------------------------------------------
# 附加反例：缺失事件、重复事件、时间倒序
# ---------------------------------------------------------------------------

def test_missing_decision_event_fails(tmp_path):
    root = build_clean_fixture(tmp_path)
    rows = [r for r in load_jsonl(root / 'gateway_audit.jsonl')
            if r.get('event_type') != 'DecisionEvent']
    dump_jsonl(root / 'gateway_audit.jsonl', rows)
    summary = verify(root)
    assert summary['verdict'] == 'FAIL'
    codes = {f['code'] for f in summary['findings'] if not f['ok']}
    assert 'ARRIVAL_WITHOUT_DECISION' in codes, codes


def test_duplicate_decision_event_fails(tmp_path):
    root = build_clean_fixture(tmp_path)
    rows = load_jsonl(root / 'gateway_audit.jsonl')
    dup = [r for r in rows if r.get('event_type') == 'DecisionEvent'][0]
    rows.append(dict(dup))
    dump_jsonl(root / 'gateway_audit.jsonl', rows)
    summary = verify(root)
    assert summary['verdict'] == 'FAIL'
    codes = {f['code'] for f in summary['findings'] if not f['ok']}
    assert 'DUPLICATE_DECISION' in codes, codes


def test_time_order_violation_fails(tmp_path):
    root = build_clean_fixture(tmp_path)
    rows = load_jsonl(root / 'gateway_audit.jsonl')
    for row in rows:
        if row.get('event_type') == 'DecisionEvent':
            row['decision_at'] = '2026-10-15T23:59:59.000Z'   # 早于 arrival
    dump_jsonl(root / 'gateway_audit.jsonl', rows)
    summary = verify(root)
    assert summary['verdict'] == 'FAIL'
    codes = {f['code'] for f in summary['findings'] if not f['ok']}
    assert 'TIME_ORDER_VIOLATION' in codes, codes


def test_block_with_planner_started_fails(tmp_path):
    """模块阻断却启动了 Planner -> 必须失败。"""
    root = build_clean_fixture(tmp_path)
    (root / 'f0_ON02.json').write_text(json.dumps({
        'decision': 'ADAPTER_BLOCK',
        'reason_code': 'ADAPTER_MODULE_STATUS_NOT_PROCEED',
        'request_id': 'on02-block-rev-run', 'run_id': 'rev-run',
        'modules': [{'module': 'task_risk', 'status': 'BLOCK_RECOMMENDED'}],
        'online': {'enabled': True, 'outcome': 'PLANNER_RESULT_RECEIVED'},
    }, ensure_ascii=False), encoding='utf-8')
    summary = verify(root)
    assert summary['verdict'] == 'FAIL'
    codes = {f['code'] for f in summary['findings'] if not f['ok']}
    assert 'BLOCK_NO_PLANNER' in codes, codes


def test_tool_is_not_a_keyword_check(tmp_path):
    """工具必须能发现结构化矛盾，而不是"日志里有没有某个词"。"""
    root = build_clean_fixture(tmp_path)
    # 日志文本原样保留（含所有关键词），但把 Goal 的 request_id 改错
    goals = load_jsonl(root / 'navsim_goals.jsonl')
    goals[0]['request_id'] = 'on01-legal-rev-run-MUTATED'
    dump_jsonl(root / 'navsim_goals.jsonl', goals)
    summary = verify(root)
    assert summary['verdict'] == 'FAIL', '仅靠关键词检查会漏掉该篡改'
