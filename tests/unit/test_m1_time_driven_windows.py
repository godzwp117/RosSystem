"""G1 时间驱动窗口与双通道观测的确定性单元测试。

这些测试用**注入的假时钟与假快照**验证窗口语义，不依赖真实 ROS 2：
窗口边界、事件归属、零消息窗口、轮询失败、发布者去重、尾部窗口、
多次到期窗口连续关闭、以及内存有界性，都必须在这里被钉死。
真实 ROS 2 复验另见 G2 实验证据。
"""
from __future__ import annotations

import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

from modules.member1_comm.research.window_aggregator import (  # noqa: E402
    CONTRACT, MAX_PENDING_TIMESTAMPS, MIN_SAMPLES, WindowAggregator)


class FakeClock:
    def __init__(self, start=0.0):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def make(window=30.0, snapshot=None):
    clock = FakeClock()
    agg = WindowAggregator(window_sec=window, clock=clock,
                           snapshot=snapshot or (lambda: ('stable',)))
    agg.start()
    return agg, clock


# ---------------------------------------------------------------- 窗口推进
def test_window_contract_version():
    agg, _clock = make()
    clock = _clock
    clock.advance(31)
    agg.tick()
    assert agg.closed[0]['contract'] == CONTRACT


def test_zero_messages_still_closes_window():
    """G1 核心修复：没有业务消息也必须关闭窗口。"""
    agg, clock = make()
    clock.advance(30.0)
    agg.tick()
    assert len(agg.closed) == 1
    window = agg.closed[0]
    assert window['message_observation']['status'] == 'INSUFFICIENT'
    assert window['message_observation']['samples'] == 0
    # 关键：不足时**不得**出现伪造的间隔统计
    assert window['message_observation']['features'] == {}


def test_zero_messages_with_graph_change_keeps_graph_features():
    """零消息 + 有图变化：图通道仍必须给出有效特征。"""
    state = {'sig': 'a'}
    agg, clock = make(snapshot=lambda: state['sig'])
    agg.poll_graph()
    state['sig'] = 'b'
    clock.advance(5)
    agg.poll_graph()
    state['sig'] = 'c'
    clock.advance(5)
    agg.poll_graph()
    clock.advance(25)
    agg.tick()
    window = agg.closed[0]
    assert window['graph_observation']['status'] == 'VALID'
    assert window['graph_observation']['features'][
        'graph_snapshot_transition_count'] == 2
    assert window['message_observation']['status'] == 'INSUFFICIENT'
    # 两路合成：图有效但消息不足 -> PARTIAL，不能谎称 FULL
    assert window['overall_observation_status'] == 'PARTIAL'


def test_one_to_nine_messages_is_insufficient_not_fabricated():
    agg, clock = make()
    for i in range(9):
        clock.advance(1.0)
        agg.record_message()
    clock.advance(30)
    agg.tick()
    message = agg.closed[0]['message_observation']
    assert message['status'] == 'INSUFFICIENT'
    assert message['samples'] == 9
    assert message['features'] == {}


def test_ten_messages_produce_statistics():
    agg, clock = make()
    for _ in range(10):
        clock.advance(1.0)
        agg.record_message()
    clock.advance(30)
    agg.tick()
    features = agg.closed[0]['message_observation']['features']
    assert features['message_count'] >= MIN_SAMPLES
    assert features['gap_median_ms'] is not None


def test_boundary_message_belongs_to_exactly_one_window():
    """左闭右开：恰好落在边界上的消息只归属后一个窗口。"""
    agg, clock = make()
    agg.record_message(at=0.0)     # 窗口 0
    agg.record_message(at=29.999)  # 窗口 0
    agg.record_message(at=30.0)    # 恰好边界 -> 窗口 1
    clock.advance(60)
    agg.tick()
    first, second = agg.closed[0], agg.closed[1]
    assert first['message_observation']['samples'] == 2
    assert second['window_start'] == 30.0


def test_late_message_is_counted_not_silently_kept():
    """窗口关闭后才到的旧时间戳消息：必须计数并丢弃，不能串到后续窗口。"""
    agg, clock = make()
    clock.advance(30.0)
    agg.tick()                     # 窗口 0 关闭
    agg.record_message(at=5.0)     # 属于已关闭窗口
    for _ in range(12):
        clock.advance(1.0)
        agg.record_message()
    clock.advance(30)
    agg.tick()
    window = agg.closed[1]
    assert window['message_observation']['features']['late_messages_dropped'] >= 1
    assert window['message_observation']['samples'] == 12


def test_multiple_expired_windows_closed_in_sequence():
    """tick 迟到时，中间跨过的窗口必须逐个补齐，不能丢失或合并。"""
    agg, clock = make()
    clock.advance(95.0)
    agg.tick()
    assert len(agg.closed) == 3
    starts = [w['window_start'] for w in agg.closed]
    assert starts == [0.0, 30.0, 60.0]
    for window in agg.closed:
        assert window['window_end'] - window['window_start'] == 30.0


def test_windows_are_contiguous_and_non_overlapping():
    agg, clock = make()
    for _ in range(90):
        clock.advance(1.0)
        agg.record_message()
        agg.tick()
    agg.finish()
    complete = [w for w in agg.closed if w['window_complete']]
    for left, right in zip(complete, complete[1:]):
        assert left['window_end'] == right['window_start']


def test_graph_event_attributed_by_observation_time():
    """图变化按**观察时刻**归属窗口，不借用消息到达时间。"""
    state = {'sig': 'a'}
    agg, clock = make(snapshot=lambda: state['sig'])
    agg.poll_graph()                # 窗口 0，建立基线（不计变化）
    clock.advance(31.0)
    agg.poll_graph()                # 这一步会先推进窗口到窗口 1
    state['sig'] = 'b'
    clock.advance(2.0)
    agg.poll_graph()                # 变化发生在窗口 1
    clock.advance(30.0)
    agg.tick()
    # 窗口 0 建立基线，变化不应被算到窗口 0
    assert agg.closed[0]['graph_observation']['features'][
        'graph_snapshot_transition_count'] == 0
    assert agg.closed[1]['graph_observation']['features'][
        'graph_snapshot_transition_count'] == 1


# ---------------------------------------------------------------- 失败与降级
def test_graph_poll_failure_is_reported_not_treated_as_no_change():
    def boom():
        raise RuntimeError('graph unavailable')

    agg, clock = make(snapshot=boom)
    for _ in range(3):
        agg.poll_graph()
        clock.advance(1.0)
    clock.advance(30.0)
    agg.tick()
    graph = agg.closed[0]['graph_observation']
    assert graph['status'] in ('FAILED', 'DEGRADED')
    assert graph['failed_polls'] == 3
    assert graph['successful_polls'] == 0


def test_no_graph_polls_marks_not_run():
    agg, clock = make()
    clock.advance(30.0)
    agg.tick()
    assert agg.closed[0]['graph_observation']['status'] == 'NOT_RUN'


def test_partial_poll_failure_degrades_but_keeps_counting():
    state = {'fail': False, 'sig': 'a'}

    def snapshot():
        if state['fail']:
            raise RuntimeError('flaky')
        return state['sig']

    agg, clock = make(snapshot=snapshot)
    agg.poll_graph()
    state['sig'] = 'b'
    clock.advance(5)
    agg.poll_graph()
    state['fail'] = True
    clock.advance(5)
    agg.poll_graph()
    clock.advance(25)
    agg.tick()
    graph = agg.closed[0]['graph_observation']
    assert graph['status'] == 'DEGRADED'
    assert graph['successful_polls'] == 2
    assert graph['failed_polls'] == 1
    assert graph['features']['graph_snapshot_transition_count'] == 1


# ---------------------------------------------------------------- 发布者去重
def test_publisher_set_is_per_window_not_cumulative():
    """第四轮的跨窗口累计是错误来源，这里钉死按窗口重置。"""
    agg, clock = make()
    agg.record_publisher('node_a')
    for _ in range(12):
        clock.advance(2.0)          # 0 -> 24
        agg.record_message()
    clock.advance(6)                # -> 30，窗口 0 到期
    agg.tick()
    first = agg.closed[0]['message_observation']['features'][
        'publisher_count_in_window']
    assert first == 1

    # 第二个窗口：同样有消息，但**没有**再出现发布者
    for _ in range(12):
        clock.advance(2.0)          # -> 54
        agg.record_message()
    clock.advance(6)                # -> 60，窗口 1 到期
    agg.tick()
    second = agg.closed[1]['message_observation']['features'][
        'publisher_count_in_window']
    assert second == 0, '第二个窗口没有再出现发布者，不能沿用上一窗口的集合'


# ---------------------------------------------------------------- 尾部窗口
def test_finish_marks_trailing_window_incomplete():
    agg, clock = make()
    for _ in range(12):
        clock.advance(2.0)
        agg.record_message()
    clock.advance(10)
    agg.finish()
    complete = [w for w in agg.closed if w['window_complete']]
    incomplete = [w for w in agg.closed if not w['window_complete']]
    assert len(complete) == 1
    assert len(incomplete) == 1
    assert incomplete[0]['window_end'] - incomplete[0]['window_start'] < 30.0


def test_finish_without_partial_does_not_create_empty_window():
    agg, clock = make()
    clock.advance(60.0)
    agg.finish()
    assert all(w['window_complete'] for w in agg.closed)
    assert len(agg.closed) == 2


# ---------------------------------------------------------------- 资源有界
def test_high_rate_messages_bounded_memory():
    """高频下时间戳缓冲必须有上限，不能无限增长。"""
    agg, clock = make()
    for _ in range(MAX_PENDING_TIMESTAMPS + 500):
        agg.record_message(at=0.0)
    clock.advance(30)
    agg.tick()
    window = agg.closed[0]
    assert len(agg._timestamps) == 0
    dropped = window['message_observation'].get('dropped_timestamps')
    assert dropped is None or dropped > 0


def test_session_summary_counts_channels():
    agg, clock = make()
    agg.poll_graph()
    for _ in range(12):
        clock.advance(2.0)
        agg.record_message()
        agg.poll_graph()
    clock.advance(10)
    agg.finish()
    summary = agg.summary()
    assert summary['windows_total'] >= 1
    assert summary['windows_message_ok'] >= 1
    assert summary['windows_graph_valid'] >= 1


# ---------------------------------------------------------------- 组合语义
@pytest.mark.parametrize('messages,graph_ok,expected', [
    (0, False, 'INSUFFICIENT'),
    (0, True, 'PARTIAL'),
    (12, False, 'PARTIAL'),
    (12, True, 'FULL'),
])
def test_overall_status_matrix(messages, graph_ok, expected):
    state = {'sig': 'a', 'fail': False}

    def snapshot():
        if state['fail']:
            raise RuntimeError('down')
        return state['sig']

    agg, clock = make(snapshot=snapshot)
    if not graph_ok:
        state['fail'] = True
    agg.poll_graph()
    for _ in range(messages):
        clock.advance(1.0)
        agg.record_message()
    clock.advance(30)
    agg.tick()
    assert agg.closed[0]['overall_observation_status'] == expected
