#!/usr/bin/env python3
"""mock_modules/identity_trust_mock.py -- DDS 身份与资源访问安全的模拟实现。

用途
----
在真实身份与权限分析模块尚未开发时，提供**可复现的接口占位**。

**这不是身份认证，也不构成任何授权结论。**
本 Mock 刻意不伪造以下内容：
  * 不声称完成真实 Enclave 认证；
  * 不声称观察到 DDS AccessControl 日志；
  * 不声称有受控安全实验支持。

因此 `identity_evidence.kind` 恒为 `MOCK`（而非更高级别的证据），
`access_control_evidence.kind` 恒为 `MOCK`。
`subject.declared_enclave` 若由输入给出，仅作为**客户端自报值**记录，
绝不写入 `subject.authenticated_identity`。

输入：一个 ModuleInputEnvelope（stdin）
输出：一个 IdentityTrustAssessment（stdout）

行为控制（测试用）
------------------
`observations[].detail.f0_mock`：
    {"scenario": "authorized" | "denied" | "unknown" | "error",
     "fault": "<协议层故障名>"}
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _protocol import (  # noqa: E402
    EXIT_INPUT_ERROR, EXIT_OK, apply_overrides, apply_fault_injection,
    control_for, emit,
    epoch_now_iso, note, parse_args, read_input, require,
)

MODULE = 'identity_trust'
SCHEMA_VERSION = '1.0.0-proposed'
PRODUCER = {'name': 'identity_trust_mock', 'module_version': '0.1.0', 'source': 'MOCK'}
RESOURCE = '/rg/guarded_navigate'

# (顶层状态, 授权结果, 拒绝层级, 身份证据种类, 访问控制证据种类, 理由)
STATUS_TABLE = {
    'authorized': ('AUTHORIZED', 'AUTHORIZED', 'NONE', 'MOCK', 'NONE',
                   '模拟分析判定为已授权（模拟结论，非 DDS 认证）'),
    'denied': ('DENIED', 'DENIED', 'UNKNOWN', 'MOCK', 'MOCK',
               '模拟分析判定为拒绝（模拟结论，未观察到真实访问控制日志）'),
    'unknown': ('UNKNOWN', 'UNKNOWN', 'UNKNOWN', 'MOCK', 'UNKNOWN',
                '证据不足，无法判定授权状态（不等于已授权）'),
    'error': ('ERROR', 'ERROR', 'UNKNOWN', 'MOCK', 'UNKNOWN',
              '模块自身执行失败，未能形成授权判断'),
}


def build(envelope):
    control = control_for(envelope, MODULE)
    scenario = str(control.get('scenario', 'authorized')).lower()
    if scenario in ('default', ''):
        scenario = 'authorized'
    if scenario not in STATUS_TABLE:
        raise ValueError('未知场景: {0!r}（可选 {1}）'.format(
            scenario, sorted(STATUS_TABLE)))

    status, result, denial_layer, identity_kind, ac_kind, reason = STATUS_TABLE[scenario]

    subject = {'observed_name': 'planner_node'}
    # 输入中若声明了 enclave，只作为**自报值**记录，且不提升为已认证身份
    declared = control.get('declared_enclave')
    if declared:
        subject['declared_enclave'] = str(declared)

    requested_resource = str(control.get('requested_resource', RESOURCE))
    operation = str(control.get('operation', 'SERVICE_REQUEST'))

    document = {
        'schema_version': SCHEMA_VERSION,
        'run_id': require(envelope, 'run_id'),
        'request_id': require(envelope, 'request_id'),
        'event_id': 'evt-id-{0}'.format(require(envelope, 'request_id')),
        'producer': dict(PRODUCER),
        'observed_at': epoch_now_iso(),
        'status': status,
        'reason': reason,
        'subject': subject,
        'requested_resource': {'resource': requested_resource, 'operation': operation},
        'authorization': {
            'result_status': result,
            'denial_layer': denial_layer,
        },
        'identity_evidence': {
            'kind': identity_kind,
            'detail': '来源为模拟实现；未进行任何真实身份认证',
        },
        'access_control_evidence': {
            'kind': ac_kind,
            'detail': '无真实访问控制日志；结论不构成 DDS AccessControl 判定',
        },
        'evidence_refs': [{
            'ref': 'mock_modules/identity_trust_mock.py',
            'kind': 'MOCK',
            'note': '模拟结论；不得当作已通过 DDS 认证或已获授权',
        }],
    }
    # 可选字段：仅在来源明确时才写 policy_ref（此处刻意不写，避免伪造策略版本）
    return document, scenario


def main() -> int:
    args = parse_args('身份与资源访问安全 Mock（模拟实现，无安全保证）')
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
