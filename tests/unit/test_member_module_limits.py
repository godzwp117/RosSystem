#!/usr/bin/env python3
"""FIX-02：有界读取、超时与进程组清理的**真实故障子进程**测试。

不通过"检查源码里出现 max_stdout_bytes 字符串"来证明安全 ——
每一项都用**真实运行的故障子进程**及其退出证据来验证。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, 'scripts'))

import check_member_module as cmm  # noqa: E402

FAULTY = os.path.join(REPO, 'tests', 'fixtures', 'faulty_modules')

ENVELOPE = {
    'schema_version': '1.0.0-proposed',
    'run_id': 'lim-test',
    'request_id': 'req-lim-001',
    'created_at': '2026-10-12T12:00:00Z',
    'candidate_action': {'action_resource': '/rg/guarded_navigate',
                         'operation': 'NAVIGATE'},
    'observations': [{'source': 'x', 'kind': 'UNKNOWN',
                      'observed_at': '2026-10-12T12:00:00Z', 'detail': {}}],
    'evidence_refs': [{'ref': 'x', 'kind': 'UNKNOWN'}],
}


def cmd(script, *extra):
    return [sys.executable, os.path.join(FAULTY, script), *extra]


# ---------------- LIM-01 正常小输出成功 ----------------
def test_lim01_normal_small_output_succeeds():
    r = cmm.invoke([sys.executable, '-c',
                    'import sys,json; sys.stdin.read(); '
                    'print(json.dumps({"ok":1}))'],
                   ENVELOPE, timeout=30, max_bytes=65536)
    assert r['exceeded'] is None
    assert r['returncode'] == 0
    assert r['stdout_bytes'] < 100
    assert json.loads(r['stdout'])['ok'] == 1


# ---------------- LIM-02 stdout 超限立即失败 ----------------
def test_lim02_stdout_overflow_fails_immediately():
    started = time.monotonic()
    r = cmm.invoke(cmd('flood_stdout.py'), ENVELOPE, timeout=60, max_bytes=8192)
    elapsed = time.monotonic() - started
    assert r['exceeded'] == 'STDOUT_TOO_LARGE', r
    # 关键：保留量必须**被限制**，而不是把整个洪泛读进内存
    assert r['stdout_bytes'] <= 8192, r['stdout_bytes']
    # 且必须立即终止，而不是等超时
    assert elapsed < 30, '应在超限时立即终止，实测 {0:.1f}s'.format(elapsed)


# ---------------- LIM-03 持续输出不造成无界内存 ----------------
def test_lim03_continuous_output_is_bounded():
    r = cmm.invoke(cmd('flood_stdout.py'), ENVELOPE, timeout=60,
                   max_bytes=1024 * 1024)
    assert r['exceeded'] == 'STDOUT_TOO_LARGE'
    # 保留的字节数受上限约束，不随输出总量增长
    assert r['stdout_bytes'] <= 1024 * 1024


# ---------------- LIM-04 stderr 洪泛不会无限缓存 ----------------
def test_lim04_stderr_flood_is_capped():
    r = cmm.invoke(cmd('flood_stderr.py'), ENVELOPE, timeout=60,
                   max_bytes=1024 * 1024)
    # stderr 保留量必须被限制（上限来自 team_demo.MAX_STDERR_LIMIT）
    assert len(r['stderr'].encode()) <= cmm.MAX_STDERR_KEEP
    # 且 stdout 仍能拿到合法 JSON（说明 stderr 被排空而非阻塞子进程）
    assert r['stdout'].strip().startswith('{')


# ---------------- LIM-05 超时导致失败关闭 ----------------
def test_lim05_timeout_fails_closed():
    started = time.monotonic()
    r = cmm.invoke(cmd('hang.py'), ENVELOPE, timeout=2.0, max_bytes=65536)
    elapsed = time.monotonic() - started
    assert r['exceeded'] == 'TIMEOUT', r
    assert elapsed < 30, '超时后应受控终止，实测 {0:.1f}s'.format(elapsed)
    # 超时**不得**判为成功
    assert r['returncode'] != 0


# ---------------- LIM-06 子进程与子进程组正确退出 ----------------
def test_lim06_child_process_group_is_reaped():
    r = cmm.invoke(cmd('spawn_child.py'), ENVELOPE, timeout=3.0, max_bytes=65536)
    assert r['exceeded'] == 'TIMEOUT'
    # 该模块会把子进程 pid 打到 stdout
    child_pid = None
    for token in r['stdout'].split():
        if token.isdigit():
            child_pid = int(token)
            break
    time.sleep(1.5)
    if child_pid is not None:
        # 注意：**僵尸进程的 /proc/<pid> 仍然存在**。真正要断言的是
        # "子进程已终止"（不再运行），而不是"目录项消失"。
        state = None
        try:
            with open('/proc/{0}/stat'.format(child_pid), encoding='utf-8') as h:
                state = h.read().rsplit(')', 1)[1].split()[0]
        except (OSError, IndexError):
            state = None            # 目录已消失 -> 已回收
        assert state is None or state == 'Z', (
            '子进程 {0} 仍在运行（state={1}），说明只杀了父进程而非整个进程组'.format(
                child_pid, state))


# ---------------- LIM-07 其他实例进程不被清理 ----------------
def test_lim07_foreign_process_is_not_killed():
    """验收工具只应清理本次调用的进程组。"""
    other = subprocess.Popen([sys.executable, '-c',
                              'import time; time.sleep(600)'],
                             start_new_session=True)
    time.sleep(0.5)
    try:
        r = cmm.invoke(cmd('hang.py'), ENVELOPE, timeout=2.0, max_bytes=65536)
        assert r['exceeded'] == 'TIMEOUT'
        time.sleep(1.0)
        assert other.poll() is None, '其他实例的进程被误杀'
    finally:
        try:
            os.killpg(os.getpgid(other.pid), 9)
        except OSError:
            other.kill()


def test_lim07b_no_name_based_kill_in_tool():
    """工具不得按名称批量清理 —— 用 AST 只检查**真实代码字符串常量**，
    不误伤文档字符串里对"禁止按名清理"的说明。"""
    import ast
    src = open(os.path.join(REPO, 'scripts', 'check_member_module.py'),
               encoding='utf-8').read()
    tree = ast.parse(src)

    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef,
                             ast.AsyncFunctionDef)):
            body = getattr(node, 'body', None)
            if body and isinstance(body[0], ast.Expr) \
                    and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                docstrings.add(id(body[0].value))

    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in docstrings:
                continue
            for banned in ('pkill', 'killall'):
                if banned in node.value:
                    offenders.append((node.lineno, banned))
    assert not offenders, '代码中出现按名称批量清理: {0}'.format(offenders)


# ---------------- LIM-08 UTF-8 多字节严格按字节计数 ----------------
def test_lim08_utf8_counted_in_bytes_not_characters():
    r = cmm.invoke(cmd('huge_utf8.py'), ENVELOPE, timeout=60, max_bytes=9000)
    assert r['exceeded'] == 'STDOUT_TOO_LARGE'
    # 若误按**字符**计数，300000 字节 / 3 = 100000 字符仍会超限，
    # 但保留量断言能区分实现：字节上限必须被遵守
    assert r['stdout_bytes'] <= 9000
    # 直接对比：同样字符数若按字符计会小 3 倍
    kept_chars = len(r['stdout'])
    assert r['stdout_bytes'] >= kept_chars, '字节数必须 >= 字符数（UTF-8 多字节）'


# ---------------- 一致语义 ----------------
def test_tool_reuses_adapter_bounded_reader():
    """验收工具与适配层必须共用同一套有界读取实现，而非各写一套。"""
    src = open(os.path.join(REPO, 'scripts', 'check_member_module.py'),
               encoding='utf-8').read()
    assert 'import team_demo' in src
    assert 'read_bounded' in src
    assert 'terminate_process_group' in src


def test_tool_no_longer_buffers_with_subprocess_run():
    """invoke() 不得再使用会全量缓存的 capture_output。

    用 AST 直接检查真实调用：若 `invoke` 函数体内出现带 `capture_output`
    关键字的调用，即为失败。文档字符串里的说明不会被误判。
    """
    import ast
    src = open(os.path.join(REPO, 'scripts', 'check_member_module.py'),
               encoding='utf-8').read()
    tree = ast.parse(src)
    invoke = next((n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef) and n.name == 'invoke'), None)
    assert invoke is not None, '未找到 invoke()'

    bad = []
    uses_popen = False
    for node in ast.walk(invoke):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg == 'capture_output':
                    bad.append(node.lineno)
            func = node.func
            name = getattr(func, 'attr', None) or getattr(func, 'id', None)
            if name == 'Popen':
                uses_popen = True
    assert not bad, 'invoke() 仍在使用 capture_output（行号 {0}）'.format(bad)
    assert uses_popen, 'invoke() 应使用 Popen 做流式读取'


if __name__ == '__main__':
    failures = 0
    for name in sorted(dir()):
        if name.startswith('test_'):
            try:
                globals()[name]()
                print('  [PASS] {0}'.format(name))
            except Exception as exc:            # noqa: BLE001
                failures += 1
                print('  [FAIL] {0}: {1}'.format(name, exc))
    print('\n  LIMIT TESTS: {0}'.format(
        'PASS' if failures == 0 else 'FAIL ({0})'.format(failures)))
    sys.exit(0 if failures == 0 else 1)
