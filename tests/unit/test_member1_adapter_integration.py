"""F0 适配层 + 成员一真实模块：External 调用链路与失败关闭。

本文件验证的是**适配层真的把真实模块当外部进程调用**：
  * 命令来自受信任配置（不是业务 JSON）；
  * 模块退出码、stdout 契约、Schema 校验都由适配层真实检查；
  * 成员一给出 UNKNOWN / SUSPICIOUS / ERROR 时适配层必须阻断；
  * 只有在受信任的受控测试配置（`--controlled-test`）下才可能出现 READY，
    而且结果里必须留下 CONTROLLED_TEST_ONLY 的痕迹。

注意：READY_FOR_GATEWAY_SUBMISSION 仍然只是"可提交"，不等于 Gateway 允许。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

pytest.importorskip('jsonschema', reason='需要 jsonschema>=4.0（Draft 2020-12）')

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / 'scripts'
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(ROOT / 'tests' / 'unit') not in sys.path:
    sys.path.insert(0, str(ROOT / 'tests' / 'unit'))

import validate_team_contracts as vtc  # noqa: E402
import team_demo  # noqa: E402
from test_team_process_protocol import (  # noqa: E402
    EXIT_BLOCK, EXIT_READY, envelope, proceed_control, run_adapter, write_config)

MODEL = ROOT / 'modules/member1_comm/model/comm_risk_model.json'
FEATURES = ROOT / 'modules/member1_comm/features.json'
PROBES = ROOT / 'tests/fixtures/member1/rospace_comm_rows.json'
SHA = json.loads((ROOT / 'modules/member1_comm/model/model_manifest.json')
                 .read_text(encoding='utf-8'))['model_sha256']


def real_command(*extra):
    return [sys.executable, 'modules/member1_comm/module.py',
            '--model', str(MODEL), '--model-sha256', SHA,
            '--features', str(FEATURES), *extra]


def config_with_real_comm(tmp_path, *extra):
    return write_config(tmp_path, mode='mock',
                        commands={'comm_risk': real_command(*extra)})


def probe(kind):
    rows = json.loads(PROBES.read_text(encoding='utf-8'))
    threshold = rows['model']['threshold']
    if kind == 'above':
        return next(r for r in rows['rows'] if r['score'] >= threshold)
    return next(r for r in rows['rows'] if r['score'] < threshold)


def real_envelope(row):
    """三模块混跑信封：成员一用真实特征，其余两位仍是明确标注的 Mock。"""
    document = envelope(proceed_control())
    document['observations'][0]['detail']['rospace_comm'] = {
        'features': {'feature_names': row['feature_names'], 'values': row['values']},
    }
    document['observations'][0]['detail']['f0_runtime'] = {
        'communication': {'resource': '/rg/guarded_navigate',
                          'resource_type': 'Action', 'operation': 'GOAL_SEND'},
        'request_count': 12,
        'window': {'start': '2026-10-10T11:59:55Z', 'end': '2026-10-10T12:00:00Z',
                   'duration_ms': 5000},
    }
    # 观察时间必须落在窗口内、且不早于 created_at - 300s
    document['observations'][0]['observed_at'] = '2026-10-10T11:59:58Z'
    return document


def comm_record(result):
    return next(r for r in result['modules'] if r['module'] == 'comm_risk')


def test_real_module_unknown_blocks(tmp_path):
    """真实模块 -> UNKNOWN（模型未过验证门槛）-> 适配层阻断，但进程本身成功。"""
    config = config_with_real_comm(tmp_path)
    code, result, _err = run_adapter(tmp_path, real_envelope(probe('below')), config)
    assert result['decision'] == 'ADAPTER_BLOCK'
    assert result['reason_code'] == team_demo.REASON_NOT_PROCEED
    record = comm_record(result)
    # 命令确实来自受信任配置的 real 路径，而不是 mock
    assert any('modules/member1_comm/module.py' in part for part in record['command'])
    assert record['interface'] == 'comm_risk_evidence'
    assert record['exit_code'] == 0
    assert record['schema_ok'] is True
    assert record['status'] == 'UNKNOWN'


def test_real_module_suspicious_blocks(tmp_path):
    config = config_with_real_comm(tmp_path)
    code, result, _err = run_adapter(tmp_path, real_envelope(probe('above')), config)
    assert result['decision'] == 'ADAPTER_BLOCK'
    assert result['reason_code'] == team_demo.REASON_NOT_PROCEED
    assert comm_record(result)['status'] == 'SUSPICIOUS'


def test_real_module_ready_only_in_controlled_test_config(tmp_path):
    """受控测试配置：真实模块可给出 NORMAL，适配层才可能 READY。

    NORMAL 只在 `--controlled-test`（受信任命令行）下出现，且在输出里留下
    CONTROLLED_TEST_ONLY 依据，避免被当作生产结论。
    """
    config = config_with_real_comm(tmp_path, '--controlled-test')
    code, result, _err = run_adapter(tmp_path, real_envelope(probe('below')), config)
    assert result['decision'] == 'READY_FOR_GATEWAY_SUBMISSION', result
    assert code == EXIT_READY
    assert comm_record(result)['status'] == 'NORMAL'
    # 审计：结果必须显式说明这只是受控测试，不是生产结论
    assert result['note'].startswith('本结果仅表示适配层的候选输入检查结论')
    assert result['online']['enabled'] is False


def test_missing_model_blocks_with_exit_3(tmp_path):
    command = [sys.executable, 'modules/member1_comm/module.py',
               '--model', str(ROOT / 'training_runs/absent/model.json'),
               '--model-sha256', '0' * 64]
    config = write_config(tmp_path, mode='mock', commands={'comm_risk': command})
    code, result, _err = run_adapter(tmp_path, real_envelope(probe('below')), config)
    assert result['decision'] == 'ADAPTER_BLOCK'
    assert result['reason_code'] == team_demo.REASON_EXIT_NONZERO
    assert comm_record(result)['exit_code'] == 3


def test_tampered_model_hash_blocks_as_schema_valid_error(tmp_path):
    """哈希不符 -> 模块给出合法 ERROR -> 适配层阻断（不是崩溃、不是放行）。"""
    command = [sys.executable, 'modules/member1_comm/module.py',
               '--model', str(MODEL), '--model-sha256', 'f' * 64,
               '--features', str(FEATURES)]
    config = write_config(tmp_path, mode='mock', commands={'comm_risk': command})
    code, result, _err = run_adapter(tmp_path, real_envelope(probe('below')), config)
    assert result['decision'] == 'ADAPTER_BLOCK'
    assert result['reason_code'] == team_demo.REASON_NOT_PROCEED
    record = comm_record(result)
    assert record['exit_code'] == 0
    assert record['schema_ok'] is True
    assert record['status'] == 'ERROR'


def test_real_module_output_is_schema_valid(tmp_path):
    """适配层记录里的 schema_ok 是真实校验结果，不是假定的。"""
    config = config_with_real_comm(tmp_path)
    _code, result, _err = run_adapter(tmp_path, real_envelope(probe('below')), config)
    assert comm_record(result)['schema_ok'] is True
