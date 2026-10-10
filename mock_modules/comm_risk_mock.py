#!/usr/bin/env python3
"""mock_modules/comm_risk_mock.py -- 通信行为可信分析的模拟实现。

用途
----
在真实通信行为分析模块尚未开发时，提供**可复现的接口占位**，
使适配层、进程协议与安全失败行为可以先行开发和测试。

**这不是安全算法，也不构成任何安全保证。**
所有输出都标记 `producer.source = MOCK` 且 `evidence_refs[].kind = MOCK`。

输入：一个 ModuleInputEnvelope（stdin）
输出：一个 CommRiskEvidence（stdout）

行为控制（测试用）
------------------
在输入信封的 `observations[].detail.f0_mock` 中给出：

    {"scenario": "normal" | "suspicious" | "unknown" | "error",
     "fault": "<协议层故障名>"}      # fault 需要 --allow-fault-injection

未给出 scenario 时默认 `normal`。
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _protocol import (  # noqa: E402
    EXIT_INPUT_ERROR, EXIT_OK, apply_fault_injection, candidate_target,
    apply_overrides, control_for, emit, epoch_now_iso, note, parse_args, read_input, require,
)

MODULE = 'comm_risk'
SCHEMA_VERSION = '1.0.0-proposed'
PRODUCER = {'name': 'comm_risk_mock', 'module_version': '0.1.0', 'source': 'MOCK'}
RESOURCE = '/rg/guarded_navigate'

STATUS_TABLE = {
    'normal': ('NORMAL', 'NONE', 'NONE', '窗口内请求数在基线范围内'),
    'suspicious': ('SUSPICIOUS', 'REQUEST_RATE_ANOMALY', 'HIGH',
                   '窗口内请求数显著高于基线，并存在重复调用特征'),
    'unknown': ('UNKNOWN', 'UNKNOWN', 'UNKNOWN',
                '观察样本不足，无法判定是否异常（不等于正常）'),
    'error': ('ERROR', 'UNKNOWN', 'UNKNOWN', '模块自身执行失败，未能形成判断'),
}


def build(envelope):
    control = control_for(envelope, MODULE)
    scenario = str(control.get('scenario', 'normal')).lower()
    if scenario in ('default', ''):
        scenario = 'normal'
    if scenario not in STATUS_TABLE:
        raise ValueError('未知场景: {0!r}（可选 {1}）'.format(
            scenario, sorted(STATUS_TABLE)))

    status, anomaly, risk, reason = STATUS_TABLE[scenario]
    target = candidate_target(envelope)
    # 请求数与频率随场景变化，使输出与场景真实相关
    request_count = {'normal': 3, 'suspicious': 120, 'unknown': 0, 'error': 0}[scenario]
    frequency = {'normal': 0.6, 'suspicious': 24.0, 'unknown': 0.0, 'error': 0.0}[scenario]

    document = {
        'schema_version': SCHEMA_VERSION,
        'run_id': require(envelope, 'run_id'),
        'request_id': require(envelope, 'request_id'),
        'event_id': 'evt-comm-{0}'.format(require(envelope, 'request_id')),
        'producer': dict(PRODUCER),
        'observed_at': epoch_now_iso(),
        'status': status,
        'reason': reason,
        'communication': {
            'resource': RESOURCE,
            'resource_type': 'Action',
            'operation': 'GOAL_SEND',
        },
        'window': {
            'start': '2026-10-10T12:00:00Z',
            'end': epoch_now_iso(),
            'duration_ms': 5000,
        },
        'request_count': request_count,
        'frequency_hz': frequency,
        'anomaly_category': anomaly,
        'risk_level': risk,
        'basis': [
            '场景 {0}：窗口内请求数 {1}'.format(scenario, request_count),
            '候选目标 ({0}, {1}) 坐标系 {2}'.format(target['x'], target['y'],
                                                     target['frame_id']),
        ],
        'evidence_refs': [{
            'ref': 'mock_modules/comm_risk_mock.py',
            'kind': 'MOCK',
            'note': '模拟结论，不构成真实安全保证，不得作为 DDS 认证依据',
        }],
    }
    return document, scenario


def main() -> int:
    args = parse_args('通信行为可信分析 Mock（模拟实现，无安全保证）')
    try:
        envelope = read_input()
    except ValueError as exc:
        note('输入解析失败: {0}'.format(exc))
        return EXIT_INPUT_ERROR

    control = control_for(envelope, MODULE)
    if apply_fault_injection(control.get('fault'), args.allow_fault_injection):
        return EXIT_OK

    try:
        document, scenario = build(envelope)
    except ValueError as exc:
        note('无法构造输出: {0}'.format(exc))
        return EXIT_INPUT_ERROR

    apply_overrides(document, control)
    note('场景={0} 状态={1}'.format(scenario, document['status']))
    emit(document)
    return EXIT_OK


if __name__ == '__main__':
    sys.exit(main())
