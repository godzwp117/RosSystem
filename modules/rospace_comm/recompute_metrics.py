#!/usr/bin/env python3
"""从既有混淆矩阵重算派生指标（不重训、不改混淆矩阵）。

用途
----
`macro_recall` 是 TP/FP/TN/FN 的**纯函数**。原实现定义写错，导致记录值不可用。
本脚本按正确公式重算派生指标并就地更新 `metrics.json`，同时：

* **不动** `confusion_matrix` —— 它来自真实推理，重算不改变它；
* 保留旧值到 `metrics_legacy`，便于审计"修复前 vs 修复后"；
* 写入 `metrics_recomputed` 标记与公式定义。

用法：
    .research-venv/bin/python modules/rospace_comm/recompute_metrics.py \
        --run-dir training_runs/rospace_reduced_v2
"""

from __future__ import annotations

import argparse
import json
import os
import sys


def derive(tp: int, fp: int, tn: int, fn: int) -> dict:
    """按正确公式计算全部派生指标。"""
    recall_attack = tp / (tp + fn) if (tp + fn) else 0.0
    recall_normal = tn / (tn + fp) if (tn + fp) else 0.0
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    f1 = (2 * precision * recall_attack / (precision + recall_attack)
          if (precision + recall_attack) else 0.0)
    total = tp + fp + tn + fn
    return {
        'accuracy': (tp + tn) / total if total else 0.0,
        'precision': precision,
        'recall': recall_attack,
        'f1': f1,
        'false_positive_rate': fp / (fp + tn) if (fp + tn) else 0.0,
        'balanced_accuracy': (recall_attack + recall_normal) / 2.0,
        'sensitivity_recall_attack': recall_attack,
        'specificity_recall_normal': recall_normal,
        'macro_recall': (recall_attack + recall_normal) / 2.0,
        'macro_recall_definition': '(Recall_attack + Recall_normal) / 2',
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='重算派生指标')
    parser.add_argument('--run-dir', required=True)
    args = parser.parse_args(argv)

    path = os.path.join(args.run_dir, 'metrics.json')
    with open(path, encoding='utf-8') as handle:
        m = json.load(handle)
    cm = m['confusion_matrix']
    new = derive(cm['tp'], cm['fp'], cm['tn'], cm['fn'])

    # 保留旧值供审计
    m.setdefault('metrics_legacy', {})
    for key in ('macro_recall',):
        if key in m['metrics'] and m['metrics'][key] != new.get(key):
            m['metrics_legacy'][key] = m['metrics'][key]
    m['metrics'].update({k: v for k, v in new.items()})

    # 攻击类别平均检测召回（跨攻击类型，与二分类 Macro Recall 不同）
    per = m.get('per_class_detection_recall') or m.get('per_class_recall') or {}
    attacks = [v for k, v in per.items()
               if v.get('is_attack') and v.get('support')]
    m['metrics']['macro_attack_detection_recall'] = (
        sum(v['detection_recall'] if 'detection_recall' in v else v['recall']
            for v in attacks) / len(attacks)) if attacks else None
    m['metrics']['macro_attack_detection_scope'] = sorted(
        k for k, v in per.items() if v.get('is_attack') and v.get('support'))
    m['metrics']['attack_classes_not_evaluated'] = sorted(
        k for k, v in per.items() if v.get('is_attack') and not v.get('support'))

    m['metrics_recomputed'] = {
        'reason': ('原 macro_recall 定义错误：对 observe 类使用了"被判为攻击的比例"'
                   '（即误报率）而非召回率，得到既非二分类 Macro Recall、'
                   '也非攻击类别平均的值。'),
        'confusion_matrix_unchanged': True,
        'formula': '(Recall_attack + Recall_normal)/2 == Balanced Accuracy',
    }
    assert abs(m['metrics']['macro_recall'] - m['metrics']['balanced_accuracy']) < 1e-12

    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(m, handle, ensure_ascii=False, indent=2)
    print('  {0}: macro_recall {1} -> {2:.4f}（= Balanced Accuracy {3:.4f}）'.format(
        os.path.basename(args.run_dir.rstrip('/')),
        m['metrics_legacy'].get('macro_recall', 'n/a'), m['metrics']['macro_recall'],
        m['metrics']['balanced_accuracy']))
    print('    macro_attack_detection_recall = {0}（范围 {1}）'.format(
        m['metrics']['macro_attack_detection_recall'],
        m['metrics']['macro_attack_detection_scope']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
