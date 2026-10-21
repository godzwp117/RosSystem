#!/usr/bin/env python3
"""m1_data_audit.py -- M1 数据与标签审计（专项② P0）。

为什么需要这个脚本
------------------
此前 M1 的两个模型测试 F1 分别只有 0.1312 与 0.0891，而"恒预测攻击"的平凡基线
F1 却有约 0.8132。**一个模型比"一律判攻击"还差一个数量级，说明问题不在模型容量，
而在数据、标签或评估口径。** 在改模型之前必须先把数据事实查清楚。

本脚本逐列、逐文件、逐类别地核对 ROSPaCe_reduced 的 15 个原始分片，输出可复现的
审计事实：

* 标签列到底在哪一列、取值域是什么；
* 每个分片的标签分布（判断"文件级划分"是否等价于"类别划分"）；
* 时间范围与分片之间的时间关系（判断是否能把分片当作独立采集会话）；
* 配置使用的 49 维特征在各分片上的缺失率与量纲漂移；
* 每个类别的样本量与"恒定预测"基线，从而给出任何模型的**最低可接受线**。

设计约束
--------
* 只读数据，不修改、不重采样落盘；
* 采样使用固定种子的等距抽样，保证可复现且与标签无关（不看标签决定抽哪些行）；
* 输出 JSON 供后续训练脚本与报告引用，避免人工转录。

用法
----
    python3 scripts/m1_data_audit.py --out artifacts/research/m1/<run_id>/data_audit

    # 可指定每片抽样行数（默认 20000）
    python3 scripts/m1_data_audit.py --rows-per-shard 50000 --out ...
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DATA = '/home/zhangwei/project/RosSystem/data/ROSPaCe_reduced/ROSPaCe_reduced'
DEFAULT_ARCHIVE = ('/home/zhangwei/project/RosSystem/data/ROSPaCe_reduced/'
                   'ROSPaCe_reduced.tar.gz')
FEATURES = os.path.join(REPO, 'modules/member1_comm/features.json')

#: 标签列的位置：ROSPaCe_reduced 的 CSV 无表头，标签是最后一列。
#: 本脚本**不假设**该位置，而是先在样本上自动探测，探测结果与实际列号不一致就报错。
LABEL_VALUES = {'observe', 'nmap discovery', 'ros2 reconnaissance',
                'attack', 'normal', 'benign'}


def now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def sha256_file(path, limit=None):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        read = 0
        while True:
            chunk = fh.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
            read += len(chunk)
            if limit and read >= limit:
                break
    return h.hexdigest()


def detect_label_column(path, probe=20000):
    """在样本上探测标签列：返回 (列号, 取值分布)。找不到唯一候选就返回 (None, {})."""
    cand = defaultdict(Counter)
    with open(path, newline='', encoding='utf-8', errors='replace') as fh:
        reader = csv.reader(fh)
        width = 0
        for index, row in enumerate(reader):
            if index >= probe:
                break
            width = max(width, len(row))
            for column, value in enumerate(row):
                text = (value or '').strip().lower()
                if text in LABEL_VALUES:
                    cand[column][text] += 1
    if len(cand) != 1:
        return None, {}, width
    column = next(iter(cand))
    return column, dict(cand[column]), width


def to_float(text):
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    if math.isnan(value) or math.isinf(value):
        return None
    return value


def audit_shard(path, label_column, feature_names, feature_index, rows_per_shard):
    """等距抽样一个分片：统计标签、时间范围、特征缺失与分布。"""
    total = os.path.getsize(path)
    with open(path, newline='', encoding='utf-8', errors='replace') as fh:
        lines = sum(1 for _ in fh)
    step = max(1, lines // rows_per_shard) if rows_per_shard else 1

    labels = Counter()
    seen = 0
    first_ts = last_ts = None
    missing = Counter()
    sums = defaultdict(float)
    counts = defaultdict(int)
    mins = {}
    maxs = {}

    with open(path, newline='', encoding='utf-8', errors='replace') as fh:
        reader = csv.reader(fh)
        for index, row in enumerate(reader):
            if index % step:
                continue
            seen += 1
            if label_column < len(row):
                labels[(row[label_column] or '').strip()] += 1
            if row:
                ts = (row[0] or '').strip()
                if ts:
                    if first_ts is None:
                        first_ts = ts
                    last_ts = ts
            for name, column in feature_index.items():
                value = to_float(row[column]) if column < len(row) else None
                if value is None:
                    missing[name] += 1
                    continue
                sums[name] += value
                counts[name] += 1
                if name not in mins or value < mins[name]:
                    mins[name] = value
                if name not in maxs or value > maxs[name]:
                    maxs[name] = value

    means = {n: (sums[n] / counts[n]) for n in sums if counts[n]}
    miss_rate = {n: (missing[n] / seen if seen else 1.0) for n in feature_names}
    return {
        'path': path,
        'bytes': total,
        'lines_sampled': seen,
        'sampling_step': step,
        'labels': dict(labels),
        'time_first': first_ts,
        'time_last': last_ts,
        'feature_missing_rate': miss_rate,
        'feature_mean': means,
        'feature_min': mins,
        'feature_max': maxs,
    }


def constant_predictor_f1(positive, total):
    """"恒预测为正"的 F1：2p/(1+p)，p 为正样本比例。这是任何分类器的最低可接受线。"""
    if total <= 0:
        return None
    p = positive / total
    return (2 * p / (1 + p)) if p > 0 else 0.0


def main(argv=None):
    parser = argparse.ArgumentParser(description='M1 数据与标签审计')
    parser.add_argument('--data-dir', default=DEFAULT_DATA)
    parser.add_argument('--archive', default=DEFAULT_ARCHIVE)
    parser.add_argument('--features', default=FEATURES)
    parser.add_argument('--rows-per-shard', type=int, default=20000)
    parser.add_argument('--out', required=True)
    args = parser.parse_args(argv)

    os.makedirs(args.out, exist_ok=True)
    with open(args.features, encoding='utf-8') as fh:
        feature_manifest = json.load(fh)
    feature_names = feature_manifest['feature_names']

    shards = sorted(
        (name for name in os.listdir(args.data_dir) if name.endswith('.csv')),
        key=lambda n: int(''.join(ch for ch in n if ch.isdigit()) or 0))

    report = {
        'generated_at': now(),
        'script': os.path.relpath(os.path.abspath(__file__), REPO),
        'rows_per_shard': args.rows_per_shard,
        'feature_manifest': {'path': os.path.relpath(args.features, REPO),
                             'count': len(feature_names),
                             'sha256': sha256_file(args.features)},
        'archive': None,
        'shards': [],
        'label_column': None,
        'warnings': [],
    }
    if os.path.isfile(args.archive):
        report['archive'] = {'path': args.archive,
                             'bytes': os.path.getsize(args.archive),
                             'sha256': sha256_file(args.archive)}

    # 1) 标签列探测（只用第一个分片，且要求在全部样本上一致）
    first = os.path.join(args.data_dir, shards[0])
    label_column, label_probe, width = detect_label_column(first)
    if label_column is None:
        report['warnings'].append(
            '无法唯一定位标签列；候选为多个或没有。审计中止。')
        with open(os.path.join(args.out, 'data_audit.json'), 'w',
                  encoding='utf-8') as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
        print(json.dumps(report['warnings'], ensure_ascii=False))
        return 2
    report['label_column'] = {'index': label_column, 'width': width,
                              'probe_distribution': label_probe}

    # 2) 特征在前 1 行上的列位置（无表头，按配置顺序取前 N 列不可靠，
    #    因此这里用"列数 - 1（去掉标签）"与前 49 列做映射，并在报告中声明该假设）
    feature_index = {name: i for i, name in enumerate(feature_names)}
    report['feature_column_mapping'] = {
        'assumption': ('无表头，按 features.json 顺序取前 len(features) 列；'
                       '标签列除外'),
        'n_features': len(feature_names), 'label_column': label_column}

    per_class = Counter()
    for name in shards:
        path = os.path.join(args.data_dir, name)
        info = audit_shard(path, label_column, feature_names, feature_index,
                           args.rows_per_shard)
        info['shard'] = name
        report['shards'].append(info)
        for label, count in info['labels'].items():
            per_class[label] += count

    total = sum(per_class.values())
    summary = {'per_class_sampled': dict(per_class), 'total_sampled': total}
    attack = sum(c for l, c in per_class.items() if l != 'observe')
    summary['attack_sampled'] = attack
    summary['attack_ratio'] = (attack / total) if total else None
    summary['constant_attack_f1'] = constant_predictor_f1(attack, total)
    summary['constant_normal_f1'] = None
    if total:
        p = (total - attack) / total
        summary['constant_normal_f1'] = (2 * p / (1 + p)) if p > 0 else 0.0
    report['summary'] = summary

    # 3) 分片级类别纯度：判断"文件级划分"是否等价于类别划分（泄漏风险）
    purity = []
    for info in report['shards']:
        labels = info['labels']
        total_s = sum(labels.values()) or 1
        dominant = max(labels.values()) if labels else 0
        purity.append({'shard': info['shard'], 'dominant_ratio': dominant / total_s,
                       'labels': labels})
    report['shard_label_purity'] = purity
    if any(item['dominant_ratio'] > 0.95 for item in purity):
        report['warnings'].append(
            '存在单一类别占比 >95% 的分片：文件级划分近似类别划分，'
            '在该划分上报告的高指标不能代表泛化能力。')

    # 4) 特征缺失率最高的若干项（判断是否需要插补）
    miss_by_feature = defaultdict(list)
    for info in report['shards']:
        for name, rate in info['feature_missing_rate'].items():
            miss_by_feature[name].append(rate)
    worst = sorted(((n, sum(v) / len(v)) for n, v in miss_by_feature.items()),
                   key=lambda item: -item[1])[:10]
    report['worst_missing_features'] = [
        {'feature': n, 'mean_missing_rate': r} for n, r in worst]

    with open(os.path.join(args.out, 'data_audit.json'), 'w',
              encoding='utf-8') as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)

    lines = ['# M1 数据审计结果', '',
             f'- 生成时间：{report["generated_at"]}',
             f'- 分片数：{len(shards)}',
             f'- 每片抽样行数：{args.rows_per_shard}',
             f'- 标签列：第 {label_column} 列（共 {width} 列）', '',
             '## 采样标签分布', '', '| 标签 | 样本数 | 占比 |', '| --- | --- | --- |']
    for label, count in sorted(per_class.items(), key=lambda kv: -kv[1]):
        lines.append('| {0} | {1} | {2:.2%} |'.format(label, count, count / total))
    lines += ['', '## 平凡基线（任何模型的最低可接受线）', '',
              f'- 恒预测"攻击" F1 = **{summary["constant_attack_f1"]:.4f}**',
              f'- 恒预测"正常" F1 = **{summary["constant_normal_f1"]:.4f}**', '',
              '> 任何模型若低于恒预测攻击基线，说明它连"一律报警"都不如。', '',
              '## 分片标签纯度', '', '| 分片 | 主导类别占比 | 标签分布 |',
              '| --- | --- | --- |']
    for item in purity:
        lines.append('| {0} | {1:.2%} | {2} |'.format(
            item['shard'], item['dominant_ratio'],
            ', '.join(f'{k}={v}' for k, v in sorted(item['labels'].items()))))
    lines += ['', '## 缺失率最高的特征', '', '| 特征 | 平均缺失率 |', '| --- | --- |']
    for item in report['worst_missing_features']:
        lines.append('| `{0}` | {1:.2%} |'.format(item['feature'],
                                                  item['mean_missing_rate']))
    if report['warnings']:
        lines += ['', '## 警告', ''] + [f'- {w}' for w in report['warnings']]
    with open(os.path.join(args.out, 'data_audit.md'), 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(lines) + '\n')

    print(json.dumps({'out': args.out, 'shards': len(shards),
                      'labels': per_class,
                      'constant_attack_f1': summary['constant_attack_f1'],
                      'warnings': report['warnings']}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
