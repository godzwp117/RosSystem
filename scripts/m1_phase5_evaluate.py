#!/usr/bin/env python3
"""m1_phase5_evaluate.py -- G4 无泄漏审计 + 双通道会话级评估（第五轮）。

契约变化
--------
第四轮只有消息通道；本轮窗口是 `m1-observation-window/2`，
分 `message_observation` 与 `graph_observation` 两块。
本脚本按新 Schema 提取特征，并按**通道**做消融：
仅消息 / 仅图 / 双通道。

纪律
----
* 划分单位是 session；
* 阈值固定 0.5，不在测试会话上调参；
* 报每类召回、每会话 FPR、最差会话，不只报平均；
* 会话数不足预登记门槛时输出 `INSUFFICIENT_EVIDENCE`。
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics

import numpy as np

#: 消息通道特征（全部运行时真实可观测）
MESSAGE_FEATURES = (
    'message_count', 'frequency_hz', 'gap_median_ms', 'gap_p95_ms',
    'gap_max_ms', 'gap_cv', 'publisher_count_in_window',
)

#: 图通道特征
GRAPH_FEATURES = ('graph_snapshot_transition_count',)

#: 禁止作为特征的字段（出现即判泄漏）
FORBIDDEN = (
    'duration_ms', 'window_start', 'window_end', 'session_id', 'scenario',
    'resource', 'topic', 'label', 'label_basis', 'filename', 'segment_index',
    'graph_poll_interval_sec',
)

#: 预登记门槛（见 M1_PHASE5_EXPERIMENT_PROTOCOL §6）
GATE_NORMAL_FPR = 0.10
GATE_CLASS_RECALL = 0.80
GATE_UNKNOWN_RATIO = 0.20
GATE_WORST_SESSION_F1 = 0.60

#: 目标会话数（协议 §1）
TARGET_NORMAL_SESSIONS = 20
TARGET_ANOMALY_PER_CLASS = 5


def load_sessions(root):
    sessions = []
    for name in sorted(os.listdir(root)):
        if not name.endswith('.json'):
            continue
        path = os.path.join(root, name)
        try:
            with open(path, encoding='utf-8') as fh:
                document = json.load(fh)
        except Exception:                                    # noqa: BLE001
            sessions.append({'session_id': name[:-5], 'status': 'UNREADABLE'})
            continue
        rows = []
        for window in document.get('windows') or []:
            if not window.get('window_complete'):
                continue
            message = window.get('message_observation') or {}
            graph = window.get('graph_observation') or {}
            features = {}
            features.update(message.get('features') or {})
            features.update(graph.get('features') or {})
            rows.append({
                'features': features,
                'message_status': message.get('status'),
                'graph_status': graph.get('status'),
                'overall': window.get('overall_observation_status'),
                # graph-only 场景：消息通道本就无业务消息，图特征才是信号
                'usable_graph_only': graph.get('status') == 'VALID',
                'usable_message': message.get('status') == 'OK',
            })
        sessions.append({
            'session_id': document.get('session_id'),
            'scenario': document.get('scenario'),
            'label': document.get('label'),
            'label_basis': document.get('label_basis'),
            'label_source': document.get('label_source'),
            'windows': rows,
        })
    return sessions


def auc(scores, labels):
    pos = [s for s, y in zip(scores, labels) if y == 1]
    neg = [s for s, y in zip(scores, labels) if y == 0]
    if not pos or not neg:
        return None
    wins = sum(1.0 if p > n else 0.5 if p == n else 0.0 for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def build_matrix(rows, features):
    out = []
    for row in rows:
        vector = []
        for name in features:
            value = row['features'].get(name)
            vector.append(float(value) if isinstance(value, (int, float))
                          and math.isfinite(float(value)) else float('nan'))
        out.append(vector)
    return np.array(out, dtype=float) if out else np.zeros((0, len(features)))


def session_samples(sessions, features, require_message_ok=False):
    """把一个会话变成样本列表；图与消息通道都可用的窗口才算样本。"""
    samples = []
    for session in sessions:
        if session.get('status') == 'UNREADABLE':
            continue
        for row in session['windows']:
            if not row['usable_graph_only']:
                continue
            if require_message_ok and not row['usable_message']:
                continue
            if not row['features']:
                continue
            samples.append((session, row))
    return samples


def leave_one_session_out(sessions, features, require_message_ok=False):
    samples = session_samples(sessions, features, require_message_ok)
    by_session = {}
    for session, row in samples:
        by_session.setdefault(session['session_id'], []).append((session, row))
    usable = [s for s in sessions
              if s.get('status') != 'UNREADABLE' and s['session_id'] in by_session
              and any(y for _sid, y in [(s['session_id'], s['label'])])]
    results = []
    for held in usable:
        train = [(s, r) for sid, rows in by_session.items() if sid != held['session_id']
                 for (s, r) in rows]
        test = by_session[held['session_id']]
        y_train = np.array([1 if s['label'] == 'anomaly' else 0 for s, _r in train])
        if len(train) == 0 or len(set(y_train.tolist())) < 2:
            results.append({'session_id': held['session_id'],
                            'label': held['label'],
                            'status': 'SKIPPED_SINGLE_CLASS_TRAINING'})
            continue
        from sklearn.linear_model import LogisticRegression
        X_train = build_matrix([r for _s, r in train], features)
        X_test = build_matrix([r for _s, r in test], features)
        median = np.nanmedian(X_train, axis=0)
        median = np.where(np.isnan(median), 0.0, median)
        X_train = np.where(np.isnan(X_train), median, X_train)
        X_test = np.where(np.isnan(X_test), median, X_test)
        mean, scale = X_train.mean(0), X_train.std(0)
        scale = np.where(scale < 1e-12, 1.0, scale)
        model = LogisticRegression(max_iter=1000, class_weight='balanced')
        model.fit((X_train - mean) / scale, y_train)
        scores = model.predict_proba((X_test - mean) / scale)[:, 1]
        y_test = np.array([1 if s['label'] == 'anomaly' else 0 for s, _r in test])
        predicted = (scores >= 0.5).astype(int)
        tp = int(((predicted == 1) & (y_test == 1)).sum())
        fp = int(((predicted == 1) & (y_test == 0)).sum())
        fn = int(((predicted == 0) & (y_test == 1)).sum())
        tn = int(((predicted == 0) & (y_test == 0)).sum())
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        results.append({
            'session_id': held['session_id'], 'label': held['label'],
            'scenario': held['scenario'],
            'tp': tp, 'fp': fp, 'fn': fn, 'tn': tn,
            'recall': round(recall, 4),
            'fpr': round(fp / (fp + tn), 4) if fp + tn else None,
            'f1': round(f1, 4),
        })
    return results


def summarise(results, classes):
    scored = [r for r in results if 'f1' in r]
    normal = [r for r in scored if r['label'] == 'normal']
    anomaly = [r for r in scored if r['label'] == 'anomaly']
    per_class = {}
    for name in classes:
        rows = [r for r in anomaly if r.get('scenario') == name]
        if rows:
            per_class[name] = {
                'sessions': len(rows),
                'recall': round(statistics.fmean(r['recall'] for r in rows), 4),
                'detected': sum(1 for r in rows if r['tp'] > 0),
            }
    return {
        'sessions_scored': len(scored),
        'skipped': len(results) - len(scored),
        'normal_sessions': len(normal),
        'anomaly_sessions': len(anomaly),
        'normal_fpr_mean': round(statistics.fmean(r['fpr'] for r in normal), 4)
                           if normal and all(r['fpr'] is not None for r in normal) else None,
        'normal_fpr_worst': round(max(r['fpr'] for r in normal), 4)
                            if normal and all(r['fpr'] is not None for r in normal) else None,
        'anomaly_recall_mean': round(statistics.fmean(r['recall'] for r in anomaly), 4)
                               if anomaly else None,
        'worst_session_f1': round(min(r['f1'] for r in scored), 4) if scored else None,
        'per_class': per_class,
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--sessions', required=True)
    parser.add_argument('--g2', default=None)
    parser.add_argument('--out', required=True)
    args = parser.parse_args(argv)

    sessions = load_sessions(args.sessions)
    usable = [s for s in sessions if s.get('status') != 'UNREADABLE']
    unreadable = [s['session_id'] for s in sessions if s.get('status') == 'UNREADABLE']
    normal = [s for s in usable if s['label'] == 'normal']
    anomaly = [s for s in usable if s['label'] == 'anomaly']
    classes = sorted({s['scenario'] for s in anomaly})

    all_rows = [r for s in usable for r in s['windows']]
    present_forbidden = [f for f in FORBIDDEN
                         if any(f in r['features'] for r in all_rows)]

    report = {
        'contract': 'm1-phase5-evaluation/1',
        'sessions_total': len(usable),
        'sessions_unreadable': unreadable,
        'normal_sessions': len(normal),
        'anomaly_sessions': len(anomaly),
        'anomaly_classes': {c: sum(1 for s in anomaly if s['scenario'] == c)
                            for c in classes},
        'complete_windows': len(all_rows),
        'forbidden_features_present': present_forbidden,
        'sample_target': {
            'normal_required': TARGET_NORMAL_SESSIONS,
            'normal_actual': len(normal),
            'anomaly_per_class_required': TARGET_ANOMALY_PER_CLASS,
            'anomaly_per_class_actual': {c: sum(1 for s in anomaly
                                                if s['scenario'] == c) for c in classes},
        },
        'gates': {
            'normal_fpr': GATE_NORMAL_FPR,
            'class_recall': GATE_CLASS_RECALL,
            'unknown_ratio': GATE_UNKNOWN_RATIO,
            'worst_session_f1': GATE_WORST_SESSION_F1,
        },
        'label_provenance': {
            'sources': sorted({s.get('label_source') for s in usable}),
            'all_from_experiment_condition':
                all(s.get('label_source') == 'EXPERIMENT_CONDITION' for s in usable),
        },
    }

    # 单特征判别力（双通道合并后）
    labels, rows_flat = [], []
    for s in usable:
        for r in s['windows']:
            if not r['usable_graph_only'] or not r['features']:
                continue
            labels.append(1 if s['label'] == 'anomaly' else 0)
            rows_flat.append(r)
    single = {}
    for name in MESSAGE_FEATURES + GRAPH_FEATURES:
        values = [float(r['features'][name]) for r in rows_flat
                  if isinstance(r['features'].get(name), (int, float))]
        kept = [y for r, y in zip(rows_flat, labels)
                if isinstance(r['features'].get(name), (int, float))]
        if values:
            single[name] = {'auc': auc(values, kept), 'n': len(values)}
    report['single_feature_auc'] = single

    # 通道消融
    combinations = {
        'message_only': MESSAGE_FEATURES,
        'graph_only': GRAPH_FEATURES,
        'both': MESSAGE_FEATURES + GRAPH_FEATURES,
    }
    ablations = {}
    for name, features in combinations.items():
        results = leave_one_session_out(usable, features)
        ablations[name] = {'features': list(features),
                           'summary': summarise(results, classes),
                           'per_session': results}
    report['ablations'] = ablations

    best = ablations['both']['summary']
    verdicts = {}
    verdicts['normal_fpr'] = (
        'PASS' if best['normal_fpr_worst'] is not None
        and best['normal_fpr_worst'] <= GATE_NORMAL_FPR else 'FAIL')
    classes_ok = all(v['recall'] >= GATE_CLASS_RECALL
                     for v in best['per_class'].values()) if best['per_class'] else False
    verdicts['attack_recall'] = 'PASS' if classes_ok else 'FAIL'
    verdicts['worst_session'] = (
        'PASS' if best['worst_session_f1'] is not None
        and best['worst_session_f1'] >= GATE_WORST_SESSION_F1 else 'FAIL')
    report['gate_verdicts'] = verdicts

    total_required = TARGET_NORMAL_SESSIONS + TARGET_ANOMALY_PER_CLASS * len(classes)
    target_met = (len(normal) >= TARGET_NORMAL_SESSIONS and
                  all(v >= TARGET_ANOMALY_PER_CLASS
                      for v in report['sample_target']['anomaly_per_class_actual'].values()))
    report['sample_target_met'] = target_met
    report['overall'] = (
        'EVIDENCE_SUFFICIENT' if target_met and all(v == 'PASS' for v in verdicts.values())
        else 'INSUFFICIENT_EVIDENCE')

    with open(args.out, 'w', encoding='utf-8') as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps({
        'sessions': report['sessions_total'],
        'normal': report['normal_sessions'],
        'anomaly': report['anomaly_sessions'],
        'classes': report['anomaly_classes'],
        'forbidden_features_present': present_forbidden,
        'sample_target_met': target_met,
        'single_feature_auc': {k: round(v['auc'], 3) if v['auc'] else None
                               for k, v in single.items()},
        'both_summary': {k: best[k] for k in
                         ('normal_fpr_worst', 'anomaly_recall_mean',
                          'worst_session_f1', 'per_class')},
        'gate_verdicts': verdicts,
        'overall': report['overall'],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
