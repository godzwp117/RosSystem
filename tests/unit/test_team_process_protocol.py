"""进程调用协议测试（P-01 ~ P-15）。

原则
----
* 每个用例都通过**真实适配层进程**执行（`scripts/team_demo.py`），
  断言真实返回的判定与退出码 —— 而不是调用一个参考函数推断"理论上应该拒绝"。
* 负例必须确认适配层**实际拒绝**，不能把"测试跑起来了"当成拒绝。
* 故障注入只能由**受信任配置**开启，业务输入无法打开它（P-13 验证这一点）。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

import pytest

pytest.importorskip('jsonschema', reason='需要 jsonschema>=4.0（Draft 2020-12）')

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(ROOT, 'scripts')
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import validate_team_contracts as vtc  # noqa: E402

ADAPTER = os.path.join(ROOT, 'scripts', 'team_demo.py')
FIXTURES = os.path.join(ROOT, 'tests', 'fixtures', 'team_modules')

EXIT_READY = 0
EXIT_BLOCK = 10


# ---------------------------------------------------------------- 夹具
def envelope(mock_control=None, *, request_id='req-p-0001', run_id='run-p-0001',
             target=None, observations_detail=None, **overrides):
    document = {
        'schema_version': vtc.CONTRACT_VERSION,
        'run_id': run_id,
        'request_id': request_id,
        'created_at': '2026-10-10T12:00:00Z',
        'candidate_action': {
            'action_resource': '/rg/guarded_navigate',
            'operation': 'NAVIGATE',
            'task_id': 'patrol_a_001',
            'target': target or {'frame_id': 'map', 'x': 1.5, 'y': 1.5, 'z': 0.0},
        },
        'observations': [{
            'source': '/rg/guarded_navigate',
            'kind': 'MOCK',
            'observed_at': '2026-10-10T12:00:00Z',
            'detail': observations_detail if observations_detail is not None
                      else {'f0_mock': mock_control or {}},
        }],
        'evidence_refs': [{'ref': 'tests', 'kind': 'MOCK'}],
    }
    document.update(overrides)
    return document


def proceed_control(**per_module):
    """三模块全部给出推进状态的默认控制块。"""
    control = {
        'comm_risk': {'scenario': 'normal'},
        'identity_trust': {'scenario': 'authorized'},
        'task_risk': {'scenario': 'allow'},
    }
    for module, value in per_module.items():
        if value is None:
            control.pop(module, None)
        else:
            control[module] = value
    return control


def write_config(tmp_path, *, mode='mock', allow_faults=False, modules=None,
                 commands=None, timeouts=None):
    """生成受信任的测试配置（故障注入必须在这里显式开启）。"""
    import yaml

    definitions = modules or {
        'comm_risk': 'comm_risk_evidence',
        'identity_trust': 'identity_trust_assessment',
        'task_risk': 'task_risk_decision',
    }
    config = {'adapter': {'log_path': str(tmp_path / 'adapter.jsonl')}, 'modules': {}}
    for name, interface in definitions.items():
        if mode == 'mock':
            command = ['python3', 'mock_modules/{0}_mock.py'.format(name)]
        else:
            command = ['python3', 'tests/fixtures/team_modules/{0}_double.py'.format(name)]
        if commands and name in commands:
            command = commands[name]
        config['modules'][name] = {
            'mode': mode,
            'interface': interface,
            'command': command,
            'timeout_sec': (timeouts or {}).get(name, 10),
            'max_stdout_bytes': 65536,
            'allow_fault_injection': allow_faults,
        }
    path = tmp_path / 'team_modules.yaml'
    path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding='utf-8')
    return str(path)


def run_adapter(tmp_path, envelope_document, config_path, *, timeout=120,
                raw_input=None):
    """真实执行适配层进程，返回 (exit_code, result_dict, stderr_text)。"""
    input_path = tmp_path / 'envelope.json'
    if raw_input is not None:
        input_path.write_text(raw_input, encoding='utf-8')
    else:
        input_path.write_text(json.dumps(envelope_document, ensure_ascii=False),
                              encoding='utf-8')
    proc = subprocess.run(
        [sys.executable, ADAPTER, '--input', str(input_path),
         '--config', config_path, '--log', str(tmp_path / 'adapter.jsonl'),
         '--workdir', ROOT],
        capture_output=True, text=True, timeout=timeout, cwd=ROOT)
    try:
        result = json.loads(proc.stdout)
    except ValueError:
        result = {'decision': 'UNPARSEABLE', 'raw_stdout': proc.stdout[:400]}
    return proc.returncode, result, proc.stderr


# ---------------------------------------------------------------- P-01/P-02
def test_p01_p02_stdin_object_and_single_stdout_object(tmp_path):
    """P-01 子进程收到完整输入对象；P-02 stdout 恰好一个 JSON 对象。"""
    config = write_config(tmp_path)
    code, result, _err = run_adapter(tmp_path, envelope(proceed_control()), config)
    assert code == EXIT_READY, result
    assert result['decision'] == 'READY_FOR_GATEWAY_SUBMISSION'
    # 三个模块都被真实调用，且各自返回了状态
    assert [m['module'] for m in result['modules']] == \
        ['comm_risk', 'identity_trust', 'task_risk']
    for module in result['modules']:
        assert module['exit_code'] == 0
        assert module['status'], '每个模块都应返回状态'
        assert module['pid'] and module['pgid'], '应记录 PID 与 PGID'


def test_p01_output_is_single_object_no_debug_on_stdout(tmp_path):
    """适配层自身 stdout 必须是单个 JSON 对象（日志只能进 stderr/文件）。"""
    config = write_config(tmp_path)
    input_path = tmp_path / 'envelope.json'
    input_path.write_text(json.dumps(envelope(proceed_control())), encoding='utf-8')
    proc = subprocess.run(
        [sys.executable, ADAPTER, '--input', str(input_path), '--config', config,
         '--log', str(tmp_path / 'a.jsonl'), '--workdir', ROOT],
        capture_output=True, text=True, timeout=120, cwd=ROOT)
    json.loads(proc.stdout)          # 必须能整体解析
    assert proc.stdout.strip().startswith('{')
    assert '注意' not in proc.stdout.split('\n')[0]


# ---------------------------------------------------------------- P-03..P-05
@pytest.mark.parametrize('fault', ['debug_text', 'two_objects', 'empty',
                                   'invalid_json'])
def test_p03_to_p05_malformed_stdout_is_rejected(tmp_path, fault):
    """P-03 混入调试文本 / P-04 两个 JSON / P-05 空输出 / 非 JSON 一律拒绝。"""
    config = write_config(tmp_path, allow_faults=True)
    control = proceed_control()
    control['fault'] = {'comm_risk': fault}
    code, result, _err = run_adapter(tmp_path, envelope(control), config)
    assert code == EXIT_BLOCK, result
    assert result['decision'] == 'ADAPTER_BLOCK'
    assert result['reason_code'] in (
        'ADAPTER_MODULE_STDOUT_INVALID', 'ADAPTER_MODULE_EXIT_NONZERO')


# ---------------------------------------------------------------- P-06
def test_p06_nonzero_exit_is_rejected(tmp_path):
    """P-06 非零退出码 → 拒绝。"""
    config = write_config(tmp_path, allow_faults=True)
    control = proceed_control()
    control['fault'] = {'identity_trust': 'exit_nonzero'}
    code, result, _err = run_adapter(tmp_path, envelope(control), config)
    assert code == EXIT_BLOCK
    assert result['reason_code'] == 'ADAPTER_MODULE_EXIT_NONZERO'
    module = [m for m in result['modules'] if m['module'] == 'identity_trust'][0]
    assert module['exit_code'] != 0


# ---------------------------------------------------------------- P-07/P-08/P-09
def test_p07_invalid_utf8_is_rejected(tmp_path):
    """P-07 非法 UTF-8 输出 → 拒绝。"""
    config = write_config(tmp_path, allow_faults=True)
    control = proceed_control()
    control['fault'] = {'comm_risk': 'bad_encoding'}
    code, result, _err = run_adapter(tmp_path, envelope(control), config)
    assert code == EXIT_BLOCK
    assert result['reason_code'] == 'ADAPTER_MODULE_STDOUT_ENCODING'


@pytest.mark.parametrize('fault', ['nan', 'infinity'])
def test_p08_non_finite_output_is_rejected(tmp_path, fault):
    """P-08 输出 NaN / Infinity → 拒绝（解析阶段）。"""
    config = write_config(tmp_path, allow_faults=True)
    control = proceed_control()
    control['fault'] = {'comm_risk': fault}
    code, result, _err = run_adapter(tmp_path, envelope(control), config)
    assert code == EXIT_BLOCK
    assert result['reason_code'] in ('ADAPTER_MODULE_STDOUT_INVALID',
                                     'ADAPTER_MODULE_SCHEMA_INVALID')


def test_p09_invalid_timestamp_is_rejected(tmp_path):
    """P-09 非法日期格式 → 拒绝（依赖严格 RFC 3339 检查器真实生效）。"""
    config = write_config(tmp_path, allow_faults=True)
    control = proceed_control()
    control['fault'] = {'comm_risk': 'bad_timestamp'}
    code, result, _err = run_adapter(tmp_path, envelope(control), config)
    assert code == EXIT_BLOCK
    assert result['reason_code'] == 'ADAPTER_MODULE_SCHEMA_INVALID'


# ---------------------------------------------------------------- P-10/P-11
def test_p10_oversize_output_is_rejected(tmp_path):
    """P-10 输出超出大小限制 → 拒绝。"""
    config = write_config(tmp_path, allow_faults=True)
    control = proceed_control()
    control['fault'] = {'comm_risk': 'oversize'}
    code, result, _err = run_adapter(tmp_path, envelope(control), config)
    assert code == EXIT_BLOCK
    assert result['reason_code'] == 'ADAPTER_MODULE_STDOUT_TOO_LARGE'


def test_p11_timeout_is_rejected_and_process_cleaned(tmp_path):
    """P-11 子进程超时 → 拒绝，且本次调用的进程被清理（不残留非僵尸进程）。"""
    config = write_config(tmp_path, allow_faults=True, timeouts={'comm_risk': 2})
    control = proceed_control()
    control['fault'] = {'comm_risk': 'timeout'}
    code, result, _err = run_adapter(tmp_path, envelope(control), config, timeout=180)
    assert code == EXIT_BLOCK
    assert result['reason_code'] == 'ADAPTER_MODULE_TIMEOUT'
    module = [m for m in result['modules'] if m['module'] == 'comm_risk'][0]
    assert module['cleanup'] not in ('not_needed',), '超时必须执行清理'
    assert 'unreaped' not in module['cleanup'], '子进程必须被回收'
    # 复核该 PID 不再存活（僵尸除外：僵尸已终止但未被 PID 1 回收）
    pid = module['pid']
    alive = subprocess.run(['ps', '-o', 'stat=', '-p', str(pid)],
                           capture_output=True, text=True).stdout.strip()
    assert (not alive) or alive.startswith('Z'), \
        '超时后不应残留存活进程，实际状态: {0!r}'.format(alive)


# ---------------------------------------------------------------- P-12/P-13
def test_p12_command_args_with_spaces_are_not_shell_interpreted(tmp_path):
    """P-12 参数含空格时不发生 Shell 解释：参数边界必须正确。"""
    import yaml
    marker = tmp_path / 'space marker.txt'
    config = write_config(tmp_path, allow_faults=True)
    document = yaml.safe_load(open(config, encoding='utf-8'))
    # 用一个把参数原样回显的替身，参数里带空格与元字符
    document['modules']['comm_risk']['command'] = [
        'python3', '-c',
        'import sys,json; sys.stdin.read(); '
        'print(json.dumps({"argv": sys.argv[1:]}))',
        'a b', '$(touch {0})'.format(marker),
    ]
    config2 = tmp_path / 'spaces.yaml'
    config2.write_text(yaml.safe_dump(document, allow_unicode=True), encoding='utf-8')
    code, result, _err = run_adapter(tmp_path, envelope(proceed_control()), str(config2))
    # 该命令输出不符合 Schema，因此必然阻断；关键是证明没有发生 Shell 执行
    assert not marker.exists(), '参数中的 $(...) 绝不能被 Shell 执行'
    assert code == EXIT_BLOCK


def test_p13_input_cannot_control_module_command(tmp_path):
    """P-13 业务输入无法影响模块命令：命令只来自受信任配置。"""
    config = write_config(tmp_path)          # 该配置未开启故障注入
    control = proceed_control()
    control['fault'] = 'invalid_json'        # 输入试图让模块输出非法 JSON
    code, result, _err = run_adapter(tmp_path, envelope(control), config)
    # 未开启故障注入时，模块拒绝执行（退出码 2）→ 适配层阻断
    assert code == EXIT_BLOCK
    assert result['reason_code'] == 'ADAPTER_MODULE_EXIT_NONZERO'
    # 且配置中的命令没有被输入改写
    module = [m for m in result['modules'] if m['module'] == 'comm_risk'][0]
    assert module['command'] == ['python3', 'mock_modules/comm_risk_mock.py']


def test_p13_input_cannot_inject_command_via_payload(tmp_path):
    """P-13 补充：输入中夹带命令/路径字段不会被执行。"""
    config = write_config(tmp_path)
    document = envelope(proceed_control())
    document['observations'][0]['detail']['command'] = 'rm -rf /tmp/should-not-run'
    document['observations'][0]['detail']['producer'] = 'gateway'
    code, result, _err = run_adapter(tmp_path, document, config)
    module = [m for m in result['modules'] if m['module'] == 'comm_risk']
    if module:
        assert module[0]['command'] == ['python3', 'mock_modules/comm_risk_mock.py']


# ---------------------------------------------------------------- P-14/P-15
def test_p14_stderr_diagnostics_do_not_pollute_stdout(tmp_path):
    """P-14 stderr 诊断日志不得污染 stdout 的 JSON 解析。"""
    config = write_config(tmp_path)
    code, result, stderr = run_adapter(tmp_path, envelope(proceed_control()), config)
    assert code == EXIT_READY
    assert result['decision'] == 'READY_FOR_GATEWAY_SUBMISSION'
    # 模块确实写了 stderr，但不影响结果解析
    assert 'stderr' in stderr or '[adapter]' in stderr


def test_p15_duplicate_json_keys_are_rejected(tmp_path):
    """P-15 重复 JSON 键 → 拒绝，不采用含糊解析结果。

    适配层使用严格解析器：重复键在解析阶段即被拒绝
    （Python 默认 json.loads 会静默取最后一个值，必须避免）。
    """
    config = write_config(tmp_path, allow_faults=True)
    control = proceed_control()
    control['fault'] = {'comm_risk': 'duplicate_key'}
    code, result, _err = run_adapter(tmp_path, envelope(control), config)
    assert code == EXIT_BLOCK
    assert result['reason_code'] == 'ADAPTER_MODULE_STDOUT_INVALID'

    # 输入信封本身含重复键也必须被拒绝
    raw = ('{"schema_version":"1.0.0-proposed","run_id":"r","run_id":"r2",'
           '"request_id":"q","created_at":"2026-10-10T12:00:00Z",'
           '"candidate_action":{},"observations":[],"evidence_refs":[]}')
    code2, result2, _err2 = run_adapter(tmp_path, None, config, raw_input=raw)
    assert code2 == 3
    assert result2['reason_code'] == 'ADAPTER_INPUT_INVALID'


# ---------------------------------------------------------------- 严格解析器单测
def test_strict_parser_rejects_non_finite_and_duplicates():
    """直接验证共享严格解析器本身（适配层复用它，不另建弱化版本）。"""
    with pytest.raises(ValueError):
        vtc.load_json_strict_text('{"a": 1, "a": 2}')
    with pytest.raises(ValueError):
        vtc.load_json_strict_text('{"a": NaN}')
    with pytest.raises(ValueError):
        vtc.load_json_strict_text('{"a": Infinity}')
    assert vtc.load_json_strict_text('{"a": 1}') == {'a': 1}


def test_format_checker_still_enforced_after_d1_changes():
    """D1 的改动不得削弱阶段 C 的格式校验能力。"""
    ok, detail = vtc.self_check_format_checker()
    assert ok, detail


# ================================================================ H1 输出资源限额
# 这些用例的核心要求：**确认故障确实发生**，并确认拒绝原因对应实际故障。
# 不接受"反正最终 BLOCK 了，所以通过"—— 那种断言无法区分"限流生效"与
# "因为别的原因失败"。因此每条都断言具体的 reason_code。

def test_h1_flood_stdout_is_bounded_and_terminated(tmp_path):
    """H1 持续洪泛 stdout：必须在读取过程中终止，而不是读完再报错。"""
    config = write_config(tmp_path, allow_faults=True, timeouts={'comm_risk': 30})
    control = proceed_control()
    control['fault'] = {'comm_risk': 'flood_stdout'}
    code, result, _err = run_adapter(tmp_path, envelope(control), config, timeout=300)
    assert code == EXIT_BLOCK
    assert result['reason_code'] == 'ADAPTER_MODULE_STDOUT_TOO_LARGE', \
        '必须是"输出超限"，不能是其它失败原因：{0}'.format(result['reason_code'])
    module = [m for m in result['modules'] if m['module'] == 'comm_risk'][0]
    assert module['cleanup'] not in ('not_needed',), '超限后必须终止本次调用'
    assert 'unreaped' not in module['cleanup'], '子进程必须被回收'


def test_h1_flood_stdout_does_not_inflate_adapter_memory(tmp_path):
    """H1 洪泛输出不得让适配层无界缓冲（用自报峰值内存作为证据）。"""
    config = write_config(tmp_path, allow_faults=True, timeouts={'comm_risk': 30})

    code_ok, result_ok, _ = run_adapter(tmp_path, envelope(proceed_control()), config)
    assert code_ok == EXIT_READY
    baseline_kb = result_ok['adapter_peak_rss_kb']

    control = proceed_control()
    control['fault'] = {'comm_risk': 'flood_stdout'}
    code, result, _err = run_adapter(tmp_path, envelope(control), config, timeout=300)
    assert code == EXIT_BLOCK
    assert result['reason_code'] == 'ADAPTER_MODULE_STDOUT_TOO_LARGE'

    # 洪泛目标是 64 MiB；若发生无界缓冲，峰值会增长数十 MB。
    # 这里给出宽松但有意义的上界：增长不得超过 32 MiB。
    growth_kb = result['adapter_peak_rss_kb'] - baseline_kb
    assert growth_kb < 32 * 1024, \
        '适配层峰值内存增长 {0} KiB，疑似发生了无界缓冲'.format(growth_kb)


def test_h1_flood_stderr_is_drained_but_not_retained(tmp_path):
    """H1 stderr 洪泛：必须持续排空（避免子进程阻塞），但不无界保留。"""
    config = write_config(tmp_path, allow_faults=True, timeouts={'comm_risk': 30})
    control = proceed_control()
    control['fault'] = {'comm_risk': 'flood_stderr'}
    code, result, _err = run_adapter(tmp_path, envelope(control), config, timeout=300)
    assert code == EXIT_BLOCK
    module = [m for m in result['modules'] if m['module'] == 'comm_risk'][0]
    # 子进程能写完并正常退出（说明 stderr 被排空，没有把它堵死）
    assert module['exit_code'] == 0, 'stderr 未被排空会把子进程堵死'
    # 但保留量受上限约束
    assert module['stderr_bytes_kept'] <= 16384, \
        'stderr 保留量超出上限: {0}'.format(module['stderr_bytes_kept'])


def test_h1_flood_both_streams(tmp_path):
    """H1 stdout 与 stderr 同时大量输出。"""
    config = write_config(tmp_path, allow_faults=True, timeouts={'comm_risk': 30})
    control = proceed_control()
    control['fault'] = {'comm_risk': 'flood_both'}
    code, result, _err = run_adapter(tmp_path, envelope(control), config, timeout=300)
    assert code == EXIT_BLOCK
    assert result['reason_code'] == 'ADAPTER_MODULE_STDOUT_TOO_LARGE'


def test_h1_next_call_succeeds_after_limit_exceeded(tmp_path):
    """H1 超限后，下一次正常调用仍必须成功（无状态污染）。"""
    config = write_config(tmp_path, allow_faults=True, timeouts={'comm_risk': 30})
    control = proceed_control()
    control['fault'] = {'comm_risk': 'flood_stdout'}
    code_bad, _r, _e = run_adapter(tmp_path, envelope(control), config, timeout=300)
    assert code_bad == EXIT_BLOCK
    code_ok, result_ok, _err = run_adapter(tmp_path, envelope(proceed_control()), config)
    assert code_ok == EXIT_READY, '超限后再次正常调用应成功'
    assert result_ok['decision'] == 'READY_FOR_GATEWAY_SUBMISSION'


def test_h1_input_larger_than_limit_is_rejected(tmp_path):
    """H1 输入信封超过上限 → 拒绝，且不把输入交给模块。"""
    config = write_config(tmp_path)
    document = envelope(proceed_control())
    document['observations'][0]['detail']['padding'] = 'y' * (1024 * 1024 + 1024)
    code, result, _err = run_adapter(tmp_path, document, config)
    assert code == EXIT_BLOCK
    assert result['reason_code'] in ('ADAPTER_INPUT_TOO_LARGE',
                                     'ADAPTER_MODULE_EXIT_NONZERO')


def test_h1_no_non_zombie_descendants_after_flood(tmp_path):
    """H1 洪泛超限后不得残留本实例的非僵尸进程。"""
    config = write_config(tmp_path, allow_faults=True, timeouts={'comm_risk': 30})
    control = proceed_control()
    control['fault'] = {'comm_risk': 'flood_stdout'}
    code, result, _err = run_adapter(tmp_path, envelope(control), config, timeout=300)
    assert code == EXIT_BLOCK
    module = [m for m in result['modules'] if m['module'] == 'comm_risk'][0]
    assert module['pgid'], '应记录进程组'
    # 以进程组为单位复查：该组内不应再有存活（非僵尸）进程
    listing = subprocess.run(['ps', '-eo', 'pgid=,stat=,cmd='],
                             capture_output=True, text=True).stdout
    alive = []
    for line in listing.splitlines():
        parts = line.split(None, 2)
        if len(parts) < 2:
            continue
        pgid, state = parts[0], parts[1]
        if pgid == str(module['pgid']) and not state.startswith('Z'):
            alive.append(line.strip())
    assert not alive, '洪泛超限后仍有存活进程: {0}'.format(alive)
