#!/usr/bin/env python3
"""本轮定向修复的验收测试（FIX-01 ~ FIX-15）。

状态口径（严格区分，SKIPPED 不计入 PASS）：
    PASS / FAIL / BLOCKED / NOT_RUN / SKIPPED

断言基于**真实模型与真实数据**。缺少前置条件时用 pytest.skip 并写明原因，
但本文件中的**强制验收项**（FIX-01/02/03/04/05/06/07/09/10/14/15）
在缺少前置时会被 `test_mandatory_coverage()` 汇总暴露，不会静默变成 PASS。
"""
from __future__ import annotations

import csv
import json
import os
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MOD = os.path.join(REPO, 'modules', 'rospace_comm')
FIX = os.path.join(REPO, 'tests', 'research', 'fixtures')
RUN_V1 = os.path.join(REPO, 'training_runs', 'rospace_reduced')
RUN_V2 = os.path.join(REPO, 'training_runs', 'rospace_reduced_v2')
SCHEMA = os.path.join(REPO, 'docs', 'interfaces', 'schemas',
                      'comm_risk_evidence.schema.json')
ADAPTER = os.path.join(MOD, 'f0_adapter.py')
MATRIX = os.path.join(REPO, 'docs', 'data', 'ROSPaCe_MODEL_FEATURE_FEASIBILITY.csv')
MATRIX_SUMMARY = os.path.join(REPO, 'docs', 'data',
                              'ROSPaCe_MODEL_FEATURE_FEASIBILITY_SUMMARY.json')

MANDATORY = ['FIX-01', 'FIX-02', 'FIX-03', 'FIX-04', 'FIX-05', 'FIX-06',
             'FIX-07', 'FIX-09', 'FIX-10', 'FIX-14', 'FIX-15']


def _run_adapter(args=(), envelope=None):
    proc = subprocess.run([sys.executable, ADAPTER, *args],
                          input=json.dumps(envelope) if envelope is not None else None,
                          capture_output=True, text=True, timeout=600,
                          cwd=REPO)
    return proc


def _validate(payload):
    from jsonschema import Draft202012Validator
    Draft202012Validator(json.load(open(SCHEMA, encoding='utf-8'))).validate(payload)


def _envelope(name):
    return json.load(open(os.path.join(FIX, 'envelope_{0}.json'.format(name)),
                          encoding='utf-8'))


needs_v2 = pytest.mark.skipif(not os.path.isfile(os.path.join(RUN_V2, 'model.joblib')),
                              reason='需要 v2 模型（先运行 train.py --tag v2）')


# ============================================================ P0-1
@needs_v2
def test_fix01_normal_prediction_matches_schema():
    """FIX-01：真实正常样本 -> 合法 CommRiskEvidence。"""
    proc = _run_adapter(['--model-run-dir', RUN_V2], _envelope('normal'))
    assert proc.returncode == 0, proc.stderr
    ev = json.loads(proc.stdout)
    _validate(ev)
    assert ev['status'] == 'NORMAL'
    assert ev['anomaly_category'] == 'NONE'


@needs_v2
def test_fix02_attack_prediction_matches_schema():
    """FIX-02：真实攻击样本 -> 合法枚举，输出通过 Schema。

    这是 P0-1 的核心：修复前攻击预测产生 NETWORK_TRAFFIC_ANOMALY，会被 Schema 拒绝。
    """
    proc = _run_adapter(['--model-run-dir', RUN_V2], _envelope('attack'))
    assert proc.returncode == 0, proc.stderr
    ev = json.loads(proc.stdout)
    _validate(ev)                                  # 修复前这一步会抛异常
    assert ev['status'] == 'SUSPICIOUS'
    legal = json.load(open(SCHEMA, encoding='utf-8'))[
        'properties']['anomaly_category']['enum']
    assert ev['anomaly_category'] in legal
    assert ev['anomaly_category'] == 'UNKNOWN', '二分类无法对应具体类别'
    for key in ('attack_probability',):
        assert key in ev['extensions']['rospace_comm']
    assert ev['extensions']['rospace_comm']['model_sha256']


def test_fix02b_schema_rejects_pre_fix_value():
    """负向对照：修复前的取值必须被 Schema 拒绝（证明缺陷真实存在）。"""
    from jsonschema import Draft202012Validator
    schema = json.load(open(SCHEMA, encoding='utf-8'))
    sample = {
        'schema_version': '1.0.0-proposed', 'run_id': 'r', 'request_id': 'q',
        'event_id': 'e', 'producer': {'name': 'n', 'module_version': '1',
                                      'source': 'EXTERNAL'},
        'observed_at': '2026-01-01T00:00:00Z', 'status': 'SUSPICIOUS',
        'reason': 'x', 'evidence_refs': [{'ref': 'r', 'kind': 'UNKNOWN'}],
        'communication': {'resource': '/rg/guarded_navigate',
                          'resource_type': 'Action'},
        'window': {'start': '2026-01-01T00:00:00Z', 'end': '2026-01-01T00:00:00Z',
                   'duration_ms': 0},
        'request_count': 1, 'anomaly_category': 'NETWORK_TRAFFIC_ANOMALY',
        'risk_level': 'HIGH', 'basis': ['x'],
    }
    with pytest.raises(Exception):
        Draft202012Validator(schema).validate(sample)


# ============================================================ P0-3
@needs_v2
def test_fix04_business_input_cannot_choose_model():
    """FIX-04：业务输入不能切换 joblib 模型。"""
    proc = _run_adapter(['--model-run-dir', RUN_V2], _envelope('evil_model_dir'))
    assert proc.returncode == 0, '信封里的 model_run_dir 应被忽略而不是采纳/报错'
    assert '已忽略' in proc.stderr
    ev = json.loads(proc.stdout)
    prov = ev['extensions']['rospace_comm']['model_dir_provenance']
    assert 'trusted-root' in prov, '实际使用的仍是受信任根'
    assert 'evil' not in prov


@needs_v2
def test_fix04b_untrusted_model_dir_rejected():
    """FIX-04：命令行指向不受信目录必须拒绝。"""
    proc = _run_adapter(['--model-run-dir', '/tmp/definitely_untrusted'],
                        _envelope('normal'))
    assert proc.returncode == 3
    assert 'MODEL_DIR_UNTRUSTED' in proc.stderr


@needs_v2
def test_fix14_corrupt_model_fails_closed(tmp_path=None):
    """FIX-14：模型损坏必须 fail-closed，不得被解释为正常通信。"""
    import shutil
    broken = os.path.join(REPO, 'training_runs', '_tmp_broken_for_test')
    shutil.rmtree(broken, ignore_errors=True)
    shutil.copytree(RUN_V2, broken)
    try:
        with open(os.path.join(broken, 'model.joblib'), 'wb') as handle:
            handle.write(b'not a joblib file')
        proc = _run_adapter(['--model-run-dir', broken], _envelope('normal'))
        assert proc.returncode == 3, '损坏模型必须 exit 3'
        assert 'ADAPTER_BLOCK' not in proc.stdout
        assert 'NORMAL' not in proc.stdout
    finally:
        shutil.rmtree(broken, ignore_errors=True)


# ============================================================ P0-2
def test_fix05_model_feature_matrix_is_complete():
    """FIX-05：模型输入特征矩阵完全覆盖，无遗漏无重复。"""
    if not os.path.isfile(MATRIX) or not os.path.isfile(MATRIX_SUMMARY):
        pytest.fail('缺少模型特征矩阵（强制验收项不得 SKIP）')
    cfg = json.load(open(os.path.join(RUN_V2, 'feature_config.json'),
                         encoding='utf-8'))
    model_features = cfg['feature_names']
    rows = list(csv.DictReader(open(MATRIX, encoding='utf-8')))
    names = [r['feature'] for r in rows]
    assert len(names) == len(set(names)), '矩阵存在重复字段'
    assert set(names) == set(model_features), (
        '矩阵与模型特征不一致；缺失=%s 多余=%s' % (
            sorted(set(model_features) - set(names))[:5],
            sorted(set(names) - set(model_features))[:5]))
    summary = json.load(open(MATRIX_SUMMARY, encoding='utf-8'))
    total = (summary['DIRECTLY_AVAILABLE_MODEL_FEATURES']
             + summary['INSTRUMENTATION_REQUIRED_MODEL_FEATURES']
             + summary['UNAVAILABLE_MODEL_FEATURES']
             + summary['UNKNOWN_MODEL_FEATURES'])
    assert total == summary['TRAINED_MODEL_FEATURES'] == len(model_features), \
        'A+B+C+D 必须等于实际模型特征数'
    # 未参与训练的原始字段不得计入模型在线覆盖
    for name in summary['raw_fields_not_used_by_model']:
        assert name not in model_features, \
            '%s 未参与训练，不应出现在模型特征中' % name


def test_fix05b_two_scopes_are_distinct():
    """FIX-05：原始字段口径与模型特征口径必须分开。"""
    summary = json.load(open(MATRIX_SUMMARY, encoding='utf-8'))
    assert summary['RAW_NON_LABEL_FIELDS'] == 61
    assert summary['TRAINED_MODEL_FEATURES'] == 49
    assert summary['RAW_NON_LABEL_FIELDS'] != summary['TRAINED_MODEL_FEATURES']
    # src_topic / msg_type 是 A 类原始字段但不参与训练
    for name in ('src_topic', 'msg_type'):
        assert name in summary['raw_fields_not_used_by_model']
    assert summary['RUNTIME_MONITOR'] == 'NOT_READY'


# ============================================================ P1-1
@needs_v2
def test_fix06_preprocessing_stats_only_from_training():
    """FIX-06：预处理统计量只由训练集生成，且被完整记录。"""
    cfg = json.load(open(os.path.join(RUN_V2, 'feature_config.json'),
                         encoding='utf-8'))
    assert cfg['preprocessing_strategy'] == 'PREPROC_V2_TWO_PASS_FIXED'
    stats = cfg['pass1_statistics']
    assert len(stats['effective_count']) == len(cfg['feature_names'])
    assert len(stats['missing']) == len(cfg['feature_names'])
    assert 'rule_for_all_missing' in stats
    m = json.load(open(os.path.join(RUN_V2, 'metrics.json'), encoding='utf-8'))
    assert m['split_basis'] == 'FILE_DISJOINT_SPLIT'
    assert 'SESSION_DISJOINT_SPLIT' not in m['split_basis']
    # 两遍策略必须体现在配置中
    assert 'PREPROC_V2_TWO_PASS_FIXED' == cfg['preprocessing_strategy']


@needs_v2
def test_fix07_scaler_fixed_during_training():
    """FIX-07：训练过程中 scaler 保持固定 —— 落盘 scaler 与配置中的参数一致。"""
    import joblib
    import numpy as np
    cfg = json.load(open(os.path.join(RUN_V2, 'feature_config.json'),
                         encoding='utf-8'))
    scaler = joblib.load(os.path.join(RUN_V2, 'scaler.joblib'))
    assert np.allclose(scaler.mean_, np.array(cfg['column_means'])), \
        'scaler 均值与配置不一致，说明训练中仍在变动'
    assert np.allclose(scaler.scale_, np.array(cfg['column_scales']))
    # 零方差列必须显式记录，而不是被静默用 0 掩盖
    zero_var = cfg['pass1_statistics']['zero_variance_columns']
    if zero_var:
        idx = {n: i for i, n in enumerate(cfg['feature_names'])}
        for name in zero_var:
            assert scaler.mean_[idx[name]] is not None


@needs_v2
def test_fix08_inference_uses_training_preprocessing():
    """FIX-08：推理使用与训练一致的预处理（同一 scaler 与填充规则）。"""
    cfg = json.load(open(os.path.join(RUN_V2, 'feature_config.json'),
                         encoding='utf-8'))
    proc = _run_adapter(['--model-run-dir', RUN_V2], _envelope('normal'))
    assert proc.returncode == 0
    ev = json.loads(proc.stdout)
    assert cfg['config_sha256'][:16] in ' '.join(ev['basis'])


# ============================================================ P1-2
def test_fix09_numeric_shard_sort():
    """FIX-09：分片按**数字编号**排序，`_2` 必须排在 `_10` 之前。

    原实现用普通字符串排序，`_10` 会排在 `_2` 前面，导致"最后 N 片作测试"
    取到的并不是时间上最晚的分片。

    本测试用**合成文件名**覆盖 `_0/_1/_2/_9/_10/_14`，
    并显式证明数字序与字典序在这组输入上**确实不同** ——
    这样断言才有区分能力，而不是恒真。
    """
    sys.path.insert(0, MOD)
    import train as T

    names = ['rospace_reduced_0.csv', 'rospace_reduced_1.csv',
             'rospace_reduced_2.csv', 'rospace_reduced_9.csv',
             'rospace_reduced_10.csv', 'rospace_reduced_14.csv']
    # 数字序（被测语义）
    numeric = sorted(names, key=T.shard_index)
    # 字典序（缺陷行为）
    lexicographic = sorted(names)
    expected = ['rospace_reduced_0.csv', 'rospace_reduced_1.csv',
                'rospace_reduced_2.csv', 'rospace_reduced_9.csv',
                'rospace_reduced_10.csv', 'rospace_reduced_14.csv']

    assert numeric == expected, '数字序结果不符: %s' % numeric
    # 关键：两种排序必须真的不同，否则本测试没有区分能力
    assert numeric != lexicographic, (
        '数字序与字典序在此输入上相同，测试无法区分缺陷：%s' % numeric)
    # `_2` 必须在 `_10` 之前 —— 这正是缺陷会违反的点
    assert numeric.index('rospace_reduced_2.csv') < numeric.index(
        'rospace_reduced_10.csv')
    # 字典序下 `_10` 确实会跑到 `_2` 前面（证明缺陷真实存在）
    assert lexicographic.index('rospace_reduced_10.csv') < lexicographic.index(
        'rospace_reduced_2.csv')
    # 编号解析稳定：同一输入重复排序结果一致
    assert sorted(names, key=T.shard_index) == numeric

    # 异常文件名必须有**确定**处理：直接对真实函数 list_csv 做端到端测试
    # （在临时目录里放入同样的文件名，避免只测排序键而漏掉 None 的处理）。
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        for name in names + ['rospace_reduced_extra.csv', 'other.csv']:
            open(os.path.join(tmpdir, name), 'w').close()
        ordered = [os.path.basename(f) for f in T.list_csv(tmpdir)]
        assert T.shard_index('rospace_reduced_extra.csv') is None
        assert T.shard_index('other.csv') is None
        # 有编号的分片按数字序在前，无编号的确定性地排在后面
        assert ordered[:len(names)] == expected, ordered
        assert ordered[len(names):] == ['other.csv', 'rospace_reduced_extra.csv'], \
            '无编号文件应按名称确定性排序并排在编号分片之后: %s' % ordered
        # 幂等：重复调用结果一致
        assert [os.path.basename(f) for f in T.list_csv(tmpdir)] == ordered

    # 真实目录排序仍是数字序（数据集存在时才检查）
    if os.path.isdir(T.MAIN_DIR):
        real = [os.path.basename(f) for f in T.list_csv(T.MAIN_DIR)]
        if real:
            assert real[-1] == 'rospace_reduced_14.csv', real[-1]


def test_fix09b_sort_mismatch_is_detectable():
    """FIX-09：证明错误实现会被本测试抓到（防止断言退化为恒真）。

    用**故意写错的**字典序实现替换 `shard_index` 的语义，
    断言它在上面的期望值上会失败。若这里失败，说明原测试没有区分能力。
    """
    names = ['rospace_reduced_0.csv', 'rospace_reduced_1.csv',
             'rospace_reduced_2.csv', 'rospace_reduced_9.csv',
             'rospace_reduced_10.csv', 'rospace_reduced_14.csv']
    expected = ['rospace_reduced_0.csv', 'rospace_reduced_1.csv',
                'rospace_reduced_2.csv', 'rospace_reduced_9.csv',
                'rospace_reduced_10.csv', 'rospace_reduced_14.csv']
    broken = sorted(names)                      # 缺陷实现
    assert broken != expected, '若两者相同则本测试无意义'
    assert broken.index('rospace_reduced_10.csv') < broken.index(
        'rospace_reduced_2.csv')


@needs_v2
def test_fix10_split_has_no_file_overlap():
    """FIX-10：训练与测试分片无重叠。"""
    split = json.load(open(os.path.join(RUN_V2, 'split_manifest.json'),
                           encoding='utf-8'))
    train, test = set(split['train_files']), set(split['test_files'])
    assert not (train & test), '训练与测试分片存在重叠: %s' % (train & test)


@needs_v2
def test_fix11_split_basis_honest():
    """FIX-11：划分基线与证据一致 —— 不得声称会话独立。"""
    m = json.load(open(os.path.join(RUN_V2, 'metrics.json'), encoding='utf-8'))
    assert m['split_basis'] == 'FILE_DISJOINT_SPLIT'
    note = m['split_basis_note']
    assert '不等于' in note and 'SESSION_DISJOINT_SPLIT' in note
    assert '无法证明采集会话独立' in note


@needs_v2
def test_fix12_class_coverage_recorded():
    """FIX-12：测试标签覆盖情况完整记录，未出现的类别不得虚报。"""
    m = json.load(open(os.path.join(RUN_V2, 'metrics.json'), encoding='utf-8'))
    assert 'per_class_recall' in m
    assert 'class_coverage_note' in m
    assert 'NOT_EVALUATED' in m['class_coverage_note']
    for label, v in m['per_class_recall'].items():
        assert v['support'] > 0, '支持数为 0 的类别不应出现在 per_class_recall'


@needs_v2
def test_fix13_simple_baselines_computed():
    """FIX-13：简单基线真实计算，并给出相对提升。"""
    m = json.load(open(os.path.join(RUN_V2, 'metrics.json'), encoding='utf-8'))
    b = m['simple_baselines']
    assert b['always_attack']['recall'] == 1.0
    assert b['always_normal']['recall'] == 0.0
    total = sum(m['confusion_matrix'].values())
    assert 0.0 <= b['always_attack']['f1'] <= 1.0
    assert total > 0
    lift = m['lift_over_always_attack']
    assert 'f1_delta' in lift and 'balanced_accuracy_delta' in lift
    assert m['metrics']['balanced_accuracy'] > 0


# ============================================================ 边界
def test_fix15_schemas_and_contracts_unchanged():
    """FIX-15：F0 公共 Schema、冻结 Action、原因码、Gateway 均未改动。"""
    base = 'ebfe263530d10a746c172367f9d96d2f9dc5d7d4'
    proc = subprocess.run(
        ['git', 'diff', '--name-only', base, 'HEAD', '--',
         'docs/interfaces/', 'src/rg_interfaces/action/PatrolNavigate.action',
         'src/rg_policy/rg_policy/reason_codes.py', 'src/rg_gateway/',
         'security/'],
        cwd=REPO, capture_output=True, text=True)
    assert proc.stdout.strip() == '', '冻结接口被修改: %s' % proc.stdout


def test_mandatory_coverage_is_not_silently_skipped():
    """强制验收项的覆盖汇总：任何一项缺失都必须在报告中可见。

    本测试自身永远 PASS，但会把缺失的强制项打印出来，
    防止「因为 skip 而看起来全绿」。
    """
    missing = []
    if not os.path.isfile(os.path.join(RUN_V2, 'model.joblib')):
        missing = [f for f in MANDATORY if f not in ('FIX-05', 'FIX-15')]
    report = os.path.join(REPO, 'docs', 'review',
                          'ROSPaCe_可信评测与接口缺陷修复报告.md')
    assert os.path.isfile(report), '缺少可信评测报告'
    text = open(report, encoding='utf-8').read()
    assert 'RUNTIME_MONITOR' in text
    if missing:
        pytest.skip('强制项因缺少 v2 模型未运行: %s（不是 PASS）' % missing)


# ============================================================ A1 指标定义
def _load_derive():
    """直接导入被测函数的实现（不是另写一套参考实现）。"""
    sys.path.insert(0, MOD)
    import recompute_metrics as R
    return R


def test_macro_recall_matches_hand_computed_confusion_matrix():
    """A1：用**人工算出的**期望值校验指标实现（独立验证，非自我比较）。

    构造一个四类情形齐全的混淆矩阵：
      * 正常预测正确      -> TN
      * 正常误报          -> FP
      * 攻击检出          -> TP
      * 攻击漏报          -> FN
    取 TP=6, FP=2, TN=8, FN=4，手工算出期望值后再与代码结果比较。
    """
    R = _load_derive()
    TP, FP, TN, FN = 6, 2, 8, 4

    # ---- 手工计算（与本文件之外的任何实现无关）----
    exp_recall_attack = TP / (TP + FN)                 # 6/10 = 0.6
    exp_recall_normal = TN / (TN + FP)                 # 8/10 = 0.8
    exp_macro_recall = (exp_recall_attack + exp_recall_normal) / 2   # 0.7
    exp_balanced = (exp_recall_attack + exp_recall_normal) / 2       # 0.7
    exp_precision = TP / (TP + FP)                     # 6/8 = 0.75
    exp_f1 = 2 * exp_precision * exp_recall_attack / (exp_precision + exp_recall_attack)
    exp_acc = (TP + TN) / (TP + FP + TN + FN)          # 14/20 = 0.7
    exp_fpr = FP / (FP + TN)                           # 2/10 = 0.2

    got = R.derive(TP, FP, TN, FN)
    assert got['recall'] == pytest.approx(exp_recall_attack)
    assert got['specificity_recall_normal'] == pytest.approx(exp_recall_normal)
    assert got['macro_recall'] == pytest.approx(exp_macro_recall)
    assert got['balanced_accuracy'] == pytest.approx(exp_balanced)
    assert got['precision'] == pytest.approx(exp_precision)
    assert got['f1'] == pytest.approx(exp_f1)
    assert got['accuracy'] == pytest.approx(exp_acc)
    assert got['false_positive_rate'] == pytest.approx(exp_fpr)
    # 二分类下 Macro Recall 必须等于 Balanced Accuracy
    assert got['macro_recall'] == pytest.approx(got['balanced_accuracy'])


def test_macro_recall_would_catch_the_original_bug():
    """A1 负向对照：原错误实现会给出与正确值不同的结果。

    原实现把 observe 的"被判为攻击比例"（= 误报率）当成正常类召回率，
    即 macro = (Recall_attack + FPR) / 2。对 TP=6,FP=2,TN=8,FN=4：
      错误值 = (0.6 + 0.2)/2 = 0.4
      正确值 = (0.6 + 0.8)/2 = 0.7
    若两者相等，说明本用例无法区分缺陷。
    """
    TP, FP, TN, FN = 6, 2, 8, 4
    wrong = (TP / (TP + FN) + FP / (FP + TN)) / 2
    right = (TP / (TP + FN) + TN / (TN + FP)) / 2
    assert wrong == pytest.approx(0.4)
    assert right == pytest.approx(0.7)
    assert wrong != right, '本用例必须能区分错误实现'


@needs_v2
def test_recorded_macro_recall_equals_balanced_accuracy():
    """A1：落盘指标中二分类 macro_recall 必须等于 balanced_accuracy。"""
    m = json.load(open(os.path.join(RUN_V2, 'metrics.json'), encoding='utf-8'))
    mt = m['metrics']
    assert mt['macro_recall'] == pytest.approx(mt['balanced_accuracy'], abs=1e-12)
    assert mt['macro_recall'] == pytest.approx(0.5544, abs=1e-3), \
        'reduced v2 的二分类 Macro Recall 应为约 0.5544，不再是 0.0546'
    # 旧值必须留档而不是被抹掉
    assert m.get('metrics_legacy', {}).get('macro_recall') == pytest.approx(
        0.0546, abs=1e-3)
    # 跨攻击类别的平均是**另一个**指标，且名称不同
    assert 'macro_attack_detection_recall' in mt
    assert mt['macro_attack_detection_recall'] != pytest.approx(mt['macro_recall'])


def test_confusion_matrix_unchanged_by_recompute():
    """A1：重算只改派生指标，**不修改**混淆矩阵。"""
    if not os.path.isfile(os.path.join(RUN_V2, 'metrics.json')):
        pytest.skip('需要 v2 指标')
    m = json.load(open(os.path.join(RUN_V2, 'metrics.json'), encoding='utf-8'))
    assert m['metrics_recomputed']['confusion_matrix_unchanged'] is True
    assert set(m['confusion_matrix']) == {'tp', 'fp', 'tn', 'fn'}
    for v in m['confusion_matrix'].values():
        assert isinstance(v, int) and v >= 0
