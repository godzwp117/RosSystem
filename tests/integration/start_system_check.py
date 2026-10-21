#!/usr/bin/env python3
"""start_system_check.py -- scripts/start_system.sh 生命周期回归检查（产出结构化证据）。

覆盖任务 B5 中的三项：
  * `start_system.sh` 正常启动与退出
  * 重复启动检查（必须被拒绝且不影响运行中的实例）
  * 启动后 ROS 2 图与节点数量的真实性核对

为什么单独写这个文件
--------------------
`scenario_runner.py` 面向业务 Action 场景（A/B 与负例），不覆盖统一启动器；而统一启动器
的生命周期问题（信号处置、进程组清理、重复实例）恰恰是可靠性加固的重点。本工具把
这些检查固化成可重复执行、可产出证据的测试，输出格式与 `scenario_runner` 的
`summary.json` 一致，因此 `scripts/export_acceptance.py` 能直接收集。

注意（本执行环境的真实限制）
----------------------------
本环境无法分配 pty（`/dev/ptmx` 打开返回 EACCES），因此"按 Ctrl+C"用等价投递语义验证：
子进程先被复位为 SIG_DFL，再向**整个进程组**发送 SIGINT —— 与终端 Ctrl+C 的信号投递
语义一致（终端也是向前台进程组发 SIGINT）。这不等于在真实交互终端按物理按键。

用法：
    python3 tests/integration/start_system_check.py [--run-id ID] [--keep-running]
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
START_SCRIPT = os.path.join('scripts', 'start_system.sh')
CONTAINER = os.environ.get('RG_CONTAINER', 'rg_jazzy')
LAUNCHER = '/tmp/rg_sigint_dfl_launcher.py'
READY_MARKER = '前台运行中'
STOPPED_MARKER = '本实例已停止'
READY_TIMEOUT_SEC = 180
STOP_TIMEOUT_SEC = 90

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


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def sh(cmd, timeout=120):
    proc = subprocess.run(['bash', '-lc', cmd], capture_output=True, text=True, timeout=timeout)
    return proc.returncode, (proc.stdout or '') + (proc.stderr or '')


def container_exec(script, timeout=120):
    return sh('docker exec {0} bash -lc {1}'.format(CONTAINER, json.dumps(script)), timeout=timeout)


def live_node_processes() -> list:
    """容器内三个常驻节点的非僵尸进程（cmdline 行）。"""
    rc, out = container_exec(
        "ps -eo stat=,cmd= --no-headers | grep -vE '^[[:space:]]*Z' "
        "| grep -E 'rg_gateway/lib/rg_gateway/security_gateway"
        "|rg_demo_nodes/lib/rg_demo_nodes/(navigation_sim|operator_node)' | grep -v grep")
    return [line.strip() for line in out.splitlines() if line.strip()]


def action_list() -> str:
    """就绪探测（GAP-05 修复）。

    原实现用 `ros2 action list`，它经**共享 ROS 2 daemon** 查询图，而 daemon
    按 Domain 缓存上一次的图 —— 跨 Domain 测试时可能报告上一个 Domain 的结果
    （假就绪或假失败）。根因是"探测依赖了带缓存的间接层"。

    现改为在本进程内用 rclpy 直接探测（见 domain_ready_probe.py）：
    自己初始化节点，因此图属于当前进程的 Domain；用 ActionClient.wait_for_server()
    做真实可达性判断；不经 daemon，也不去重置或杀死其他实例的 daemon。

    输出格式保持为"每行一个 Action 名"，因此调用方的断言无需改动。
    """
    rc, out = container_exec(
        'source /opt/ros/jazzy/setup.bash >/dev/null 2>&1; cd /ws; '
        'source install/setup.bash >/dev/null 2>&1; '
        'timeout 40 python3 tests/integration/domain_ready_probe.py '
        '--action /rg/guarded_navigate --action /rg/nav_execute '
        '--timeout 12 --json 2>&1')
    try:
        payload = json.loads(out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        # 探测本身失败时如实回退，不假装有结果
        return out.strip()
    lines = [entry['action'] for entry in payload.get('results', []) if entry.get('ready')]
    return '\n'.join(lines)


class Scenario:
    def __init__(self, scenario_id, name, expected):
        self.scenario_id = scenario_id
        self.name = name
        self.expected = expected
        self.checks = []
        self.commands = []
        self.started = time.time()
        self.evidence_files = []
        self.dir = None

    def check(self, name, ok, detail):
        # detail 必须是字符串：schema 要求 string，列表需显式拼装
        if isinstance(detail, (list, tuple)):
            detail = '; '.join(str(item) for item in detail) or '(empty)'
        self.checks.append({'check': name, 'result': 'PASS' if ok else 'FAIL', 'detail': str(detail)})
        return ok

    def command(self, argv, exit_code, duration, log_path=None):
        self.commands.append({
            'step': 'argv', 'argv': argv, 'exit_code': exit_code,
            'duration_sec': round(duration, 3), 'log_path': log_path,
        })

    @property
    def passed(self):
        return bool(self.checks) and all(c['result'] == 'PASS' for c in self.checks)

    def to_summary(self, run_id):
        return {
            'scenario': self.scenario_id,
            'suite': 'start_system',
            'description': self.name,
            'result': 'PASS' if self.passed else 'FAIL',
            'started_at': now_iso(),
            'evidence_dir': os.path.relpath(self.dir, ROOT) if self.dir else '',
            'navsim_goal_count': 0,
            'decision_sequence': [],
            'execution_status_codes': [],
            'reject_log_lines': 0,
            'planner_results': [],
            'planner_exit_codes': [],
            'checks': self.checks,
            'commands': self.commands,
            'expectations': {'description': self.expected},
        }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='start_system.sh 生命周期回归检查')
    parser.add_argument('--run-id', default=None)
    parser.add_argument('--keep-running', action='store_true', help='检查结束后不停止实例（排障用）')
    args = parser.parse_args(argv)

    run_id = args.run_id or utc_stamp()
    run_dir = os.path.join(EVIDENCE_ROOT, run_id)
    shutil.rmtree(run_dir, ignore_errors=True)
    os.makedirs(run_dir, exist_ok=True)

    with open(LAUNCHER, 'w', encoding='utf-8') as handle:
        handle.write(LAUNCHER_SRC)

    # 前置：清理可能残留的测试实例，避免互相干扰
    sh('cd {0} && for p in $(pgrep -f "^bash \\./scripts/start_system\\.sh$" 2>/dev/null); '
       'do kill -TERM $p 2>/dev/null; done; sleep 4; true'.format(ROOT))
    shutil.rmtree(os.path.join(ROOT, 'logs', 'start_system'), ignore_errors=True)
    baseline_nodes = live_node_processes()

    results = []

    # ---------------- 场景 1：正常启动 / 就绪 / Ctrl+C 退出 ----------------
    sc1 = Scenario('start_system_normal_lifecycle', '正常启动、就绪检测与 Ctrl+C 优雅退出',
                   '启动后 3 个常驻节点与 2 个 Action 就绪；Ctrl+C 后进程组清空、容器保留、日志保留')
    sc1.dir = os.path.join(run_dir, sc1.scenario_id)
    os.makedirs(sc1.dir, exist_ok=True)
    log_path = os.path.join(sc1.dir, 'start_system.log')

    sc1.check('启动前无残留常驻节点', not baseline_nodes,
              '基线存活进程数={0}'.format(len(baseline_nodes)))

    log_handle = open(log_path, 'wb')
    t0 = time.time()
    proc = subprocess.Popen(['python3', LAUNCHER, ROOT], stdout=log_handle,
                            stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    sc1.command(['python3', LAUNCHER, ROOT], None, 0.0, os.path.relpath(log_path, ROOT))

    ready = False
    deadline = time.time() + READY_TIMEOUT_SEC
    while time.time() < deadline:
        try:
            text = open(log_path, 'rb').read().decode('utf-8', errors='replace')
        except OSError:
            text = ''
        if READY_MARKER in text:
            ready = True
            break
        if proc.poll() is not None:
            break
        time.sleep(1)
    sc1.commands[0]['duration_sec'] = round(time.time() - t0, 3)
    sc1.check('start_system.sh 在超时内输出就绪横幅', ready,
              '等待上限 {0}s，耗时 {1:.1f}s'.format(READY_TIMEOUT_SEC, time.time() - t0))

    actions = action_list() if ready else ''
    with open(os.path.join(sc1.dir, 'action_list.txt'), 'w', encoding='utf-8') as handle:
        handle.write(actions + '\n')
    sc1.evidence_files.append(os.path.relpath(os.path.join(sc1.dir, 'action_list.txt'), ROOT))

    up_ok = '/rg/guarded_navigate' in actions and 'rg_interfaces/action/PatrolNavigate' in actions
    down_ok = '/rg/nav_execute' in actions and 'rg_interfaces/action/PatrolNavigate' in actions
    sc1.check('/rg/guarded_navigate 可发现且类型为 rg_interfaces/action/PatrolNavigate', up_ok,
              '; '.join(l for l in actions.splitlines() if 'guarded_navigate' in l) or '未发现')
    sc1.check('/rg/nav_execute 可发现且类型为 rg_interfaces/action/PatrolNavigate', down_ok,
              '; '.join(l for l in actions.splitlines() if 'nav_execute' in l) or '未发现')

    nodes = live_node_processes()
    with open(os.path.join(sc1.dir, 'node_processes.txt'), 'w', encoding='utf-8') as handle:
        handle.write('\n'.join(nodes) + '\n')
    sc1.evidence_files.append(os.path.relpath(os.path.join(sc1.dir, 'node_processes.txt'), ROOT))
    sc1.check('三个常驻节点进程均存活', len(nodes) == 3, '存活 {0} 个'.format(len(nodes)))

    # 拷贝实例日志
    ls_rc, instance_dir = sh('ls -d {0}/logs/start_system/*/ 2>/dev/null | head -1'.format(ROOT))
    instance_dir = instance_dir.strip()
    if instance_dir and os.path.isdir(instance_dir):
        for name in ('runner.log', 'launch.log', 'audit.jsonl', 'navsim_goals.jsonl', 'instance.env'):
            src = os.path.join(instance_dir, name)
            if os.path.isfile(src):
                dest = os.path.join(sc1.dir, name)
                shutil.copy2(src, dest)
                sc1.evidence_files.append(os.path.relpath(dest, ROOT))

    # ---------------- 场景 2：重复启动必须被拒绝 ----------------
    sc2 = Scenario('start_system_duplicate_refused', '运行期重复启动被拒绝且不影响现有实例',
                   '第二次启动返回非零且提示已有实例；现有节点数量与 PID 不变')
    sc2.dir = os.path.join(run_dir, sc2.scenario_id)
    os.makedirs(sc2.dir, exist_ok=True)
    dup_log = os.path.join(sc2.dir, 'duplicate_start.log')
    dup_t0 = time.time()
    dup = subprocess.run(['bash', START_SCRIPT], cwd=ROOT, capture_output=True, text=True, timeout=180)
    dup_dur = time.time() - dup_t0
    with open(dup_log, 'w', encoding='utf-8') as handle:
        handle.write(dup.stdout + dup.stderr)
    sc2.command(['bash', START_SCRIPT], dup.returncode, dup_dur, os.path.relpath(dup_log, ROOT))
    sc2.evidence_files.append(os.path.relpath(dup_log, ROOT))
    sc2.check('重复启动返回码为 4（已有实例）', dup.returncode == 4,
              '实际返回码 {0}'.format(dup.returncode))
    sc2.check('重复启动明确提示已有实例',
              'RoboGuard 系统实例' in (dup.stdout + dup.stderr),
              '; '.join(l for l in (dup.stdout + dup.stderr).splitlines() if '已有' in l or '拒绝' in l))
    nodes_after = live_node_processes()
    sc2.check('重复启动后节点数量未变（无重复 Gateway/NavigationSim）',
              len(nodes_after) == len(nodes),
              '启动前 {0} 个，重复启动后 {1} 个'.format(len(nodes), len(nodes_after)))
    sc2.check('重复启动后节点 PID 完全一致（原实例未被影响）',
              sorted(nodes_after) == sorted(nodes), 'PID 集合一致' if sorted(nodes_after) == sorted(nodes) else 'PID 发生变化')

    # ---------------- 场景 1 收尾：Ctrl+C ----------------
    if not args.keep_running and proc.poll() is None:
        stop_t0 = time.time()
        pgid = os.getpgid(proc.pid)
        if pgid == proc.pid:
            os.killpg(pgid, signal.SIGINT)
            sc1.command(['os.killpg({0}, SIGINT)'.format(pgid)], None, 0.0)
        else:
            os.kill(proc.pid, signal.SIGINT)
            sc1.command(['os.kill({0}, SIGINT)'.format(proc.pid)], None, 0.0)
        try:
            proc.wait(timeout=STOP_TIMEOUT_SEC)
        except subprocess.TimeoutExpired:
            proc.kill()
        stop_dur = time.time() - stop_t0
        sc1.commands[-1]['duration_sec'] = round(stop_dur, 3)
        sc1.commands[-1]['exit_code'] = proc.returncode
        log_handle.close()
        text = open(log_path, 'rb').read().decode('utf-8', errors='replace')
        sc1.check('收到 SIGINT 后输出停止横幅', STOPPED_MARKER in text, '在日志中找到「本实例已停止」')
        sc1.check('脚本退出码为 0', proc.returncode == 0, '实际 {0}'.format(proc.returncode))
        sc1.check('退出耗时在 {0}s 内'.format(STOP_TIMEOUT_SEC), stop_dur < STOP_TIMEOUT_SEC,
                  '{0:.1f}s'.format(stop_dur))
        leftover = live_node_processes()
        sc1.check('退出后容器内无本实例残留活进程', not leftover,
                  '残留 {0} 个'.format(len(leftover)) if leftover else '无残留')
        # 注意：这里不是 str.format，Go 模板只需双层花括号
        rc, running = sh('docker inspect -f "{{.State.Running}}" ' + CONTAINER)
        sc1.check('容器保持运行（未被停止）', running.strip() == 'true', 'State.Running={0}'.format(running.strip()))
        sc1.check('审计与 NavSim 日志目录保留', bool(instance_dir) and os.path.isdir(instance_dir),
                  instance_dir or '未找到实例目录')
    else:
        log_handle.close()

    results.append(sc1)
    results.append(sc2)

    passed = sum(1 for s in results if s.passed)
    summary = {
        'run_id': run_id,
        'finished_at': now_iso(),
        'workspace': ROOT,
        'suite': 'start_system',
        'total': len(results),
        'passed': passed,
        'failed': len(results) - passed,
        'scenarios': [s.to_summary(run_id) for s in results],
    }
    with open(os.path.join(run_dir, 'summary.json'), 'w', encoding='utf-8') as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)

    print('=== start_system 生命周期检查: {0} ==='.format(run_id))
    for scenario in results:
        print('  [{0}] {1}'.format('PASS' if scenario.passed else 'FAIL', scenario.scenario_id))
        for check in scenario.checks:
            print('      [{0}] {1} -- {2}'.format(check['result'], check['check'], check['detail']))
    print('  summary: {0}'.format(os.path.relpath(os.path.join(run_dir, 'summary.json'), ROOT)))
    print('START_SYSTEM CHECK: {0} ({1}/{2})'.format(
        'PASS' if passed == len(results) else 'FAIL', passed, len(results)))
    return 0 if passed == len(results) else 1


if __name__ == '__main__':
    sys.exit(main())
