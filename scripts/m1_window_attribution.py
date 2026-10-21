#!/usr/bin/env python3
"""m1_window_attribution.py -- 逐特征归因诊断（专项③/第三轮 P0）。

为什么需要它
-----------
第二轮把实时 1 秒窗口喂给一个**用 30 秒窗口训练**的模型，结果正常 50 Hz
发布者的窗口全部得到 1.0 风险分。仅说"分布漂移"没有诊断价值，必须给出
**每个特征对 logit 的贡献**，才能判断是哪一个契约参数失配。

模型打分公式（与 module.py 一致）：

    raw_i -> t_i = sign(raw_i) * log1p(|raw_i|)
    x_i        = (t_i - mean_i) / scale_i
    z          = sum(w_i * x_i) + intercept
    p          = sigmoid(z)

因此每个特征的贡献就是 `w_i * x_i`；`z` 是该贡献之和加截距。

本工具输出：
* 每个特征的 raw 值、变换值、标准化值、权重、贡献；
* 贡献排序（谁把结论推向"攻击"）；
* 训练分布分位数，用于判断该输入是否落在训练域内。

用法
----
    python3 scripts/m1_window_attribution.py \
        --model modules/member1_comm/model/comm_risk_window_model.json \
        --windows-json artifacts/.../window_scored_50hz.json \
        --out artifacts/.../attribution.json
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DATA = ('/home/zhangwei/project/RosSystem/data/ROSPaCe_reduced/'
                'windows_0.jsonl')


def signed_log1p(value):
    return math.copysign(math.log1p(abs(value)), value)


def percentiles(values):
    if not values:
        return {}
    ordered = sorted(values)
    n = len(ordered)
    out = {}
    for p in (1, 5, 50, 95, 99):
        index = min(n - 1, max(0, int(round(p / 100.0 * (n - 1)))))
        out[f'p{p}'] = round(ordered[index], 4)
    return out


def training_distribution(path, feature_names):
    values = {name: [] for name in feature_names}
    with open(path, encoding='utf-8') as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            window = d.get('window') or {}
            record = {
                'request_count': d.get('request_count'),
                'frequency_hz': d.get('frequency_hz'),
                'gap_median_ms': d.get('gap_median_ms'),
                'gap_p95_ms': d.get('gap_p95_ms'),
                'gap_max_ms': d.get('gap_max_ms'),
                'duration_ms': window.get('duration_ms'),
            }
            for name in feature_names:
                value = record.get(name)
                if isinstance(value, (int, float)) and math.isfinite(float(value)):
                    values[name].append(float(value))
    return {name: percentiles(vals) for name, vals in values.items()}


def attribute(model, record):
    """返回 (probability, z, contributions[])。"""
    names = model['feature_names']
    contributions = []
    total = 0.0
    for i, name in enumerate(names):
        raw = record.get(name)
        if not isinstance(raw, (int, float)) or not math.isfinite(float(raw)):
            raw = model['impute'][i]
            missing = True
        else:
            missing = False
        transformed = signed_log1p(float(raw))
        standardised = (transformed - model['mean'][i]) / model['scale'][i]
        contribution = standardised * model['weights'][i]
        total += contribution
        contributions.append({
            'feature': name, 'raw': raw, 'imputed': missing,
            'transformed': round(transformed, 6),
            'standardised': round(standardised, 6),
            'weight': model['weights'][i],
            'contribution_to_logit': round(contribution, 6),
        })
    z = total + model['intercept']
    probability = 1.0 / (1.0 + math.exp(-max(-700.0, min(700.0, z))))
    contributions.sort(key=lambda c: -abs(c['contribution_to_logit']))
    return probability, z, contributions


def main(argv=None):
    parser = argparse.ArgumentParser(description='逐特征归因')
    parser.add_argument('--model', required=True)
    parser.add_argument('--windows-json', required=True,
                        help='采集器输出（含 windows[].features）')
    parser.add_argument('--training-data', default=DEFAULT_DATA)
    parser.add_argument('--out', required=True)
    args = parser.parse_args(argv)

    model = json.load(open(args.model, encoding='utf-8'))
    document = json.load(open(args.windows_json, encoding='utf-8'))
    windows = document.get('windows') or []
    names = model['feature_names']
    train_dist = training_distribution(args.training_data, names)

    results = []
    for index, window in enumerate(windows):
        features = window.get('features') or {}
        probability, z, contributions = attribute(model, features)
        out_of_range = []
        for name in names:
            value = features.get(name)
            dist = train_dist.get(name) or {}
            if not isinstance(value, (int, float)) or not dist:
                continue
            if value < dist['p1'] or value > dist['p99']:
                out_of_range.append({'feature': name, 'value': value,
                                     'training_p1': dist['p1'],
                                     'training_p99': dist['p99']})
        results.append({
            'window_index': index,
            'samples': window.get('samples'),
            'features': features,
            'probability': round(probability, 6),
            'logit': round(z, 6),
            'threshold': model['threshold'],
            'decision': ('ATTACK' if probability >= model['threshold']
                         else 'NORMAL'),
            'contributions': contributions,
            'outside_training_p1_p99': out_of_range,
        })

    aggregate = {}
    for name in names:
        aggregate[name] = {
            'training_percentiles': train_dist.get(name),
            'training_weight': model['weights'][names.index(name)],
        }
    summary = {
        'model': args.model,
        'threshold': model['threshold'],
        'windows_scored': len(results),
        'windows_attack': sum(1 for r in results if r['decision'] == 'ATTACK'),
        'training_distribution': aggregate,
        'windows': results,
        'diagnosis_hint': ('若 duration_ms / request_count / frequency_hz 的取值'
                           '与 training_percentiles 相差一个数量级，说明窗口契约'
                           '不一致，而不是"模型学错了"。'),
    }
    with open(args.out, 'w', encoding='utf-8') as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)

    if results:
        first = results[0]
        print(json.dumps({
            'windows': len(results),
            'attack_windows': summary['windows_attack'],
            'probability_first': first['probability'],
            'logit_first': first['logit'],
            'top_contributions': [
                {'feature': c['feature'], 'raw': c['raw'],
                 'contribution': c['contribution_to_logit'],
                 'training_p50': train_dist.get(c['feature'], {}).get('p50'),
                 'training_p99': train_dist.get(c['feature'], {}).get('p99')}
                for c in first['contributions'][:4]],
            'out': args.out,
        }, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
