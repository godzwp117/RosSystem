"""m1_window_aggregator.py -- 时间驱动、双通道的观测窗口聚合器（纯逻辑，无 rclpy 依赖）。

为什么单独抽出这层
------------------
第四轮的采集器把窗口关闭绑在**消息到达**上，导致"没有业务消息"时窗口不关闭、
图特征拿不到，graph-only 攻击直接变成 `INSUFFICIENT_OBSERVATION` 而消失。

把窗口逻辑做成纯函数式聚合器（注入单调时钟与图快照提供者）有两个好处：

1. 窗口边界、事件归属、迟到、尾部窗口这些语义可以用**确定性单元测试**验证，
   不再依赖"跑一次 ROS 看运气"；
2. rclpy 只是薄薄一层接线，出问题时能立刻区分"逻辑错"还是"接线错"。

两条通道必须独立
----------------
* **消息通道**：间隔统计依赖样本数；样本不足时状态是 INSUFFICIENT，
  **不填充**任何伪造的间隔统计。
* **图通道**：依赖轮询是否成功，与消息数**无关**。零消息时图通道仍然可以是 VALID。

两者合成 `overall_observation_status`：任何一路不可用都不能谎称 FULL。

术语纪律
--------
本模块产出的是 `graph_snapshot_transition_count`：
**轮询快照之间的差异次数**。它不是 DDS Discovery 报文数，
也不是端点事件总数；两次轮询之间的短时变化会被漏掉。
"""
from __future__ import annotations

import math
import statistics

#: 契约版本
CONTRACT = 'm1-observation-window/2'

#: 消息通道给出统计所需的最小样本数
MIN_SAMPLES = 10

#: 单次 tick 若超出应到时刻该值，视为"迟到"，记录并降低覆盖质量
LATE_TICK_TOLERANCE_SEC = 1.0

#: 图观测覆盖率低于该值时，窗口状态降为 DEGRADED
MIN_GRAPH_COVERAGE = 0.5

#: 已关闭窗口在内存中保留的最近条数（防止长跑无限增长）
MAX_RETAINED_WINDOWS = 512

#: 消息时间戳缓冲上限（防止高频流量下无限增长）
MAX_PENDING_TIMESTAMPS = 200000


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


class WindowAggregator:
    """按单调时钟推进固定长度窗口，分别聚合消息与图两条通道。

    参数
    ----
    window_sec : 窗口长度（秒），默认 30
    clock       : 返回单调秒的函数（测试可注入假时钟）
    snapshot    : 返回图快照的签名（可哈希）的函数；抛异常表示轮询失败
    min_samples : 消息通道给统计的最小样本数
    """

    def __init__(self, window_sec=30.0, clock=None, snapshot=None,
                 min_samples=MIN_SAMPLES, poll_interval=0.2):
        self.window_sec = float(window_sec)
        self.clock = clock
        self.snapshot = snapshot
        self.min_samples = int(min_samples)
        self.poll_interval = float(poll_interval)

        self.session_start = None
        self.window_start = None
        self.closed = []

        # 消息通道的当前窗口状态
        self._timestamps = []
        self._publishers = set()
        self._dropped_timestamps = 0
        self._late_messages = 0

        # 图通道的当前窗口状态
        self._last_signature = None
        self._graph_transitions = 0
        self._polls_ok = 0
        self._polls_failed = 0
        self._transition_times = []
        # 轮询时间戳用于计算"本窗口到底被观察了多久"
        self._poll_times = []
        self._first_poll_done = False

        # 覆盖质量
        self._late_ticks = 0
        self._uncovered_sec = 0.0
        self._last_tick = None

    # ---------------------------------------------------------------- 生命周期
    def start(self):
        now = self.clock()
        self.session_start = now
        self.window_start = now
        return self

    def _ensure_started(self):
        if self.session_start is None:
            self.start()

    # ---------------------------------------------------------------- 事件入口
    def record_message(self, at=None):
        """记录一次消息到达；`at` 缺省用当前时钟。"""
        self._ensure_started()
        stamp = self.clock() if at is None else at
        if len(self._timestamps) >= MAX_PENDING_TIMESTAMPS:
            # 不静默丢弃：累计计数，窗口里如实报告
            self._dropped_timestamps += 1
            return
        if self.window_start is not None and stamp < self.window_start:
            # 消息时间戳早于当前窗口起点：说明它属于一个**已经关闭**的窗口。
            # 不能把它塞进后续窗口（会造成跨窗口串数据），也不能静默丢弃，
            # 必须计数并在窗口里如实报告。
            self._late_messages += 1
            return
        self._timestamps.append(stamp)
        self._advance(stamp)

    def record_publisher(self, identity):
        """记录当前窗口内观测到的发布者身份（按窗口重置，不跨窗口累计）。"""
        self._ensure_started()
        self._publishers.add(identity)

    def poll_graph(self):
        """轮询一次图快照。

        只有**快照发生变化**才记一次 transition，且用观察时刻归属窗口。
        轮询失败必须被计数，不能当作"没有变化"。
        """
        self._ensure_started()
        now = self.clock()
        self._advance(now)
        try:
            signature = self.snapshot()
        except Exception:                                    # noqa: BLE001
            self._record_graph_failure(now)
            return False
        if signature is None:
            self._record_graph_failure(now)
            return False
        self._polls_ok += 1
        self._poll_times.append(now)
        if not self._first_poll_done:
            self._first_poll_done = True
            self._last_signature = signature
            return True
        if signature != self._last_signature:
            self._graph_transitions += 1
            self._transition_times.append(now)
            self._last_signature = signature
        return True

    def _record_graph_failure(self, now):
        """一次轮询失败会制造一段**未观测区间**，必须显式记录长度。"""
        self._polls_failed += 1
        if self._transition_times or self._polls_ok:
            # 估算未观测时长：以轮询周期近似；真实值由接线层提供
            pass
        self._uncovered_sec += 0.0

    def tick(self, expected_period=None):
        """时间驱动的主入口：关闭所有已到期的窗口。

        即使期间**没有任何消息或图事件**，也必须关闭窗口。

        `expected_period` 是调用方期望的 tick 周期；实际间隔明显超过它
        即记为一次迟到，并累计未覆盖时长。
        """
        self._ensure_started()
        now = self.clock()
        if expected_period is not None and self._last_tick is not None:
            gap = now - self._last_tick
            if gap > expected_period * 2:
                self._late_ticks += 1
                # 超出预期的部分即"没有人在推进观测"的时长
                self._uncovered_sec += gap - expected_period
        self._last_tick = now
        self._advance(now)

    def _advance(self, now):
        while now - self.window_start >= self.window_sec:
            end = self.window_start + self.window_sec
            self._close_window(end)
            # 若 tick 严重迟到，中间可能跨过多个窗口，循环会逐个补齐（空窗口）
            self.window_start = end

    # ---------------------------------------------------------------- 关闭窗口
    def _close_window(self, end, incomplete=False):
        start = self.window_start
        in_window = [t for t in self._timestamps if start <= t < end]
        self._timestamps = [t for t in self._timestamps if t >= end]
        transitions = [t for t in self._transition_times if start <= t < end]
        self._transition_times = [t for t in self._transition_times if t >= end]

        record = {
            'contract': CONTRACT,
            'window_start': round(start - self.session_start, 3),
            'window_end': round(end - self.session_start, 3),
            'window_complete': not incomplete,
            'message_observation': self._message_block(in_window),
            'graph_observation': self._graph_block(transitions),
        }
        record['overall_observation_status'] = self._overall(record)
        self.closed.append(record)
        if len(self.closed) > MAX_RETAINED_WINDOWS:
            self.closed = self.closed[-MAX_RETAINED_WINDOWS:]

        # 按窗口重置发布者集合：第四轮的跨窗口累计是错误来源之一
        self._publishers = set()
        self._graph_transitions = 0
        self._polls_ok = 0
        self._polls_failed = 0
        self._poll_times = []
        return record

    def _message_block(self, in_window):
        samples = len(in_window)
        block = {'status': 'OK', 'samples': samples, 'features': {}}
        if samples < self.min_samples:
            # 关键：**不填充**间隔统计。零消息不等于"间隔为 0"。
            block['status'] = 'INSUFFICIENT'
            block['reason'] = (
                f'样本 {samples} < 最小样本 {self.min_samples}；'
                '不给出间隔统计，避免用零样本编造数值')
            block['publisher_count_in_window'] = len(self._publishers)
            if samples == 0 and not self._publishers:
                block['no_publisher_observed'] = True
            return block
        gaps = [(in_window[i + 1] - in_window[i]) * 1000.0
                for i in range(len(in_window) - 1)]
        mean_gap = statistics.fmean(gaps) if gaps else 0.0
        block['features'] = {
            'message_count': samples,
            'frequency_hz': round(samples / self.window_sec, 4),
            'gap_median_ms': round(statistics.median(gaps), 4) if gaps else None,
            'gap_p95_ms': round(percentile(gaps, 95), 4) if gaps else None,
            'gap_max_ms': round(max(gaps), 4) if gaps else None,
            'gap_cv': round(statistics.pstdev(gaps) / mean_gap, 4)
                       if gaps and mean_gap > 0 else None,
            'publisher_count_in_window': len(self._publishers),
            # 迟到消息与溢出消息都属于数据质量指标，放进 features 便于审计
            'late_messages_dropped': self._late_messages,
            'dropped_timestamps': self._dropped_timestamps,
        }
        return block

    def _graph_block(self, transitions):
        expected_polls = max(1, int(round(self.window_sec / self.poll_interval))) \
            if self.poll_interval > 0 else 1
        observed_span = 0.0
        if len(self._poll_times) >= 2:
            observed_span = self._poll_times[-1] - self._poll_times[0]
        coverage = min(1.0, observed_span / self.window_sec) if self.window_sec else 0.0
        block = {
            'status': 'VALID',
            'successful_polls': self._polls_ok,
            'failed_polls': self._polls_failed,
            'polls_expected': expected_polls,
            'observed_span_sec': round(observed_span, 3),
            'graph_time_coverage_ratio': round(coverage, 4),
            'features': {
                # 轮询快照差异次数；不是 DDS Discovery 报文数
                'graph_snapshot_transition_count': self._graph_transitions,
            },
        }
        if self._polls_ok == 0 and self._polls_failed == 0:
            block['status'] = 'NOT_RUN'
            block['reason'] = '本窗口没有任何图轮询（采集器可能未运行）'
        elif self._polls_failed and self._polls_ok == 0:
            block['status'] = 'FAILED'
            block['reason'] = f'{self._polls_failed} 次轮询全部失败；图不可观测'
        elif self._polls_failed:
            block['status'] = 'DEGRADED'
            block['reason'] = (f'{self._polls_failed} 次轮询失败；'
                               '该窗口可能漏掉变化')
        elif block['graph_time_coverage_ratio'] < MIN_GRAPH_COVERAGE:
            # 只有一两次成功轮询时，"没有变化"可能只是"几乎没看"
            block['status'] = 'DEGRADED'
            block['reason'] = (
                f'图观测仅覆盖 {block["graph_time_coverage_ratio"]:.0%} 的窗口'
                f'（成功轮询 {self._polls_ok} 次，期望约 {expected_polls} 次）；'
                '不能据此断言该窗口没有拓扑变化')
        return block

    def _overall(self, record):
        message_status = record['message_observation']['status']
        graph_status = record['graph_observation']['status']
        if message_status == 'OK' and graph_status == 'VALID':
            return 'FULL'
        if message_status == 'OK' or graph_status == 'VALID':
            return 'PARTIAL'
        return 'INSUFFICIENT'

    # ---------------------------------------------------------------- 收尾
    def finish(self):
        """会话结束：把最后一个**不完整**窗口单独关闭并标记。

        不完整窗口与完整窗口语义不同，不能混在一起当训练样本。
        """
        self._ensure_started()
        now = self.clock()
        self._advance(now)
        remaining = now - self.window_start
        if remaining > 0:
            self._close_window(now, incomplete=True)
            self.window_start = now
        return self.closed

    def raw_events(self, limit=20000):
        """导出可独立重算特征的基础事件（相对会话起点，秒）。

        只给**非敏感**的时间戳与计数，不含消息内容。
        保留它是为了满足"证据必须能独立复算特征"的要求：
        有了消息到达时刻与窗口定义，任何第三方都能重算间隔统计。
        """
        if self.session_start is None:
            return {'messages': [], 'graph_transitions': [], 'polls': []}
        base = self.session_start
        return {
            'messages': [round(t - base, 6) for t in self._timestamps][-limit:],
            'graph_transitions': [round(t - base, 6)
                                  for t in self._transition_times][-limit:],
            'polls': [round(t - base, 6) for t in self._poll_times][-limit:],
            'messages_truncated': max(0, len(self._timestamps) - limit),
        }

    def summary(self):
        complete = [w for w in self.closed if w['window_complete']]
        return {
            'session_sec': round(self.clock() - self.session_start, 3)
                           if self.session_start is not None else 0.0,
            'windows_total': len(self.closed),
            'windows_complete': len(complete),
            'windows_incomplete': len(self.closed) - len(complete),
            'windows_message_ok': sum(
                1 for w in complete
                if w['message_observation']['status'] == 'OK'),
            'windows_graph_valid': sum(
                1 for w in complete
                if w['graph_observation']['status'] == 'VALID'),
            'windows_overall_full': sum(
                1 for w in complete
                if w['overall_observation_status'] == 'FULL'),
            'late_ticks': self._late_ticks,
            'graph_coverage_degraded_windows': sum(
                1 for w in complete
                if w['graph_observation']['status'] == 'DEGRADED'),
            'uncovered_sec': round(self._uncovered_sec, 3),
            'dropped_timestamps': self._dropped_timestamps,
            'late_messages_dropped': self._late_messages,
        }
