#!/usr/bin/env python3
"""ROSPaCe 数据适配与检测基线的真实测试（DATA / MODEL / COMPARISON / JAZZY / F0）。

设计原则
--------
* 断言基于**真实文件与真实模型**，不使用桩数据替代数据集本身。
* 需要 22 GB 原始数据或已训练模型的重型用例，在缺少前置时 **skip 并说明原因**，
  而不是伪造通过。
* 每个断言都指向可复核的产物路径。

运行：
    .research-venv/bin/python -m pytest tests/research/test_rospace_adapter.py -v
"""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, 'modules', 'rospace_comm'))

MAIN_DIR = os.path.join(REPO, 'data', 'ROSPaCe_reduced', 'ROSPaCe_reduced')
NOPER_DIR = os.path.join(REPO, 'data', 'ROSPaCe_reduced',
                         'ROSPaCe_reduced_noperiodicity')
FEATURE_LIST = os.path.join(REPO, 'data', 'ROSPaCe_reduced', 'feature_list.xlsx')
MANIFEST = os.path.join(REPO, 'docs', 'data', 'ROSPaCe_DATA_MANIFEST.json')
FEASIBILITY = os.path.join(REPO, 'docs', 'data',
                           'ROSPaCe_JAZZY_FEATURE_FEASIBILITY.csv')
RUN_REDUCED = os.path.join(REPO, 'training_runs', 'rospace_reduced')
RUN_NOPER = os.path.join(REPO, 'training_runs', 'rospace_noperiodicity')
ADAPTER = os.path.join(REPO, 'modules', 'rospace_comm', 'f0_adapter.py')
ENVELOPE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures')

needs_data = pytest.mark.skipif(not os.path.isdir(MAIN_DIR),
                                reason='需要 ROSPaCe 原始数据（本地未下载）')
needs_model = pytest.mark.skipif(
    not os.path.isfile(os.path.join(RUN_REDUCED, 'model.joblib')),
    reason='需要先运行 train.py 生成模型')


# ============================================================ DATA
@needs_data
def test_both_datasets_and_feature_list_exist():
    assert os.path.isdir(MAIN_DIR), '主数据集目录缺失'
    assert os.path.isdir(NOPER_DIR), '去周期性数据集目录缺失'
    assert os.path.isfile(FEATURE_LIST), 'feature_list.xlsx 缺失'
    assert len([f for f in os.listdir(MAIN_DIR) if f.endswith('.csv')]) == 15
    assert len([f for f in os.listdir(NOPER_DIR) if f.endswith('.csv')]) == 10


@needs_data
def test_only_first_shard_has_header():
    """每个数据集只有 _0 分片带表头——这是标签统计能否正确的前提。"""
    def has_header(path):
        with open(path, encoding='utf-8', errors='replace') as handle:
            return handle.readline().startswith('timestamp,')

    assert has_header(os.path.join(MAIN_DIR, 'rospace_reduced_0.csv'))
    for name in ('rospace_reduced_1.csv', 'rospace_reduced_5.csv',
                 'rospace_reduced_14.csv'):
        assert not has_header(os.path.join(MAIN_DIR, name)), \
            '{0} 不应带表头（首行即数据）'.format(name)


@needs_data
def test_headers_identical_when_reference_is_used():
    """无表头分片沿用参考表头后，列名与列数应与 _0 完全一致。"""
    import inspect_data as idm
    ref = idm.read_header(os.path.join(MAIN_DIR, 'rospace_reduced_0.csv'))
    assert len(ref) == 62 and ref[-1] == 'attack'
    for name in ('rospace_reduced_1.csv', 'rospace_reduced_9.csv'):
        header = idm.read_header(os.path.join(MAIN_DIR, name), ref)
        assert header == ref


def test_label_distribution_matches_full_scan():
    """标签分布必须来自全量扫描，且状态为 FULL。"""
    if not os.path.isfile(MANIFEST):
        pytest.skip('需要先运行 inspect_data.py')
    manifest = json.load(open(MANIFEST, encoding='utf-8'))
    assert manifest['statistics_status'] == 'FULL', '统计被截断，不得当作全量'
    # 主数据集全量行数（实测值，非估算）
    assert manifest['full_dataset_rows'] == 30_247_050
    labels = manifest['label_counts']
    assert set(labels) == {
        'observe', 'metasploit SYN flood', 'nmap SYN flood', 'nmap discovery',
        'ros2 reconnaissance', 'ros2 node crashing', 'ros2 reflection'}
    # 标签统计必须覆盖全部行（这正是"表头探测"缺陷会造成的问题）
    assert sum(labels.values()) == manifest['full_dataset_rows'], \
        '标签计数之和 != 全量行数，说明部分分片的标签没有被统计'


def test_label_is_string_not_binary():
    """标签是字符串，不得假设 0/1。"""
    if not os.path.isfile(MANIFEST):
        pytest.skip('需要 manifest')
    labels = json.load(open(MANIFEST, encoding='utf-8'))['label_counts']
    assert '0' not in labels and '1' not in labels
    assert 'observe' in labels, '缺少正常类标签 observe'


@needs_data
def test_feature_dictionary_covers_all_columns():
    """模型用到的每一列都能在 feature_list 中找到说明。"""
    dict_path = os.path.join(REPO, 'docs', 'data',
                             'ROSPaCe_FEATURE_DICTIONARY.csv')
    if not os.path.isfile(dict_path):
        pytest.skip('需要 feature dictionary')
    rows = list(csv.DictReader(open(dict_path, encoding='utf-8')))
    in_main = [r for r in rows if r['in_reduced_main'] == 'yes']
    assert len(in_main) == 62
    unknown = [r['feature_name'] for r in in_main
               if r['semantics'] == 'SEMANTICS_UNKNOWN']
    # 实测结论：**唯一**没有语义说明的是标签列 attack 本身。
    # 数据集作者在 feature_list 中把 attack 的 monitor 与 description 都留空，
    # 因此标签含义只能由实际取值确定（见 test_label_is_string_not_binary）。
    # 这一条断言把这个事实固定下来：既确认特征列都有说明，
    # 也确认"标签语义未文档化"是数据集的真实状态而不是我们的疏漏。
    assert unknown == ['attack'], (
        '期望只有标签列 attack 无语义说明，实际: {0}'.format(unknown))
    feature_cols = [r for r in in_main if r['feature_name'] != 'attack']
    assert all(r['semantics'] == 'DESCRIBED' for r in feature_cols), \
        '存在未解释的特征列'


# ============================================================ MODEL
@needs_model
def test_model_artifacts_and_metrics_present():
    metrics = json.load(open(os.path.join(RUN_REDUCED, 'metrics.json'),
                             encoding='utf-8'))
    for key in ('accuracy', 'precision', 'recall', 'f1', 'false_positive_rate'):
        assert key in metrics['metrics']
    assert len(metrics['model_sha256']) == 64
    assert metrics['statistics_scope']['TRAINING_SUBSET_rows'] > 0
    # 必须严格区分全量统计与训练子集
    assert metrics['statistics_scope']['full_dataset_rows'] == 30_247_050
    assert (metrics['statistics_scope']['TRAINING_SUBSET_rows']
            < metrics['statistics_scope']['full_dataset_rows'])


@needs_model
def test_test_set_contains_both_classes():
    """测试集必须是双类别，否则指标是被类别分布伪造的。"""
    metrics = json.load(open(os.path.join(RUN_REDUCED, 'metrics.json'),
                             encoding='utf-8'))
    cm = metrics['confusion_matrix']
    assert cm['tn'] + cm['fp'] > 0, '测试集没有正常样本，指标无意义'
    assert cm['tp'] + cm['fn'] > 0, '测试集没有攻击样本，指标无意义'


@needs_model
def test_feature_config_is_frozen_and_hashed():
    cfg = json.load(open(os.path.join(RUN_REDUCED, 'feature_config.json'),
                         encoding='utf-8'))
    assert cfg['feature_order_frozen'] is True
    assert len(cfg['feature_names']) == 49
    assert 'attack' not in cfg['feature_names'], '标签列不得进入特征'
    assert len(cfg['config_sha256']) == 64
    assert cfg['missing_value_rule'] == 'training_set_column_mean'


@needs_model
def test_missing_model_fails_closed():
    """缺模型必须以非零退出码失败，不得默认返回正常。"""
    proc = subprocess.run(
        [sys.executable, os.path.join(REPO, 'modules', 'rospace_comm', 'predict.py'),
         '--run-dir', '/tmp/definitely_no_such_run', '--csv-row', 'x:1'],
        capture_output=True, text=True, timeout=300)
    assert proc.returncode == 3, '缺模型应返回 3，实际 {0}'.format(proc.returncode)
    assert '不得在缺少模型时默认返回' in proc.stderr


@needs_model
def test_missing_features_fail_closed_no_zero_fill():
    """缺特征必须失败（退出码 4），不得静默填 0。"""
    proc = subprocess.run(
        [sys.executable, os.path.join(REPO, 'modules', 'rospace_comm', 'predict.py'),
         '--run-dir', RUN_REDUCED, '--input', '/dev/stdin'],
        input='{"timestamp":"2026-01-01T00:00:00Z","Net_Sent":1.0}\n',
        capture_output=True, text=True, timeout=300)
    assert proc.returncode == 4, '缺特征应返回 4，实际 {0}'.format(proc.returncode)
    assert '不填充 0' in proc.stderr


# ============================================================ COMPARISON
@needs_model
def test_both_datasets_trained_independently():
    for run in (RUN_REDUCED, RUN_NOPER):
        assert os.path.isfile(os.path.join(run, 'model.joblib')), \
            '{0} 缺少模型'.format(run)
    mr = json.load(open(os.path.join(RUN_REDUCED, 'metrics.json'), encoding='utf-8'))
    mn = json.load(open(os.path.join(RUN_NOPER, 'metrics.json'), encoding='utf-8'))
    assert mr['dataset'] == 'reduced'
    assert mn['dataset'] == 'noperiodicity'
    # 两版本是各自独立训练的产物（模型哈希不同）
    assert mr['model_sha256'] != mn['model_sha256'], \
        '两版本模型相同，说明没有独立训练'
    # 模型类别与超参可比
    assert mr['model_class'] == mn['model_class']
    assert mr['model_params'] == mn['model_params']


@needs_model
def test_comparison_reports_limited_conclusion_strength():
    """对照报告必须写明两版本无法建立相同划分，限制结论强度。"""
    report = os.path.join(REPO, 'docs', 'review',
                          'ROSPaCe_双版本检测基线对照报告.md')
    text = open(report, encoding='utf-8').read()
    assert '无法建立相同的实验划分' in text
    assert '不构成' in text and '因果证据' in text
    # 报告必须明确限制适用性：不得宣称实时检测能力
    assert '不得据此宣称实现了 ROS 2 实时入侵检测' in text
    assert '不具备 Jazzy 在线获取能力' in text


# ============================================================ JAZZY_FEATURES
def test_feasibility_matrix_covers_every_model_feature():
    if not os.path.isfile(FEASIBILITY):
        pytest.skip('需要可行性矩阵')
    rows = list(csv.DictReader(open(FEASIBILITY, encoding='utf-8')))
    assert len(rows) > 0
    statuses = {r['status'] for r in rows}
    assert statuses <= {'A', 'B', 'C', 'D'}, '状态必须是四级分类之一'
    # 每个特征都必须有状态与获取方式
    for r in rows:
        assert r['feature'], '存在空特征名'
        assert r['jazzy_mechanism'], '{0} 缺少 Jazzy 获取方式'.format(r['feature'])


def test_a_class_features_have_real_evidence():
    """A 类必须有实测证据（tested=yes）。"""
    if not os.path.isfile(FEASIBILITY):
        pytest.skip('需要可行性矩阵')
    rows = list(csv.DictReader(open(FEASIBILITY, encoding='utf-8')))
    a_rows = [r for r in rows if r['status'] == 'A']
    assert len(a_rows) > 0, '至少要有一个 A 类特征'
    untested = [r['feature'] for r in a_rows if r['tested'] != 'yes']
    assert untested == [], 'A 类特征缺少实测证据: {0}'.format(untested)


def test_model_is_not_claimed_online_ready():
    """模型依赖 B/C/D 类时必须声明 NOT_READY。"""
    summary_path = os.path.join(REPO, 'docs', 'data',
                                'ROSPaCe_JAZZY_FEASIBILITY_SUMMARY.json')
    if not os.path.isfile(summary_path):
        pytest.skip('需要汇总')
    summary = json.load(open(summary_path, encoding='utf-8'))
    assert summary['not_online_usable'] > 0, '若全部可在线获取则不应为 NOT_READY'
    assert summary['A'] < summary['total'], 'A 类不应等于全部特征'


# ============================================================ F0
@pytest.mark.skipif(not os.path.isfile(ADAPTER), reason='需要 f0_adapter.py')
def test_f0_adapter_requires_runtime_request_count():
    """缺 request_count 必须拒绝产出（退出码 4），不得伪造。"""
    envelope = {
        'schema_version': '1.0.0-proposed', 'run_id': 'r', 'request_id': 'q',
        'created_at': '2026-10-11T12:00:00Z',
        'candidate_action': {'action_resource': '/rg/guarded_navigate',
                             'operation': 'NAVIGATE'},
        'observations': [{'source': 'x', 'kind': 'UNKNOWN',
                          'observed_at': '2026-10-11T12:00:00Z',
                          'detail': {'rospace_comm': {'features': {'a': 1.0}}}}],
        'evidence_refs': [{'ref': 'x', 'kind': 'UNKNOWN'}],
    }
    proc = subprocess.run([sys.executable, ADAPTER], input=json.dumps(envelope),
                          capture_output=True, text=True, timeout=300)
    assert proc.returncode == 4, '应返回 4，实际 {0}'.format(proc.returncode)
    assert 'MAPPING_BLOCKED_REQUEST_COUNT' in proc.stderr


@pytest.mark.skipif(not os.path.isfile(ADAPTER), reason='需要 f0_adapter.py')
def test_f0_adapter_rejects_absent_features():
    """缺 ROSPaCe 特征必须失败（退出码 2），不得用本地 CSV 冒充。"""
    envelope = {
        'schema_version': '1.0.0-proposed', 'run_id': 'r', 'request_id': 'q',
        'created_at': '2026-10-11T12:00:00Z',
        'candidate_action': {'action_resource': '/rg/guarded_navigate',
                             'operation': 'NAVIGATE'},
        'observations': [{'source': 'x', 'kind': 'UNKNOWN',
                          'observed_at': '2026-10-11T12:00:00Z', 'detail': {}}],
        'evidence_refs': [{'ref': 'x', 'kind': 'UNKNOWN'}],
    }
    proc = subprocess.run([sys.executable, ADAPTER], input=json.dumps(envelope),
                          capture_output=True, text=True, timeout=300)
    assert proc.returncode == 2
    assert 'ROSPACE_FEATURES_ABSENT' in proc.stderr


def test_public_schemas_unmodified():
    """不得为迁就数据集修改公共 Schema 或冻结契约。"""
    base = os.environ.get('ROSPACE_BASE_SHA', 'ebfe263')
    proc = subprocess.run(
        ['git', 'diff', '--name-only', base, 'HEAD', '--',
         'docs/interfaces/', 'src/rg_interfaces/action/PatrolNavigate.action',
         'src/rg_policy/rg_policy/reason_codes.py', 'src/rg_gateway/'],
        cwd=REPO, capture_output=True, text=True)
    assert proc.stdout.strip() == '', '公共 Schema 或冻结契约被修改: {0}'.format(
        proc.stdout)


def test_acceptance_report_states_runtime_not_ready():
    """验收报告必须如实把 RUNTIME_MONITOR 标为 NOT_READY。"""
    report = os.path.join(REPO, 'docs', 'review',
                          'F0_ROSPaCe数据适配与检测基线验收报告.md')
    text = open(report, encoding='utf-8').read()
    assert 'RUNTIME_MONITOR' in text
    assert 'NOT_READY' in text
    assert '不具备 Jazzy 实时特征获取能力' in text or '离线分类' in text
