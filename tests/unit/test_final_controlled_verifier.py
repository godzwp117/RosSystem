"""受控在线严格验收器的**故障注入**测试。

一个只会说 PASS 的验收器毫无价值。这些测试构造**错误证据**，
要求验证器必须拒绝；只有全部反例都被拒绝，
`FINAL_CONTROLLED_VERIFIER_NEGATIVE_TESTS` 才允许 PASS。

所有注入都在 pytest 的临时目录里进行，
**不修改任何历史原始证据**。
"""
from __future__ import annotations

import json
import os
import shutil
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, 'scripts'))

from verify_final_controlled_online import verify  # noqa: E402

RUN_ID = 'run-test-001'


def base_evidence(run_dir):
    """构造一份**正确**的受控在线证据（三场景）。"""
    ids = {cid: f'{cid.lower()}-x-{RUN_ID}' for cid in ('ON01', 'ON02', 'ON05')}
    audit = [
        # ON-01：到达 + ALLOW + 执行
        {'event_type': 'RosCommEvent', 'request_id': ids['ON01'],
         'task_id': 'patrol_a_001'},
        {'event_type': 'DecisionEvent', 'request_id': ids['ON01'],
         'decision': 'ALLOW', 'reason_code': 'ALLOW_IN_POLICY',
         'task_id': 'patrol_a_001'},
        {'event_type': 'ExecutionEvent', 'request_id': ids['ON01'],
         'outcome': 'SUCCESS', 'task_id': 'patrol_a_001'},
        # ON-05：到达 + BLOCK（无执行事件）
        {'event_type': 'RosCommEvent', 'request_id': ids['ON05'],
         'task_id': 'patrol_a_001'},
        {'event_type': 'DecisionEvent', 'request_id': ids['ON05'],
         'decision': 'BLOCK', 'reason_code': 'OUT_OF_REGION',
         'task_id': 'patrol_a_001'},
    ]
    journal = [
        {'request_id': ids['ON01'], 'goal_id': 'g-on01', 'task_id': 'patrol_a_001',
         'action': '/rg/nav_execute', 'frame_id': 'map'},
    ]
    manifest = {'run_id': RUN_ID,
                'scenarios': [{'cid': cid, 'request_id': ids[cid]}
                              for cid in ('ON01', 'ON02', 'ON05')]}
    f0 = {
        'ON01': {'decision': 'READY_FOR_GATEWAY_SUBMISSION',
                 'online': {'outcome': 'PLANNER_RESULT_RECEIVED'}},
        'ON02': {'decision': 'ADAPTER_BLOCK',
                 'online': {'outcome': 'NOT_SUBMITTED_ADAPTER_BLOCK'}},
        'ON05': {'decision': 'READY_FOR_GATEWAY_SUBMISSION',
                 'online': {'outcome': 'PLANNER_RESULT_RECEIVED'}},
    }
    write_evidence(run_dir, audit, journal, manifest, f0)
    return ids


def write_evidence(run_dir, audit, journal, manifest, f0):
    os.makedirs(run_dir, exist_ok=True)
    def dump_jsonl(name, rows):
        with open(os.path.join(run_dir, name), 'w', encoding='utf-8') as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + '\n')
    dump_jsonl('gateway_audit.jsonl', audit)
    dump_jsonl('navsim_goals.jsonl', journal)
    with open(os.path.join(run_dir, 'manifest.json'), 'w', encoding='utf-8') as fh:
        json.dump(manifest, fh, ensure_ascii=False)
    for cid, doc in f0.items():
        with open(os.path.join(run_dir, f'f0_{cid}.json'), 'w', encoding='utf-8') as fh:
            json.dump(doc, fh, ensure_ascii=False)


def read_evidence(run_dir):
    def load_jsonl(name):
        path = os.path.join(run_dir, name)
        if not os.path.exists(path):
            return []
        with open(path, encoding='utf-8') as fh:
            return [json.loads(line) for line in fh if line.strip()]
    manifest = json.load(open(os.path.join(run_dir, 'manifest.json'), encoding='utf-8'))
    f0 = {}
    for cid in ('ON01', 'ON02', 'ON05'):
        path = os.path.join(run_dir, f'f0_{cid}.json')
        if os.path.exists(path):
            f0[cid] = json.load(open(path, encoding='utf-8'))
    return load_jsonl('gateway_audit.jsonl'), load_jsonl('navsim_goals.jsonl'), manifest, f0


@pytest.fixture()
def run_dir(tmp_path):
    directory = tmp_path / 'run'
    base_evidence(str(directory))
    return str(directory)


def assert_rejected(run_dir):
    findings, _facts = verify(run_dir)
    assert findings.verdict() == 'FAIL', '该错误证据本应被拒绝，验证器却给了 PASS'
    return [f['code'] for f in findings.failures]


# ---------------------------------------------------------------- 基线
def test_correct_evidence_passes(run_dir):
    findings, facts = verify(run_dir)
    assert findings.verdict() == 'PASS'
    assert facts['scenarios']['ON01']['navsim_goals'] == 1


# ---------------------------------------------------------------- 1-4 ON-01
def test_on01_gateway_block_is_rejected(run_dir):
    audit, journal, manifest, f0 = read_evidence(run_dir)
    for row in audit:
        if row.get('event_type') == 'DecisionEvent' and 'on01' in row['request_id']:
            row['decision'] = 'BLOCK'
            row['reason_code'] = 'OUT_OF_REGION'
    write_evidence(run_dir, audit, journal, manifest, f0)
    assert 'GATEWAY_DECISION' in assert_rejected(run_dir)


def test_on01_missing_goal_is_rejected(run_dir):
    audit, journal, manifest, f0 = read_evidence(run_dir)
    write_evidence(run_dir, audit, [], manifest, f0)
    assert 'NAVSIM_GOAL_COUNT' in assert_rejected(run_dir)


def test_on01_duplicate_goal_is_rejected(run_dir):
    audit, journal, manifest, f0 = read_evidence(run_dir)
    journal.append(dict(journal[0], goal_id='g-on01-dup'))
    write_evidence(run_dir, audit, journal, manifest, f0)
    assert 'NAVSIM_GOAL_COUNT' in assert_rejected(run_dir)


def test_on01_missing_execution_event_is_rejected(run_dir):
    audit, journal, manifest, f0 = read_evidence(run_dir)
    audit = [row for row in audit if row.get('event_type') != 'ExecutionEvent']
    write_evidence(run_dir, audit, journal, manifest, f0)
    assert 'GATEWAY_EXECUTION_COUNT' in assert_rejected(run_dir)


# ---------------------------------------------------------------- 5-6 ON-02
def test_on02_gateway_arrival_is_rejected(run_dir):
    audit, journal, manifest, f0 = read_evidence(run_dir)
    on02 = manifest['scenarios'][1]['request_id']
    audit.append({'event_type': 'RosCommEvent', 'request_id': on02})
    write_evidence(run_dir, audit, journal, manifest, f0)
    assert 'GATEWAY_ARRIVAL_COUNT' in assert_rejected(run_dir)


def test_on02_illegal_goal_is_rejected(run_dir):
    audit, journal, manifest, f0 = read_evidence(run_dir)
    on02 = manifest['scenarios'][1]['request_id']
    journal.append({'request_id': on02, 'goal_id': 'g-illegal',
                    'action': '/rg/nav_execute'})
    write_evidence(run_dir, audit, journal, manifest, f0)
    assert 'NAVSIM_GOAL_COUNT' in assert_rejected(run_dir)


# ---------------------------------------------------------------- 7-8 ON-05
def test_on05_wrong_allow_is_rejected(run_dir):
    audit, journal, manifest, f0 = read_evidence(run_dir)
    for row in audit:
        if row.get('event_type') == 'DecisionEvent' and 'on05' in row['request_id']:
            row['decision'] = 'ALLOW'
            row['reason_code'] = 'ALLOW_IN_POLICY'
    write_evidence(run_dir, audit, journal, manifest, f0)
    codes = assert_rejected(run_dir)
    assert 'GATEWAY_DECISION' in codes


def test_on05_goal_is_rejected(run_dir):
    audit, journal, manifest, f0 = read_evidence(run_dir)
    on05 = manifest['scenarios'][2]['request_id']
    journal.append({'request_id': on05, 'goal_id': 'g-leak',
                    'action': '/rg/nav_execute'})
    write_evidence(run_dir, audit, journal, manifest, f0)
    assert 'NAVSIM_GOAL_COUNT' in assert_rejected(run_dir)


def test_on05_successful_execution_is_rejected(run_dir):
    audit, journal, manifest, f0 = read_evidence(run_dir)
    on05 = manifest['scenarios'][2]['request_id']
    audit.append({'event_type': 'ExecutionEvent', 'request_id': on05,
                  'outcome': 'SUCCESS'})
    write_evidence(run_dir, audit, journal, manifest, f0)
    codes = assert_rejected(run_dir)
    assert 'NO_SUCCESSFUL_EXECUTION' in codes or 'GATEWAY_EXECUTION_COUNT' in codes


# ---------------------------------------------------------------- 9-11 标识
def test_replaced_request_id_is_rejected(run_dir):
    audit, journal, manifest, f0 = read_evidence(run_dir)
    manifest['scenarios'][0]['request_id'] = 'on01-other-run'
    write_evidence(run_dir, audit, journal, manifest, f0)
    assert_rejected(run_dir)


def test_wrong_run_id_is_rejected(run_dir):
    audit, journal, manifest, f0 = read_evidence(run_dir)
    manifest['run_id'] = 'a-different-run'
    write_evidence(run_dir, audit, journal, manifest, f0)
    assert 'REQUEST_ID_MATCHES_RUN' in assert_rejected(run_dir)


def test_missing_audit_is_rejected(run_dir):
    audit, journal, manifest, f0 = read_evidence(run_dir)
    os.remove(os.path.join(run_dir, 'gateway_audit.jsonl'))
    write_evidence(run_dir, [], journal, manifest, f0)
    assert 'AUDIT_PRESENT' in assert_rejected(run_dir)


def test_corrupt_audit_is_rejected(run_dir):
    with open(os.path.join(run_dir, 'gateway_audit.jsonl'), 'w', encoding='utf-8') as fh:
        fh.write('{not json\n')
    assert 'AUDIT_PRESENT' in assert_rejected(run_dir)


def test_missing_journal_is_rejected(run_dir):
    os.remove(os.path.join(run_dir, 'navsim_goals.jsonl'))
    assert 'JOURNAL_PRESENT' in assert_rejected(run_dir)


def test_corrupt_journal_is_rejected(run_dir):
    with open(os.path.join(run_dir, 'navsim_goals.jsonl'), 'w', encoding='utf-8') as fh:
        fh.write('garbage\n')
    assert 'JOURNAL_PRESENT' in assert_rejected(run_dir)


# ---------------------------------------------------------------- 15-18 一致性
def test_f0_contradicting_gateway_is_rejected(run_dir):
    """F0 说 BLOCK，但审计显示到达并 ALLOW —— 必须拒绝。"""
    audit, journal, manifest, f0 = read_evidence(run_dir)
    f0['ON01']['decision'] = 'ADAPTER_BLOCK'
    write_evidence(run_dir, audit, journal, manifest, f0)
    codes = assert_rejected(run_dir)
    assert 'F0_DECISION' in codes


def test_foreign_events_from_another_run_are_rejected(run_dir):
    audit, journal, manifest, f0 = read_evidence(run_dir)
    audit.append({'event_type': 'RosCommEvent',
                  'request_id': 'on01-x-some-other-experiment'})
    write_evidence(run_dir, audit, journal, manifest, f0)
    assert 'NO_FOREIGN_AUDIT_REQUESTS' in assert_rejected(run_dir)


def test_duplicate_decision_is_rejected(run_dir):
    audit, journal, manifest, f0 = read_evidence(run_dir)
    dup = dict([r for r in audit
                if r.get('event_type') == 'DecisionEvent' and 'on01' in r['request_id']][0])
    audit.append(dup)
    write_evidence(run_dir, audit, journal, manifest, f0)
    assert 'NO_DUPLICATE_DECISION' in assert_rejected(run_dir)


def test_unrelated_goal_is_not_silently_ignored(run_dir):
    """无关 request_id 的 Goal 必须被**报出**，而不是悄悄算进或算掉。"""
    audit, journal, manifest, f0 = read_evidence(run_dir)
    journal.append({'request_id': 'unknown-request', 'goal_id': 'g-x',
                    'action': '/rg/nav_execute'})
    write_evidence(run_dir, audit, journal, manifest, f0)
    assert 'NO_FOREIGN_JOURNAL_GOALS' in assert_rejected(run_dir)


def test_on02_planner_submitted_is_rejected(run_dir):
    audit, journal, manifest, f0 = read_evidence(run_dir)
    f0['ON02']['online']['outcome'] = 'PLANNER_RESULT_RECEIVED'
    write_evidence(run_dir, audit, journal, manifest, f0)
    assert 'PLANNER_NOT_SUBMITTED' in assert_rejected(run_dir)
