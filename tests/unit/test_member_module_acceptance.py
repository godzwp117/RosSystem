#!/usr/bin/env python3
"""统一成员模块验收工具的测试。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TOOL = os.path.join(REPO, 'scripts', 'check_member_module.py')
MOCK_CONFIG = os.path.join(REPO, 'config', 'team_modules.example.yaml')
MODULES = ('comm_risk', 'identity_trust', 'task_risk')


def run_tool(module, config=MOCK_CONFIG, out_dir=None, run_id=None):
    args = [sys.executable, TOOL, '--module', module, '--config', config]
    if out_dir:
        args += ['--out-dir', out_dir]
    if run_id:
        args += ['--run-id', run_id]
    return subprocess.run(args, capture_output=True, text=True, timeout=600,
                          cwd=REPO)


def test_tool_exists_and_has_cli():
    proc = subprocess.run([sys.executable, TOOL, '--help'],
                          capture_output=True, text=True, timeout=120, cwd=REPO)
    assert proc.returncode == 0
    for key in ('--module', '--config'):
        assert key in proc.stdout


@pytest.mark.parametrize('module', MODULES)
def test_three_modules_are_acceptable(module, tmp_path):
    proc = run_tool(module, out_dir=str(tmp_path), run_id='t-' + module)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert '达到 PR 合入门槛: True' in proc.stdout


@pytest.mark.parametrize('module', MODULES)
def test_report_is_machine_readable(module, tmp_path):
    run_tool(module, out_dir=str(tmp_path), run_id='r-' + module)
    report = tmp_path / ('r-' + module) / 'report.json'
    assert report.is_file()
    data = json.loads(report.read_text(encoding='utf-8'))
    for key in ('baseline_sha', 'module', 'module_command', 'test_layer',
                'checks', 'meets_pr_gate', 'algorithm_evidence',
                'runtime_integration'):
        assert key in data, key
    assert data['module'] == module
    assert data['test_layer'] == 'L1_PROTOCOL'


def test_report_does_not_leak_sensitive_material(tmp_path):
    """报告不得泄露敏感材料。

    注意：这里**故意不在源码里写出完整标记字面量**。
    仓库 CI 的凭据扫描会对所有被跟踪文件 grep `BEGIN [A-Z ]*PRIVATE KEY`，
    如果本测试把该字面量直接写在源码里，扫描会把这个**测试文件本身**
    误判为疑似凭据泄露，导致 member-module-gates 失败。
    因此标记在运行时拼接，既保留断言语义，又不污染仓库扫描。
    """
    run_tool('comm_risk', out_dir=str(tmp_path), run_id='sec')
    text = (tmp_path / 'sec' / 'report.json').read_text(encoding='utf-8')
    private_key_marker = 'BEGIN' + ' ' + 'PRIVATE' + ' ' + 'KEY'   # 运行时拼接
    for forbidden in ('AWS_SECRET', 'AWS_SECRET_ACCESS_KEY', 'GITHUB_TOKEN',
                      'GH_TOKEN', private_key_marker):
        assert forbidden not in text, '报告泄露了敏感材料: {0}'.format(forbidden)


def test_legal_block_is_not_reported_as_schema_invalid(tmp_path):
    """DENIED / SUSPICIOUS / BLOCK_RECOMMENDED 是合法安全阻断，不是 Schema 错误。"""
    proc = run_tool('comm_risk', out_dir=str(tmp_path), run_id='lb')
    assert 'LEGAL_BLOCK' in proc.stdout or 'STATE-03' in proc.stdout
    text = (tmp_path / 'lb' / 'report.json').read_text(encoding='utf-8')
    assert 'LEGAL_BLOCK' in text


def test_adapter_is_the_mandatory_fail_closed_boundary(tmp_path):
    proc = run_tool('comm_risk', out_dir=str(tmp_path), run_id='adp')
    assert 'ADP-01' in proc.stdout


def test_skipped_is_not_counted_as_pass(tmp_path):
    run_tool('comm_risk', out_dir=str(tmp_path), run_id='sk')
    data = json.loads((tmp_path / 'sk' / 'report.json').read_text(encoding='utf-8'))
    counts = data['counts']
    assert 'SKIPPED' not in counts or counts.get('SKIPPED', 0) == 0
    # L2/L3 必须显式标注为未完成，而不是 PASS
    assert data['algorithm_evidence'] == 'NOT_READY'
    assert data['runtime_integration'] == 'BLOCKED'


def test_mandatory_failure_yields_nonzero_exit(tmp_path):
    """配置里没有该模块时必须非零退出。"""
    cfg = tmp_path / 'empty.yaml'
    cfg.write_text('modules: {}\n', encoding='utf-8')
    proc = run_tool('comm_risk', config=str(cfg), out_dir=str(tmp_path),
                    run_id='fail')
    assert proc.returncode != 0


def test_missing_config_file_yields_nonzero_exit(tmp_path):
    proc = run_tool('comm_risk', config=str(tmp_path / 'nope.yaml'),
                    out_dir=str(tmp_path), run_id='nocfg')
    assert proc.returncode != 0


def test_tool_records_real_execution_evidence(tmp_path):
    run_tool('task_risk', out_dir=str(tmp_path), run_id='ev')
    data = json.loads((tmp_path / 'ev' / 'report.json').read_text(encoding='utf-8'))
    run_check = next(c for c in data['checks'] if c['id'] == 'RUN-01')
    assert run_check['status'] == 'PASS'
    assert run_check['returncode'] == 0
    assert 'stdout_bytes' in run_check
    assert data['module_command'], '必须记录实际执行的命令'
    assert data['executable'], '必须记录可执行文件'
