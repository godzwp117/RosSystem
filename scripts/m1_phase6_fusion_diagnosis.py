#!/usr/bin/env python3
"""m1_phase6_fusion_diagnosis.py -- 诊断"为什么图-only 能检出、融合后反而漏检"。

背景事实（第五轮实测）
----------------------
* graph-only：`anomaly-endpoint-recon` 5/5 检出；
* message+graph：同一类别 0/5 检出。

本脚本不改模型、不调参，只做**归因**：
1. 看两类会话在各特征上的实际取值（是否被消息特征的量纲淹没）；
2. 看联合模型里图特征的系数是否被压小；
3. 看标准化前后图特征的相对幅度；
4. 检查"消息通道缺失"在融合时如何被插补（是否把图-only 会话变成正常）。

只输出诊断，不下"已修复"的结论。
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

import numpy as np

MESSAGE_FEATURES = ('message_count', 'frequency_hz', 'gap_median_ms',
                    'gap_p95_ms', 'gap_max_ms', 'gap_cv',
                    'publisher_count_in_window')
GRAPH_FEATURES = ('graph_snapshot_transition_count',)


def load(root):
    sessions = []
    for name in sorted(os.listdir(root)):
        if not name.endswith('.json'):
            continue
        try:
            doc = json.load(open(os.path.join(root, name), encoding='utf-8'))
        except Exception:                                    # noqa: BLE001
            continue
        rows = []
        for w in doc.get('windows') or []:
            if not w.get('window_complete'):
                continue
            msg = w.get('message_observation') or {}
            graph = w.get('graph_observation') or {}
            feats = {}
            feats.update(msg.get('features') or {})
            feats.update(graph.get('features') or {})
            rows.append({'features': feats,
                         'message_status': msg.get('status'),
                         'graph_status': graph.get('status')})
        sessions.append({'session_id': doc.get('session_id'),
                         'scenario': doc.get('scenario'),
                         'label': doc.get('label'),
                         'windows': rows})
    return sessions


def describe(values):
    if not values:
        return {'n': 0}
    arr = np.array(values, dtype=float)
    return {'n': len(arr), 'min': round(float(arr.min()), 4),
            'median': round(float(np.median(arr)), 4),
            'max': round(float(arr.max()), 4),
            'std': round(float(arr.std()), 4)}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--sessions', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args(argv)

    sessions = load(args.sessions)
    report = {'contract': 'm1-fusion-diagnosis/1',
              'sessions_root': args.sessions,
              'sessions': len(sessions)}

    # 1) 各场景的特征取值分布
    by_scenario = {}
    for s in sessions:
        bucket = by_scenario.setdefault(s['scenario'], {'label': s['label'],
                                                        'sessions': 0,
                                                        'features': {}})
        bucket['sessions'] += 1
        for row in s['windows']:
            for name, value in row['features'].items():
                if isinstance(value, (int, float)) and math.isfinite(float(value)):
                    bucket['features'].setdefault(name, []).append(float(value))
    for scenario, bucket in by_scenario.items():
        bucket['feature_stats'] = {name: describe(vals)
                                   for name, vals in bucket['features'].items()}
        bucket.pop('features')
    report['per_scenario_feature_stats'] = by_scenario

    # 2) 消息通道缺失率（图-only 场景的关键）
    missing = {}
    for s in sessions:
        total = len(s['windows'])
        if not total:
            continue
        msg_missing = sum(1 for w in s['windows'] if w['message_status'] != 'OK')
        missing.setdefault(s['scenario'], []).append(msg_missing / total)
    report['message_channel_missing_ratio'] = {
        k: round(float(np.mean(v)), 4) for k, v in missing.items()}

    # 3) 联合模型里图特征的系数与标准化幅度
    rows, labels = [], []
    for s in sessions:
        for w in s['windows']:
            if not w['features']:
                continue
            rows.append(w['features'])
            labels.append(1 if s['label'] == 'anomaly' else 0)
    if len(set(labels)) >= 2 and rows:
        from sklearn.linear_model import LogisticRegression
        features = list(MESSAGE_FEATURES) + list(GRAPH_FEATURES)
        X = np.array([[float(r.get(n)) if isinstance(r.get(n), (int, float))
                       else float('nan') for n in features] for r in rows])
        median = np.nanmedian(X, axis=0)
        median = np.where(np.isnan(median), 0.0, median)
        X = np.where(np.isnan(X), median, X)
        mean, scale = X.mean(0), X.std(0)
        scale = np.where(scale < 1e-12, 1.0, scale)
        Z = (X - mean) / scale
        model = LogisticRegression(max_iter=2000, class_weight='balanced')
        model.fit(Z, np.array(labels))
        report['joint_model'] = {
            'feature_scales': {n: round(float(s), 6)
                               for n, s in zip(features, scale)},
            'standardised_abs_mean': {n: round(float(np.abs(Z[:, i]).mean()), 4)
                                      for i, n in enumerate(features)},
            'coefficients': {n: round(float(c), 6)
                             for n, c in zip(features, model.coef_[0])},
            'intercept': round(float(model.intercept_[0]), 6),
            'note': ('系数与标准化幅度共同决定实际影响力：'
                     '|coef| × 该特征的典型 |z| 才是它对 logit 的贡献量级。'),
        }
        graph_index = features.index('graph_snapshot_transition_count')
        graph_contribution = abs(model.coef_[0][graph_index]) * float(
            np.abs(Z[:, graph_index]).mean())
        message_contributions = {
            n: abs(model.coef_[0][i]) * float(np.abs(Z[:, i]).mean())
            for i, n in enumerate(features) if n != 'graph_snapshot_transition_count'}
        report['joint_model']['graph_contribution'] = round(graph_contribution, 4)
        report['joint_model']['max_message_contribution'] = round(
            max(message_contributions.values()), 4)
        report['joint_model']['dominance_ratio'] = (
            round(max(message_contributions.values()) / graph_contribution, 2)
            if graph_contribution else None)

    json.dump(report, open(args.out, 'w', encoding='utf-8'),
              ensure_ascii=False, indent=2)
    print(json.dumps({
        'scenarios': list(by_scenario),
        'message_missing_ratio': report['message_channel_missing_ratio'],
        'joint_model': {k: report.get('joint_model', {}).get(k) for k in
                        ('graph_contribution', 'max_message_contribution',
                         'dominance_ratio')},
        'out': args.out}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
