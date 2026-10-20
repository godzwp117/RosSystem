#!/usr/bin/env python3
"""ADP-01 加固的可证伪性测试（适配层**输入校验拒绝**）。

修复的缺陷
----------
旧 `ADP-01` 判定为：

    blocked = ('ADAPTER_BLOCK' in proc.stdout
               or 'ADAPTER_INPUT_INVALID' in proc.stdout
               or proc.returncode != 0)

`proc.returncode != 0` 使**任意**非零退出都被算作「输入校验成功阻断」。
于是适配器因 Python 异常、依赖缺失、配置错误而崩溃时，也会被记为
「输入拒绝 PASS」——验收证明的错误。

加固后的判定必须**同时**成立（见 `judge_clean_input_rejection`）：
  1. stdout 是可解析 JSON；
  2. 顶层 decision == ADAPTER_BLOCK；
  3. reason_code == ADAPTER_INPUT_INVALID；
  4. returncode == EXIT_INPUT_INVALID（3，协议规定）；
  5. 没有任何模块被调用（用调用标记证明拒绝发生在模块调用之前）；
  6. 没有启动 Planner。

本文件覆盖任务书 ADP-N01..N10，并额外给出**旧逻辑会误判**的直接证明。
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
import team_demo as td  # noqa: E402

MOCK_CONFIG = os.path.join(REPO, 'config', 'team_modules.example.yaml')
ADAPTER = os.path.join(REPO, 'scripts', 'team_demo.py')


# ---------------------------------------------------------------------------
# 0) 旧逻辑确实会误判（证明修复的必要性）
# ---------------------------------------------------------------------------

def test_old_logic_would_have_accepted_a_crashing_adapter():
    """直接复现旧判定表达式：崩溃的适配器在旧逻辑下被记为 PASS。"""
    crashed = {'returncode': 1, 'stdout': 'Traceback (most recent call last): ...'}
    old_blocked = ('ADAPTER_BLOCK' in crashed['stdout']
                   or 'ADAPTER_INPUT_INVALID' in crashed['stdout']
                   or crashed['returncode'] != 0)
    assert old_blocked is True, '旧表达式对崩溃进程返回 True（这正是缺陷）'

    # 新判定必须拒绝它
    evidence = {'stdout_is_json': False, 'decision': None, 'reason_code': None,
                'planner_started': False, 'modules_invoked': None,
                'exit_code': 1, 'stdout_head': crashed['stdout'][:80],
                'stderr_head': ''}
    ok, detail = cmm.judge_clean_input_rejection(evidence)
    assert ok is False, '新判定不得把崩溃记为输入拒绝'
    assert 'JSON' in detail


def test_new_logic_requires_every_condition():
    """逐项破坏：任一条件缺失都必须判负（不是恒真断言）。"""
    good = {'stdout_is_json': True, 'decision': 'ADAPTER_BLOCK',
            'reason_code': td.REASON_INPUT_INVALID,
            'planner_started': False, 'modules_invoked': 0,
            'exit_code': td.EXIT_INPUT_INVALID, 'stdout_head': '',
            'stderr_head': ''}
    ok, _ = cmm.judge_clean_input_rejection(dict(good))
    assert ok is True, '合法输入拒绝应通过'

    breakages = {
        'stdout 非 JSON': {'stdout_is_json': False},
        'decision 不是 ADAPTER_BLOCK': {'decision': 'READY_FOR_GATEWAY_SUBMISSION'},
        'reason_code 不符': {'reason_code': td.REASON_CONFIG_INVALID},
        '退出码不符协议': {'exit_code': td.EXIT_BLOCK},
        '退出码为 None': {'exit_code': None},
        '模块已被调用': {'modules_invoked': 1},
        'Planner 已启动': {'planner_started': True},
    }
    for name, patch in breakages.items():
        broken = dict(good)
        broken.update(patch)
        ok, detail = cmm.judge_clean_input_rejection(broken)
        assert ok is False, '{0} 却判为通过'.format(name)
        assert detail, name


def test_constant_source_is_the_adapter_not_a_hardcoded_copy():
    """判定用的原因码/退出码必须取自已导入的适配层模块。"""
    assert cmm._td_checks['REASON_INPUT_INVALID'] == td.REASON_INPUT_INVALID
    assert cmm._td_checks['EXIT_INPUT_INVALID'] == td.EXIT_INPUT_INVALID
    assert td.REASON_INPUT_INVALID == 'ADAPTER_INPUT_INVALID'
    assert td.EXIT_INPUT_INVALID == 3


# ---------------------------------------------------------------------------
# 1) 端到端：ADP-N01..N10 由真实子进程验证
# ---------------------------------------------------------------------------

def _run_checker(tmp_path, run_id, module='task_risk', config=MOCK_CONFIG):
    proc = subprocess.run(
        [sys.executable, os.path.join(REPO, 'scripts', 'check_member_module.py'),
         '--module', module, '--config', config,
         '--out-dir', str(tmp_path), '--run-id', run_id],
        capture_output=True, text=True, timeout=1800, cwd=REPO)
    report_path = os.path.join(str(tmp_path), run_id, 'report.json')
    with open(report_path, encoding='utf-8') as handle:
        return proc, json.load(handle)


@pytest.fixture(scope='module')
def adp_report(tmp_path_factory):
    out = tmp_path_factory.mktemp('adp01')
    proc, report = _run_checker(out, 'adp01-e2e')
    return proc, report


def _check(report, cid):
    for entry in report['checks']:
        if entry['id'] == cid:
            return entry
    raise AssertionError('缺少检查项 ' + cid)


@pytest.mark.parametrize('cid,label', [
    ('ADP-N01', '缺少 observations'),
    ('ADP-N02', 'schema_version 非法'),
    ('ADP-N03', '缺少 candidate_action'),
    ('ADP-N04', '非法 JSON 输入'),
])
def test_clean_input_rejection_cases_pass(adp_report, cid, label):
    """ADP-N01..N04：必须给出明确的 ADAPTER_INPUT_INVALID 拒绝。"""
    _proc, report = adp_report
    entry = _check(report, cid)
    assert entry['status'] == 'PASS', entry
    evidence = entry['adapter_evidence']
    assert evidence['decision'] == 'ADAPTER_BLOCK', entry
    assert evidence['reason_code'] == 'ADAPTER_INPUT_INVALID', entry
    assert evidence['exit_code'] == 3, entry
    assert evidence['modules_invoked'] == 0, entry
    assert evidence['planner_started'] is False, entry
    # 模块不得被调用（调用标记不存在）
    assert entry['module_called'] is False, entry


@pytest.mark.parametrize('cid,label', [
    ('ADP-N05', '适配器内部异常/模块脚本崩溃'),
    ('ADP-N06', '适配器依赖缺失'),
    ('ADP-N07', '配置文件不存在'),
    ('ADP-N08', '模块非零退出且输出非 JSON'),
])
def test_non_input_faults_are_not_recorded_as_input_rejection(adp_report, cid,
                                                              label):
    """ADP-N05..N08：非输入类故障绝不能被记为「输入校验拒绝」。"""
    _proc, report = adp_report
    entry = _check(report, cid)
    assert entry['status'] == 'PASS', entry
    assert entry['misrecorded_as_input_rejection'] is False, entry
    evidence = entry.get('adapter_evidence') or {}
    # 若适配层产出了结构化结果，其原因码不得是输入拒绝
    if evidence:
        assert evidence.get('reason_code') != 'ADAPTER_INPUT_INVALID', entry


def test_reason_code_must_match_real_failure_path(adp_report):
    """ADP-N09：原因码必须与真实失败路径一致，不得冒充输入拒绝。"""
    _proc, report = adp_report
    entry = _check(report, 'ADP-N09')
    assert entry['status'] == 'PASS', entry
    evidence = entry['adapter_evidence']
    assert evidence['reason_code'] != 'ADAPTER_INPUT_INVALID', entry


def test_legal_input_really_invokes_module(adp_report):
    """ADP-N10：合法输入必须真实调用模块，否则 FAIL。"""
    _proc, report = adp_report
    entry = _check(report, 'ADP-N10')
    assert entry['status'] == 'PASS', entry
    assert entry['module_called'] is True, entry


def test_positive_control_exists(adp_report):
    """必须有正向对照，否则「全部判为阻断」也能骗过本项。"""
    _proc, report = adp_report
    entry = _check(report, 'ADP-00')
    assert entry['status'] == 'PASS', entry
    assert entry['control'] == 'POSITIVE_CONTROL', entry


def test_original_adp01_now_requires_real_rejection(adp_report):
    """ADP-01 本身也必须给出可核验的输入拒绝证据。"""
    _proc, report = adp_report
    entry = _check(report, 'ADP-01')
    assert entry['status'] == 'PASS', entry
    evidence = entry['adapter_evidence']
    assert evidence['decision'] == 'ADAPTER_BLOCK'
    assert evidence['reason_code'] == 'ADAPTER_INPUT_INVALID'
    assert evidence['exit_code'] == 3
    assert evidence['modules_invoked'] == 0


def test_no_regression_in_overall_gate(adp_report):
    """加固后门槛仍应通过，且不得出现 FAIL。"""
    _proc, report = adp_report
    assert report['meets_pr_gate'] is True, report.get('counts')
    assert report['counts'].get('FAIL', 0) == 0, report['counts']
