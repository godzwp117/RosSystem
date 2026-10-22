#!/usr/bin/env python3
"""verify_final_controlled_online.py -- 受控在线模式的 request_id 级严格验收。

为什么需要它
============
旧的 `final_system.sh` 只检查"审计行数 >= 2 且 Goal 行数 >= 1"。
这个断言无法证明**每个请求**的 Gateway 决策都是对的：
两个请求都 BLOCK 但恰好有一条无关 Goal，也会通过。

本工具按 request_id 逐条核对三个场景的不变量，
数据全部来自**原始** F0 输出、Gateway audit 与 NavigationSim journal，
不读取任何总结文本。

三个场景的不变量
================
ON-01 合法允许：
    F0 READY；Planner 提交；Gateway 到达恰好 1；决策 ALLOW/ALLOW_IN_POLICY；
    有且仅有 1 条 ExecutionEvent；NavSim 恰好 1 条对应 Goal。

ON-02 适配器拒绝：
    F0 ADAPTER_BLOCK；Planner 未提交；Gateway 到达 0；NavSim Goal 0。
    **不得**用 F0 输出里的 gateway_submission=null 推断 Gateway 未收到 ——
    必须由真实审计的 request_id 计数证明。

ON-05 Gateway 独立阻断：
    M3 ALLOW_RECOMMENDED；F0 READY；Planner 提交；Gateway 到达 1；
    决策 BLOCK/OUT_OF_REGION；**不得**有表示成功的 ExecutionEvent；
    NavSim Goal 0。

退出码：0 = VERDICT=PASS；非零 = VERDICT=FAIL（附逐条失败原因）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

SCENARIOS = ('ON01', 'ON02', 'ON05')

#: 场景 -> (期望 F0 决策前缀, 期望 Gateway 到达数, 期望决策, 期望 reason, 期望 Goal 数)
EXPECT = {
    'ON01': {'f0': 'READY_FOR_GATEWAY_SUBMISSION', 'arrivals': 1,
             'decision': 'ALLOW', 'reason': 'ALLOW_IN_POLICY',
             'executions': 1, 'goals': 1},
    'ON02': {'f0': 'ADAPTER_BLOCK', 'arrivals': 0,
             'decision': None, 'reason': None, 'executions': 0, 'goals': 0},
    'ON05': {'f0': 'READY_FOR_GATEWAY_SUBMISSION', 'arrivals': 1,
             'decision': 'BLOCK', 'reason': 'OUT_OF_REGION',
             'executions': 0, 'goals': 0},
}


def load_jsonl(path):
    if not os.path.exists(path):
        return None
    rows = []
    try:
        with open(path, encoding='utf-8') as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rows.append(json.loads(line))
    except (ValueError, OSError):
        return 'CORRUPT'
    return rows


def load_json(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except (ValueError, OSError):
        return 'CORRUPT'


class Findings:
    def __init__(self):
        self.items = []

    def add(self, scenario, code, ok, detail=''):
        self.items.append({'scenario': scenario, 'code': code,
                           'ok': bool(ok), 'detail': detail})

    def check(self, scenario, code, condition, detail=''):
        self.add(scenario, code, condition, '' if condition else detail)
        return condition

    @property
    def failures(self):
        return [i for i in self.items if not i['ok']]

    def verdict(self):
        return 'PASS' if not self.failures else 'FAIL'


def resolve_run_id(manifest, audit, journal):
    """run_id 必须能从 manifest 读到一个确定值，并与 request_id 后缀一致。"""
    if isinstance(manifest, dict) and manifest.get('run_id'):
        return manifest['run_id']
    for rows in (audit, journal):
        if isinstance(rows, list):
            for row in rows:
                rid = row.get('request_id') or ''
                # request_id 形如 on01-xxx-<run_id>
                for prefix in ('on01-', 'on02-', 'on05-'):
                    if rid.startswith(prefix):
                        return rid[len(prefix):]
    return None


def verify(run_dir):
    findings = Findings()
    audit = load_jsonl(os.path.join(run_dir, 'gateway_audit.jsonl'))
    journal = load_jsonl(os.path.join(run_dir, 'navsim_goals.jsonl'))
    manifest = load_json(os.path.join(run_dir, 'manifest.json'))

    findings.check('GLOBAL', 'AUDIT_PRESENT', isinstance(audit, list) and audit,
                   '网关审计缺失或损坏')
    findings.check('GLOBAL', 'JOURNAL_PRESENT', isinstance(journal, list),
                   'NavigationSim journal 缺失或损坏')
    findings.check('GLOBAL', 'MANIFEST_PRESENT', isinstance(manifest, dict),
                   'manifest 缺失或损坏')
    if not isinstance(audit, list) or not isinstance(journal, list):
        return findings, {}

    run_id = resolve_run_id(manifest, audit, journal)
    findings.check('GLOBAL', 'RUN_ID_RESOLVED', bool(run_id), '无法确定 run_id')

    expected_ids = {}
    if isinstance(manifest, dict):
        for entry in manifest.get('scenarios') or []:
            if entry.get('cid') in SCENARIOS and entry.get('request_id'):
                expected_ids[entry['cid']] = entry['request_id']

    facts = {'run_id': run_id, 'scenarios': {}}
    known_ids = set(expected_ids.values())

    for cid in SCENARIOS:
        expect = EXPECT[cid]
        want_rid = expected_ids.get(cid)
        if not want_rid:
            findings.add(cid, 'REQUEST_ID_IN_MANIFEST', False,
                         'manifest 中缺少该场景的 request_id')
            continue

        # run_id 必须一致：request_id 必须以 -<run_id> 结尾
        if run_id:
            findings.check(cid, 'REQUEST_ID_MATCHES_RUN',
                           want_rid.endswith(run_id),
                           f'request_id {want_rid!r} 与 run_id {run_id!r} 不匹配')

        # ---- F0 ----
        f0 = load_json(os.path.join(run_dir, f'f0_{cid}.json'))
        findings.check(cid, 'F0_PRESENT', isinstance(f0, dict), 'F0 输出缺失或损坏')
        f0_decision = f0.get('decision') if isinstance(f0, dict) else None
        findings.check(cid, 'F0_DECISION',
                       f0_decision == expect['f0'],
                       f'F0 决策 {f0_decision!r} != 期望 {expect["f0"]!r}')

        # ---- Planner 提交状态：以 F0 的 online.outcome 为**线索**，
        #      真实到达仍以审计为准（下文的 ARRIVALS）
        online = (f0.get('online') or {}) if isinstance(f0, dict) else {}
        submitted = online.get('outcome') in (
            'PLANNER_RESULT_RECEIVED', 'PLANNER_RESULT_TIMEOUT')
        if expect['arrivals'] == 0:
            findings.check(cid, 'PLANNER_NOT_SUBMITTED', not submitted,
                           f'期望未提交，但 online.outcome={online.get("outcome")!r}')
        else:
            findings.check(cid, 'PLANNER_SUBMITTED', submitted,
                           f'期望已提交，但 online.outcome={online.get("outcome")!r}')

        # ---- Gateway 审计（按 request_id 真实计数）----
        rows = [r for r in audit if r.get('request_id') == want_rid]
        arrivals = [r for r in rows if r.get('event_type') == 'RosCommEvent']
        decisions = [r for r in rows if r.get('event_type') == 'DecisionEvent']
        executions = [r for r in rows if r.get('event_type') == 'ExecutionEvent']

        findings.check(cid, 'GATEWAY_ARRIVAL_COUNT',
                       len(arrivals) == expect['arrivals'],
                       f'到达 {len(arrivals)} 次，期望 {expect["arrivals"]}')
        findings.check(cid, 'GATEWAY_DECISION_COUNT',
                       len(decisions) == (1 if expect['decision'] else 0),
                       f'决策事件 {len(decisions)} 条，期望 '
                       f'{1 if expect["decision"] else 0}')

        if expect['decision']:
            got = decisions[0].get('decision') if decisions else None
            findings.check(cid, 'GATEWAY_DECISION', got == expect['decision'],
                           f'Gateway 决策 {got!r} != 期望 {expect["decision"]!r}')
            got_reason = decisions[0].get('reason_code') if decisions else None
            findings.check(cid, 'GATEWAY_REASON', got_reason == expect['reason'],
                           f'reason_code {got_reason!r} != 期望 {expect["reason"]!r}')

        findings.check(cid, 'GATEWAY_EXECUTION_COUNT',
                       len(executions) == expect['executions'],
                       f'执行事件 {len(executions)} 条，期望 {expect["executions"]}')
        # ON-05 特别要求：不得有表示成功执行的事件
        if cid == 'ON05':
            successes = [e for e in executions
                         if str(e.get('outcome') or e.get('status') or '').upper()
                         in ('SUCCESS', 'EXECUTED', 'OK')]
            findings.check(cid, 'NO_SUCCESSFUL_EXECUTION', not successes,
                           f'被 BLOCK 的请求出现成功执行事件: {successes[:1]}')

        # ---- NavigationSim ----
        goals = [g for g in journal if g.get('request_id') == want_rid]
        findings.check(cid, 'NAVSIM_GOAL_COUNT',
                       len(goals) == expect['goals'],
                       f'Goal {len(goals)} 个，期望 {expect["goals"]}')
        if goals:
            findings.check(cid, 'GOAL_HAS_ID', all(g.get('goal_id') for g in goals),
                           'Goal 缺少 goal_id')
            findings.check(cid, 'GOAL_ACTION_MATCH',
                           all(g.get('action') == '/rg/nav_execute' for g in goals),
                           'Goal 的 action 不是 /rg/nav_execute')

        facts['scenarios'][cid] = {
            'request_id': want_rid,
            'f0_decision': f0_decision,
            'planner_outcome': online.get('outcome'),
            'gateway_arrivals': len(arrivals),
            'gateway_decisions': [d.get('decision') for d in decisions],
            'gateway_reasons': [d.get('reason_code') for d in decisions],
            'gateway_executions': len(executions),
            'navsim_goals': len(goals),
            'goal_ids': [g.get('goal_id') for g in goals],
        }

    # ---- 跨请求隔离：审计与 journal 不得出现未知 request_id ----
    unknown_audit = {r.get('request_id') for r in audit
                     if r.get('request_id') and r.get('request_id') not in known_ids}
    unknown_journal = {g.get('request_id') for g in journal
                       if g.get('request_id') and g.get('request_id') not in known_ids}
    findings.check('GLOBAL', 'NO_FOREIGN_AUDIT_REQUESTS', not unknown_audit,
                   f'审计中出现无关 request_id: {sorted(unknown_audit)}')
    findings.check('GLOBAL', 'NO_FOREIGN_JOURNAL_GOALS', not unknown_journal,
                   f'journal 中出现无关 request_id: {sorted(unknown_journal)}')

    # ---- 重复事件 ----
    for cid in SCENARIOS:
        want = expected_ids.get(cid)
        if not want:
            continue
        decisions = [r for r in audit
                     if r.get('request_id') == want
                     and r.get('event_type') == 'DecisionEvent']
        findings.check(cid, 'NO_DUPLICATE_DECISION', len(decisions) <= 1,
                       f'同一 request_id 出现 {len(decisions)} 条 DecisionEvent')

    return findings, facts


def main(argv=None):
    parser = argparse.ArgumentParser(description='受控在线 request_id 级严格验收')
    parser.add_argument('--run-dir', required=True,
                        help='包含 gateway_audit.jsonl / navsim_goals.jsonl / manifest.json / f0_ON*.json')
    parser.add_argument('--json-out', default=None)
    parser.add_argument('--md-out', default=None)
    args = parser.parse_args(argv)

    findings, facts = verify(args.run_dir)
    document = {
        'contract': 'final-controlled-verifier/1',
        'run_dir': args.run_dir,
        'checks': len(findings.items),
        'failures': len(findings.failures),
        'verdict': findings.verdict(),
        'facts': facts,
        'results': findings.items,
    }
    if args.json_out:
        os.makedirs(os.path.dirname(os.path.abspath(args.json_out)), exist_ok=True)
        with open(args.json_out, 'w', encoding='utf-8') as fh:
            json.dump(document, fh, ensure_ascii=False, indent=2)
    if args.md_out:
        lines = ['# 受控在线 request_id 级验收', '',
                 f'- 目录：`{args.run_dir}`',
                 f'- 检查：{document["checks"]} 项，失败 {document["failures"]} 项',
                 f'- 结论：**{document["verdict"]}**', '',
                 '| 场景 | request_id | F0 | Gateway 到达 | 决策 | Goal |',
                 '| --- | --- | --- | --- | --- | --- |']
        for cid, row in facts.get('scenarios', {}).items():
            lines.append('| {0} | `{1}` | {2} | {3} | {4} | {5} |'.format(
                cid, row['request_id'], row['f0_decision'],
                row['gateway_arrivals'],
                ','.join(str(d) for d in row['gateway_decisions']) or '-',
                row['navsim_goals']))
        if findings.failures:
            lines += ['', '## 失败项', '']
            for item in findings.failures:
                lines.append('- `{0}` / `{1}`：{2}'.format(
                    item['scenario'], item['code'], item['detail']))
        with open(args.md_out, 'w', encoding='utf-8') as fh:
            fh.write('\n'.join(lines) + '\n')

    print(json.dumps({'verdict': document['verdict'], 'checks': document['checks'],
                      'failures': document['failures'],
                      'failed': [i['code'] for i in findings.failures][:8]},
                     ensure_ascii=False, indent=2))
    return 0 if document['verdict'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
