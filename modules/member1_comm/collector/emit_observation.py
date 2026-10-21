#!/usr/bin/env python3
"""采集一次真实运行时观测，并输出可被 M1 消费（或明确拒绝）的观测块。

为什么需要它
============
M1 需要 `observations[].detail.rospace_comm.features`（特征向量）与
`detail.f0_runtime`（资源、请求计数、时间窗）。本工具负责**真实**产出前者，
并如实标注后者哪一部分缺失。

关键约束：request_count 不会被伪造
==================================
`request_count` 是**业务请求数**（ROS 2 Action 触发次数），不是采样次数、
不是报文数、不是 TCP 连接数。没有 ROS 2 运行时就没有这个计数，因此：

* 不给 `--request-count` 时，输出里没有 `f0_runtime`，M1 会以退出码 4
  （`MAPPING_BLOCKED`）失败关闭——这正是当前真实状态；
* 给了 `--request-count` 时，输出会带 `request_count_source`，写明这个数字
  是**算子/实验脚本声明**的（CONTROLLED_TEST），不是自动采集的。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.member1_comm.collector import proc_runtime  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--duration', type=float, default=2.0)
    parser.add_argument('--interval', type=float, default=0.5)
    parser.add_argument('--resource', default='/rg/guarded_navigate')
    parser.add_argument('--kind', default='RUNTIME_LOG',
                        help='观测种类（写入信封时必须与受信任配置一致）')
    parser.add_argument('--request-count', type=int,
                        help='业务请求数（只能由算子/实验脚本声明）')
    parser.add_argument('--out', required=True, help='快照 JSON 输出路径')
    parser.add_argument('--observation-out',
                        help='可选：输出可直接合并进信封的观测块')
    args = parser.parse_args(argv)

    snapshot = proc_runtime.collect(args.duration, args.interval)
    snapshot['resource'] = args.resource
    snapshot['observation_kind'] = args.kind
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding='utf-8')

    observation = {
        'source': args.resource,
        'kind': args.kind,
        'observed_at': snapshot['window']['end'],
        'detail': {
            'rospace_comm': {
                'features': {
                    'feature_names': snapshot['measurements']['feature_names'],
                    'values': snapshot['measurements']['values'],
                },
                'collection': {
                    'schema_version': snapshot['schema_version'],
                    'measurement_sha256': snapshot['evidence']['measurement_sha256'],
                    'window': snapshot['window'],
                    'source': snapshot['source']['kind'],
                    'missing': snapshot['missing'],
                    'semantic_equivalence': 'UNVERIFIED',
                    'note': '真实 Linux /proc 采样；主机级窗口值，不能归因到单条请求',
                },
            },
        },
    }
    if args.request_count is not None:
        observation['detail']['f0_runtime'] = {
            'communication': {'resource': args.resource,
                              'resource_type': 'Action',
                              'operation': 'GOAL_SEND'},
            'request_count': args.request_count,
            'request_count_source': 'OPERATOR_DECLARED_CONTROLLED_TEST',
            'window': {'start': snapshot['window']['start'],
                       'end': snapshot['window']['end'],
                       'duration_ms': snapshot['window']['duration_ms']},
        }
    else:
        observation['detail']['mapping_blocked'] = {
            'request_count': snapshot['unavailable']['request_count'],
            'reason': ('没有 ROS 2 运行时 -> 没有业务请求计数；'
                       'M1 必须失败关闭（退出码 4），不得用采样次数代替'),
        }

    if args.observation_out:
        target = Path(args.observation_out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({'observations': [observation],
                                      'evidence_refs': [
                                          {'ref': 'modules/member1_comm/collector/proc_runtime.py',
                                           'kind': args.kind}]},
                                     indent=2, ensure_ascii=False),
                          encoding='utf-8')
    print(json.dumps({
        'snapshot': str(out),
        'observation': str(args.observation_out) if args.observation_out else None,
        'features': len(snapshot['measurements']['feature_names']),
        'missing': snapshot['missing'],
        'measurement_sha256': snapshot['evidence']['measurement_sha256'],
        'request_count': args.request_count,
        'mapping': ('COMPLETE' if args.request_count is not None
                    else 'BLOCKED_MISSING_REQUEST_COUNT'),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
