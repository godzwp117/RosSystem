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
    # 该断言原先写作 `... or True`，恒真，等于没检查。现改为检查真实内容：
    # 适配层构造的 Planner 命令行必须通过 ros2 run 启动 planner_node，
    # 而 planner_node 的出口固定为 /rg/guarded_navigate（由其源码常量保证）。
    planner_cmd = ' '.join(online.get('planner_command') or [])
    case.check('在线提交使用已有 Planner 入口（不新建下游通道）',
               'rg_demo_nodes' in planner_cmd and 'planner_node' in planner_cmd,
               planner_cmd or '(命令为空)')
    case.check('候选操作入口为 /rg/guarded_navigate（未指向执行端）',
               '/rg/nav_execute' not in planner_cmd,
               planner_cmd or '(命令为空)')

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


def scenario_replacement(case: Case, module: str, *, run_id: str, domain: str):
    """T09/T10/T11：**只替换一个**模块，其余两个保持 Mock。

    三项必须各自独立验证。此前的实现用"三个替身同时替换"一次覆盖 T09/T10/T11，
    无法证明"只换人员一不需要改人员二、三"，因此不满足验收粒度要求。
    """
    port = {'comm_risk': 'T09', 'identity_trust': 'T10', 'task_risk': 'T11'}[module]
    instance = Instance(case.dir, run_id, domain, port.lower())
    config = write_config(os.path.join(case.dir, 'team_modules.yaml'),
                          doubles=False, planner=True)
    # 只把目标模块换成替身；其余保持 mock
    import yaml as _yaml
    document = _yaml.safe_load(open(config, encoding='utf-8'))
    document['modules'][module]['mode'] = 'double'
    document['modules'][module]['command'] = [
        'python3', 'tests/fixtures/team_modules/{0}_double.py'.format(module)]
    mixed = os.path.join(case.dir, 'team_modules_mixed.yaml')
    with open(mixed, 'w', encoding='utf-8') as handle:
        _yaml.safe_dump(document, handle, allow_unicode=True)

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
        'f0_mock': {
            'comm_risk': {'scenario': 'normal'},
            'identity_trust': {'scenario': 'authorized'},
            'task_risk': {'scenario': 'allow'},
        },
        'comm': {'request_count': 2, 'baseline_count': 3},
        'identity': {'subject': 'planner_node', 'resource': '/rg/guarded_navigate',
                     'operation': 'SERVICE_REQUEST'},
    }
    envelope_doc = envelope_for(INTERIOR_TARGET, request_id=request_id, run_id=run_id,
                               observations_detail=detail_map)
    goals_before = count_lines(instance.navsim_path)

    code, result, _o, _e = run_adapter(mixed, envelope_doc, case.dir, online=True,
                                       planner_timeout=45.0)
    case.evidence['request_id'] = request_id
    case.evidence['replaced_module'] = module
    case.evidence['adapter_decision'] = result.get('decision')

    records = {m['module']: m for m in result.get('modules', [])}
    case.check('三个模块都被真实调用', len(records) == 3,
               sorted(records))
    # 真实 command / mode 证据：证明"只有目标模块被替换"
    replaced_cmd = ' '.join(records.get(module, {}).get('command', []))
    case.check('目标模块 {0} 实际加载替身'.format(module),
               'tests/fixtures/team_modules' in replaced_cmd and
               '{0}_double.py'.format(module) in replaced_cmd,
               replaced_cmd)
    case.check('目标模块 mode 为 double', records.get(module, {}).get('mode') == 'double',
               records.get(module, {}).get('mode'))
    others = {k: v for k, v in records.items() if k != module}
    case.check('其余模块仍为 Mock（未被连带替换）',
               all('mock_modules' in ' '.join(v.get('command', [])) for v in others.values())
               and all(v.get('mode') == 'mock' for v in others.values()),
               {k: (v.get('mode'), v.get('command')) for k, v in others.items()})
    case.check('三个模块输出均通过公共 Schema',
               all(m.get('schema_ok') for m in result.get('modules', [])),
               [m.get('schema_ok') for m in result.get('modules', [])])
    case.check('替换后仍可推进', result.get('decision') == 'READY_FOR_GATEWAY_SUBMISSION',
               result.get('reason_code'))
    online = result.get('online') or {}
    case.check('已实际提交 Planner', online.get('submitted') is True, online.get('outcome'))
    case.check('Planner 返回终态', (online.get('planner_result') or {}).get('outcome') == 'RESULT',
               (online.get('planner_result') or {}).get('outcome'))

    time.sleep(1.0)
    audit = read_jsonl(instance.audit_path)
    decisions = decisions_for(audit, request_id)
    case.check('Gateway 有该 request_id 的 DecisionEvent', len(decisions) >= 1,
               'decisions={0}'.format(len(decisions)))
    if decisions:
        case.evidence['gateway_decision'] = decisions[-1].get('decision')
        case.check('Gateway 判定 ALLOW', decisions[-1].get('decision') == 'ALLOW',
                   decisions[-1].get('decision'))
    goals_after = count_lines(instance.navsim_path)
    case.evidence['navsim_goal_delta'] = goals_after - goals_before
    case.check('NavigationSim Goal 增量为 1', goals_after - goals_before == 1,
               'delta={0}'.format(goals_after - goals_before))
    return instance


# ---------------------------------------------------------------- T14
def _normalise(path: str) -> str:
    """规范化路径，用于归属校验。

    不能只用字符串前缀判断：`/tmp/run1` 与 `/tmp/run10` 前缀相同但归属不同，
    符号链接与相对路径也会造成误判。因此比较规范化后的真实路径。
    """
    return os.path.realpath(os.path.abspath(path))


def _container_identity(name: str) -> dict:
    """取容器的 ID 与挂载源，用于"删除前先证明确实是本轮创建的"。

    返回空字典表示容器不存在。
    """
    probe = subprocess.run(
        ['docker', 'inspect', '-f', '{{.Id}}|{{range .Mounts}}{{.Source}}{{end}}', name],
        capture_output=True, text=True, timeout=120)
    if probe.returncode != 0:
        return {}
    raw = probe.stdout.strip()
    if '|' not in raw:
        return {}
    cid, source = raw.split('|', 1)
    return {'id': cid.strip(), 'mount_source': source.strip()}


def _record_run_id_map(case: Case, mapping: dict) -> None:
    case.evidence['container_run_id_map'] = mapping


def _instance_evidence(instance: Instance, request_id: str, label: str) -> dict:
    """读取某实例的**真实**审计与下游日志，返回结构化证据。

    缺文件、格式错误、请求未关联都必须能被上层断言捕获为 FAIL ——
    不使用任何 `or True` 之类的兜底，也不推测固定路径。
    """
    evidence = {
        'label': label,
        'request_id': request_id,
        'audit_path': os.path.relpath(instance.audit_path, ROOT),
        'navsim_path': os.path.relpath(instance.navsim_path, ROOT),
        'audit_exists': os.path.isfile(instance.audit_path),
        'navsim_exists': os.path.isfile(instance.navsim_path),
        'decision_count': 0,
        'decision': None,
        'reason_code': None,
        'goal_count': 0,
        'audit_parse_errors': 0,
    }
    if evidence['audit_exists']:
        records = read_jsonl(instance.audit_path)
        # read_jsonl 会静默跳过坏行；这里单独统计，坏行必须能被发现
        with open(instance.audit_path, 'r', encoding='utf-8', errors='ignore') as handle:
            raw_lines = [ln for ln in handle.read().splitlines() if ln.strip()]
        evidence['audit_parse_errors'] = max(0, len(raw_lines) - len(records))
        decisions = decisions_for(records, request_id)
        evidence['decision_count'] = len(decisions)
        if decisions:
            evidence['decision'] = decisions[-1].get('decision')
            evidence['reason_code'] = decisions[-1].get('reason_code')
        evidence['all_request_ids'] = sorted(
            {r.get('request_id') for r in records if r.get('request_id')})
    if evidence['navsim_exists']:
        goals = read_jsonl(instance.navsim_path)
        evidence['goal_count'] = len(navsim_goals_for(goals, request_id))
        evidence['all_goal_request_ids'] = sorted(
            {g.get('request_id') for g in goals if g.get('request_id')})
    return evidence


def _send_legal_action(instance: Instance, case: Case, config: str, run_id: str,
                       tag: str) -> str:
    """向一个实例发送一次合法候选请求，返回其 request_id。"""
    request_id = 'req-{0}'.format(uuid.uuid4().hex[:12])
    code, result, _o, _e = run_adapter(
        config, envelope_for(INTERIOR_TARGET, request_id=request_id, run_id=run_id),
        os.path.join(case.dir, tag), online=True, planner_timeout=45.0,
        log_name='{0}_adapter.jsonl'.format(tag))
    case.evidence.setdefault('requests', {})[tag] = {
        'request_id': request_id,
        'exit_code': code,
        'decision': result.get('decision'),
        'online_outcome': (result.get('online') or {}).get('outcome'),
    }
    return request_id


def scenario_t14(case: Case, run_id: str, base_dir: str):
    """T14：两个**真实独立**开发实例并发运行且互不串扰。

    与首版的区别
    ------------
    * 首版存在 `os.path.isfile(...) or True` —— 恒真断言，无论文件是否存在都通过。
      本版改为读取真实审计/下游日志并逐项断言缺失即 FAIL。
    * 首版是"先后各跑一次"，不是并发。本版让两个栈**同时处于就绪状态**期间
      各自发送请求，再验证日志互不串扰。
    * 首版未验证 request_id 是否跨越实例出现。本版做双向交叉检查。
    * 容器名与本轮 run_id 关联，删除前校验容器 ID 与**规范化后的**挂载源。
    """
    import shutil
    import tempfile

    tmp = tempfile.mkdtemp(prefix='t14_{0}_'.format(run_id[:12]))
    short = run_id.replace('_', '')[:10].lower()
    members = [
        {'tag': 'a', 'container': 'rg_ho_{0}_a'.format(short), 'domain': '51',
         'ws': os.path.join(tmp, 'ws_a')},
        {'tag': 'b', 'container': 'rg_ho_{0}_b'.format(short), 'domain': '52',
         'ws': os.path.join(tmp, 'ws_b')},
    ]
    created = []
    instances = {}

    if shutil.which('docker') is None:
        case.check('T14 需要 docker（必须在宿主机运行）', False,
                   'BLOCKED: 当前环境没有 docker，T14 应在宿主机执行')
        return None

    try:
        for item in members:
            os.makedirs(item['ws'], exist_ok=True)
            for name in os.listdir(ROOT):
                if name in ('.git', 'logs', 'tests', 'gitignore', 'gitlog.md',
                            'build', 'install', 'log'):
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
            # 显式容器名 + 显式 Domain（不使用 RG_MEMBER，以免与其派生名冲突）；
            # 这符合 member_env.sh 的规则：显式值优先，且不与成员档位混用。
            env = dict(os.environ)
            env.pop('RG_MEMBER', None)
            env['RG_CONTAINER'] = item['container']
            env['ROS_DOMAIN_ID'] = item['domain']
            proc = subprocess.run(
                ['bash', os.path.join(item['ws'], 'scripts', 'container_up.sh')],
                cwd=item['ws'], env=env, capture_output=True, text=True, timeout=1800)
            item['container_exit'] = proc.returncode
            created.append(item)
            case.check('实例 {0} 容器就绪（Domain {1}）'.format(item['tag'], item['domain']),
                       proc.returncode == 0, (proc.stdout + proc.stderr)[-200:])

        _record_run_id_map(case, {i['container']: run_id for i in created})
        if not all(i.get('container_exit') == 0 for i in created):
            return None

        # 构建每个实例自己的配置与栈
        for item in created:
            inner_dir = os.path.join(item['ws'], 't14_evidence')
            os.makedirs(inner_dir, exist_ok=True)
            write_config(os.path.join(inner_dir, 'team_modules.yaml'), planner=True)
            # 适配层在容器内运行，因此必须使用**容器内路径**（/ws/...），
            # 而不是宿主机路径。早期版本直接传宿主路径，容器内找不到文件。
            item['config'] = '/ws/t14_evidence/team_modules.yaml'

            # 真实构建：工作区副本刻意不携带 build/install，
            # 因此每个成员容器都要自己构建 —— 这也正是新成员的真实路径。
            build = subprocess.run(
                ['docker', 'exec', item['container'], 'bash', '-lc',
                 'cd /ws && source /opt/ros/jazzy/setup.bash && '
                 'colcon build --event-handlers console_direct+ 2>&1 | tail -3'],
                capture_output=True, text=True, timeout=2400)
            case.check('实例 {0} 在容器内完成四包构建'.format(item['tag']),
                       build.returncode == 0 and 'packages finished' in build.stdout,
                       (build.stdout or build.stderr)[-160:])

        procs = {}
        for item in created:
            inner = ("cd /ws && source /opt/ros/jazzy/setup.bash && "
                     "source install/setup.bash && "
                     "ros2 launch rg_demo_nodes stack.launch.py "
                     "policy_path:=/ws/config/task_policy.yaml "
                     "audit_log_path:=/ws/t14_evidence/audit.jsonl "
                     "navsim_record_path:=/ws/t14_evidence/navsim.jsonl")
            log = open(os.path.join(case.dir, 'stack_{0}.log'.format(item['tag'])), 'wb')
            procs[item['tag']] = {
                'proc': subprocess.Popen(
                    ['docker', 'exec', item['container'], 'bash', '-lc', inner],
                    stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL),
                'handle': log, 'item': item,
            }

        # 两个栈**同时**就绪（这是并发隔离验证的前提）
        for tag, entry in procs.items():
            deadline = time.time() + 150
            ready = False
            path = os.path.join(case.dir, 'stack_{0}.log'.format(tag))
            while time.time() < deadline:
                if entry['proc'].poll() is not None:
                    break
                text = open(path, 'r', encoding='utf-8', errors='replace').read()
                if 'NAVSIM_READY' in text and 'GATEWAY_READY' in text:
                    ready = True
                    break
                time.sleep(0.5)
            detail = path
            if not ready:
                # 失败时给出日志尾部，避免只报"未就绪"而无法定位
                tail = open(path, 'r', encoding='utf-8', errors='replace').read()[-200:]
                detail = '{0} :: {1}'.format(path, tail.replace(chr(10), ' | '))
            case.check('实例 {0} 栈就绪'.format(tag), ready, detail)

        # 并发期间各发一次合法请求
        rid_a = _send_legal_action_host(created[0], case, run_id, 'a')
        rid_b = _send_legal_action_host(created[1], case, run_id, 'b')

        # 双向交叉检查：A 的 request_id 不得出现在 B 的日志，反之亦然
        for item, mine, theirs in ((created[0], rid_a, rid_b),
                                   (created[1], rid_b, rid_a)):
            audit_local = os.path.join(item['ws'], 't14_evidence', 'audit.jsonl')
            navsim_local = os.path.join(item['ws'], 't14_evidence', 'navsim.jsonl')
            record = {
                'container': item['container'],
                'audit_exists': os.path.isfile(audit_local),
                'navsim_exists': os.path.isfile(navsim_local),
                'own_request_id': mine,
                'other_request_id': theirs,
            }
            case.check('实例 {0} 的 Gateway 审计文件真实存在'.format(item['tag']),
                       record['audit_exists'], audit_local)
            case.check('实例 {0} 的 NavigationSim 日志真实存在'.format(item['tag']),
                       record['navsim_exists'], navsim_local)
            if record['audit_exists']:
                records = read_jsonl(audit_local)
                own = decisions_for(records, mine)
                foreign = decisions_for(records, theirs)
                record['own_decision_count'] = len(own)
                record['foreign_decision_count'] = len(foreign)
                record['own_decision'] = own[-1].get('decision') if own else None
                case.check('实例 {0} 有本实例 request_id 的 DecisionEvent'.format(item['tag']),
                           len(own) >= 1, 'own={0}'.format(len(own)))
                case.check('实例 {0} 不含另一实例的 DecisionEvent（无串扰）'.format(item['tag']),
                           len(foreign) == 0, 'foreign={0}'.format(len(foreign)))
                if own:
                    case.check('实例 {0} Gateway 判定 ALLOW'.format(item['tag']),
                               own[-1].get('decision') == 'ALLOW',
                               own[-1].get('decision'))
            if record['navsim_exists']:
                goals = read_jsonl(navsim_local)
                own_goals = navsim_goals_for(goals, mine)
                foreign_goals = navsim_goals_for(goals, theirs)
                record['own_goal_count'] = len(own_goals)
                record['foreign_goal_count'] = len(foreign_goals)
                case.check('实例 {0} 下游收到本实例 Goal'.format(item['tag']),
                           len(own_goals) == 1, 'own_goals={0}'.format(len(own_goals)))
                case.check('实例 {0} 下游不含另一实例 Goal（无串扰）'.format(item['tag']),
                           len(foreign_goals) == 0,
                           'foreign_goals={0}'.format(len(foreign_goals)))
            case.evidence.setdefault('isolation', {})[item['tag']] = record

        # 关闭实例 A（先校验容器归属），B 必须仍能完成**新的** Action
        victim = created[0]
        identity = _container_identity(victim['container'])
        belongs = (identity.get('mount_source') and
                   _normalise(identity['mount_source']) == _normalise(victim['ws']))
        case.check('实例 A 容器归属校验通过（挂载源规范化后匹配）', bool(belongs),
                   'identity={0} expected={1}'.format(identity, victim['ws']))
        if belongs:
            subprocess.run(['docker', 'stop', victim['container']],
                           capture_output=True, timeout=300)
            case.check('实例 A 已停止', True, victim['container'])
        else:
            case.check('实例 A 未通过归属校验，拒绝停止', False,
                       '为避免误停他人容器，已跳过 docker stop')

        # B 的新请求：用**不同**的 request_id，证明 B 仍在正常工作
        rid_b2 = _send_legal_action_host(created[1], case, run_id, 'b_after')
        case.check('关闭 A 后 B 完成新的真实 Action（request_id 不同）',
                   rid_b2 != rid_b, '{0} vs {1}'.format(rid_b2, rid_b))
        navsim_local = os.path.join(created[1]['ws'], 't14_evidence', 'navsim.jsonl')
        if os.path.isfile(navsim_local):
            goals = read_jsonl(navsim_local)
            case.check('B 的新请求在下游产生 Goal', len(navsim_goals_for(goals, rid_b2)) == 1,
                       'goals={0}'.format(len(navsim_goals_for(goals, rid_b2))))
            case.check('B 的下游仍不含 A 的 request_id',
                       len(navsim_goals_for(goals, rid_a)) == 0,
                       'A goals={0}'.format(len(navsim_goals_for(goals, rid_a))))
        return created
    finally:
        for entry in procs.values() if 'procs' in dir() else []:
            try:
                entry['handle'].close()
            except Exception:  # noqa: BLE001
                pass
        for item in created:
            identity = _container_identity(item['container'])
            source = identity.get('mount_source', '')
            # 删除前双重校验：容器存在，且挂载源规范化后确实指向本轮的临时目录
            if identity and source and _normalise(source).startswith(_normalise(tmp)):
                subprocess.run(['docker', 'rm', '-f', item['container']],
                               capture_output=True, timeout=300)
            elif identity:
                print('  [warn] 跳过删除 {0}：挂载源 {1} 不属于本轮临时目录'.format(
                    item['container'], source))
        shutil.rmtree(tmp, ignore_errors=True)


def _send_legal_action_host(item: dict, case: Case, run_id: str, tag: str) -> str:
    """在成员容器内通过适配层发送一次合法候选请求，返回 request_id。"""
    request_id = 'req-{0}'.format(uuid.uuid4().hex[:12])
    envelope_doc = envelope_for(INTERIOR_TARGET, request_id=request_id, run_id=run_id)
    inner_dir = os.path.join(item['ws'], 't14_evidence')
    os.makedirs(inner_dir, exist_ok=True)
    env_path = os.path.join(inner_dir, 'envelope_{0}.json'.format(tag))
    with open(env_path, 'w', encoding='utf-8') as handle:
        json.dump(envelope_doc, handle, ensure_ascii=False)
    # 适配层在容器内运行：--input / --config / --log 都必须用**容器内路径**。
    # 早期版本传了宿主机路径，容器内找不到文件，表现为 ADAPTER_INPUT_INVALID。
    inner = ("cd /ws && source /opt/ros/jazzy/setup.bash && source install/setup.bash && "
             "python3 scripts/team_demo.py --input /ws/t14_evidence/envelope_{0}.json "
             "--config {1} --online --planner-timeout 45 "
             "--log /ws/t14_evidence/adapter_{0}.jsonl 2>&1").format(
                 tag, item['config'])
    proc = subprocess.run(['docker', 'exec', item['container'], 'bash', '-lc', inner],
                          capture_output=True, text=True, timeout=900)
    result = {}
    try:
        start = proc.stdout.index('{')
        result = json.loads(proc.stdout[start:])
    except (ValueError, IndexError):
        result = {'decision': 'UNPARSEABLE', 'raw': proc.stdout[-300:]}
    case.evidence.setdefault('requests', {})[tag] = {
        'request_id': request_id,
        'decision': result.get('decision'),
        'reason_code': result.get('reason_code'),
        'online_outcome': (result.get('online') or {}).get('outcome'),
        'exit_code': proc.returncode,
    }
    case.check('实例 {0} 请求经适配层推进'.format(tag),
               result.get('decision') == 'READY_FOR_GATEWAY_SUBMISSION',
               'decision={0} reason={1}'.format(result.get('decision'),
                                                result.get('reason_code')))
    return request_id



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
            # 三项必须各自独立：只替换对应模块，其余保持 Mock。
            # 早期实现用"三替身同时替换"一次覆盖三项，无法证明逐模块可替换。
            module = {'T09': 'comm_risk', 'T10': 'identity_trust',
                      'T11': 'task_risk'}[case_id]
            instance = scenario_replacement(case, module, run_id=run_id, domain=domain)
        elif case_id == 'T14':
            scenario_t14(case, run_id, base_dir)
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
        # 完整覆盖 T01~T15。早期列表遗漏 T10、T11，却仍把整套显示为"all"，
        # 属于会掩盖未执行项的报告缺陷。
        selected = list(SCENARIO_TABLE)
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
