#!/usr/bin/env python3
"""m1_graph_collector.py -- 时间驱动 + 消息/图双通道的真实 ROS 2 采集器（G1/G2/G3）。

与第四轮采集器的差别
====================
第四轮：窗口由**消息到达**推进 → 没有消息就没有窗口 → graph-only 攻击消失。
本轮：窗口由**时间**推进（`/m1_tick` 定时器 + 单调时钟），
      即使一条消息都没有，窗口照样关闭并输出图特征。

两条通道各自独立判定有效性
--------------------------
* `message_observation.status`：`OK` / `INSUFFICIENT`（样本 < MIN_SAMPLES）
* `graph_observation.status`：`VALID` / `DEGRADED` / `FAILED` / `NOT_RUN`

零消息**不等于**图观测无效；图有效也**不等于**整体风险已分析充分
（合成状态 `overall_observation_status`）。

术语纪律
--------
产出的是 `graph_snapshot_transition_count`（轮询快照差异次数），
不是 DDS Discovery 报文数。两次轮询之间的短时变化会被漏掉 ——
这属于已知盲区，由 G2 的漏采实验量化。

标签纪律
--------
本脚本**不产生标签**，也不知道标签；标签由驱动方按实验条件写入。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import rclpy  # noqa: E402
from rclpy.node import Node  # noqa: E402
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy  # noqa: E402

from modules.member1_comm.research.window_aggregator import (  # noqa: E402
    MIN_SAMPLES, WindowAggregator)

MESSAGE_TYPES = {
    'std_msgs/msg/String': ('std_msgs.msg', 'String'),
    'std_msgs/msg/Int32': ('std_msgs.msg', 'Int32'),
}


def now_iso():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'


def resolve_type(name):
    module_name, class_name = MESSAGE_TYPES[name]
    module = __import__(module_name, fromlist=[class_name])
    return getattr(module, class_name)


class GraphCollector(Node):
    def __init__(self, args):
        super().__init__('m1_graph_collector')
        self.aggregator = WindowAggregator(
            window_sec=args.window, clock=time.monotonic,
            snapshot=self._snapshot, min_samples=MIN_SAMPLES).start()
        self.args = args
        self._poll_interval = args.poll_interval
        self._last_poll = 0.0
        self._tick_lateness = []

        qos = QoSProfile(depth=200,
                         reliability=ReliabilityPolicy.BEST_EFFORT,
                         history=HistoryPolicy.KEEP_LAST)
        msg_type = resolve_type(args.type)
        self.subscription = self.create_subscription(
            msg_type, args.topic, self._on_message, qos)
        # 时间驱动：即使没有任何消息，这个定时器也会推进窗口
        self.create_timer(0.05, self._on_tick)

    def _snapshot(self):
        """图快照签名。查询失败会抛异常，由聚合器计为失败轮询。"""
        nodes = tuple(sorted(self.get_node_names()))
        topics = tuple(sorted(self.get_topic_names_and_types()))
        services = tuple(sorted(self.get_service_names_and_types()))
        return (nodes, topics, services)

    def _on_tick(self):
        started = time.monotonic()
        # 图轮询按自身周期进行，与消息流无关
        if started - self._last_poll >= self._poll_interval:
            self._last_poll = started
            self.aggregator.poll_graph()
            try:
                for info in self.get_publishers_info_by_topic(self.args.topic):
                    self.aggregator.record_publisher(
                        (info.node_name, info.node_namespace))
            except Exception:                                # noqa: BLE001
                pass
        self.aggregator.tick()
        elapsed = time.monotonic() - started
        if elapsed > self._poll_interval * 2:
            self._tick_lateness.append(round(elapsed, 4))

    def _on_message(self, _msg):
        self.aggregator.record_message()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--session-id', required=True)
    parser.add_argument('--scenario', required=True)
    parser.add_argument('--label', required=True, choices=['normal', 'anomaly'])
    parser.add_argument('--label-basis', required=True)
    parser.add_argument('--topic', required=True)
    parser.add_argument('--type', default='std_msgs/msg/String')
    parser.add_argument('--duration', type=float, default=65.0)
    parser.add_argument('--window', type=float, default=30.0)
    parser.add_argument('--poll-interval', type=float, default=0.2)
    parser.add_argument('--domain', type=int, default=69)
    parser.add_argument('--out', required=True)
    args = parser.parse_args(argv)

    rclpy.init()
    node = GraphCollector(args)
    started_at = now_iso()
    deadline = time.monotonic() + args.duration
    try:
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.02)
    finally:
        node.aggregator.finish()
        ended_at = now_iso()
        windows = node.aggregator.closed
        document = {
            'contract': 'm1-graph-session/1',
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
            'window_policy': 'time-driven, fixed, contiguous, non-overlapping',
            'graph_poll_interval_sec': args.poll_interval,
            'graph_feature_semantics': (
                'graph_snapshot_transition_count = 相邻轮询快照的差异次数；'
                '不是 DDS Discovery 报文数，两次轮询之间的短时变化会被漏掉'),
            'started_at': started_at,
            'ended_at': ended_at,
            'min_samples': MIN_SAMPLES,
            'windows': windows,
            'summary': node.aggregator.summary(),
            'tick_lateness_samples': node._tick_lateness[:20],
            'collector': 'scripts/m1_graph_collector.py',
        }
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, 'w', encoding='utf-8') as fh:
            json.dump(document, fh, ensure_ascii=False, indent=2)
        node.destroy_node()
        rclpy.shutdown()
    summary = document['summary'] if 'document' in dir() else {}
    print(json.dumps({'session_id': args.session_id,
                      'label': args.label,
                      'windows': summary.get('windows_total'),
                      'message_ok': summary.get('windows_message_ok'),
                      'graph_valid': summary.get('windows_graph_valid'),
                      'out': args.out}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
