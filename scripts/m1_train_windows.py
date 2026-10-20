#!/usr/bin/env python3
"""m1_train_windows.py -- M1 窗口级在线检测模型训练与诚实评估（专项② P1）。

为什么改到"窗口级"
------------------
`scripts/m1_data_audit.py` 已证明：ROSPaCe_reduced 的 15 个分片是**按采集会话**
组织的，且每个分片被某一类攻击主导（例如 7–9 号几乎全是 metasploit SYN flood，
1–2 号几乎全是正常流量）。因此原先的"按文件划分训练/测试"实际上等价于
"按攻击类别划分"，测出来的不是检测能力，而是跨类别迁移能力——这正是
49 维模型测试 F1 只有 0.1312、却低于"恒预测攻击"基线 0.8567 的原因。

本脚本改用**窗口级特征**，它同时满足两个要求：

1. **可在运行时真实观测**：request_count / frequency_hz / gap 统计 / 窗口时长
   都可以从 ROS 2 侧的发布与 Action 事件算出，不依赖 tshark 的内核级字段；
2. **可以按会话分组评估**：窗口数据带 `segment_index`，据此做
   GroupKFold，训练集与验证集不共享采集会话，避免时间自相关导致的虚高。

评估纪律（本脚本的硬性要求）
--------------------------
* 阈值只能在**训练折**上选，不得用验证折调阈值；
* 每次都同时报告"恒预测攻击"与"恒预测正常"两个平凡基线，
  任何候选模型必须**超过平凡基线**才算有效；
* 逐类别召回必须分开报，不能只报总体准确率；
* 所有折的结果都保留，不做"只留最好一次"的挑选；
* 特征缺失用训练折中位数插补，不得用全量数据的中位数（那会泄漏）。

用法
----
    python3 scripts/m1_train_windows.py \
        --windows /home/zhangwei/project/RosSystem/data/ROSPaCe_reduced/windows_0.jsonl \
        --out artifacts/research/m1/<run_id>/model
"""
from __future__ import annotations

import argparse
import json
import os
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_WINDOWS = ('/home/zhangwei/project/RosSystem/data/ROSPaCe_reduced/'
                   'windows_0.jsonl')

#: 攻击标签集合。`observe` 是正常基线，其余都视为攻击。
NORMAL_LABEL = 'observe'

#: 窗口级数值特征——这些量在运行时都能从 ROS 2 事件流算出。
NUMERIC = ('request_count', 'frequency_hz', 'gap_median_ms', 'gap_p95_ms',
           'gap_max_ms', 'duration_ms')


def now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def load_windows(path):
    rows = []
    with open(path, encoding='utf-8') as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            comm = d.get('communication') or {}
            window = d.get('window') or {}
            rows.append({
                'segment': d.get('segment_index'),
                'block': d.get('block_index'),
                'label': d.get('source_label'),
                'resource': comm.get('resource'),
                'operation': comm.get('operation'),
                'request_count': d.get('request_count'),
                'frequency_hz': d.get('frequency_hz'),
                'gap_median_ms': d.get('gap_median_ms'),
                'gap_p95_ms': d.get('gap_p95_ms'),
                'gap_max_ms': d.get('gap_max_ms'),
                'duration_ms': window.get('duration_ms'),
            })
    return rows


def to_features(rows, resource_vocab):
    """把窗口记录转成数值矩阵。资源名用训练折的固定词表做 one-hot（未知资源-> other）。"""
    import numpy as np
    matrix = np.zeros((len(rows), len(NUMERIC) + len(resource_vocab) + 1),
                      dtype=np.float64)
    for i, row in enumerate(rows):
        for j, name in enumerate(NUMERIC):
            value = row.get(name)
            matrix[i, j] = float(value) if isinstance(value, (int, float)) and \
                math.isfinite(float(value)) else float('nan')
        resource = row.get('resource')
        if resource in resource_vocab:
            matrix[i, len(NUMERIC) + resource_vocab.index(resource)] = 1.0
        else:
            matrix[i, len(NUMERIC) + len(resource_vocab)] = 1.0
    return matrix


def constant_f1(positive, total):
    if total <= 0:
        return 0.0
    p = positive / total
    return (2 * p / (1 + p)) if p > 0 else 0.0


def binary_metrics(y_true, y_pred):
    tp = sum(1 for t, p in zip(y_true, y_pred) if t == 1 and p == 1)
    fp = sum(1 for t, p in zip(y_true, y_pred) if t == 0 and p == 1)
    fn = sum(1 for t, p in zip(y_true, y_pred) if t == 1 and p == 0)
    tn = sum(1 for t, p in zip(y_true, y_pred) if t == 0 and p == 0)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    specificity = tn / (tn + fp) if (tn + fp) else 0.0
    return {'tp': tp, 'fp': fp, 'fn': fn, 'tn': tn, 'precision': round(precision, 4),
            'recall': round(recall, 4), 'f1': round(f1, 4),
            'specificity': round(specificity, 4)}


def per_class_recall(rows, y_pred):
    stats = defaultdict(lambda: [0, 0])
    for row, pred in zip(rows, y_pred):
        label = row['label']
        is_attack = 0 if label == NORMAL_LABEL else 1
        stats[label][1] += 1
        if pred == is_attack and is_attack == 1:
            stats[label][0] += 1
        elif label == NORMAL_LABEL and pred == 0:
            stats[label][0] += 1
    return {label: {'detected': d, 'total': t,
                    'rate': round(d / t, 4) if t else None}
            for label, (d, t) in sorted(stats.items())}


def build_candidates():
    """候选模型。故意包含弱基线与强模型，且**全部**参与评估，不做事后挑选。"""
    from sklearn.ensemble import ExtraTreesClassifier, RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    candidates = {
        'logistic': Pipeline([('scale', StandardScaler()),
                              ('clf', LogisticRegression(max_iter=2000,
                                                         class_weight='balanced'))]),
        'random_forest': RandomForestClassifier(n_estimators=200, max_depth=12,
                                               class_weight='balanced',
                                               random_state=0, n_jobs=-1),
        'extra_trees': ExtraTreesClassifier(n_estimators=200, max_depth=12,
                                            class_weight='balanced',
                                            random_state=0, n_jobs=-1),
    }
    try:
        from sklearn.ensemble import HistGradientBoostingClassifier
        candidates['hist_gb'] = HistGradientBoostingClassifier(
            max_iter=200, max_depth=6, learning_rate=0.1, random_state=0)
    except Exception:
        pass
    return candidates


def rule_baseline(rows_train, rows_test):
    """纯规则基线：窗口频率高于训练折"正常"频率的 99 分位即判攻击。

    这条基线存在的意义是回答一个问题：**复杂模型是否真的比一条阈值规则更强？**
    如果打不过它，就没有理由上线复杂模型。
    """
    import numpy as np
    normal = [r['frequency_hz'] for r in rows_train
              if r['label'] == NORMAL_LABEL and isinstance(r.get('frequency_hz'), (int, float))]
    if not normal:
        return None, None
    threshold = float(np.percentile(normal, 99))
    predictions = [1 if (r.get('frequency_hz') or 0.0) > threshold else 0
                   for r in rows_test]
    return predictions, {'threshold_frequency_hz': round(threshold, 4),
                         'fitted_on': 'train-fold normal windows only'}


def main(argv=None):
    parser = argparse.ArgumentParser(description='M1 窗口级检测模型训练')
    parser.add_argument('--windows', default=DEFAULT_WINDOWS)
    parser.add_argument('--out', required=True)
    parser.add_argument('--folds', type=int, default=5)
    parser.add_argument('--top-resources', type=int, default=12)
    args = parser.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)

    import numpy as np
    from sklearn.model_selection import GroupKFold

    rows = load_windows(args.windows)
    labels = Counter(r['label'] for r in rows)
    segments = sorted({r['segment'] for r in rows})

    report = {
        'generated_at': now(),
        'script': os.path.relpath(os.path.abspath(__file__), REPO),
        'input': {'windows': args.windows,
                  'rows': len(rows),
                  'labels': dict(labels),
                  'segments': segments},
        'design': {
            'grouping': 'GroupKFold by segment_index (采集会话)',
            'threshold_selection': '仅用训练折，验证折不参与阈值选择',
            'binary_definition': f'攻击 = 非 {NORMAL_LABEL!r}',
            'features': list(NUMERIC) + ['resource one-hot (top-k) + other'],
        },
        'folds': [],
        'candidates': {},
        'notes': [],
    }
    if len(segments) < args.folds:
        report['notes'].append(
            f'会话数 {len(segments)} 少于折数 {args.folds}，折数自动降为 {len(segments)}')
        args.folds = max(2, len(segments))

    y_all = np.array([0 if r['label'] == NORMAL_LABEL else 1 for r in rows])
    groups = np.array([r['segment'] for r in rows])

    per_candidate_scores = defaultdict(list)
    splitter = GroupKFold(n_splits=args.folds)
    fold_index = 0
    for train_idx, test_idx in splitter.split(np.zeros(len(rows)), y_all, groups):
        fold_index += 1
        train_rows = [rows[i] for i in train_idx]
        test_rows = [rows[i] for i in test_idx]
        # 词表只用训练折，避免泄漏
        counts = Counter(r['resource'] for r in train_rows)
        vocab = [name for name, _ in counts.most_common(args.top_resources)]
        x_train = to_features(train_rows, vocab)
        x_test = to_features(test_rows, vocab)
        y_train = np.array([0 if r['label'] == NORMAL_LABEL else 1 for r in train_rows])
        y_test = np.array([0 if r['label'] == NORMAL_LABEL else 1 for r in test_rows])

        # 训练折中位数插补（不得用全量）
        medians = np.nanmedian(np.where(np.isnan(x_train), np.nan, x_train), axis=0)
        medians = np.where(np.isnan(medians), 0.0, medians)
        def impute(matrix):
            out = matrix.copy()
            for j in range(out.shape[1]):
                column = out[:, j]
                missing = np.isnan(column)
                if missing.any():
                    column[missing] = medians[j]
            return out
        x_train_i, x_test_i = impute(x_train), impute(x_test)

        fold = {
            'fold': fold_index,
            'train_rows': len(train_rows), 'test_rows': len(test_rows),
            'train_segments': sorted({r['segment'] for r in train_rows}),
            'test_segments': sorted({r['segment'] for r in test_rows}),
            'train_labels': dict(Counter(r['label'] for r in train_rows)),
            'test_labels': dict(Counter(r['label'] for r in test_rows)),
            'test_attack_ratio': round(float(y_test.mean()), 4) if len(y_test) else None,
            'baseline_constant_attack': constant_f1(int(y_test.sum()), len(y_test)),
            'baseline_constant_normal': constant_f1(int((1 - y_test).sum()), len(y_test)),
            'candidates': {},
        }

        # 平凡基线也作为"候选"参与对比，体现最低线
        fold['candidates']['constant_attack'] = {
            'metrics': binary_metrics(list(y_test), [1] * len(y_test))}
        fold['candidates']['constant_normal'] = {
            'metrics': binary_metrics(list(y_test), [0] * len(y_test))}

        preds, info = rule_baseline(train_rows, test_rows)
        if preds is not None:
            fold['candidates']['rule_frequency_99pct'] = {
                'metrics': binary_metrics(list(y_test), preds), 'params': info}
            per_candidate_scores['rule_frequency_99pct'].append(
                fold['candidates']['rule_frequency_99pct']['metrics']['f1'])

        for name, model in build_candidates().items():
            try:
                model.fit(x_train_i, y_train)
                # 阈值只在训练折上选：取训练折 F1 最优的概率阈值
                train_prob = model.predict_proba(x_train_i)[:, 1]
                best_threshold, best_f1 = 0.5, -1.0
                for threshold in (0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9):
                    pred_train = (train_prob >= threshold).astype(int)
                    f1 = binary_metrics(list(y_train), list(pred_train))['f1']
                    if f1 > best_f1:
                        best_threshold, best_f1 = threshold, f1
                prob = model.predict_proba(x_test_i)[:, 1]
                pred = (prob >= best_threshold).astype(int)
                metrics = binary_metrics(list(y_test), list(pred))
                metrics['threshold'] = best_threshold
                metrics['train_f1_at_threshold'] = round(best_f1, 4)
                fold['candidates'][name] = {'metrics': metrics}
                per_candidate_scores[name].append(metrics['f1'])
            except Exception as exc:                            # noqa: BLE001
                fold['candidates'][name] = {'error': str(exc)[:200]}

        # 逐类别召回（用最优的树模型给出，便于定位失效类别）
        if 'extra_trees' in fold['candidates'] and 'error' not in fold['candidates']['extra_trees']:
            model = build_candidates()['extra_trees']
            model.fit(x_train_i, y_train)
            threshold = fold['candidates']['extra_trees']['metrics'].get('threshold', 0.5)
            pred = (model.predict_proba(x_test_i)[:, 1] >= threshold).astype(int)
            fold['per_class'] = per_class_recall(test_rows, list(pred))

        report['folds'].append(fold)

    # 汇总：均值与最差折，避免只看平均
    for name, scores in per_candidate_scores.items():
        report['candidates'][name] = {
            'folds': len(scores),
            'mean_f1': round(float(np.mean(scores)), 4),
            'worst_f1': round(float(np.min(scores)), 4),
            'best_f1': round(float(np.max(scores)), 4),
        }
    baseline_mean = float(np.mean([f['baseline_constant_attack'] for f in report['folds']]))
    report['baselines'] = {
        'constant_attack_mean_f1': round(baseline_mean, 4),
        'note': ('任何候选的平均 F1 若不超过该值，就没有证据表明它优于'
                 '"一律报警"这条零成本策略。'),
    }
    winners = {name: v for name, v in report['candidates'].items()
               if v['mean_f1'] > baseline_mean}
    report['verdict'] = {
        'candidates_beating_constant_attack': sorted(winners),
        'any_candidate_effective': bool(winners),
    }
    if not winners:
        report['notes'].append(
            '没有任何候选在会话分组评估下超过"恒预测攻击"基线：'
            '这支持"当前特征体系不足以构成有效在线检测"的结论，'
            '而不是继续用旧文件划分刷分。')

    with open(os.path.join(args.out, 'training_report.json'), 'w',
              encoding='utf-8') as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)

    lines = ['# M1 窗口级模型评估（会话分组）', '',
             f'- 生成时间：{report["generated_at"]}',
             f'- 输入窗口数：{len(rows)}',
             f'- 会话（segment）数：{len(segments)}',
             f'- 折数：{args.folds}（GroupKFold by segment）', '',
             '## 类别分布', '', '| 标签 | 窗口数 |', '| --- | --- |']
    for label, count in labels.most_common():
        lines.append(f'| {label} | {count} |')
    lines += ['', '## 候选对比（每折都超过基线才算强）', '',
              '| 候选 | 平均 F1 | 最差折 F1 | 最好折 F1 |', '| --- | --- | --- | --- |']
    for name, v in sorted(report['candidates'].items(),
                          key=lambda kv: -kv[1]['mean_f1']):
        lines.append(f'| `{name}` | {v["mean_f1"]} | {v["worst_f1"]} | {v["best_f1"]} |')
    lines += ['', f'**恒预测攻击基线平均 F1 = {report["baselines"]["constant_attack_mean_f1"]}**',
              '', f'超过基线的候选：{report["verdict"]["candidates_beating_constant_attack"] or "（无）"}']
    if report['notes']:
        lines += ['', '## 说明'] + [f'- {n}' for n in report['notes']]
    with open(os.path.join(args.out, 'training_report.md'), 'w',
              encoding='utf-8') as fh:
        fh.write('\n'.join(lines) + '\n')

    print(json.dumps({'out': args.out,
                      'candidates': report['candidates'],
                      'baseline': report['baselines'],
                      'verdict': report['verdict']}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
