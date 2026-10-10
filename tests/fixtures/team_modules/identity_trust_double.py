#!/usr/bin/env python3
"""身份与授权**测试替身**：按本地权限矩阵真实计算授权结论。

与 mock_modules/identity_trust_mock.py 的本质区别
-------------------------------------------------
Mock 是场景开关（输入说 authorized 就输出 AUTHORIZED）。
本替身读取 `tests/fixtures/team_modules/permissions_matrix.json`
以及输入中的 (主体, 资源, 操作) 三元组，按矩阵规则算出结论。
换主体或换资源会得到不同结果。

**这不是 DDS 认证**：`identity_evidence.kind` 为 `MOCK`（模拟），
`access_control_evidence.kind` 为 `NONE`（无真实访问控制日志）。
绝不写入 `subject.authenticated_identity`。
"""

from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(HERE))), 'mock_modules'))

from _protocol import (  # noqa: E402
    EXIT_INPUT_ERROR, EXIT_OK, emit, epoch_now_iso, note, parse_args, read_input,
    require,
)

SCHEMA_VERSION = '1.0.0-proposed'
PRODUCER = {'name': 'identity_trust_double', 'module_version': '0.1.0', 'source': 'MOCK'}
MATRIX_PATH = os.path.join(HERE, 'permissions_matrix.json')


def load_matrix():
    with open(MATRIX_PATH, 'r', encoding='utf-8') as handle:
        return json.load(handle)


def decide(matrix, subject, resource, operation):
    """按矩阵判断；返回 (状态, 拒绝层级, 依据)。"""
    entry = (matrix.get('subjects') or {}).get(subject)
    if entry is None:
        return ('UNKNOWN', 'UNKNOWN', '主体 {0} 不在测试矩阵中，无法判断'.format(subject))
    for rule in entry.get('allowed', []):
        if rule.get('resource') == resource:
            if operation in (rule.get('operations') or []):
                return ('AUTHORIZED', 'NONE',
                        '测试矩阵允许 {0} 对 {1} 执行 {2}'.format(subject, resource, operation))
            return ('DENIED', 'UNKNOWN',
                    '测试矩阵未授予操作 {0}（资源 {1} 已列出但操作不匹配）'.format(
                        operation, resource))
    return ('DENIED', 'UNKNOWN',
            '测试矩阵中不存在资源 {0} 的允许规则'.format(resource))


def main() -> int:
    parse_args('身份授权测试替身（矩阵计算，非 DDS 认证）')
    try:
        envelope = read_input()
    except ValueError as exc:
        note('输入解析失败: {0}'.format(exc))
        return EXIT_INPUT_ERROR

    observed = {}
    for observation in envelope.get('observations', []) or []:
        detail = observation.get('detail') if isinstance(observation, dict) else None
        if isinstance(detail, dict) and isinstance(detail.get('identity'), dict):
            observed = detail['identity']
            break

    subject = str(observed.get('subject', 'planner_node'))
    resource = str(observed.get('resource', '/rg/guarded_navigate'))
    operation = str(observed.get('operation', 'SERVICE_REQUEST'))

    if observed.get('fail'):
        note('按输入要求模拟替身自身失败')
        return EXIT_INPUT_ERROR

    try:
        matrix = load_matrix()
    except (OSError, ValueError) as exc:
        note('无法读取测试权限矩阵: {0}'.format(exc))
        return EXIT_INPUT_ERROR

    status, denial_layer, reason = decide(matrix, subject, resource, operation)
    result_status = status if status in ('AUTHORIZED', 'DENIED') else 'UNKNOWN'

    document = {
        'schema_version': SCHEMA_VERSION,
        'run_id': require(envelope, 'run_id'),
        'request_id': require(envelope, 'request_id'),
        'event_id': 'evt-id-double-{0}'.format(require(envelope, 'request_id')),
        'producer': dict(PRODUCER),
        'observed_at': epoch_now_iso(),
        'status': status,
        'reason': reason,
        'subject': {'observed_name': subject},
        'requested_resource': {'resource': resource, 'operation': operation},
        'authorization': {'result_status': result_status, 'denial_layer': denial_layer},
        'identity_evidence': {
            'kind': 'MOCK',
            'detail': '测试替身按本地夹具矩阵计算；未进行任何真实身份认证',
        },
        'access_control_evidence': {
            'kind': 'NONE',
            'detail': '无真实 DDS AccessControl 日志',
        },
        'policy_ref': {'permissions_ref':
                       'tests/fixtures/team_modules/permissions_matrix.json',
                       'policy_version': 'test-fixture-1'},
        'evidence_refs': [{'ref': 'tests/fixtures/team_modules/permissions_matrix.json',
                           'kind': 'MOCK',
                           'note': '测试夹具推导，不得当作已通过 DDS 认证'}],
    }
    note('替身矩阵：subject={0} resource={1} op={2} -> {3}'.format(
        subject, resource, operation, status))
    emit(document)
    return EXIT_OK


if __name__ == '__main__':
    sys.exit(main())
