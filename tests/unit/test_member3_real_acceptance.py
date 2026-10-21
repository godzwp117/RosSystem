#!/usr/bin/env python3
"""M3 回归：真实模块通用验收（真实条件触发 + 反「假通过」）。

覆盖任务书要求
--------------
1. 原有 Mock 模式与检查保持兼容（不带 `--real-fixture` 时行为不变）。
2. 真实模块不必解析 `f0_mock.scenario`。
3. 四种状态各由**真实条件**触发：合法任务 / 违规任务 / 缺少策略 / 损坏策略。
4. 场景输入、受信任模块配置、期望状态、实际输出四者可追溯。
5. 业务 JSON 不能指定本地命令、策略文件或可执行文件。
6. 不得通过删除检查项、修改期望状态或降低门槛获得 PASS。
7. 验收器检查**实际状态**，而不是仅检查预期场景标签。
8. 原有超时、stdout/stderr、请求 ID、Schema 与失败关闭测试保持有效。

反假通过（本节重点）
--------------------
验收器必须把「未执行」「不满足条件」的真实模块判为**失败**，因此这里故意
构造若干坏模块（静默退出 / 挂起 / 非法 JSON / 无视策略恒返回 ALLOW /
不返回状态字段），并要求对应检查项为 FAIL。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'scripts'))

import check_member_module as cmm  # noqa: E402

CHECKER = REPO / 'scripts' / 'check_member_module.py'
REAL_CONFIG = REPO / 'config' / 'team_modules.member3.real.yaml'
REAL_FIXTURE = REPO / 'config' / 'acceptance' / 'real_scenarios.member3.yaml'
MOCK_CONFIG = REPO / 'config' / 'team_modules.example.yaml'
REAL_MODULE = REPO / 'modules' / 'member3_taskrisk' / 'module.py'


def run_checker(module, config, tmp_path, run_id, fixture=None, timeout=600):
    command = [sys.executable, str(CHECKER), '--module', module,
               '--config', str(config), '--out-dir', str(tmp_path),
               '--run-id', run_id]
    if fixture:
        command += ['--real-fixture', str(fixture)]
    return subprocess.run(command, capture_output=True, text=True,
                          timeout=timeout, cwd=REPO)


def report_of(tmp_path, run_id):
    return json.loads((tmp_path / run_id / 'report.json').read_text(encoding='utf-8'))


def by_id(report):
    return {c['id']: c for c in report['checks']}


def real_rows(report):
    return {r['scenario']: r for r in report.get('real_state_matrix', [])}


# ---------------------------------------------------------------------------
# fixture 与配置本身
# ---------------------------------------------------------------------------

def test_fixture_shape_is_valid():
    config = cmm.load_yaml(str(REAL_CONFIG))
    fixture = cmm.parse_real_fixture(str(REAL_FIXTURE), 'task_risk', config)
    names = [s['name'] for s in fixture['scenarios']]
    assert names == ['allow', 'block', 'unknown', 'error']
    states = {s['name']: s['expected_state'] for s in fixture['scenarios']}
    assert states == {'allow': 'ALLOW_RECOMMENDED',
                      'block': 'BLOCK_RECOMMENDED',
                      'unknown': 'UNKNOWN', 'error': 'ERROR'}
    classes = {s['name']: s['expected_class'] for s in fixture['scenarios']}
    assert classes == {'allow': 'PROCEED', 'block': 'LEGAL_BLOCK',
                       'unknown': 'LEGAL_BLOCK', 'error': 'LEGAL_BLOCK'}


def test_command_profiles_live_in_trusted_config_only():
    config = cmm.load_yaml(str(REAL_CONFIG))
    profiles = config['real_command_profiles']
    assert set(profiles) == {'policy_valid', 'policy_tight_region',
                             'policy_absent', 'policy_corrupt'}
    fixture = cmm.parse_real_fixture(str(REAL_FIXTURE), 'task_risk', config)
    for scenario in fixture['scenarios']:
        # 命令来自配置档案，且 fixture 只携带档案名
        assert scenario['command'][0] == sys.executable
        assert '--policy' in scenario['command']
        assert scenario['command_profile'] in profiles


def test_fixture_cannot_smuggle_commands_or_policy_paths(tmp_path):
    """业务输入携带本地执行控制字段必须被拒绝（失败关闭）。"""
    for key in ('command', 'exec', 'policy', 'env', 'cwd', 'workdir',
                'shell', 'executable', 'script'):
        document = yaml.safe_load(REAL_FIXTURE.read_text(encoding='utf-8'))
        document['real_scenarios']['task_risk'][0]['envelope_patch'][key] = '/bin/sh'
        bad = tmp_path / 'bad-{0}.yaml'.format(key)
        bad.write_text(yaml.safe_dump(document, allow_unicode=True), encoding='utf-8')
        with pytest.raises(cmm.FixtureError) as info:
            cmm.parse_real_fixture(str(bad), 'task_risk',
                                   cmm.load_yaml(str(REAL_CONFIG)))
        assert '本地执行控制字段' in str(info.value)


def test_fixture_cannot_escape_repo_with_policy_path(tmp_path):
    document = yaml.safe_load(REAL_FIXTURE.read_text(encoding='utf-8'))
    document['real_scenarios']['task_risk'][0]['policy'] = '../../etc/passwd'
    bad = tmp_path / 'escape.yaml'
    bad.write_text(yaml.safe_dump(document, allow_unicode=True), encoding='utf-8')
    with pytest.raises(cmm.FixtureError) as info:
        cmm.parse_real_fixture(str(bad), 'task_risk',
                               cmm.load_yaml(str(REAL_CONFIG)))
    assert '越出仓库范围' in str(info.value)


def test_fixture_rejects_inconsistent_expected_class(tmp_path):
    """不能声明 PROCEED 却把阻断状态写成期望（期望必须自洽）。"""
    document = yaml.safe_load(REAL_FIXTURE.read_text(encoding='utf-8'))
    document['real_scenarios']['task_risk'][1]['expected_class'] = 'PROCEED'
    bad = tmp_path / 'inconsistent.yaml'
    bad.write_text(yaml.safe_dump(document, allow_unicode=True), encoding='utf-8')
    with pytest.raises(cmm.FixtureError) as info:
        cmm.parse_real_fixture(str(bad), 'task_risk',
                               cmm.load_yaml(str(REAL_CONFIG)))
    assert '不自洽' in str(info.value)


def test_fixture_rejects_state_outside_module_enum(tmp_path):
    document = yaml.safe_load(REAL_FIXTURE.read_text(encoding='utf-8'))
    document['real_scenarios']['task_risk'][0]['expected_state'] = 'MADE_UP'
    bad = tmp_path / 'enum.yaml'
    bad.write_text(yaml.safe_dump(document, allow_unicode=True), encoding='utf-8')
    with pytest.raises(cmm.FixtureError):
        cmm.parse_real_fixture(str(bad), 'task_risk',
                               cmm.load_yaml(str(REAL_CONFIG)))


def test_unknown_command_profile_is_rejected():
    with pytest.raises(cmm.FixtureError) as info:
        cmm.resolve_profile_command(['python3', 'x.py'], {'real_command_profiles': {}},
                                    'nope')
    assert '不存在档案' in str(info.value)


def test_policy_file_state_is_independent_ground_truth():
    """验收器独立判定策略真实状态，不依赖模块或 fixture 自报。"""
    assert cmm.policy_file_state('config/task_policy.yaml') == 'VALID'
    assert cmm.policy_file_state(
        'config/scenarios/task_policy_tight_region.yaml') == 'VALID'
    assert cmm.policy_file_state(
        'config/scenarios/task_policy_absent.yaml') == 'ABSENT'
    assert cmm.policy_file_state(
        'config/scenarios/task_policy_corrupt.yaml') == 'CORRUPT'
    assert cmm.policy_file_state(None) == 'UNKNOWN'


def test_authoritative_policy_is_untouched_by_fixtures():
    """缺失/损坏策略必须是隔离 fixture，正式权威策略不得被改动。"""
    authoritative = REPO / 'config' / 'task_policy.yaml'
    data = yaml.safe_load(authoritative.read_text(encoding='utf-8'))
    assert data['active'] is True
    assert data['task_id'] == 'patrol_a_001'
    assert data['allowed_region'] == {'x_min': 0.0, 'x_max': 4.0,
                                      'y_min': 0.0, 'y_max': 4.0}
    # absent fixture 必须真的不存在，否则 UNKNOWN 场景失效
    assert not (REPO / 'config' / 'scenarios' / 'task_policy_absent.yaml').exists()
    # corrupt fixture 必须真的不可解析
    assert cmm.policy_file_state(
        'config/scenarios/task_policy_corrupt.yaml') == 'CORRUPT'


# ---------------------------------------------------------------------------
# 真实四状态（端到端）
# ---------------------------------------------------------------------------

@pytest.fixture(scope='module')
def real_run(tmp_path_factory):
    out = tmp_path_factory.mktemp('real-acceptance')
    proc = run_checker('task_risk', REAL_CONFIG, out, 'm3-real',
                       fixture=REAL_FIXTURE)
    report = report_of(out, 'm3-real')
    return proc, report


def test_real_module_four_states_triggered_by_real_conditions(real_run):
    proc, report = real_run
    rows = real_rows(report)
    assert set(rows) == {'allow', 'block', 'unknown', 'error'}, rows
    for name, row in rows.items():
        assert row['structured'] is True, (name, row)
        assert row['schema_ok'] is True, (name, row)
        assert row['ids_ok'] is True, (name, row)
        assert row['actual_state'] == row['expected_state'], (name, row)
        assert row['actual_class'] == row['expected_class'], (name, row)
        assert row['traceability_ok'] is True, (name, row)
    assert rows['allow']['actual_state'] == 'ALLOW_RECOMMENDED'
    assert rows['block']['actual_state'] == 'BLOCK_RECOMMENDED'
    assert rows['unknown']['actual_state'] == 'UNKNOWN'
    assert rows['error']['actual_state'] == 'ERROR'


def test_real_module_reports_real_reason_codes(real_run):
    _proc, report = real_run
    rows = real_rows(report)
    assert rows['allow']['actual_reason_code'] == 'ALLOW_IN_POLICY'
    assert rows['block']['actual_reason_code'] == 'OUT_OF_REGION'
    assert rows['unknown']['actual_reason_code'] == 'POLICY_MISSING'
    assert rows['error']['actual_reason_code'] == 'POLICY_MISSING'
    # 真实条件对应的策略文件真实状态
    assert rows['allow']['policy_file_state'] == 'VALID'
    assert rows['block']['policy_file_state'] == 'VALID'
    assert rows['unknown']['policy_file_state'] == 'ABSENT'
    assert rows['error']['policy_file_state'] == 'CORRUPT'


def test_block_is_not_a_schema_error(real_run):
    """阻断状态结构合法，是 LEGAL_BLOCK 而非 Schema 错误。"""
    _proc, report = real_run
    checks = by_id(report)
    assert checks['REAL-STATE-SCHEMA']['status'] == 'PASS'
    for name in ('block', 'unknown', 'error'):
        row = real_rows(report)[name]
        assert row['schema_ok'] is True
        assert row['actual_class'] == 'LEGAL_BLOCK'


def test_f0_blocks_real_blocking_states(real_run):
    _proc, report = real_run
    checks = by_id(report)
    for name in ('BLOCK', 'UNKNOWN', 'ERROR'):
        entry = checks['REAL-ADP-{0}'.format(name)]
        assert entry['status'] == 'PASS', entry
        assert entry['decision'] == 'ADAPTER_BLOCK'
        assert entry['returncode'] != 0


def test_legal_condition_only_yields_ready_for_gateway_submission(real_run):
    _proc, report = real_run
    entry = by_id(report)['REAL-ADP-ALLOW']
    assert entry['status'] == 'PASS', entry
    assert entry['decision'] == 'READY_FOR_GATEWAY_SUBMISSION'
    # READY 不是 Gateway ALLOW，也不是执行成功
    assert entry.get('gateway_decision') is None


def test_real_fixture_run_reaches_pr_gate(real_run):
    proc, report = real_run
    assert report['meets_pr_gate'] is True, report.get('counts')
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]


def test_mock_matrix_is_recorded_but_not_applicable(real_run):
    """mock 场景开关对真实模块不适用：记录保留、门槛由真实矩阵承担。"""
    _proc, report = real_run
    checks = by_id(report)
    for name in ('BLOCK', 'UNKNOWN', 'ERROR'):
        entry = checks['STATE-{0}'.format(name)]
        # 未删检查项：仍然存在于报告中并如实标注状态
        assert entry['mandatory'] is False
        assert entry['gate'] is False
        assert entry['applicability'] == 'NOT_APPLICABLE_REAL_MODULE'
        assert entry['status'] == 'FAIL'          # 如实记录，未被改成 PASS
    # 每个不适用项都指向对应的真实条件检查
    assert 'REAL-STATE-BLOCK' in checks['STATE-BLOCK']['detail']
    assert checks['REAL-STATE-BLOCK']['status'] == 'PASS'
    assert checks['REAL-STATE-UNKNOWN']['status'] == 'PASS'
    assert checks['REAL-STATE-ERROR']['status'] == 'PASS'


def test_l3_remains_blocked_without_ros(real_run):
    """没有 ROS 2 环境时 L3 必须保持 BLOCKED，不能用离线测试代替。"""
    _proc, report = real_run
    assert by_id(report)['LAYER-03']['status'] == 'BLOCKED'


# ---------------------------------------------------------------------------
# Mock 模式向后兼容
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('module', ['comm_risk', 'identity_trust', 'task_risk'])
def test_mock_mode_still_passes_without_real_fixture(module, tmp_path):
    proc = run_checker(module, MOCK_CONFIG, tmp_path, 'mock-' + module)
    report = report_of(tmp_path, 'mock-' + module)
    assert report['meets_pr_gate'] is True, report.get('counts')
    assert proc.returncode == 0
    checks = by_id(report)
    for name in ('ALLOW', 'BLOCK', 'UNKNOWN', 'ERROR'):
        pass
    for scenario in ('NORMAL', 'SUSPICIOUS', 'UNKNOWN', 'ERROR',
                     'AUTHORIZED', 'DENIED', 'ALLOW', 'BLOCK'):
        cid = 'STATE-{0}'.format(scenario)
        if cid in checks:
            assert checks[cid]['mandatory'] is True
            assert checks[cid]['gate'] is True
            assert checks[cid]['status'] == 'PASS', checks[cid]


def test_mock_mode_states_are_mandatory_and_gating(tmp_path):
    """不带 --real-fixture 时，mock 状态矩阵仍是强制项（门槛未被放松）。"""
    run_checker('task_risk', MOCK_CONFIG, tmp_path, 'mock-gate')
    report = report_of(tmp_path, 'mock-gate')
    for cid in ('STATE-ALLOW', 'STATE-BLOCK', 'STATE-UNKNOWN', 'STATE-ERROR'):
        entry = by_id(report)[cid]
        assert entry['mandatory'] is True
        assert entry['gate'] is True


# ---------------------------------------------------------------------------
# 反假通过：坏模块必须判 FAIL
# ---------------------------------------------------------------------------

BROKEN_MODULES = {
    # 静默退出：不产出任何结构化输出
    'silent': 'import sys\nsys.exit(0)\n',
    # 挂起：必须在超时后被终止且不得判成功
    'hang': 'import time\ntime.sleep(300)\n',
    # 非法 JSON：stdout 不是 JSON
    'garbage': 'print("not json at all")\n',
    # 恒返回 ALLOW：无视策略内容与候选目标
    'always_allow': textwrap.dedent('''
        import json, sys
        env = json.load(sys.stdin)
        print(json.dumps({
            "schema_version": "1.0.0-proposed", "run_id": env["run_id"],
            "request_id": env["request_id"], "event_id": "fake-" + env["request_id"],
            "producer": {"name": "fake", "source": "EXTERNAL",
                         "module_version": "0"},
            "observed_at": "2026-10-12T12:00:00Z", "status": "ALLOW_RECOMMENDED",
            "task_id": env["candidate_action"]["task_id"],
            "candidate_action": {"action_resource": "/rg/guarded_navigate",
                                 "operation": "NAVIGATE"},
            "target": env["candidate_action"]["target"],
            "risk_level": "NONE", "reason": "always allow",
            "rule_basis": ["fake"], "evidence_refs": [{"ref": "fake", "kind": "MOCK"}],
        }))
    '''),
    # 状态字段缺失：结构非法
    'no_status': textwrap.dedent('''
        import json, sys
        env = json.load(sys.stdin)
        print(json.dumps({"run_id": env["run_id"], "request_id": env["request_id"]}))
    '''),
}


def make_broken_config(tmp_path, name, extra_env=None):
    """把坏模块命令写进一份临时受信任配置（命令仍只来自配置文件）。"""
    config = cmm.load_yaml(str(REAL_CONFIG))
    script = tmp_path / 'broken_{0}.py'.format(name)
    script.write_text(BROKEN_MODULES[name], encoding='utf-8')
    config['modules']['task_risk']['command'] = [sys.executable, str(script)]
    # 档案统一指向坏模块，去掉真实模块的 --policy 参数
    config['real_command_profiles'] = {
        key: {'command': [sys.executable, str(script)]}
        for key in config['real_command_profiles']}
    path = tmp_path / 'config_{0}.yaml'.format(name)
    path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding='utf-8')
    return path


@pytest.mark.parametrize('name', sorted(BROKEN_MODULES))
def test_broken_module_is_never_accepted(name, tmp_path):
    """未执行 / 不满足条件的真实模块必须判 FAIL 且达不到门槛。"""
    config = make_broken_config(tmp_path, name)
    proc = run_checker('task_risk', config, tmp_path, 'broken-' + name,
                       fixture=REAL_FIXTURE, timeout=900)
    report = report_of(tmp_path, 'broken-' + name)
    checks = by_id(report)
    # 四个真实状态一律不得通过
    for scenario in ('ALLOW', 'BLOCK', 'UNKNOWN', 'ERROR'):
        cid = 'REAL-STATE-{0}'.format(scenario)
        assert checks[cid]['status'] == 'FAIL', (name, cid, checks[cid])
    assert checks['REAL-STATE-SUMMARY']['status'] == 'FAIL'
    assert report['meets_pr_gate'] is False
    assert proc.returncode != 0


def test_hanging_module_is_terminated_not_accepted(tmp_path):
    """挂起模块必须被超时终止，且不得因为「进程不再运行」而算通过。"""
    config = make_broken_config(tmp_path, 'hang')
    proc = run_checker('task_risk', config, tmp_path, 'broken-hang',
                       fixture=REAL_FIXTURE, timeout=900)
    report = report_of(tmp_path, 'broken-hang')
    checks = by_id(report)
    assert checks['REAL-STATE-ALLOW']['status'] == 'FAIL'
    assert report['meets_pr_gate'] is False
    assert proc.returncode != 0


def test_always_allow_module_fails_on_blocking_scenarios(tmp_path):
    """恒返回 ALLOW 的模块必须在 BLOCK/UNKNOWN/ERROR 场景被判 FAIL。

    这正是「只检查预期场景标签」会漏掉的情形：真实状态与期望相反，
    验收器必须以**实际状态**判负。

    更强的一点：该假模块不读取任何策略，因此即使某个场景的期望状态「碰巧」
    是 ALLOW_RECOMMENDED，也会因为无法回引真实读取的策略而判负 ——
    说明追溯检查不是走过场。
    """
    config = make_broken_config(tmp_path, 'always_allow')
    run_checker('task_risk', config, tmp_path, 'broken-allow',
                fixture=REAL_FIXTURE, timeout=900)
    report = report_of(tmp_path, 'broken-allow')
    checks = by_id(report)
    assert checks['REAL-STATE-BLOCK']['status'] == 'FAIL'
    assert checks['REAL-STATE-UNKNOWN']['status'] == 'FAIL'
    assert checks['REAL-STATE-ERROR']['status'] == 'FAIL'
    # 连「碰巧」状态相同的合法场景也失败：没有可追溯的策略依据
    assert checks['REAL-STATE-ALLOW']['status'] == 'FAIL'
    assert checks['REAL-STATE-ALLOW']['actual_state'] == 'ALLOW_RECOMMENDED'
    assert report['meets_pr_gate'] is False


def test_fake_policy_citation_cannot_buy_traceability(tmp_path):
    """只在输出里编造策略路径不足以通过追溯：必须与真实文件状态自洽。

    构造一个「恒报 ALLOW 且回引策略路径」的模块；由于 absent/corrupt 场景
    的策略文件真实状态分别是 ABSENT/CORRUPT，它仍然必须失败。
    """
    script = tmp_path / 'fake_cite.py'
    script.write_text(textwrap.dedent('''
        import json, sys
        env = json.load(sys.stdin)
        print(json.dumps({
            "schema_version": "1.0.0-proposed", "run_id": env["run_id"],
            "request_id": env["request_id"], "event_id": "fake-" + env["request_id"],
            "producer": {"name": "fake", "source": "EXTERNAL", "module_version": "0"},
            "observed_at": "2026-10-12T12:00:00Z", "status": "ALLOW_RECOMMENDED",
            "task_id": env["candidate_action"]["task_id"],
            "candidate_action": {"action_resource": "/rg/guarded_navigate",
                                 "operation": "NAVIGATE"},
            "target": env["candidate_action"]["target"],
            "risk_level": "NONE", "reason": "fake",
            "rule_basis": ["fake"],
            "evidence_refs": [
                {"ref": "config/task_policy.yaml", "kind": "UNKNOWN"},
                {"ref": "config/scenarios/task_policy_absent.yaml", "kind": "UNKNOWN"},
                {"ref": "config/scenarios/task_policy_corrupt.yaml", "kind": "UNKNOWN"}],
            "policy_ref": {"policy_version": "1.0"},
        }))
    '''), encoding='utf-8')
    config = cmm.load_yaml(str(REAL_CONFIG))
    config['modules']['task_risk']['command'] = [sys.executable, str(script)]
    config['real_command_profiles'] = {
        key: {'command': [sys.executable, str(script)]}
        for key in config['real_command_profiles']}
    path = tmp_path / 'fake_cite.yaml'
    path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding='utf-8')
    run_checker('task_risk', path, tmp_path, 'fake-cite',
                fixture=REAL_FIXTURE, timeout=900)
    report = report_of(tmp_path, 'fake-cite')
    checks = by_id(report)
    assert checks['REAL-STATE-UNKNOWN']['status'] == 'FAIL'
    assert checks['REAL-STATE-ERROR']['status'] == 'FAIL'
    assert report['meets_pr_gate'] is False


def test_mislabeled_expected_state_would_be_caught(tmp_path):
    """把期望状态改成与真实条件不符时，验收器必须判 FAIL（期望不可自定义通关）。"""
    document = yaml.safe_load(REAL_FIXTURE.read_text(encoding='utf-8'))
    # 违规任务真实产出 BLOCK_RECOMMENDED，这里硬说它应该是 ALLOW
    document['real_scenarios']['task_risk'][1]['expected_state'] = 'ALLOW_RECOMMENDED'
    document['real_scenarios']['task_risk'][1]['expected_class'] = 'PROCEED'
    bad_fixture = tmp_path / 'mislabeled.yaml'
    bad_fixture.write_text(yaml.safe_dump(document, allow_unicode=True),
                           encoding='utf-8')
    run_checker('task_risk', REAL_CONFIG, tmp_path, 'mislabeled',
                fixture=bad_fixture)
    report = report_of(tmp_path, 'mislabeled')
    checks = by_id(report)
    entry = checks['REAL-STATE-BLOCK']
    assert entry['status'] == 'FAIL'
    assert entry['actual_state'] == 'BLOCK_RECOMMENDED'
    assert entry['expected_state'] == 'ALLOW_RECOMMENDED'


# ---------------------------------------------------------------------------
# 保持原有失败关闭 / 上限 / 请求 ID 检查
# ---------------------------------------------------------------------------

def test_original_fail_closed_checks_still_present(real_run):
    _proc, report = real_run
    checks = by_id(report)
    for cid in ('ERR-01', 'ERR-03', 'ERR-04', 'ADP-01', 'LIM-01', 'LIM-02',
                'PROTO-01', 'PROTO-04', 'ID-01', 'ID-02', 'SCH-01'):
        assert cid in checks, cid
        assert checks[cid]['status'] == 'PASS', (cid, checks[cid])


def test_real_module_does_not_read_f0_mock_switch():
    """真实模块不解析 `f0_mock.scenario`：同一输入不同开关 -> 同一状态。"""
    base = json.loads(json.dumps(cmm.build_envelope('req-probe')))
    results = []
    for scenario in ('allow', 'block', 'unknown', 'error'):
        env = json.loads(json.dumps(base))
        env['observations'][0]['detail']['f0_mock']['task_risk'] = {
            'scenario': scenario}
        proc = subprocess.run(
            [sys.executable, str(REAL_MODULE), '--policy', 'config/task_policy.yaml'],
            input=json.dumps(env), capture_output=True, text=True, cwd=REPO,
            timeout=120)
        results.append(json.loads(proc.stdout)['status'])
    assert results == ['ALLOW_RECOMMENDED'] * 4


# ---------------------------------------------------------------------------
# 解释器统一（兼容性修复的直接覆盖）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('alias', ['python', 'python3', 'python3.10',
                                   'python3.11', 'python3.12', 'python3.13'])
def test_bare_python_alias_maps_to_current_interpreter(alias):
    """裸 python 别名必须映射到当前验收进程的解释器。

    交付配置写 `python3`，而真实模块需要 jsonschema>=4；若验收器自身跑在
    满足依赖的解释器里、却用 PATH 上另一个 python3 调模块，会得到
    「模块不可运行」的假失败。只改解释器，不改任何参数。
    """
    resolved = cmm.resolve_interpreter([alias, 'modules/x.py', '--policy', 'p.yaml'])
    assert resolved[0] == sys.executable
    assert resolved[1:] == ['modules/x.py', '--policy', 'p.yaml']


def test_non_python_command_is_not_rewritten():
    """非 python 命令必须原样保留（不越权改写受信任配置）。"""
    original = ['/usr/bin/env', 'ros2', 'run', 'rg_demo_nodes', 'planner_node']
    assert cmm.resolve_interpreter(original) == original


def test_absolute_python_path_is_not_rewritten():
    """显式绝对路径解释器视为运维有意选择，不覆盖。"""
    original = ['/opt/venv/bin/python3', 'module.py']
    assert cmm.resolve_interpreter(original) == original


def test_profile_args_keep_module_and_append_only():
    """args 档案只能追加到模块命令之后，不能替换模块本身。"""
    config = {'real_command_profiles': {'p': {'args': ['--policy', 'x.yaml']}}}
    composed = cmm.resolve_profile_command(
        ['python3', 'modules/member3_taskrisk/module.py'], config, 'p')
    assert composed[0] == sys.executable
    assert composed[1] == 'modules/member3_taskrisk/module.py'
    assert composed[2:] == ['--policy', 'x.yaml']
