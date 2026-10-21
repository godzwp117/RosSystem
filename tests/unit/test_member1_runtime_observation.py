"""M1 真实运行时观测：/proc 采集、缺失项如实标注、子集模型推理与失败关闭。

证据等级（本文件把两者严格分开）
================================
* **REAL_RUNTIME**：`proc_runtime.collect()` 直接读 Linux /proc 的实时计数，
  断言里会检查"窗口内确有变化"（例如 pgpgin 的增量大于 0），以证明不是静态快照。
* **OFFLINE_RESEARCH**：24 维子集模型来自 ROSPaCe 离线训练与 held-out 评估。
* **CONTROLLED_TEST**：`request_count` 由测试显式声明，不是自动采集。

结论边界：本文件证明"真实采集 -> 模型推理"的链路可用，**不**证明在线检测有效，
也**不**证明 49 维输入可以在目标环境获得。
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
for extra in (ROOT, ROOT / 'scripts'):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import validate_team_contracts as vtc  # noqa: E402
from modules.member1_comm.collector import proc_runtime  # noqa: E402

MODULE = ROOT / 'modules/member1_comm/module.py'
SUBSET_FEATURES = ROOT / 'modules/member1_comm/features_runtime_subset.json'
FULL_FEATURES = ROOT / 'modules/member1_comm/features.json'
SUBSET_MODEL = ROOT / 'modules/member1_comm/model/comm_risk_model_runtime_subset.json'
SUBSET_MANIFEST = ROOT / 'modules/member1_comm/model/model_manifest_runtime_subset.json'
FULL_MODEL = ROOT / 'modules/member1_comm/model/comm_risk_model.json'
FULL_MANIFEST = ROOT / 'modules/member1_comm/model/model_manifest.json'
FEASIBILITY = ROOT / 'docs/integration/m1_feature_feasibility.json'


@pytest.fixture(scope='module')
def snapshot():
    return proc_runtime.collect(0.8, 0.2)


def build_envelope(snapshot_value, *, with_request_count=True, kind='RUNTIME_LOG'):
    window = snapshot_value['window']
    detail = {
        'rospace_comm': {
            'features': {
                'feature_names': snapshot_value['measurements']['feature_names'],
                'values': snapshot_value['measurements']['values'],
            },
            'collection': {'measurement_sha256':
                           snapshot_value['evidence']['measurement_sha256']},
        },
    }
    if with_request_count:
        detail['f0_runtime'] = {
            'communication': {'resource': '/rg/guarded_navigate',
                              'resource_type': 'Action', 'operation': 'GOAL_SEND'},
            'request_count': 7,
            'request_count_source': 'OPERATOR_DECLARED_CONTROLLED_TEST',
            'window': {'start': window['start'], 'end': window['end'],
                       'duration_ms': window['duration_ms']},
        }
    return {
        'schema_version': vtc.CONTRACT_VERSION,
        'run_id': 'run-m1-runtime',
        'request_id': 'req-m1-runtime',
        'created_at': window['end'],
        'candidate_action': {
            'action_resource': '/rg/guarded_navigate', 'operation': 'NAVIGATE',
            'task_id': 'patrol_a_001',
            'target': {'frame_id': 'map', 'x': 2.0, 'y': 2.0, 'z': 0.0},
        },
        'observations': [{
            'source': '/rg/guarded_navigate', 'kind': kind,
            'observed_at': window['end'], 'detail': detail,
        }],
        'evidence_refs': [{'ref': 'modules/member1_comm/collector/proc_runtime.py',
                           'kind': kind}],
    }


def run_module(document, args):
    return subprocess.run(
        [sys.executable, str(MODULE), *args],
        input=json.dumps(document).encode('utf-8'),
        capture_output=True, timeout=180, cwd=str(ROOT))


# ---------------------------------------------------------------- REAL_RUNTIME
def test_collector_reads_live_proc_counters(snapshot):
    """真实采集：24 维可得，1 维本机缺失，且窗口内确实有计数器变化。"""
    names = snapshot['measurements']['feature_names']
    assert snapshot['source']['kind'] == 'LINUX_PROC'
    assert snapshot['window']['sample_count'] >= 2
    assert snapshot['window']['duration_ms'] > 0
    assert len(names) == 24
    assert 'pgalloc_dma' in snapshot['missing']
    assert 'pgalloc_dma' not in names
    deltas = dict(zip(names, snapshot['measurements']['window_deltas']))
    moved = [name for name, delta in deltas.items() if delta != 0]
    assert moved, 'no counter moved inside the window; collector is not live'
    # 测量内容可复核
    recomputed = hashlib.sha256(json.dumps(
        {'feature_names': names,
         'values': snapshot['measurements']['values'],
         'window_deltas': snapshot['measurements']['window_deltas']},
        sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    assert recomputed == snapshot['evidence']['measurement_sha256']


def test_collector_never_fabricates_request_count(snapshot):
    """request_count 是业务请求数：没有 ROS 2 时必须显式不可用。"""
    assert 'request_count' not in snapshot
    assert snapshot['unavailable']['request_count']
    assert snapshot['unavailable']['tshark_features']
    assert snapshot['unavailable']['ros_graph_features'] == ['subscribers_count',
                                                             'publishers_count']


def test_module_fails_closed_without_request_count(snapshot):
    """真实观测但缺 request_count -> 退出码 4（MAPPING_BLOCKED），不产出结论。"""
    document = build_envelope(snapshot, with_request_count=False)
    proc = run_module(document, [
        '--model', str(SUBSET_MODEL),
        '--model-sha256', json.loads(SUBSET_MANIFEST.read_text())['model_sha256'],
        '--features', str(SUBSET_FEATURES),
        '--observation-provenance', 'RUNTIME_LOG'])
    assert proc.returncode == 4, proc.stderr[-400:]
    assert b'MAPPING_BLOCKED' in proc.stderr


# ---------------------------------------------------------------- OFFLINE_RESEARCH
def test_subset_model_manifest_matches_delivered_file():
    manifest = json.loads(SUBSET_MANIFEST.read_text(encoding='utf-8'))
    raw = SUBSET_MODEL.read_bytes()
    assert manifest['model_sha256'] == hashlib.sha256(raw).hexdigest()
    assert manifest['model_size_bytes'] == len(raw)
    model = json.loads(raw)
    assert model['feature_names'] == json.loads(
        SUBSET_FEATURES.read_text(encoding='utf-8'))['feature_names']
    # 诚实性：门槛未通过、效果未证明
    assert manifest['validation_gate_passed'] is False
    assert manifest['detector_effectiveness'] == 'NOT_PROVEN'
    assert manifest['measured_on_test_split']['f1'] < \
        manifest['measured_on_test_split']['always_attack_f1']
    assert all(name in model['feature_names'] for name in
               json.loads(SUBSET_FEATURES.read_text())['feature_names'])


def test_runtime_subset_model_consumes_real_features(snapshot):
    """真实 /proc 特征 -> 24 维模型 -> 合法输出；门槛未过，绝不会 NORMAL。"""
    manifest = json.loads(SUBSET_MANIFEST.read_text(encoding='utf-8'))
    document = build_envelope(snapshot)
    proc = run_module(document, [
        '--model', str(SUBSET_MODEL),
        '--model-sha256', manifest['model_sha256'],
        '--features', str(SUBSET_FEATURES),
        '--observation-provenance', 'RUNTIME_LOG'])
    assert proc.returncode == 0, proc.stderr[-400:]
    out = json.loads(proc.stdout)
    assert not vtc.validate_document(out, vtc.load_schema('comm_risk_evidence'))
    assert out['status'] in ('UNKNOWN', 'SUSPICIOUS')
    assert out['status'] != 'NORMAL'
    extension = out['extensions']['member1_comm']
    assert extension['model_sha256'] == manifest['model_sha256']
    assert isinstance(extension['score'], float)
    assert extension['trusted_provenance'] == 'RUNTIME_LOG'
    assert extension['envelope_provenance'] == 'RUNTIME_LOG'


def test_49_feature_model_rejects_the_runtime_subset(snapshot):
    """24 维真实观测不能喂给 49 维模型：必须 UNKNOWN，不得补零/猜列。"""
    manifest = json.loads(FULL_MANIFEST.read_text(encoding='utf-8'))
    document = build_envelope(snapshot)
    proc = run_module(document, [
        '--model', str(FULL_MODEL),
        '--model-sha256', manifest['model_sha256'],
        '--features', str(FULL_FEATURES),
        '--observation-provenance', 'RUNTIME_LOG'])
    assert proc.returncode == 0, proc.stderr[-400:]
    out = json.loads(proc.stdout)
    assert out['status'] == 'UNKNOWN'
    assert 'FEATURE_NAMES_ABSENT_OR_ORDER_MISMATCH' in out['reason']


# ---------------------------------------------------------------- 可行性矩阵
def test_feasibility_matrix_matches_measured_capabilities():
    document = json.loads(FEASIBILITY.read_text(encoding='utf-8'))
    counts = document['summary']['counts']
    assert counts['COLLECTABLE_RUNTIME_OK'] == 24
    assert counts['COLLECTABLE_RUNTIME_MISSING_ON_HOST'] == 1
    assert counts['REQUIRES_PCAP_DISSECTION'] == 22
    assert counts['REQUIRES_ROS_GRAPH'] == 2
    assert document['summary']['runtime_subset_size'] == 24
    rows = {row['feature']: row for row in document['features']}
    assert rows['pgalloc_dma']['collectable'] == 'COLLECTABLE_RUNTIME_MISSING_ON_HOST'
    assert rows['subscribers_count']['collectable'] == 'REQUIRES_ROS_GRAPH'
    assert rows['layers.tcp.tcp.window_size']['collectable'] == 'REQUIRES_PCAP_DISSECTION'
    assert rows['Tcp_Established']['collectable'] == 'COLLECTABLE_RUNTIME_OK'
    # 每个"可采集"都必须有真实实现（不是文档里写写）
    for row in document['features']:
        if row['collectable'] == 'COLLECTABLE_RUNTIME_OK':
            assert row['feature'] in proc_runtime.SPECS, row['feature']
    # 语义等价性一律未验证（不得被悄悄写成 EQUIVALENT）
    assert all(row['semantic_equivalence'] == 'UNVERIFIED'
               for row in document['features'])
    # 没有 ROS 2 / tshark 的环境事实必须被记下来
    probe = document['environment_probe']
    assert probe['ros_available'] is False
    assert probe['tshark'] is None
