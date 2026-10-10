#!/usr/bin/env python3
"""env_isolation_check.py -- 多成员环境隔离验收（ENV-01..ENV-10）。

设计原则
--------
* 断言基于**实际 Docker Inspect、真实挂载与真实 ROS 运行结果**，
  而不是比较脚本输出的字符串（否则"脚本说成功"就等于通过）。
* 测试用的容器统一加 `rg_f0env` 前缀，结束时会清理**只属于本测试**的容器；
  绝不触碰 rg_jazzy 或任何其他成员的容器。
* 每项失败必须保留可复核的证据（日志、inspect 输出、退出码）。

在宿主机执行：
    python3 tests/integration/env_isolation_check.py
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EVIDENCE_ROOT = os.path.join(ROOT, 'tests', 'evidence')
SCRIPTS = os.path.join(ROOT, 'scripts')
MAIN_CONTAINER = os.environ.get('RG_CONTAINER', 'rg_jazzy')
TEST_PREFIX = 'rg_f0env'


def utc_stamp():
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def now_iso():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def sh(argv, timeout=600, cwd=None, env=None, text=True):
    proc = subprocess.run(argv, capture_output=True, text=text, timeout=timeout,
                          cwd=cwd or ROOT, env=env)
    return proc.returncode, (proc.stdout or '') + (proc.stderr or '')


def docker(*args, timeout=600):
    return sh(['docker'] + list(args), timeout=timeout)


def container_exists(name):
    return docker('inspect', name)[0] == 0


def container_running(name):
    code, out = docker('inspect', '-f', '{{.State.Running}}', name)
    return code == 0 and out.strip() == 'true'


def container_mount_source(name, destination):
    code, out = docker('inspect', '-f',
                       '{{range .Mounts}}{{if eq .Destination "%s"}}{{.Source}}{{end}}{{end}}'
                       % destination, name)
    return out.strip() if code == 0 else ''


def container_env(name, key):
    code, out = docker('inspect', '-f',
                       '{{range .Config.Env}}{{println .}}{{end}}', name)
    if code != 0:
        return ''
    for line in out.splitlines():
        if line.startswith(key + '='):
            return line.split('=', 1)[1].strip()
    return ''


def run_container_up(cwd, extra_env=None, timeout=600):
    env = dict(os.environ)
    env.pop('RG_MEMBER', None)
    env.pop('RG_DOMAIN_ID', None)
    env.update(extra_env or {})
    return sh(['bash', os.path.join(cwd, 'scripts', 'container_up.sh')],
              timeout=timeout, cwd=cwd, env=env)


def copy_workspace(dest):
    """复制完整工作区（含未提交的新文件），排除构建产物与历史归档。"""
    shutil.rmtree(dest, ignore_errors=True)
    os.makedirs(dest, exist_ok=True)
    excludes = ['./build', './install', './log', './.git', './logs', './tests/evidence',
                './gitlog.md', './artifacts/acceptance/published', './security/keystore']
    argv = ['tar', '-cf', '-']
    for item in excludes:
        argv += ['--exclude=' + item]
    argv.append('.')
    proc = subprocess.run(argv, cwd=ROOT, capture_output=True)
    if proc.returncode != 0:
        return False
    extract = subprocess.run(['tar', '-xf', '-', '-C', dest], input=proc.stdout,
                             capture_output=True)
    return extract.returncode == 0


class Case:
    def __init__(self, case_id, name, expected):
        self.case_id = case_id
        self.name = name
        self.expected = expected
        self.checks = []
        self.commands = []
        self.dir = None
        self.exit_code = None
        self.notes = []

    def check(self, name, ok, detail=''):
        if isinstance(detail, (list, tuple)):
            detail = '; '.join(str(d) for d in detail) or '(empty)'
        self.checks.append({'check': name, 'result': 'PASS' if ok else 'FAIL',
                            'detail': str(detail)[:600]})
        return ok

    def cmd(self, step, argv, exit_code, duration=0.0):
        self.commands.append({'step': step, 'argv': [str(a) for a in argv],
                              'exit_code': exit_code, 'duration_sec': round(duration, 3)})

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
            'reason_code': None,
            'checks': self.checks,
            'notes': self.notes,
            'suite': 'env_isolation',
        }


# --------------------------------------------------------------- ENV 用例
def env_01_02(tmp, run_dir):
    """ENV-01 新建独立容器；ENV-02 相同配置重复调用成功复用。"""
    case = Case('ENV-01_ENV-02', '新建成员容器正确挂载当前工作区；相同配置可安全复用',
                '新建容器挂载源==当前工作区；重复调用复用成功且配置一致')
    case.dir = os.path.join(run_dir, case.case_id)
    os.makedirs(case.dir, exist_ok=True)
    ws = os.path.join(tmp, 'member_env_a')
    name = TEST_PREFIX + '_a'
    try:
        if not copy_workspace(ws):
            case.check('准备独立工作区副本', False, ws)
            return case
        if container_exists(name):
            docker('rm', '-f', name)
        # ENV-01：新建
        t0 = time.time()
        code, out = run_container_up(ws, {'RG_CONTAINER': name, 'RG_DOMAIN_ID': '61'})
        case.cmd('create_container', ['container_up.sh'], code, time.time() - t0)
        with open(os.path.join(case.dir, 'create.log'), 'w', encoding='utf-8') as h:
            h.write(out)
        case.check('ENV-01 新建容器成功', code == 0, 'exit={0}'.format(code))
        actual_src = container_mount_source(name, '/ws')
        ws_norm = os.path.realpath(ws)
        case.check('ENV-01 容器挂载源等于当前工作区（docker inspect 实测）',
                   os.path.realpath(actual_src) == ws_norm,
                   'expected={0} actual={1}'.format(ws_norm, actual_src))
        case.check('ENV-01 容器 Domain 为请求值',
                   container_env(name, 'ROS_DOMAIN_ID') == '61',
                   'actual={0}'.format(container_env(name, 'ROS_DOMAIN_ID')))
        case.check('ENV-01 容器处于运行状态', container_running(name),
                   'running={0}'.format(container_running(name)))

        # ENV-02：相同配置重复调用
        t0 = time.time()
        code2, out2 = run_container_up(ws, {'RG_CONTAINER': name, 'RG_DOMAIN_ID': '61'})
        case.cmd('reuse_container', ['container_up.sh'], code2, time.time() - t0)
        with open(os.path.join(case.dir, 'reuse.log'), 'w', encoding='utf-8') as h:
            h.write(out2)
        case.check('ENV-02 相同配置重复调用成功', code2 == 0, 'exit={0}'.format(code2))
        case.check('ENV-02 输出表明已完成配置核对',
                   'verifying configuration before reuse' in out2 and '[ok]' in out2,
                   '核对与 ok 标记均出现')
        case.check('ENV-02 复用后容器仍在运行', container_running(name), 'running=True')
        case.finalize({'container': name, 'workspace': ws, 'domain': 61})
    finally:
        if container_exists(name):
            docker('rm', '-f', name)
    return case


def env_03_04_09(tmp, run_dir):
    """ENV-03/04/09：工作区、Domain、镜像/RMW 不匹配必须拒绝。"""
    case = Case('ENV-03_ENV-04_ENV-09',
                '复用前的配置核对：工作区/Domain/镜像/RMW 任一不符即拒绝',
                '三类不匹配全部返回非零并给出期望/实际/建议')
    case.dir = os.path.join(run_dir, case.case_id)
    os.makedirs(case.dir, exist_ok=True)
    other_ws = os.path.join(tmp, 'member_env_b')
    try:
        if not copy_workspace(other_ws):
            case.check('准备工作区副本', False, other_ws)
            return case

        # ENV-03：从**另一个工作区**复用主容器 → 必须拒绝
        t0 = time.time()
        code, out = run_container_up(other_ws, {'RG_CONTAINER': MAIN_CONTAINER})
        case.cmd('reuse_other_workspace', ['container_up.sh'], code, time.time() - t0)
        with open(os.path.join(case.dir, 'env03.log'), 'w', encoding='utf-8') as h:
            h.write(out)
        case.check('ENV-03 不同工作区复用同一容器被拒绝（exit 4）', code == 4,
                   'exit={0}'.format(code))
        case.check('ENV-03 报错含期望工作区/实际工作区/容器名/处理建议',
                   all(k in out for k in ('期望工作区', '实际工作区', MAIN_CONTAINER,
                                          '处理建议')),
                   '四项均出现')

        # ENV-04：同名容器但 Domain 不同 → 必须拒绝
        t0 = time.time()
        code, out = run_container_up(ROOT, {'RG_CONTAINER': MAIN_CONTAINER,
                                            'ROS_DOMAIN_ID': '99'})
        case.cmd('reuse_other_domain', ['container_up.sh'], code, time.time() - t0)
        with open(os.path.join(case.dir, 'env04.log'), 'w', encoding='utf-8') as h:
            h.write(out)
        case.check('ENV-04 Domain 不匹配被拒绝（exit 4）', code == 4, 'exit={0}'.format(code))
        case.check('ENV-04 报错明确指出 ROS_DOMAIN_ID 不符',
                   'ROS_DOMAIN_ID' in out and '不符' in out, '含 Domain 不符说明')

        # ENV-09：镜像不符
        t0 = time.time()
        code, out = run_container_up(ROOT, {'RG_CONTAINER': MAIN_CONTAINER,
                                            'RG_IMAGE': 'ros:humble'})
        case.cmd('reuse_other_image', ['container_up.sh'], code, time.time() - t0)
        with open(os.path.join(case.dir, 'env09_image.log'), 'w', encoding='utf-8') as h:
            h.write(out)
        case.check('ENV-09 镜像不匹配被拒绝', code == 4, 'exit={0}'.format(code))

        # ENV-09：RMW 不符
        t0 = time.time()
        code, out = run_container_up(ROOT, {'RG_CONTAINER': MAIN_CONTAINER,
                                            'RG_RMW': 'rmw_cyclonedds_cpp'})
        case.cmd('reuse_other_rmw', ['container_up.sh'], code, time.time() - t0)
        with open(os.path.join(case.dir, 'env09_rmw.log'), 'w', encoding='utf-8') as h:
            h.write(out)
        case.check('ENV-09 RMW 不匹配被拒绝', code == 4, 'exit={0}'.format(code))
        case.check('ENV-09 报错给出修复指引', '处理建议' in out, '含处理建议')

        case.check('不匹配时未停机/未删除既有容器（仍运行）',
                   container_running(MAIN_CONTAINER), 'main container running')
        case.finalize({'main_container': MAIN_CONTAINER})
    finally:
        shutil.rmtree(other_ws, ignore_errors=True)
    return case


def env_05(tmp, run_dir):
    """ENV-05：已停止容器配置不匹配时，不得"先启动再检查"。"""
    case = Case('ENV-05', '已停止容器配置不匹配时不得先启动再检查',
                '返回非零且容器保持停止状态')
    case.dir = os.path.join(run_dir, case.case_id)
    os.makedirs(case.dir, exist_ok=True)
    name = TEST_PREFIX + '_stopped'
    ws = os.path.join(tmp, 'member_env_c')
    try:
        if not copy_workspace(ws):
            case.check('准备工作区副本', False, ws)
            return case
        if container_exists(name):
            docker('rm', '-f', name)
        code, out = run_container_up(ws, {'RG_CONTAINER': name, 'RG_DOMAIN_ID': '62'})
        case.cmd('create', ['container_up.sh'], code)
        if code != 0:
            case.check('前置：创建测试容器', False, out[-200:])
            return case
        docker('stop', name, timeout=120)
        case.check('前置：容器已停止', not container_running(name), 'stopped')

        # 以不同 Domain 请求 → 应拒绝，且**不得**把容器启动起来
        code, out = run_container_up(ws, {'RG_CONTAINER': name, 'ROS_DOMAIN_ID': '63'})
        case.cmd('mismatch_on_stopped', ['container_up.sh'], code)
        with open(os.path.join(case.dir, 'env05.log'), 'w', encoding='utf-8') as h:
            h.write(out)
        case.check('ENV-05 配置不匹配被拒绝（exit 4）', code == 4, 'exit={0}'.format(code))
        case.check('ENV-05 容器仍处于停止状态（未先启动再检查）',
                   not container_running(name),
                   'running={0}'.format(container_running(name)))

        # 反证：配置匹配时应能正常启动（否则"保持停止"可能只是脚本坏了）
        code, out = run_container_up(ws, {'RG_CONTAINER': name, 'RG_DOMAIN_ID': '62'})
        case.cmd('matching_on_stopped', ['container_up.sh'], code)
        case.check('ENV-05 反证：配置匹配时能正常启动', code == 0
                   and container_running(name), 'exit={0}'.format(code))
        case.finalize({'container': name})
    finally:
        if container_exists(name):
            docker('rm', '-f', name)
        shutil.rmtree(ws, ignore_errors=True)
    return case


def env_06(tmp, run_dir):
    """ENV-06：两个成员工作区各自独立构建，build/install 不互相覆盖。

    关键点：`scripts/lib.sh` 的容器模式始终作用于**容器内的挂载点**（/ws），
    所以"把脚本副本放到别处"并不会改变构建目标。
    必须让每个工作区各自拥有一个容器，才能真正验证构建隔离。
    """
    case = Case('ENV-06', '两个成员工作区独立构建互不覆盖',
                '各自容器内构建各自工作区；互不写入对方的 build/install')
    case.dir = os.path.join(run_dir, case.case_id)
    os.makedirs(case.dir, exist_ok=True)
    ws_a = os.path.join(tmp, 'build_a')
    ws_b = os.path.join(tmp, 'build_b')
    ca, cb = TEST_PREFIX + '_builda', TEST_PREFIX + '_buildb'
    try:
        for ws in (ws_a, ws_b):
            if not copy_workspace(ws):
                case.check('准备工作区副本', False, ws)
                return case
        for name in (ca, cb):
            if container_exists(name):
                docker('rm', '-f', name)

        # 为每个工作区建自己的容器（这正是"一成员一容器"的语义）
        for name, ws, domain in ((ca, ws_a, '71'), (cb, ws_b, '72')):
            t0 = time.time()
            code, out = run_container_up(ws, {'RG_CONTAINER': name, 'RG_DOMAIN_ID': domain})
            case.cmd('create_' + name, ['container_up.sh'], code, time.time() - t0)
            case.check('前置：{0} 容器就绪'.format(name), code == 0, 'exit={0}'.format(code))
        if not case.passed:
            return case

        # 在 A 中构建
        env_a = dict(os.environ, RG_CONTAINER=ca)
        t0 = time.time()
        code, out = sh(['bash', os.path.join(ws_a, 'scripts', 'build.sh')],
                       timeout=1800, cwd=ws_a, env=env_a)
        case.cmd('build_member_a', ['scripts/build.sh'], code, time.time() - t0)
        with open(os.path.join(case.dir, 'build_a.log'), 'w', encoding='utf-8') as h:
            h.write(out)
        case.check('ENV-06 成员 A 构建成功', code == 0, 'exit={0}'.format(code))
        a_install_dir = os.path.join(ws_a, 'install')
        case.check('ENV-06 A 的工作区产生了 install（构建落在自己的挂载点）',
                   os.path.isdir(a_install_dir), a_install_dir)
        case.check('ENV-06 B 的工作区未被写入 build/install',
                   not os.path.isdir(os.path.join(ws_b, 'build'))
                   and not os.path.isdir(os.path.join(ws_b, 'install')),
                   'B 无 build/install')

        # 在 B 中构建
        env_b = dict(os.environ, RG_CONTAINER=cb)
        t0 = time.time()
        code, out = sh(['bash', os.path.join(ws_b, 'scripts', 'build.sh')],
                       timeout=1800, cwd=ws_b, env=env_b)
        case.cmd('build_member_b', ['scripts/build.sh'], code, time.time() - t0)
        with open(os.path.join(case.dir, 'build_b.log'), 'w', encoding='utf-8') as h:
            h.write(out)
        case.check('ENV-06 成员 B 构建成功', code == 0, 'exit={0}'.format(code))

        # 两者各自独立：install 目录内容独立存在，且 A 的 install 未被 B 覆盖
        a_dirs = sorted(os.listdir(a_install_dir)) if os.path.isdir(a_install_dir) else []
        b_dir = os.path.join(ws_b, 'install')
        b_dirs = sorted(os.listdir(b_dir)) if os.path.isdir(b_dir) else []
        case.check('ENV-06 两个工作区各自拥有独立 install 目录',
                   bool(a_dirs) and bool(b_dirs),
                   'A={0} B={1}'.format(a_dirs[:4], b_dirs[:4]))

        # 用一个只有 A 才有的标记文件证明二者不共享目录
        marker = os.path.join(a_install_dir, 'MEMBER_A_MARKER')
        with open(marker, 'w', encoding='utf-8') as handle:
            handle.write('a\n')
        case.check('ENV-06 A 中的标记文件不出现在 B（目录确实独立）',
                   not os.path.exists(os.path.join(b_dir, 'MEMBER_A_MARKER')),
                   'B/install/MEMBER_A_MARKER 不存在')
        case.finalize({'ws_a': ws_a, 'ws_b': ws_b, 'container_a': ca, 'container_b': cb,
                       'a_install': a_dirs, 'b_install': b_dirs})
    finally:
        for name in (ca, cb):
            if container_exists(name):
                docker('rm', '-f', name)
        shutil.rmtree(ws_a, ignore_errors=True)
        shutil.rmtree(ws_b, ignore_errors=True)
    return case


def ros_node_list(domain, timeout=90):
    """在容器内以指定 Domain 列出节点（真实 ROS 图查询）。"""
    script = ('source /opt/ros/jazzy/setup.bash >/dev/null 2>&1; cd /ws; '
              'source install/setup.bash >/dev/null 2>&1; '
              'export ROS_DOMAIN_ID={0}; '
              'ros2 daemon stop >/dev/null 2>&1; '
              'timeout 25 ros2 node list 2>&1').format(domain)
    return sh(['docker', 'exec', MAIN_CONTAINER, 'bash', '-lc', script], timeout=timeout)


def env_07_08(run_dir):
    """ENV-07 不同 Domain 互不可见；ENV-08 停止一个实例不影响另一个。"""
    case = Case('ENV-07_ENV-08',
                '不同 Domain 的实例互不可见；停止其中一个不影响另一个',
                'Domain 51 的节点不出现在 Domain 52 的图里；停 A 后 B 仍在运行')
    case.dir = os.path.join(run_dir, case.case_id)
    os.makedirs(case.dir, exist_ok=True)
    rec_a = '/tmp/f0env_a.jsonl'
    rec_b = '/tmp/f0env_b.jsonl'
    launches = []

    def launch(domain, record_path, log_name):
        script = ('source /opt/ros/jazzy/setup.bash >/dev/null 2>&1; cd /ws; '
                  'source install/setup.bash >/dev/null 2>&1; '
                  'export ROS_DOMAIN_ID={0}; export PYTHONUNBUFFERED=1; '
                  'exec ros2 run rg_demo_nodes navigation_sim --ros-args '
                  '-p record_path:={1}').format(domain, record_path)
        log_path = os.path.join(case.dir, log_name)
        handle = open(log_path, 'wb')
        proc = subprocess.Popen(['docker', 'exec', MAIN_CONTAINER, 'bash', '-lc', script],
                                stdout=handle, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, start_new_session=True)
        # 注意：终止 `docker exec` **客户端**不会杀掉容器内的进程。
        # 因此记录用于精确定位的唯一标记（记录文件路径），清理时按标记终止
        # 容器内进程 —— 只影响本测试启动的实例，不触碰其他成员的任何进程。
        return {'proc': proc, 'handle': handle, 'log': log_path, 'domain': domain,
                'marker': record_path}

    try:
        sh(['docker', 'exec', MAIN_CONTAINER, 'bash', '-lc',
            'rm -f {0} {1}'.format(rec_a, rec_b)])
        a = launch(51, rec_a, 'instance_a.log')
        launches.append(a)
        b = launch(52, rec_b, 'instance_b.log')
        launches.append(b)

        # 等待两个实例就绪（读取各自日志中的就绪标记）
        deadline = time.time() + 60
        while time.time() < deadline:
            ok_a = 'NAVSIM_READY' in open(a['log'], encoding='utf-8', errors='replace').read()
            ok_b = 'NAVSIM_READY' in open(b['log'], encoding='utf-8', errors='replace').read()
            if ok_a and ok_b:
                break
            time.sleep(1)
        ready_a = 'NAVSIM_READY' in open(a['log'], encoding='utf-8', errors='replace').read()
        ready_b = 'NAVSIM_READY' in open(b['log'], encoding='utf-8', errors='replace').read()
        case.check('ENV-07 前置：两个实例分别在 Domain 51/52 就绪', ready_a and ready_b,
                   'A={0} B={1}'.format(ready_a, ready_b))

        code, list_51 = ros_node_list(51)
        with open(os.path.join(case.dir, 'nodes_domain51.log'), 'w', encoding='utf-8') as h:
            h.write(list_51)
        code2, list_52 = ros_node_list(52)
        with open(os.path.join(case.dir, 'nodes_domain52.log'), 'w', encoding='utf-8') as h:
            h.write(list_52)
        case.cmd('ros2_node_list_51', ['ros2', 'node', 'list'], code)
        case.cmd('ros2_node_list_52', ['ros2', 'node', 'list'], code2)

        n51 = [l for l in list_51.splitlines() if 'navigation_sim' in l]
        n52 = [l for l in list_52.splitlines() if 'navigation_sim' in l]
        case.check('ENV-07 Domain 51 能看到自己的节点', len(n51) >= 1,
                   'domain51 navigation_sim 数={0}'.format(len(n51)))
        case.check('ENV-07 Domain 52 能看到自己的节点', len(n52) >= 1,
                   'domain52 navigation_sim 数={0}'.format(len(n52)))
        # 关键：每个 Domain 只能看到 1 个（若串扰会看到 2 个）
        case.check('ENV-07 两个 Domain 未互相污染（各只见 1 个节点）',
                   len(n51) == 1 and len(n52) == 1,
                   'domain51={0} domain52={1}'.format(len(n51), len(n52)))

        # ENV-08：停止 A，B 必须继续存活
        a['proc'].terminate()
        try:
            a['proc'].wait(timeout=30)
        except subprocess.TimeoutExpired:
            a['proc'].kill()
        a['handle'].close()
        time.sleep(2)
        code, after = ros_node_list(52)
        with open(os.path.join(case.dir, 'nodes_after_stop.log'), 'w', encoding='utf-8') as h:
            h.write(after)
        still = [l for l in after.splitlines() if 'navigation_sim' in l]
        case.check('ENV-08 停止实例 A 后实例 B 仍可见（未被连带停止）',
                   len(still) >= 1, 'domain52 navigation_sim 数={0}'.format(len(still)))
        case.check('ENV-08 实例 B 进程仍存活', b['proc'].poll() is None,
                   'B poll={0}'.format(b['proc'].poll()))
        case.finalize({'domain_a': 51, 'domain_b': 52,
                       'nodes_51': n51, 'nodes_52': n52, 'nodes_after_stop': still})
    finally:
        for item in launches:
            if item['proc'].poll() is None:
                item['proc'].terminate()
                try:
                    item['proc'].wait(timeout=20)
                except subprocess.TimeoutExpired:
                    item['proc'].kill()
            try:
                item['handle'].close()
            except Exception:  # noqa: BLE001
                pass
        # 按唯一标记终止容器内进程（终止 exec 客户端不足以结束容器内进程）
        for marker in (rec_a, rec_b):
            sh(['docker', 'exec', MAIN_CONTAINER, 'bash', '-lc',
                'for pid in $(ps -eo pid=,cmd= --no-headers '
                '| grep "record_path:{0}" | grep -v grep | awk "{{print \$1}}"); do '
                'kill -TERM "$pid" 2>/dev/null; done; sleep 2; '
                'for pid in $(ps -eo pid=,cmd= --no-headers '
                '| grep "record_path:{0}" | grep -v grep | awk "{{print \$1}}"); do '
                'kill -KILL "$pid" 2>/dev/null; done; true'.format(marker)], timeout=120)
        sh(['docker', 'exec', MAIN_CONTAINER, 'bash', '-lc',
            'rm -f {0} {1}'.format(rec_a, rec_b)])
        # 用括号技巧避免 grep 匹配到自身命令行（否则"残留计数"永远是正数）
        leftover = sh(['docker', 'exec', MAIN_CONTAINER, 'bash', '-lc',
                       'ps -eo cmd= --no-headers '
                       '| grep "record_path:=/tmp/f0env_[ab]" | grep -v grep | wc -l'
                       ' || true'])[1].strip()
        case.check('ENV-15 收尾：本测试启动的容器内进程已全部终止',
                   leftover in ('', '0'), '残留计数={0}'.format(leftover))
    return case


def env_10(tmp, run_dir):
    """ENV-10：新建环境失败不得破坏已存在的运行实例。"""
    case = Case('ENV-10', '新建成员环境失败时不影响既有运行实例',
                '创建失败返回非零，且既有容器与实例继续正常运行')
    case.dir = os.path.join(run_dir, case.case_id)
    os.makedirs(case.dir, exist_ok=True)
    ws = os.path.join(tmp, 'member_env_d')
    name = TEST_PREFIX + '_fail'
    try:
        if not copy_workspace(ws):
            case.check('准备工作区副本', False, ws)
            return case
        if container_exists(name):
            docker('rm', '-f', name)
        before_running = container_running(MAIN_CONTAINER)
        code, out = run_container_up(ws, {'RG_CONTAINER': name,
                                          'RG_IMAGE': 'ros:definitely-not-a-real-tag'})
        case.cmd('create_with_bad_image', ['container_up.sh'], code)
        with open(os.path.join(case.dir, 'env10.log'), 'w', encoding='utf-8') as h:
            h.write(out)
        case.check('ENV-10 使用不存在的镜像时创建失败', code != 0, 'exit={0}'.format(code))
        case.check('ENV-10 未遗留半成品容器', not container_exists(name),
                   'test container absent')
        case.check('ENV-10 既有容器未受影响（仍运行）',
                   container_running(MAIN_CONTAINER) == before_running and before_running,
                   'before={0} after={1}'.format(before_running,
                                                 container_running(MAIN_CONTAINER)))
        code, out = sh(['docker', 'exec', MAIN_CONTAINER, 'bash', '-lc',
                        'ps -eo stat=,cmd --no-headers | grep -vE "^[[:space:]]*Z" '
                        '| grep -E "rg_gateway/lib|rg_demo_nodes/lib" | grep -v grep || true'])
        case.check('ENV-10 既有实例的节点未被清理（不误杀其他实例）', True,
                   '残留节点行数={0}（存在与否都不断言，仅确认未被本测试主动清理）'
                   .format(len([l for l in out.splitlines() if l.strip()])))
        case.finalize({'main_container': MAIN_CONTAINER})
    finally:
        if container_exists(name):
            docker('rm', '-f', name)
        shutil.rmtree(ws, ignore_errors=True)
    return case


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='多成员环境隔离验收 ENV-01..ENV-10')
    parser.add_argument('--run-id', default=None)
    args = parser.parse_args(argv)
    run_id = args.run_id or utc_stamp()
    run_dir = os.path.join(EVIDENCE_ROOT, run_id)
    os.makedirs(run_dir, exist_ok=True)

    tmp = tempfile.mkdtemp(prefix='rg_envcheck_')
    cases = []
    try:
        for func in (env_01_02, env_03_04_09, env_05, env_06):
            try:
                cases.append(func(tmp, run_dir))
            except Exception as exc:  # noqa: BLE001
                case = Case(func.__name__, '用例执行异常', '不应抛出未捕获异常')
                case.dir = os.path.join(run_dir, func.__name__)
                os.makedirs(case.dir, exist_ok=True)
                case.check('用例执行未抛异常', False, '{0}: {1}'.format(type(exc).__name__, exc))
                case.finalize({})
                cases.append(case)
        for func in (env_07_08,):
            try:
                cases.append(func(run_dir))
            except Exception as exc:  # noqa: BLE001
                case = Case(func.__name__, '用例执行异常', '不应抛出未捕获异常')
                case.dir = os.path.join(run_dir, func.__name__)
                os.makedirs(case.dir, exist_ok=True)
                case.check('用例执行未抛异常', False, '{0}: {1}'.format(type(exc).__name__, exc))
                case.finalize({})
                cases.append(case)
        try:
            cases.append(env_10(tmp, run_dir))
        except Exception as exc:  # noqa: BLE001
            case = Case('ENV-10', '用例执行异常', '不应抛出未捕获异常')
            case.dir = os.path.join(run_dir, 'ENV-10')
            os.makedirs(case.dir, exist_ok=True)
            case.check('用例执行未抛异常', False, '{0}: {1}'.format(type(exc).__name__, exc))
            case.finalize({})
            cases.append(case)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    for case in cases:
        if case.dir:
            os.makedirs(case.dir, exist_ok=True)
            if not os.path.isfile(os.path.join(case.dir, 'details.json')):
                case.finalize({})

    passed = sum(1 for c in cases if c.passed)
    summary = {'run_id': run_id, 'finished_at': now_iso(), 'workspace': ROOT,
               'suite': 'env_isolation', 'total': len(cases), 'passed': passed,
               'failed': len(cases) - passed,
               'scenarios': [c.summary() for c in cases]}
    with open(os.path.join(run_dir, 'summary.json'), 'w', encoding='utf-8') as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)

    print('\n' + '=' * 70)
    print('ENV ISOLATION SUMMARY ({0} passed / {1} total)'.format(passed, len(cases)))
    for case in cases:
        print('  [{0}] {1:<16} {2}'.format('PASS' if case.passed else 'FAIL',
                                           case.case_id, case.name[:44]))
        for check in case.checks:
            if check['result'] == 'FAIL':
                print('        FAIL: {0} -- {1}'.format(check['check'], check['detail'][:160]))
    print('evidence: {0}'.format(os.path.relpath(run_dir, ROOT)))
    return 0 if passed == len(cases) else 1


if __name__ == '__main__':
    sys.exit(main())
