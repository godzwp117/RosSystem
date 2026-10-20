#!/usr/bin/env python3
"""m1_session_collector.py -- 一次独立采集会话的多资源窗口观测器（研究用）。

设计要点（对应 M1_TRUSTED_DATA_COLLECTION_SPEC）
==============================================
1. **一个进程 = 一个采集会话**。会话有显式开始/结束时间，写入 session 元数据。
2. **窗口固定**：窗口长度由 `--window` 给定（默认 30 s），首尾相接不重叠。
   窗口时长因此是常量，**不可能**成为判别信号（这正是上一轮 duration_ms 泄漏的修复）。
3. **特征只来自本进程实际观测**：订阅回调收到多少条、到达间隔多少、
   图结构在窗口内变化多少次，全部由本进程计数，不接受任何外部自报。
4. **标签不参与**：本脚本**不产生标签**，也不知道标签。标签由实验驱动方
   在会话元数据里声明，并附 label_basis。模型预测绝不参与标签生成。
5. **样本不足给 INSUFFICIENT**：窗口内样本 < MIN_SAMPLES 时标记为不足，
   不编造数值。

特征（全部运行时真实可观测，且不含时长/会话/资源名）
--------------------------------------------------
    message_count      窗口内本订阅者收到的消息数
    frequency_hz       message_count / 窗口秒数
    gap_median_ms      相邻到达间隔中位数
    gap_p95_ms         相邻到达间隔 95 分位
    gap_max_ms         相邻到达间隔最大值
    gap_cv             间隔变异系数（std/mean），刻画规律性
    graph_change_count 窗口内 ROS 图结构变化回调次数（节点/话题增减）
    distinct_publishers 窗口内该话题上见过的不同发布者数量

刻意**不采集**：窗口时长、segment id、文件名、脚本名、场景编号、
Gateway 决策、执行结果、资源名的类别编码。

用法
----
    python3 scripts/m1_session_collector.py \
        --session-id norm-050hz-s03 --label normal \
        --label-basis "authorized 50 Hz publisher, no policy violation" \
        --topic /m1r/probe --duration 75 --window 30 --out out.json
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import time
from datetime import datetime, timezone

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy

#: 窗口内样本少于该值时不给统计结论
MIN_SAMPLES = 10

#: 允许的消息类型（研究用；避免任意 import）
MESSAGE_TYPES = {
    'std_msgs/msg/String': ('std_msgs.msg', 'String'),
    'std_msgs/msg/Int32': ('std_msgs.msg', 'Int32'),
    'std_msgs/msg/Empty': ('std_msgs.msg', 'Empty'),
}


def now_iso():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'


def resolve_type(name):
    if name not in MESSAGE_TYPES:
        raise SystemExit(f'unsupported message type: {name}')
    module_name, class_name = MESSAGE_TYPES[name]
    module = __import__(module_name, fromlist=[class_name])
    return getattr(module, class_name)


def percentile(values, pct):
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * (pct / 100.0)
    low = int(math.floor(rank))
    high = int(math.ceil(rank))
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


class SessionObserver(Node):
    """订阅一个话题，按固定窗口统计到达行为与图变化。"""

    def __init__(self, topic, msg_type, window_sec):
        super().__init__('m1_session_observer')
        self.topic = topic
        self.window_sec = window_sec
        self.arrivals = []
        self.publisher_ids = set()
        self.graph_changes = 0
        self.windows = []
        self.session_start = time.monotonic()
        self.window_start = self.session_start
        self.insufficient = 0

        qos = QoSProfile(depth=200,
                         reliability=ReliabilityPolicy.BEST_EFFORT,
                         history=HistoryPolicy.KEEP_LAST)
        self.subscription = self.create_subscription(
            msg_type, topic, self._on_message, qos)
        # 图变化：节点/话题增减都会触发；这是真实可观测的发现行为信号。
        self._graph_timer = self.create_timer(0.5, self._poll_graph)
        self._last_graph = self._graph_signature()

    def _graph_signature(self):
        try:
            return (tuple(sorted(self.get_node_names())),
                    tuple(sorted(self.get_topic_names_and_types())))
        except Exception:                                    # noqa: BLE001
            return ((), ())

    def _poll_graph(self):
        signature = self._graph_signature()
        if signature != self._last_graph:
            self.graph_changes += 1
            self._last_graph = signature

    def _on_message(self, _msg):
        stamp = time.monotonic()
        self.arrivals.append(stamp)
        try:
            info = self.get_publishers_info_by_topic(self.topic)
            for entry in info:
                self.publisher_ids.add((entry.node_name, entry.node_namespace))
        except Exception:                                    # noqa: BLE001
            pass
        while stamp - self.window_start >= self.window_sec:
            self._close_window(self.window_start + self.window_sec)

    def _close_window(self, end):
        start = self.window_start
        in_window = [t for t in self.arrivals if start <= t < end]
        self.arrivals = [t for t in self.arrivals if t >= end]
        record = {
            'window_start': round(start - self.session_start, 3),
            'window_end': round(end - self.session_start, 3),
            'features': {},
            'samples': len(in_window),
            'status': 'OK',
        }
        if len(in_window) < MIN_SAMPLES:
            record['status'] = 'INSUFFICIENT_OBSERVATION'
            self.insufficient += 1
            self.windows.append(record)
            self.window_start = end
            return
        gaps = [(in_window[i + 1] - in_window[i]) * 1000.0
                for i in range(len(in_window) - 1)]
        mean_gap = statistics.fmean(gaps) if gaps else 0.0
        record['features'] = {
            'message_count': len(in_window),
            'frequency_hz': round(len(in_window) / self.window_sec, 4),
            'gap_median_ms': round(statistics.median(gaps), 4) if gaps else None,
            'gap_p95_ms': round(percentile(gaps, 95), 4) if gaps else None,
            'gap_max_ms': round(max(gaps), 4) if gaps else None,
            'gap_cv': round(statistics.pstdev(gaps) / mean_gap, 4)
                       if gaps and mean_gap > 0 else None,
            'graph_change_count': self.graph_changes,
            'distinct_publishers': len(self.publisher_ids),
        }
        self.graph_changes = 0
        self.windows.append(record)
        self.window_start = end

    def flush(self):
        stamp = time.monotonic()
        while stamp - self.window_start >= self.window_sec:
            self._close_window(self.window_start + self.window_sec)


def main(argv=None):
    parser = argparse.ArgumentParser(description='M1 研究用多资源窗口观测器')
    parser.add_argument('--session-id', required=True)
    parser.add_argument('--label', required=True,
                        choices=['normal', 'anomaly'])
    parser.add_argument('--label-basis', required=True,
                        help='标签依据：必须描述实验事实，不能写模型预测')
    parser.add_argument('--scenario', required=True)
    parser.add_argument('--topic', required=True)
    parser.add_argument('--type', default='std_msgs/msg/String')
    parser.add_argument('--duration', type=float, default=75.0)
    parser.add_argument('--window', type=float, default=30.0)
    parser.add_argument('--domain', type=int, default=68)
    parser.add_argument('--out', required=True)
    args = parser.parse_args(argv)

    msg_type = resolve_type(args.type)
    rclpy.init()
    node = SessionObserver(args.topic, msg_type, args.window)
    started_at = now_iso()
    deadline = time.monotonic() + args.duration
    try:
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.1)
    finally:
        node.flush()
        ended_at = now_iso()
        document = {
            'contract': 'm1-session-observation/1',
            'session_id': args.session_id,
            'scenario': args.scenario,
            'label': args.label,
            'label_basis': args.label_basis,
            'label_source': 'EXPERIMENT_CONDITION',
            'model_used_for_labeling': False,
            'topic': args.topic,
            'message_type': args.type,
            'domain_id': args.domain,
            'window_sec': args.window,
            'window_policy': 'fixed, contiguous, non-overlapping',
            'started_at': started_at,
            'ended_at': ended_at,
            'min_samples': MIN_SAMPLES,
            'windows': node.windows,
            'insufficient_windows': node.insufficient,
            'collector': 'scripts/m1_session_collector.py',
        }
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, 'w', encoding='utf-8') as fh:
            json.dump(document, fh, ensure_ascii=False, indent=2)
        node.destroy_node()
        rclpy.shutdown()
    print(json.dumps({'session_id': args.session_id, 'label': args.label,
                      'windows': len(node.windows),
                      'insufficient': node.insufficient,
                      'out': args.out}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
