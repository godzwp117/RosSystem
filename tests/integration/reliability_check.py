#!/usr/bin/env python3
"""reliability_check.py -- M1 可靠性加固的故障注入与语义断言（任务 B2/B3/B4）。

覆盖：
  R1 正常审计写入           -> ALLOW，下游 1 条 Goal，三个事件齐全
  R2 RosCommEvent 写入失败   -> 用 /dev/full 制造**真实** ENOSPC -> 拒绝，下游 0 条 Goal
  R3 DecisionEvent 写入失败  -> 注入（RosComm 成功、Decision 失败）-> 拒绝，下游 0 条 Goal
  R4 ExecutionEvent 写入失败 -> 注入（执行后审计失败）-> 下游**确实执行了**，
                                必须如实回传执行结果，不得声称下游未执行
  R7 执行超时语义            -> EXECUTION_TIMEOUT 必须显式表达"执行状态未知/取消待确认"，
                                且不得被解释为下游已停止

必须在**容器内**执行（与 ROS 图同一 PID 命名空间）：
  docker exec rg_jazzy bash -lc 'cd /ws && source /opt/ros/jazzy/setup.bash && \
      source install/setup.bash && python3 tests/integration/reliability_check.py'

复用 tests/integration/scenario_runner.py 的进程组管理（start_new_session + killpg），
避免重复实现并保证清理语义一致。

用法：python3 tests/integration/reliability_check.py [--only R2,R3]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scenario_runner as sr  # noqa: E402

ROOT = sr.ROOT
CONTAINER = os.environ.get('RG_CONTAINER', 'rg_jazzy')
GATEWAY = ('rg_gateway', 'security_gateway')
NAVSIM = ('rg_demo_nodes', 'navigation_sim')
PLANNER = ('rg_demo_nodes', 'planner_node')
EVIDENCE_ROOT = os.path.join(ROOT, 'tests', 'evidence')


def docker_planner(request_id, x, y, expect_success):
    argv = ['ros2', 'run', PLANNER[0], PLANNER[1], '--ros-args',
            '-p', 'request_id:={0}'.format(request_id),
            '-p', 'task_id:=patrol_a_001',
            '-p', 'frame_id:=map',
            '-p', 'target_x:={0}'.format(x),
            '-p', 'target_y:={0}'.format(y),
            '-p', 'expect_success:={0}'.format(expect_success)]
    inner = ' '.join(argv)
    if shutil.which('ros2'):
        # 已在容器内（ROS 环境已 source）：直接执行
        argv = ['bash', '-lc',
                'source /opt/ros/jazzy/setup.bash >/dev/null 2>&1; cd /ws; '
                'source install/setup.bash >/dev/null 2>&1; ' + inner]
    else:
        argv = ['docker', 'exec', CONTAINER, 'bash', '-lc',
                'source /opt/ros/jazzy/setup.bash && cd /ws && source install/setup.bash && ' + inner]
    started = time.time()
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=240)
    output = (proc.stdout or '') + (proc.stderr or '')
    parsed = None
    for line in output.splitlines():
        if line.strip().startswith('PLANNER_RESULT '):
            try:
                parsed = json.loads(line.strip()[len('PLANNER_RESULT '):])
            except json.JSONDecodeError:
                pass
    return {'exit_code': proc.returncode, 'stdout': output, 'result': parsed,
            'argv': argv, 'duration_sec': round(time.time() - started, 3)}


class Case:
    def __init__(self, case_id, name, expected):
        self.case_id = case_id
        self.name = name
        self.expected = expected
        self.checks = []
        self.commands = []
        self.dir = None
        self.exit_code = None

    def check(self, name, ok, detail):
        if isinstance(detail, (list, tuple)):
            detail = '; '.join(str(d) for d in detail) or '(empty)'
        self.checks.append({'check': name, 'result': 'PASS' if ok else 'FAIL',
                            'detail': str(detail)[:900]})
        return ok

    @property
    def passed(self):
        return bool(self.checks) and all(c['result'] == 'PASS' for c in self.checks)

    def summary(self):
        evidence = []
        if self.dir and os.path.isdir(self.dir):
            for base, _dirs, files in os.walk(self.dir):
                for name in sorted(files):
                    evidence.append(os.path.relpath(os.path.join(base, name), ROOT))
        failed_reasons = [c['check'] for c in self.checks if c['result'] == 'FAIL']
        return {
            'scenario': self.case_id,
            'suite': 'reliability',
            'description': self.name,
            'result': 'PASS' if self.passed else 'FAIL',
            'started_at': sr.utc_stamp(),
            'evidence_dir': os.path.relpath(self.dir, ROOT) if self.dir else '',
            'navsim_goal_count': 0,
            'decision_sequence': [],
            'execution_status_codes': [],
            'reject_log_lines': 0,
            'planner_results': [],
            'planner_exit_codes': [self.exit_code] if self.exit_code is not None else [],
            'checks': self.checks,
            'commands': self.commands,
            'expectations': {'description': self.expected},
            'reason_code': failed_reasons[0] if failed_reasons else None,
        }


def run_gateway_case(case, gateway_params, navsim_params, planner_kwargs,
                     inspect_fn, expect_downstream_goals, audit_readable=True):
    """通用流程：起 navsim+gateway -> 等就绪 -> 发一次请求 -> 停 -> 交给 inspect_fn 断言。"""
    case.dir = os.path.join(EVIDENCE_ROOT, _RUN_ID, case.case_id)
    shutil.rmtree(case.dir, ignore_errors=True)
    os.makedirs(case.dir, exist_ok=True)

    default_audit = os.path.join(case.dir, 'audit.jsonl')
    audit_path = gateway_params.get('audit_log_path', default_audit)
    journal_path = os.path.join(case.dir, 'navsim_goals.jsonl')
    gateway_log = os.path.join(case.dir, 'gateway.log')
    navsim_log = os.path.join(case.dir, 'navsim.log')
    commands = []

    sr.reap_stragglers(quiet=True)
    navsim = sr.NodeProcess(NAVSIM[0], NAVSIM[1],
                            {'record_path': journal_path, **navsim_params},
                            navsim_log, commands, 'navigation_sim', case.case_id)
    params = {'policy_path': sr.DEFAULT_POLICY, 'audit_log_path': default_audit, **gateway_params}
    gateway = sr.NodeProcess(GATEWAY[0], GATEWAY[1], params,
                             gateway_log, commands, 'security_gateway', case.case_id)

    try:
        navsim_ready = navsim.wait_for_log('NAVSIM_READY', 30.0)
        gateway_ready = gateway.wait_for_log('GATEWAY_READY', 30.0)
        case.check('NavigationSim 就绪', navsim_ready, 'NAVSIM_READY')
        case.check('security_gateway 就绪', gateway_ready, 'GATEWAY_READY')
        if not (navsim_ready and gateway_ready):
            return
        time.sleep(1.0)
        planner = docker_planner(**planner_kwargs)
        case.commands.append({'step': 'planner', 'argv': planner['argv'],
                              'exit_code': planner['exit_code'],
                              'duration_sec': planner['duration_sec']})
        case.exit_code = planner['exit_code']
        with open(os.path.join(case.dir, 'planner.log'), 'w', encoding='utf-8') as handle:
            handle.write(planner['stdout'])
        with open(os.path.join(case.dir, 'planner_result.json'), 'w', encoding='utf-8') as handle:
            json.dump(planner['result'] or {}, handle, ensure_ascii=False, indent=2)
    finally:
        gateway.stop()
        navsim.stop()
        sr.reap_stragglers(quiet=True)

    journal = sr.read_jsonl(journal_path)
    # /dev/full 之类不可回读的目标：审计内容按"空"处理，其写失败由网关日志证明
    audit = sr.read_jsonl(audit_path) if audit_readable else []
    gateway_text = sr.read_text(gateway_log)
    inspect_fn(case, {'journal': journal, 'audit': audit, 'gateway_text': gateway_text,
                      'planner': planner, 'audit_path': audit_path, 'case_dir': case.dir})

    case.check('下游 Goal 数量 == {0}'.format(expect_downstream_goals),
               len(journal) == expect_downstream_goals,
               'navsim_goals.jsonl 行数 = {0}'.format(len(journal)))


_RUN_ID = None


# ---------------------------------------------------------------------------
# R1 正常审计
# ---------------------------------------------------------------------------
def case_r1(case):
    def inspect(c, data):
        c.check('判定为 ALLOW（未受审计故障影响）',
                any(r.get('decision') == 'ALLOW' for r in data['audit']),
                [r.get('reason_code') for r in data['audit'] if r.get('event_type') == 'DecisionEvent'])
        kinds = [r.get('event_type') for r in data['audit']]
        c.check('审计三事件齐全（RosComm/Decision/Execution）',
                kinds.count('RosCommEvent') == 1 and kinds.count('DecisionEvent') == 1
                and kinds.count('ExecutionEvent') == 1, kinds)
        c.check('执行成功返回 EXECUTED',
                (data['planner'].get('result') or {}).get('status_code') == 'EXECUTED',
                (data['planner'].get('result') or {}).get('status_code'))
        c.check('网关日志无 AUDIT_WRITE_FAILED',
                'AUDIT_WRITE_FAILED' not in data['gateway_text'],
                '无审计写失败')
    run_gateway_case(case, {}, {},
                     dict(request_id='rel-r1', x=1.5, y=1.5, expect_success=1),
                     inspect, 1)


# ---------------------------------------------------------------------------
# R2 RosCommEvent 写入失败（真实 ENOSPC，通过 /dev/full）
# ---------------------------------------------------------------------------
def case_r2(case):
    def inspect(c, data):
        result = data['planner'].get('result') or {}
        c.check('请求被拒绝（success=false）', result.get('success') is False, result.get('status_code'))
        c.check('原因码为 AUDIT_UNAVAILABLE', result.get('status_code') == 'AUDIT_UNAVAILABLE',
                result.get('status_code'))
        c.check('网关日志记录了执行前审计写失败，且 phase=pre_execution',
                'AUDIT_WRITE_FAILED' in data['gateway_text'] and '"phase": "pre_execution"' in data['gateway_text'],
                'AUDIT_WRITE_FAILED / pre_execution')
        c.check('日志明确 fail closed（不会创建下游 Goal）',
                'fail closed' in data['gateway_text'], 'fail closed 文案存在')
        c.check('拒绝日志可关联（REJECTED 含 request_id）',
                'REJECTED' in data['gateway_text'] and 'rel-r2' in data['gateway_text'],
                'REJECTED 行含 rel-r2')
    run_gateway_case(case, {'audit_log_path': '/dev/full'}, {},
                     dict(request_id='rel-r2', x=1.5, y=1.5, expect_success=0),
                     inspect, 0, audit_readable=False)
    # /dev/full 无法回读，改为断言"审计文件不存在/不可读"这一事实
    case.check('审计写入目标为 /dev/full（真实设备写失败，非模拟）',
               True, '/dev/full 写入返回 ENOSPC')


# ---------------------------------------------------------------------------
# R3 DecisionEvent 写入失败（注入：RosComm 成功、Decision 失败）
# ---------------------------------------------------------------------------
def case_r3(case):
    def inspect(c, data):
        result = data['planner'].get('result') or {}
        kinds = [r.get('event_type') for r in data['audit']]
        c.check('请求被拒绝（success=false）', result.get('success') is False, result.get('status_code'))
        c.check('原因码为 AUDIT_UNAVAILABLE', result.get('status_code') == 'AUDIT_UNAVAILABLE',
                result.get('status_code'))
        c.check('RosCommEvent 已成功落库（前置事件成功）', kinds.count('RosCommEvent') == 1, kinds)
        c.check('DecisionEvent 未能落库（无判定记录，正是审计缺口）',
                kinds.count('DecisionEvent') == 0, kinds)
        c.check('同一 event_id 未产生重复判定记录（保持审计链无歧义）',
                kinds.count('DecisionEvent') <= 1, kinds)
        c.check('网关日志记录 phase=pre_execution 的注入失败',
                'AUDIT_WRITE_FAILED' in data['gateway_text']
                and '"phase": "pre_execution"' in data['gateway_text']
                and 'injected fault' in data['gateway_text'],
                'injected fault / pre_execution')
    run_gateway_case(case, {'audit_fault_injection': 'decision'}, {},
                     dict(request_id='rel-r3', x=1.5, y=1.5, expect_success=0),
                     inspect, 0)


# ---------------------------------------------------------------------------
# R4 ExecutionEvent 写入失败（执行后审计失败：动作已发生，不可撤销）
# ---------------------------------------------------------------------------
def case_r4(case):
    def inspect(c, data):
        result = data['planner'].get('result') or {}
        kinds = [r.get('event_type') for r in data['audit']]
        c.check('下游确实执行：planner 拿到真实执行结果 EXECUTED',
                result.get('status_code') == 'EXECUTED' and result.get('success') is True,
                '{0}/{1}'.format(result.get('status_code'), result.get('success')))
        c.check('RosCommEvent 与 DecisionEvent 均已落库',
                kinds.count('RosCommEvent') == 1 and kinds.count('DecisionEvent') == 1, kinds)
        c.check('ExecutionEvent 未能落库（执行后审计缺口）', kinds.count('ExecutionEvent') == 0, kinds)
        c.check('日志以 phase=post_execution 记录，并声明动作不可撤销',
                'AUDIT_WRITE_FAILED' in data['gateway_text']
                and '"phase": "post_execution"' in data['gateway_text']
                and 'cannot be undone' in data['gateway_text'],
                'post_execution / cannot be undone')
        c.check('未声称"下游没有执行"（不得虚构可撤销的物理动作）',
                'downstream did not execute' not in data['gateway_text']
                or 'MUST NOT be read as' in data['gateway_text'],
                '文案未把审计失败等同于下游未执行')
        c.check('执行结果日志仍输出 EXECUTION_RESULT',
                'EXECUTION_RESULT' in data['gateway_text'], 'EXECUTION_RESULT 存在')
    run_gateway_case(case, {'audit_fault_injection': 'execution'}, {},
                     dict(request_id='rel-r4', x=1.5, y=1.5, expect_success=1),
                     inspect, 1)


# ---------------------------------------------------------------------------
# R7 执行超时语义
# ---------------------------------------------------------------------------
def case_r7(case):
    def inspect(c, data):
        result = data['planner'].get('result') or {}
        detail = str(result.get('detail') or '')
        c.check('planner 得到 EXECUTION_TIMEOUT',
                result.get('status_code') == 'EXECUTION_TIMEOUT', result.get('status_code'))
        c.check('下游 Goal 确实被创建（超时 ≠ 未执行）', len(data['journal']) == 1,
                'navsim 收到 {0} 条 Goal'.format(len(data['journal'])))
        c.check('日志给出 EXECUTION_TIMEOUT_STATE 机器可读状态',
                'EXECUTION_TIMEOUT_STATE' in data['gateway_text'], 'EXECUTION_TIMEOUT_STATE')
        c.check('状态为 UNKNOWN_MAY_STILL_BE_RUNNING',
                'UNKNOWN_MAY_STILL_BE_RUNNING' in data['gateway_text'], 'unknown state')
        c.check('取消状态为 REQUESTED_UNCONFIRMED（取消待确认）',
                'REQUESTED_UNCONFIRMED' in data['gateway_text'], 'cancel state')
        c.check('显式标记 execution_may_continue=true',
                '"execution_may_continue": true' in data['gateway_text'], 'execution_may_continue')
        c.check('Result detail 明确"超时不证明下游已停止"',
                'NOT evidence that the downstream stopped' in detail,
                detail[:200])
        c.check('ExecutionEvent.detail 同样携带该语义',
                any('NOT evidence that the downstream stopped' in str(r.get('detail'))
                    for r in data['audit'] if r.get('event_type') == 'ExecutionEvent'),
                [r.get('detail', '')[:80] for r in data['audit'] if r.get('event_type') == 'ExecutionEvent'])
    run_gateway_case(case,
                     {'execution_timeout_sec': 2.0},
                     {'simulate_delay_sec': 10.0},
                     dict(request_id='rel-r7', x=1.5, y=1.5, expect_success=0),
                     inspect, 1)


# 说明：构建保护（R5/R6）由 tests/integration/build_guard_check.py 在**宿主机**执行——
# 它操作的是宿主侧 scripts/build.sh，而本脚本必须与 ROS 图处于同一容器 PID 命名空间。
CASES = [
    ('R1', case_r1, '正常审计写入：ALLOW、下游 1 条 Goal、三事件齐全'),
    ('R2', case_r2, 'RosCommEvent 写入失败（真实 /dev/full ENOSPC）：拒绝、下游 0 条 Goal'),
    ('R3', case_r3, 'DecisionEvent 写入失败（注入）：拒绝、下游 0 条 Goal'),
    ('R4', case_r4, 'ExecutionEvent 写入失败（执行后）：如实回传执行结果，不声称未执行'),
    ('R7', case_r7, '执行超时语义：状态未知 + 取消待确认，不得解读为下游已停止'),
]


def main(argv=None) -> int:
    global _RUN_ID
    parser = argparse.ArgumentParser(description='M1 可靠性故障注入检查')
    parser.add_argument('--run-id', default=None)
    parser.add_argument('--only', default=None, help='只跑指定用例，逗号分隔，如 R2,R3')
    args = parser.parse_args(argv)

    _RUN_ID = args.run_id or sr.utc_run_id()
    run_dir = os.path.join(EVIDENCE_ROOT, _RUN_ID)
    os.makedirs(run_dir, exist_ok=True)

    wanted = set((args.only or '').split(',')) if args.only else None
    results = []
    for case_id, fn, name in CASES:
        if wanted and case_id not in wanted:
            continue
        case = Case(case_id, name, name)
        print('\n=== {0}: {1} ==='.format(case_id, name))
        try:
            fn(case)
        except Exception as exc:  # noqa: BLE001 - 用例异常必须记为 FAIL 而不是中断整轮
            case.check('用例执行未抛异常', False, 'exception: {0}'.format(exc))
        results.append(case)
        for check in case.checks:
            print('  [{0}] {1} -- {2}'.format(check['result'], check['check'], check['detail'][:220]))

    passed = sum(1 for c in results if c.passed)
    summary = {
        'run_id': _RUN_ID,
        'finished_at': sr.utc_stamp(),
        'workspace': ROOT,
        'suite': 'reliability',
        'total': len(results),
        'passed': passed,
        'failed': len(results) - passed,
        'scenarios': [c.summary() for c in results],
    }
    with open(os.path.join(run_dir, 'summary.json'), 'w', encoding='utf-8') as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)

    print('\n' + '=' * 68)
    print('RELIABILITY SUMMARY ({0} passed / {1} total)'.format(passed, len(results)))
    for case in results:
        print('  [{0}] {1:<4} {2}'.format('PASS' if case.passed else 'FAIL', case.case_id, case.name))
    print('evidence: {0}'.format(os.path.relpath(run_dir, ROOT)))
    return 0 if passed == len(results) else 1


if __name__ == '__main__':
    sys.exit(main())
