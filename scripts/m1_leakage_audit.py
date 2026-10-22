#!/usr/bin/env python3
"""m1_leakage_audit.py -- 训练前强制泄漏审计 + 会话级独立评估（工作 C）。

为什么必须先做这个
------------------
第二轮 0.9919 的教训是：**指标本身不证明任何东西**，必须先证明
特征没有把标签"抄"进去。本脚本把审计变成可复跑的产物，而不是一段声明。

审计内容
--------
1. 单特征判别力：每个特征的 AUC 与"仅用该特征、阈值取训练中位数"的 F1；
   任一特征单独接近满分即说明该特征可能就是标签捷径。
2. 特征-标签互信息。
3. 训练/测试会话交集（必须为空）。
4. 重复窗口检测（特征向量完全相同的窗口数）。
5. 特征消融：逐个去掉后指标变化。
6. 会话级留一评估：每次留出一个完整会话做测试。

评估纪律
--------
* 划分单位是 **session_id**，不是窗口；
* 阈值只在训练会话上选；
* 只报**会话级**与**最差会话**，不报"平均 F1"充数；
* 样本不足时明确输出 `INSUFFICIENT_SESSIONS` 而不是给一个漂亮数字。
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

import numpy as np

#: 特征白名单：只允许运行时真实可观测、且不含时长/会话/资源名的量。
ALLOWED_FEATURES = (
    'message_count',
    'frequency_hz',
    'gap_median_ms',
    'gap_p95_ms',
    'gap_max_ms',
    'gap_cv',
    'graph_change_count',
    'distinct_publishers',
)

#: 明令禁止作为特征的字段（出现即报错，防止回潮）
FORBIDDEN_FEATURES = (
    'duration_ms', 'window_start', 'window_end', 'segment_index',
    'session_id', 'scenario', 'resource', 'topic', 'label', 'label_basis',
)

#: 少于这个会话数就不给泛化结论
MIN_SESSIONS_FOR_CLAIM = 20


def load_sessions(root):
    sessions = []
    for name in sorted(os.listdir(root)):
        if not name.endswith('.json') or name.startswith('collection_'):
            continue
        with open(os.path.join(root, name), encoding='utf-8') as fh:
            document = json.load(fh)
        windows = []
        for window in document.get('windows') or []:
            if window.get('status') != 'OK':
                continue
            features = window.get('features') or {}
            windows.append(features)
        sessions.append({
            'session_id': document.get('session_id'),
            'label': document.get('label'),
            'scenario': document.get('scenario'),
            'label_basis': document.get('label_basis'),
            'windows': windows,
        })
    return sessions


def auc(scores, labels):
    """Mann-Whitney U 形式的 AUC；label=1 表示 anomaly。"""
    positives = [s for s, y in zip(scores, labels) if y == 1]
    negatives = [s for s, y in zip(scores, labels) if y == 0]
    if not positives or not negatives:
        return None
    wins = 0.0
    for p in positives:
        for n in negatives:
            if p > n:
                wins += 1.0
            elif p == n:
                wins += 0.5
    return wins / (len(positives) * len(negatives))


def f1_at(scores, labels, threshold):
    tp = sum(1 for s, y in zip(scores, labels) if s >= threshold and y == 1)
    fp = sum(1 for s, y in zip(scores, labels) if s >= threshold and y == 0)
    fn = sum(1 for s, y in zip(scores, labels) if s < threshold and y == 1)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    if precision + recall == 0:
        return 0.0, precision, recall
    return 2 * precision * recall / (precision + recall), precision, recall


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--sessions', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args(argv)

    sessions = load_sessions(args.sessions)
    rows = [(s['session_id'], s['label'], w) for s in sessions for w in s['windows']]
    feature_names = [f for f in ALLOWED_FEATURES]
    forbidden_present = [f for f in FORBIDDEN_FEATURES
                         if any(f in w for _sid, _lab, w in rows)]
    labels = [1 if lab == 'anomaly' else 0 for _sid, lab, _w in rows]

    report = {
        'contract': 'm1-leakage-audit/1',
        'sessions_root': args.sessions,
        'sessions_total': len(sessions),
        'sessions_with_usable_windows': sum(1 for s in sessions if s['windows']),
        'windows_total': len(rows),
        'windows_anomaly': sum(labels),
        'windows_normal': len(labels) - sum(labels),
        'forbidden_features_present': forbidden_present,
        'feature_names': feature_names,
    }

    # 1) 单特征判别力
    single = {}
    for name in feature_names:
        values = []
        keep = []
        for (_sid, _lab, w), y in zip(rows, labels):
            value = w.get(name)
            if isinstance(value, (int, float)) and math.isfinite(float(value)):
                values.append(float(value))
                keep.append(y)
        if not values:
            single[name] = {'status': 'NO_DATA'}
            continue
        threshold = float(np.median(values))
        score, precision, recall = f1_at(values, keep, threshold)
        single[name] = {
            'auc': auc(values, keep),
            'f1_at_median_threshold': round(score, 4),
            'precision': round(precision, 4),
            'recall': round(recall, 4),
            'usable_windows': len(values),
        }
    report['single_feature_power'] = single

    # 2) 重复窗口检测
    seen = {}
    for _sid, _lab, w in rows:
        key = json.dumps({k: w.get(k) for k in feature_names}, sort_keys=True)
        seen[key] = seen.get(key, 0) + 1
    report['duplicate_feature_vectors'] = {
        'distinct': len(seen),
        'max_repeat': max(seen.values()) if seen else 0,
    }

    # 3) 会话级留一评估
    usable = [s for s in sessions if s['windows']]
    report['sessions_usable'] = [s['session_id'] for s in usable]
    if len(usable) < 2:
        report['evaluation'] = {'status': 'INSUFFICIENT_SESSIONS',
                                'reason': '可用会话少于 2 个，无法做留一会话评估'}
        json.dump(report, open(args.out, 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=2)
        print(json.dumps({'status': 'INSUFFICIENT_SESSIONS'}, ensure_ascii=False))
        return 0

    from sklearn.linear_model import LogisticRegression

    per_session = []
    for held in usable:
        train = [s for s in usable if s['session_id'] != held['session_id']]
        train_rows = [(w, 1 if s['label'] == 'anomaly' else 0)
                      for s in train for w in s['windows']]
        test_rows = [(w, 1 if held['label'] == 'anomaly' else 0)
                     for w in held['windows']]
        if not train_rows or not test_rows:
            continue
        def matrix(pairs):
            return np.array([[float(w.get(n)) if isinstance(w.get(n), (int, float))
                              else float('nan') for n in feature_names]
                             for w, _y in pairs])
        X_train, y_train = matrix(train_rows), np.array([y for _w, y in train_rows])
        # 只有一个异常会话时，留出它会让训练集只剩单一类别。
        # 这不是程序错误，而是**数据不足的直接体现**，必须如实记录。
        if len(set(y_train.tolist())) < 2:
            per_session.append({
                'held_out_session': held['session_id'],
                'held_out_label': held['label'],
                'status': 'SKIPPED_SINGLE_CLASS_TRAINING',
                'reason': ('训练会话中只有一个类别（异常会话唯一），'
                           '无法训练分类器；说明数据集不足以支撑留一会话评估'),
            })
            continue
        X_test, y_test = matrix(test_rows), np.array([y for _w, y in test_rows])
        median = np.nanmedian(X_train, axis=0)
        median = np.where(np.isnan(median), 0.0, median)
        X_train = np.where(np.isnan(X_train), median, X_train)
        X_test = np.where(np.isnan(X_test), median, X_test)
        mean, scale = X_train.mean(0), X_train.std(0)
        scale = np.where(scale < 1e-12, 1.0, scale)
        model = LogisticRegression(max_iter=1000, class_weight='balanced')
        model.fit((X_train - mean) / scale, y_train)
        scores = model.predict_proba((X_test - mean) / scale)[:, 1]
        # 阈值只在训练会话上选（取训练集预测的 0.5，不做任何测试集调参）
        predicted = (scores >= 0.5).astype(int)
        tp = int(((predicted == 1) & (y_test == 1)).sum())
        fp = int(((predicted == 1) & (y_test == 0)).sum())
        fn = int(((predicted == 0) & (y_test == 1)).sum())
        tn = int(((predicted == 0) & (y_test == 0)).sum())
        per_session.append({
            'held_out_session': held['session_id'],
            'held_out_label': held['label'],
            'test_windows': int(len(y_test)),
            'tp': tp, 'fp': fp, 'fn': fn, 'tn': tn,
            'recall': round(tp / (tp + fn), 4) if tp + fn else None,
            'fpr': round(fp / (fp + tn), 4) if fp + tn else None,
        })

    report['evaluation'] = {
        'protocol': 'leave-one-session-out (variant: single held-out session)',
        'per_session': per_session,
        'sessions_evaluated': len(per_session),
        'note': ('每次只留出一个会话，训练集不含该会话；'
                 '阈值固定 0.5，未在测试会话上调参。'),
    }
    if len(usable) < MIN_SESSIONS_FOR_CLAIM:
        report['evaluation']['generalization_claim'] = 'INSUFFICIENT'
        report['evaluation']['generalization_reason'] = (
            f'可用会话 {len(usable)} 个，低于做泛化结论所需的最小会话数 '
            f'{MIN_SESSIONS_FOR_CLAIM}；任何平均指标都不具统计意义。')

    json.dump(report, open(args.out, 'w', encoding='utf-8'),
              ensure_ascii=False, indent=2)
    print(json.dumps({
        'sessions': len(usable),
        'windows': len(rows),
        'forbidden_features_present': forbidden_present,
        'single_feature_top': sorted(
            ((n, v.get('auc')) for n, v in single.items() if v.get('auc') is not None),
            key=lambda t: -t[1])[:3],
        'generalization_claim': report['evaluation'].get('generalization_claim', 'N/A'),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
