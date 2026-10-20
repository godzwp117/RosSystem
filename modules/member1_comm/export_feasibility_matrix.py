#!/usr/bin/env python3
"""生成 M1 特征可采集性矩阵（机器可读），供 docs/integration 引用。

产物
====
`docs/integration/m1_feature_feasibility.json`：49 个模型特征逐条记录

* `dataset_monitor`：数据集文档（`feature_list.xlsx`）标注的采集来源
  （Tshark / OS Monitor / ROS Monitor Node）；
* `runtime_source`：本系统在目标环境里能对应到什么（精确到 /proc 文件与字段，
  或者明确写"需要 tshark 解剖"/"需要 ROS 2 图内省"）；
* `collectable`：COLLECTABLE_RUNTIME_OK / COLLECTABLE_RUNTIME_MISSING_ON_HOST /
  REQUIRES_PCAP_DISSECTION / REQUIRES_ROS_GRAPH / UNKNOWN；
* `semantic_equivalence`：与训练语义是否等价（**默认 UNVERIFIED**，不得写 EQUIVALENT，
  除非能给出采样周期/单位/统计口径的证据）；
* `per_request_linkage`：这些值能否归因到**单条**任务请求。主机级 /proc 计数器
  是主机全局量，只能做到"同一时间窗"，不能做到"同一条请求"；
* `needs_extra_privilege`：是否需要额外权限（/proc 全部为 world-readable）。

为什么强调"名称相似不等于特征等价"
==================================
`layers.tcp.tcp.window_size` 与"某个 socket 的 SO_RCVBUF"看起来都是"窗口大小"，
但前者是逐包 TCP 头字段，后者是内核套接字参数；把它们当同一个量会直接
制造错误的检测依据。因此本矩阵不按名字对齐，只按**采集机制**对齐。

用法
====
```bash
python3 modules/member1_comm/export_feasibility_matrix.py \
    --xlsx /path/to/feature_list.xlsx \
    --out docs/integration/m1_feature_feasibility.json
```
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from modules.member1_comm.collector import proc_runtime  # noqa: E402

TSHARK_LIKE = ('layers.',)


def probe_environment():
    """如实探测本机能力；所有结论都来自实际检查，不做假设。"""
    vmstat = {}
    try:
        for line in open('/proc/vmstat', encoding='utf-8').read().splitlines():
            parts = line.split()
            if len(parts) == 2:
                vmstat[parts[0]] = parts[1]
    except OSError:
        pass
    return {
        'ros_available': bool(os.path.isdir('/opt/ros')) or bool(shutil.which('ros2')),
        'ros2_binary': shutil.which('ros2'),
        'tshark': shutil.which('tshark'),
        'tcpdump': shutil.which('tcpdump'),
        'kernel': platform.release(),
        'platform': platform.platform(),
        'proc_readable': {path: os.access(path, os.R_OK) for path in
                          ('/proc/net/dev', '/proc/net/snmp', '/proc/net/tcp',
                           '/proc/net/tcp6', '/proc/meminfo', '/proc/vmstat',
                           '/proc/diskstats')},
        'vmstat_has': {key: (key in vmstat) for key in
                       ('pgpgin', 'pgpgout', 'pgfault', 'pgmajfault', 'pgfree',
                        'pgactivate', 'pgdeactivate', 'pgalloc_dma',
                        'nr_active_file', 'nr_inactive_file')},
    }


def load_dataset_docs(xlsx):
    import openpyxl
    workbook = openpyxl.load_workbook(str(xlsx), read_only=True)
    sheet = workbook['features_list']
    rows = list(sheet.iter_rows(values_only=True))[1:]
    return {row[0]: {'monitor': row[1], 'description': row[2]}
            for row in rows if row and row[0]}


def classify(name, doc, probe):
    """返回 (runtime_source, collectable, needs_privilege, linkage, note)。"""
    monitor = (doc or {}).get('monitor')
    if monitor == 'OS Monitor':
        spec = proc_runtime.SPECS.get(name)
        if spec is None:
            return ('未实现的 /proc 读取器', 'UNKNOWN', 'none', 'WINDOW_ONLY',
                    '数据集标注为 OS Monitor，但本观测器尚未实现该字段')
        if name == 'pgalloc_dma' and not probe['vmstat_has'].get('pgalloc_dma'):
            return ('/proc/vmstat:pgalloc_dma（本机缺失）',
                    'COLLECTABLE_RUNTIME_MISSING_ON_HOST', 'none', 'WINDOW_ONLY',
                    '本机 /proc/vmstat 没有该计数器；不得用其它字段替代')
        return ('{0} [{1}]'.format(spec['path'], spec.get('detail', spec['kind'])),
                'COLLECTABLE_RUNTIME_OK', 'none', 'WINDOW_ONLY', spec.get('detail', ''))
    if monitor == 'ROS Monitor Node':
        return ('ROS 2 图内省（rclpy / ros2 node / topic 列表）',
                'REQUIRES_ROS_GRAPH', 'ROS 2 运行时',
                'PER_REQUEST_POSSIBLE_WITH_GRAPH_SNAPSHOT',
                '需要 ROS 2 运行时；本环境没有 ROS 2')
    if monitor == 'Tshark' or str(name).startswith(TSHARK_LIKE):
        if not probe['tshark']:
            return ('pcap + tshark 解剖（{0}）'.format(name),
                    'REQUIRES_PCAP_DISSECTION', 'CAP_NET_RAW + tshark',
                    'PER_PACKET_POSSIBLE_BUT_COSTLY',
                    '本环境无 tshark；tcpdump 只能给出原始字节，不能伪造解剖语义')
        return ('pcap + tshark 解剖', 'REQUIRES_PCAP_DISSECTION',
                'CAP_NET_RAW + tshark', 'PER_PACKET_POSSIBLE_BUT_COSTLY', '')
    return ('未知来源', 'UNKNOWN', 'unknown', 'UNKNOWN',
            '数据集文档未标注 monitor')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--features', default=str(
        ROOT / 'modules/member1_comm/features.json'))
    parser.add_argument('--xlsx', required=True,
                        help='ROSPaCe feature_list.xlsx（数据集文档，不入库）')
    parser.add_argument('--out', required=True)
    args = parser.parse_args(argv)

    names = json.loads(Path(args.features).read_text(encoding='utf-8'))['feature_names']
    docs = load_dataset_docs(args.xlsx)
    probe = probe_environment()
    rows = []
    for name in names:
        doc = docs.get(name)
        runtime_source, collectable, privilege, linkage, note = classify(
            name, doc, probe)
        rows.append({
            'feature': name,
            'dataset_monitor': (doc or {}).get('monitor', 'NOT_DOCUMENTED'),
            'dataset_description': (doc or {}).get('description', ''),
            'runtime_source': runtime_source,
            'collectable': collectable,
            'needs_extra_privilege': privilege,
            'per_request_linkage': linkage,
            'semantic_equivalence': 'UNVERIFIED',
            'runtime_subset_member': name in proc_runtime.SPECS and name != 'pgalloc_dma',
            'note': note,
        })
    counts = Counter(row['collectable'] for row in rows)
    document = {
        'schema_version': 'm1-feature-feasibility/1',
        'generated_at_utc': __import__('datetime').datetime.utcnow()
                            .strftime('%Y-%m-%dT%H:%M:%SZ'),
        'model': {'feature_manifest': 'modules/member1_comm/features.json',
                  'feature_count': len(rows)},
        'dataset_documentation': {
            'source': 'ROSPaCe feature_list.xlsx (features_list sheet)',
            'monitor_counts': dict(Counter(row['dataset_monitor'] for row in rows)),
            'note': ('monitor 列是数据集作者标注的采集来源；description 只给官方文档链接，'
                     '未给出采样周期、单位或统计口径'),
        },
        'environment_probe': probe,
        'summary': {
            'counts': dict(counts),
            'runtime_subset_size': sum(1 for row in rows
                                       if row['runtime_subset_member']),
            'verdict': ('49 维模型输入无法在目标环境按等价语义获得：'
                        '24 维可真实采集（主机级、窗口级），22 维需 tshark 解剖，'
                        '2 维需 ROS 2 图内省，1 维本机缺失。'),
        },
        'features': rows,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps({'out': str(out), 'counts': dict(counts),
                      'runtime_subset': document['summary']['runtime_subset_size'],
                      'env': {k: probe[k] for k in ('ros_available', 'tshark', 'tcpdump')}},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
