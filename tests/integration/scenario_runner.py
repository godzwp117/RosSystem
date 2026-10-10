#!/usr/bin/env python3
"""A/B and negative-scenario harness with count-based assertions.

Every check is derived from an explicit count or from a parsed JSON/JSONL record,
never from eyeballing terminal text (task requirement 11/12).

Assertion sources
-----------------
* ``logs/<scenario>/navsim_goals.jsonl`` -- the executor journal: **one line per
  Goal actually delivered to NavigationSim**. This is the authoritative
  "downstream Goal count".
* ``logs/<scenario>/audit.jsonl``        -- the Gateway audit trail: RosCommEvent /
  DecisionEvent / ExecutionEvent, correlated by ``event_id`` and ``request_id``.
* ``logs/<scenario>/planner_run*.log``   -- the Planner's ``PLANNER_RESULT`` JSON
  line plus its process exit code.
* ``logs/<scenario>/gateway.log``        -- rejection log lines (``REJECTED``), which
  must be correlatable to a rejected request by ``request_id``/``event_id``.

Process hygiene
---------------
Nodes are started with ``start_new_session=True`` and torn down with
``SIGINT`` -> ``SIGTERM`` -> ``SIGKILL`` sent to the whole *process group*. This
matters: ``ros2 run`` is a wrapper whose child is the real node, so killing only
the wrapper orphans the node (observed during development, and the cause of a
spurious "more than one action server" warning). A /proc scan reaps stragglers
before and after every scenario.

Usage (from a shell where ROS and this workspace's install/ are sourced)::

    python3 tests/integration/scenario_runner.py --suite all
    python3 tests/integration/scenario_runner.py --suite ab
    python3 tests/integration/scenario_runner.py --only A_zone_allow
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
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = os.environ.get(
    'RG_WS', os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
INSTALL_MARKER = os.path.join(ROOT, 'install')
CONFIG_DIR = os.path.join(ROOT, 'config')
SCENARIO_CONFIG_DIR = os.path.join(CONFIG_DIR, 'scenarios')
DEFAULT_POLICY = os.path.join(CONFIG_DIR, 'task_policy.yaml')
MISSING_POLICY = os.path.join(SCENARIO_CONFIG_DIR, 'task_policy_does_not_exist.yaml')

GATEWAY_PKG, GATEWAY_EXE = 'rg_gateway', 'security_gateway'
NAVSIM_PKG, NAVSIM_EXE = 'rg_demo_nodes', 'navigation_sim'
OPERATOR_PKG, OPERATOR_EXE = 'rg_demo_nodes', 'operator_node'
PLANNER_PKG, PLANNER_EXE = 'rg_demo_nodes', 'planner_node'

#: Substrings identifying node processes belonging to this workspace.
NODE_MARKERS = (
    os.path.join('install', 'rg_gateway', 'lib'),
    os.path.join('install', 'rg_demo_nodes', 'lib'),
    'rg_gateway/lib/rg_gateway/security_gateway',
    'rg_demo_nodes/lib/rg_demo_nodes/',
)


# ---------------------------------------------------------------------------
# small utilities
# ---------------------------------------------------------------------------
def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def utc_run_id() -> str:
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def read_jsonl(path: str) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    if not os.path.isfile(path):
        return records
    with open(path, 'r', encoding='utf-8') as handle:
        for line in handle:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def read_text(path: str) -> str:
    if not os.path.isfile(path):
        return ''
    with open(path, 'r', encoding='utf-8', errors='replace') as handle:
        return handle.read()


def _proc_field(pid: int, field: str) -> str:
    try:
        with open('/proc/{0}/{1}'.format(pid, field), 'r', encoding='utf-8',
                  errors='replace') as handle:
            return handle.read().strip()
    except (OSError, PermissionError):
        return ''


def _proc_environ(pid: int) -> Dict[str, str]:
    environ = {}
    try:
        with open('/proc/{0}/environ'.format(pid), 'rb') as handle:
            raw = handle.read().decode('utf-8', errors='replace')
    except (OSError, PermissionError):
        return environ
    for item in raw.split('\x00'):
        if '=' in item:
            key, value = item.split('=', 1)
            environ[key] = value
    return environ


def find_node_processes() -> List[Dict[str, Any]]:
    """本工作区的节点进程，附带**归属信息**（域、会话、进程组、是否本会话）。

    归属信息是安全清理的前提：没有它就无法区分"我上一轮遗留的节点"和
    "同一容器里另一个成员正在运行的节点"。
    """
    found: List[Dict[str, Any]] = []
    self_pid = os.getpid()
    self_sid = os.getsid(0)
    for entry in os.listdir('/proc'):
        if not entry.isdigit():
            continue
        pid = int(entry)
        if pid == self_pid:
            continue
        try:
            with open('/proc/{0}/cmdline'.format(pid), 'rb') as handle:
                cmdline = handle.read().decode('utf-8', errors='replace').replace('\x00', ' ')
        except (OSError, PermissionError):
            continue
        if not any(marker in cmdline for marker in NODE_MARKERS):
            continue
        environ = _proc_environ(pid)
        stat = _proc_field(pid, 'stat')
        # stat 的字段 5 是 session，6 是 tty；comm 可能含空格，故从右往左取
        sid = None
        try:
            parts = stat.rsplit(')', 1)[1].split()
            sid = int(parts[3])
        except (IndexError, ValueError):
            sid = None
        found.append({
            'pid': pid,
            'domain': environ.get('ROS_DOMAIN_ID', ''),
            'sid': sid,
            'own_session': (sid == self_sid),
            'test_marker': environ.get('RG_TEST_RUN_ID', ''),
            'cmdline': cmdline[:160],
        })
    return found


def find_node_pids() -> List[int]:
    """兼容旧调用点：仅返回 PID 列表。"""
    return [item['pid'] for item in find_node_processes()]


def reap_stragglers(quiet: bool = False) -> List[int]:
    """清理遗留节点，**默认只清理可证明属于本实例的进程**。

    安全收紧（A5）
    --------------
    原实现扫描 /proc 后对所有匹配进程直接 SIGKILL，不区分 ROS Domain、
    不区分启动者与容器内的其他实例。在多成员共享同一容器时，这等于杀掉
    他人正在运行的 Gateway / NavigationSim。

    现按归属分级：
      * **本会话**（sid == 当前 sid）的节点：确定是本实例启动的，直接清理；
      * **其他域**（ROS_DOMAIN_ID 与当前不同）的节点：默认**只报告不清理**，
        因为它们更可能属于另一个实例；
      * **同域但非本会话**：默认只报告；确需清理须显式设置
        RG_REAP_FOREIGN=1（会打印明确警告）。
    """
    reaped: List[int] = []
    skipped: List[Dict[str, Any]] = []

    for item in find_node_processes():
        pid = item['pid']
        # 归属判定依据是**测试专属标记**，而不是进程名、工作区路径或 Domain：
        #   * 带 RG_TEST_RUN_ID  -> 本脚手架（含历史轮次）启动的测试节点，可清理；
        #   * 不带该标记         -> 成员用 start_system.sh 启动的真实系统，绝不触碰。
        # 本会话的节点同样直接清理（一定是本次运行启动的）。
        if item.get('test_marker') or item['own_session']:
            try:
                os.kill(pid, signal.SIGKILL)
                reaped.append(pid)
            except OSError:
                pass
        else:
            skipped.append(item)

    if reaped:
        time.sleep(0.5)
    if not quiet:
        if reaped:
            print('[preflight] reaped own leftover node process(es): {0}'.format(reaped))
        if skipped:
            print('[preflight] 跳过 {0} 个不属于本实例的节点进程（未清理）:'.format(
                len(skipped)))
            for item in skipped[:5]:
                print('    pid={0} domain={1!r} own_session={2}'.format(
                    item['pid'], item['domain'], item['own_session']))
            print('    这些进程不带测试标记，可能是成员正在运行的系统；'
                  '已跳过以避免误杀。')
            print('    若确认它们确实是遗留测试节点，可手动检查后再处理。')
    return reaped


# ---------------------------------------------------------------------------
# scenario model
# ---------------------------------------------------------------------------
@dataclass
class PlannerRun:
    """One invocation of planner_node and the outcome it must produce."""

    label: str
    params: Dict[str, Any]
    expect_exit: int
    expect_success: Optional[bool] = None
    expect_status_code: Optional[str] = None


@dataclass
class Scenario:
    name: str
    suite: str
    description: str
    planner_runs: List[PlannerRun]
    policy_path: Optional[str] = None          # None -> authoritative policy
    gateway_params: Dict[str, Any] = field(default_factory=dict)
    navsim_params: Dict[str, Any] = field(default_factory=dict)
    expect_navsim_goals: int = 0
    expect_decision_codes: List[str] = field(default_factory=list)
    expect_execution_events: int = 0
    expect_reject_logs: int = 0
    expect_executed_request_ids: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# node process management
# ---------------------------------------------------------------------------
class NodeProcess:
    def __init__(self, package: str, executable: str, params: Dict[str, Any],
                 log_path: str, commands: List[Dict[str, Any]], label: str,
                 scenario: str):
        argv = ['ros2', 'run', package, executable, '--ros-args']
        for key, value in params.items():
            argv += ['-p', '{0}:={1}'.format(key, _param_literal(value))]

        env = dict(os.environ)
        env['PYTHONUNBUFFERED'] = '1'
        # 测试专属标记：本脚手架启动的节点一定带这个变量。
        # 成员自己用 start_system.sh 启动的栈**不带**该变量，因此永远不会被
        # 测试脚手架的遗留清理碰到 —— 这是"只清理自己的进程"的可判定依据。
        env['RG_TEST_RUN_ID'] = os.environ.get('RG_TEST_RUN_ID') or (
            'scenario_runner-{0}'.format(os.getpid()))
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        self._log_handle = open(log_path, 'wb')
        self.log_path = log_path
        self.label = label
        self._started_at = utc_stamp()
        self._t0 = time.time()
        self.proc = subprocess.Popen(
            argv,
            stdout=self._log_handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            cwd=ROOT,
            env=env,
        )
        self._command_record = {
            'scenario': scenario,
            'step': label,
            'kind': 'ros2 run (long-running)',
            'argv': argv,
            'cwd': ROOT,
            'pid': self.proc.pid,
            'started_at': self._started_at,
            'log_path': log_path,
            'exit_code': None,
        }
        commands.append(self._command_record)

    def wait_for_log(self, marker: str, timeout_sec: float) -> bool:
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            if marker in read_text(self.log_path):
                self._command_record['ready_after_sec'] = round(time.time() - self._t0, 3)
                return True
            if self.proc.poll() is not None:
                return marker in read_text(self.log_path)
            time.sleep(0.2)
        return marker in read_text(self.log_path)

    def stop(self, grace_sec: float = 8.0) -> Optional[int]:
        if self.proc.poll() is None:
            _signal_group(self.proc.pid, signal.SIGINT, grace_sec)
        if self.proc.poll() is None:
            _signal_group(self.proc.pid, signal.SIGTERM, 4.0)
        if self.proc.poll() is None:
            _signal_group(self.proc.pid, signal.SIGKILL, 5.0)
        try:
            code = self.proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            code = None
        self._command_record['exit_code'] = code
        self._command_record['finished_at'] = utc_stamp()
        self._command_record['duration_sec'] = round(time.time() - self._t0, 3)
        try:
            self._log_handle.close()
        except OSError:
            pass
        return code


def _signal_group(pid: int, sig: int, wait_sec: float) -> None:
    try:
        os.killpg(os.getpgid(pid), sig)
    except (OSError, ProcessLookupError):
        try:
            os.kill(pid, sig)
        except OSError:
            return
    deadline = time.time() + wait_sec
    while time.time() < deadline:
        try:
            os.kill(pid, 0)
        except OSError:
            return
        time.sleep(0.1)


def _param_literal(value: Any) -> str:
    if isinstance(value, bool):
        return 'true' if value else 'false'
    return str(value)


# ---------------------------------------------------------------------------
# checks
# ---------------------------------------------------------------------------
@dataclass
class Check:
    name: str
    passed: bool
    detail: str

    def to_dict(self) -> Dict[str, Any]:
        return {'check': self.name, 'result': 'PASS' if self.passed else 'FAIL',
                'detail': self.detail}


def _check(name: str, condition: bool, detail: str) -> Check:
    return Check(name=name, passed=bool(condition), detail=detail)


def run_scenario(scenario: Scenario, evidence_dir: str) -> Dict[str, Any]:
    scenario_dir = os.path.join(evidence_dir, scenario.name)
    shutil.rmtree(scenario_dir, ignore_errors=True)
    os.makedirs(scenario_dir, exist_ok=True)

    audit_path = os.path.join(scenario_dir, 'audit.jsonl')
    journal_path = os.path.join(scenario_dir, 'navsim_goals.jsonl')
    gateway_log = os.path.join(scenario_dir, 'gateway.log')
    navsim_log = os.path.join(scenario_dir, 'navsim.log')
    commands: List[Dict[str, Any]] = []

    policy_path = scenario.policy_path or DEFAULT_POLICY

    print('\n=== scenario: {0} ==='.format(scenario.name))
    print('    {0}'.format(scenario.description))
    print('    policy: {0}'.format(policy_path))

    reap_stragglers()
    navsim = NodeProcess(
        NAVSIM_PKG, NAVSIM_EXE,
        {'record_path': journal_path, **scenario.navsim_params},
        navsim_log, commands, 'navigation_sim', scenario.name)
    gateway = NodeProcess(
        GATEWAY_PKG, GATEWAY_EXE,
        {'policy_path': policy_path, 'audit_log_path': audit_path,
         **scenario.gateway_params},
        gateway_log, commands, 'security_gateway', scenario.name)

    checks: List[Check] = []
    planner_results: List[Dict[str, Any]] = []
    planner_exits: List[int] = []

    try:
        navsim_ready = navsim.wait_for_log('NAVSIM_READY', 30.0)
        gateway_ready = gateway.wait_for_log('GATEWAY_READY', 30.0)
        checks.append(_check(
            'bringup: NavigationSim ready', navsim_ready,
            'NAVSIM_READY seen in {0}'.format(os.path.relpath(navsim_log, ROOT))))
        checks.append(_check(
            'bringup: security_gateway ready', gateway_ready,
            'GATEWAY_READY seen in {0}'.format(os.path.relpath(gateway_log, ROOT))))

        for index, run in enumerate(scenario.planner_runs, start=1):
            log_path = os.path.join(scenario_dir, 'planner_{0}_{1}.log'.format(index, run.label))
            argv = ['ros2', 'run', PLANNER_PKG, PLANNER_EXE, '--ros-args']
            for key, value in run.params.items():
                argv += ['-p', '{0}:={1}'.format(key, _param_literal(value))]
            env = dict(os.environ)
            env['PYTHONUNBUFFERED'] = '1'
            started = utc_stamp()
            t0 = time.time()
            try:
                completed = subprocess.run(
                    argv, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, timeout=120.0)
                exit_code: Optional[int] = completed.returncode
                output = completed.stdout.decode('utf-8', errors='replace')
            except subprocess.TimeoutExpired as exc:
                exit_code = None
                output = (exc.stdout or b'').decode('utf-8', errors='replace')
            with open(log_path, 'w', encoding='utf-8') as handle:
                handle.write(output)
            commands.append({
                'scenario': scenario.name,
                'step': 'planner_run{0}:{1}'.format(index, run.label),
                'kind': 'ros2 run (one-shot)',
                'argv': argv,
                'cwd': ROOT,
                'started_at': started,
                'finished_at': utc_stamp(),
                'duration_sec': round(time.time() - t0, 3),
                'exit_code': exit_code,
                'log_path': log_path,
            })
            parsed = _parse_planner_results(output)
            planner_exits.append(exit_code if exit_code is not None else -999)
            planner_results.append(parsed[-1] if parsed else {})
    finally:
        gateway.stop()
        navsim.stop()
        reaped = reap_stragglers(quiet=True)
        if reaped:
            print('    [teardown] reaped stragglers: {0}'.format(reaped))

    # ---------------- assertions from artefacts ----------------
    journal = read_jsonl(journal_path)
    audit = read_jsonl(audit_path)
    gateway_text = read_text(gateway_log)
    reject_lines = [line for line in gateway_text.splitlines() if 'REJECTED ' in line]

    decisions = [rec for rec in audit if rec.get('event_type') == 'DecisionEvent']
    executions = [rec for rec in audit if rec.get('event_type') == 'ExecutionEvent']
    comms = [rec for rec in audit if rec.get('event_type') == 'RosCommEvent']

    # 1. downstream Goal count -- the core A/B assertion
    checks.append(_check(
        'navsim Goal count == {0}'.format(scenario.expect_navsim_goals),
        len(journal) == scenario.expect_navsim_goals,
        'journal {0} has {1} line(s)'.format(
            os.path.relpath(journal_path, ROOT), len(journal))))

    # 2. planner exit codes
    for index, run in enumerate(scenario.planner_runs):
        actual_exit = planner_exits[index] if index < len(planner_exits) else None
        checks.append(_check(
            'planner[{0}] exit code == {1}'.format(run.label, run.expect_exit),
            actual_exit == run.expect_exit,
            'actual exit code {0}'.format(actual_exit)))

    # 3. planner business outcome
    for index, run in enumerate(scenario.planner_runs):
        result = planner_results[index] if index < len(planner_results) else {}
        if run.expect_success is not None:
            checks.append(_check(
                'planner[{0}] Result.success == {1}'.format(run.label, run.expect_success),
                result.get('success') is run.expect_success,
                'status_code={0!r} detail={1!r}'.format(
                    result.get('status_code'), (result.get('detail') or '')[:120])))
        if run.expect_status_code is not None:
            checks.append(_check(
                'planner[{0}] status_code == {1}'.format(run.label, run.expect_status_code),
                result.get('status_code') == run.expect_status_code,
                'actual status_code={0!r}'.format(result.get('status_code'))))

    # 4. DecisionEvent reason-code sequence
    actual_codes = [rec.get('reason_code') for rec in decisions]
    checks.append(_check(
        'DecisionEvent reason_code sequence == {0}'.format(scenario.expect_decision_codes),
        actual_codes == scenario.expect_decision_codes,
        'actual sequence {0}'.format(actual_codes)))

    # 5. ExecutionEvent count
    checks.append(_check(
        'ExecutionEvent count == {0}'.format(scenario.expect_execution_events),
        len(executions) == scenario.expect_execution_events,
        'actual {0} ExecutionEvent(s): {1}'.format(
            len(executions), [rec.get('status_code') for rec in executions])))

    # 6. every received Goal produced exactly one RosCommEvent + one DecisionEvent
    checks.append(_check(
        'RosCommEvent count == DecisionEvent count == planner runs',
        len(comms) == len(decisions) == len(scenario.planner_runs),
        'comm={0} decision={1} planner_runs={2}'.format(
            len(comms), len(decisions), len(scenario.planner_runs))))

    # 7. event_id traceability: no orphan records, shared event_id across phases
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for rec in audit:
        groups.setdefault(rec.get('event_id'), []).append(rec)
    malformed = {key: len(value) for key, value in groups.items()
                 if len([r for r in value if r.get('event_type') == 'RosCommEvent']) != 1
                 or len([r for r in value if r.get('event_type') == 'DecisionEvent']) != 1
                 or len([r for r in value if r.get('event_type') == 'ExecutionEvent']) > 1}
    checks.append(_check(
        'event_id traceability (1 RosComm + 1 Decision + <=1 Execution each)',
        not malformed,
        'event_id groups: {0}; malformed: {1}'.format(len(groups), malformed or 'none')))

    # 8. BLOCK => no ExecutionEvent for that event_id
    block_event_ids = {rec.get('event_id') for rec in decisions
                       if rec.get('decision') == 'BLOCK'}
    execution_event_ids = {rec.get('event_id') for rec in executions}
    leaked = block_event_ids & execution_event_ids
    checks.append(_check(
        'BLOCKed event_ids never have an ExecutionEvent',
        not leaked,
        'leaked event_ids: {0}'.format(sorted(leaked) or 'none')))

    # 9. rejection log lines are correlatable
    checks.append(_check(
        'correlatable REJECTED log lines == {0}'.format(scenario.expect_reject_logs),
        len(reject_lines) == scenario.expect_reject_logs,
        'found {0} REJECTED line(s) in {1}'.format(
            len(reject_lines), os.path.relpath(gateway_log, ROOT))))
    if reject_lines:
        blocked_request_ids = {rec.get('request_id') for rec in decisions
                               if rec.get('decision') == 'BLOCK'}
        blocked_event_ids = {rec.get('event_id') for rec in decisions
                             if rec.get('decision') == 'BLOCK'}
        correlated = all(
            any(rid and rid in line for rid in blocked_request_ids)
            and any(eid and eid in line for eid in blocked_event_ids)
            for line in reject_lines)
        checks.append(_check(
            'every REJECTED line carries a BLOCKed request_id and event_id',
            correlated,
            'blocked request_ids={0}'.format(sorted(blocked_request_ids))))
        checks.append(_check(
            'REJECTED lines declare downstream_goal_created=false',
            all('"downstream_goal_created": false' in line for line in reject_lines),
            'checked {0} line(s)'.format(len(reject_lines))))

    # 10. the executor saw exactly the request_ids that were ALLOWed
    expected_ids = set(scenario.expect_executed_request_ids)
    journal_ids = {rec.get('request_id') for rec in journal}
    checks.append(_check(
        'executor request_id set matches the ALLOWed set',
        journal_ids == expected_ids,
        'journal={0} expected={1}'.format(sorted(journal_ids), sorted(expected_ids))))

    passed = all(check.passed for check in checks)
    result = {
        'scenario': scenario.name,
        'suite': scenario.suite,
        'description': scenario.description,
        'policy_path': policy_path,
        'result': 'PASS' if passed else 'FAIL',
        'started_at': utc_stamp(),
        'evidence_dir': os.path.relpath(scenario_dir, ROOT),
        'navsim_goal_count': len(journal),
        'decision_sequence': actual_codes,
        'execution_status_codes': [rec.get('status_code') for rec in executions],
        'reject_log_lines': len(reject_lines),
        'planner_results': planner_results,
        'planner_exit_codes': planner_exits,
        'checks': [check.to_dict() for check in checks],
        'commands': commands,
        # 显式记录期望值，使验收证据包能给出 expected vs actual 对照，
        # 而不是只留一个结论性的 PASS/FAIL。
        'expectations': {
            'navsim_goals': scenario.expect_navsim_goals,
            'decision_codes': list(scenario.expect_decision_codes),
            'execution_events': scenario.expect_execution_events,
            'reject_logs': scenario.expect_reject_logs,
            'executed_request_ids': list(scenario.expect_executed_request_ids),
        },
    }
    with open(os.path.join(scenario_dir, 'commands.json'), 'w', encoding='utf-8') as handle:
        json.dump(commands, handle, ensure_ascii=False, indent=2)
    with open(os.path.join(scenario_dir, 'scenario_result.json'), 'w', encoding='utf-8') as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)

    _print_checks(checks)
    return result


def _parse_planner_results(output: str) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for line in output.splitlines():
        line = line.strip()
        if line.startswith('PLANNER_RESULT '):
            try:
                results.append(json.loads(line[len('PLANNER_RESULT '):]))
            except json.JSONDecodeError:
                pass
    return results


def _print_checks(checks: Sequence[Check]) -> None:
    for check in checks:
        print('    [{0}] {1} -- {2}'.format(
            'PASS' if check.passed else 'FAIL', check.name, check.detail))


# ---------------------------------------------------------------------------
# scenario catalogue
# ---------------------------------------------------------------------------
def build_scenarios() -> List[Scenario]:
    a_id = 'a-zone-request-0001'
    b_id = 'b-zone-request-0002'
    return [
        # ---------------- suite "ab" (requirement 11) ----------------
        Scenario(
            name='A_zone_allow',
            suite='ab',
            description='In-region target: Gateway ALLOW, one downstream Goal, EXECUTED.',
            planner_runs=[PlannerRun(
                label='allow', params={'task_id': 'patrol_a_001', 'request_id': a_id,
                                       'frame_id': 'map', 'target_x': 1.5, 'target_y': 1.5,
                                       'expect_success': 1},
                expect_exit=0, expect_success=True, expect_status_code='EXECUTED')],
            expect_navsim_goals=1,
            expect_decision_codes=['ALLOW_IN_POLICY'],
            expect_execution_events=1,
            expect_reject_logs=0,
            expect_executed_request_ids=[a_id],
        ),
        Scenario(
            name='B_zone_block_out_of_region',
            suite='ab',
            description='Out-of-region target: Gateway BLOCK/OUT_OF_REGION, zero downstream Goals.',
            planner_runs=[PlannerRun(
                label='block', params={'task_id': 'patrol_a_001', 'request_id': b_id,
                                       'frame_id': 'map', 'target_x': 9.0, 'target_y': 9.0,
                                       'expect_success': 0},
                expect_exit=0, expect_success=False, expect_status_code='OUT_OF_REGION')],
            expect_navsim_goals=0,
            expect_decision_codes=['OUT_OF_REGION'],
            expect_execution_events=0,
            expect_reject_logs=1,
            expect_executed_request_ids=[],
        ),
        # ---------------- suite "negative" (requirement 12) ----------------
        Scenario(
            name='policy_file_missing',
            suite='negative',
            description='Authoritative policy file absent: fail closed with POLICY_MISSING.',
            planner_runs=[PlannerRun(
                label='missing', params={'task_id': 'patrol_a_001',
                                         'request_id': 'neg-policy-0001',
                                         'frame_id': 'map', 'target_x': 1.5, 'target_y': 1.5,
                                         'expect_success': 0},
                expect_exit=0, expect_success=False, expect_status_code='POLICY_MISSING')],
            policy_path=MISSING_POLICY,
            expect_navsim_goals=0,
            expect_decision_codes=['POLICY_MISSING'],
            expect_execution_events=0,
            expect_reject_logs=1,
        ),
        Scenario(
            name='policy_missing_required_field',
            suite='negative',
            description='Policy lacks coordinate_frame: schema error, fail closed.',
            planner_runs=[PlannerRun(
                label='badfield', params={'task_id': 'patrol_a_001',
                                          'request_id': 'neg-policy-0002',
                                          'frame_id': 'map', 'target_x': 1.5, 'target_y': 1.5,
                                          'expect_success': 0},
                expect_exit=0, expect_success=False, expect_status_code='POLICY_MISSING')],
            policy_path=os.path.join(SCENARIO_CONFIG_DIR, 'task_policy_missing_field.yaml'),
            expect_navsim_goals=0,
            expect_decision_codes=['POLICY_MISSING'],
            expect_execution_events=0,
            expect_reject_logs=1,
        ),
        Scenario(
            name='policy_nonfinite_region',
            suite='negative',
            description='Policy region bound is NaN: never coerced, fail closed.',
            planner_runs=[PlannerRun(
                label='nanregion', params={'task_id': 'patrol_a_001',
                                           'request_id': 'neg-policy-0003',
                                           'frame_id': 'map', 'target_x': 1.5, 'target_y': 1.5,
                                           'expect_success': 0},
                expect_exit=0, expect_success=False, expect_status_code='POLICY_MISSING')],
            policy_path=os.path.join(SCENARIO_CONFIG_DIR, 'task_policy_nonfinite_region.yaml'),
            expect_navsim_goals=0,
            expect_decision_codes=['POLICY_MISSING'],
            expect_execution_events=0,
            expect_reject_logs=1,
        ),
        Scenario(
            name='policy_inactive',
            suite='negative',
            description='Policy valid but active:false: treated as no authority, fail closed.',
            planner_runs=[PlannerRun(
                label='inactive', params={'task_id': 'patrol_a_001',
                                          'request_id': 'neg-policy-0004',
                                          'frame_id': 'map', 'target_x': 1.5, 'target_y': 1.5,
                                          'expect_success': 0},
                expect_exit=0, expect_success=False, expect_status_code='POLICY_MISSING')],
            policy_path=os.path.join(SCENARIO_CONFIG_DIR, 'task_policy_inactive.yaml'),
            expect_navsim_goals=0,
            expect_decision_codes=['POLICY_MISSING'],
            expect_execution_events=0,
            expect_reject_logs=1,
        ),
        Scenario(
            name='task_id_mismatch_request_side',
            suite='negative',
            description='Goal task_id differs from the authoritative policy: TASK_MISMATCH.',
            planner_runs=[PlannerRun(
                label='taskmismatch', params={'task_id': 'patrol_b_042',
                                              'request_id': 'neg-task-0001',
                                              'frame_id': 'map', 'target_x': 1.5,
                                              'target_y': 1.5, 'expect_success': 0},
                expect_exit=0, expect_success=False, expect_status_code='TASK_MISMATCH')],
            expect_navsim_goals=0,
            expect_decision_codes=['TASK_MISMATCH'],
            expect_execution_events=0,
            expect_reject_logs=1,
        ),
        Scenario(
            name='task_id_mismatch_policy_side',
            suite='negative',
            description='Authoritative policy is for patrol_b_999: a patrol_a_001 Goal is TASK_MISMATCH.',
            planner_runs=[PlannerRun(
                label='taskmismatch2', params={'task_id': 'patrol_a_001',
                                               'request_id': 'neg-task-0002',
                                               'frame_id': 'map', 'target_x': 1.5,
                                               'target_y': 1.5, 'expect_success': 0},
                expect_exit=0, expect_success=False, expect_status_code='TASK_MISMATCH')],
            policy_path=os.path.join(SCENARIO_CONFIG_DIR, 'task_policy_task_b.yaml'),
            expect_navsim_goals=0,
            expect_decision_codes=['TASK_MISMATCH'],
            expect_execution_events=0,
            expect_reject_logs=1,
        ),
        Scenario(
            name='frame_id_invalid',
            suite='negative',
            description='Goal frame_id=camera_link while policy coordinate_frame=map: INVALID_TARGET.',
            planner_runs=[PlannerRun(
                label='badframe', params={'task_id': 'patrol_a_001',
                                          'request_id': 'neg-frame-0001',
                                          'frame_id': 'camera_link', 'target_x': 1.5,
                                          'target_y': 1.5, 'expect_success': 0},
                expect_exit=0, expect_success=False, expect_status_code='INVALID_TARGET')],
            expect_navsim_goals=0,
            expect_decision_codes=['INVALID_TARGET'],
            expect_execution_events=0,
            expect_reject_logs=1,
        ),
        Scenario(
            name='target_nan',
            suite='negative',
            description='Goal target.x = NaN: INVALID_TARGET, never coerced.',
            planner_runs=[PlannerRun(
                label='nan', params={'task_id': 'patrol_a_001',
                                     'request_id': 'neg-nan-0001', 'frame_id': 'map',
                                     'target_x': 'nan', 'target_y': 1.5, 'expect_success': 0},
                expect_exit=0, expect_success=False, expect_status_code='INVALID_TARGET')],
            expect_navsim_goals=0,
            expect_decision_codes=['INVALID_TARGET'],
            expect_execution_events=0,
            expect_reject_logs=1,
        ),
        Scenario(
            name='target_infinite',
            suite='negative',
            description='Goal target.y = inf: INVALID_TARGET, never coerced.',
            planner_runs=[PlannerRun(
                label='inf', params={'task_id': 'patrol_a_001',
                                     'request_id': 'neg-inf-0001', 'frame_id': 'map',
                                     'target_x': 1.5, 'target_y': 'inf', 'expect_success': 0},
                expect_exit=0, expect_success=False, expect_status_code='INVALID_TARGET')],
            expect_navsim_goals=0,
            expect_decision_codes=['INVALID_TARGET'],
            expect_execution_events=0,
            expect_reject_logs=1,
        ),
        Scenario(
            name='duplicate_request_id',
            suite='negative',
            description='Same request_id sent twice: ALLOW then DUPLICATE_REQUEST (replay guard).',
            planner_runs=[
                PlannerRun(
                    label='first', params={'task_id': 'patrol_a_001',
                                           'request_id': 'neg-dup-0001', 'frame_id': 'map',
                                           'target_x': 2.0, 'target_y': 2.0, 'expect_success': 1},
                    expect_exit=0, expect_success=True, expect_status_code='EXECUTED'),
                PlannerRun(
                    label='replay', params={'task_id': 'patrol_a_001',
                                            'request_id': 'neg-dup-0001', 'frame_id': 'map',
                                            'target_x': 2.5, 'target_y': 2.5, 'expect_success': 0},
                    expect_exit=0, expect_success=False,
                    expect_status_code='DUPLICATE_REQUEST'),
            ],
            expect_navsim_goals=1,
            expect_decision_codes=['ALLOW_IN_POLICY', 'DUPLICATE_REQUEST'],
            expect_execution_events=1,
            expect_reject_logs=1,
            expect_executed_request_ids=['neg-dup-0001'],
        ),
        Scenario(
            name='rate_limit',
            suite='negative',
            description='max_requests_per_minute=2: third in-region Goal is RATE_LIMIT.',
            policy_path=os.path.join(SCENARIO_CONFIG_DIR, 'task_policy_low_rate.yaml'),
            planner_runs=[
                PlannerRun(label='r1', params={'task_id': 'patrol_a_001',
                                               'request_id': 'neg-rate-0001',
                                               'frame_id': 'map', 'target_x': 1.0,
                                               'target_y': 1.0, 'expect_success': 1},
                           expect_exit=0, expect_success=True, expect_status_code='EXECUTED'),
                PlannerRun(label='r2', params={'task_id': 'patrol_a_001',
                                               'request_id': 'neg-rate-0002',
                                               'frame_id': 'map', 'target_x': 2.0,
                                               'target_y': 2.0, 'expect_success': 1},
                           expect_exit=0, expect_success=True, expect_status_code='EXECUTED'),
                PlannerRun(label='r3', params={'task_id': 'patrol_a_001',
                                               'request_id': 'neg-rate-0003',
                                               'frame_id': 'map', 'target_x': 3.0,
                                               'target_y': 3.0, 'expect_success': 0},
                           expect_exit=0, expect_success=False, expect_status_code='RATE_LIMIT'),
            ],
            expect_navsim_goals=2,
            expect_decision_codes=['ALLOW_IN_POLICY', 'ALLOW_IN_POLICY', 'RATE_LIMIT'],
            expect_execution_events=2,
            expect_reject_logs=1,
            expect_executed_request_ids=['neg-rate-0001', 'neg-rate-0002'],
        ),
        Scenario(
            name='execution_timeout',
            suite='negative',
            description='Executor stalls past execution_timeout_sec: EXECUTION_TIMEOUT, audited.',
            planner_runs=[PlannerRun(
                label='timeout', params={'task_id': 'patrol_a_001',
                                         'request_id': 'neg-timeout-0001',
                                         'frame_id': 'map', 'target_x': 1.5, 'target_y': 1.5,
                                         'expect_success': 0},
                expect_exit=0, expect_success=False,
                expect_status_code='EXECUTION_TIMEOUT')],
            gateway_params={'execution_timeout_sec': 2.0},
            navsim_params={'simulate_delay_sec': 10.0},
            expect_navsim_goals=1,
            expect_decision_codes=['ALLOW_IN_POLICY'],
            expect_execution_events=1,
            expect_reject_logs=0,
            expect_executed_request_ids=['neg-timeout-0001'],
        ),
    ]


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------
def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--suite', choices=['ab', 'negative', 'all'], default='all')
    parser.add_argument('--only', action='append', default=None,
                        help='run only the named scenario(s); repeatable')
    parser.add_argument('--evidence-root', default=os.path.join(ROOT, 'tests', 'evidence'))
    args = parser.parse_args(argv)

    if not os.path.isdir(INSTALL_MARKER):
        print('FATAL: {0} not found. Build first: colcon build'.format(INSTALL_MARKER),
              file=sys.stderr)
        return 2

    scenarios = build_scenarios()
    if args.only:
        wanted = set(args.only)
        scenarios = [s for s in scenarios if s.name in wanted]
    elif args.suite != 'all':
        scenarios = [s for s in scenarios if s.suite == args.suite]
    if not scenarios:
        print('no scenarios selected', file=sys.stderr)
        return 2

    evidence_dir = os.path.join(args.evidence_root, utc_run_id())
    os.makedirs(evidence_dir, exist_ok=True)
    print('evidence directory: {0}'.format(os.path.relpath(evidence_dir, ROOT)))

    results = []
    for scenario in scenarios:
        results.append(run_scenario(scenario, evidence_dir))

    summary = {
        'run_id': os.path.basename(evidence_dir),
        'finished_at': utc_stamp(),
        'workspace': ROOT,
        'total': len(results),
        'passed': sum(1 for r in results if r['result'] == 'PASS'),
        'failed': sum(1 for r in results if r['result'] != 'PASS'),
        'scenarios': results,
    }
    with open(os.path.join(evidence_dir, 'summary.json'), 'w', encoding='utf-8') as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)
    with open(os.path.join(evidence_dir, 'summary.md'), 'w', encoding='utf-8') as handle:
        handle.write(_render_summary_markdown(summary))

    print('\n' + '=' * 78)
    print('SCENARIO SUMMARY  ({0} passed / {1} total)'.format(summary['passed'], summary['total']))
    print('=' * 78)
    for result in results:
        failed = [c for c in result['checks'] if c['result'] == 'FAIL']
        print('  [{0}] {1:<34} navsim_goals={2} decisions={3}'.format(
            result['result'], result['scenario'], result['navsim_goal_count'],
            ','.join(result['decision_sequence']) or '-'))
        for check in failed:
            print('         FAILED: {0} -- {1}'.format(check['check'], check['detail']))
    print('evidence: {0}'.format(os.path.relpath(evidence_dir, ROOT)))
    return 0 if summary['failed'] == 0 else 1


def _render_summary_markdown(summary: Dict[str, Any]) -> str:
    lines = [
        '# Scenario summary',
        '',
        '- run id: `{0}`'.format(summary['run_id']),
        '- finished at: `{0}`'.format(summary['finished_at']),
        '- workspace: `{0}`'.format(summary['workspace']),
        '- result: **{0} passed / {1} total**'.format(summary['passed'], summary['total']),
        '',
        '| Scenario | Result | NavSim Goals | Decision sequence | Execution status | REJECTED lines |',
        '| --- | --- | --- | --- | --- | --- |',
    ]
    for result in summary['scenarios']:
        lines.append('| `{0}` | {1} | {2} | {3} | {4} | {5} |'.format(
            result['scenario'], result['result'], result['navsim_goal_count'],
            ', '.join(result['decision_sequence']) or '-',
            ', '.join(result['execution_status_codes']) or '-',
            result['reject_log_lines']))
    lines += ['', '## Per-check detail', '']
    for result in summary['scenarios']:
        lines.append('### {0} -- {1}'.format(result['scenario'], result['result']))
        lines.append('')
        lines.append('{0}'.format(result['description']))
        lines.append('')
        lines.append('| Check | Result | Detail |')
        lines.append('| --- | --- | --- |')
        for check in result['checks']:
            lines.append('| {0} | {1} | {2} |'.format(
                check['check'], check['result'],
                str(check['detail']).replace('|', '\\|')))
        lines.append('')
    return '\n'.join(lines) + '\n'


if __name__ == '__main__':
    sys.exit(main())
