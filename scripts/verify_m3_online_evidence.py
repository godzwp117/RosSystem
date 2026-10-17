#!/usr/bin/env python3
"""verify_m3_online_evidence.py -- M3 在线联调跨层证据的**独立**复核工具。

设计目标
--------
按 `request_id` 把下列各层证据关联起来，并检查状态转移与实际执行是否自洽：

    M3 模块输出 -> 适配层决策 -> Planner 结果 -> Gateway DecisionEvent
                -> Action Result -> NavigationSim Goal

本工具**不以关键词是否出现在日志里**作为判据。它从各层提取结构化事实，
再断言层与层之间的**一致性**，因此能发现：

  * request_id 串单（某一层的 request_id 不属于本 run）
  * Gateway BLOCK 却出现下游 Goal
  * 模块阻断却启动了 Planner
  * Action Result 与 NavigationSim Goal 不一致
  * 缺失必要审计事件（RosCommEvent / DecisionEvent）
  * 同一 request_id 的重复事件或重复 Goal
  * 事件时间顺序异常（decision 早于 arrival）

用法
----
    python3 scripts/verify_m3_online_evidence.py --run-dir <证据目录> \
        [--json-out out.json] [--md-out out.md]

退出码：0 = 全部场景通过；1 = 存在 FAIL 发现；2 = 用法/输入错误。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

# 合法的 Gateway 业务原因码（冻结集合，本地副本用于**独立**比对）
GATEWAY_REASON_CODES = {
    'ALLOW_IN_POLICY', 'TASK_MISMATCH', 'INVALID_TARGET', 'OUT_OF_REGION',
    'POLICY_MISSING', 'DUPLICATE_REQUEST', 'RATE_LIMIT', 'EXECUTION_TIMEOUT',
    'AUDIT_UNAVAILABLE',
}
SCENARIOS = ('ON01', 'ON02', 'ON03', 'ON04', 'ON05', 'ON06')


def parse_ts(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(
            timezone.utc)
    except ValueError:
        return None


def load_json(path):
    with open(path, encoding='utf-8') as handle:
        return json.load(handle)


def load_jsonl(path):
    rows = []
    if not os.path.isfile(path):
        return rows
    with open(path, encoding='utf-8') as handle:
        for lineno, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError as exc:
                rows.append({'__parse_error__': str(exc), '__line__': lineno})
    return rows


class Findings:
    def __init__(self):
        self.items = []

    def add(self, scenario, code, ok, detail):
        self.items.append({'scenario': scenario, 'code': code,
                           'ok': bool(ok), 'detail': detail})

    def fail_count(self):
        return sum(1 for i in self.items if not i['ok'])


def audit_by_request(audit_rows):
    """把 Gateway 审计按 request_id 聚合。"""
    index = {}
    for row in audit_rows:
        if '__parse_error__' in row:
            continue
        rid = row.get('request_id')
        if not isinstance(rid, str):
            continue
        bucket = index.setdefault(rid, {'arrivals': [], 'decisions': [],
                                        'executions': [], 'unknown_types': []})
        etype = row.get('event_type')
        if etype == 'RosCommEvent':
            bucket['arrivals'].append(row)
        elif etype == 'DecisionEvent':
            bucket['decisions'].append(row)
        elif etype == 'ExecutionEvent':
            bucket['executions'].append(row)
        else:
            bucket['unknown_types'].append(row)
    return index


def journal_by_request(journal_rows):
    index = {}
    for row in journal_rows:
        rid = row.get('request_id')
        if isinstance(rid, str):
            index.setdefault(rid, []).append(row)
    return index


def scenario_facts(run_dir, cid):
    """读取单个场景的全部层次证据。"""
    facts = {'cid': cid, 'missing': []}
    f0 = os.path.join(run_dir, 'f0_{0}.json'.format(cid))
    if os.path.isfile(f0):
        try:
            facts['f0'] = load_json(f0)
        except ValueError as exc:
            facts['f0'] = None
            facts['missing'].append('f0_{0}.json 解析失败: {1}'.format(cid, exc))
    else:
        facts['f0'] = None
        facts['missing'].append('f0_{0}.json'.format(cid))

    adapter = os.path.join(run_dir, 'adapter_{0}.jsonl'.format(cid))
    facts['adapter_records'] = load_jsonl(adapter)
    if not os.path.isfile(adapter):
        facts['missing'].append('adapter_{0}.jsonl'.format(cid))
    return facts


def verify_scenario(facts, audit_index, journal_index, findings,
                    expected_request_id=None, expected_run_id=None,
                    manifest_entry=None):
    cid = facts['cid']
    f0 = facts['f0']
    if f0 is None:
        findings.add(cid, 'EVIDENCE_MISSING', False,
                     '缺少 f0_{0}.json'.format(cid))
        return {}
    if facts['missing']:
        # 适配层记录缺失属"本该发生却缺失"
        for item in facts['missing']:
            findings.add(cid, 'ADAPTER_LOG_MISSING', False, item)

    decision = f0.get('decision')
    reason = f0.get('reason_code')
    modules = f0.get('modules') or []
    online = f0.get('online') or {}
    m3 = next((m for m in modules if m.get('module') == 'task_risk'), {})
    m3_status = m3.get('status')
    adapter_records = facts['adapter_records']

    # --- 适配层自身的 request_id / run_id 必须与其记录一致 ---
    rid = None
    run_id = None
    if adapter_records:
        first = adapter_records[0]
        rid = first.get('request_id')
        run_id = first.get('run_id')
    if rid is None:
        rid = f0.get('request_id')
        run_id = f0.get('run_id')

    result = {'cid': cid, 'request_id': rid, 'run_id': run_id,
              'adapter_decision': decision, 'adapter_reason': reason,
              'm3_status': m3_status,
              'planner_outcome': online.get('outcome'),
              'planner_started': online.get('outcome') not in (
                  None, 'NOT_SUBMITTED_ADAPTER_BLOCK')}

    if expected_request_id and rid != expected_request_id:
        findings.add(cid, 'REQUEST_ID_MISMATCH', False,
                     '适配层记录 request_id={0!r} 与权威清单 {1!r} 不一致'.format(
                         rid, expected_request_id))
    if expected_run_id and run_id != expected_run_id:
        findings.add(cid, 'RUN_ID_MISMATCH', False,
                     '适配层记录 run_id={0!r} 与权威清单 {1!r} 不一致'.format(
                         run_id, expected_run_id))
    # F0 输出自身的 request_id 也必须与清单一致（防止只改 f0 记录）
    f0_rid = f0.get('request_id')
    if expected_request_id and f0_rid and f0_rid != expected_request_id:
        findings.add(cid, 'F0_REQUEST_ID_MISMATCH', False,
                     'F0 输出 request_id={0!r} 与清单 {1!r} 不一致'.format(
                         f0_rid, expected_request_id))

    # --- 适配层决策记录不得出现跨 request_id 串单 ---
    for rec in adapter_records:
        if rec.get('request_id') not in (None, rid):
            findings.add(cid, 'ADAPTER_REQUEST_ID_DRIFT', False,
                         '适配层记录出现他人 request_id={0!r}'.format(
                             rec.get('request_id')))
            break

    bucket = audit_index.get(rid, {'arrivals': [], 'decisions': [],
                                   'executions': [], 'unknown_types': []})
    goals = journal_index.get(rid, [])
    result['gateway_arrivals'] = len(bucket['arrivals'])
    result['gateway_decisions'] = [
        {'decision': d.get('decision'), 'reason_code': d.get('reason_code')}
        for d in bucket['decisions']]
    result['gateway_executions'] = len(bucket['executions'])
    result['navsim_goals'] = len(goals)

    # --- 非法原因码 / 未知事件类型 ---
    if bucket['unknown_types']:
        findings.add(cid, 'UNKNOWN_AUDIT_EVENT', False,
                     '审计中出现未知 event_type')
    for d in bucket['decisions']:
        if d.get('reason_code') not in GATEWAY_REASON_CODES:
            findings.add(cid, 'ILLEGAL_GATEWAY_REASON_CODE', False,
                         'reason_code={0!r} 不在冻结集合内'.format(
                             d.get('reason_code')))
    if len(bucket['decisions']) > 1:
        findings.add(cid, 'DUPLICATE_DECISION', False,
                     '同一 request_id 出现 {0} 条 DecisionEvent'.format(
                         len(bucket['decisions'])))
    if len(bucket['arrivals']) > 1:
        findings.add(cid, 'DUPLICATE_ARRIVAL', False,
                     '同一 request_id 出现 {0} 条 RosCommEvent'.format(
                         len(bucket['arrivals'])))
    if len(goals) > 1:
        findings.add(cid, 'DUPLICATE_GOAL', False,
                     '同一 request_id 出现 {0} 条 Goal'.format(len(goals)))
    for goal in goals:
        if goal.get('request_id') != rid:
            findings.add(cid, 'GOAL_REQUEST_ID_CORRUPT', False,
                         'Goal 的 request_id 与索引不一致')

    # --- 时间顺序：decision 不得早于 arrival ---
    if bucket['arrivals'] and bucket['decisions']:
        a = parse_ts(bucket['arrivals'][0].get('received_at'))
        dtime = parse_ts(bucket['decisions'][0].get('decision_at'))
        if a and dtime and dtime < a:
            findings.add(cid, 'TIME_ORDER_VIOLATION', False,
                         'DecisionEvent 早于 RosCommEvent')

    # --- 到达 Gateway 的请求必须留下 DecisionEvent（不允许"只到达不判定"）---
    if bucket['arrivals'] and not bucket['decisions']:
        findings.add(cid, 'ARRIVAL_WITHOUT_DECISION', False,
                     '有 {0} 条 RosCommEvent 但无 DecisionEvent'.format(
                         len(bucket['arrivals'])))

    # --- 场景级状态转移 ---
    if decision == 'READY_FOR_GATEWAY_SUBMISSION':
        findings.add(cid, 'M3_PROPOSED', m3_status == 'ALLOW_RECOMMENDED',
                     'M3 状态={0!r}'.format(m3_status))
        # 必须真的提交给 Gateway（除非 Planner 超时/失败）
        submitted = bool(bucket['arrivals'])
        if online.get('outcome') == 'PLANNER_RESULT_TIMEOUT':
            # 超时：可能已到达也可能未到达，但**不得**记为 BLOCK；
            # 只要有 arrival 就必须有对应 decision
            findings.add(cid, 'TIMEOUT_NOT_BLOCK', True,
                         '超时未记为 Gateway BLOCK（outcome={0}）'.format(
                             online.get('outcome')))
            if submitted and not bucket['decisions']:
                findings.add(cid, 'TIMEOUT_MISSING_DECISION', False,
                             '有 arrival 但无 DecisionEvent，无法判定执行状态')
        else:
            findings.add(cid, 'SUBMITTED_TO_GATEWAY', submitted,
                         'Gateway arrival={0}'.format(len(bucket['arrivals'])))
        # ALLOW 场景：Action Result 与 Goal 必须一致
        pr = online.get('planner_result') or {}
        status_code = pr.get('status_code')
        if decision == 'READY_FOR_GATEWAY_SUBMISSION' and status_code == 'EXECUTED':
            findings.add(cid, 'ACTION_RESULT_GOAL_CONSISTENT',
                         len(goals) == 1,
                         'Action Result=EXECUTED 且 Goal 数={0}'.format(len(goals)))
    elif decision == 'ADAPTER_BLOCK':
        # 适配层阻断：不得启动 Planner、不得有 Gateway arrival、不得有 Goal
        findings.add(cid, 'BLOCK_NO_PLANNER',
                     online.get('outcome') == 'NOT_SUBMITTED_ADAPTER_BLOCK',
                     'outcome={0!r}'.format(online.get('outcome')))
        findings.add(cid, 'BLOCK_NO_GATEWAY_ARRIVAL', not bucket['arrivals'],
                     'Gateway arrival={0}'.format(len(bucket['arrivals'])))
        findings.add(cid, 'BLOCK_NO_GOAL', not goals,
                     'Goal 数={0}'.format(len(goals)))
        # Gateway BLOCK 语义：没有 execution，且（若有决策）必须为 BLOCK
        findings.add(cid, 'BLOCK_NO_EXECUTION', not bucket['executions'],
                     'ExecutionEvent={0}'.format(len(bucket['executions'])))
    else:
        findings.add(cid, 'UNEXPECTED_ADAPTER_DECISION', False,
                     'decision={0!r}'.format(decision))

    # --- Gateway BLOCK 却出现 Goal：无论哪个场景都必须失败 ---
    if bucket['decisions']:
        gw = bucket['decisions'][0].get('decision')
        if gw == 'BLOCK' and goals:
            findings.add(cid, 'BLOCK_BUT_GOAL_EXISTS', False,
                         'Gateway BLOCK 却出现 {0} 条 Goal'.format(len(goals)))
        if gw == 'BLOCK' and bucket['executions']:
            findings.add(cid, 'BLOCK_BUT_EXECUTED', False,
                         'Gateway BLOCK 却出现 ExecutionEvent')
    return result


def load_manifest(run_dir):
    """读取本 run 的**权威清单**（由驱动器写入）。

    为什么需要它：若"期望 request_id"取自适配层自己的记录，那么把适配层记录
    整体改掉也能通过，形成**自证循环**。清单由驱动器在各场景**执行前**写入，
    为复核提供外部基准，使串单检查具备真实判别力。
    """
    path = os.path.join(run_dir, 'manifest.json')
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding='utf-8') as handle:
            return json.load(handle)
    except ValueError:
        return None


#: 声明中表示"客户端未观测到结果"的保留字，用于超时场景。
UNOBSERVED = 'UNOBSERVED'


def validate_claims(summary, claims):
    """校验**报告声明**与**实测证据**是否一致。

    为什么需要它：2026-10-16 的收尾报告曾把 ON-06（Planner 超时）表述为
    "Gateway 无决策、Goal 0"，而原始审计显示该请求实际被 ALLOW 且已执行。
    该错误由**人工书写**引入，原始日志与校验器本身都是对的。
    因此这里把"报告怎么说"也纳入机器校验：声明与证据不一致即报 FAIL。

    claims 结构::

        {"scenarios": {"ON06": {
            "planner_outcome": "PLANNER_RESULT_TIMEOUT",
            "gateway_arrival": 1,
            "gateway_decision": "ALLOW",
            "gateway_reason_code": "ALLOW_IN_POLICY",
            "gateway_execution": 1,
            "navsim_goals": 1
        }, ...}}

    缺失的声明键表示"不作声称"，不参与比对（避免把未写的字段当成 0）。
    """
    findings = Findings()
    # 允许声明文件省略 run_id（模板可跨 run 复用：CID -> 期望事实与具体
    # request_id 无关，request_id 由 manifest 提供并单独校验）
    if not isinstance(claims, dict) or not isinstance(claims.get('scenarios'), dict):
        findings.add('GLOBAL', 'CLAIMS_MALFORMED', False,
                     'claims 必须形如 {"scenarios": {CID: {...}}}')
        return findings
    by_cid = {row.get('cid'): row for row in summary.get('scenarios') or []}

    def compare(cid, key, claimed, actual, code):
        if claimed is None:
            return
        findings.add(cid, code, claimed == actual,
                     '声明 {0}={1!r} vs 实测 {2!r}'.format(key, claimed, actual))

    for cid, claim in claims['scenarios'].items():
        if cid not in by_cid:
            findings.add(cid, 'CLAIM_WITHOUT_EVIDENCE', False,
                         '声明了 {0} 但证据中没有该场景'.format(cid))
            continue
        row = by_cid[cid]
        decisions = row.get('gateway_decisions') or []
        actual_decision = decisions[0].get('decision') if decisions else None
        actual_reason = decisions[0].get('reason_code') if decisions else None

        compare(cid, 'planner_outcome', claim.get('planner_outcome'),
                row.get('planner_outcome'), 'PLANNER_OUTCOME_MISMATCH')
        compare(cid, 'gateway_arrival', claim.get('gateway_arrival'),
                row.get('gateway_arrivals'), 'GATEWAY_ARRIVAL_MISMATCH')
        compare(cid, 'gateway_decision', claim.get('gateway_decision'),
                actual_decision, 'GATEWAY_DECISION_MISMATCH')
        compare(cid, 'gateway_reason_code', claim.get('gateway_reason_code'),
                actual_reason, 'GATEWAY_REASON_MISMATCH')
        compare(cid, 'gateway_execution', claim.get('gateway_execution'),
                row.get('gateway_executions'), 'GATEWAY_EXECUTION_MISMATCH')
        compare(cid, 'navsim_goals', claim.get('navsim_goals'),
                row.get('navsim_goals'), 'NAVSIM_GOAL_MISMATCH')

        # ---- 语义不变量：防止"超时 = 未执行/被拒绝"这类错误复现 ----
        if claim.get('planner_outcome') == 'PLANNER_RESULT_TIMEOUT':
            # 超时只说明客户端未观测到终态，绝不能据此断定未到达 / BLOCK / 未执行
            if claim.get('gateway_decision') == 'BLOCK':
                findings.add(cid, 'TIMEOUT_MISREPORTED_AS_BLOCK', False,
                             '把 Planner 超时记为 Gateway BLOCK；超时不是拒绝证据')
            if claim.get('gateway_arrival') == 0:
                findings.add(cid, 'TIMEOUT_MISREPORTED_AS_NO_ARRIVAL', False,
                             '把 Planner 超时记为 Gateway 未收到请求；超时不能证明未到达')
            if claim.get('gateway_execution') == 0 and (row.get('gateway_executions') or 0) > 0:
                findings.add(cid, 'TIMEOUT_MISREPORTED_AS_NOT_EXECUTED', False,
                             '声明超时未执行，但审计中存在 ExecutionEvent')
            if claim.get('navsim_goals') == 0 and (row.get('navsim_goals') or 0) > 0:
                findings.add(cid, 'TIMEOUT_MISREPORTED_AS_NO_GOAL', False,
                             '声明超时 Goal 为 0，但 journal 中存在对应 Goal')

        # 适配层阻断的场景：不得声称到达 / 决策 / 执行 / Goal
        if claim.get('adapter_decision') == 'ADAPTER_BLOCK':
            for key, field in (('gateway_arrival', 'gateway_arrivals'),
                               ('gateway_execution', 'gateway_executions'),
                               ('navsim_goals', 'navsim_goals')):
                if claim.get(key) not in (None, 0):
                    findings.add(cid, 'BLOCK_SCENARIO_CLAIMS_DOWNSTREAM', False,
                                 '阻断场景不得声称 {0}={1!r}'.format(key, claim[key]))
            if claim.get('gateway_decision') == 'ALLOW':
                findings.add(cid, 'BLOCK_SCENARIO_CLAIMS_ALLOW', False,
                             '适配层已阻断，不可能出现 Gateway ALLOW')
    return findings


def verify_run(run_dir, require_manifest=True, claims=None):
    findings = Findings()
    manifest = load_manifest(run_dir)
    expected_by_cid = {}
    if manifest is None:
        if require_manifest:
            findings.add('GLOBAL', 'MANIFEST_MISSING', False,
                         '缺少 manifest.json，无法独立核验 request_id 归属'
                         '（为避免自证循环，这是失败而非放行）')
    else:
        for entry in manifest.get('scenarios') or []:
            if isinstance(entry, dict) and entry.get('cid'):
                expected_by_cid[entry['cid']] = entry
    audit_rows = load_jsonl(os.path.join(run_dir, 'gateway_audit.jsonl'))
    journal_rows = load_jsonl(os.path.join(run_dir, 'navsim_goals.jsonl'))
    audit_index = audit_by_request(audit_rows)
    journal_index = journal_by_request(journal_rows)

    results = []
    for cid in SCENARIOS:
        facts = scenario_facts(run_dir, cid)
        if facts['f0'] is None and not facts['adapter_records']:
            findings.add(cid, 'NOT_RUN', True, '该场景本轮未执行')
            continue
        expected = expected_by_cid.get(cid) or {}
        results.append(verify_scenario(
            facts, audit_index, journal_index, findings,
            expected_request_id=expected.get('request_id'),
            expected_run_id=expected.get('run_id'),
            manifest_entry=expected))

    # 全局：审计里的 request_id 必须都属于本 run 的已知场景
    known = {r.get('request_id') for r in results if r.get('request_id')}
    for rid in audit_index:
        if rid not in known:
            findings.add('GLOBAL', 'ORPHAN_AUDIT_REQUEST', False,
                         '审计中出现不属于任何场景的 request_id={0!r}'.format(rid))
    for rid in journal_index:
        if rid not in known:
            findings.add('GLOBAL', 'ORPHAN_GOAL_REQUEST', False,
                         'journal 中出现不属于任何场景的 request_id={0!r}'.format(rid))

    if claims is not None:
        claim_findings = validate_claims(
            {'scenarios': results}, claims)
        findings.items.extend(claim_findings.items)

    summary = {
        'run_dir': os.path.abspath(run_dir),
        'claims_checked': bool(claims),
        'manifest_used': manifest is not None,
        'manifest_scenarios': sorted(expected_by_cid),
        'gateway_audit_rows': len(audit_rows),
        'navsim_goal_rows': len(journal_rows),
        'scenarios_verified': len(results),
        'scenarios': results,
        'findings': findings.items,
        'failures': findings.fail_count(),
        'checks': len(findings.items),
        'verdict': 'PASS' if findings.fail_count() == 0 else 'FAIL',
    }
    return summary


def render_markdown(summary):
    lines = ['# M3 在线联调证据复核（独立工具输出）', '']
    lines.append('- 证据目录：`{0}`'.format(summary['run_dir']))
    lines.append('- Gateway 审计行数：{0}'.format(summary['gateway_audit_rows']))
    lines.append('- NavigationSim Goal 行数：{0}'.format(
        summary['navsim_goal_rows']))
    lines.append('- 复核检查项：{0}（失败 {1}）'.format(
        summary['checks'], summary['failures']))
    lines.append('- **判定：`{0}`**'.format(summary['verdict']))
    lines.append('')
    lines.append('## 场景关联表')
    lines.append('')
    lines.append('| 场景 | request_id | 适配层决策 | M3 状态 | Planner outcome | Gateway arrival | Gateway decision | Execution | Goal 数 |')
    lines.append('| --- | --- | --- | --- | --- | --- | --- | --- | --- |')
    for row in summary['scenarios']:
        gw = ','.join('{0}/{1}'.format(d.get('decision'), d.get('reason_code'))
                      for d in row.get('gateway_decisions') or []) or '-'
        lines.append('| {0} | `{1}` | {2} | {3} | {4} | {5} | {6} | {7} | {8} |'.format(
            row.get('cid'), row.get('request_id'), row.get('adapter_decision'),
            row.get('m3_status'), row.get('planner_outcome'),
            row.get('gateway_arrivals'), gw, row.get('gateway_executions'),
            row.get('navsim_goals')))
    lines.append('')
    lines.append('## 检查明细')
    lines.append('')
    for item in summary['findings']:
        mark = 'PASS' if item['ok'] else 'FAIL'
        lines.append('- [{0}] `{1}` {2} :: {3}'.format(
            mark, item['scenario'], item['code'], item['detail']))
    lines.append('')
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description='M3 在线联调跨层证据复核')
    parser.add_argument('--run-dir', required=True)
    parser.add_argument('--json-out')
    parser.add_argument('--md-out')
    parser.add_argument('--claims',
                        help='报告声明 JSON（{scenarios:{CID:{...}}}）；给定时'
                             '额外校验报告表述与实测证据是否一致')
    args = parser.parse_args(argv)

    if not os.path.isdir(args.run_dir):
        sys.stderr.write('run-dir 不存在: {0}\n'.format(args.run_dir))
        return 2
    claims = None
    if args.claims:
        with open(args.claims, encoding='utf-8') as handle:
            claims = json.load(handle)
    summary = verify_run(args.run_dir, claims=claims)
    text = json.dumps(summary, ensure_ascii=False, indent=2)
    if args.json_out:
        with open(args.json_out, 'w', encoding='utf-8') as handle:
            handle.write(text)
    if args.md_out:
        with open(args.md_out, 'w', encoding='utf-8') as handle:
            handle.write(render_markdown(summary))
    print(text)
    return 0 if summary['failures'] == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
