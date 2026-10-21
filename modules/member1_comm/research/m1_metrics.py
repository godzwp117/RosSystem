"""m1_metrics.py -- M1 第六轮评估指标的正确语义（纯函数，可单测）。

为什么重写
==========
第五轮评估器把 **F1 的最小值** 当作"最差会话"，但 F1 只有在存在正类时才有意义：

* 一个**正常**会话没有正类，`TP` 恒为 0 → `F1` 恒为 0。
  于是"最差会话 F1 = 0"其实只是"某个会话是正常的"，与模型好坏无关。
* 一个**异常**会话没有负类时，`FPR` 无定义。

正确做法是按会话类别选用指标：

| 会话类别 | 适用指标 | 不适用 |
| --- | --- | --- |
| normal | FPR、误报窗口率 | recall / F1（无正类） |
| anomaly | recall、precision、F1 | FPR（无负类） |

并且要**分别**报告两个不同的量：

* `overall_fpr`：把所有正常会话的窗口汇总后的误报率；
* `worst_session_fpr`：单个正常会话里最差的那个误报率。

两者语义不同：前者衡量总体噪声，后者衡量"有没有一个场景被全线误报"。
只报其中一个都会误导。

本模块不依赖 sklearn，只做混淆矩阵运算，便于用手工构造的矩阵做单元测试。
"""
from __future__ import annotations

from dataclasses import dataclass, field

#: 指标不适用时的返回值（机器可读，区别于 0 分）
NOT_APPLICABLE = 'N/A'


@dataclass
class Confusion:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0

    @property
    def positives(self):
        return self.tp + self.fn

    @property
    def negatives(self):
        return self.fp + self.tn

    @property
    def total(self):
        return self.tp + self.fp + self.fn + self.tn

    def as_dict(self):
        return {'tp': self.tp, 'fp': self.fp, 'fn': self.fn, 'tn': self.tn}


def fpr(confusion):
    """负类误报率。负类为 0 时无定义 → N/A。"""
    if confusion.negatives == 0:
        return NOT_APPLICABLE
    return confusion.fp / confusion.negatives


def recall(confusion):
    """正类召回。正类为 0 时无定义 → N/A。"""
    if confusion.positives == 0:
        return NOT_APPLICABLE
    return confusion.tp / confusion.positives


def precision(confusion):
    """精确率。

    正类预测数为 0 时是 0/0，**不定义** —— 不把它写成 0，
    因为"没有做出任何正类预测"与"预测了但全错"是两件事。
    此时"全漏"的信息由 `recall == 0` 承载。
    """
    if confusion.tp + confusion.fp == 0:
        return NOT_APPLICABLE
    return confusion.tp / (confusion.tp + confusion.fp)


def f1(confusion):
    p = precision(confusion)
    r = recall(confusion)
    if p == NOT_APPLICABLE or r == NOT_APPLICABLE:
        return NOT_APPLICABLE
    if p + r == 0:
        return 0.0
    return 2 * p * r / (p + r)


def false_positive_window_rate(confusion):
    """误报窗口率：正常窗口里被判为异常的比例，与 FPR 同源但命名更直白。"""
    return fpr(confusion)


def session_block(confusion, label):
    """按会话类别返回**适用**指标；不适用的显式写 N/A。"""
    block = {
        'label': label,
        'confusion': confusion.as_dict(),
        'windows': confusion.total,
        'metrics_applicable': [],
        'metrics_not_applicable': [],
    }
    if label == 'normal':
        value = fpr(confusion)
        block['fpr'] = value
        block['false_positive_window_rate'] = value
        block['metrics_applicable'] = ['fpr', 'false_positive_window_rate']
        block['metrics_not_applicable'] = ['recall', 'precision', 'f1']
        if value == NOT_APPLICABLE:
            block['note'] = '该会话没有负类样本，FPR 无定义'
    elif label == 'anomaly':
        recall_value = recall(confusion)
        block['recall'] = recall_value
        block['precision'] = precision(confusion)
        block['f1'] = f1(confusion)
        block['metrics_applicable'] = ['recall', 'precision', 'f1']
        block['metrics_not_applicable'] = ['fpr', 'false_positive_window_rate']
        if recall_value == NOT_APPLICABLE:
            block['note'] = '该会话没有正类样本，召回无定义'
    else:
        block['note'] = f'未知会话类别 {label!r}；不计算任何指标'
        block['metrics_not_applicable'] = ['fpr', 'recall', 'precision', 'f1']
    return block


def aggregate(session_blocks):
    """汇总：总体 FPR 与最差会话 FPR 必须分开报告。"""
    normal = [b for b in session_blocks if b['label'] == 'normal']
    anomaly = [b for b in session_blocks if b['label'] == 'anomaly']

    # 总体 FPR：先合并分子分母，再相除（不是各会话 FPR 的平均）
    pooled_fp = sum(b['confusion']['fp'] for b in normal)
    pooled_neg = sum(b['confusion']['fp'] + b['confusion']['tn'] for b in normal)
    overall_fpr = pooled_fp / pooled_neg if pooled_neg else NOT_APPLICABLE

    per_session_fpr = [b['fpr'] for b in normal if b.get('fpr') not in (None, NOT_APPLICABLE)]
    worst_fpr = max(per_session_fpr) if per_session_fpr else NOT_APPLICABLE
    mean_fpr = (sum(per_session_fpr) / len(per_session_fpr)
                if per_session_fpr else NOT_APPLICABLE)

    # 异常侧：召回按类别汇总（合并分子分母）
    by_class = {}
    for class_name in sorted({b.get('scenario') for b in anomaly if b.get('scenario')}):
        rows = [b for b in anomaly if b.get('scenario') == class_name]
        tp = sum(b['confusion']['tp'] for b in rows)
        fn = sum(b['confusion']['fn'] for b in rows)
        fp = sum(b['confusion']['fp'] for b in rows)
        by_class[class_name] = {
            'sessions': len(rows),
            'tp': tp, 'fn': fn, 'fp': fp,
            'recall': (tp / (tp + fn)) if (tp + fn) else NOT_APPLICABLE,
            'sessions_detected': sum(1 for b in rows
                                     if b['confusion']['tp'] > 0),
        }

    recalls = [v['recall'] for v in by_class.values()
               if v['recall'] != NOT_APPLICABLE]
    return {
        'normal_sessions': len(normal),
        'anomaly_sessions': len(anomaly),
        'overall_fpr_pooled': overall_fpr,
        'overall_fpr_pooled_denominator': pooled_neg,
        'worst_session_fpr': worst_fpr,
        'mean_session_fpr': mean_fpr,
        'per_class': by_class,
        'worst_class_recall': min(recalls) if recalls else NOT_APPLICABLE,
        'note': ('overall_fpr_pooled 与 worst_session_fpr 是两个不同的量：'
                 '前者衡量总体噪声，后者衡量是否存在被全线误报的场景。'),
    }


@dataclass
class Coverage:
    """观测覆盖质量：一个窗口"有数据"不等于"被可靠观察了 30 秒"。"""
    windows_total: int = 0
    windows_message_ok: int = 0
    windows_graph_valid: int = 0
    windows_graph_degraded: int = 0
    windows_graph_failed: int = 0
    windows_graph_not_run: int = 0
    windows_full: int = 0
    windows_partial: int = 0
    windows_insufficient: int = 0
    uncovered_sec: float = 0.0
    late_ticks: int = 0
    expected_sec: float = 0.0
    notes: list = field(default_factory=list)

    def as_dict(self):
        coverage_ratio = None
        if self.expected_sec > 0:
            coverage_ratio = max(0.0, min(1.0, 1.0 - self.uncovered_sec / self.expected_sec))
        return {
            'windows_total': self.windows_total,
            'windows_message_ok': self.windows_message_ok,
            'windows_graph_valid': self.windows_graph_valid,
            'windows_graph_degraded': self.windows_graph_degraded,
            'windows_graph_failed': self.windows_graph_failed,
            'windows_graph_not_run': self.windows_graph_not_run,
            'windows_overall_full': self.windows_full,
            'windows_overall_partial': self.windows_partial,
            'windows_overall_insufficient': self.windows_insufficient,
            'uncovered_sec': round(self.uncovered_sec, 3),
            'expected_sec': round(self.expected_sec, 3),
            'graph_time_coverage_ratio': (round(coverage_ratio, 4)
                                          if coverage_ratio is not None else None),
            'late_ticks': self.late_ticks,
            'notes': list(self.notes),
        }
