#!/usr/bin/env python3
"""mock_modules/task_risk_mock.py -- 任务感知风险推理的模拟实现。

用途
----
在真实任务风险推理模块尚未开发时，提供**可复现的接口占位**。

**这是上游风险建议，不是 Gateway 的最终授权。**
即使输出 `ALLOW_RECOMMENDED`，候选操作仍必须经过 `/rg/guarded_navigate`
由 SecurityGateway 按其权威策略判定。

关于 M3 扩展字段：F0 基线不提供权威策略版本，因此本 Mock
**绝不填写** `policy_epoch` / `policy_digest`（不用 0 或占位常量冒充）。
`task_phase` 仅在输入显式给出且标注来源为 MOCK 时才写入。

输入：一个 ModuleInputEnvelope（stdin）
输出：一个 TaskRiskDecision（stdout）

行为控制（测试用）
------------------
`observations[].detail.f0_mock`：
    {"scenario": "allow" | "block" | "unknown" | "error",
     "fault": "<协议层故障名>"}
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _protocol import (  # noqa: E402
    EXIT_INPUT_ERROR, EXIT_OK, apply_fault_injection, candidate_target,
    apply_overrides, control_for, emit, epoch_now_iso, note, parse_args, read_input, require,
)

MODULE = 'task_risk'
SCHEMA_VERSION = '1.0.0-proposed'
PRODUCER = {'name': 'task_risk_mock', 'module_version': '0.1.0', 'source': 'MOCK'}
GUARDED_ACTION = '/rg/guarded_navigate'

# (顶层状态, 风险等级, 理由)
STATUS_TABLE = {
    'allow': ('ALLOW_RECOMMENDED', 'NONE', '模拟判定目标位于允许区域，未发现任务约束冲突'),
    'block': ('BLOCK_RECOMMENDED', 'HIGH', '模拟判定目标超出允许区域，存在任务越界风险'),
    'unknown': ('UNKNOWN', 'UNKNOWN', '无可信策略来源，无法判定是否越界（不等于允许）'),
    'error': ('ERROR', 'UNKNOWN', '模块自身执行失败，未能形成风险建议'),
}


def build(envelope):
    control = control_for(envelope, MODULE)
    scenario = str(control.get('scenario', 'allow')).lower()
    if scenario in ('default', ''):
        scenario = 'allow'
    if scenario not in STATUS_TABLE:
        raise ValueError('未知场景: {0!r}（可选 {1}）'.format(
            scenario, sorted(STATUS_TABLE)))

    status, risk, reason = STATUS_TABLE[scenario]
    task_id = require(envelope, 'task_id') if 'task_id' in envelope else None
    action = envelope.get('candidate_action') or {}
    task_id = task_id or action.get('task_id')
    if not task_id:
        raise ValueError('输入信封缺少任务标识（candidate_action.task_id）')
    target = candidate_target(envelope)

    document = {
        'schema_version': SCHEMA_VERSION,
        'run_id': require(envelope, 'run_id'),
        'request_id': require(envelope, 'request_id'),
        'event_id': 'evt-task-{0}'.format(require(envelope, 'request_id')),
        'producer': dict(PRODUCER),
        'observed_at': epoch_now_iso(),
        'status': status,
        'reason': reason,
        'task_id': task_id,
        # 候选操作固定指向准入入口；上游无法选择执行端
        'candidate_action': {
            'action_resource': GUARDED_ACTION,
            'operation': str(action.get('operation', 'NAVIGATE')),
        },
        'target': target,
        'risk_level': risk,
        'rule_basis': [
            '场景 {0}：候选目标 ({1}, {2}) 坐标系 {3}'.format(
                scenario, target['x'], target['y'], target['frame_id']),
            '来源为模拟规则，非权威 TaskPolicy 判定',
        ],
        'evidence_refs': [{
            'ref': 'mock_modules/task_risk_mock.py',
            'kind': 'MOCK',
            'note': '模拟建议；最终授权仍由 SecurityGateway 判定',
        }],
    }
    # 仅在输入显式提供且标注来源时才写入 task_phase；绝不伪造 policy_epoch/digest
    declared_phase = control.get('task_phase')
    if declared_phase:
        document['task_context'] = {
            'task_phase': str(declared_phase),
            'phase_source': 'MOCK',
        }
    return document, scenario


def main() -> int:
    args = parse_args('任务风险推理 Mock（模拟建议，非最终授权）')
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
