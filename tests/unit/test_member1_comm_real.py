"""成员一真实通信风险模块：真实模型推理 + 失败关闭 + 来源可信性。

测试层次
--------
这些都是 **L1 协议/工程**测试：真实子进程 + 真实交付模型 + 真实 held-out 数据行。
它们证明"模块可被真实调用、状态可真实到达、失败关闭有效"，**不**证明检测
效果（那需要 L2 离线评估与 L3 在线观测，两者当前都不成立）。

为什么用 held-out 真实行
------------------------
`tests/fixtures/member1/rospace_comm_rows.json` 由
`modules/member1_comm/export_probe_rows.py` 从 ROSPaCe 测试分片导出，
只按"打分是否过阈值"选取，标签仅作记录。期望状态由已发布决策规则推出，
与标签无关。
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip('jsonschema', reason='需要 jsonschema>=4.0（Draft 2020-12）')

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / 'scripts'
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import validate_team_contracts as vtc  # noqa: E402

MODULE = ROOT / 'modules/member1_comm/module.py'
FEATURES = ROOT / 'modules/member1_comm/features.json'
MODEL = ROOT / 'modules/member1_comm/model/comm_risk_model.json'
MANIFEST = ROOT / 'modules/member1_comm/model/model_manifest.json'
PROBES = ROOT / 'tests/fixtures/member1/rospace_comm_rows.json'

CREATED = '2026-10-13T12:00:05Z'
OBSERVED = '2026-10-13T12:00:03Z'
WINDOW = {'start': '2026-10-13T12:00:00Z', 'end': '2026-10-13T12:00:05Z',
          'duration_ms': 5000}


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


@pytest.fixture(scope='module')
def probes():
    return json.loads(PROBES.read_text(encoding='utf-8'))


@pytest.fixture(scope='module')
def model_sha():
    return sha256_file(MODEL)


def envelope(row=None, *, kind='CONTROLLED_SECURITY_EXPERIMENT',
             drop_features=False, drop_runtime=False, request_id='req-m1-real'):
    detail = {
        'f0_runtime': {
            'communication': {'resource': '/rg/guarded_navigate',
                              'resource_type': 'Action', 'operation': 'GOAL_SEND'},
            'request_count': 12,
            'window': dict(WINDOW),
        },
    }
    if row is not None and not drop_features:
        detail['rospace_comm'] = {
            'features': {'feature_names': row['feature_names'],
                         'values': row['values']},
        }
    if drop_runtime:
        detail.pop('f0_runtime')
    return {
        'schema_version': vtc.CONTRACT_VERSION,
        'run_id': 'run-m1-real',
        'request_id': request_id,
        'created_at': CREATED,
        'candidate_action': {
            'action_resource': '/rg/guarded_navigate',
            'operation': 'NAVIGATE',
            'task_id': 'patrol_a_001',
            'target': {'frame_id': 'map', 'x': 2.0, 'y': 2.0, 'z': 0.0},
        },
        'observations': [{
            'source': '/rg/guarded_navigate',
            'kind': kind,
            'observed_at': OBSERVED,
            'detail': detail,
        }],
        'evidence_refs': [{'ref': 'member1-probe', 'kind': kind}],
    }


def run(document, args, *, raw=None, timeout=120):
    payload = raw if raw is not None else json.dumps(document, ensure_ascii=False)
    proc = subprocess.run(
        [sys.executable, str(MODULE), *args],
        input=payload.encode('utf-8'), capture_output=True, timeout=timeout, cwd=str(ROOT))
    return proc


def base_args(sha, *extra):
    return ['--model', str(MODEL), '--model-sha256', sha, '--features', str(FEATURES), *extra]


def validate_output(document):
    errors = vtc.validate_document(document, vtc.load_schema('comm_risk_evidence'))
    assert not errors, errors


# ---------------------------------------------------------------- 交付物一致性
def test_model_manifest_matches_delivered_model(model_sha):
    manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
    assert manifest['model_sha256'] == model_sha
    assert manifest['model_size_bytes'] == MODEL.stat().st_size
    assert manifest['feature_count'] == len(
        json.loads(FEATURES.read_text(encoding='utf-8'))['feature_names'])
    # 诚实性断言：门槛未通过、效果未证明，必须如实记录在交付清单里
    assert manifest['validation_gate_passed'] is False
    assert manifest['detector_effectiveness'] == 'NOT_PROVEN'
    assert manifest['runtime_monitor'] == 'NOT_READY'


def test_model_is_numeric_json_not_pickle():
    raw = MODEL.read_bytes()
    payload = json.loads(raw)
    assert payload['format'] == 'member1-numeric-v1'
    assert payload['algorithm'] in ('logistic', 'extra_trees')
    # 纯 JSON 必须能被严格解析：不允许 NaN/Infinity 字面量
    assert b'NaN' not in raw and b'Infinity' not in raw


# ---------------------------------------------------------------- 真实推理
def test_probe_rows_reach_expected_states(probes, model_sha):
    """真实 held-out 行 -> 真实子进程 -> 期望状态（与数据标签无关）。"""
    seen = set()
    for row in probes['rows']:
        proc = run(envelope(row), base_args(model_sha, '--observation-provenance',
                                           'CONTROLLED_SECURITY_EXPERIMENT'))
        assert proc.returncode == 0, proc.stderr.decode('utf-8', 'replace')
        document = json.loads(proc.stdout)
        validate_output(document)
        assert document['status'] == row['expected_status'], (
            row['shard'], row['original_csv_row'], document['reason'])
        assert document['run_id'] == 'run-m1-real'
        assert document['request_id'] == 'req-m1-real'
        extension = document['extensions']['member1_comm']
        assert extension['model_sha256'] == model_sha
        assert extension['score'] == pytest.approx(row['score'], abs=1e-9)
        assert extension['trusted_provenance'] == 'CONTROLLED_SECURITY_EXPERIMENT'
        assert extension['feature_manifest_verified'] is True
        assert document['basis']
        seen.add(document['status'])
    # 至少覆盖"确实检出"与"证据不足"两条路径
    assert 'SUSPICIOUS' in seen
    assert 'UNKNOWN' in seen


def test_controlled_test_flag_is_the_only_way_to_normal(probes, model_sha):
    below = [row for row in probes['rows'] if row['score'] < probes['model']['threshold']]
    assert below, 'fixture must contain a below-threshold row'
    row = below[0]
    args = base_args(model_sha, '--observation-provenance',
                     'CONTROLLED_SECURITY_EXPERIMENT')
    untrusted = run(envelope(row), args)
    assert json.loads(untrusted.stdout)['status'] == 'UNKNOWN'
    trusted = run(envelope(row), base_args(model_sha, '--controlled-test'))
    document = json.loads(trusted.stdout)
    validate_output(document)
    assert document['status'] == 'NORMAL'
    assert document['extensions']['member1_comm']['controlled_test'] is True
    assert 'CONTROLLED_TEST_ONLY' in document['reason']


# ---------------------------------------------------------------- 来源可信性
def test_normal_allowed_requires_all_three_conditions():
    """纯函数级别：NORMAL 的三个条件缺一不可（与具体模型门槛值无关）。"""
    from modules.member1_comm.module import normal_allowed

    def allowed(*args):
        return normal_allowed(*args)[0]

    # 门槛未通过 -> 即使来源可信也不得 NORMAL
    assert allowed('RUNTIME_LOG', 'RUNTIME_LOG', False) is False
    # 受信任配置未声明可信来源 -> 信封自报什么都不算
    assert allowed('UNKNOWN', 'RUNTIME_LOG', True) is False
    assert allowed('MOCK', 'RUNTIME_LOG', True) is False
    # 配置声明与信封自报不一致 -> 视为伪造/错配
    assert allowed('RUNTIME_LOG', 'MOCK', True) is False
    assert allowed('CONTROLLED_SECURITY_EXPERIMENT', 'RUNTIME_LOG', True) is False
    # 三者同时成立才允许
    assert allowed('RUNTIME_LOG', 'RUNTIME_LOG', True) is True
    assert allowed('CONTROLLED_SECURITY_EXPERIMENT',
                   'CONTROLLED_SECURITY_EXPERIMENT', True) is True
    # 失败的每条路径都有稳定的机器可读原因码
    assert normal_allowed('MOCK', 'RUNTIME_LOG', True)[2] == 'OBSERVATION_PROVENANCE_NOT_TRUSTED'
    assert normal_allowed('RUNTIME_LOG', 'MOCK', True)[2] == 'OBSERVATION_PROVENANCE_MISMATCH'
    assert normal_allowed('RUNTIME_LOG', 'RUNTIME_LOG', False)[2] == 'MODEL_NOT_ACCEPTED'


def test_self_reported_runtime_kind_cannot_earn_normal(probes, model_sha):
    """业务输入自报 kind=RUNTIME_LOG 不足以让模块给出 NORMAL。

    受信任配置没有声明可信来源时，即使信封自称 RUNTIME_LOG，也必须保留 UNKNOWN。
    """
    below = [row for row in probes['rows'] if row['score'] < probes['model']['threshold']]
    row = below[0]
    proc = run(envelope(row, kind='RUNTIME_LOG'), base_args(model_sha))
    document = json.loads(proc.stdout)
    validate_output(document)
    assert document['status'] == 'UNKNOWN'
    # 具体理由可能是"门槛未过"或"来源不可信"，两者都是失败关闭；
    # 关键断言是它**没有**变成 NORMAL，且受信任来源仍记录为 UNKNOWN。
    assert document['status'] != 'NORMAL'
    assert document['extensions']['member1_comm']['trusted_provenance'] == 'UNKNOWN'
    assert document['extensions']['member1_comm']['envelope_provenance'] == 'RUNTIME_LOG'


def test_envelope_kind_must_match_trusted_provenance(probes, model_sha):
    below = [row for row in probes['rows'] if row['score'] < probes['model']['threshold']]
    proc = run(envelope(below[0], kind='MOCK'),
               base_args(model_sha, '--observation-provenance', 'RUNTIME_LOG'))
    document = json.loads(proc.stdout)
    validate_output(document)
    assert document['status'] == 'UNKNOWN'
    assert document['extensions']['member1_comm']['trusted_provenance'] == 'RUNTIME_LOG'
    assert document['extensions']['member1_comm']['envelope_provenance'] == 'MOCK'


def test_suspicious_is_reported_regardless_of_provenance(probes, model_sha):
    """检出异常不依赖来源声明：模型判定异常就报 SUSPICIOUS（仍然只是建议）。"""
    above = [row for row in probes['rows'] if row['score'] >= probes['model']['threshold']]
    assert above, 'fixture must contain an above-threshold row'
    document = json.loads(run(envelope(above[0], kind='MOCK'),
                              base_args(model_sha)).stdout)
    validate_output(document)
    assert document['status'] == 'SUSPICIOUS'
    assert document['anomaly_category'] == 'UNKNOWN'
    assert document['risk_level'] == 'MEDIUM'


# ---------------------------------------------------------------- 失败关闭
def test_missing_model_exits_3():
    proc = run(envelope(), ['--model', str(ROOT / 'training_runs/absent/model.json'),
                            '--model-sha256', '0' * 64])
    assert proc.returncode == 3
    assert b'MODEL_ABSENT' in proc.stderr


def test_hash_mismatch_yields_error_state(probes, model_sha):
    proc = run(envelope(probes['rows'][0]),
               ['--model', str(MODEL), '--model-sha256', 'f' * 64,
                '--features', str(FEATURES)])
    assert proc.returncode == 0
    document = json.loads(proc.stdout)
    validate_output(document)
    assert document['status'] == 'ERROR'
    assert 'MODEL_INVALID' in document['reason']


def test_model_outside_allowlist_yields_error(probes, tmp_path, model_sha):
    outside = tmp_path / 'model.json'
    outside.write_bytes(MODEL.read_bytes())
    proc = run(envelope(probes['rows'][0]),
               ['--model', str(outside), '--model-sha256', model_sha])
    document = json.loads(proc.stdout)
    validate_output(document)
    assert document['status'] == 'ERROR'
    assert 'model must live under' in document['reason']


def test_feature_manifest_mismatch_yields_error(probes, tmp_path, model_sha):
    broken = tmp_path / 'features.json'
    broken.write_text(json.dumps({'feature_names': ['rate']}), encoding='utf-8')
    proc = run(envelope(probes['rows'][0]),
               ['--model', str(MODEL), '--model-sha256', model_sha,
                '--features', str(broken)])
    document = json.loads(proc.stdout)
    validate_output(document)
    assert document['status'] == 'ERROR'
    assert 'MODEL_FEATURE_LIST_MISMATCH' in document['reason']


def test_feature_vector_removed_yields_unknown(model_sha):
    proc = run(envelope(None),
               base_args(model_sha, '--observation-provenance', 'RUNTIME_LOG'))
    document = json.loads(proc.stdout)
    validate_output(document)
    assert document['status'] == 'UNKNOWN'
    assert 'FEATURE_NAMES_ABSENT' in document['reason']


def test_feature_vector_truncated_yields_unknown(probes, model_sha):
    row = dict(probes['rows'][0])
    row = json.loads(json.dumps(row))
    row['values'] = row['values'][:10]
    document = json.loads(run(envelope(row), base_args(model_sha)).stdout)
    validate_output(document)
    assert document['status'] == 'UNKNOWN'
    assert 'FEATURE_VALUES_ABSENT_OR_SHAPE_MISMATCH' in document['reason']


def test_missing_mapping_exits_4(probes, model_sha):
    proc = run(envelope(probes['rows'][0], drop_runtime=True), base_args(model_sha))
    assert proc.returncode == 4
    assert b'MAPPING_BLOCKED' in proc.stderr


def test_observation_outside_window_exits_4(probes, model_sha):
    document = envelope(probes['rows'][0])
    document['observations'][0]['observed_at'] = '2026-10-13T11:59:00Z'
    proc = run(document, base_args(model_sha))
    assert proc.returncode == 4
    assert b'outside declared window' in proc.stderr


def test_stale_observation_yields_unknown(probes, model_sha):
    document = envelope(probes['rows'][0])
    document['created_at'] = '2026-10-13T12:10:00Z'  # 与 observation 差 7 分钟
    document['observations'][0]['observed_at'] = '2026-10-13T12:00:03Z'
    document['observations'][0]['detail']['f0_runtime']['window'] = {
        'start': '2026-10-13T12:00:00Z', 'end': '2026-10-13T12:10:00Z',
        'duration_ms': 600000}
    proc = run(document, base_args(model_sha, '--observation-provenance',
                                   'CONTROLLED_SECURITY_EXPERIMENT'))
    assert proc.returncode == 0, proc.stderr
    resolved = json.loads(proc.stdout)
    validate_output(resolved)
    assert resolved['status'] == 'UNKNOWN'
    assert 'OBSERVATION_STALE_OR_FUTURE' in resolved['reason']


def test_invalid_json_exits_2():
    proc = run(None, base_args('0' * 64), raw='{not json')
    assert proc.returncode == 2
    assert b'INPUT_INVALID' in proc.stderr


def test_duplicate_json_key_exits_2(probes, model_sha):
    document = envelope(probes['rows'][0])
    raw = json.dumps(document)[:-1] + ', "run_id": "dup"}'
    proc = run(None, base_args(model_sha), raw=raw)
    assert proc.returncode == 2


def test_nan_literal_exits_2(probes, model_sha):
    document = envelope(probes['rows'][0])
    raw = json.dumps(document).replace('"request_count": 12', '"request_count": NaN')
    proc = run(None, base_args(model_sha), raw=raw)
    assert proc.returncode == 2


def test_stdout_is_exactly_one_json_object(probes, model_sha):
    proc = run(envelope(probes['rows'][0]), base_args(model_sha))
    text = proc.stdout.decode('utf-8').strip()
    decoder = json.JSONDecoder()
    _document, end = decoder.raw_decode(text)
    assert text[end:].strip() == ''
    # 诊断信息只能出现在 stderr
    assert proc.stderr.decode('utf-8').strip()
