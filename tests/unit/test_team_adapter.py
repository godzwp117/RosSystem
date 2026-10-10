"""安全失败关闭与真实替换测试（S-01 ~ S-18 + 替换验收）。

原则
----
* 每个用例都通过**真实适配层进程**执行并断言其真实返回的判定与退出码，
  不用参考函数推断"理论上应该拒绝"。
* 唯一允许推进的结论是 `READY_FOR_GATEWAY_SUBMISSION`；且该结论**不代表**
  Gateway 已允许，也不代表下游已执行。
* 故障注入只能由受信任配置开启，输入无法打开它。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

pytest.importorskip('jsonschema', reason='需要 jsonschema>=4.0（Draft 2020-12）')

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(ROOT, 'scripts')
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import validate_team_contracts as vtc  # noqa: E402
import team_demo  # noqa: E402  （适配层模块，用于错误码命名空间检查）
from test_team_process_protocol import (  # noqa: E402
    ADAPTER, EXIT_BLOCK, EXIT_READY, envelope, proceed_control, run_adapter,
    write_config,
)

FIXTURES = os.path.join(ROOT, 'tests', 'fixtures', 'team_modules')


def double_config(tmp_path, *, timeouts=None):
    return write_config(tmp_path, mode='double', allow_faults=False,
                        timeouts=timeouts)


def doubles_envelope(*, comm=None, identity=None, target=None, **kwargs):
    """构造供测试替身使用的输入（替身按数据规则计算，不读场景开关）。"""
    detail = {
        'comm': comm or {'request_count': 3, 'baseline_count': 3},
        'identity': identity or {'subject': 'planner_node',
                                 'resource': '/rg/guarded_navigate',
                                 'operation': 'SERVICE_REQUEST'},
    }
    return envelope(None, target=target, observations_detail=detail, **kwargs)


# ---------------------------------------------------------------- S-01..S-06
def test_s01_all_three_proceed_gives_ready(tmp_path):
    """S-01 三模块均为推进状态 → READY_FOR_GATEWAY_SUBMISSION。"""
    config = write_config(tmp_path)
    code, result, _err = run_adapter(tmp_path, envelope(proceed_control()), config)
    assert code == EXIT_READY
    assert result['decision'] == 'READY_FOR_GATEWAY_SUBMISSION'
    assert result['reason_code'] == 'ADAPTER_OK'
    # 结果中必须明确其边界，不得被读成 Gateway 已允许
    assert '不代表 Gateway' in result['note']
    assert result['decision'] != 'Gateway ALLOW'.replace(' ', '_')


@pytest.mark.parametrize('module,scenario,status', [
    ('comm_risk', 'suspicious', 'SUSPICIOUS'),
    ('identity_trust', 'denied', 'DENIED'),
    ('task_risk', 'block', 'BLOCK_RECOMMENDED'),
])
def test_s02_to_s04_business_rejections_block(tmp_path, module, scenario, status):
    """S-02/S-03/S-04 任一模块给出业务拒绝状态 → 本地阻断。"""
    config = write_config(tmp_path)
    control = proceed_control(**{module: {'scenario': scenario}})
    code, result, _err = run_adapter(tmp_path, envelope(control), config)
    assert code == EXIT_BLOCK
    assert result['decision'] == 'ADAPTER_BLOCK'
    assert result['reason_code'] == 'ADAPTER_MODULE_STATUS_NOT_PROCEED'
    assert status in result['detail']


@pytest.mark.parametrize('module,scenario', [
    ('comm_risk', 'unknown'), ('comm_risk', 'error'),
    ('identity_trust', 'unknown'), ('identity_trust', 'error'),
    ('task_risk', 'unknown'), ('task_risk', 'error'),
])
def test_s05_s06_unknown_and_error_never_proceed(tmp_path, module, scenario):
    """S-05/S-06 UNKNOWN 与 ERROR 一律阻断，不得被当作允许。"""
    config = write_config(tmp_path)
    control = proceed_control(**{module: {'scenario': scenario}})
    code, result, _err = run_adapter(tmp_path, envelope(control), config)
    assert code == EXIT_BLOCK
    assert result['reason_code'] == 'ADAPTER_MODULE_STATUS_NOT_PROCEED'
    assert 'ADAPTER_BLOCK' == result['decision']


# ---------------------------------------------------------------- S-07..S-11
def test_s07_incompatible_schema_version_blocks(tmp_path):
    """S-07 Schema 版本不兼容 → 阻断。"""
    config = write_config(tmp_path)
    control = proceed_control()
    control['comm_risk'] = {'scenario': 'normal',
                            'override': {'schema_version': '9.9.9'}}
    code, result, _err = run_adapter(tmp_path, envelope(control), config)
    assert code == EXIT_BLOCK
    assert result['reason_code'] == 'ADAPTER_MODULE_SCHEMA_VERSION'


def test_s08_missing_required_field_blocks(tmp_path):
    """S-08 缺少必填字段 → 阻断。"""
    config = write_config(tmp_path)
    control = proceed_control()
    control['task_risk'] = {'scenario': 'allow', 'drop': ['rule_basis']}
    code, result, _err = run_adapter(tmp_path, envelope(control), config)
    assert code == EXIT_BLOCK
    assert result['reason_code'] == 'ADAPTER_MODULE_SCHEMA_INVALID'


def test_s09_request_id_mismatch_blocks(tmp_path):
    """S-09 request_id 不一致（串单）→ 阻断。"""
    config = write_config(tmp_path)
    control = proceed_control()
    control['identity_trust'] = {'scenario': 'authorized',
                                 'override': {'request_id': 'req-OTHER'}}
    code, result, _err = run_adapter(tmp_path, envelope(control), config)
    assert code == EXIT_BLOCK
    assert result['reason_code'] == 'ADAPTER_CONSISTENCY_REQUEST_ID'


def test_s10_run_id_mismatch_blocks(tmp_path):
    """S-10 run_id 不一致 → 阻断。"""
    config = write_config(tmp_path)
    control = proceed_control()
    control['task_risk'] = {'scenario': 'allow', 'override': {'run_id': 'run-OTHER'}}
    code, result, _err = run_adapter(tmp_path, envelope(control), config)
    assert code == EXIT_BLOCK
    assert result['reason_code'] == 'ADAPTER_CONSISTENCY_RUN_ID'


def test_s11_task_id_mismatch_blocks(tmp_path):
    """S-11 任务标识不一致 → 阻断。"""
    config = write_config(tmp_path)
    control = proceed_control()
    control['task_risk'] = {'scenario': 'allow', 'override': {'task_id': 'other_task'}}
    code, result, _err = run_adapter(tmp_path, envelope(control), config)
    assert code == EXIT_BLOCK
    assert result['reason_code'] == 'ADAPTER_CONSISTENCY_TASK_ID'


def test_s11_candidate_action_mismatch_blocks(tmp_path):
    """S-11 候选操作不一致 → 阻断。"""
    config = write_config(tmp_path)
    control = proceed_control()
    control['task_risk'] = {'scenario': 'allow', 'override': {
        'candidate_action': {'action_resource': '/rg/guarded_navigate',
                             'operation': 'NAVIGATE'},
        'task_id': 'patrol_a_001'}}
    # 先确认基线可通过，再制造动作不一致
    code_ok, result_ok, _ = run_adapter(tmp_path, envelope(control), config)
    assert code_ok == EXIT_READY, result_ok

    control2 = proceed_control()
    control2['task_risk'] = {'scenario': 'allow', 'override': {
        'candidate_action': {'action_resource': '/rg/nav_execute',
                             'operation': 'NAVIGATE'}}}
    code, result, _err = run_adapter(tmp_path, envelope(control2), config)
    # 输出 schema 的 const 会先拒绝，这本身也是正确的防线
    assert code == EXIT_BLOCK
    assert result['reason_code'] in ('ADAPTER_MODULE_SCHEMA_INVALID',
                                     'ADAPTER_CONSISTENCY_ACTION')


def test_s11_event_id_duplicate_blocks(tmp_path):
    """S-11 事件标识重复 → 阻断（去重约定）。"""
    config = write_config(tmp_path)
    control = proceed_control()
    shared = 'evt-shared-0001'
    for module in ('comm_risk', 'identity_trust', 'task_risk'):
        control[module] = dict(control[module], override={'event_id': shared})
    code, result, _err = run_adapter(tmp_path, envelope(control), config)
    assert code == EXIT_BLOCK
    assert result['reason_code'] == 'ADAPTER_CONSISTENCY_EVENT_ID'


# ---------------------------------------------------------------- S-12..S-14
def test_s12_module_timeout_blocks(tmp_path):
    """S-12 模块超时 → 阻断。"""
    config = write_config(tmp_path, allow_faults=True, timeouts={'task_risk': 2})
    control = proceed_control()
    control['fault'] = {'task_risk': 'timeout'}
    code, result, _err = run_adapter(tmp_path, envelope(control), config, timeout=180)
    assert code == EXIT_BLOCK
    assert result['reason_code'] == 'ADAPTER_MODULE_TIMEOUT'


def test_s13_module_crash_blocks(tmp_path):
    """S-13 模块崩溃（非零退出）→ 阻断。"""
    config = write_config(tmp_path, allow_faults=True)
    control = proceed_control()
    control['fault'] = {'comm_risk': 'exit_nonzero'}
    code, result, _err = run_adapter(tmp_path, envelope(control), config)
    assert code == EXIT_BLOCK
    assert result['reason_code'] == 'ADAPTER_MODULE_EXIT_NONZERO'


def test_s13_module_missing_blocks(tmp_path):
    """S-13 补充：可执行文件不存在 → 阻断且记录原因。"""
    config = write_config(tmp_path, commands={
        'comm_risk': ['python3', 'mock_modules/does_not_exist.py']})
    code, result, _err = run_adapter(tmp_path, envelope(proceed_control()), config)
    assert code == EXIT_BLOCK
    assert result['reason_code'] in ('ADAPTER_MODULE_EXIT_NONZERO',
                                     'ADAPTER_MODULE_MISSING')
    module = [m for m in result['modules'] if m['module'] == 'comm_risk'][0]
    assert module['status'] is None, '未成功的调用不得记录状态'


def test_s14_schema_valid_but_non_proceed_status_blocks(tmp_path):
    """S-14 输出结构完全合法但状态不允许推进 → 阻断。

    这条最关键：Schema 校验成功**不等于**可以推进。
    """
    config = write_config(tmp_path)
    control = proceed_control()
    # suspicious 是完全合法的 CommRiskEvidence 状态，但不是推进状态
    control['comm_risk'] = {'scenario': 'suspicious'}
    code, result, _err = run_adapter(tmp_path, envelope(control), config)
    assert code == EXIT_BLOCK
    assert result['reason_code'] == 'ADAPTER_MODULE_STATUS_NOT_PROCEED'
    module = [m for m in result['modules'] if m['module'] == 'comm_risk'][0]
    assert module['schema_ok'] is True, '本例中 Schema 必须是通过的'
    assert module['status'] == 'SUSPICIOUS'


# ---------------------------------------------------------------- S-15
def test_s15_self_reported_producer_does_not_override_a_deny(tmp_path):
    """S-15 自报 producer=gateway 不能覆盖来自模块的拒绝结论。"""
    config = write_config(tmp_path)
    control = proceed_control()
    control['identity_trust'] = {
        'scenario': 'denied',
        'override': {'producer': {'name': 'gateway', 'module_version': '9.9.9',
                                  'source': 'EXTERNAL'}},
    }
    code, result, _err = run_adapter(tmp_path, envelope(control), config)
    assert code == EXIT_BLOCK, '自报高权限来源不得把拒绝变成允许'
    assert result['reason_code'] == 'ADAPTER_MODULE_STATUS_NOT_PROCEED'


def test_s15_self_reported_producer_is_not_treated_as_a_credential(tmp_path):
    """S-15 补充：producer 是自报信息，适配层不得据此改变判定路径。

    诚实来源与自报 gateway 来源，在其余输入完全相同时必须得到**相同结论**。
    """
    config = write_config(tmp_path)
    honest = proceed_control()
    code_a, result_a, _ = run_adapter(tmp_path, envelope(honest), config)

    spoofed = proceed_control()
    for module in ('comm_risk', 'identity_trust', 'task_risk'):
        spoofed[module] = dict(spoofed[module], override={
            'producer': {'name': 'gateway', 'module_version': '0.0.1',
                         'source': 'EXTERNAL'}})
    code_b, result_b, _ = run_adapter(tmp_path, envelope(spoofed), config)

    assert code_a == code_b == EXIT_READY
    assert result_a['decision'] == result_b['decision']
    # 结果中不得出现任何"已认证/已授权"的表述
    text = json.dumps(result_b, ensure_ascii=False)
    for banned in ('DDS 认证通过', '已认证身份', 'authenticated_identity'):
        assert banned not in text


# ---------------------------------------------------------------- S-16
@pytest.mark.parametrize('resource', ['/rg/nav_execute', '/rg/nav_sim',
                                      '/rg/unguarded'])
def test_s16_input_cannot_select_execution_resource(tmp_path, resource):
    """S-16 输入尝试把候选操作指向执行端 → 在输入校验阶段拒绝。"""
    config = write_config(tmp_path)
    document = envelope(proceed_control())
    document['candidate_action']['action_resource'] = resource
    code, result, _err = run_adapter(tmp_path, document, config)
    assert code == 3, '应在输入校验阶段以退出码 3 拒绝'
    assert result['reason_code'] == 'ADAPTER_INPUT_INVALID'
    # 未通过输入校验时，不得调用任何模块（不产生执行准备结论）
    assert result['modules'] == []


def test_s16_config_cannot_offer_execution_channel(tmp_path):
    """S-16 补充：示例配置中不得出现任何指向执行端的命令。"""
    text = open(os.path.join(ROOT, 'config', 'team_modules.example.yaml'),
                encoding='utf-8').read()
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith('#'):
            continue
        assert '/rg/nav_execute' not in stripped or '不' in stripped, \
            '示例配置不得把执行端作为可配置入口: {0!r}'.format(line)


# ---------------------------------------------------------------- S-17/S-18
def test_s17_failure_does_not_poison_next_invocation(tmp_path):
    """S-17 模块异常后再次正常调用不受污染。"""
    config = write_config(tmp_path, allow_faults=True)

    bad = proceed_control()
    bad['fault'] = {'comm_risk': 'exit_nonzero'}
    code_bad, result_bad, _ = run_adapter(tmp_path, envelope(bad), config)
    assert code_bad == EXIT_BLOCK

    code_ok, result_ok, _ = run_adapter(tmp_path, envelope(proceed_control()), config)
    assert code_ok == EXIT_READY, '前一次失败不得影响后续调用'
    assert result_ok['decision'] == 'READY_FOR_GATEWAY_SUBMISSION'
    assert all(m['status'] for m in result_ok['modules'])


def test_s18_first_module_failure_stops_before_later_modules(tmp_path):
    """S-18 一个模块失败 → 不启动后续模块，绝不产生执行准备成功结论。"""
    config = write_config(tmp_path, allow_faults=True)
    control = proceed_control()
    control['fault'] = {'comm_risk': 'invalid_json'}
    code, result, _err = run_adapter(tmp_path, envelope(control), config)
    assert code == EXIT_BLOCK
    assert result['decision'] == 'ADAPTER_BLOCK'
    invoked = [m['module'] for m in result['modules']]
    assert invoked == ['comm_risk'], \
        '第一个模块失败后不应继续调用后续模块，实际: {0}'.format(invoked)


# ---------------------------------------------------------------- 真实替换
def test_replacement_all_three_modules_with_real_doubles(tmp_path):
    """替换验收：三个模块全部换成规则计算型替身，链路仍然工作。"""
    config = double_config(tmp_path)
    code, result, _err = run_adapter(tmp_path, doubles_envelope(), config)
    assert code == EXIT_READY, result
    assert result['decision'] == 'READY_FOR_GATEWAY_SUBMISSION'
    invoked = [m['module'] for m in result['modules']]
    assert invoked == ['comm_risk', 'identity_trust', 'task_risk']
    # 证明实际加载的是替身文件，而不是原 Mock
    for module in result['modules']:
        assert 'tests/fixtures/team_modules' in ' '.join(module['command'])
        assert 'mock_modules' not in ' '.join(module['command'])


@pytest.mark.parametrize('module,index', [
    ('comm_risk', 0), ('identity_trust', 1), ('task_risk', 2)])
def test_replacement_one_module_at_a_time(tmp_path, module, index):
    """逐个替换：只换一个模块，其余保持 Mock，链路仍然工作。

    这证明替换是**按模块独立**的：换人员一不需要改人员二、三的代码。
    """
    import yaml

    config_path = write_config(tmp_path)
    document = yaml.safe_load(open(config_path, encoding='utf-8'))
    document['modules'][module] = {
        'mode': 'double',
        'interface': document['modules'][module]['interface'],
        'command': ['python3',
                    'tests/fixtures/team_modules/{0}_double.py'.format(module)],
        'timeout_sec': 10,
        'max_stdout_bytes': 65536,
        'allow_fault_injection': False,
    }
    mixed = tmp_path / 'mixed.yaml'
    mixed.write_text(yaml.safe_dump(document, allow_unicode=True), encoding='utf-8')

    code, result, _err = run_adapter(tmp_path, doubles_envelope(), str(mixed))
    assert code == EXIT_READY, result
    records = {m['module']: m for m in result['modules']}
    assert 'tests/fixtures/team_modules' in ' '.join(records[module]['command'])
    for other in records:
        if other != module:
            assert 'mock_modules' in ' '.join(records[other]['command']), \
                '只应替换 {0}，{1} 应保持 Mock'.format(module, other)


def test_replacement_doubles_are_data_driven_not_scenario_switches(tmp_path):
    """替身必须是真实现：同一替身在不同输入下给出不同结论。

    若替身只是 Mock 改名，它就只能靠场景开关变化，本用例会失败。
    """
    config = double_config(tmp_path)

    # 通信替身：请求数远超基线 → SUSPICIOUS
    code1, result1, _ = run_adapter(tmp_path, doubles_envelope(
        comm={'request_count': 100, 'baseline_count': 3}), config)
    assert code1 == EXIT_BLOCK
    comm1 = [m for m in result1['modules'] if m['module'] == 'comm_risk'][0]
    assert comm1['status'] == 'SUSPICIOUS', comm1

    # 同一替身，正常数值 → NORMAL
    code2, result2, _ = run_adapter(tmp_path, doubles_envelope(
        comm={'request_count': 3, 'baseline_count': 3}), config)
    comm2 = [m for m in result2['modules'] if m['module'] == 'comm_risk'][0]
    assert comm2['status'] == 'NORMAL', comm2

    # 任务替身：目标越界 → BLOCK_RECOMMENDED；区域内 → ALLOW_RECOMMENDED
    code3, result3, _ = run_adapter(tmp_path, doubles_envelope(
        target={'frame_id': 'map', 'x': 9.0, 'y': 9.0, 'z': 0.0}), config)
    assert code3 == EXIT_BLOCK
    task3 = [m for m in result3['modules'] if m['module'] == 'task_risk'][0]
    assert task3['status'] == 'BLOCK_RECOMMENDED', task3

    code4, result4, _ = run_adapter(tmp_path, doubles_envelope(
        target={'frame_id': 'map', 'x': 1.5, 'y': 1.5, 'z': 0.0}), config)
    task4 = [m for m in result4['modules'] if m['module'] == 'task_risk'][0]
    assert task4['status'] == 'ALLOW_RECOMMENDED', task4


def test_replacement_identity_double_uses_permission_matrix(tmp_path):
    """身份替身按本地矩阵计算：换主体或换资源会改变结论。"""
    config = double_config(tmp_path)

    code_ok, result_ok, _ = run_adapter(tmp_path, doubles_envelope(), config)
    assert code_ok == EXIT_READY

    # 未知主体 → UNKNOWN → 阻断
    code_x, result_x, _ = run_adapter(tmp_path, doubles_envelope(
        identity={'subject': 'unknown_node', 'resource': '/rg/guarded_navigate',
                  'operation': 'SERVICE_REQUEST'}), config)
    assert code_x == EXIT_BLOCK
    ident = [m for m in result_x['modules'] if m['module'] == 'identity_trust'][0]
    assert ident['status'] == 'UNKNOWN'

    # 已知主体但越权资源 → DENIED → 阻断
    code_y, result_y, _ = run_adapter(tmp_path, doubles_envelope(
        identity={'subject': 'observer_node', 'resource': '/rg/guarded_navigate',
                  'operation': 'SERVICE_REQUEST'}), config)
    assert code_y == EXIT_BLOCK
    ident2 = [m for m in result_y['modules'] if m['module'] == 'identity_trust'][0]
    assert ident2['status'] == 'DENIED'


def test_replacement_double_output_passes_existing_schema(tmp_path):
    """替换后 Schema 校验仍然生效：替身输出通过既有契约校验。"""
    config = double_config(tmp_path)
    code, result, _err = run_adapter(tmp_path, doubles_envelope(), config)
    assert code == EXIT_READY
    for module in result['modules']:
        assert module['schema_ok'] is True
        assert module['interface'] in vtc.SCHEMA_FILES


# ---------------------------------------------------------------- 记录与日志
def test_adapter_log_is_separate_from_stdout(tmp_path):
    """适配层日志与结果 JSON 分离，日志为可解析 JSONL。"""
    config = write_config(tmp_path)
    log_path = tmp_path / 'adapter.jsonl'
    code, result, _err = run_adapter(tmp_path, envelope(proceed_control()), config)
    assert code == EXIT_READY
    assert log_path.is_file()
    lines = [json.loads(line) for line in
             log_path.read_text(encoding='utf-8').splitlines() if line.strip()]
    assert lines, '应至少有一条调用记录'
    entry = lines[-1]
    assert entry['decision'] == result['decision']
    assert entry['reason_code'] == result['reason_code']
    for module in entry['modules']:
        for field in ('invocation_id', 'module', 'command', 'timeout_sec',
                      'pid', 'exit_code', 'duration_ms', 'status', 'schema_ok'):
            assert field in module, '调用记录缺少字段 {0}'.format(field)


def test_adapter_error_codes_do_not_collide_with_business_reason_codes():
    """适配层内部错误码不得与 Gateway 的八个业务原因码混用。"""
    import rg_policy.reason_codes as rc

    business = set(rc.DECISION_REASON_CODES)
    adapter_codes = {value for key, value in vars(team_demo).items()
                     if key.startswith('REASON_') and isinstance(value, str)}
    assert adapter_codes, '应定义适配层错误码'
    assert not (adapter_codes & business), \
        '适配层错误码与业务原因码重叠: {0}'.format(adapter_codes & business)
    for code in adapter_codes:
        assert code.startswith('ADAPTER_')
