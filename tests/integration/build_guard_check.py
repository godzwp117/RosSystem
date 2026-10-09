#!/usr/bin/env python3
"""build_guard_check.py -- 构建保护检查（任务 B3），必须**在宿主机**上运行。

为什么单独一个脚本
------------------
B3 的对象是宿主侧的 `scripts/build.sh`（它通过 docker exec 操作容器），所以用例必须在
宿主机执行；而 B2/B4 的审计与超时用例必须与 ROS 图在同一个容器 PID 命名空间里执行，
两者环境天然不同，拆开比强塞进一个脚本更可靠。

覆盖：
  R6 空闲时构建            -> exit 0，输出 BUILD RESULT: PASS
  R5 系统运行时构建        -> exit 4，明确拒绝，实例节点 PID 与数量不变

节点存活一律以**容器内** ps 为准（宿主 PID 命名空间看不到容器进程）。

用法：python3 tests/integration/build_guard_check.py
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
CONTAINER = os.environ.get('RG_CONTAINER', 'rg_jazzy')
LAUNCHER = '/tmp/rg_build_guard_launcher.py'

LAUNCHER_SRC = '''import os, signal, sys
signal.signal(signal.SIGINT, signal.SIG_DFL)
signal.signal(signal.SIGQUIT, signal.SIG_DFL)
try:
    os.setsid()
except OSError:
    pass
os.chdir(sys.argv[1])
os.execv("/bin/bash", ["bash", "scripts/start_system.sh"])
'''


def utc_stamp():
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def now_iso():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def sh(argv, timeout=300, cwd=None):
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, cwd=cwd)
    return proc.returncode, (proc.stdout or '') + (proc.stderr or '')


def container_nodes():
    """容器内三个常驻节点的非僵尸进程 cmdline。"""
    script = ("ps -eo stat=,cmd= --no-headers | grep -vE '^[[:space:]]*Z' "
              "| grep -E 'rg_gateway/lib/rg_gateway/security_gateway"
              "|rg_demo_nodes/lib/rg_demo_nodes/(navigation_sim|operator_node)' | grep -v grep")
    rc, out = sh(['docker', 'exec', CONTAINER, 'bash', '-lc', script])
    return [line.strip() for line in out.splitlines() if line.strip()]


class Case:
    def __init__(self, case_id, name):
        self.case_id = case_id
        self.name = name
        self.checks = []
        self.commands = []
        self.dir = None
        self.exit_code = None
        self.navsim_goals = 0

    def check(self, name, ok, detail):
        if isinstance(detail, (list, tuple)):
            detail = '; '.join(str(d) for d in detail) or '(empty)'
        self.checks.append({'check': name, 'result': 'PASS' if ok else 'FAIL', 'detail': str(detail)[:900]})
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
            'suite': 'build_guard',
            'description': self.name,
            'result': 'PASS' if self.passed else 'FAIL',
            'started_at': now_iso(),
            'evidence_dir': os.path.relpath(self.dir, ROOT) if self.dir else '',
            'navsim_goal_count': self.navsim_goals,
            'decision_sequence': [],
            'execution_status_codes': [],
            'reject_log_lines': 0,
            'planner_results': [],
            'planner_exit_codes': [self.exit_code] if self.exit_code is not None else [],
            'checks': self.checks,
            'commands': self.commands,
            'expectations': {'description': self.name},
        }


def case_r6(run_dir):
    case = Case('R6', '空闲时（无运行中实例）构建必须成功')
    case.dir = os.path.join(run_dir, 'R6')
    os.makedirs(case.dir, exist_ok=True)
    shutil.rmtree(os.path.join(ROOT, 'logs', 'start_system'), ignore_errors=True)
    baseline = container_nodes()
    case.check('前置条件：当前无运行中的常驻节点', not baseline, '容器内节点数={0}'.format(len(baseline)))
    log = os.path.join(case.dir, 'build_idle.log')
    t0 = time.time()
    rc, out = sh(['bash', 'scripts/build.sh'], timeout=1200, cwd=ROOT)
    case.exit_code = rc
    with open(log, 'w', encoding='utf-8') as handle:
        handle.write(out)
    case.commands.append({'step': 'build', 'argv': ['bash', 'scripts/build.sh'], 'exit_code': rc,
                          'duration_sec': round(time.time() - t0, 3)})
    case.check('构建成功（exit 0）', rc == 0, 'exit={0}'.format(rc))
    case.check('输出 BUILD RESULT: PASS', 'BUILD RESULT: PASS' in out, 'BUILD RESULT: PASS')
    case.check('构建前状态检查放行', '未发现运行中的受管理实例' in out, '未发现运行中的受管理实例')
    return case


def case_r5(run_dir):
    case = Case('R5', '系统运行时构建被安全拒绝且实例不受影响')
    case.dir = os.path.join(run_dir, 'R5')
    os.makedirs(case.dir, exist_ok=True)
    with open(LAUNCHER, 'w', encoding='utf-8') as handle:
        handle.write(LAUNCHER_SRC)
    instance_log = os.path.join(case.dir, 'instance.log')
    handle = open(instance_log, 'wb')
    proc = subprocess.Popen(['python3', LAUNCHER, ROOT], stdout=handle,
                            stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    try:
        deadline = time.time() + 180
        ready = False
        while time.time() < deadline:
            if '前台运行中' in open(instance_log, 'rb').read().decode('utf-8', 'replace'):
                ready = True
                break
            if proc.poll() is not None:
                break
            time.sleep(1)
        case.check('前置条件：受管理实例已启动并就绪', ready, 'start_system.sh 输出就绪横幅')
        if not ready:
            return case
        before = container_nodes()
        case.check('前置条件：实例三个常驻节点存活', len(before) == 3,
                   '容器内节点数={0}'.format(len(before)))

        log = os.path.join(case.dir, 'build_while_running.log')
        t0 = time.time()
        rc, out = sh(['bash', 'scripts/build.sh'], timeout=600, cwd=ROOT)
        case.exit_code = rc
        with open(log, 'w', encoding='utf-8') as h:
            h.write(out)
        case.commands.append({'step': 'build', 'argv': ['bash', 'scripts/build.sh'], 'exit_code': rc,
                              'duration_sec': round(time.time() - t0, 3)})
        case.check('系统运行时构建被拒绝（exit 4）', rc == 4, 'exit={0}'.format(rc))
        case.check('给出明确拒绝原因与处置建议',
                   '构建被拒绝' in out and '正在运行' in out and '不会主动清理' in out,
                   [l for l in out.splitlines() if '拒绝' in l or '正在运行' in l][:2])
        case.check('明确声明未执行 colcon build', '未执行 colcon build' in out, '未执行 colcon build')
        case.check('未出现 pkill 副作用输出', 'killed leftover node' not in out, '无 reap 输出')
        after = container_nodes()
        case.check('被拒绝后实例仍在运行（节点数不变）', len(after) == len(before),
                   'before={0} after={1}'.format(len(before), len(after)))
        case.check('被拒绝后节点 PID 完全一致（未被打断）',
                   sorted(after) == sorted(before), 'PID 集合一致' if sorted(after) == sorted(before) else 'PID 变化')
    finally:
        if proc.poll() is None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGINT)
            except OSError:
                proc.terminate()
            try:
                proc.wait(timeout=90)
            except subprocess.TimeoutExpired:
                proc.kill()
        handle.close()
        # 兜底：清掉可能残留的实例（仅本脚本自己起的）
        sh(['bash', '-lc',
            'for p in $(pgrep -f "^bash \\./scripts/start_system\\.sh$" 2>/dev/null); do kill -TERM $p; done; true'],
           cwd=ROOT, timeout=120)
    return case


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='构建保护检查（宿主机执行）')
    parser.add_argument('--run-id', default=None)
    args = parser.parse_args(argv)
    run_id = args.run_id or utc_stamp()
    run_dir = os.path.join(EVIDENCE_ROOT, run_id)
    os.makedirs(run_dir, exist_ok=True)

    # 先跑空闲构建（R6），再跑运行中拒绝（R5）——顺序不能反
    results = [case_r6(run_dir), case_r5(run_dir)]

    for case in results:
        print('=== {0}: {1} ==='.format(case.case_id, case.name))
        for check in case.checks:
            print('  [{0}] {1} -- {2}'.format(check['result'], check['check'], check['detail'][:200]))

    passed = sum(1 for c in results if c.passed)
    summary = {
        'run_id': run_id,
        'finished_at': now_iso(),
        'workspace': ROOT,
        'suite': 'build_guard',
        'total': len(results),
        'passed': passed,
        'failed': len(results) - passed,
        'scenarios': [c.summary() for c in results],
    }
    with open(os.path.join(run_dir, 'summary.json'), 'w', encoding='utf-8') as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)
    print('BUILD GUARD SUMMARY ({0} passed / {1} total)'.format(passed, len(results)))
    print('evidence: {0}'.format(os.path.relpath(run_dir, ROOT)))
    return 0 if passed == len(results) else 1


if __name__ == '__main__':
    sys.exit(main())
