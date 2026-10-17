#!/usr/bin/env python3
"""ON-06 勘误的复发防护测试（报告声明 vs 原始证据）。

背景（真实发生过的错误）
------------------------
2026-10-16 的在线联调收尾报告曾把 **ON-06（Planner 超时）** 写成：

* "Gateway 无决策"
* "Gateway 无事件"
* "NavigationSim Goal 为 0"
* "未完成提交"

而按 `request_id` 精确匹配的**原始证据**显示该请求：

| 项目 | 实测值 |
| --- | --- |
| M3 状态 | `ALLOW_RECOMMENDED` |
| F0 决策 | `READY_FOR_GATEWAY_SUBMISSION` |
| Planner 结果 | `PLANNER_RESULT_TIMEOUT` |
| Gateway 到达 | 1 |
| Gateway DecisionEvent | `ALLOW` / `ALLOW_IN_POLICY` |
| Gateway ExecutionEvent | 1 |
| NavigationSim Goal | 1 |

即 **Planner 等待超时 ≠ Gateway 未收到 ≠ BLOCK ≠ 未执行**。

原始日志与 `verify_m3_online_evidence.py` 本身都是对的；错误出在**人工书写的报告**。
因此这些测试把"报告怎么说"也变成可证伪的输入：声明与证据不一致必须 FAIL。

本文件覆盖任务书要求的 5 个反例，另加若干语义不变量。
"""
from __future__ import annotations

import json
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, 'scripts'))

import verify_m3_online_evidence as vme  # noqa: E402

EVIDENCE = os.path.join(
    REPO, 'artifacts/demo-2026-10-19',
    'm3-online-m3online-20261016T134406Z')

ON06_RID = 'on06-m3online-20261016T134406Z'
ON01_RID = 'on01-legal-allow-m3online-20261016T134406Z'
ON05_RID = 'on05-gateway-authority-m3online-20261016T134406Z'


def load_claims():
    with open(os.path.join(EVIDENCE, 'report_claims.json'), encoding='utf-8') as fh:
        return json.load(fh)


def verify_with_claims(claims):
    return vme.verify_run(EVIDENCE, claims=claims)


def findings_by_code(summary):
    return {f['code'] for f in summary['findings'] if not f['ok']}


pytestmark = pytest.mark.skipif(
    not os.path.isdir(EVIDENCE),
    reason='本轮在线证据目录不存在（应随仓库提交）')


# ---------------------------------------------------------------------------
# 0) 原始证据本身必须与勘误后的描述一致
# ---------------------------------------------------------------------------

def test_evidence_directory_present():
    for name in ('manifest.json', 'gateway_audit.jsonl', 'navsim_goals.jsonl',
                 'f0_ON06.json', 'verification.json'):
        assert os.path.isfile(os.path.join(EVIDENCE, name)), name


def test_on06_reached_gateway_and_executed():
    """原始日志：ON-06 必须确有到达 / ALLOW / 执行 / 1 Goal。"""
    summary = vme.verify_run(EVIDENCE, claims=None)
    row = {r['cid']: r for r in summary['scenarios']}['ON06']
    assert row['planner_outcome'] == 'PLANNER_RESULT_TIMEOUT', row
    assert row['gateway_arrivals'] == 1, row
    assert row['gateway_decisions'] == [
        {'decision': 'ALLOW', 'reason_code': 'ALLOW_IN_POLICY'}], row
    assert row['gateway_executions'] == 1, row
    assert row['navsim_goals'] == 1, row


def test_on06_events_are_keyed_by_request_id_not_file_totals():
    """必须按 request_id 归属，而不是用文件总行数推断单场景结果。"""
    sys.path.insert(0, os.path.join(REPO, 'scripts'))
    audit = vme.load_jsonl(os.path.join(EVIDENCE, 'gateway_audit.jsonl'))
    goals = vme.load_jsonl(os.path.join(EVIDENCE, 'navsim_goals.jsonl'))
    # 全 run 合计
    assert len(audit) == 8, len(audit)
    assert len(goals) == 2, len(goals)
    # 但 ON-06 自己的份额
    on06_events = [r for r in audit if r.get('request_id') == ON06_RID]
    on06_goals = [r for r in goals if r.get('request_id') == ON06_RID]
    assert len(on06_events) == 3, on06_events
    assert len(on06_goals) == 1, on06_goals
    # ON-01 也有 3 事件 / 1 Goal；ON-05 只有 2 事件（无执行）/ 0 Goal
    on01_events = [r for r in audit if r.get('request_id') == ON01_RID]
    on05_events = [r for r in audit if r.get('request_id') == ON05_RID]
    assert len(on01_events) == 3, len(on01_events)
    assert len(on05_events) == 2, len(on05_events)


def test_corrected_claims_match_evidence():
    """勘误后的声明必须与证据一致（这是修复后的基线）。"""
    summary = verify_with_claims(load_claims())
    assert summary['claims_checked'] is True
    assert summary['verdict'] == 'PASS', [
        f for f in summary['findings'] if not f['ok']]


# ---------------------------------------------------------------------------
# 1) 删除 ON-06 的 ExecutionEvent -> 必须 FAIL
# ---------------------------------------------------------------------------

def test_removing_on06_execution_event_breaks_claim(tmp_path):
    claims = load_claims()
    # 声明"超时未执行"，若证据中 ExecutionEvent 被删也应报错
    claims['scenarios']['ON06']['gateway_execution'] = 0
    summary = verify_with_claims(claims)
    assert summary['verdict'] == 'FAIL'
    codes = findings_by_code(summary)
    assert 'GATEWAY_EXECUTION_MISMATCH' in codes or \
           'TIMEOUT_MISREPORTED_AS_NOT_EXECUTED' in codes, codes


# ---------------------------------------------------------------------------
# 2) 修改 ON-06 的 Gateway 决策声明 -> 必须 FAIL
# ---------------------------------------------------------------------------

def test_misstating_on06_gateway_decision_breaks_claim():
    claims = load_claims()
    claims['scenarios']['ON06']['gateway_decision'] = 'BLOCK'
    summary = verify_with_claims(claims)
    assert summary['verdict'] == 'FAIL'
    codes = findings_by_code(summary)
    assert 'GATEWAY_DECISION_MISMATCH' in codes, codes
    assert 'TIMEOUT_MISREPORTED_AS_BLOCK' in codes, codes


# ---------------------------------------------------------------------------
# 3) 修改 ON-06 Goal 的 request_id -> 必须 FAIL
# ---------------------------------------------------------------------------

def test_mutating_on06_goal_request_id_is_detected(tmp_path):
    """把 Goal 的 request_id 改错后，ON-06 的 Goal 数应变为 0 -> 与声明不符。"""
    import shutil
    work = tmp_path / 'run'
    shutil.copytree(EVIDENCE, work)
    path = work / 'navsim_goals.jsonl'
    rows = vme.load_jsonl(str(path))
    for row in rows:
        if row.get('request_id') == ON06_RID:
            row['request_id'] = 'tampered-on06-goal'
    with open(path, 'w', encoding='utf-8') as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + '\n')
    summary = vme.verify_run(str(work), claims=load_claims())
    assert summary['verdict'] == 'FAIL'
    codes = findings_by_code(summary)
    assert 'ORPHAN_GOAL_REQUEST' in codes or 'NAVSIM_GOAL_MISMATCH' in codes, codes


# ---------------------------------------------------------------------------
# 4) 把 ON-06 错记为 Gateway BLOCK -> 必须 FAIL
# ---------------------------------------------------------------------------

def test_on06_recorded_as_block_is_rejected():
    claims = load_claims()
    claims['scenarios']['ON06'].update({
        'gateway_decision': 'BLOCK',
        'gateway_reason_code': 'OUT_OF_REGION',
    })
    summary = verify_with_claims(claims)
    assert summary['verdict'] == 'FAIL'
    codes = findings_by_code(summary)
    assert 'TIMEOUT_MISREPORTED_AS_BLOCK' in codes, codes


# ---------------------------------------------------------------------------
# 5) 把 ON-06 错记为"Gateway 没有收到请求" -> 必须 FAIL
# ---------------------------------------------------------------------------

def test_on06_recorded_as_no_arrival_is_rejected():
    claims = load_claims()
    claims['scenarios']['ON06']['gateway_arrival'] = 0
    summary = verify_with_claims(claims)
    assert summary['verdict'] == 'FAIL'
    codes = findings_by_code(summary)
    assert 'TIMEOUT_MISREPORTED_AS_NO_ARRIVAL' in codes, codes
    assert 'GATEWAY_ARRIVAL_MISMATCH' in codes, codes


def test_on06_recorded_as_zero_goals_is_rejected():
    claims = load_claims()
    claims['scenarios']['ON06']['navsim_goals'] = 0
    summary = verify_with_claims(claims)
    assert summary['verdict'] == 'FAIL'
    codes = findings_by_code(summary)
    assert 'TIMEOUT_MISREPORTED_AS_NO_GOAL' in codes, codes


# ---------------------------------------------------------------------------
# 6) 其它语义不变量
# ---------------------------------------------------------------------------

def test_blocked_scenario_claiming_downstream_is_rejected():
    """ON-02 是适配层阻断，不可能有到达/执行/Goal。"""
    claims = load_claims()
    claims['scenarios']['ON02']['navsim_goals'] = 1
    summary = verify_with_claims(claims)
    assert summary['verdict'] == 'FAIL'
    codes = findings_by_code(summary)
    assert 'BLOCK_SCENARIO_CLAIMS_DOWNSTREAM' in codes, codes


def test_blocked_scenario_claiming_allow_is_rejected():
    claims = load_claims()
    claims['scenarios']['ON03']['gateway_decision'] = 'ALLOW'
    summary = verify_with_claims(claims)
    assert summary['verdict'] == 'FAIL'
    codes = findings_by_code(summary)
    assert 'BLOCK_SCENARIO_CLAIMS_ALLOW' in codes, codes


def test_claim_for_unknown_scenario_is_rejected():
    claims = load_claims()
    claims['scenarios']['ON99'] = {'navsim_goals': 0}
    summary = verify_with_claims(claims)
    assert summary['verdict'] == 'FAIL'
    codes = findings_by_code(summary)
    assert 'CLAIM_WITHOUT_EVIDENCE' in codes, codes


def test_claims_absent_means_no_claim_check():
    """不给 claims 时不应误报（声明校验是可选增强，不是必需前提）。"""
    summary = vme.verify_run(EVIDENCE, claims=None)
    assert summary['claims_checked'] is False
    assert summary['verdict'] == 'PASS'


def test_missing_logs_are_not_silently_zero(tmp_path):
    """缺少审计日志时不得默认当作 0 次执行而放行。"""
    import shutil
    work = tmp_path / 'run-empty'
    shutil.copytree(EVIDENCE, work)
    (work / 'gateway_audit.jsonl').write_text('', encoding='utf-8')
    (work / 'navsim_goals.jsonl').write_text('', encoding='utf-8')
    summary = vme.verify_run(str(work), claims=load_claims())
    assert summary['verdict'] == 'FAIL'
    codes = findings_by_code(summary)
    # 声明了到达/执行/Goal，但日志里没有 -> 必须被发现
    assert codes & {'GATEWAY_ARRIVAL_MISMATCH', 'GATEWAY_EXECUTION_MISMATCH',
                    'NAVSIM_GOAL_MISMATCH'}, codes
