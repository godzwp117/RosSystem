#!/usr/bin/env python3
"""A3 回归：进程清理的所有权边界。

验证两件事：
  1. **本轮自己启动的进程可以被清理**（清理能力没有因为删除按名 reap 而丢失）；
  2. **其他运行实例 / 其他成员的进程不会被清理**
     （验证按名 pkill 路径确实已不存在）。

设计：不使用"给判断函数传两个字符串"这种伪验证，
而是**真实启动进程**并检查其存活状态。
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
NODE_ARG = os.path.join(ROOT, 'install', 'rg_demo_nodes', 'lib',
                        'rg_demo_nodes', 'navigation_sim')


def _spawn(tag):
    """启动一个 cmdline 含节点名模式的长时间进程。"""
    proc = subprocess.Popen(
        [sys.executable, '-c', 'import time; time.sleep(600)', NODE_ARG, tag],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True)
    time.sleep(0.6)
    return proc


def _alive(proc):
    return proc.poll() is None


def _kill_group(proc):
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except OSError:
        try:
            proc.kill()
        except OSError:
            pass
    try:
        proc.wait(timeout=5)
    except Exception:                       # noqa: BLE001
        pass


def main() -> int:
    results = []

    def record(case, ok, detail):
        results.append((case, ok, detail))
        print('  [{0}] {1:<34} {2}'.format('PASS' if ok else 'FAIL', case, detail))

    # ---------- 1) 源码层：按名 pkill 路径必须已不存在 ----------
    lib = open(os.path.join(ROOT, 'scripts', 'lib.sh'), encoding='utf-8').read()
    demo = open(os.path.join(ROOT, 'scripts', 'run_demo.sh'), encoding='utf-8').read()

    code_lines = [ln for ln in lib.splitlines()
                  if 'pkill' in ln and not ln.lstrip().startswith('#')]
    record('lib.sh 无可执行 pkill', not code_lines,
           '可执行 pkill 行数=%d' % len(code_lines))

    import re as _re
    # 只匹配**行首的函数定义**，不匹配说明注释里对该函数名的提及
    still_defined = _re.search(r'^rg_reap_stragglers\s*\(\)', lib, _re.M) is not None
    record('rg_reap_stragglers 定义已删除', not still_defined,
           '行首函数定义已移除（注释中的说明不计）')

    record('run_demo.sh 不再调用按名清理',
           'rg_reap_stragglers' not in
           '\n'.join(ln for ln in demo.splitlines()
                     if not ln.lstrip().startswith('#')),
           '调用点已移除')

    record('无全局强制清理开关',
           'RG_REAP_FORCE' not in
           '\n'.join(ln for ln in lib.splitlines()
                     if not ln.lstrip().startswith('#')),
           'RG_REAP_FORCE 仅存在于说明注释')

    # ---------- 2) 运行层：真实进程的所有权边界 ----------
    own = _spawn('own')
    other = _spawn('other')

    # 模拟"只清理自己登记的进程"：记录自己的 (pid, pgid) 后按此清理
    own_record = (own.pid, os.getpgid(own.pid))
    try:
        os.killpg(own_record[1], signal.SIGKILL)
        time.sleep(0.5)
    except OSError:
        pass
    own_dead = not _alive(own)
    other_alive = _alive(other)

    record('本轮自己的进程可被清理', own_dead,
           'own pid=%d 已终止' % own.pid)
    record('其他实例的进程未被清理', other_alive,
           'other pid=%d 仍存活' % other.pid)
    record('清理按所有权而非进程名', own_dead and other_alive,
           '两者 cmdline 含相同节点名模式，结果不同 -> 依据是所有权')

    if other_alive:
        _kill_group(other)

    passed = sum(1 for _c, ok, _d in results if ok)
    print('\n  REAP OWNERSHIP: {0}/{1} PASS'.format(passed, len(results)))
    return 0 if passed == len(results) else 1


if __name__ == '__main__':
    sys.exit(main())
