"""成员一真实验收器回归：config + fixture + 真实模型必须达到 L1 门槛。

这个测试把交付的
  * config/team_modules.member1.real.yaml
  * config/acceptance/real_scenarios.member1.yaml
  * modules/member1_comm/model/comm_risk_model.json
三者作为**一个整体**回归，避免配置/模型/fixture 漂移后无人发现。

注意门槛的含义：`meets_pr_gate` 只表示 L1 协议层验收通过。
算法有效性（L2）仍然是 NOT_READY，在线监测（L3）仍然是 BLOCKED —— 报告里
必须照抄，不得把 L1 通过写成检测有效。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip('jsonschema', reason='需要 jsonschema>=4.0（Draft 2020-12）')

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / 'config' / 'team_modules.member1.real.yaml'
FIXTURE = ROOT / 'config' / 'acceptance' / 'real_scenarios.member1.yaml'


def run_checker(tmp_path, run_id='m1-real'):
    return subprocess.run(
        [sys.executable, str(ROOT / 'scripts' / 'check_member_module.py'),
         '--module', 'comm_risk', '--config', str(CONFIG),
         '--real-fixture', str(FIXTURE),
         '--out-dir', str(tmp_path), '--run-id', run_id],
        capture_output=True, text=True, timeout=600, cwd=str(ROOT))


def test_real_fixture_matrix_passes(tmp_path):
    proc = run_checker(tmp_path)
    assert proc.returncode == 0, proc.stdout[-4000:] + proc.stderr[-2000:]
    data = json.loads((tmp_path / 'm1-real' / 'report.json')
                      .read_text(encoding='utf-8'))
    checks = {c['id']: c for c in data['checks']}
    # 五个真实条件场景全部通过（含 NORMAL 只在受控配置下可达）
    for cid in ('REAL-STATE-SUSPICIOUS', 'REAL-STATE-UNKNOWN',
                'REAL-STATE-NORMAL-CONTROLLED', 'REAL-STATE-FEATURES-ABSENT',
                'REAL-STATE-ERROR', 'REAL-STATE-SCHEMA', 'REAL-STATE-SUMMARY'):
        assert checks[cid]['status'] == 'PASS', (cid, checks[cid])
    # 适配层对阻断状态必须阻断；受控场景才可能出现 READY
    for cid in ('REAL-ADP-SUSPICIOUS', 'REAL-ADP-UNKNOWN',
                'REAL-ADP-FEATURES-ABSENT', 'REAL-ADP-ERROR'):
        assert checks[cid]['decision'] == 'ADAPTER_BLOCK', (cid, checks[cid])
    assert checks['REAL-ADP-NORMAL-CONTROLLED']['decision'] == \
        'READY_FOR_GATEWAY_SUBMISSION'
    assert data['meets_pr_gate'] is True
    # 诚实性：L2/L3 不得被 L1 通过顺带"提升"
    assert data['algorithm_evidence'] == 'NOT_READY'
    assert data['runtime_integration'] == 'BLOCKED'


def test_mock_state_matrix_is_not_applicable_for_real_module(tmp_path):
    """真实模块不解析 f0_mock 场景开关：这些检查必须标记为不适用且不入门槛。"""
    proc = run_checker(tmp_path, 'm1-na')
    assert proc.returncode == 0, proc.stdout[-3000:]
    data = json.loads((tmp_path / 'm1-na' / 'report.json')
                      .read_text(encoding='utf-8'))
    checks = {c['id']: c for c in data['checks']}
    for scenario in ('NORMAL', 'SUSPICIOUS', 'UNKNOWN', 'ERROR'):
        entry = checks['STATE-{0}'.format(scenario)]
        assert entry.get('gate') is False
        assert entry.get('applicability') == 'NOT_APPLICABLE_REAL_MODULE'
        assert entry['mandatory'] is False
