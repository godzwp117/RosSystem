#!/usr/bin/env python3
"""sros2_check.py -- M2 安全链路对照实验（S1–S6），在容器内运行。

实验设计的关键（为什么结论可信）
--------------------------------
1. **普通模式与安全模式使用不同的 DDS domain**：普通 = 42（容器默认），安全 = 43。
   两者不共用进程、不共用环境变量、也不共用 ros2 daemon 缓存，避免互相污染。
2. **每个角色一个独立 Enclave**，通过 `ROS_SECURITY_ENCLAVE_OVERRIDE` 逐进程指定，
   不使用统一的全局 Enclave。
3. **越权实验带正向对照**：同一个测试客户端、同一份代码路径、同一时间窗口内，
   分别以 /gateway（被授权）与 /planner、/unauthorized（未授权）身份访问
   `/rg/nav_execute`。只有正向对照成功、越权访问失败，"拒绝来自 DDS 权限"这一结论
   才成立 —— 单看客户端超时不足以证明权限规则生效。
4. 断言以**文件证据**为主（NavigationSim 的 JSONL 记录行数、网关审计 JSONL），
   不依赖在安全模式下运行 ros2 CLI（那样需要额外的 CLI 身份，会引入额外变量）。

必须在容器内执行：
    docker exec rg_jazzy bash -lc 'cd /ws && source /opt/ros/jazzy/setup.bash && \\
        source install/setup.bash && python3 tests/integration/sros2_check.py'
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
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EVIDENCE_ROOT = os.path.join(ROOT, 'tests', 'evidence')
POLICY = os.path.join(ROOT, 'config', 'task_policy.yaml')
KEYSTORE = os.path.join(ROOT, 'security', 'keystore')
ROGUE_CLIENT = os.path.join(ROOT, 'tests', 'integration', 'rogue_action_client.py')

NORMAL_DOMAIN = os.environ.get('RG_NORMAL_DOMAIN', '42')
SECURE_DOMAIN = os.environ.get('RG_SECURE_DOMAIN', '43')
ACTION_GUARDED = '/rg/guarded_navigate'
ACTION_EXECUTE = '/rg/nav_execute'


def now_iso():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def utc_stamp():
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def read_text(path):
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as handle:
            return handle.read()
    except OSError:
        return ''


def count_lines(path):
    return sum(1 for line in read_text(path).splitlines() if line.strip())


def read_jsonl(path):
    out = []
    for line in read_text(path).splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


class RosNode:
    """容器内单个 ROS 2 进程，可指定 domain / enclave / 安全开关。"""

    def __init__(self, label, package, executable, params, log_path,
                 domain, enclave=None, secure=False, extra_env=None):
        self.label = label
        self.log_path = log_path
        self.exit_code = None
        self.argv = ['ros2', 'run', package, executable, '--ros-args']
        for key, value in params.items():
            self.argv += ['-p', '{0}:={1}'.format(key, value)]
        env = dict(os.environ)
        env['ROS_DOMAIN_ID'] = str(domain)
        env.pop('ROS_SECURITY_ENABLE', None)
        env.pop('ROS_SECURITY_STRATEGY', None)
        env.pop('ROS_SECURITY_KEYSTORE', None)
        env.pop('ROS_SECURITY_ENCLAVE_OVERRIDE', None)
        if secure:
            env['ROS_SECURITY_ENABLE'] = 'true'
            env['ROS_SECURITY_STRATEGY'] = 'Enforce'
            env['ROS_SECURITY_KEYSTORE'] = KEYSTORE
            if enclave:
                env['ROS_SECURITY_ENCLAVE_OVERRIDE'] = enclave
        env.update(extra_env or {})
        env['PYTHONUNBUFFERED'] = '1'
        self.env = env
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        self._handle = open(log_path, 'wb')
        self._t0 = time.time()
        self.proc = subprocess.Popen(self.argv, stdout=self._handle,
                                     stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                     start_new_session=True, cwd=ROOT, env=env)

    def wait_for_log(self, marker, timeout_sec):
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            if marker in read_text(self.log_path):
                return True
            if self.proc.poll() is not None:
                return marker in read_text(self.log_path)
            time.sleep(0.3)
        return marker in read_text(self.log_path)

    def alive(self):
        return self.proc.poll() is None

    def stop(self, grace=12.0):
        if self.proc.poll() is None:
            try:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGINT)
            except OSError:
                self.proc.terminate()
            try:
                self.proc.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
                except OSError:
                    self.proc.kill()
        try:
            self.exit_code = self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.exit_code = None
        self._handle.close()
        return self.exit_code


def run_rogue(case_dir, action, node_name, enclave, domain, secure,
              request_id, x, y, keystore_override=None, server_wait=8.0, label='rogue'):
    """以指定安全身份运行越权测试客户端。"""
    log_path = os.path.join(case_dir, '{0}.log'.format(label))
    env = dict(os.environ)
    env['ROS_DOMAIN_ID'] = str(domain)
    env.pop('ROS_SECURITY_ENABLE', None)
    env.pop('ROS_SECURITY_STRATEGY', None)
    env.pop('ROS_SECURITY_KEYSTORE', None)
    env.pop('ROS_SECURITY_ENCLAVE_OVERRIDE', None)
    if secure:
        env['ROS_SECURITY_ENABLE'] = 'true'
        env['ROS_SECURITY_STRATEGY'] = 'Enforce'
        env['ROS_SECURITY_KEYSTORE'] = keystore_override or KEYSTORE
        if enclave:
            env['ROS_SECURITY_ENCLAVE_OVERRIDE'] = enclave
    env['PYTHONUNBUFFERED'] = '1'
    argv = ['python3', ROGUE_CLIENT, '--action', action, '--node-name', node_name,
            '--request-id', request_id, '--x', str(x), '--y', str(y),
            '--server-wait', str(server_wait)]
    t0 = time.time()
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=180,
                          cwd=ROOT, env=env)
    duration = time.time() - t0
    output = (proc.stdout or '') + (proc.stderr or '')
    with open(log_path, 'w', encoding='utf-8') as handle:
        handle.write(output)
    parsed = None
    for line in output.splitlines():
        if line.strip().startswith('ROGUE_RESULT '):
            try:
                parsed = json.loads(line.strip()[len('ROGUE_RESULT '):])
            except json.JSONDecodeError:
                pass
    return {'exit_code': proc.returncode, 'output': output, 'result': parsed,
            'argv': argv, 'duration_sec': round(duration, 3), 'log_path': log_path}


class Case:
    def __init__(self, case_id, name, expected, secure, enclave=None, resource=None,
                 domain=None):
        self.domain = domain
        self.case_id = case_id
        self.name = name
        self.expected = expected
        self.secure = secure
        self.enclave = enclave
        self.resource = resource
        self.checks = []
        self.commands = []
        self.dir = None
        self.exit_code = None
        self.goals = 0
        self.reason = None
        self.rejection_layer = 'not_applicable'
        self.notes = []

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
            for base, _d, files in os.walk(self.dir):
                for name in sorted(files):
                    evidence.append(os.path.relpath(os.path.join(base, name), ROOT))
        return {
            'scenario': self.case_id,
            'scenario_id': self.case_id,
            'description': self.name,
            'scenario_name': self.name,
            'expected_result': self.expected,
            'actual_result': '; '.join('{0}={1}'.format(c['check'], c['result']) for c in self.checks)[:800],
            'result': 'PASS' if self.passed else 'FAIL',
            'status': 'PASS' if self.passed else 'FAIL',
            'evidence_dir': os.path.relpath(self.dir, ROOT) if self.dir else '',
            'command': self.commands[0]['argv'] if self.commands else [],
            'commands': self.commands,
            'exit_code': self.exit_code,
            'duration_ms': int(sum(c.get('duration_sec') or 0 for c in self.commands) * 1000),
            'log_path': evidence[0] if evidence else None,
            'evidence_files': evidence,
            'reason_code': self.reason,
            # 该场景实际执行的 ROS_DOMAIN_ID（普通 42 / Enforce 43），
            # 与容器默认 domain 区分记录。
            'ros_domain_id': self.domain,
            'security_mode': 'enforce' if self.secure else 'disabled',
            'source_role': self.enclave.strip('/') if self.enclave else None,
            'source_enclave': self.enclave,
            'requested_resource': self.resource,
            'downstream_goal_count': self.goals,
            'rejection_layer': self.rejection_layer,
            'checks': self.checks,
            'notes': self.notes,
        }


def start_stack(case, domain, secure, enclaves, gateway_params=None, navsim_params=None,
                with_operator=True):
    """启动 navsim + gateway（+ operator），返回 (nodes, journal, audit, gateway_log)。"""
    case.dir = os.path.join(EVIDENCE_ROOT, RUN_ID, case.case_id)
    shutil.rmtree(case.dir, ignore_errors=True)
    os.makedirs(case.dir, exist_ok=True)
    journal = os.path.join(case.dir, 'navsim_goals.jsonl')
    audit = os.path.join(case.dir, 'audit.jsonl')
    gateway_log = os.path.join(case.dir, 'gateway.log')
    nodes = []

    navsim_params = {'record_path': journal, **(navsim_params or {})}
    gw_params = {'policy_path': POLICY, 'audit_log_path': audit, **(gateway_params or {})}

    if with_operator:
        nodes.append(RosNode('operator', 'rg_demo_nodes', 'operator_node',
                             {'task_id': 'patrol_a_001', 'publish_period_sec': 2.0},
                             os.path.join(case.dir, 'operator.log'), domain,
                             enclave=enclaves.get('operator'), secure=secure))
    navsim = RosNode('navsim', 'rg_demo_nodes', 'navigation_sim', navsim_params,
                     os.path.join(case.dir, 'navsim.log'), domain,
                     enclave=enclaves.get('navsim'), secure=secure)
    gateway = RosNode('gateway', 'rg_gateway', 'security_gateway', gw_params,
                      gateway_log, domain, enclave=enclaves.get('gateway'), secure=secure)
    nodes += [navsim, gateway]

    navsim_ready = navsim.wait_for_log('NAVSIM_READY', 40.0)
    gateway_ready = gateway.wait_for_log('GATEWAY_READY', 40.0)
    case.check('NavigationSim 就绪（安全模式={0}, domain={1}）'.format(secure, domain),
               navsim_ready, 'NAVSIM_READY' if navsim_ready else read_text(navsim.log_path)[-300:])
    case.check('security_gateway 就绪（安全模式={0}, enclave={1}）'.format(
        secure, enclaves.get('gateway')), gateway_ready,
        'GATEWAY_READY' if gateway_ready else read_text(gateway_log)[-300:])
    if secure:
        case.check('网关日志确认策略已加载且安全模式生效',
                   'GATEWAY_READY' in read_text(gateway_log)
                   and '"policy_loaded": true' in read_text(gateway_log),
                   'policy_loaded=true')
    return nodes, journal, audit, gateway_log


def run_planner(case, enclave, domain, secure, request_id, x, y, expect_success):
    log_path = os.path.join(case.dir, 'planner.log')
    argv = ['ros2', 'run', 'rg_demo_nodes', 'planner_node', '--ros-args',
            '-p', 'request_id:={0}'.format(request_id),
            '-p', 'task_id:=patrol_a_001', '-p', 'frame_id:=map',
            '-p', 'target_x:={0}'.format(x), '-p', 'target_y:={0}'.format(y),
            '-p', 'expect_success:={0}'.format(expect_success)]
    env = dict(os.environ)
    env['ROS_DOMAIN_ID'] = str(domain)
    env.pop('ROS_SECURITY_ENABLE', None)
    env.pop('ROS_SECURITY_STRATEGY', None)
    env.pop('ROS_SECURITY_KEYSTORE', None)
    env.pop('ROS_SECURITY_ENCLAVE_OVERRIDE', None)
    if secure:
        env['ROS_SECURITY_ENABLE'] = 'true'
        env['ROS_SECURITY_STRATEGY'] = 'Enforce'
        env['ROS_SECURITY_KEYSTORE'] = KEYSTORE
        env['ROS_SECURITY_ENCLAVE_OVERRIDE'] = enclave
    env['PYTHONUNBUFFERED'] = '1'
    t0 = time.time()
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=240, cwd=ROOT, env=env)
    duration = time.time() - t0
    output = (proc.stdout or '') + (proc.stderr or '')
    with open(log_path, 'w', encoding='utf-8') as handle:
        handle.write(output)
    parsed = None
    for line in output.splitlines():
        if line.strip().startswith('PLANNER_RESULT '):
            try:
                parsed = json.loads(line.strip()[len('PLANNER_RESULT '):])
            except json.JSONDecodeError:
                pass
    case.commands.append({'step': 'planner', 'argv': argv, 'exit_code': proc.returncode,
                          'duration_sec': round(duration, 3)})
    case.exit_code = proc.returncode
    return {'exit_code': proc.returncode, 'result': parsed, 'output': output}


def stop_all(nodes):
    for node in reversed(nodes):
        node.stop()
    time.sleep(1.5)
    # 兜底：确认容器内没有本项目残留节点（非僵尸）
    out = subprocess.run(['bash', '-lc',
                          "ps -eo stat=,cmd --no-headers | grep -vE '^[[:space:]]*Z' "
                          "| grep -E 'rg_gateway/lib|rg_demo_nodes/lib' | grep -v grep || true"],
                         capture_output=True, text=True).stdout
    return [l for l in out.splitlines() if l.strip()]


# ---------------------------------------------------------------------------
# 场景
# ---------------------------------------------------------------------------
def scenario_s1_result(case, planner):
    result = planner['result'] or {}
    case.check('planner 拿到 EXECUTED 结果',
               result.get('status_code') == 'EXECUTED' and result.get('success') is True,
               '{0}/{1}'.format(result.get('status_code'), result.get('success')))


def scenario_s2(case, ctx):
    """S2 Enforce 模式合法 A 区请求（复用已启动的安全栈）。"""
    before = count_lines(ctx['journal'])
    planner = run_planner(case, '/planner', SECURE_DOMAIN, True, 's2-a-zone', 1.5, 1.5, 1)
    after = count_lines(ctx['journal'])
    case.goals = after - before
    result = planner['result'] or {}
    audit = read_jsonl(ctx['audit'])
    decision = [r for r in audit if r.get('event_type') == 'DecisionEvent']
    case.reason = decision[-1].get('reason_code') if decision else None
    case.check('Enforce 下 Planner 成功拿到执行结果（EXECUTED）',
               result.get('status_code') == 'EXECUTED' and result.get('success') is True,
               '{0}/{1}'.format(result.get('status_code'), result.get('success')))
    case.check('Enforce 下下游新增 1 条 Goal', case.goals == 1,
               'journal 增量={0}'.format(case.goals))
    case.check('Enforce 下判定为 ALLOW_IN_POLICY', case.reason == 'ALLOW_IN_POLICY', case.reason)
    case.check('授权链完整（身份合法 + 基础通信许可 + 业务放行）', case.passed,
               '三项均满足')


def scenario_s5(case, ctx):
    """S5 Enforce 模式 B 区越界请求：身份合法但业务拒绝。"""
    before = count_lines(ctx['journal'])
    planner = run_planner(case, '/planner', SECURE_DOMAIN, True, 's5-b-zone', 9.0, 9.0, 0)
    after = count_lines(ctx['journal'])
    case.goals = after - before
    result = planner['result'] or {}
    audit = read_jsonl(ctx['audit'])
    decision = [r for r in audit if r.get('event_type') == 'DecisionEvent']
    case.reason = decision[-1].get('reason_code') if decision else None
    case.rejection_layer = 'business_task_policy'
    case.check('身份与基础通信许可合法（请求确实到达网关并有判定记录）',
               case.reason is not None, case.reason)
    case.check('业务层拒绝：OUT_OF_REGION', case.reason == 'OUT_OF_REGION', case.reason)
    case.check('planner 得到 success=false', result.get('success') is False,
               '{0}/{1}'.format(result.get('status_code'), result.get('success')))
    case.check('下游未新增 Goal（越权未执行）', case.goals == 0,
               'journal 增量={0}'.format(case.goals))
    case.check('拒绝来自 TaskPolicy 而非 DDS（与 S3/S4 区分）',
               case.reason == 'OUT_OF_REGION' and case.goals == 0, 'business_task_policy')


def _direct_access_case(case, ctx, enclave, node_name, request_id, expect_success, label):
    before = count_lines(ctx['journal'])
    rogue = run_rogue(case.dir, ACTION_EXECUTE, node_name, enclave, SECURE_DOMAIN, True,
                      request_id, 1.5, 1.5, label=label)
    after = count_lines(ctx['journal'])
    case.goals = after - before
    case.commands.append({'step': label, 'argv': rogue['argv'],
                          'exit_code': rogue['exit_code'],
                          'duration_sec': rogue['duration_sec']})
    case.exit_code = rogue['exit_code']
    result = rogue['result'] or {}
    outcome = result.get('outcome')
    case.reason = result.get('status_code') or outcome
    security_hint = any(k in rogue['output'].lower() for k in
                        ('security', 'permission', 'accesscontrol', 'access control',
                         'unauthorized', 'not authorized', 'denied'))
    return rogue, outcome, security_hint


def scenario_s3(case, ctx):
    """S3 Enforce 模式：Planner 身份直接访问执行接口应被拒绝。"""
    rogue, outcome, hint = _direct_access_case(
        case, ctx, '/planner', 'planner_node', 's3-planner-direct', False, 'rogue_planner')
    case.rejection_layer = 'dds_security'
    dds_denied = ('not found in allow rule' in rogue['output']
                  or 'SECURITY Error' in rogue['output'])
    case.check('Planner 身份直连 /rg/nav_execute 未能完成执行',
               outcome in ('ACTION_CLIENT_CREATION_DENIED', 'NO_ACTION_SERVER',
                           'SEND_GOAL_TIMEOUT', 'RESULT_TIMEOUT', 'EXCEPTION'),
               'outcome={0} exit={1}'.format(outcome, rogue['exit_code']))
    case.check('DDS 访问控制层给出明确拒绝证据（不是单纯客户端超时）', dds_denied,
               [l.strip()[-150:] for l in rogue['output'].splitlines()
                if 'not found in allow rule' in l or 'SECURITY Error' in l][:2] or '未见 DDS 拒绝证据')
    case.check('NavigationSim 未收到该直连 Goal', case.goals == 0,
               'journal 增量={0}'.format(case.goals))
    case.check('正向对照（S3C，/gateway 身份）在同一窗口内成功 -> 排除"服务端没起来/客户端有 bug"',
               ctx.get('control_ok') is True,
               'control_ok={0}'.format(ctx.get('control_ok')))
    case.notes.append('客户端输出中{0}安全相关关键字；结论主要依据'
                      '"同一客户端、同一时间窗口的正向对照成功"。'.format(
                          '命中' if hint else '未命中'))
    case.notes.append('仅凭客户端超时不能证明 DDS 权限生效；本场景的可信度来自 S3C 正向对照。')


def scenario_s3c(case, ctx):
    """S3C 正向对照：/gateway 身份访问 /rg/nav_execute 应当成功。"""
    rogue, outcome, hint = _direct_access_case(
        case, ctx, '/gateway', 'security_gateway', 's3c-gateway-direct', True, 'rogue_gateway')
    case.rejection_layer = 'not_applicable'
    ok = outcome == 'RESULT' and (rogue['result'] or {}).get('success') is True
    ctx['control_ok'] = bool(ok)
    case.check('/gateway 身份直连 /rg/nav_execute 成功（正向对照）', ok,
               'outcome={0} status={1}'.format(outcome, (rogue['result'] or {}).get('status_code')))
    case.check('NavigationSim 收到 1 条直连 Goal', case.goals == 1,
               'journal 增量={0}'.format(case.goals))
    case.notes.append('该场景证明：同样的客户端代码与同样的目标 Action，'
                      '在被授权身份下可以成功 —— 因此 S3/S4 的失败只能归因于身份权限。')


def scenario_s4(case, ctx):
    """S4 无授权身份访问执行接口应被拒绝。"""
    rogue, outcome, hint = _direct_access_case(
        case, ctx, '/unauthorized', 'rogue_client', 's4-unauthorized', False, 'rogue_unauthorized')
    case.rejection_layer = 'dds_security'
    dds_denied = ('not found in allow rule' in rogue['output']
                  or 'SECURITY Error' in rogue['output'])
    case.check('无授权身份无法完成执行调用',
               outcome in ('ACTION_CLIENT_CREATION_DENIED', 'NO_ACTION_SERVER',
                           'SEND_GOAL_TIMEOUT', 'RESULT_TIMEOUT', 'EXCEPTION', 'INIT_FAILED'),
               'outcome={0} exit={1}'.format(outcome, rogue['exit_code']))
    case.check('DDS 访问控制层给出明确拒绝证据', dds_denied,
               [l.strip()[-150:] for l in rogue['output'].splitlines()
                if 'not found in allow rule' in l or 'SECURITY Error' in l][:2] or '未见 DDS 拒绝证据')
    case.check('NavigationSim 未收到该未授权 Goal', case.goals == 0,
               'journal 增量={0}'.format(case.goals))
    case.check('保留可归因的拒绝证据（客户端日志 + 网关/执行端无对应记录）',
               bool(read_text(os.path.join(case.dir, 'rogue_unauthorized.log'))),
               'rogue_unauthorized.log')
    case.notes.append('未授权身份的有效证书来自同一 CA，权限文件中不含任何业务资源，'
                      '因此拒绝发生在 DDS 访问控制层而非发现层。')


def scenario_s6(case, ctx):
    """S6 安全配置失效：不得静默回退为无认证通信。"""
    before = count_lines(ctx['journal'])
    bad_keystore = os.path.join(case.dir, 'nonexistent-keystore')
    rogue = run_rogue(case.dir, ACTION_EXECUTE, 'rogue_client', '/unauthorized',
                      SECURE_DOMAIN, True, 's6-bad-keystore', 1.5, 1.5,
                      keystore_override=bad_keystore, label='rogue_bad_keystore')
    after = count_lines(ctx['journal'])
    case.goals = after - before
    case.commands.append({'step': 'rogue_bad_keystore', 'argv': rogue['argv'],
                          'exit_code': rogue['exit_code'],
                          'duration_sec': rogue['duration_sec']})
    case.exit_code = rogue['exit_code']
    result = rogue['result'] or {}
    outcome = result.get('outcome')
    text = rogue['output'].lower()
    security_error = any(k in text for k in
                         ('security', 'keystore', 'permission', 'no such file',
                          'accesscontrol', 'denied', 'unable to'))
    case.rejection_layer = 'dds_security'
    case.check('缺少凭证时无法完成执行调用',
               outcome in ('INIT_FAILED', 'ACTION_CLIENT_CREATION_DENIED', 'NO_ACTION_SERVER',
                           'SEND_GOAL_TIMEOUT', 'RESULT_TIMEOUT', 'EXCEPTION'),
               'outcome={0} exit={1}'.format(outcome, rogue['exit_code']))
    case.check('失败发生在安全初始化阶段（SECURITY ERROR），而非静默降级',
               'SECURITY ERROR' in rogue['output'] or 'does not exist' in rogue['output'],
               (result.get('detail') or '')[:200])
    case.check('未静默回退为无认证通信（下游未新增 Goal）', case.goals == 0,
               'journal 增量={0}'.format(case.goals))
    case.check('客户端暴露安全/凭证相关错误，而非"一切正常"', security_error,
               [l for l in rogue['output'].splitlines() if 'security' in l.lower()
                or 'keystore' in l.lower()][:2] or '未发现安全关键字（见日志）')
    case.notes.append('同一 domain(43) 上的安全栈全程可用（见 S2/S3C 成功），'
                      '因此"未新增 Goal"不能由环境不可用解释，只能由该参与者自身的安全配置失效解释。')


RUN_ID = None


def main(argv=None) -> int:
    global RUN_ID
    parser = argparse.ArgumentParser(description='M2 SROS 2 对照实验 S1-S6')
    parser.add_argument('--run-id', default=None)
    parser.add_argument('--only', default=None, help='逗号分隔，如 S3,S3C')
    args = parser.parse_args(argv)
    RUN_ID = args.run_id or utc_stamp()
    run_dir = os.path.join(EVIDENCE_ROOT, RUN_ID)
    os.makedirs(run_dir, exist_ok=True)

    wanted = set((args.only or '').split(',')) if args.only else None
    results = []

    # ---------------- S1：普通模式（独立 domain 42）----------------
    if not wanted or 'S1' in wanted:
        case = Case('S1_normal_mode_a_zone', '普通模式合法 A 区请求（domain 42，未启用安全）',
                    'Gateway ALLOW，NavigationSim 收到 1 条 Goal', secure=False,
                    domain=int(NORMAL_DOMAIN))
        print('\n=== S1 普通模式合法 A 区请求 ===')
        nodes, journal, audit, gw_log = start_stack(case, NORMAL_DOMAIN, False,
                                                    {'navsim': None, 'gateway': None,
                                                     'operator': None})
        try:
            if case.passed:
                planner = run_planner(case, None, NORMAL_DOMAIN, False, 's1-a-zone', 1.5, 1.5, 1)
                scenario_s1_result(case, planner)
                goals = count_lines(journal)
                case.goals = goals
                decision = [r for r in read_jsonl(audit) if r.get('event_type') == 'DecisionEvent']
                case.reason = decision[0].get('reason_code') if decision else None
                case.check('Gateway 判定 ALLOW', bool(decision) and decision[0].get('decision') == 'ALLOW',
                           case.reason or '无判定记录')
                case.check('NavigationSim 收到 1 条 Goal', goals == 1,
                           'journal 行数={0}'.format(goals))
        finally:
            leftovers = stop_all(nodes)
            case.check('场景结束后容器内无残留节点', not leftovers,
                       '残留 {0}'.format(leftovers) if leftovers else '无残留')
        results.append(case)

    # ------------- S2/S5/S3/S3C/S4/S6：共享一个 Enforce 安全栈 -------------
    shared_ids = ['S2', 'S5', 'S3', 'S3C', 'S4', 'S6']
    if not wanted or (wanted & set(shared_ids)):
        ctx_case = Case('_stack', 'Enforce 共享安全栈（domain 43）', '栈就绪', secure=True,
                        domain=int(SECURE_DOMAIN))
        print('\n=== 启动 Enforce 安全栈（domain {0}）==='.format(SECURE_DOMAIN))
        nodes, journal, audit, gw_log = start_stack(
            ctx_case, SECURE_DOMAIN, True,
            {'operator': '/operator', 'navsim': '/navsim', 'gateway': '/gateway'})
        ctx = {'journal': journal, 'audit': audit, 'gateway_log': gw_log,
               'control_ok': None, 'stack_ok': ctx_case.passed}
        try:
            if ctx_case.passed:
                for cid, fn, name, enclave, resource in (
                        ('S2', scenario_s2, 'Enforce 模式合法 A 区请求：Planner→Gateway→NavigationSim 正常完成',
                         '/planner', ACTION_GUARDED),
                        ('S5', scenario_s5, 'Enforce 模式 B 区越界：身份合法但 TaskPolicy 拒绝',
                         '/planner', ACTION_GUARDED),
                        ('S3C', scenario_s3c, '正向对照：/gateway 身份直连执行接口应当成功',
                         '/gateway', ACTION_EXECUTE),
                        ('S3', scenario_s3, 'Enforce 模式：Planner 身份直连执行接口应被拒绝',
                         '/planner', ACTION_EXECUTE),
                        ('S4', scenario_s4, '无授权身份访问执行接口应被拒绝',
                         '/unauthorized', ACTION_EXECUTE),
                        ('S6', scenario_s6, '安全配置失效不得静默回退为无认证通信',
                         'bad-keystore', ACTION_EXECUTE)):
                    if wanted and cid not in wanted:
                        continue
                    case = Case(cid, name, name, secure=True, enclave=enclave, resource=resource,
                                domain=int(SECURE_DOMAIN))
                    # 共享栈：场景目录各自独立，但断言读取共享的 journal/audit
                    case.dir = os.path.join(run_dir, cid)
                    os.makedirs(case.dir, exist_ok=True)
                    print('\n=== {0} {1} ==='.format(cid, name))
                    fn(case, ctx)
                    results.append(case)
            else:
                for cid in shared_ids:
                    if wanted and cid not in wanted:
                        continue
                    case = Case(cid, '依赖 Enforce 安全栈的场景', '必须先就绪', secure=True,
                                domain=int(SECURE_DOMAIN))
                    case.dir = os.path.join(run_dir, cid)
                    os.makedirs(case.dir, exist_ok=True)
                    case.check('Enforce 安全栈就绪（前置条件）', False,
                               '安全栈未能就绪，本场景记 FAIL 而非跳过')
                    results.append(case)
        finally:
            leftovers = stop_all(nodes)
            if not ctx_case.passed:
                print('  WARN: Enforce 安全栈未就绪，相关场景已记为 FAIL')
            else:
                print('  [stack] 安全栈已停止；残留节点={0}'.format(len(leftovers)))

    passed = sum(1 for c in results if c.passed)
    summary = {
        'run_id': RUN_ID,
        'finished_at': now_iso(),
        'workspace': ROOT,
        'suite': 'sros2',
        'normal_domain': NORMAL_DOMAIN,
        'secure_domain': SECURE_DOMAIN,
        'total': len(results),
        'passed': passed,
        'failed': len(results) - passed,
        'scenarios': [c.summary() for c in results],
    }
    with open(os.path.join(run_dir, 'summary.json'), 'w', encoding='utf-8') as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)

    print('\n' + '=' * 70)
    print('SROS2 SUMMARY ({0} passed / {1} total)'.format(passed, len(results)))
    for case in results:
        print('  [{0}] {1:<26} {2}'.format('PASS' if case.passed else 'FAIL', case.case_id, case.name[:52]))
        for check in case.checks:
            if check['result'] == 'FAIL':
                print('        FAIL: {0} -- {1}'.format(check['check'], check['detail'][:160]))
    print('evidence: {0}'.format(os.path.relpath(run_dir, ROOT)))
    return 0 if passed == len(results) else 1


if __name__ == '__main__':
    sys.exit(main())
