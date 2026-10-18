#!/usr/bin/env python3
"""ros2_window.py -- 从真实 ROS 2 通信测量窗口特征（专项② P1）。

它解决什么问题
--------------
窗口级模型要用的特征（窗口内消息数、频率、到达间隔中位数/p95/最大值、窗口时长）
必须**从真实 ROS 2 通信事件**测出来，不能由实验算子在 JSON 里自报。
本脚本用 rclpy 真实订阅一个话题，按实际到达时间戳计算这些量，并把结果交给
M1 的纯数值推理器打分。

与训练特征的语义对齐
--------------------
训练数据（windows_0.jsonl）的字段定义：

    request_count  窗口内该资源上的消息数
    frequency_hz   request_count / 窗口秒数
    gap_*_ms       相邻消息间隔的统计量
    duration_ms    窗口时长

本脚本用同样的定义计算，并在输出里显式写出 `feature_semantics` 与
`observation_source`，避免"字段名相同就推定等价"。

不可自证的原则
--------------
* `request_count` 只来自**本进程实际收到的消息**，不接受命令行/信封传入；
* 采集器输出带 `collected_at`、`topic`、`message_type`、`samples`；
* 若窗口内样本过少（< MIN_SAMPLES），输出 `INSUFFICIENT_OBSERVATION` 而**不是**
  编一个数出来。

用法
----
    python3 modules/member1_comm/collector/ros2_window.py \
        --topic /m1_probe/tick --type std_msgs/msg/String \
        --duration 6 --interval 0.5 --out window.json

    # 只采集不打分
    ... --no-score
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from datetime import datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

#: 少于这个样本数就不给结论：窗口统计在极稀疏样本上没有意义。
MIN_SAMPLES = 8


def now_iso():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def percentile(values, fraction):
    """线性插值分位数（与 numpy 默认一致，便于和训练侧对齐）。"""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def summarise(timestamps, started_at, ended_at):
    """把到达时间戳转成与训练侧同定义的窗口特征。"""
    count = len(timestamps)
    duration_s = max(ended_at - started_at, 1e-9)
    gaps_ms = [(b - a) * 1000.0 for a, b in zip(timestamps, timestamps[1:])]
    return {
        'request_count': count,
        'duration_ms': round(duration_s * 1000.0, 3),
        'frequency_hz': round(count / duration_s, 6),
        'gap_median_ms': round(percentile(gaps_ms, 0.5), 4) if gaps_ms else None,
        'gap_p95_ms': round(percentile(gaps_ms, 0.95), 4) if gaps_ms else None,
        'gap_max_ms': round(max(gaps_ms), 4) if gaps_ms else None,
    }


def collect(topic, message_type, duration, interval):
    """真实订阅并采集。返回 (windows, meta)。"""
    import rclpy
    from rclpy.node import Node
    from rosidl_runtime_py.utilities import get_message

    rclpy.init()
    node = Node('m1_window_collector')
    msg_class = get_message(message_type)
    arrivals = []
    subscription = node.create_subscription(
        msg_class, topic, lambda msg: arrivals.append(time.monotonic()), 200)

    windows = []
    started = time.monotonic()
    window_start = started
    while True:
        rclpy.spin_once(node, timeout_sec=0.05)
        current = time.monotonic()
        if current - window_start >= interval:
            stamp = [t for t in arrivals if t >= window_start]
            windows.append({
                'window_start_monotonic': round(window_start, 6),
                'window_end_monotonic': round(current, 6),
                'features': summarise(stamp, window_start, current),
                'samples': len(stamp),
            })
            # 只保留本窗口之后的到达，避免跨窗口重复计数
            arrivals[:] = [t for t in arrivals if t >= current]
            window_start = current
        if current - started >= duration:
            break

    node.destroy_subscription(subscription)
    node.destroy_node()
    rclpy.shutdown()
    meta = {'topic': topic, 'message_type': message_type,
            'duration_sec': duration, 'interval_sec': interval,
            'total_messages': sum(w['samples'] for w in windows)}
    return windows, meta


def score_with_model(features, model_path, features_path=None):
    """用导出的纯数值模型打分，公式与 modules/member1_comm/module.py 完全一致：

        x_i = (sign(v) * log1p(|v|) - mean_i) / scale_i
        z   = sum(w_i * x_i) + intercept
        p   = sigmoid(z)

    这里刻意**不复用** module.py 的内部函数：采集器要能在只装了 rclpy 的
    容器里独立运行（容器内不一定有模块目录的导入路径），而公式只有三行，
    直接实现反而更容易逐字核对。两者的一致性由导出脚本的
    numeric_consistency 校验（容差 1e-9）保证。
    """
    model = json.load(open(model_path, encoding='utf-8'))
    names = model['feature_names']
    raw = []
    for i, name in enumerate(names):
        value = features.get(name)
        if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            value = model['impute'][i]
        raw.append(float(value))
    total = 0.0
    for i, value in enumerate(raw):
        transformed = math.copysign(math.log1p(abs(value)), value)
        normalised = (transformed - model['mean'][i]) / model['scale'][i]
        total += normalised * model['weights'][i]
    total += model['intercept']
    return 1.0 / (1.0 + math.exp(-max(-700.0, min(700.0, total))))


def main(argv=None):
    parser = argparse.ArgumentParser(description='从真实 ROS 2 通信测量窗口特征')
    parser.add_argument('--topic', required=True)
    parser.add_argument('--type', dest='message_type', required=True,
                        help='例如 std_msgs/msg/String')
    parser.add_argument('--duration', type=float, default=6.0)
    parser.add_argument('--interval', type=float, default=0.5)
    parser.add_argument('--out', required=True)
    parser.add_argument('--no-score', action='store_true')
    parser.add_argument('--model', default=None)
    parser.add_argument('--features', default=None)
    args = parser.parse_args(argv)

    windows, meta = collect(args.topic, args.message_type, args.duration,
                            args.interval)
    document = {
        'schema_version': '1.0.0-proposed',
        'collected_at': now_iso(),
        'collector': {
            'component': 'modules/member1_comm/collector/ros2_window.py',
            'observation_source': 'LIVE_ROS2_SUBSCRIPTION',
            'topic': meta['topic'],
            'message_type': meta['message_type'],
            'count_definition': ('本进程在该窗口内实际收到的消息数'
                                 '（不由命令行或信封提供）'),
            'duration_sec': meta['duration_sec'],
            'interval_sec': meta['interval_sec'],
            'total_messages': meta['total_messages'],
        },
        'feature_semantics': {
            'request_count': '窗口内消息数',
            'frequency_hz': 'request_count / 窗口秒数',
            'gap_median_ms': '相邻消息到达间隔的中位数（毫秒）',
            'gap_p95_ms': '相邻消息到达间隔的 95 分位（毫秒）',
            'gap_max_ms': '相邻消息到达间隔的最大值（毫秒）',
            'duration_ms': '窗口时长（毫秒）',
            'alignment_note': ('与训练集 windows_0.jsonl 同名同定义；'
                               '训练集来自 PCAP 侧统计，本采集器来自 ROS 2 订阅侧，'
                               '二者在"同一资源、同一时间窗"意义下语义等价，'
                               '但采样位置不同，数值不保证逐点相同。'),
        },
        'windows': windows,
        'verdict': None,
    }

    insufficient = [w for w in windows if w['samples'] < MIN_SAMPLES]
    if len(insufficient) == len(windows):
        document['verdict'] = {'status': 'INSUFFICIENT_OBSERVATION',
                               'reason': f'所有窗口样本数均 < {MIN_SAMPLES}，'
                                         '拒绝据此给出风险结论'}
    elif not args.no_score and args.model:
        scores = []
        for window in windows:
            if window['samples'] < MIN_SAMPLES:
                continue
            try:
                scores.append(float(score_with_model(window['features'],
                                                     args.model)))
            except Exception as exc:                        # noqa: BLE001
                document['verdict'] = {'status': 'SCORE_FAILED',
                                       'reason': str(exc)[:200]}
                break
        if scores and document['verdict'] is None:
            document['verdict'] = {'status': 'SCORED',
                                   'windows_scored': len(scores),
                                   'score_max': round(max(scores), 6),
                                   'score_mean': round(sum(scores) / len(scores), 6),
                                   'score_min': round(min(scores), 6)}

    with open(args.out, 'w', encoding='utf-8') as fh:
        json.dump(document, fh, ensure_ascii=False, indent=2)
    print(json.dumps({'out': args.out, 'windows': len(windows),
                      'total_messages': meta['total_messages'],
                      'verdict': document['verdict']}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
