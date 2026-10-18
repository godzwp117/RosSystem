#!/usr/bin/env python3
"""FIX-03：三模块 × 四状态 = 12 个组合的**真实运行**验证。

不通过检查枚举列表或字符串出现来证明覆盖 —— 每一项都真实调用模块、
真实产出 JSON、真实通过 Schema，并由状态分类器处理。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, 'scripts'))

import check_member_module as cmm  # noqa: E402

CONFIG = os.path.join(REPO, 'config', 'team_modules.example.yaml')

EXPECTED = {
    'comm_risk': {'PROCEED': 'NORMAL',
                  'LEGAL_BLOCK': {'SUSPICIOUS', 'UNKNOWN', 'ERROR'}},
    'identity_trust': {'PROCEED': 'AUTHORIZED',
                       'LEGAL_BLOCK': {'DENIED', 'UNKNOWN', 'ERROR'}},
    'task_risk': {'PROCEED': 'ALLOW_RECOMMENDED',
                  'LEGAL_BLOCK': {'BLOCK_RECOMMENDED', 'UNKNOWN', 'ERROR'}},
}


def run_tool(module, tmp_path, run_id):
    return subprocess.run(
        [sys.executable, os.path.join(REPO, 'scripts', 'check_member_module.py'),
         '--module', module, '--config', CONFIG,
         '--out-dir', str(tmp_path), '--run-id', run_id],
        capture_output=True, text=True, timeout=900, cwd=REPO)


def test_state_matrix_is_complete():
    """三模块各四种状态，合计 12 个组合，无遗漏。"""
    total = sum(len(v) for v in cmm.STATE_MATRIX.values())
    assert total == 12, total
    for module, rows in cmm.STATE_MATRIX.items():
        assert len(rows) == 4, (module, rows)
        states = {r[1] for r in rows}
        assert EXPECTED[module]['PROCEED'] in states
        assert EXPECTED[module]['LEGAL_BLOCK'] <= states


@pytest.mark.parametrize('module', sorted(EXPECTED))
def test_all_four_states_really_execute(module, tmp_path):
    """每个状态都必须真实运行并通过 Schema，分类正确。"""
    proc = run_tool(module, tmp_path, 'fs-' + module)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    data = json.loads((tmp_path / ('fs-' + module) / 'report.json')
                      .read_text(encoding='utf-8'))
    rows = data['state_matrix']
    assert len(rows) == 4, rows

    for row in rows:
        assert row['returncode'] == 0, row
        assert row['structured'] is True, row
        assert row['schema_ok'] is True, row
        assert row['ids_ok'] is True, row
        assert row['actual_state'] == row['expected_state'], row
        assert row['actual_class'] == row['expected_class'], row

    proceed = [r for r in rows if r['expected_class'] == 'PROCEED']
    blocked = [r for r in rows if r['expected_class'] == 'LEGAL_BLOCK']
    assert len(proceed) == 1 and len(blocked) == 3
    assert proceed[0]['actual_state'] == EXPECTED[module]['PROCEED']
    assert {r['actual_state'] for r in blocked} == EXPECTED[module]['LEGAL_BLOCK']


@pytest.mark.parametrize('module', sorted(EXPECTED))
def test_blocking_states_are_schema_valid_not_schema_errors(module, tmp_path):
    """关键区分：阻断状态**结构合法**，只是不允许推进。"""
    run_tool(module, tmp_path, 'sv-' + module)
    data = json.loads((tmp_path / ('sv-' + module) / 'report.json')
                      .read_text(encoding='utf-8'))
    for row in data['state_matrix']:
        if row['expected_class'] == 'LEGAL_BLOCK':
            assert row['schema_ok'] is True, (
                '{0} 被误判为 Schema 非法: {1}'.format(row['actual_state'],
                                                       row.get('detail')))
            assert row['actual_class'] == 'LEGAL_BLOCK'


@pytest.mark.parametrize('module', sorted(EXPECTED))
def test_adapter_blocks_every_blocking_state(module, tmp_path):
    """三种阻断状态经 team_demo.py 必须全部返回 ADAPTER_BLOCK。"""
    proc = run_tool(module, tmp_path, 'ad-' + module)
    assert proc.returncode == 0, proc.stdout
    for state in EXPECTED[module]['LEGAL_BLOCK']:
        assert 'ADP-{0}'.format(
            {'SUSPICIOUS': 'SUSPICIOUS', 'DENIED': 'DENIED',
             'BLOCK_RECOMMENDED': 'BLOCK', 'UNKNOWN': 'UNKNOWN',
             'ERROR': 'ERROR'}[state]) in proc.stdout


def test_layers_are_not_conflated(tmp_path):
    """L1 通过不得自动把 L2/L3 标为 PASS。"""
    run_tool('comm_risk', tmp_path, 'ly')
    data = json.loads((tmp_path / 'ly' / 'report.json').read_text(encoding='utf-8'))
    assert data['test_layer'] == 'L1_PROTOCOL'
    assert data['algorithm_evidence'] == 'NOT_READY'
    assert data['runtime_integration'] == 'BLOCKED'
    assert data['counts'].get('PASS', 0) > 0
    # L2/L3 在 checks 中必须是 NOT_RUN / BLOCKED，而不是 PASS
    for c in data['checks']:
        if c['id'] in ('LAYER-02', 'LAYER-03'):
            assert c['status'] in ('NOT_RUN', 'BLOCKED'), c


def test_state_classifier_is_not_hardcoded():
    """STATE 项必须来自真实运行结果，而不是写死的 PASS。"""
    src = open(os.path.join(REPO, 'scripts', 'check_member_module.py'),
               encoding='utf-8').read()
    # 不应再出现"直接写入 PASS 的 STATE-03 静态断言"
    assert "report.add('STATE-03'" not in src
    assert 'state_matrix' in src


if __name__ == '__main__':
    failures = 0
    for name in sorted(dir()):
        if name.startswith('test_'):
            fn = globals()[name]
            import inspect
            if inspect.signature(fn).parameters:
                continue
            try:
                fn()
                print('  [PASS] {0}'.format(name))
            except Exception as exc:            # noqa: BLE001
                failures += 1
                print('  [FAIL] {0}: {1}'.format(name, exc))
    print('\n  FOUR-STATE TESTS: {0}'.format(
        'PASS' if failures == 0 else 'FAIL ({0})'.format(failures)))
    sys.exit(0 if failures == 0 else 1)
