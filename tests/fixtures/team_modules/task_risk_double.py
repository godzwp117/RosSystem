#!/usr/bin/env python3
"""任务风险**测试替身**：按本地区域规则真实计算风险建议。

与 mock_modules/task_risk_mock.py 的本质区别
--------------------------------------------
Mock 是场景开关（输入说 block 就输出 BLOCK_RECOMMENDED）。
本替身读取 `tests/fixtures/team_modules/region_rules.json` 与输入中的
候选目标坐标，按几何规则算出建议。目标坐标变化会改变输出。

**这是上游建议，不是最终授权。**
即使输出 ALLOW_RECOMMENDED，候选操作仍必须经过 /rg/guarded_navigate。
本替身绝不填写 policy_epoch / policy_digest（F0 无权威策略版本来源）。
"""

from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(HERE))), 'mock_modules'))

from _protocol import (  # noqa: E402
    EXIT_INPUT_ERROR, EXIT_OK, candidate_target, emit, epoch_now_iso, note,
    parse_args, read_input, require,
)

SCHEMA_VERSION = '1.0.0-proposed'
PRODUCER = {'name': 'task_risk_double', 'module_version': '0.1.0', 'source': 'MOCK'}
GUARDED_ACTION = '/rg/guarded_navigate'
RULES_PATH = os.path.join(HERE, 'region_rules.json')


def decide(region, target):
    x, y = float(target['x']), float(target['y'])
    inside = (region['x_min'] <= x <= region['x_max']
              and region['y_min'] <= y <= region['y_max'])
    span = 'x∈[{0},{1}] y∈[{2},{3}]'.format(
        region['x_min'], region['x_max'], region['y_min'], region['y_max'])
    if inside:
        return ('ALLOW_RECOMMENDED', 'NONE',
                '目标 ({0}, {1}) 位于测试允许区域 {2} 内'.format(x, y, span))
    return ('BLOCK_RECOMMENDED', 'HIGH',
            '目标 ({0}, {1}) 超出测试允许区域 {2}'.format(x, y, span))


def main() -> int:
    parse_args('任务风险测试替身（几何规则，非最终授权）')
    try:
        envelope = read_input()
    except ValueError as exc:
        note('输入解析失败: {0}'.format(exc))
        return EXIT_INPUT_ERROR

    action = envelope.get('candidate_action') or {}
    task_id = action.get('task_id')
    if not task_id:
        note('输入缺少 candidate_action.task_id')
        return EXIT_INPUT_ERROR

    target = candidate_target(envelope)
    for observation in envelope.get('observations', []) or []:
        detail = observation.get('detail') if isinstance(observation, dict) else None
        if isinstance(detail, dict) and detail.get('task', {}).get('fail'):
            note('按输入要求模拟替身自身失败')
            return EXIT_INPUT_ERROR

    try:
        with open(RULES_PATH, 'r', encoding='utf-8') as handle:
            rules = json.load(handle)
    except (OSError, ValueError) as exc:
        note('无法读取测试区域规则: {0}'.format(exc))
        return EXIT_INPUT_ERROR

    status, risk, reason = decide(rules['allowed_region'], target)
    document = {
        'schema_version': SCHEMA_VERSION,
        'run_id': require(envelope, 'run_id'),
        'request_id': require(envelope, 'request_id'),
        'event_id': 'evt-task-double-{0}'.format(require(envelope, 'request_id')),
        'producer': dict(PRODUCER),
        'observed_at': epoch_now_iso(),
        'status': status,
        'reason': reason,
        'task_id': str(task_id),
        'candidate_action': {
            'action_resource': GUARDED_ACTION,
            'operation': str(action.get('operation', 'NAVIGATE')),
        },
        'target': target,
        'risk_level': risk,
        'rule_basis': ['测试区域规则（非权威 TaskPolicy）',
                       reason],
        'evidence_refs': [{'ref': 'tests/fixtures/team_modules/region_rules.json',
                           'kind': 'MOCK',
                           'note': '测试夹具规则推导；最终授权仍由 SecurityGateway 判定'}],
    }
    note('替身几何：target=({0},{1}) -> {2}'.format(target['x'], target['y'], status))
    emit(document)
    return EXIT_OK


if __name__ == '__main__':
    sys.exit(main())
