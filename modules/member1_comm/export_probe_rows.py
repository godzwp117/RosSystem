#!/usr/bin/env python3
"""从真实 ROSPaCe 测试分片导出"协议可达性探针行"。

这个脚本存在的唯一目的
======================
成员一的数值模型是一个**离线**分类器。要证明"真实模型真的在跑、四条状态码
都能通过真实子进程到达"，必须用**真实数据行**而不是随机数或标签反推。

本脚本因此从离线训练得到的 **held-out 测试分片**（shard 13/14）里，按存储顺序
取"第一个过阈值"和"第一个未过阈值"的真实行，连同其分片号、原始 CSV 行号、
真实标签、模型打分一起导出为受控 fixture。

明确不是什么
============
* 不是检测效果评估：这里的行数是 2-4 行，不构成任何指标。
* 不是按标签挑样本：选择顺序由"打分是否过阈值"决定，与真实标签无关；
  标签只作为**记录**写进 fixture，用于事后核对，不参与选择。
* 不是实时观测：这些是离线 CSV 行，证明的是模型推理链路与状态可达性，
  不证明能从 ROS 2 实时采集到同样的特征。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from modules.member1_comm.module import predict, strict_json  # noqa: E402

import numpy as np  # noqa: E402


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--samples', type=Path, required=True,
                        help='训练产出的采样目录（含 manifest.json 与 shard_*.npz）')
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--shards', type=int, nargs='+', default=[13, 14])
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--per-shard', type=int, default=1,
                        help='每分片各导出几行"过阈值"与"未过阈值"真实行')
    args = parser.parse_args(argv)

    args.samples = Path(args.samples).resolve()
    args.model = Path(args.model).resolve()
    args.out = Path(args.out)
    manifest = strict_json((args.samples / 'manifest.json').read_bytes())
    model = strict_json(args.model.read_bytes())
    names = model['feature_names']
    if manifest['feature_names'] != names:
        raise SystemExit('sample manifest features differ from model features')
    threshold = model['threshold']
    probe_rows = []
    for shard in args.shards:
        entry = next((f for f in manifest['files'] if f['shard'] == shard), None)
        if entry is None:
            raise SystemExit('shard {0} absent from sample manifest'.format(shard))
        with np.load(args.samples / entry['sample_file'], allow_pickle=False) as archive:
            matrix = archive['x']
            labels = archive['labels'].tolist()
            rows = archive['rows'].tolist()
            stamps = archive['timestamps'].tolist()
        over, under = [], []
        for index in range(len(labels)):
            values = [None if np.isnan(v) else float(v) for v in matrix[index]]
            score = predict(model, {'feature_names': names, 'values': values})
            item = {
                'shard': shard,
                'sample_index': index,
                'original_csv_row': int(rows[index]),
                'timestamp': stamps[index],
                'dataset_label': labels[index],
                'score': score,
                'feature_names': names,
                'values': values,
            }
            if score >= threshold and len(over) < args.per_shard:
                over.append(item)
            elif score < threshold and len(under) < args.per_shard:
                under.append(item)
            if len(over) >= args.per_shard and len(under) >= args.per_shard:
                break
        probe_rows.extend(over + under)
        print('shard {0}: over={1} under={2}'.format(shard, len(over), len(under)), flush=True)

    gate = bool(model['validation_gate_passed'])
    for item in probe_rows:
        attack = item['score'] >= threshold
        # 期望状态严格由已发布的决策规则推出，与标签无关。
        item['expected_status'] = 'SUSPICIOUS' if attack else ('NORMAL' if gate else 'UNKNOWN')
        item['expected_status_controlled_test'] = 'SUSPICIOUS' if attack else 'NORMAL'
        item['decision_rule'] = ('score >= threshold -> SUSPICIOUS; '
                                 'score < threshold -> NORMAL only if validation_gate_passed '
                                 'else UNKNOWN (controlled-test config may still show NORMAL)')

    document = {
        'schema_version': '1.0.0',
        'purpose': ('real held-out rows for protocol reachability of the member-1 numeric model; '
                    'NOT a detection-effectiveness measurement'),
        'model': {'path': str(args.model.relative_to(ROOT)), 'sha256': sha256(args.model),
                  'threshold': threshold, 'validation_gate_passed': gate,
                  'algorithm': model['algorithm']},
        'dataset': {'archive_name': manifest['archive_name'],
                    'archive_sha256': manifest['archive_sha256'],
                    'archive_md5': manifest['archive_md5'],
                    'official_verification': manifest['official_verification'],
                    'split_type': 'FILE_DISJOINT_SPLIT',
                    'shards': args.shards,
                    'sampling': 'uniform reservoir per shard (see manifest.json)',
                    'selection': 'first rows in stored order crossing / not crossing the model threshold; '
                                 'dataset labels are recorded but never used for selection'},
        'rows': probe_rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(document, indent=2, allow_nan=False), encoding='utf-8')
    print('wrote {0} rows to {1}'.format(len(probe_rows), args.out))
    return 0


if __name__ == '__main__':
    sys.exit(main())
