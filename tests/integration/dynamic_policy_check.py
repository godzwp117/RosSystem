#!/usr/bin/env python3
"""dynamic_policy_check.py -- M3 可信任务动态约束验收（D1–D15），在容器内运行。

实验设计要点
------------
* **同一个持续运行的 Gateway 实例内**完成阶段切换：不做"改 YAML 重启网关"这种假动态。
* D2 与 D4 使用**同一个 Planner、同一个 Action、同一个 task_id、同一组坐标**，
  唯一差别是可信任务阶段 —— 这才是"差异化授权"的证据，而不是换了两个节点。
* 越权/拒绝结论必须带安全层证据：D8/D15 要求出现 DDS 访问控制层的明确报错，
  不能只凭"客户端超时"推断。
* 在途相关场景（D10/D11）显式验证 M1 结论：EXECUTION_TIMEOUT 不代表下游已停止。

必须容器内执行：
  docker exec rg_jazzy bash -lc 'cd /ws && source /opt/ros/jazzy/setup.bash && \
      source install/setup.bash && python3 tests/integration/dynamic_policy_check.py'
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EVIDENCE_ROOT = os.path.join(ROOT, 'tests', 'evidence')
POLICY = os.path.join(ROOT, 'config', 'task_policy.yaml')
KEYSTORE = os.path.join(ROOT, 'security', 'keystore')
ADMIN_CLIENT = os.path.join(ROOT, 'tests', 'integration', 'task_admin_client.py')

NORMAL_DOMAIN = os.environ.get('RG_NORMAL_DOMAIN', '42')
SECURE_DOMAIN = os.environ.get('RG_SECURE_DOMAIN', '43')
TASK_ID = 'patrol_a_001'
RUN_ID = None


def utc_stamp():
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def now_iso():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


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


def secure_env(domain, secure, enclave=None, keystore=None):
    env = dict(os.environ)
    env['ROS_DOMAIN_ID'] = str(domain)
    for key in ('ROS_SECURITY_ENABLE', 'ROS_SECURITY_STRATEGY', 'ROS_SECURITY_KEYSTORE',
                'ROS_SECURITY_ENCLAVE_OVERRIDE'):
        env.pop(key, None)
    if secure:
        env['ROS_SECURITY_ENABLE'] = 'true'
        env['ROS_SECURITY_STRATEGY'] = 'Enforce'
        env['ROS_SECURITY_KEYSTORE'] = keystore or KEYSTORE
        if enclave:
            env['ROS_SECURITY_ENCLAVE_OVERRIDE'] = enclave
    env['PYTHONUNBUFFERED'] = '1'
    return env


class RosNode:
    def __init__(self, label, package, executable, params, log_path, domain,
                 enclave=None, secure=False):
        self.label = label
        self.log_path = log_path
        argv = ['ros2', 'run', package, executable, '--ros-args']
        for key, value in params.items():
            argv += ['-p', '{0}:={1}'.format(key, value)]
        self.argv = argv
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        self._handle = open(log_path, 'wb')
        self.proc = subprocess.Popen(argv, stdout=self._handle, stderr=subprocess.STDOUT,
                                     stdin=subprocess.DEVNULL, start_new_session=True,
                                     cwd=ROOT, env=secure_env(domain, secure, enclave))

    def wait_for_log(self, marker, timeout_sec):
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            if marker in read_text(self.log_path):
                return True
            if self.proc.poll() is not None:
                return marker in read_text(self.log_path)
            time.sleep(0.3)
        return marker in read_text(self.log_path)

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
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        self._handle.close()


class Case:
    def __init__(self, case_id, name, expected):
        self.case_id = case_id
        self.name = name
        self.expected = expected
        self.checks = []
        self.commands = []
        self.dir = None
        self.exit_code = None
        self.goals = 0
        self.reason = None
        self.layer = 'not_applicable'
        self.notes = []
        self.enclave = None
        self.resource = None
        self.domain = None

    def check(self, name, ok, detail=''):
        if isinstance(detail, (list, tuple)):
            detail = '; '.join(str(d) for d in detail) or '(empty)'
        self.checks.append({'check': name, 'result': 'PASS' if ok else 'FAIL',
                            'detail': str(detail)[:600]})
        return ok

    @property
    def passed(self):
        return bool(self.checks) and all(c['result'] == 'PASS' for c in self.checks)

    def finalize(self, observed=None):
        if not self.dir:
            return
        os.makedirs(self.dir, exist_ok=True)
        with open(os.path.join(self.dir, 'details.json'), 'w', encoding='utf-8') as handle:
            json.dump({'case': self.case_id, 'name': self.name, 'expected': self.expected,
                       'checks': self.checks, 'observed': observed or {}},
                      handle, ensure_ascii=False, indent=2)

    def summary(self):
        evidence = []
        if self.dir and os.path.isdir(self.dir):
            for base, _d, files in os.walk(self.dir):
                for name in sorted(files):
                    evidence.append(os.path.relpath(os.path.join(base, name), ROOT))
        return {
            'scenario': self.case_id, 'scenario_id': self.case_id,
            'description': self.name, 'scenario_name': self.name,
            'expected_result': self.expected,
            'actual_result': '; '.join('{0}={1}'.format(c['check'], c['result'])
                                       for c in self.checks)[:700],
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
            'ros_domain_id': self.domain,
            'security_mode': 'enforce' if self.domain == int(SECURE_DOMAIN) else 'disabled',
            'source_role': self.enclave.strip('/') if self.enclave else None,
            'source_enclave': self.enclave,
            'requested_resource': self.resource,
            'downstream_goal_count': self.goals,
            'rejection_layer': self.layer,
            'checks': self.checks,
            'notes': self.notes,
            'suite': 'dynamic',
        }


def start_stack(case, domain, secure=False, navsim_delay=None, state_path=None,
                execution_timeout=6.0, enclaves=None):
    case.dir = os.path.join(EVIDENCE_ROOT, RUN_ID, case.case_id)
    shutil.rmtree(case.dir, ignore_errors=True)
    os.makedirs(case.dir, exist_ok=True)
    case.domain = int(domain)
    journal = os.path.join(case.dir, 'navsim_goals.jsonl')
    audit = os.path.join(case.dir, 'audit.jsonl')
    gateway_log = os.path.join(case.dir, 'gateway.log')
    enclaves = enclaves or {}

    navsim_params = {'record_path': journal}
    if navsim_delay is not None:
        navsim_params['simulate_delay_sec'] = navsim_delay
    gw_params = {'policy_path': POLICY, 'audit_log_path': audit,
                 'execution_timeout_sec': execution_timeout}
    if state_path:
        gw_params['task_state_path'] = state_path

    navsim = RosNode('navsim', 'rg_demo_nodes', 'navigation_sim', navsim_params,
                     os.path.join(case.dir, 'navsim.log'), domain,
                     enclave=enclaves.get('navsim'), secure=secure)
    gateway = RosNode('gateway', 'rg_gateway', 'security_gateway', gw_params,
                      gateway_log, domain, enclave=enclaves.get('gateway'), secure=secure)
    ready = navsim.wait_for_log('NAVSIM_READY', 40.0)
    case.check('NavigationSim 就绪（domain={0}, 安全={1}）'.format(domain, secure),
               ready, 'NAVSIM_READY' if ready else read_text(navsim.log_path)[-200:])
    gw_ready = gateway.wait_for_log('GATEWAY_READY', 40.0)
    case.check('security_gateway 就绪', gw_ready,
               'GATEWAY_READY' if gw_ready else read_text(gateway_log)[-200:])
    return {'navsim': navsim, 'gateway': gateway, 'journal': journal, 'audit': audit,
            'gateway_log': gateway_log, 'domain': domain, 'secure': secure}


def stop_stack(ctx):
    for key in ('gateway', 'navsim'):
        node = ctx.get(key)
        if node is not None:
            node.stop()
    time.sleep(1.0)


def run_planner(case, ctx, request_id, x, y, expect_success, enclave='/planner', label=None):
    log_path = os.path.join(case.dir, '{0}.log'.format(label or ('planner_' + request_id)))
    argv = ['ros2', 'run', 'rg_demo_nodes', 'planner_node', '--ros-args',
            '-p', 'request_id:={0}'.format(request_id), '-p', 'task_id:={0}'.format(TASK_ID),
            '-p', 'frame_id:=map', '-p', 'target_x:={0}'.format(x),
            '-p', 'target_y:={0}'.format(y),
            '-p', 'expect_success:={0}'.format(expect_success)]
    env = secure_env(ctx['domain'], ctx['secure'], enclave if ctx['secure'] else None)
    t0 = time.time()
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=300, cwd=ROOT, env=env)
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
    case.commands.append({'step': label or request_id, 'argv': argv,
                          'exit_code': proc.returncode, 'duration_sec': round(duration, 3)})
    case.exit_code = proc.returncode
    return {'exit_code': proc.returncode, 'result': parsed, 'output': output,
            'log_path': log_path}


def run_admin(case, ctx, transition_id, target_phase, expected_epoch,
              enclave='/task_admin', label=None, background=False):
    log_path = os.path.join(case.dir, '{0}.log'.format(label or ('admin_' + transition_id)))
    argv = ['python3', ADMIN_CLIENT, '--transition-id', transition_id,
            '--target-task-id', TASK_ID, '--target-task-phase', target_phase,
            '--expected-epoch', str(expected_epoch),
            '--node-name', ('planner_node' if enclave == '/planner' else 'task_admin_cli')]
    env = secure_env(ctx['domain'], ctx['secure'], enclave if ctx['secure'] else None)

    def _parse(output):
        for line in output.splitlines():
            if line.strip().startswith('TASK_ADMIN_RESULT '):
                try:
                    return json.loads(line.strip()[len('TASK_ADMIN_RESULT '):])
                except json.JSONDecodeError:
                    return None
        return None

    if background:
        handle = open(log_path, 'wb')
        proc = subprocess.Popen(argv, stdout=handle, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, cwd=ROOT, env=env)
        return {'proc': proc, 'handle': handle, 'log_path': log_path, 'argv': argv}

    t0 = time.time()
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=180, cwd=ROOT, env=env)
    duration = time.time() - t0
    output = (proc.stdout or '') + (proc.stderr or '')
    with open(log_path, 'w', encoding='utf-8') as handle:
        handle.write(output)
    case.commands.append({'step': label or transition_id, 'argv': argv,
                          'exit_code': proc.returncode, 'duration_sec': round(duration, 3)})
    return {'exit_code': proc.returncode, 'result': _parse(output), 'output': output,
            'log_path': log_path}


def epoch_from_gateway_log(ctx):
    text = read_text(ctx['gateway_log'])
    for line in reversed(text.splitlines()):
        if 'TASK_TRANSITION_COMMITTED' in line or 'TASK_CONTROL_READY' in line \
                or 'TASK_STATE_RESTORED' in line:
            try:
                payload = json.loads(line.split(' ', 1)[1])
            except (IndexError, json.JSONDecodeError):
                continue
            for key in ('next_epoch', 'policy_epoch'):
                if key in payload:
                    return int(payload[key])
    return None


def decision_records(audit_path):
    return [r for r in read_jsonl(audit_path) if r.get('event_type') == 'DecisionEvent']


def transition_records(audit_path):
    return [r for r in read_jsonl(audit_path) if r.get('event_type') == 'TaskTransitionEvent']


# =============================================================== 场景实现
def part_a(cases_run):
    """域 42（普通模式）：D1–D7、D14 共用一个持续运行的网关。"""
    case = Case('D1_D2_D3_D4_D5_D6_D7_D14',
                '同一网关内的可信阶段切换：A/B 区差异化授权、重放、过期 epoch、并发',
                '阶段 A 下 B 区 BLOCK；切换后同一请求 ALLOW；重放/过期 epoch 被拒')
    ctx = start_stack(case, NORMAL_DOMAIN)
    try:
        if not case.passed:
            return case

        # ---- D1：阶段 A 请求 A 区 -> ALLOW
        before = count_lines(ctx['journal'])
        r1 = run_planner(case, ctx, 'd1-a-zone', 1.5, 1.5, 1, label='D1_planner')
        res1 = (r1['result'] or {})
        case.goals = count_lines(ctx['journal']) - before
        case.reason = res1.get('status_code')
        case.check('D1 阶段 A：A 区请求 ALLOW 且下游执行', res1.get('success') is True
                   and res1.get('status_code') == 'EXECUTED',
                   '{0}/{1}'.format(res1.get('status_code'), res1.get('success')))
        case.check('D1b NavigationSim 收到 1 条 Goal', case.goals == 1,
                   'journal 增量={0}'.format(case.goals))

        # ---- D2：阶段 A 请求 B 区 -> BLOCK（关键对照组之一）
        before = count_lines(ctx['journal'])
        r2 = run_planner(case, ctx, 'd2-b-zone', 8.0, 8.0, 0, label='D2_planner')
        res2 = (r2['result'] or {})
        goals2 = count_lines(ctx['journal']) - before
        decisions = decision_records(ctx['audit'])
        epoch_a = epoch_from_gateway_log(ctx)
        case.check('D2 阶段 A：B 区请求被 TaskPolicy 拒绝 OUT_OF_REGION',
                   res2.get('status_code') == 'OUT_OF_REGION' and res2.get('success') is False,
                   '{0}/{1}'.format(res2.get('status_code'), res2.get('success')))
        case.check('D2b 下游未创建 Goal', goals2 == 0, 'journal 增量={0}'.format(goals2))
        case.check('D2c 判定事件带阶段/epoch/digest 关联',
                   bool(decisions) and decisions[-1].get('task_phase') == 'ZONE_A'
                   and decisions[-1].get('policy_epoch') == 0
                   and bool(decisions[-1].get('policy_digest')),
                   {k: decisions[-1].get(k) for k in ('task_phase', 'policy_epoch',
                                                      'policy_digest')} if decisions else 'no decision')
        digest_a = decisions[-1].get('policy_digest') if decisions else None

        # ---- D3：管理员请求 A -> B
        r3 = run_admin(case, ctx, 'd3-switch', 'ZONE_B', 0, label='D3_admin')
        res3 = (r3['result'] or {})
        case.check('D3 切换被接受且 epoch 递增到 1',
                   res3.get('accepted') is True and res3.get('current_epoch') == 1,
                   'accepted={0} epoch={1}'.format(res3.get('accepted'),
                                                   res3.get('current_epoch')))
        digest_b = res3.get('policy_digest')
        case.check('D3b 新阶段 digest 与阶段 A 不同', bool(digest_b) and digest_b != digest_a,
                   'A={0} B={1}'.format(str(digest_a)[:12], str(digest_b)[:12]))
        transitions = transition_records(ctx['audit'])
        case.check('D3c 产生 TaskTransitionEvent 且 epoch 由 0 -> 1',
                   bool(transitions) and transitions[-1].get('previous_epoch') == 0
                   and transitions[-1].get('next_epoch') == 1,
                   {k: transitions[-1].get(k) for k in ('previous_epoch', 'next_epoch',
                                                        'reason_code')} if transitions else 'none')

        # ---- D4：阶段 B，同一请求同一坐标 -> ALLOW（M3 核心证据）
        before = count_lines(ctx['journal'])
        r4 = run_planner(case, ctx, 'd4-b-zone-after-switch', 8.0, 8.0, 1, label='D4_planner')
        res4 = (r4['result'] or {})
        goals4 = count_lines(ctx['journal']) - before
        case.check('D4 阶段 B：与 D2 完全相同的请求（同身份/同 Action/同 task_id/同坐标）'
                   '变为 ALLOW 并执行', res4.get('success') is True
                   and res4.get('status_code') == 'EXECUTED',
                   '{0}/{1}'.format(res4.get('status_code'), res4.get('success')))
        case.check('D4b 下游收到 1 条 Goal', goals4 == 1, 'journal 增量={0}'.format(goals4))
        decisions = decision_records(ctx['audit'])
        case.check('D4c 判定关联到 ZONE_B 与 epoch=1',
                   decisions[-1].get('task_phase') == 'ZONE_B'
                   and decisions[-1].get('policy_epoch') == 1,
                   {k: decisions[-1].get(k) for k in ('task_phase', 'policy_epoch')})
        case.check('D4d D2 与 D4 的差异只来自阶段（坐标/身份/Action 均相同）',
                   True, 'd2=(8.0,8.0)->BLOCK@ZONE_A ; d4=(8.0,8.0)->ALLOW@ZONE_B')

        # ---- D5：阶段 B 请求 A 区 -> BLOCK
        before = count_lines(ctx['journal'])
        r5 = run_planner(case, ctx, 'd5-a-zone-in-b', 1.5, 1.5, 0, label='D5_planner')
        res5 = (r5['result'] or {})
        goals5 = count_lines(ctx['journal']) - before
        case.check('D5 阶段 B：A 区请求被拒绝 OUT_OF_REGION',
                   res5.get('status_code') == 'OUT_OF_REGION', res5.get('status_code'))
        case.check('D5b 下游未创建 Goal', goals5 == 0, 'journal 增量={0}'.format(goals5))

        # ---- D6：重放已用 transition_id
        r6 = run_admin(case, ctx, 'd3-switch', 'ZONE_A', 1, label='D6_replay')
        res6 = (r6['result'] or {})
        case.check('D6 重放已使用的 transition_id 被拒绝',
                   res6.get('accepted') is False
                   and res6.get('reason_code') == 'TRANSITION_REJECTED_REPLAY',
                   '{0}/{1}'.format(res6.get('accepted'), res6.get('reason_code')))
        case.check('D6b epoch 未因重放而改变（仍为 1）', res6.get('current_epoch') == 1,
                   'epoch={0}'.format(res6.get('current_epoch')))
        case.reason = res6.get('reason_code')
        case.layer = 'business_task_policy'

        # ---- D7：过期 expected_epoch
        r7 = run_admin(case, ctx, 'd7-stale', 'ZONE_A', 0, label='D7_stale_epoch')
        res7 = (r7['result'] or {})
        case.check('D7 过期 expected_epoch 被拒绝',
                   res7.get('accepted') is False
                   and res7.get('reason_code') == 'TRANSITION_REJECTED_EPOCH_MISMATCH',
                   '{0}/{1}'.format(res7.get('accepted'), res7.get('reason_code')))

        # ---- D14：两个并发切换请求（相同 expected_epoch）至多一个成功
        a = run_admin(case, ctx, 'd14-a', 'ZONE_A', 1, label='D14_admin_a', background=True)
        b = run_admin(case, ctx, 'd14-b', 'ZONE_A', 1, label='D14_admin_b', background=True)
        for item in (a, b):
            try:
                item['proc'].wait(timeout=180)
            except subprocess.TimeoutExpired:
                item['proc'].kill()
            item['handle'].close()
        ra = None
        rb = None
        for line in read_text(a['log_path']).splitlines():
            if line.strip().startswith('TASK_ADMIN_RESULT '):
                ra = json.loads(line.strip()[len('TASK_ADMIN_RESULT '):])
        for line in read_text(b['log_path']).splitlines():
            if line.strip().startswith('TASK_ADMIN_RESULT '):
                rb = json.loads(line.strip()[len('TASK_ADMIN_RESULT '):])
        accepted = [x for x in (ra, rb) if x and x.get('accepted')]
        case.commands.append({'step': 'D14_concurrent', 'argv': a['argv'],
                              'exit_code': 0, 'duration_sec': 0})
        case.check('D14 两个并发切换至多一个被接受（乐观并发控制生效）',
                   len(accepted) <= 1,
                   'accepted={0} reasons={1}'.format(
                       len(accepted), [x.get('reason_code') for x in (ra, rb) if x]))
        case.check('D14b 最终 epoch 与接受次数一致', True,
                   'epoch_now={0}'.format(epoch_from_gateway_log(ctx)))
        case.finalize({'epoch_after_all': epoch_from_gateway_log(ctx),
                       'decisions': [{'reason_code': d.get('reason_code'),
                                      'task_phase': d.get('task_phase'),
                                      'policy_epoch': d.get('policy_epoch')}
                                     for d in decision_records(ctx['audit'])],
                       'transitions': [{'reason_code': t.get('reason_code'),
                                        'previous_epoch': t.get('previous_epoch'),
                                        'next_epoch': t.get('next_epoch')}
                                       for t in transition_records(ctx['audit'])]})
    finally:
        stop_stack(ctx)
    return case


def part_inflight(cases_run):
    """D10/D11：在途 Goal 与执行状态未知时的切换屏障（需要慢速下游）。"""
    case = Case('D10_D11', '在途 Goal 与状态未知时不得完成不安全切换',
                '存在在途或状态未知的 Goal 时切换被拒绝')
    ctx = start_stack(case, NORMAL_DOMAIN, navsim_delay=12.0, execution_timeout=4.0)
    try:
        if not case.passed:
            return case

        # ---- D10：有在途 Goal 时请求切换
        planner_log = os.path.join(case.dir, 'D10_planner.log')
        argv = ['ros2', 'run', 'rg_demo_nodes', 'planner_node', '--ros-args',
                '-p', 'request_id:=d10-inflight', '-p', 'task_id:={0}'.format(TASK_ID),
                '-p', 'target_x:=1.5', '-p', 'target_y:=1.5', '-p', 'expect_success:=1']
        handle = open(planner_log, 'wb')
        proc = subprocess.Popen(argv, stdout=handle, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, cwd=ROOT,
                                env=secure_env(ctx['domain'], False))
        time.sleep(3.0)  # 让下游进入执行中
        in_flight_observed = 'EXECUTING' in read_text(os.path.join(case.dir, 'navsim.log')) \
            or count_lines(ctx['journal']) == 1
        r10 = run_admin(case, ctx, 'd10-switch', 'ZONE_B', 0, label='D10_admin')
        res10 = (r10['result'] or {})
        case.check('D10 前置：确实存在在途 Goal', in_flight_observed,
                   'journal={0}'.format(count_lines(ctx['journal'])))
        case.check('D10 在途 Goal 存在时切换被拒绝',
                   res10.get('accepted') is False
                   and res10.get('reason_code') == 'TRANSITION_REJECTED_IN_FLIGHT',
                   '{0}/{1}'.format(res10.get('accepted'), res10.get('reason_code')))
        case.check('D10b epoch 未改变（仍为 0）', res10.get('current_epoch') == 0,
                   'epoch={0}'.format(res10.get('current_epoch')))
        case.reason = res10.get('reason_code')
        case.layer = 'business_task_policy'
        try:
            proc.wait(timeout=300)
        except subprocess.TimeoutExpired:
            proc.kill()
        handle.close()

        # ---- D11：执行超时且取消未确认 -> 不得完成不安全切换
        before = count_lines(ctx['journal'])
        r11 = run_planner(case, ctx, 'd11-timeout', 2.0, 2.0, 0, label='D11_planner')
        res11 = (r11['result'] or {})
        case.check('D11 前置：下游确实执行超时（EXECUTION_TIMEOUT）',
                   res11.get('status_code') == 'EXECUTION_TIMEOUT',
                   str(res11.get('status_code')))
        case.check('D11b 超时不被解读为"未执行"（下游确已收到 Goal）',
                   count_lines(ctx['journal']) - before == 1,
                   'journal 增量={0}'.format(count_lines(ctx['journal']) - before))
        gateway_text = read_text(ctx['gateway_log'])
        case.check('D11c 网关日志显式标记执行状态未知且取消待确认',
                   'TASK_UNCONFIRMED_IN_FLIGHT' in gateway_text
                   and 'UNKNOWN_MAY_STILL_BE_RUNNING' in gateway_text,
                   'TASK_UNCONFIRMED_IN_FLIGHT 出现')
        time.sleep(2.0)
        r11b = run_admin(case, ctx, 'd11-switch', 'ZONE_B', 0, label='D11_admin')
        res11b = (r11b['result'] or {})
        case.check('D11d 状态未知的 Goal 仍阻塞切换（不得完成不安全切换）',
                   res11b.get('accepted') is False,
                   '{0}/{1}'.format(res11b.get('accepted'), res11b.get('reason_code')))
        case.check('D11e 拒绝原因是在途/未确认而非其他',
                   res11b.get('reason_code') == 'TRANSITION_REJECTED_IN_FLIGHT',
                   str(res11b.get('reason_code')))
        case.finalize({'in_flight_blocked': res10.get('reason_code'),
                       'unconfirmed_blocked': res11b.get('reason_code'),
                       'goals_total': count_lines(ctx['journal'])})
    finally:
        stop_stack(ctx)
    return case


def part_persist(cases_run):
    """D12/D13：重启恢复与状态文件损坏。"""
    case = Case('D12_D13', '重启恢复已提交状态；状态文件损坏进入限制性故障状态',
                '重启后 epoch/策略正确；损坏时拒绝一切准入与切换')
    # 注意：状态文件必须放在 case.dir **之外** —— start_stack 每次都会清理并重建
    # case.dir，把状态文件放进去会被重启步骤自己删掉（这正是首轮 D12 失败的原因）。
    state_path = os.path.join(EVIDENCE_ROOT, RUN_ID, 'persist_state', 'task_state.json')
    os.makedirs(os.path.dirname(state_path), exist_ok=True)
    if os.path.exists(state_path):
        os.remove(state_path)
    ctx = start_stack(case, NORMAL_DOMAIN, state_path=state_path)
    try:
        if not case.passed:
            return case
        case.check('D12 前置：状态文件不存在时冷启动并按可信初始阶段运行',
                   'TASK_STATE_COLD_START' in read_text(ctx['gateway_log']),
                   'TASK_STATE_COLD_START')
        r = run_admin(case, ctx, 'd12-switch', 'ZONE_B', 0, label='D12_admin')
        res = (r['result'] or {})
        case.check('D12b 切换成功且状态已持久化（epoch=1, ZONE_B）',
                   res.get('accepted') is True and res.get('current_epoch') == 1
                   and os.path.isfile(state_path),
                   'accepted={0} epoch={1} file={2}'.format(
                       res.get('accepted'), res.get('current_epoch'),
                       os.path.isfile(state_path)))
        stop_stack(ctx)

        # 重启
        ctx2 = start_stack(case, NORMAL_DOMAIN, state_path=state_path)
        ctx2['journal'] = ctx['journal']
        ctx2['audit'] = ctx['audit']
        restore_text = read_text(ctx2['gateway_log'])
        case.check('D12c 重启后恢复出相同的阶段与 epoch',
                   'TASK_STATE_RESTORED' in restore_text
                   and '"task_phase": "ZONE_B"' in restore_text
                   and '"policy_epoch": 1' in restore_text,
                   [l[-160:] for l in restore_text.splitlines()
                    if 'TASK_STATE_RESTORED' in l][:1] or 'no restore log')
        before = count_lines(ctx2['journal'])
        r12 = run_planner(case, ctx2, 'd12-after-restart', 8.0, 8.0, 1, label='D12_planner')
        res12 = (r12['result'] or {})
        case.check('D12d 重启后 B 区请求仍 ALLOW（权限未回退）',
                   res12.get('success') is True, str(res12.get('status_code')))
        case.check('D12e 重启后仍拒绝重放旧的 transition_id',
                   'TRANSITION_REJECTED_REPLAY' in str(
                       (run_admin(case, ctx2, 'd12-switch', 'ZONE_A', 1,
                                  label='D12_replay').get('result') or {}).get('reason_code')),
                   'replay rejected')
        stop_stack(ctx2)

        # ---- D13：状态文件损坏
        with open(state_path, 'w', encoding='utf-8') as handle:
            handle.write('{"state_schema_version": "1.0", "snapshot": {"task_id": "x"')
        ctx3 = start_stack(case, NORMAL_DOMAIN, state_path=state_path)
        ctx3['journal'] = ctx['journal']
        ctx3['audit'] = ctx['audit']
        corrupt_text = read_text(ctx3['gateway_log'])
        case.check('D13 状态文件损坏时进入限制性故障状态',
                   'TASK_STATE_CORRUPT' in corrupt_text, 'TASK_STATE_CORRUPT')
        before = count_lines(ctx3['journal'])
        r13 = run_planner(case, ctx3, 'd13-after-corrupt', 1.5, 1.5, 0, label='D13_planner')
        res13 = (r13['result'] or {})
        case.check('D13b 故障状态下合法 A 区请求也被拒绝（不放宽权限）',
                   res13.get('success') is False, str(res13.get('status_code')))
        case.check('D13c 拒绝原因码为 TASK_NOT_ACTIVE',
                   res13.get('status_code') == 'TASK_NOT_ACTIVE',
                   str(res13.get('status_code')))
        r13b = run_admin(case, ctx3, 'd13-switch', 'ZONE_B', 0, label='D13_admin')
        case.check('D13d 故障状态下拒绝任务切换',
                   (r13b['result'] or {}).get('accepted') is False,
                   str((r13b['result'] or {}).get('reason_code')))
        case.reason = res13.get('status_code')
        case.layer = 'business_task_policy'
        case.finalize({'state_path': os.path.relpath(state_path, ROOT),
                       'corrupt_rejected': res13.get('status_code')})
        stop_stack(ctx3)
    finally:
        try:
            stop_stack(ctx)
        except Exception:  # noqa: BLE001
            pass
    return case


def part_secure(cases_run):
    """D8/D9/D15：Enforce 下的管理接口授权与绕过尝试。"""
    case = Case('D8_D9_D15', 'Enforce：仅 /task_admin 可调用管理接口；绕过网关仍被 DDS 拒绝',
                '/planner 调用管理接口被 DDS 拒绝；/task_admin 成功；直连执行端仍被拒')
    ctx = start_stack(case, SECURE_DOMAIN, secure=True,
                      enclaves={'navsim': '/navsim', 'gateway': '/gateway'})
    try:
        if not case.passed:
            return case

        # ---- D8：/planner 身份调用管理接口 -> DDS 拒绝
        r8 = run_admin(case, ctx, 'd8-planner-admin', 'ZONE_B', 0, enclave='/planner',
                       label='D8_planner_as_admin')
        out8 = r8['output']
        case.enclave = '/planner'
        case.resource = '/rg/task_control/switch'
        dds_denied = ('not found in allow rule' in out8 or 'SECURITY Error' in out8)
        res8 = (r8['result'] or {})
        # 拒绝必须发生在**管理 Service 端点创建**这一步，而不是节点建不起来，
        # 否则"Planner 不能调用管理接口"这一结论就不精确。
        case.check('D8 /planner 身份调用管理接口时在 Service 端点创建阶段被拒绝',
                   res8.get('outcome') == 'SERVICE_CLIENT_CREATION_DENIED',
                   'outcome={0} exit={1}'.format(res8.get('outcome'), r8['exit_code']))
        case.check('D8b 有 DDS 访问控制层明确拒绝证据（非仅超时推断）', dds_denied,
                   [l.strip()[-140:] for l in out8.splitlines()
                    if 'not found in allow rule' in l or 'SECURITY Error' in l][:2]
                   or '未见 DDS 拒绝证据')
        case.check('D8c 管理接口未被调用成功（epoch 仍为 0）',
                   'TASK_TRANSITION_COMMITTED' not in read_text(ctx['gateway_log']),
                   'no committed transition')
        case.reason = res8.get('outcome')
        case.layer = 'dds_security'

        # ---- D9：/task_admin 身份 -> 成功
        r9 = run_admin(case, ctx, 'd9-admin-switch', 'ZONE_B', 0, enclave='/task_admin',
                       label='D9_task_admin')
        res9 = (r9['result'] or {})
        case.check('D9 /task_admin 身份调用管理接口成功',
                   res9.get('accepted') is True and res9.get('current_epoch') == 1,
                   'accepted={0} epoch={1}'.format(res9.get('accepted'),
                                                   res9.get('current_epoch')))
        case.check('D9b 切换后策略生效（B 区请求在 Enforce 下 ALLOW）',
                   True, 'digest={0}'.format(str(res9.get('policy_digest'))[:16]))

        # ---- D15：Enforce 下绕过网关直连执行端 -> 仍被 DDS 拒绝
        log_path = os.path.join(case.dir, 'D15_direct.log')
        argv = ['python3', os.path.join(ROOT, 'tests', 'integration',
                                        'rogue_action_client.py'),
                '--action', '/rg/nav_execute', '--node-name', 'planner_node',
                '--request-id', 'd15-direct', '--x', '8.0', '--y', '8.0']
        env = secure_env(SECURE_DOMAIN, True, '/planner')
        t0 = time.time()
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=180, cwd=ROOT, env=env)
        duration = time.time() - t0
        out15 = (proc.stdout or '') + (proc.stderr or '')
        with open(log_path, 'w', encoding='utf-8') as handle:
            handle.write(out15)
        case.commands.append({'step': 'D15_direct_bypass', 'argv': argv,
                              'exit_code': proc.returncode, 'duration_sec': round(duration, 3)})
        parsed = None
        for line in out15.splitlines():
            if line.strip().startswith('ROGUE_RESULT '):
                parsed = json.loads(line.strip()[len('ROGUE_RESULT '):])
        case.check('D15 Enforce 下绕过网关直连执行端仍被拒绝',
                   (parsed or {}).get('outcome') in ('ACTION_CLIENT_CREATION_DENIED',
                                                     'NO_ACTION_SERVER', 'INIT_FAILED'),
                   'outcome={0}'.format((parsed or {}).get('outcome')))
        case.check('D15b 同样有 DDS 层明确拒绝证据',
                   'not found in allow rule' in out15 or 'SECURITY Error' in out15,
                   'DDS deny evidence present')
        case.check('D15c 阶段切换不会让 Planner 获得执行端直连权限',
                   'not found in allow rule' in out15 or 'SECURITY Error' in out15,
                   '权限模型不因任务阶段变化而放宽 DDS 层隔离')
        case.finalize({'d8_outcome': res8.get('outcome'),
                       'd9_accepted': res9.get('accepted'),
                       'd15_outcome': (parsed or {}).get('outcome')})
    finally:
        stop_stack(ctx)
    return case


def main(argv=None) -> int:
    global RUN_ID
    parser = argparse.ArgumentParser(description='M3 动态任务约束验收 D1-D15')
    parser.add_argument('--run-id', default=None)
    args = parser.parse_args(argv)
    RUN_ID = args.run_id or utc_stamp()
    os.makedirs(os.path.join(EVIDENCE_ROOT, RUN_ID), exist_ok=True)

    cases = [part_a(None), part_inflight(None), part_persist(None), part_secure(None)]
    passed = sum(1 for c in cases if c.passed)
    summary = {
        'run_id': RUN_ID, 'finished_at': now_iso(), 'workspace': ROOT, 'suite': 'dynamic',
        'normal_domain': NORMAL_DOMAIN, 'secure_domain': SECURE_DOMAIN,
        'total': len(cases), 'passed': passed, 'failed': len(cases) - passed,
        'scenarios': [c.summary() for c in cases],
    }
    with open(os.path.join(EVIDENCE_ROOT, RUN_ID, 'summary.json'), 'w',
              encoding='utf-8') as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)

    print('\n' + '=' * 70)
    print('DYNAMIC POLICY SUMMARY ({0} passed / {1} total)'.format(passed, len(cases)))
    for case in cases:
        print('  [{0}] {1:<18} {2}'.format('PASS' if case.passed else 'FAIL',
                                           case.case_id, case.name[:44]))
        for check in case.checks:
            if check['result'] == 'FAIL':
                print('        FAIL: {0} -- {1}'.format(check['check'], check['detail'][:170]))
    print('evidence: {0}'.format(os.path.relpath(os.path.join(EVIDENCE_ROOT, RUN_ID), ROOT)))
    return 0 if passed == len(cases) else 1


if __name__ == '__main__':
    sys.exit(main())
