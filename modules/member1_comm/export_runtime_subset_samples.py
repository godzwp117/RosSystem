#!/usr/bin/env python3
"""把已审计的采样分片**按列投影**成"运行时子集"训练集。

为什么是列投影而不是重新采样
============================
`modules/member1_comm/train.py` 的训练集来自 `data.py` 对官方归档的全量行审计
+ 每分片均匀蓄水池抽样。那些采样结果（`shard_*.npz`）已经固定。
要换特征子集，**不需要**也不能重新抽样——重新抽样会改变样本集合，让
"子集模型 vs 全特征模型"的比较失去可比性。

因此本工具只做一件事：按 `--features` 给出的特征名，从既有 npz 中**按列取子集**，
写出新的 npz 与 manifest，并在 manifest 里记录投影前后的特征名与列索引，
使"哪些列被保留/丢弃"完全可追溯。

安全/诚实约束
-------------
* 只允许**减少**列（投影），不允许新增或重排语义；
* 分片顺序、标签、行号、时间戳原样保留；
* 训练/验证/测试划分规则不变（仍由 train.py 按分片号切分）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--samples', type=Path, required=True,
                        help='既有采样目录（含 manifest.json 与 shard_*.npz）')
    parser.add_argument('--features', type=Path, required=True,
                        help='目标特征清单 JSON（只含 feature_names）')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)

    source = args.samples.resolve()
    out = args.out.resolve()
    manifest = json.loads((source / 'manifest.json').read_text(encoding='utf-8'))
    original = manifest['feature_names']
    target = json.loads(args.features.read_text(encoding='utf-8'))['feature_names']
    unknown = [name for name in target if name not in original]
    if unknown:
        raise SystemExit('target features not in source manifest: {0}'.format(unknown))
    if len(set(target)) != len(target):
        raise SystemExit('duplicate feature names in target list')
    indices = [original.index(name) for name in target]
    if indices != sorted(indices):
        raise SystemExit('target features must keep the original column order')

    out.mkdir(parents=True, exist_ok=True)
    files = []
    for entry in sorted(manifest['files'], key=lambda item: item['shard']):
        with np.load(source / entry['sample_file'], allow_pickle=False) as archive:
            matrix = archive['x']
            labels = archive['labels']
            rows = archive['rows']
            stamps = archive['timestamps']
        projected = matrix[:, indices]
        destination = out / entry['sample_file']
        np.savez_compressed(destination, x=projected, labels=labels,
                            rows=rows, timestamps=stamps)
        record = dict(entry)
        record['sample_file'] = destination.name
        record['missing_fraction'] = [entry['missing_fraction'][i] for i in indices]
        files.append(record)
        print('shard {0}: {1} -> {2} columns'.format(
            entry['shard'], len(original), len(target)), flush=True)

    document = dict(manifest)
    document['feature_names'] = list(target)
    document['model_feature_count'] = len(target)
    document['projection'] = {
        'kind': 'COLUMN_PROJECTION_OF_AUDITED_SAMPLES',
        'source_manifest_feature_count': len(original),
        'retained_indices': indices,
        'dropped_features': [name for name in original if name not in target],
        'note': ('仅按列投影，未重新抽样、未新增样本、未改变标签/行号/时间戳；'
                 '训练/验证/测试划分仍按分片号不变'),
    }
    document['files'] = files
    (out / 'manifest.json').write_text(json.dumps(document, indent=2), encoding='utf-8')
    print('wrote {0} shards with {1} features to {2}'.format(
        len(files), len(target), out))
    return 0


if __name__ == '__main__':
    sys.exit(main())
