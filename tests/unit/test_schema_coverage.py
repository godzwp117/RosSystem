#!/usr/bin/env python3
"""FIX-01 负向验证：覆盖检查必须能真实失败。

这些测试**临时构造隔离副本**，不修改正式 Schema 或正式样例。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CHECKER = os.path.join(REPO, 'scripts', 'check_schema_coverage.py')
EXAMPLES = os.path.join(REPO, 'docs', 'interfaces', 'examples')
SCHEMAS = os.path.join(REPO, 'docs', 'interfaces', 'schemas')


def run_checker():
    return subprocess.run([sys.executable, CHECKER], capture_output=True,
                          text=True, timeout=300, cwd=REPO)


def test_coverage_passes_on_real_repo():
    proc = run_checker()
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert 'SCHEMA_EXAMPLE_COVERAGE: PASS' in proc.stdout
    # 每份 Schema 都必须有实际校验过的样例
    for name in ('module_input', 'comm_risk_evidence',
                 'identity_trust_assessment', 'task_risk_decision'):
        assert '{0}: checked'.format(name) in proc.stdout
        assert '{0}: checked 0'.format(name) not in proc.stdout


def test_coverage_reports_zero_when_no_examples(tmp_path):
    """checked_count=0 必须失败（用隔离副本模拟样例目录为空）。"""
    sandbox = tmp_path / 'repo'
    (sandbox / 'scripts').mkdir(parents=True)
    for name in ('validate_team_contracts.py', 'check_schema_coverage.py'):
        shutil.copy2(os.path.join(REPO, 'scripts', name),
                     sandbox / 'scripts' / name)
    shutil.copytree(os.path.join(REPO, 'docs'), sandbox / 'docs')
    # 清空样例目录
    for item in (sandbox / 'docs' / 'interfaces' / 'examples').iterdir():
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()
    proc = subprocess.run([sys.executable,
                           str(sandbox / 'scripts' / 'check_schema_coverage.py')],
                          capture_output=True, text=True, timeout=300, cwd=str(sandbox))
    assert proc.returncode != 0, '样例为空时必须失败'
    assert 'FAIL' in proc.stdout


def test_coverage_fails_when_a_required_valid_example_is_removed(tmp_path):
    """移走一个必需的合法样例 -> 该 Schema 覆盖为 0 -> 必须失败。"""
    sandbox = tmp_path / 'repo'
    (sandbox / 'scripts').mkdir(parents=True)
    for name in ('validate_team_contracts.py', 'check_schema_coverage.py'):
        shutil.copy2(os.path.join(REPO, 'scripts', name),
                     sandbox / 'scripts' / name)
    shutil.copytree(os.path.join(REPO, 'docs'), sandbox / 'docs')
    # 移走 task_risk_decision 的全部合法样例
    for name in ('task_allow_recommended.json', 'task_block_recommended.json',
                 'task_unknown.json'):
        target = sandbox / 'docs' / 'interfaces' / 'examples' / name
        if target.exists():
            target.unlink()
    proc = subprocess.run([sys.executable,
                           str(sandbox / 'scripts' / 'check_schema_coverage.py')],
                          capture_output=True, text=True, timeout=300, cwd=str(sandbox))
    assert proc.returncode != 0, '缺失必需样例时必须失败'
    assert 'task_risk_decision' in proc.stdout


def test_coverage_fails_when_valid_example_violates_schema(tmp_path):
    """把合法样例改成违反 Schema（字段类型错误）-> 必须失败。"""
    sandbox = tmp_path / 'repo'
    (sandbox / 'scripts').mkdir(parents=True)
    for name in ('validate_team_contracts.py', 'check_schema_coverage.py'):
        shutil.copy2(os.path.join(REPO, 'scripts', name),
                     sandbox / 'scripts' / name)
    shutil.copytree(os.path.join(REPO, 'docs'), sandbox / 'docs')
    target = sandbox / 'docs' / 'interfaces' / 'examples' / 'comm_normal.json'
    payload = json.loads(target.read_text(encoding='utf-8'))
    # request_count 在 Schema 中要求 integer
    payload['request_count'] = 'not-an-integer'
    target.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    proc = subprocess.run([sys.executable,
                           str(sandbox / 'scripts' / 'check_schema_coverage.py')],
                          capture_output=True, text=True, timeout=300, cwd=str(sandbox))
    assert proc.returncode != 0, '合法样例违反 Schema 时必须失败'


def test_coverage_fails_when_invalid_example_is_accepted(tmp_path):
    """把一个非法样例改成合法内容 -> 期望拒绝却通过 -> 必须失败。"""
    sandbox = tmp_path / 'repo'
    (sandbox / 'scripts').mkdir(parents=True)
    for name in ('validate_team_contracts.py', 'check_schema_coverage.py'):
        shutil.copy2(os.path.join(REPO, 'scripts', name),
                     sandbox / 'scripts' / name)
    shutil.copytree(os.path.join(REPO, 'docs'), sandbox / 'docs')
    # 用合法样例的内容覆盖一个非法样例
    bad = sandbox / 'docs' / 'interfaces' / 'examples' / 'invalid' / 'comm_bad_enum.json'
    good = sandbox / 'docs' / 'interfaces' / 'examples' / 'comm_normal.json'
    bad.write_text(good.read_text(encoding='utf-8'), encoding='utf-8')
    proc = subprocess.run([sys.executable,
                           str(sandbox / 'scripts' / 'check_schema_coverage.py')],
                          capture_output=True, text=True, timeout=300, cwd=str(sandbox))
    assert proc.returncode != 0, '非法样例被接受时必须失败'


def test_ci_no_longer_uses_filename_prefix_matching():
    """CI 不得再使用模糊的文件名前缀匹配来关联 Schema 与样例。"""
    ci = open(os.path.join(REPO, '.github', 'workflows',
                           'member-module-gates.yml'), encoding='utf-8').read()
    assert 'startswith(stem' not in ci, 'CI 仍在使用文件名前缀匹配'
    assert 'check_schema_coverage.py' in ci, 'CI 未接入覆盖检查'
    assert 'validate_team_contracts.py' in ci, 'CI 未复用既有契约校验器'


def test_public_schemas_unmodified():
    """不得为了迁就样例而修改正式 Schema。"""
    base = 'baseline'
    proc = subprocess.run(
        ['git', 'diff', '--name-only', base, 'HEAD', '--',
         'docs/interfaces/schemas/', 'docs/interfaces/examples/'],
        cwd=REPO, capture_output=True, text=True)
    assert proc.stdout.strip() == '', (
        '正式 Schema 或样例被修改: {0}'.format(proc.stdout))


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
    print('\n  SCHEMA COVERAGE TESTS: {0}'.format(
        'PASS' if failures == 0 else 'FAIL ({0})'.format(failures)))
    sys.exit(0 if failures == 0 else 1)
