#!/usr/bin/env python3
"""P09: Planner result timeout vs Gateway execution (1.1.0 rerun).

Design: NavigationSim sleeps 8 s; Gateway execution timeout is 10 s; the Planner
waits only 1 s for the Result. The Planner therefore exits with RESULT_TIMEOUT
while the Gateway has already received and ALLOWed the goal, and NavigationSim
completes afterwards. This distinguishes:

  Planner TIMEOUT  !=  Gateway did not receive  !=  BLOCK  !=  not executed
  Planner exit     !=  cancellation

All processes run in one container with one wall clock. Timestamps are compared
only within that clock domain; no cross-host causal claim is made.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import sros2_check as sc  # noqa: E402

EVIDENCE_ROOT = ROOT / 'tests' / 'evidence'
DOMAIN = 42


def now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'


def run_planner(case_dir, request_id):
    log = case_dir / 'planner.log'
    argv = ['ros2', 'run', 'rg_demo_nodes', 'planner_node', '--ros-args',
            '-p', 'request_id:={0}'.format(request_id),
            '-p', 'task_id:=patrol_a_001', '-p', 'frame_id:=map',
            '-p', 'target_x:=1.5', '-p', 'target_y:=1.5',
            '-p', 'result_timeout_sec:=1.0',
            '-p', 'expect_success:=-1']
    env = dict(os.environ)
    env.update({'ROS_DOMAIN_ID': str(DOMAIN), 'PYTHONUNBUFFERED': '1'})
    for name in ('ROS_SECURITY_ENABLE', 'ROS_SECURITY_STRATEGY',
                 'ROS_SECURITY_KEYSTORE', 'ROS_SECURITY_ENCLAVE_OVERRIDE'):
        env.pop(name, None)
    started = time.time()
    proc = subprocess.run(argv, cwd=str(ROOT), env=env, capture_output=True,
                          text=True, timeout=120)
    output = (proc.stdout or '') + (proc.stderr or '')
    log.write_text(output, encoding='utf-8')
    parsed = None
    for line in output.splitlines():
        if line.strip().startswith('PLANNER_RESULT '):
            try:
                parsed = json.loads(line.strip()[len('PLANNER_RESULT '):])
            except json.JSONDecodeError:
                pass
    return {'argv': argv, 'exit_code': proc.returncode, 'result': parsed,
            'started_epoch': started, 'ended_epoch': time.time(),
            'duration_sec': round(time.time() - started, 3), 'log': log.name}


def read_jsonl(path):
    rows = []
    if Path(path).is_file():
        for line in Path(path).read_text(encoding='utf-8').splitlines():
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args(argv)
    out = EVIDENCE_ROOT / args.run_id
    if out.exists():
        import shutil
        shutil.rmtree(out)
    out.mkdir(parents=True)
    sc.EVIDENCE_ROOT = str(EVIDENCE_ROOT)
    sc.RUN_ID = args.run_id
    request_id = 'p09-timeout-' + args.run_id
    checks = []

    def check(name, ok, detail=''):
        checks.append({'check': name, 'result': 'PASS' if ok else 'FAIL',
                       'detail': str(detail)[:1000]})

    stack = sc.Case('_p09_stack', 'P09 gateway/navsim stack', 'ready', secure=False)
    nodes = []
    try:
        nodes, journal, audit, gw_log = sc.start_stack(
            stack, DOMAIN, False,
            {'navsim': None, 'gateway': None, 'operator': None},
            gateway_params={'execution_timeout_sec': 10.0,
                            'downstream_accept_timeout_sec': 10.0,
                            'audit_log_path': str(out / 'gateway_audit.jsonl')},
            navsim_params={'simulate_delay_sec': 8.0},
            with_operator=False)
        journal = Path(journal)
        audit = Path(out / 'gateway_audit.jsonl')
        if not stack.passed:
            check('stack ready', False, stack.checks)
            raise RuntimeError('stack not ready')
        before = sc.count_lines(journal)
        planner = run_planner(out, request_id)
        planner_ended = planner['ended_epoch']
        # Wait for the delayed execution event (Gateway timeout is 10 s; allow 18 s).
        deadline = time.time() + 18
        while time.time() < deadline:
            events_now = [e for e in read_jsonl(audit)
                          if e.get('request_id') == request_id]
            if any(e.get('event_type') == 'ExecutionEvent' for e in events_now):
                break
            time.sleep(0.2)
        time.sleep(0.5)
        goals = read_jsonl(journal)[before:]
        events = [e for e in read_jsonl(audit) if e.get('request_id') == request_id]
        arrivals = [e for e in events if e.get('event_type') == 'RosCommEvent']
        decisions = [e for e in events if e.get('event_type') == 'DecisionEvent']
        executions = [e for e in events if e.get('event_type') == 'ExecutionEvent']
        result = planner['result'] or {}
        check('Planner actually sent the goal then timed out waiting for Result',
              result.get('outcome') == 'RESULT_TIMEOUT', result)
        check('Planner exit code is 2 (no Result)', planner['exit_code'] == 2,
              planner['exit_code'])
        check('Gateway received the request (arrival event)',
              len(arrivals) == 1, len(arrivals))
        check('Gateway decision is ALLOW / ALLOW_IN_POLICY',
              len(decisions) == 1 and decisions[0].get('decision') == 'ALLOW'
              and decisions[0].get('reason_code') == 'ALLOW_IN_POLICY',
              decisions)
        check('NavigationSim received exactly 1 Goal', len(goals) == 1, len(goals))
        check('Gateway recorded an ExecutionEvent (not a BLOCK)',
              len(executions) == 1, executions)
        exec_status = executions[0].get('status_code') if executions else None
        check('Execution result is EXECUTED or an explicit EXECUTION_TIMEOUT (unknown, not BLOCK)',
              exec_status in ('EXECUTED', 'EXECUTION_TIMEOUT'), exec_status)
        # Late completion: the ExecutionEvent timestamp must be after the planner
        # gave up, and the planner must not have sent a cancel.
        exec_at = None
        if executions:
            stamp = (executions[0].get('finished_at')
                     or executions[0].get('executed_at'))
            try:
                exec_at = datetime.fromisoformat(
                    str(stamp).replace('Z', '+00:00')).timestamp()
            except (TypeError, ValueError):
                exec_at = None
        check('Execution completed after the Planner timed out (late result)',
              exec_at is not None and exec_at > planner_ended,
              {'finished_at': executions[0].get('finished_at') if executions else None,
               'planner_ended': datetime.fromtimestamp(planner_ended, timezone.utc).isoformat()})
        goal = goals[0] if goals else {}
        check('Goal belongs to this request_id', goal.get('request_id') == request_id,
              goal.get('request_id'))
        check('No cancel was requested by the timeout path',
              not any('cancel' in json.dumps(g).lower() for g in goals)
              and result.get('outcome') == 'RESULT_TIMEOUT',
              'planner returns on WaitTimeout; no cancel call in planner_node')
        summary = {
            'contract': 'p09-timeout/1', 'run_id': args.run_id,
            'request_id': request_id, 'scope': 'LAB_SINGLE_CONTAINER',
            'clock_domain': 'same container wall clock',
            'config': {'navsim_simulate_delay_sec': 8.0,
                       'gateway_execution_timeout_sec': 10.0,
                       'planner_result_timeout_sec': 1.0},
            'planner': planner,
            'gateway': {'arrivals': len(arrivals), 'decisions': decisions,
                        'executions': executions},
            'navsim_goals': goals,
            'checks': checks,
            'limitations': [
                'Same container/host clock; no cross-host ordering claim.',
                'This is a simulated NavigationSim (recorded_only), not a physical robot.',
                'Planner timeout is not cancellation; the execution completed after the planner left.',
            ],
        }
        summary['total'] = len(checks)
        summary['passed'] = sum(1 for c in checks if c['result'] == 'PASS')
        summary['failed'] = summary['total'] - summary['passed']
        (out / 'summary.json').write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({'run_id': args.run_id, 'passed': summary['passed'],
                          'total': summary['total'], 'failed': summary['failed']}))
        for item in checks:
            if item['result'] == 'FAIL':
                print('  FAIL: {0} -- {1}'.format(item['check'], item['detail']))
        return 0 if summary['failed'] == 0 else 1
    finally:
        if nodes:
            sc.stop_all(nodes)


if __name__ == '__main__':
    sys.exit(main())
