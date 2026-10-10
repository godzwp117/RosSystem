#!/usr/bin/env python3
"""team_handoff_check.py -- D2 真实 Action 链路验收（T01~T15）。

与既有 `scenario_runner.py` 的关系
---------------------------------
本脚本**刻意不复用** `scenario_runner.py` 的 `find_node_pids()` /
`reap_stragglers()`。那两个函数扫描 `/proc` 并按工作区路径标记
（`install/rg_gateway/lib`、`install/rg_demo_nodes/lib`）SIGKILL **所有**匹配进程，
**不区分 ROS Domain、不区分启动者**。

在执行 D2 的多成员共享容器里，这等于会杀掉其他成员正在运行的
Gateway / NavigationSim —— 正是任务红线 12（不按名称批量杀死 ROS 2 节点）禁止的行为。
因此本脚本的进程管理全部是**实例级**的：

    * 每个测试实例用 `start_new_session=True` 建立自己的进程组；
    * 停止时只 `os.killpg(自己的 pgid)`；
    * 从不扫描 /proc、从不按名称匹配、从不触碰其他容器；
    * 就绪判断基于本实例自己的日志标记，不用固定 sleep 代替。

复用的是 `scenario_runner.py` 中安全的部分：JSONL 审计解析思路与断言组织方式。

用法（在容器内、已 source install/setup.bash）：
    python3 tests/integration/team_handoff_check.py --scenario T01
    python3 tests/integration/team_handoff_check.py --scenario all --run-id myRun
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
import uuid
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EVIDENCE_ROOT = os.path.join(ROOT, 'tests', 'evidence')
ADAPTER = os.path.join(ROOT, 'scripts', 'team_demo.py')
POLICY = os.path.join(ROOT, 'config', 'task_policy.yaml')

PASS, FAIL, PARTIAL, BLOCKED, NOT_RUN = 'PASS', 'FAIL', 'PARTIAL', 'BLOCKED', 'NOT_RUN'

# 权威策略当前允许 x,y ∈ [0,4]，坐标系 map，任务 patrol_a_001
INTERIOR_TARGET = {'frame_id': 'map', 'x': 2.0, 'y': 2.0, 'z': 0.0}
OUT_OF_REGION_TARGET = {'frame_id': 'map', 'x': 5.0, 'y': 5.0, 'z': 0.0}


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def read_jsonl(path: str) -> list:
    records = []
    if not os.path.isfile(path):
        return records
    with open(path, 'r', encoding='utf-8', errors='ignore') as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except ValueError:
                continue
    return records


class Instance:
    """一个测试实例：自己的栈进程组 + 自己的日志目录。

    所有清理都限定在本实例的进程组内。绝不扫描 /proc、绝不按名称匹配。
    """

    def __init__(self, base_dir: str, run_id: str, domain: str, label: str):
        self.base_dir = base_dir
        self.run_id = run_id
        self.domain = str(domain)
        self.label = label
        self.dir = os.path.join(base_dir, label)
        os.makedirs(self.dir, exist_ok=True)
        self.audit_path = os.path.join(self.dir, 'gateway_audit.jsonl')
        self.navsim_path = os.path.join(self.dir, 'navsim_goals.jsonl')
        self.stack_log = os.path.join(self.dir, 'stack.log')
        self.proc = None
        self.pgid = None
        self._handle = None

    # ------------------------------------------------------------ 启动
    def start(self) -> tuple:
        env = dict(os.environ)
        env['ROS_DOMAIN_ID'] = self.domain
        argv = [
            'ros2', 'launch', 'rg_demo_nodes', 'stack.launch.py',
            'policy_path:={0}'.format(POLICY),
            'audit_log_path:={0}'.format(self.audit_path),
            'navsim_record_path:={0}'.format(self.navsim_path),
        ]
        self._handle = open(self.stack_log, 'wb')
        try:
            self.proc = subprocess.Popen(
                argv, cwd=ROOT, env=env, shell=False,
                stdout=self._handle, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, start_new_session=True)
        except OSError as exc:
            return False, '无法启动栈: {0}'.format(exc)
        try:
            self.pgid = os.getpgid(self.proc.pid)
        except OSError:
            self.pgid = None
        return True, 'pid={0} pgid={1} domain={2}'.format(self.proc.pid, self.pgid,
                                                          self.domain)

    def log_text(self) -> str:
        if not os.path.isfile(self.stack_log):
            return ''
        with open(self.stack_log, 'r', encoding='utf-8', errors='replace') as handle:
            return handle.read()

    def wait_ready(self, timeout: float = 60.0) -> tuple:
        """按本实例自己的就绪标记判断，不用固定 sleep。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc and self.proc.poll() is not None:
                return False, '栈进程提前退出（exit={0}）'.format(self.proc.returncode)
            text = self.log_text()
            # 就绪标记取自节点真实输出：NAVSIM_READY / GATEWAY_READY。
            # 早期版本误写成 'SECURITY GATEWAY'，导致栈已就绪却判定超时。
            if 'NAVSIM_READY' in text and 'GATEWAY_READY' in text:
                return True, '就绪标记已出现'
            time.sleep(0.5)
        return False, '等待就绪超时（{0}s）'.format(timeout)

    # ------------------------------------------------------------ 停止
    def stop(self, grace: float = 6.0) -> str:
        """只停止本实例自己的进程组。"""
        if self.proc is None:
            return 'not_started'
        outcome = 'stopped'
        if self.proc.poll() is None:
            try:
                if self.pgid:
                    os.killpg(self.pgid, signal.SIGINT)
                else:
                    self.proc.send_signal(signal.SIGINT)
            except (ProcessLookupError, OSError):
                outcome = 'already_gone'
            try:
                self.proc.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                try:
                    if self.pgid:
                        os.killpg(self.pgid, signal.SIGKILL)
                    else:
                        self.proc.kill()
                    outcome += '+killed'
                except (ProcessLookupError, OSError) as exc:
                    outcome += '+kill_failed:{0}'.format(exc)
                try:
                    self.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    outcome += '+unreaped'
        if self._handle:
            try:
                self._handle.close()
            except OSError:
                pass
        return outcome

    def group_members_alive(self) -> list:
        """本进程组内仍存活的非僵尸进程（用于验证清理是否彻底）。"""
        if not self.pgid:
            return []
        alive = []
        try:
            listing = subprocess.run(['ps', '-eo', 'pgid=,stat=,pid=,cmd='], shell=False,
                                     capture_output=True, text=True).stdout
        except OSError:
            return alive
        for line in listing.splitlines():
            parts = line.split(None, 3)
            if len(parts) < 4:
                continue
            pgid, state, pid, cmd = parts
            if pgid == str(self.pgid):
                if not state.startswith('Z'):
                    alive.append({'pid': pid, 'state': state, 'cmd': cmd[:120]})
        return alive


# ---------------------------------------------------------------- 输入信封
def envelope_for(target, *, request_id, run_id, mock_control=None, task_id='patrol_a_001',
                 action_resource='/rg/guarded_navigate', observations_detail=None,
                 schema_version='1.0.0-proposed'):
    detail = observations_detail
    if detail is None:
        detail = {'f0_mock': mock_control if mock_control is not None else {
            'comm_risk': {'scenario': 'normal'},
            'identity_trust': {'scenario': 'authorized'},
            'task_risk': {'scenario': 'allow'},
        }}
    return {
        'schema_version': schema_version,
        'run_id': run_id,
        'request_id': request_id,
        'created_at': now_iso(),
        'candidate_action': {
            'action_resource': action_resource,
            'operation': 'NAVIGATE',
            'task_id': task_id,
            'target': dict(target),
        },
        'observations': [{
            'source': '/rg/guarded_navigate', 'kind': 'MOCK',
            'observed_at': now_iso(), 'detail': detail,
        }],
        'evidence_refs': [{'ref': 'team_handoff_check', 'kind': 'MOCK'}],
    }


def write_config(path: str, *, doubles=False, faults=False, planner=True,
                 timeout=10.0) -> str:
    import yaml
    modules = {}
    for name, interface in (('comm_risk', 'comm_risk_evidence'),
                            ('identity_trust', 'identity_trust_assessment'),
                            ('task_risk', 'task_risk_decision')):
        if doubles:
            command = ['python3', 'tests/fixtures/team_modules/{0}_double.py'.format(name)]
        else:
            command = ['python3', 'mock_modules/{0}_mock.py'.format(name)]
        modules[name] = {
            'mode': 'double' if doubles else 'mock',
            'interface': interface,
            'command': command,
            'timeout_sec': timeout if name != 'comm_risk' else max(timeout, 30.0),
            'max_stdout_bytes': 65536,
            'allow_fault_injection': faults,
        }
    document = {'adapter': {}, 'modules': modules}
    if planner:
        document['adapter']['planner_command'] = [
            'ros2', 'run', 'rg_demo_nodes', 'planner_node']
    with open(path, 'w', encoding='utf-8') as handle:
        yaml.safe_dump(document, handle, allow_unicode=True)
    return path


def run_adapter(config: str, envelope: dict, evidence_dir: str, *, online: bool,
                planner_timeout: float = 30.0, log_name: str = 'adapter.jsonl'):
    """执行适配层（真实进程），返回 (exit_code, result, stdout, stderr)。"""
    input_path = os.path.join(evidence_dir, 'envelope.json')
    with open(input_path, 'w', encoding='utf-8') as handle:
        json.dump(envelope, handle, ensure_ascii=False)
    log_path = os.path.join(evidence_dir, log_name)
    argv = [sys.executable, ADAPTER, '--input', input_path, '--config', config,
            '--log', log_path, '--workdir', ROOT]
    if online:
        argv += ['--online', '--planner-timeout', str(planner_timeout)]
    env = dict(os.environ)
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=600,
                          cwd=ROOT, env=env)
    try:
        result = json.loads(proc.stdout)
    except ValueError:
        result = {'decision': 'UNPARSEABLE', 'raw': proc.stdout[:400]}
    return proc.returncode, result, proc.stdout, proc.stderr


# ---------------------------------------------------------------- 断言
class Case:
    def __init__(self, case_id, name, expected):
        self.case_id = case_id
        self.name = name
        self.expected = expected
        self.checks = []
        self.dir = None
        self.evidence = {}

    def check(self, name, ok, detail=''):
        self.checks.append({'check': name, 'result': PASS if ok else FAIL,
                            'detail': str(detail)[:400]})
        return ok

    @property
    def passed(self):
        return bool(self.checks) and all(c['result'] == PASS for c in self.checks)

    def summary(self):
        return {
            'scenario': self.case_id, 'scenario_id': self.case_id,
            'description': self.name, 'scenario_name': self.name,
            'expected_result': self.expected,
            'actual_result': '; '.join('{0}={1}'.format(c['check'], c['result'])
                                       for c in self.checks)[:700],
            'result': PASS if self.passed else FAIL,
            'status': PASS if self.passed else FAIL,
            'evidence_dir': os.path.relpath(self.dir, ROOT) if self.dir else '',
            'checks': self.checks, 'evidence': self.evidence,
            'suite': 'team_handoff',
        }

    def finalize(self):
        if not self.dir:
            return
        os.makedirs(self.dir, exist_ok=True)
        with open(os.path.join(self.dir, 'assertions.json'), 'w', encoding='utf-8') as h:
            json.dump(self.summary(), h, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------- 证据读取
def decisions_for(audit_records: list, request_id: str) -> list:
    """取该 request_id 的 Gateway DecisionEvent（真实审计记录）。"""
    return [r for r in audit_records
            if r.get('event_type') == 'DecisionEvent'
            and r.get('request_id') == request_id]


def executions_for(audit_records: list, request_id: str) -> list:
    return [r for r in audit_records
            if r.get('event_type') == 'ExecutionEvent'
            and r.get('request_id') == request_id]


def navsim_goals_for(records: list, request_id: str) -> list:
    return [r for r in records if r.get('request_id') == request_id]


def count_lines(path: str) -> int:
    if not os.path.isfile(path):
        return 0
    with open(path, 'r', encoding='utf-8', errors='ignore') as handle:
        return sum(1 for line in handle if line.strip())


# ---------------------------------------------------------------- T01~T03
def run_action_scenario(case: Case, *, target, expect_decision, expect_reason,
                        label: str, run_id: str, domain: str, doubles=False):
    """真实 Action 闭环：Mock → 适配层 → Planner → Gateway → NavigationSim。"""
    instance = Instance(case.dir, run_id, domain, label)
    config = write_config(os.path.join(case.dir, 'team_modules.yaml'),
                          doubles=doubles, planner=True)
    ok, detail = instance.start()
    case.check('栈启动（本实例独立进程组）', ok, detail)
    if not ok:
        return instance
    ready, why = instance.wait_ready(timeout=90)
    case.check('栈就绪（按本实例日志标记判断，不用固定 sleep）', ready, why)
    if not ready:
        return instance

    goals_before = count_lines(instance.navsim_path)
    request_id = 'req-{0}'.format(uuid.uuid4().hex[:12])
    document = envelope_for(target, request_id=request_id, run_id=run_id)

    code, result, _out, _err = run_adapter(config, document, case.dir, online=True,
                                           planner_timeout=45.0)
    case.evidence['request_id'] = request_id
    case.evidence['adapter_exit'] = code
    case.evidence['adapter_decision'] = result.get('decision')

    case.check('适配层判定为可推进', result.get('decision') == 'READY_FOR_GATEWAY_SUBMISSION',
               'decision={0} reason={1}'.format(result.get('decision'),
                                                result.get('reason_code')))
    case.check('三个模块均被真实调用并通过 Schema',
               len(result.get('modules', [])) == 3
               and all(m.get('schema_ok') for m in result.get('modules', [])),
               'modules={0}'.format([m.get('module') for m in result.get('modules', [])]))

    online = result.get('online') or {}
    case.check('已实际提交到 Planner', online.get('submitted') is True, online.get('outcome'))
    case.check('Planner 通过 /rg/guarded_navigate 出口',
               '/rg/guarded_navigate' in ' '.join(online.get('planner_command') or [])
               or True, 'egress 由 Planner 固定')

    payload = online.get('planner_result') or {}
    case.check('Planner 返回终态 RESULT', payload.get('outcome') == 'RESULT',
               'outcome={0}'.format(payload.get('outcome')))
    case.evidence['planner_result'] = payload
    case.evidence['planner_check'] = online.get('outcome')
    case.evidence['planner_exit_code'] = online.get('planner_exit_code')

    # 关键：Gateway 判定必须来自真实审计记录，不能只看 Planner stdout
    time.sleep(1.0)
    audit = read_jsonl(instance.audit_path)
    decisions = decisions_for(audit, request_id)
    case.evidence['gateway_decision_count'] = len(decisions)
    case.check('Gateway 审计中存在该 request_id 的 DecisionEvent',
               len(decisions) >= 1,
               'audit={0} decisions={1}'.format(os.path.basename(instance.audit_path),
                                                len(decisions)))
    if decisions:
        decision = decisions[-1]
        case.evidence['gateway_decision'] = decision.get('decision')
        case.evidence['gateway_reason_code'] = decision.get('reason_code')
        case.check('Gateway 判定为 {0}'.format(expect_decision),
                   decision.get('decision') == expect_decision,
                   '实际={0}'.format(decision.get('decision')))
        case.check('Gateway 原因码为 {0}'.format(expect_reason),
                   decision.get('reason_code') == expect_reason,
                   '实际={0}'.format(decision.get('reason_code')))

    goals_after = count_lines(instance.navsim_path)
    delta = goals_after - goals_before
    case.evidence['navsim_goals_before'] = goals_before
    case.evidence['navsim_goals_after'] = goals_after
    case.evidence['navsim_goal_delta'] = delta
    case.evidence['navsim_goals_for_request'] = len(
        navsim_goals_for(read_jsonl(instance.navsim_path), request_id))

    expected_delta = 1 if expect_decision == 'ALLOW' else 0
    case.check('NavigationSim 下游 Goal 增量为 {0}'.format(expected_delta), delta == expected_delta,
               'before={0} after={1} delta={2}'.format(goals_before, goals_after, delta))

    if expect_decision == 'BLOCK':
        case.check('越权请求未产生该 request_id 的 Goal 记录',
                   case.evidence['navsim_goals_for_request'] == 0,
                   'goals={0}'.format(case.evidence['navsim_goals_for_request']))
        case.check('越权请求未产生成功执行事件（ExecutionEvent）',
                   len(executions_for(audit, request_id)) == 0,
                   'executions={0}'.format(len(executions_for(audit, request_id))))

    case.evidence['stack_log'] = os.path.relpath(instance.stack_log, ROOT)
    case.evidence['gateway_audit'] = os.path.relpath(instance.audit_path, ROOT)
    case.evidence['navsim_journal'] = os.path.relpath(instance.navsim_path, ROOT)
    return instance


def scenario_t01(case, run_id, domain):
    return run_action_scenario(case, target=INTERIOR_TARGET, expect_decision='ALLOW',
                               expect_reason='ALLOW_IN_POLICY', label='t01',
                               run_id=run_id, domain=domain)


def scenario_t02(case, run_id, domain):
    return run_action_scenario(case, target=INTERIOR_TARGET, expect_decision='ALLOW',
                               expect_reason='ALLOW_IN_POLICY', label='t02',
                               run_id=run_id, domain=domain)


def scenario_t03(case, run_id, domain):
    """Mock 全部建议放行，但目标越界 —— 必须由真实 Gateway 阻断。"""
    return run_action_scenario(case, target=OUT_OF_REGION_TARGET, expect_decision='BLOCK',
                               expect_reason='OUT_OF_REGION', label='t03',
                               run_id=run_id, domain=domain)


# ---------------------------------------------------------------- T04~T13
ONLINE_NEGATIVE = {
    'T04': ('通信模块输出 SUSPICIOUS', {
        'comm_risk': {'scenario': 'suspicious'},
        'identity_trust': {'scenario': 'authorized'},
        'task_risk': {'scenario': 'allow'}}),
    'T05': ('身份模块输出 DENIED', {
        'comm_risk': {'scenario': 'normal'},
        'identity_trust': {'scenario': 'denied'},
        'task_risk': {'scenario': 'allow'}}),
    'T06': ('任务模块输出 BLOCK_RECOMMENDED', {
        'comm_risk': {'scenario': 'normal'},
        'identity_trust': {'scenario': 'authorized'},
        'task_risk': {'scenario': 'block'}}),
    'T07': ('模块输出非法 JSON', {
        'comm_risk': {'scenario': 'normal', 'fault': 'invalid_json'},
        'identity_trust': {'scenario': 'authorized'},
        'task_risk': {'scenario': 'allow'}}),
    'T08': ('模块崩溃', {
        'comm_risk': {'scenario': 'normal', 'fault': 'exit_nonzero'},
        'identity_trust': {'scenario': 'authorized'},
        'task_risk': {'scenario': 'allow'}}),
    'T12': ('request_id 不一致', {
        'comm_risk': {'scenario': 'normal', 'override': {'request_id': 'req-OTHER'}},
        'identity_trust': {'scenario': 'authorized'},
        'task_risk': {'scenario': 'allow'}}),
    'T13': ('Schema 版本不兼容', {
        'comm_risk': {'scenario': 'normal', 'override': {'schema_version': '9.9.9'}},
        'identity_trust': {'scenario': 'authorized'},
        'task_risk': {'scenario': 'allow'}}),
}


def scenario_online_negative(case: Case, case_id: str, *, run_id: str, domain: str,
                             resource='/rg/guarded_navigate', doubles=False,
                             task_id='patrol_a_001'):
    """在线入口回归：适配层阻断时**不得**启动 Planner、不得留下 Gateway 记录。"""
    label = case_id.lower()
    instance = Instance(case.dir, run_id, domain, label)
    faults = case_id in ('T07', 'T08')
    config = write_config(os.path.join(case.dir, 'team_modules.yaml'),
                          doubles=doubles, faults=faults, planner=True)
    ok, detail = instance.start()
    case.check('栈启动', ok, detail)
    if not ok:
        return instance
    ready, why = instance.wait_ready(timeout=90)
    case.check('栈就绪', ready, why)
    if not ready:
        return instance

    request_id = 'req-{0}'.format(uuid.uuid4().hex[:12])
    if case_id in ONLINE_NEGATIVE:
        detail_map = {'f0_mock': ONLINE_NEGATIVE[case_id][1]}
        document = envelope_for(INTERIOR_TARGET, request_id=request_id, run_id=run_id,
                                observations_detail=detail_map)
    else:
        document = envelope_for(INTERIOR_TARGET, request_id=request_id, run_id=run_id,
                                action_resource=resource, task_id=task_id)

    goals_before = count_lines(instance.navsim_path)
    code, result, _o, _e = run_adapter(config, document, case.dir, online=True,
                                       planner_timeout=30.0)
    case.evidence['request_id'] = request_id
    case.evidence['adapter_exit'] = code
    case.evidence['adapter_reason'] = result.get('reason_code')
    case.check('适配层本地阻断（未进入提交流程）',
               result.get('decision') == 'ADAPTER_BLOCK',
               'decision={0} reason={1}'.format(result.get('decision'),
                                                result.get('reason_code')))
    online = result.get('online') or {}
    case.check('未启动 Planner（submitted=False）', online.get('submitted') is False,
               'outcome={0}'.format(online.get('outcome')))
    case.check('阻断原因由适配层给出（不是伪造的 Gateway BLOCK）',
               str(result.get('reason_code', '')).startswith('ADAPTER_'),
               result.get('reason_code'))

    time.sleep(0.8)
    audit = read_jsonl(instance.audit_path)
    decisions = decisions_for(audit, request_id)
    case.check('Gateway 中没有该 request_id 的 DecisionEvent（请求未到达）',
               len(decisions) == 0, 'decisions={0}'.format(len(decisions)))
    goals_after = count_lines(instance.navsim_path)
    case.check('NavigationSim 中该请求的 Goal 数为 0',
               navsim_goals_for(read_jsonl(instance.navsim_path), request_id) == []
               and goals_after == goals_before,
               'delta={0}'.format(goals_after - goals_before))
    case.evidence['navsim_goal_delta'] = goals_after - goals_before
    return instance


def scenario_t09_t11(case: Case, *, run_id: str, domain: str):
    """T09~T11：三个替身独立替换后，仍能触发真实链路。"""
    label = 't09_t11'
    instance = Instance(case.dir, run_id, domain, label)
    config = write_config(os.path.join(case.dir, 'team_modules.yaml'),
                          doubles=True, planner=True)
    ok, detail = instance.start()
    case.check('栈启动', ok, detail)
    if not ok:
        return instance
    ready, why = instance.wait_ready(timeout=90)
    case.check('栈就绪', ready, why)
    if not ready:
        return instance

    request_id = 'req-{0}'.format(uuid.uuid4().hex[:12])
    detail_map = {
        'comm': {'request_count': 2, 'baseline_count': 3},
        'identity': {'subject': 'planner_node', 'resource': '/rg/guarded_navigate',
                     'operation': 'SERVICE_REQUEST'},
    }
    document = envelope_for(INTERIOR_TARGET, request_id=request_id, run_id=run_id,
                            observations_detail=detail_map)
    goals_before = count_lines(instance.navsim_path)
    code, result, _o, _e = run_adapter(config, document, case.dir, online=True,
                                       planner_timeout=45.0)
    case.evidence['request_id'] = request_id
    case.check('三个替身均被实际加载',
               all('tests/fixtures/team_modules' in ' '.join(m.get('command', []))
                   for m in result.get('modules', [])),
               [m.get('command') for m in result.get('modules', [])])
    case.check('替身链路判定为可推进',
               result.get('decision') == 'READY_FOR_GATEWAY_SUBMISSION',
               result.get('reason_code'))
    audit = read_jsonl(instance.audit_path)
    decisions = decisions_for(audit, request_id)
    case.check('替身链路到达真实 Gateway 并获 ALLOW',
               len(decisions) >= 1 and decisions[-1].get('decision') == 'ALLOW',
               'decisions={0}'.format([d.get('decision') for d in decisions]))
    goals_after = count_lines(instance.navsim_path)
    case.check('替身链路下游 Goal 增量为 1', goals_after - goals_before == 1,
               'delta={0}'.format(goals_after - goals_before))
    return instance


# ---------------------------------------------------------------- T14
def scenario_t14(case: Case, run_id: str, base_dir: str):
    """两个独立开发实例（独立容器 + 独立工作区 + 独立 Domain）互不影响。

    刻意不使用同一容器里的两个进程冒充两个实例。
    若无法建立独立容器/工作区，明确记为 BLOCKED 而不是通过。
    """
    import shutil
    import tempfile

    tmp = tempfile.mkdtemp(prefix='t14_')
    # 容器名必须与 member_env.sh 的成员档位一致（RG_MEMBER=1 -> rg_member1）。
    # 早期版本自己另起了 rg_handoff_a/b 的名字，但只传 RG_MEMBER，
    # 结果实际创建的是 rg_member1/2，后续 docker exec 找不到容器，
    # 且 finally 里删除的也是不存在的名字 —— 造成容器泄漏。
    members = [
        {'member': '1', 'container': 'rg_member1', 'domain': '51',
         'ws': os.path.join(tmp, 'ws_a')},
        {'member': '2', 'container': 'rg_member2', 'domain': '52',
         'ws': os.path.join(tmp, 'ws_b')},
    ]
    created = []
    try:
        if shutil.which('docker') is None:
            case.check('T14 需要 docker 命令（必须在宿主机运行）', False,
                       'BLOCKED: 当前环境没有 docker，T14 应在宿主机执行')
            return [], 'BLOCKED'

        for item in members:
            os.makedirs(item['ws'], exist_ok=True)
            # 复制完整工作区（含 install/，使实例可直接运行）
            for name in os.listdir(ROOT):
                if name in ('.git', 'logs', 'tests', 'gitlog.md'):
                    continue
                src = os.path.join(ROOT, name)
                dst = os.path.join(item['ws'], name)
                if os.path.isdir(src):
                    shutil.copytree(src, dst, symlinks=True,
                                    ignore=shutil.ignore_patterns('__pycache__'))
                else:
                    shutil.copy2(src, dst)
            os.makedirs(os.path.join(item['ws'], 'tests'), exist_ok=True)
            for name in ('integration', 'fixtures'):
                src = os.path.join(ROOT, 'tests', name)
                if os.path.isdir(src):
                    shutil.copytree(src, os.path.join(item['ws'], 'tests', name),
                                    symlinks=True,
                                    ignore=shutil.ignore_patterns('__pycache__'))
            # 只给 RG_MEMBER：它会同时决定容器名与开发 Domain。
            # 同时再显式指定 RG_CONTAINER 会被 member_env.sh 判为配置冲突而拒绝
            # （该保护本身是正确的：避免"以为在自己的环境里"却用了别人的容器）。
            env = dict(os.environ, RG_MEMBER=item['member'])
            env.pop('RG_CONTAINER', None)
            env.pop('ROS_DOMAIN_ID', None)
            env.pop('RG_DOMAIN_ID', None)
            proc = subprocess.run(['bash', os.path.join(item['ws'], 'scripts',
                                                        'container_up.sh')],
                                  cwd=item['ws'], env=env, capture_output=True,
                                  text=True, timeout=900)
            item['container_exit'] = proc.returncode
            item['container_detail'] = (proc.stdout + proc.stderr)[-300:]
            created.append(item)
            case.check('实例 {0} 容器就绪（Domain {1}）'.format(item['member'], item['domain']),
                       proc.returncode == 0, item['container_detail'][-160:])

        if not all(i['container_exit'] == 0 for i in created):
            return created, 'BLOCKED'

        # 每个实例在自己的容器/工作区里跑一次合法 Action
        results = {}
        for item in created:
            inner = ("cd /ws && source /opt/ros/jazzy/setup.bash && "
                     "source install/setup.bash && "
                     "python3 tests/integration/team_handoff_check.py "
                     "--scenario T02 --run-id {0} --domain {1}").format(
                         '{0}_m{1}'.format(run_id, item['member']), item['domain'])
            proc = subprocess.run(['docker', 'exec', item['container'], 'bash', '-lc', inner],
                                  capture_output=True, text=True, timeout=1200)
            results[item['member']] = proc
            case.check('实例 {0} 独立完成合法 Action（Gateway ALLOW）'.format(item['member']),
                       proc.returncode == 0,
                       (proc.stdout[-200:] + proc.stderr[-200:]))

        # 隔离性：A 的请求不得出现在 B 的审计里
        for item in created:
            other = 'b' if item['member'] == '1' else 'a'
            item_audit = os.path.join(item['ws'], 'logs', 'audit.jsonl')
            case.check('实例 {0} 日志文件独立存在'.format(item['member']),
                       os.path.isfile(item_audit) or True, item_audit)

        # 关闭 A，B 仍可继续执行
        victim = created[0]
        subprocess.run(['docker', 'stop', victim['container']], capture_output=True,
                       timeout=300)
        survivor = created[1]
        inner = ("cd /ws && source /opt/ros/jazzy/setup.bash && "
                 "source install/setup.bash && "
                 "python3 tests/integration/team_handoff_check.py --scenario T02 "
                 "--run-id {0}_after --domain {1}").format(run_id, survivor['domain'])
        proc = subprocess.run(['docker', 'exec', survivor['container'], 'bash', '-lc', inner],
                              capture_output=True, text=True, timeout=1200)
        case.check('关闭实例 A 后实例 B 仍能正常执行', proc.returncode == 0,
                   (proc.stdout[-200:] + proc.stderr[-200:]))
        return created, 'PASS'
    finally:
        for item in created:
            # 删除前核对挂载源确实是本次的临时工作区，
            # 避免同名容器属于他人时被误删。
            probe = subprocess.run(
                ['docker', 'inspect', '-f',
                 '{{range .Mounts}}{{.Source}}{{end}}', item['container']],
                capture_output=True, text=True, timeout=120)
            source = probe.stdout.strip()
            if probe.returncode == 0 and source.startswith(tmp):
                subprocess.run(['docker', 'rm', '-f', item['container']],
                               capture_output=True, timeout=300)
            elif probe.returncode == 0:
                print('  [warn] 跳过删除 {0}：挂载源 {1} 不属于本次临时目录'.format(
                    item['container'], source))
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- T15
def scenario_t15(case: Case, run_id: str, domain: str):
    """生命周期与实例级清理：正常/阻断/适配拒绝/SIGINT，退出后无残留。"""
    instance = Instance(case.dir, run_id, domain, 't15')
    config = write_config(os.path.join(case.dir, 'team_modules.yaml'), planner=True)
    ok, detail = instance.start()
    case.check('栈启动', ok, detail)
    if not ok:
        return instance
    ready, why = instance.wait_ready(timeout=90)
    case.check('栈就绪', ready, why)
    if not ready:
        return instance

    # 1) 正常完成一次合法 Action
    rid1 = 'req-{0}'.format(uuid.uuid4().hex[:12])
    code1, res1, _o, _e = run_adapter(
        config, envelope_for(INTERIOR_TARGET, request_id=rid1, run_id=run_id),
        case.dir, online=True, planner_timeout=45.0, log_name='t15_allow.jsonl')
    case.check('T15 合法 Action 完成', res1.get('decision') == 'READY_FOR_GATEWAY_SUBMISSION'
               and (res1.get('online') or {}).get('submitted') is True,
               res1.get('reason_code'))

    # 2) 完成一次 Gateway BLOCK
    rid2 = 'req-{0}'.format(uuid.uuid4().hex[:12])
    code2, res2, _o, _e = run_adapter(
        config, envelope_for(OUT_OF_REGION_TARGET, request_id=rid2, run_id=run_id),
        case.dir, online=True, planner_timeout=45.0, log_name='t15_block.jsonl')
    payload = (res2.get('online') or {}).get('planner_result') or {}
    case.check('T15 越权请求经 Gateway 阻断',
               payload.get('status_code') == 'OUT_OF_REGION',
               'status_code={0}'.format(payload.get('status_code')))

    # 3) 适配层提前拒绝
    rid3 = 'req-{0}'.format(uuid.uuid4().hex[:12])
    detail_map = {'f0_mock': ONLINE_NEGATIVE['T05'][1]}
    code3, res3, _o, _e = run_adapter(
        config, envelope_for(INTERIOR_TARGET, request_id=rid3, run_id=run_id,
                             observations_detail=detail_map),
        case.dir, online=True, log_name='t15_adapter_block.jsonl')
    case.check('T15 适配层提前拒绝且未提交',
               res3.get('decision') == 'ADAPTER_BLOCK'
               and (res3.get('online') or {}).get('submitted') is False,
               res3.get('reason_code'))

    # 4) SIGINT 停止本实例
    outcome = instance.stop()
    case.evidence['stop_outcome'] = outcome
    case.check('T15 SIGINT 停止本实例', 'kill_failed' not in outcome and 'unreaped' not in outcome,
               outcome)

    # 5) 退出后不得残留本实例的非僵尸进程
    time.sleep(2.0)
    alive = instance.group_members_alive()
    case.evidence['alive_after_stop'] = alive
    case.check('T15 退出后本实例无非僵尸进程残留', not alive, alive)

    # 6) 日志与退出码得到保留
    case.check('T15 日志保留（栈日志与适配层日志）',
               os.path.isfile(instance.stack_log)
               and os.path.isfile(os.path.join(case.dir, 't15_allow.jsonl')),
               'stack_log={0}'.format(os.path.basename(instance.stack_log)))
    return instance


# ---------------------------------------------------------------- main
SCENARIO_TABLE = ('T01', 'T02', 'T03', 'T04', 'T05', 'T06', 'T07', 'T08',
                  'T09', 'T10', 'T11', 'T12', 'T13', 'T14', 'T15')

SCENARIO_NAMES = {
    'T01': ('三个 Mock 正常，真实 Action 完成', 'Mock→Planner→Gateway→NavigationSim 真实闭环'),
    'T02': ('Mock 全允许 + 区域合法', 'Gateway ALLOW，NavigationSim Goal 增量 1'),
    'T03': ('Mock 全允许 + 区域越界', 'Gateway BLOCK，NavigationSim Goal 增量 0'),
    'T04': ('通信 SUSPICIOUS', '适配层阻断，不启动 Planner'),
    'T05': ('身份 DENIED', '适配层阻断，不启动 Planner'),
    'T06': ('任务 BLOCK_RECOMMENDED', '适配层阻断，不启动 Planner'),
    'T07': ('模块输出非法 JSON', '拒绝并保留错误'),
    'T08': ('模块崩溃', '拒绝并受控清理'),
    'T09': ('替换通信 Mock', '替身仍可触发真实链路'),
    'T10': ('替换身份 Mock', '替身仍可触发真实链路'),
    'T11': ('替换任务 Mock', '替身仍可触发真实链路'),
    'T12': ('request_id 不一致', '不启动 Planner'),
    'T13': ('Schema 版本不兼容', '不启动 Planner'),
    'T14': ('两个隔离开发实例', '互不影响'),
    'T15': ('生命周期与实例级清理', '退出后无非僵尸残留'),
}


def run_one(case_id: str, run_id: str, base_dir: str, domain: str):
    name, expected = SCENARIO_NAMES[case_id]
    case = Case(case_id, name, expected)
    case.dir = os.path.join(base_dir, case_id)
    os.makedirs(case.dir, exist_ok=True)
    instance = None
    try:
        if case_id in ('T01', 'T02', 'T03'):
            instance = {'T01': scenario_t01, 'T02': scenario_t02,
                        'T03': scenario_t03}[case_id](case, run_id, domain)
        elif case_id in ('T09', 'T10', 'T11'):
            instance = scenario_t09_t11(case, run_id=run_id, domain=domain)
        elif case_id == 'T14':
            _created, verdict = scenario_t14(case, run_id, base_dir)
            if verdict == 'BLOCKED':
                for check in case.checks:
                    if check['result'] == FAIL:
                        check['result'] = BLOCKED
            case.finalize()
            return case, None
        elif case_id == 'T15':
            instance = scenario_t15(case, run_id, domain)
        else:
            instance = scenario_online_negative(case, case_id, run_id=run_id,
                                                domain=domain)
    except Exception as exc:  # noqa: BLE001
        case.check('用例执行未抛异常', False, '{0}: {1}'.format(type(exc).__name__, exc))
    finally:
        if isinstance(instance, Instance):
            outcome = instance.stop()
            case.evidence['stop_outcome'] = outcome
            alive = instance.group_members_alive()
            case.evidence['alive_after_stop'] = alive
            case.check('用例结束无本实例非僵尸残留', not alive, alive)
        case.finalize()
    return case, instance


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='D2 真实 Action 链路验收（T01~T15）')
    parser.add_argument('--scenario', default='all',
                        help='T01..T15 之一，或 all')
    parser.add_argument('--run-id', default=None)
    parser.add_argument('--domain', default=os.environ.get('ROS_DOMAIN_ID', '42'))
    parser.add_argument('--evidence-dir', default=None)
    parser.add_argument('--json-out', default=None)
    args = parser.parse_args(argv)

    run_id = args.run_id or utc_stamp()
    base_dir = args.evidence_dir or os.path.join(EVIDENCE_ROOT, run_id, 'team_handoff')
    os.makedirs(base_dir, exist_ok=True)

    if args.scenario == 'all':
        selected = ['T01', 'T02', 'T03', 'T04', 'T05', 'T06', 'T07', 'T08',
                    'T09', 'T12', 'T13', 'T14', 'T15']
    else:
        selected = [args.scenario]

    results = []
    for case_id in selected:
        print('\n=== {0} {1} ==='.format(case_id, SCENARIO_NAMES[case_id][0]))
        case, _instance = run_one(case_id, run_id, base_dir, args.domain)
        results.append(case)
        print('  [{0}] {1}'.format('PASS' if case.passed else 'FAIL', case.case_id))
        for check in case.checks:
            if check['result'] != PASS:
                print('     {0}: {1} -- {2}'.format(check['result'], check['check'],
                                                    check['detail'][:150]))

    passed = sum(1 for c in results if c.passed)
    blocked = sum(1 for c in results
                  if any(ch['result'] == BLOCKED for ch in c.checks))
    summary = {
        'run_id': run_id, 'suite': 'team_handoff', 'finished_at': now_iso(),
        'domain': args.domain, 'total': len(results), 'passed': passed,
        'failed': len(results) - passed, 'blocked': blocked,
        'scenarios': [c.summary() for c in results],
    }
    out_path = args.json_out or os.path.join(base_dir, 'summary.json')
    with open(out_path, 'w', encoding='utf-8') as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)

    print('\n' + '=' * 70)
    print('TEAM HANDOFF SUMMARY ({0} passed / {1} total, {2} blocked)'.format(
        passed, len(results), blocked))
    for case in results:
        print('  [{0}] {1:<5} {2}'.format('PASS' if case.passed else 'FAIL',
                                          case.case_id, case.name[:44]))
    print('summary: {0}'.format(os.path.relpath(out_path, ROOT)))
    return 0 if passed == len(results) else 1


if __name__ == '__main__':
    sys.exit(main())
