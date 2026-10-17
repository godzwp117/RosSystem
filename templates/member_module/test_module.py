#!/usr/bin/env python3
"""模板自测：协议正确性 + 安全默认行为。

运行：
    python3 templates/member_module/test_module.py
    python3 -m pytest templates/member_module/test_module.py -q
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MODULE = os.path.join(HERE, 'module.py')

ENVELOPE = {
    'schema_version': '1.0.0-proposed',
    'run_id': 'tpl-test',
    'request_id': 'req-tpl-001',
    'created_at': '2026-10-12T12:00:00Z',
    'candidate_action': {'action_resource': '/rg/guarded_navigate',
                         'operation': 'NAVIGATE'},
    'observations': [{'source': '/rg/guarded_navigate', 'kind': 'UNKNOWN',
                      'observed_at': '2026-10-12T12:00:00Z', 'detail': {}}],
    'evidence_refs': [{'ref': 'tpl', 'kind': 'UNKNOWN'}],
}


def run(args=(), envelope=ENVELOPE):
    return subprocess.run(
        [sys.executable, MODULE, *args],
        input=json.dumps(envelope) if envelope is not None else '',
        capture_output=True, text=True, timeout=120)


def test_default_refuses_to_fabricate_a_result():
    """默认（无真实算法）必须以非零退出，且不输出任何虚构判断。"""
    proc = run(['--module', 'comm_risk'])
    assert proc.returncode == 3, proc.stderr
    assert proc.stdout.strip() == '', 'stdout 不得有输出'
    for forbidden in ('NORMAL', 'AUTHORIZED', 'ALLOW_RECOMMENDED'):
        assert forbidden not in proc.stdout


def test_placeholder_is_semantically_honest_unknown():
    """--allow-placeholder 只能给出 UNKNOWN，不能给允许推进状态。"""
    for module, forbidden in (('comm_risk', 'NORMAL'),
                              ('identity_trust', 'AUTHORIZED'),
                              ('task_risk', 'ALLOW_RECOMMENDED')):
        proc = run(['--module', module, '--allow-placeholder'])
        assert proc.returncode == 0, proc.stderr
        payload = json.loads(proc.stdout)
        assert payload['status'] == 'UNKNOWN'
        assert payload['status'] != forbidden


def test_stdout_contains_exactly_one_json_object():
    proc = run(['--module', 'comm_risk', '--allow-placeholder'])
    payload = json.loads(proc.stdout)          # 多余文本会导致这里失败
    assert isinstance(payload, dict)
    assert proc.stdout.count('\n') == 1, 'stdout 只应有一行 JSON'


def test_ids_are_correlated():
    proc = run(['--module', 'task_risk', '--allow-placeholder'])
    payload = json.loads(proc.stdout)
    assert payload['run_id'] == ENVELOPE['run_id']
    assert payload['request_id'] == ENVELOPE['request_id']
    assert ENVELOPE['request_id'] in payload['event_id']


def test_schema_version_is_checked():
    bad = dict(ENVELOPE, schema_version='9.9.9')
    proc = run(['--module', 'comm_risk', '--allow-placeholder'], envelope=bad)
    assert proc.returncode != 0
    assert proc.stdout.strip() == ''


def test_malformed_json_fails_closed():
    proc = subprocess.run([sys.executable, MODULE, '--module', 'comm_risk'],
                          input='{not json', capture_output=True, text=True,
                          timeout=120)
    assert proc.returncode != 0
    assert proc.stdout.strip() == ''


def test_missing_request_id_fails_closed():
    bad = {k: v for k, v in ENVELOPE.items() if k != 'request_id'}
    proc = run(['--module', 'comm_risk', '--allow-placeholder'], envelope=bad)
    assert proc.returncode != 0
    assert proc.stdout.strip() == ''


def test_producer_source_does_not_mean_authentication():
    """EXTERNAL 只表示"真实外部模块"，输出必须自带澄清说明。"""
    proc = run(['--module', 'identity_trust', '--allow-placeholder'])
    payload = json.loads(proc.stdout)
    assert payload['producer']['source'] == 'EXTERNAL'
    note = payload['evidence_refs'][0]['note']
    assert '不构成任何安全保证' in note


def test_no_shell_true_and_no_dangerous_calls():
    """用 AST 检查**真实代码**，不误伤文档字符串里对禁止事项的说明。"""
    import ast as _ast
    source = open(MODULE, encoding='utf-8').read()
    tree = _ast.parse(source)

    # 1) 不得出现 shell=True
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Call):
            for kw in node.keywords:
                if kw.arg == 'shell' and isinstance(kw.value, _ast.Constant) \
                        and kw.value.value is True:
                    raise AssertionError('发现 shell=True（lineno={0}）'.format(node.lineno))

    # 2) 不得有指向 /rg/nav_execute 的**代码内字符串常量**
    #    （文档字符串/注释里提到它是允许的——那是禁止事项说明）
    docstrings = set()
    for node in _ast.walk(tree):
        if isinstance(node, (_ast.Module, _ast.FunctionDef, _ast.ClassDef,
                             _ast.AsyncFunctionDef)):
            body = getattr(node, 'body', None)
            if body and isinstance(body[0], _ast.Expr) \
                    and isinstance(body[0].value, _ast.Constant) \
                    and isinstance(body[0].value.value, str):
                docstrings.add(id(body[0].value))
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Constant) and isinstance(node.value, str):
            if id(node) in docstrings:
                continue
            assert '/rg/nav_execute' not in node.value, \
                '代码中出现指向 /rg/nav_execute 的字符串（lineno={0}）'.format(node.lineno)

    # 3) 不得出现 shell=True 之外的危险调用名
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Call) and isinstance(node.func, _ast.Attribute):
            assert node.func.attr not in ('system', 'popen'), \
                '发现危险调用 {0}'.format(node.func.attr)


if __name__ == '__main__':
    failures = 0
    for name, func in sorted(globals().items()):
        if name.startswith('test_') and callable(func):
            try:
                func()
                print('  [PASS] {0}'.format(name))
            except AssertionError as exc:
                failures += 1
                print('  [FAIL] {0}: {1}'.format(name, exc))
            except Exception as exc:            # noqa: BLE001
                failures += 1
                print('  [ERROR] {0}: {1}: {2}'.format(name, type(exc).__name__, exc))
    print('\n  TEMPLATE SELF-TEST: {0}'.format(
        'PASS' if failures == 0 else 'FAIL ({0})'.format(failures)))
    sys.exit(0 if failures == 0 else 1)
