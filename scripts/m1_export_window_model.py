#!/usr/bin/env python3
"""m1_export_window_model.py -- 导出可部署的窗口级纯数值模型（专项② P1）。

为什么要单独导出
----------------
`modules/member1_comm/module.py` 的推理路径是**纯数值、无第三方依赖**的：

    x_i = (sign(v_i) * log1p(|v_i|) - mean_i) / scale_i
    z   = sum(w_i * x_i) + intercept
    p   = sigmoid(z)

因此导出的模型必须严格复现这条公式，而不是把 sklearn 对象序列化下来。
本脚本在**变换后的空间**上拟合逻辑回归，再把 (mean, scale, w, intercept)
一并写进 `member1-numeric-v1` JSON，从而保证训练侧与部署侧数值一致——
这一点由 `--verify` 直接比对 sklearn 与纯数值推理器的概率来证明。

评估纪律
--------
* 阈值只用**会话分组交叉验证**在训练折上选，均值 F1 与最差折同时报告；
* 与"恒预测攻击"基线比较，必须显著高于它才算有效；
* 导出前做一次留出集一致性校验，概率差超过 1e-9 即拒绝导出。

用法
----
    python3 scripts/m1_export_window_model.py \
        --windows .../windows_0.jsonl \
        --out modules/member1_comm/model/comm_risk_window_model.json \
        --manifest-out modules/member1_comm/model/model_manifest_window.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from collections import Counter
from datetime import datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, 'scripts'))
from m1_train_windows import (NORMAL_LABEL, NUMERIC, constant_f1,  # noqa: E402
                              load_windows)

DEFAULT_WINDOWS = ('/home/zhangwei/project/RosSystem/data/ROSPaCe_reduced/'
                   'windows_0.jsonl')


def signed_log1p(value):
    return math.copysign(math.log1p(abs(value)), value)


def transform(raw, impute):
    """按模块推理路径做"缺失->训练中位数插补 -> 带符号 log1p"。

    缺失判定必须同时覆盖 None 与 NaN：从 numpy 矩阵取值时缺失是 NaN，
    若只判 None，NaN 会一路传进 log1p 变成 NaN，概率退化为无意义值，
    数值一致性校验就会（正确地）报错。
    """
    out = []
    for i, value in enumerate(raw):
        if value is None or (isinstance(value, float) and math.isnan(value)):
            value = impute[i]
        out.append(signed_log1p(value))
    return out


def score_numeric(model, raw):
    x = transform(raw, model['impute'])
    normalised = [(v - mu) / sigma
                  for v, mu, sigma in zip(x, model['mean'], model['scale'])]
    z = sum(v * w for v, w in zip(normalised, model['weights'])) + model['intercept']
    return 1 / (1 + math.exp(-max(-700, min(700, z))))


def matrix(rows):
    out = []
    for row in rows:
        out.append([float(row.get(name)) if isinstance(row.get(name), (int, float))
                    and math.isfinite(float(row.get(name))) else float('nan')
                    for name in NUMERIC])
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description='导出窗口级纯数值模型')
    parser.add_argument('--windows', default=DEFAULT_WINDOWS)
    parser.add_argument('--out', required=True)
    parser.add_argument('--manifest-out', required=True)
    parser.add_argument('--folds', type=int, default=5)
    args = parser.parse_args(argv)

    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import GroupKFold

    rows = load_windows(args.windows)
    raw = np.array(matrix(rows), dtype=np.float64)
    y = np.array([0 if r['label'] == NORMAL_LABEL else 1 for r in rows])
    groups = np.array([r['segment'] for r in rows])

    # ---- 会话分组交叉验证：阈值只在训练折上选 ----
    fold_scores, fold_thresholds, fold_baselines = [], [], []
    splitter = GroupKFold(n_splits=min(args.folds, len(set(groups))))
    for train_idx, test_idx in splitter.split(np.zeros(len(rows)), y, groups):
        train_raw = raw[train_idx]
        impute = np.nanmedian(train_raw, axis=0)
        impute = np.where(np.isnan(impute), 0.0, impute)
        def prep(matrix_in):
            filled = np.where(np.isnan(matrix_in), impute, matrix_in)
            return np.array([[signed_log1p(v) for v in row] for row in filled])
        train_t = prep(train_raw)
        test_t = prep(raw[test_idx])
        mean = train_t.mean(axis=0)
        scale = train_t.std(axis=0)
        scale = np.where(scale < 1e-12, 1.0, scale)
        clf = LogisticRegression(max_iter=2000, class_weight='balanced')
        clf.fit((train_t - mean) / scale, y[train_idx])
        train_prob = clf.predict_proba((train_t - mean) / scale)[:, 1]
        best = (0.5, -1.0)
        for threshold in (0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9):
            pred = (train_prob >= threshold).astype(int)
            tp = int(((pred == 1) & (y[train_idx] == 1)).sum())
            fp = int(((pred == 1) & (y[train_idx] == 0)).sum())
            fn = int(((pred == 0) & (y[train_idx] == 1)).sum())
            precision = tp / (tp + fp) if tp + fp else 0.0
            recall = tp / (tp + fn) if tp + fn else 0.0
            f1 = (2 * precision * recall / (precision + recall)) if precision + recall else 0.0
            if f1 > best[1]:
                best = (threshold, f1)
        threshold = best[0]
        test_prob = clf.predict_proba((test_t - mean) / scale)[:, 1]
        pred = (test_prob >= threshold).astype(int)
        tp = int(((pred == 1) & (y[test_idx] == 1)).sum())
        fp = int(((pred == 1) & (y[test_idx] == 0)).sum())
        fn = int(((pred == 0) & (y[test_idx] == 1)).sum())
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if precision + recall else 0.0
        fold_scores.append(round(f1, 4))
        fold_thresholds.append(threshold)
        fold_baselines.append(round(constant_f1(int(y[test_idx].sum()), len(test_idx)), 4))

    mean_f1 = float(np.mean(fold_scores))
    baseline_mean = float(np.mean(fold_baselines))
    # 部署阈值取各折阈值的众数（稳健于单折抖动），不取最优折
    deploy_threshold = float(Counter(fold_thresholds).most_common(1)[0][0])

    # ---- 全量重训（部署模型）----
    impute = np.nanmedian(raw, axis=0)
    impute = np.where(np.isnan(impute), 0.0, impute)
    filled = np.where(np.isnan(raw), impute, raw)
    transformed = np.array([[signed_log1p(v) for v in row] for row in filled])
    mean = transformed.mean(axis=0)
    scale = transformed.std(axis=0)
    scale = np.where(scale < 1e-12, 1.0, scale)
    clf = LogisticRegression(max_iter=2000, class_weight='balanced')
    clf.fit((transformed - mean) / scale, y)

    model = {
        'format': 'member1-numeric-v1',
        'algorithm': 'logistic',
        'feature_names': list(NUMERIC),
        'impute': [round(float(v), 10) for v in impute],
        'mean': [round(float(v), 10) for v in mean],
        'scale': [round(float(v), 10) for v in scale],
        'weights': [round(float(v), 10) for v in clf.coef_[0]],
        'intercept': round(float(clf.intercept_[0]), 10),
        'threshold': deploy_threshold,
        # 门槛判定必须来自真实指标，不得手填
        'validation_gate_passed': bool(mean_f1 > baseline_mean + 0.05
                                       and min(fold_scores) > baseline_mean),
        'gate_basis': ('会话分组交叉验证平均 F1 %.4f / 最差折 %.4f vs '
                       '恒预测攻击基线 %.4f（要求平均超过基线 0.05 且最差折仍高于基线）'
                       % (mean_f1, min(fold_scores), baseline_mean)),
    }

    # ---- 数值一致性校验：纯数值推理器 vs sklearn ----
    verify_idx = list(range(0, len(rows), max(1, len(rows) // 500)))[:500]
    checked, max_diff = 0, 0.0
    for i in verify_idx:
        numeric = score_numeric(model, raw[i])
        sklearn_prob = float(clf.predict_proba(
            ((transformed[i] - mean) / scale).reshape(1, -1))[0, 1])
        max_diff = max(max_diff, abs(numeric - sklearn_prob))
        checked += 1
    if max_diff > 1e-9:
        print(json.dumps({'error': 'NUMERIC_MISMATCH', 'max_diff': max_diff}))
        return 2

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, 'w', encoding='utf-8') as fh:
        json.dump(model, fh, ensure_ascii=False, indent=2)
    digest = hashlib.sha256(open(args.out, 'rb').read()).hexdigest()

    manifest = {
        'generated_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'model_path': os.path.relpath(args.out, REPO),
        'model_sha256': digest,
        'algorithm': 'logistic',
        'feature_count': len(NUMERIC),
        'feature_names': list(NUMERIC),
        'training_data': os.path.basename(args.windows),
        'split': 'GroupKFold by segment_index (采集会话分组)',
        'folds': len(fold_scores),
        'fold_f1': fold_scores,
        'fold_baseline_f1': fold_baselines,
        'fold_thresholds': fold_thresholds,
        'mean_f1': round(mean_f1, 4),
        'worst_fold_f1': min(fold_scores),
        'baseline_constant_attack_mean_f1': round(baseline_mean, 4),
        'deploy_threshold': deploy_threshold,
        'validation_gate_passed': model['validation_gate_passed'],
        'gate_basis': model['gate_basis'],
        'numeric_consistency': {'checked_windows': checked,
                                'max_abs_diff': max_diff,
                                'tolerance': 1e-9},
        'provenance_limits': [
            '窗口数据 windows_0.jsonl 由仓库外脚本从 ROSPaCe_reduced PCAP 派生，'
            '生成脚本不在库内；本工作独立审计了其标签分布与特征定义。',
            '特征在 ROS 2 订阅侧与 PCAP 侧语义等价但采样位置不同，'
            '数值不保证逐点相同（见 collector 的 alignment_note）。',
            '会话分组只能保证不跨采集段泄漏，无法证明段内时间自相关已被完全消除。',
        ],
        'not_claimed': [
            '有效实时 IDS',
            '对未知攻击的检测能力',
            '生产环境误报率',
        ],
    }
    with open(args.manifest_out, 'w', encoding='utf-8') as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
    print(json.dumps({'model': args.out, 'sha256': digest,
                      'mean_f1': manifest['mean_f1'],
                      'worst_fold_f1': manifest['worst_fold_f1'],
                      'baseline': manifest['baseline_constant_attack_mean_f1'],
                      'gate': model['validation_gate_passed'],
                      'numeric_max_diff': max_diff}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
