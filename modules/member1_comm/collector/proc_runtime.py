"""成员一运行时观测器：从 Linux `/proc` 采集**真实**的 OS Monitor 特征子集。

它解决什么问题
==============
成员一的 49 维模型里有 25 维在数据集文档（`feature_list.xlsx`）中标注为
"OS Monitor"，即主机侧计数/计量。这些量在 Linux 上确实可采（不需要 ROS 2、
不需要抓包权限），因此可以做出**真实运行时观测**，而不是受控 fixture。

它不解决什么问题（必须原样转述）
================================
* 另外 22 维是 Tshark 逐包解析字段（`layers.tcp.tcp.analysis.*` 等），
  需要 pcap + Wireshark 解剖；本仓库/本环境没有 tshark，也**不能**用
  `tcpdump` 的原始字节伪造这些语义。
* 2 维 `subscribers_count` / `publishers_count` 需要 ROS 2 图内省
  （`ros2 node list`/`get_topic_names_and_types`），本环境没有 ROS 2。
* `request_count` 是**业务请求数**，不是报文数；没有 ROS 2 动作计数就只能是
  `None`，绝不能用采样次数或包数代替。
* 语义等价性**未验证**：数据集只写了 "OS Monitor" 与官方文档链接，
  没有说明采样周期、累计/增量、单位。本模块按"绝对快照 + 计数器的窗口增量"
  如实记录两种值，并在可行性矩阵里把等价性标为 `UNVERIFIED`。

因此：本观测器可以产出**真实**的 25 维子集（其中本机 `pgalloc_dma` 缺失），
但**不能**让 49 维模型获得等价输入。
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import socket
import time
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = 'member1-runtime-observation/1'

#: 25 个数据集 OS Monitor 特征的采集规格。
#: kind: counter=自启动累计（窗口内取增量）；gauge=瞬时值。
SPECS = {
    'Net_Sent': {'path': '/proc/net/dev', 'kind': 'counter', 'unit': 'bytes',
                 'detail': 'sum(tx bytes) over non-loopback interfaces'},
    'Net_Received': {'path': '/proc/net/dev', 'kind': 'counter', 'unit': 'bytes',
                     'detail': 'sum(rx bytes) over non-loopback interfaces'},
    'pgpgin': {'path': '/proc/vmstat', 'kind': 'counter', 'unit': 'pages'},
    'pgpgout': {'path': '/proc/vmstat', 'kind': 'counter', 'unit': 'pages'},
    'pgfault': {'path': '/proc/vmstat', 'kind': 'counter', 'unit': 'events'},
    'pgmajfault': {'path': '/proc/vmstat', 'kind': 'counter', 'unit': 'events'},
    'pgfree': {'path': '/proc/vmstat', 'kind': 'counter', 'unit': 'pages'},
    'pgactivate': {'path': '/proc/vmstat', 'kind': 'counter', 'unit': 'pages'},
    'pgdeactivate': {'path': '/proc/vmstat', 'kind': 'counter', 'unit': 'pages'},
    'pgalloc_dma': {'path': '/proc/vmstat', 'kind': 'counter', 'unit': 'pages'},
    'nr_active_file': {'path': '/proc/vmstat', 'kind': 'gauge', 'unit': 'pages'},
    'nr_inactive_file': {'path': '/proc/vmstat', 'kind': 'gauge', 'unit': 'pages'},
    'MemFree': {'path': '/proc/meminfo', 'kind': 'gauge', 'unit': 'kB'},
    'Buffers': {'path': '/proc/meminfo', 'kind': 'gauge', 'unit': 'kB'},
    'Cached': {'path': '/proc/meminfo', 'kind': 'gauge', 'unit': 'kB'},
    'Active': {'path': '/proc/meminfo', 'kind': 'gauge', 'unit': 'kB'},
    'Inactive': {'path': '/proc/meminfo', 'kind': 'gauge', 'unit': 'kB'},
    'SwapFree': {'path': '/proc/meminfo', 'kind': 'gauge', 'unit': 'kB'},
    'Disk_Read': {'path': '/proc/diskstats', 'kind': 'counter', 'unit': 'sectors',
                  'detail': 'sum(sectors read) over whole block devices'},
    'Disk_Write': {'path': '/proc/diskstats', 'kind': 'counter', 'unit': 'sectors',
                   'detail': 'sum(sectors written) over whole block devices'},
    'Tcp_Established': {'path': '/proc/net/tcp[,6]', 'kind': 'gauge', 'unit': 'sockets',
                        'detail': 'count state 01'},
    'Tcp_Syn': {'path': '/proc/net/tcp[,6]', 'kind': 'gauge', 'unit': 'sockets',
                'detail': 'count state 02 (SYN_SENT)'},
    'Tcp_TimeWait': {'path': '/proc/net/tcp[,6]', 'kind': 'gauge', 'unit': 'sockets',
                     'detail': 'count state 06'},
    'Tcp_Close': {'path': '/proc/net/tcp[,6]', 'kind': 'gauge', 'unit': 'sockets',
                  'detail': 'count state 07'},
    'Tcp_Listen': {'path': '/proc/net/tcp[,6]', 'kind': 'gauge', 'unit': 'sockets',
                   'detail': 'count state 0A'},
}

#: TCP 状态码 -> 特征名
TCP_STATES = {'01': 'Tcp_Established', '02': 'Tcp_Syn', '06': 'Tcp_TimeWait',
              '07': 'Tcp_Close', '0A': 'Tcp_Listen'}

PSEUDO_PREFIXES = ('loop', 'ram', 'sr', 'fd', 'dm-', 'zram')

#: 子集模型的特征清单。输出顺序**必须**与它一致：M1 对 feature_names 做严格顺序
#: 比对（不允许补零或重排），顺序不对会被正确地判为 FEATURES_INVALID。
SUBSET_MANIFEST = Path(__file__).resolve().parents[1] / 'features_runtime_subset.json'


def default_feature_order():
    """读取子集模型的特征顺序；文件缺失时退回 SPECS 声明顺序。"""
    try:
        document = json.loads(SUBSET_MANIFEST.read_text(encoding='utf-8'))
        names = document.get('feature_names')
        if isinstance(names, list) and names:
            return [str(name) for name in names]
    except (OSError, ValueError):
        pass
    return list(SPECS)


class CollectionError(RuntimeError):
    """采集不可用/不完整。调用方不得把不完整结果当作完整观测。"""


def _utc(epoch=None):
    return datetime.fromtimestamp(time.time() if epoch is None else epoch,
                                  timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _utc_ms(milliseconds):
    """毫秒精度 RFC3339。

    必须用毫秒：模块会用 (end - start) 交叉核对 duration_ms，
    秒级截断会让窗口自相矛盾（差最多 1 秒），从而被正确地拒绝。
    """
    moment = datetime.fromtimestamp(milliseconds / 1000.0, timezone.utc)
    return moment.strftime('%Y-%m-%dT%H:%M:%S.') + '{0:03d}Z'.format(
        moment.microsecond // 1000)


def _read_text(path):
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as handle:
            return handle.read()
    except OSError as exc:
        raise CollectionError('cannot read {0}: {1}'.format(path, exc.strerror)) from None


def _vmstat():
    values = {}
    for line in _read_text('/proc/vmstat').splitlines():
        parts = line.split()
        if len(parts) == 2:
            try:
                values[parts[0]] = float(parts[1])
            except ValueError:
                continue
    return values


def _meminfo():
    values = {}
    for line in _read_text('/proc/meminfo').splitlines():
        if ':' not in line:
            continue
        key, rest = line.split(':', 1)
        parts = rest.split()
        if parts:
            try:
                values[key.strip()] = float(parts[0])
            except ValueError:
                continue
    return values


def _net_dev():
    """返回 (rx_bytes, tx_bytes)：只统计非 loopback 接口（数据集来源为真实网卡）。"""
    rx = tx = 0.0
    for line in _read_text('/proc/net/dev').splitlines()[2:]:
        if ':' not in line:
            continue
        name, rest = line.split(':', 1)
        name = name.strip()
        if name == 'lo' or name.startswith(PSEUDO_PREFIXES):
            continue
        fields = rest.split()
        if len(fields) < 9:
            continue
        try:
            rx += float(fields[0])
            tx += float(fields[8])
        except ValueError:
            continue
    return rx, tx


def _whole_devices():
    try:
        names = os.listdir('/sys/block')
    except OSError:
        names = []
    return [name for name in names if not name.startswith(PSEUDO_PREFIXES)]


def _diskstats():
    """返回 (sectors_read, sectors_written)：只统计整盘设备，排除分区与伪设备。"""
    whole = set(_whole_devices())
    read = write = 0.0
    for line in _read_text('/proc/diskstats').splitlines():
        parts = line.split()
        if len(parts) < 14:
            continue
        name = parts[2]
        if whole and name not in whole:
            continue
        if not whole and name.startswith(PSEUDO_PREFIXES):
            continue
        try:
            read += float(parts[5])
            write += float(parts[9])
        except ValueError:
            continue
    return read, write


def _tcp_states():
    counts = {feature: 0.0 for feature in TCP_STATES.values()}
    for path in ('/proc/net/tcp', '/proc/net/tcp6'):
        try:
            text = _read_text(path)
        except CollectionError:
            continue
        for line in text.splitlines()[1:]:
            parts = line.split()
            if len(parts) < 4:
                continue
            feature = TCP_STATES.get(parts[3].upper())
            if feature:
                counts[feature] += 1.0
    return counts


def snapshot():
    """取一次瞬时快照：返回 {feature: value} 与每个特征的来源说明。"""
    vm = _vmstat()
    mem = _meminfo()
    rx, tx = _net_dev()
    disk_read, disk_write = _diskstats()
    tcp = _tcp_states()
    values, missing = {}, {}

    def take(name, value):
        if value is None:
            missing[name] = 'field absent on this host'
        else:
            values[name] = float(value)

    take('Net_Received', rx)
    take('Net_Sent', tx)
    take('Disk_Read', disk_read)
    take('Disk_Write', disk_write)
    for name in ('pgpgin', 'pgpgout', 'pgfault', 'pgmajfault', 'pgfree',
                 'pgactivate', 'pgdeactivate', 'pgalloc_dma',
                 'nr_active_file', 'nr_inactive_file'):
        take(name, vm.get(name))
    for name in ('MemFree', 'Buffers', 'Cached', 'Active', 'Inactive', 'SwapFree'):
        take(name, mem.get(name))
    for name, count in tcp.items():
        take(name, count)
    return values, missing


def collect(duration_sec=2.0, interval_sec=0.5, feature_order=None):
    """在一个真实时间窗口内多次采样，返回可追溯的观测块。

    返回值直接对应"证据"的要求：窗口起止与时长、采样次数、每个特征的首末值与
    窗口增量、来源文件、缺失项、以及测量内容的 SHA-256。
    """
    if duration_sec <= 0 or interval_sec <= 0:
        raise ValueError('duration/interval must be positive')
    started = time.time()
    first, first_missing = snapshot()
    samples = 1
    last, last_missing = first, first_missing
    deadline = started + duration_sec
    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            break
        time.sleep(min(interval_sec, remaining))
        last, last_missing = snapshot()
        samples += 1
        if time.time() >= deadline:
            break
    ended = time.time()
    # 用**取整后的毫秒**同时生成时间戳与 duration_ms，保证三者严格自洽。
    start_ms = int(round(started * 1000))
    end_ms = int(round(ended * 1000))
    duration_ms = end_ms - start_ms
    if duration_ms <= 0:
        raise CollectionError('window too short to be meaningful')

    order = list(feature_order) if feature_order else default_feature_order()
    names = [name for name in order if name in last and name in first]
    # 兜底：任何采集到但不在顺序表里的特征追加在末尾（正常不会发生）
    names += [name for name in last if name in first and name not in names]
    missing = dict(first_missing)
    missing.update({key: value for key, value in last_missing.items()
                    if key not in missing})
    provenance = {}
    for name in names:
        spec = SPECS[name]
        provenance[name] = {
            'path': spec['path'], 'kind': spec['kind'], 'unit': spec['unit'],
            'detail': spec.get('detail', ''),
            'first': round(first[name], 6), 'last': round(last[name], 6),
            'window_delta': round(last[name] - first[name], 6),
        }
    measurements = {'feature_names': names,
                    'values': [round(last[name], 6) for name in names],
                    'window_deltas': [round(last[name] - first[name], 6)
                                      for name in names]}
    digest = hashlib.sha256(json.dumps(measurements, sort_keys=True,
                                       separators=(',', ':')).encode()).hexdigest()
    return {
        'schema_version': SCHEMA,
        'collected_at': _utc(),
        'window': {'start': _utc_ms(start_ms), 'end': _utc_ms(end_ms),
                   'duration_ms': duration_ms,
                   'interval_ms': int(round(interval_sec * 1000)),
                   'sample_count': samples},
        'source': {
            'kind': 'LINUX_PROC',
            'host': socket.gethostname(),
            'kernel': platform.release(),
            'privileges_required': 'none (world-readable /proc entries)',
        },
        'measurements': measurements,
        'feature_order_source': ('features_runtime_subset.json'
                                  if order == default_feature_order()
                                  else 'caller-supplied'),
        'feature_provenance': provenance,
        'missing': missing,
        'unavailable': {
            'request_count': ('business request count requires ROS 2 action '
                              'accounting; packet/loop counts are NOT a substitute'),
            'tshark_features': ('22 of the 49 model features are per-packet Wireshark '
                                'dissections; no tshark in this environment'),
            'ros_graph_features': ['subscribers_count', 'publishers_count'],
        },
        'evidence': {
            'measurement_sha256': digest,
            'raw_sources': sorted({spec['path'] for spec in SPECS.values()}),
            'note': ('真实 Linux /proc 采样；不包含任何仿真值。'
                     '缺失项如实列出，不做填补。'),
        },
    }
