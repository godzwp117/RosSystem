"""M1 第六轮评估指标语义的单元测试（用手工构造的混淆矩阵）。

这些测试的作用是把"指标只在适用时才有意义"钉死：
正常会话没有正类就不该有 F1，异常会话没有负类就不该有 FPR。
第五轮把 `min(F1)` 当"最差会话"，导致正常会话被记成 F1=0，
这是**语义错误**，不是模型问题。
"""
from __future__ import annotations

import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

from modules.member1_comm.research.m1_metrics import (  # noqa: E402
    NOT_APPLICABLE, Confusion, aggregate, f1, fpr, precision, recall,
    session_block)


# ---------------------------------------------------------------- 基本运算
def test_confusion_derived_counts():
    c = Confusion(tp=3, fp=2, fn=1, tn=4)
    assert c.positives == 4
    assert c.negatives == 6
    assert c.total == 10


def test_fpr_and_recall_basic():
    c = Confusion(tp=8, fp=2, fn=2, tn=8)
    assert fpr(c) == pytest.approx(0.2)
    assert recall(c) == pytest.approx(0.8)
    assert precision(c) == pytest.approx(0.8)
    assert f1(c) == pytest.approx(0.8)


def test_zero_division_yields_na_not_zero():
    """核心语义：分母为 0 必须是 N/A，不能返回 0。"""
    only_normal = Confusion(tp=0, fp=3, fn=0, tn=7)
    assert recall(only_normal) == NOT_APPLICABLE, '没有正类时召回无定义'
    assert f1(only_normal) == NOT_APPLICABLE, '没有正类时 F1 无定义'
    assert fpr(only_normal) == pytest.approx(0.3)

    only_anomaly = Confusion(tp=3, fp=0, fn=2, tn=0)
    assert fpr(only_anomaly) == NOT_APPLICABLE, '没有负类时 FPR 无定义'
    assert recall(only_anomaly) == pytest.approx(0.6)


# ---------------------------------------------------------------- 会话语义
def test_normal_session_reports_fpr_and_marks_f1_na():
    block = session_block(Confusion(tp=0, fp=0, fn=0, tn=2), 'normal')
    assert block['fpr'] == 0.0
    assert block['metrics_not_applicable'] == ['recall', 'precision', 'f1']
    assert 'f1' not in block, '正常会话不应输出 F1 字段'


def test_normal_session_with_full_false_positives():
    block = session_block(Confusion(tp=0, fp=2, fn=0, tn=0), 'normal')
    assert block['fpr'] == 1.0
    assert block['false_positive_window_rate'] == 1.0


def test_anomaly_session_reports_recall_and_marks_fpr_na():
    block = session_block(Confusion(tp=2, fp=0, fn=0, tn=0), 'anomaly')
    assert block['recall'] == 1.0
    assert 'fpr' not in block
    assert block['metrics_not_applicable'] == ['fpr', 'false_positive_window_rate']


def test_anomaly_session_all_missed():
    """全漏：recall=0 表达失败；没有正类预测时 precision/F1 是 0/0，不编造。"""
    block = session_block(Confusion(tp=0, fp=0, fn=2, tn=0), 'anomaly')
    assert block['recall'] == 0.0
    assert block['precision'] == NOT_APPLICABLE
    assert block['f1'] == NOT_APPLICABLE


def test_anomaly_session_wrong_predictions_have_defined_f1():
    """预测了正类但全错：precision=0 有定义，F1=0。"""
    block = session_block(Confusion(tp=0, fp=2, fn=2, tn=0), 'anomaly')
    assert block['recall'] == 0.0
    assert block['precision'] == 0.0
    assert block['f1'] == 0.0


def test_unknown_label_gets_no_metrics():
    block = session_block(Confusion(tp=1, fp=1, fn=1, tn=1), 'weird')
    assert block['metrics_applicable'] == []
    assert 'fpr' not in block and 'recall' not in block


# ---------------------------------------------------------------- 汇总语义
def _normal(label, fp, tn):
    return session_block(Confusion(tp=0, fp=fp, fn=0, tn=tn), 'normal') | {'scenario': 'normal-rate'}


def _anomaly(label, tp, fn, scenario):
    block = session_block(Confusion(tp=tp, fp=0, fn=fn, tn=0), 'anomaly')
    block['scenario'] = scenario
    return block


def test_overall_fpr_is_pooled_not_mean_of_ratios():
    """总体 FPR 必须合并分子分母，不能对各会话 FPR 取算术平均。"""
    blocks = [
        _normal('normal', 10, 90),   # FPR 0.10, 100 窗口
        _normal('normal', 1, 9),     # FPR 0.10, 10 窗口
    ]
    agg = aggregate(blocks)
    assert agg['overall_fpr_pooled'] == pytest.approx(11 / 110)
    assert agg['overall_fpr_pooled_denominator'] == 110


def test_pooled_fpr_differs_from_mean_when_sizes_differ():
    """构造一个"平均"与"汇总"明显不同的例子，证明两者不可互换。"""
    blocks = [
        _normal('normal', 0, 100),   # FPR 0.00, 100 窗口
        _normal('normal', 1, 1),     # FPR 0.50, 2 窗口
    ]
    agg = aggregate(blocks)
    assert agg['overall_fpr_pooled'] == pytest.approx(1 / 102)
    assert agg['mean_session_fpr'] == pytest.approx(0.25)
    assert agg['worst_session_fpr'] == pytest.approx(0.5)


def test_worst_and_overall_fpr_reported_separately():
    blocks = [
        _normal('normal', 0, 50),
        _normal('normal', 2, 0),     # 该会话全线误报
    ]
    agg = aggregate(blocks)
    assert agg['overall_fpr_pooled'] == pytest.approx(2 / 52)
    assert agg['worst_session_fpr'] == 1.0
    assert agg['overall_fpr_pooled'] != agg['worst_session_fpr']


def test_per_class_recall_pooled_and_session_counts():
    blocks = [
        _anomaly('anomaly', 2, 0, 'anomaly-flood'),
        _anomaly('anomaly', 0, 2, 'anomaly-flood'),
        _anomaly('anomaly', 2, 0, 'anomaly-churn'),
        _anomaly('anomaly', 0, 2, 'anomaly-endpoint-recon'),
    ]
    agg = aggregate(blocks)
    flood = agg['per_class']['anomaly-flood']
    assert flood['recall'] == pytest.approx(0.5), '合并分子分母：2/(2+2)'
    assert flood['sessions'] == 2
    assert flood['sessions_detected'] == 1
    assert agg['per_class']['anomaly-churn']['recall'] == 1.0
    assert agg['per_class']['anomaly-endpoint-recon']['recall'] == 0.0
    assert agg['worst_class_recall'] == 0.0


def test_aggregate_without_anomalies_is_na():
    agg = aggregate([_normal('normal', 0, 10)])
    assert agg['worst_class_recall'] == NOT_APPLICABLE
    assert agg['anomaly_sessions'] == 0


def test_aggregate_without_normals_is_na():
    agg = aggregate([_anomaly('anomaly', 1, 0, 'x')])
    assert agg['overall_fpr_pooled'] == NOT_APPLICABLE
    assert agg['worst_session_fpr'] == NOT_APPLICABLE


def test_worst_session_metric_never_uses_f1():
    """回归：第五轮把 min(F1) 当最差会话；正确实现里正常会话根本不产出 F1。"""
    blocks = [_normal('normal', 0, 5), _normal('normal', 5, 0),
              _anomaly('anomaly', 1, 0, 'a')]
    agg = aggregate(blocks)
    for block in blocks:
        if block['label'] == 'normal':
            assert 'f1' not in block
    assert agg['worst_session_fpr'] == 1.0
    # 异常侧单独汇总，不被正常会话污染
    assert agg['per_class']['a']['recall'] == 1.0
