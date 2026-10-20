#!/usr/bin/env python3
"""通信风险**测试替身**：按数值规则真实计算风险状态。

与 mock_modules/comm_risk_mock.py 的本质区别
--------------------------------------------
Mock 是**场景开关**：输入说 `scenario=suspicious` 就输出 SUSPICIOUS。
本替身是**规则计算**：读取输入中真实的观察数值
（`observations[].detail.comm.request_count` / `baseline_count`），
按阈值规则自行算出状态。不同输入必须得到不同输出。

它仍然是测试件，不是安全算法：`producer.source = MOCK`，
`producer.name = comm_risk_double`（与 Mock 不同，便于证明实际加载的是替身）。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), 'mock_modules'))

from _protocol import (  # noqa: E402
    EXIT_INPUT_ERROR, EXIT_OK, emit, epoch_now_iso, note, parse_args, read_input,
    require,
)

SCHEMA_VERSION = '1.0.0-proposed'
PRODUCER = {'name': 'comm_risk_double', 'module_version': '0.1.0', 'source': 'MOCK'}
RESOURCE = '/rg/guarded_navigate'
ANOMALY_RATIO = 5.0      # 超过基线的倍数即判定异常
SUSPICIOUS_RATIO = 2.0   # 超过该倍数即判定可疑


def observe(envelope):
    """从输入中取出通信观察数值（替身真实读取输入，而非读场景开关）。"""
    for observation in envelope.get('observations', []) or []:
        if not isinstance(observation, dict):
            continue
        detail = observation.get('detail')
        if isinstance(detail, dict) and isinstance(detail.get('comm'), dict):
            return detail['comm']
    return {}


def decide(count, baseline):
    if baseline <= 0:
        return ('UNKNOWN', 'UNKNOWN', 'UNKNOWN', '基线数据不可用，无法比较')
    ratio = float(count) / float(baseline)
    if ratio > ANOMALY_RATIO:
        return ('SUSPICIOUS', 'REQUEST_RATE_ANOMALY', 'HIGH',
                '请求数 {0} 为基线 {1} 的 {2:.1f} 倍'.format(count, baseline, ratio))
    if ratio > SUSPICIOUS_RATIO:
        return ('SUSPICIOUS', 'REQUEST_RATE_ANOMALY', 'MEDIUM',
                '请求数 {0} 为基线 {1} 的 {2:.1f} 倍'.format(count, baseline, ratio))
    return ('NORMAL', 'NONE', 'NONE',
            '请求数 {0} 未超过基线 {1} 的 {2:.1f} 倍'.format(count, baseline, ratio))


def main() -> int:
    parse_args('通信风险测试替身（规则计算，非安全算法）')
    try:
        envelope = read_input()
    except ValueError as exc:
        note('输入解析失败: {0}'.format(exc))
        return EXIT_INPUT_ERROR

    comm = observe(envelope)
    count = comm.get('request_count')
    baseline = comm.get('baseline_count')
    if count is None or baseline is None:
        note('缺少 comm.request_count / comm.baseline_count，无法计算')
        return EXIT_INPUT_ERROR
    if comm.get('fail'):
        note('按输入要求模拟替身自身失败')
        return EXIT_INPUT_ERROR

    status, anomaly, risk, reason = decide(count, baseline)
    document = {
        'schema_version': SCHEMA_VERSION,
        'run_id': require(envelope, 'run_id'),
        'request_id': require(envelope, 'request_id'),
        'event_id': 'evt-comm-double-{0}'.format(require(envelope, 'request_id')),
        'producer': dict(PRODUCER),
        'observed_at': epoch_now_iso(),
        'status': status,
        'reason': reason,
        'communication': {'resource': RESOURCE, 'resource_type': 'Action',
                          'operation': 'GOAL_SEND'},
        'window': {'start': '2026-10-10T12:00:00Z', 'end': epoch_now_iso(),
                   'duration_ms': 5000},
        'request_count': int(count),
        'anomaly_category': anomaly,
        'risk_level': risk,
        'basis': ['阈值规则：>5.0 倍异常，>2.0 倍可疑', reason],
        'evidence_refs': [{'ref': 'tests/fixtures/team_modules/comm_risk_double.py',
                           'kind': 'MOCK',
                           'note': '测试替身结论，不构成真实安全保证'}],
    }
    note('替身规则：count={0} baseline={1} -> {2}'.format(count, baseline, status))
    emit(document)
    return EXIT_OK


if __name__ == '__main__':
    sys.exit(main())
