#!/usr/bin/env python3
"""LIM-01 与 REAL-STATE 退出码判定的**反例测试**。

修复的两个验收器严谨性缺陷
--------------------------
1. **LIM-01 无条件 PASS**：旧实现写作
   ``'PASS' if r_t['exceeded'] in ('TIMEOUT', None) else 'PASS'``
   —— 三元表达式两个分支同为 ``'PASS'``，恒为 PASS，无法验证任何东西。
   现在由 :func:`check_member_module.judge_timeout` 依据**可核验事实**
   （是否超时、超时后是否被信号终止、进程组是否回收、运行时间是否被真正约束）
   区分：超时前干净结束 / 超时且已终止回收 / 超时未被约束。
2. **REAL-STATE 未校验成功退出**：``returncode != 0`` 但 stdout 是合法 JSON 且
   状态正确时，旧实现仍然判 PASS。现在 ``returncode == 0`` 是真实状态验收的
   必要条件；同时保留 UNKNOWN / ERROR 作为**合法安全阻断**的语义
   （它们结构合法且 rc==0 时仍然通过，不因其"不是 ALLOW"而被判 Schema 失败）。

本文件同时包含**真实故障子进程**测试与**故障注入**测试，确保失败分支
不是纸面逻辑：被注入失败结果时，LIM-01 必须真的记为 FAIL。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, 'scripts'))

import check_member_module as cmm  # noqa: E402

FAULTY = os.path.join(REPO, 'tests', 'fixtures', 'faulty_modules')
CHECKER = os.path.join(REPO, 'scripts', 'check_member_module.py')
MOCK_CONFIG = os.path.join(REPO, 'config', 'team_modules.example.yaml')
REAL_CONFIG = os.path.join(REPO, 'config', 'team_modules.member3.real.yaml')
REAL_FIXTURE = os.path.join(REPO, 'config', 'acceptance',
                            'real_scenarios.member3.yaml')

ENVELOPE = {
    'schema_version': '1.0.0-proposed',
    'run_id': 'lim01-test',
    'request_id': 'req-lim01-001',
    'created_at': '2026-10-16T00:00:00Z',
    'candidate_action': {'action_resource': '/rg/guarded_navigate',
                         'operation': 'NAVIGATE', 'task_id': 'patrol_a_001',
                         'target': {'frame_id': 'map', 'x': 2.0, 'y': 2.0}},
    'observations': [{'source': 'x', 'kind': 'UNKNOWN',
                      'observed_at': '2026-10-16T00:00:00Z', 'detail': {}}],
    'evidence_refs': [{'ref': 'x', 'kind': 'UNKNOWN'}],
}


# ===========================================================================
# 1) judge_timeout 的判定表（每条都断言 ok/status，确保不是恒真）
# ===========================================================================

def test_clean_completion_within_bound_passes():
    ok, status, _ = cmm.judge_timeout(
        {'exceeded': None, 'elapsed': 0.009, 'returncode': 0, 'terminate': None},
        0.001)
    assert ok is True and status == 'clean_completion'


def test_clean_completion_nonzero_exit_still_clean():
    """超时前自行结束即算干净（退出码由 PROTO/ID 等检查单独判定）。"""
    ok, status, _ = cmm.judge_timeout(
        {'exceeded': None, 'elapsed': 0.02, 'returncode': 2, 'terminate': None},
        0.001)
    assert ok is True and status == 'clean_completion'


def test_overrun_without_timeout_fails():
    """未报超时但运行时间远超上限 -> 极小超时没有约束住运行时间，判负。"""
    ok, status, detail = cmm.judge_timeout(
        {'exceeded': None, 'elapsed': 30.0, 'returncode': 0, 'terminate': None},
        0.001)
    assert ok is False and status == 'overran_without_timeout'
    assert '未约束' in detail or '超过上限' in detail


def test_timeout_terminated_and_reaped_passes():
    ok, status, _ = cmm.judge_timeout(
        {'exceeded': 'TIMEOUT', 'elapsed': 0.502, 'returncode': -15,
         'terminate': 'terminated'}, 0.5)
    assert ok is True and status == 'timeout_terminated'


def test_timeout_with_kill_escalation_is_clean():
    ok, status, _ = cmm.judge_timeout(
        {'exceeded': 'TIMEOUT', 'elapsed': 1.2, 'returncode': -9,
         'terminate': 'terminated+killed'}, 0.5)
    assert ok is True and status == 'timeout_terminated'


@pytest.mark.parametrize('terminate', [
    'terminated+unreaped', 'terminated+kill_failed:EPERM',
    'term_failed:EPERM', None, 'unknown_outcome',
])
def test_timeout_without_clean_reap_fails(terminate):
    """超时后进程组未完成回收 -> 必须判负，绝不能记为 PASS。"""
    ok, status, detail = cmm.judge_timeout(
        {'exceeded': 'TIMEOUT', 'elapsed': 0.6, 'returncode': -15,
         'terminate': terminate}, 0.5)
    assert ok is False and status == 'timeout_not_contained'
    assert 'terminate' in detail


def test_timeout_without_signal_exit_fails():
    """超时但退出码不是被信号杀死的负值 -> 无法证明真的终止了，判负。"""
    for rc in (0, 1, None):
        ok, status, _ = cmm.judge_timeout(
            {'exceeded': 'TIMEOUT', 'elapsed': 0.6, 'returncode': rc,
             'terminate': 'terminated'}, 0.5)
        assert ok is False and status == 'timeout_not_contained', rc


def test_timeout_took_far_too_long_fails():
    """超时后仍跑了远超余量的时间 -> 超时未被有效执行，判负。"""
    ok, status, detail = cmm.judge_timeout(
        {'exceeded': 'TIMEOUT', 'elapsed': 60.0, 'returncode': -15,
         'terminate': 'terminated'}, 0.5)
    assert ok is False and status == 'timeout_not_contained'
    assert 'elapsed' in detail


@pytest.mark.parametrize('exceeded', [
    'STDOUT_TOO_LARGE', 'STDERR_TOO_LARGE', 'SPAWN_FAILED', 'NOT_FOUND',
    'SETUP_FAILED:x',
])
def test_unexpected_exceeded_reason_fails(exceeded):
    """非 TIMEOUT 的 exceeded 原因不得被极小超时检查接受为通过。"""
    ok, status, _ = cmm.judge_timeout(
        {'exceeded': exceeded, 'elapsed': 0.1, 'returncode': -15,
         'terminate': 'terminated'}, 0.5)
    assert ok is False and status == 'unexpected_exceeded'


def test_no_result_shape_can_ever_be_unconditionally_true():
    """穷举：judge_timeout 必须对失败输入返回 False（旧实现恒 True）。"""
    false_cases = 0
    for exceeded in (None, 'TIMEOUT', 'STDOUT_TOO_LARGE', 'NOT_FOUND'):
        for rc in (None, 0, 1, -15):
            for terminate in (None, 'terminated', 'terminated+unreaped'):
                for elapsed in (0.001, 5.0, 120.0):
                    ok, _s, _d = cmm.judge_timeout(
                        {'exceeded': exceeded, 'elapsed': elapsed,
                         'returncode': rc, 'terminate': terminate}, 0.001)
                    if not ok:
                        false_cases += 1
    assert false_cases > 0, 'judge_timeout 对任何输入都不判负 —— 与旧实现同样无效'


# ===========================================================================
# 2) 真实故障子进程：进程序列与 LIM-01 判定一致
# ===========================================================================

def test_real_hanging_module_is_terminated_and_judged_pass():
    r = cmm.invoke([sys.executable, os.path.join(FAULTY, 'hang.py')],
                   ENVELOPE, timeout=0.5, max_bytes=65536)
    ok, status, detail = cmm.judge_timeout(r, 0.5)
    assert r['exceeded'] == 'TIMEOUT', r
    assert r['returncode'] < 0, r
    assert r['elapsed'] <= 0.5 + cmm.TIMEOUT_GRACE_SEC, r
    assert ok is True and status == 'timeout_terminated', (status, detail)


def test_real_fast_module_completes_cleanly():
    """快速模块在小超时下应**自行结束**，而不是被判超时 —— 且不得挂起。"""
    script = os.path.join(FAULTY, 'quick_ok.py')
    assert os.path.isfile(script), '正例 fixture 缺失: ' + script
    r = cmm.invoke([sys.executable, script], ENVELOPE, timeout=5.0,
                   max_bytes=65536)
    ok, status, detail = cmm.judge_timeout(r, 5.0)
    assert ok is True, detail
    assert r['elapsed'] < 5.0


def test_timeout_verdict_rejects_forged_never_terminated_result():
    """模拟「超时后进程从未被终止」：必须判负（旧实现会记 PASS）。"""
    forged = {'exceeded': 'TIMEOUT', 'elapsed': 300.0, 'returncode': None,
              'terminate': None}
    ok, status, _ = cmm.judge_timeout(forged, 0.001)
    assert ok is False and status == 'timeout_not_contained'


# ===========================================================================
# 3) 端到端：LIM-01 真的会因为失败条件记为 FAIL
# ===========================================================================

def _run_checker(config, out_dir, run_id, fixture=None):
    command = [sys.executable, CHECKER, '--module', 'task_risk',
               '--config', config, '--out-dir', out_dir, '--run-id', run_id]
    if fixture:
        command += ['--real-fixture', fixture]
    return subprocess.run(command, capture_output=True, text=True,
                          timeout=900, cwd=REPO)


def test_lim01_passes_on_real_module(tmp_path):
    proc = _run_checker(MOCK_CONFIG, str(tmp_path), 'lim01-mock')
    report = json.loads((tmp_path / 'lim01-mock' / 'report.json')
                        .read_text(encoding='utf-8'))
    entry = {c['id']: c for c in report['checks']}['LIM-01']
    assert entry['status'] == 'PASS', entry
    # 判定必须基于可核验事实，而不是恒真表达式
    assert entry['timeout_verdict'] in ('clean_completion', 'timeout_terminated')
    assert entry['effective_timeout_sec'] == 0.001
    assert 'returncode' in entry and 'elapsed_sec' in entry


def test_lim01_records_fail_when_termination_is_not_contained(monkeypatch,
                                                             tmp_path):
    """故障注入：让 invoke 返回「超时但未终止」的结果，LIM-01 必须 FAIL。

    这是对「无条件 PASS」的直接反例 —— 旧实现在同样的输入下仍会记 PASS。
    """
    real_invoke = cmm.invoke

    def fake_invoke(command, envelope, timeout, max_bytes, stdin_text=None):
        result = real_invoke(command, envelope, timeout, max_bytes, stdin_text)
        if timeout <= 0.002:          # 只有极小超时那次被投毒
            result = dict(result)
            result.update({'exceeded': 'TIMEOUT', 'returncode': None,
                           'terminate': None, 'elapsed': 120.0,
                           'stdout': '', 'stdout_bytes': 0})
        return result

    monkeypatch.setattr(cmm, 'invoke', fake_invoke)
    out_dir = tmp_path / 'inject'
    rc = cmm.main(['--module', 'task_risk', '--config', MOCK_CONFIG,
                   '--out-dir', str(out_dir), '--run-id', 'lim01-inject'])
    report = json.loads((out_dir / 'lim01-inject' / 'report.json')
                        .read_text(encoding='utf-8'))
    entry = {c['id']: c for c in report['checks']}['LIM-01']
    assert entry['status'] == 'FAIL', entry
    assert entry['timeout_verdict'] == 'timeout_not_contained'
    assert rc != 0, 'LIM-01 失败时必须导致门槛不通过'


# ===========================================================================
# 4) judge_exit_consistency 与 REAL-STATE 的退出码条件
# ===========================================================================

def test_exit_consistency_rules():
    ok, _ = cmm.judge_exit_consistency({'stdout': '{"a":1}', 'returncode': 0})
    assert ok is True
    # 有结构化输出却非零退出 -> 不一致
    ok, detail = cmm.judge_exit_consistency(
        {'stdout': '{"a":1}', 'returncode': 1})
    assert ok is False and 'rc=1' in detail
    # 无结构化输出时，非零退出是合法的失败关闭信号
    ok, _ = cmm.judge_exit_consistency({'stdout': '', 'returncode': 2})
    assert ok is True
    ok, _ = cmm.judge_exit_consistency({'stdout': '   ', 'returncode': 2})
    assert ok is True
    # 未启动/被信号杀死：stdout 为空 -> 不在本项判负
    ok, _ = cmm.judge_exit_consistency({'stdout': '', 'returncode': None})
    assert ok is True


def _nonzero_exit_valid_json_module(tmp_path):
    """输出完全合法且状态正确，但以 rc=1 退出 —— 必须被判负。"""
    module = tmp_path / 'nonzero_exit.py'
    module.write_text(textwrap.dedent('''
        import json, sys
        env = json.load(sys.stdin)
        # 模拟真实模块：先把合法输出写出去，再以非零状态退出
        json.dump({
            "schema_version": "1.0.0-proposed",
            "run_id": env["run_id"], "request_id": env["request_id"],
            "event_id": "m3-{0}-fake".format(env["request_id"]),
            "producer": {"name": "fake", "source": "EXTERNAL",
                         "module_version": "0"},
            "observed_at": "2026-10-16T00:00:00Z",
            "status": "UNKNOWN", "task_id": env["candidate_action"]["task_id"],
            "candidate_action": {"action_resource": "/rg/guarded_navigate",
                                 "operation": "NAVIGATE"},
            "target": env["candidate_action"]["target"],
            "risk_level": "UNKNOWN",
            "reason": "POLICY_MISSING: 本地策略不可用",
            "rule_basis": ["fail closed"],
            "evidence_refs": [{"ref": "fake", "kind": "UNKNOWN"}],
            "policy_ref": {"policy_version": "1.0"},
            "extensions": {"member3": {"reason_code": "POLICY_MISSING"}},
        }, sys.stdout)
        sys.exit(1)
    '''), encoding='utf-8')
    return module


def test_real_state_fails_on_nonzero_exit_despite_valid_json(tmp_path):
    """反例：合法 JSON + 期望状态，但 rc=1 -> REAL-STATE 必须 FAIL。"""
    module = _nonzero_exit_valid_json_module(tmp_path)
    config = cmm.load_yaml(REAL_CONFIG)
    config['modules']['task_risk']['command'] = [sys.executable, str(module)]
    config['real_command_profiles'] = {
        key: {'command': [sys.executable, str(module)]}
        for key in config['real_command_profiles']}
    cfg = tmp_path / 'nonzero.yaml'
    cfg.write_text(json.dumps(config), encoding='utf-8')

    _run_checker(str(cfg), str(tmp_path), 'nonzero', fixture=REAL_FIXTURE)
    report = json.loads((tmp_path / 'nonzero' / 'report.json')
                        .read_text(encoding='utf-8'))
    checks = {c['id']: c for c in report['checks']}
    # 状态与 Schema 都对，但退出码不允许 -> 不得通过
    row = {r['scenario']: r for r in report['real_state_matrix']}['unknown']
    assert row['actual_state'] == 'UNKNOWN'
    assert row['schema_ok'] is True
    assert row['returncode'] == 1
    assert row['returncode_ok'] is False
    assert row['passed'] is False
    assert checks['REAL-STATE-UNKNOWN']['status'] == 'FAIL'
    assert report['meets_pr_gate'] is False


def test_real_state_passes_on_zero_exit(tmp_path):
    """正例对照：同一 fixture 配真实模块（rc=0）必须全部通过。"""
    _run_checker(REAL_CONFIG, str(tmp_path), 'zeroexit', fixture=REAL_FIXTURE)
    report = json.loads((tmp_path / 'zeroexit' / 'report.json')
                        .read_text(encoding='utf-8'))
    for row in report['real_state_matrix']:
        assert row['returncode'] == 0, row
        assert row['returncode_ok'] is True, row
        assert row['passed'] is True, row
    assert report['meets_pr_gate'] is True


def test_blocking_states_still_pass_with_zero_exit(tmp_path):
    """UNKNOWN/ERROR 是**合法安全阻断**：结构合法且 rc==0 时仍应通过。"""
    _run_checker(REAL_CONFIG, str(tmp_path), 'blocks', fixture=REAL_FIXTURE)
    report = json.loads((tmp_path / 'blocks' / 'report.json')
                        .read_text(encoding='utf-8'))
    checks = {c['id']: c for c in report['checks']}
    for name, want in (('UNKNOWN', 'UNKNOWN'), ('ERROR', 'ERROR'),
                       ('BLOCK', 'BLOCK_RECOMMENDED')):
        entry = checks['REAL-STATE-{0}'.format(name)]
        assert entry['status'] == 'PASS', entry
        assert entry['actual_state'] == want
        assert entry['security_class'] == 'LEGAL_BLOCK'
        assert entry['schema_valid'] is True
