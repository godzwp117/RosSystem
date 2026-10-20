#!/usr/bin/env python3
"""int_limited_verification.py -- 受限三真实联合验证的实证用例（集成轮）。

本轮**不是** LEVEL 3 正向准入。本脚本只做一件事：
用真实 F0 适配器路径证明"该阻断时确实阻断、该推进时确实推进"，
并把每一次判定、模块状态与是否进入下游记录成可复核证据。

覆盖的验收项（编号对应任务书《必须复验》）：

* 4  M1 缺少有效在线模型/状态为 UNKNOWN 时，F0 不得推进
* 5  M2 没有生产可信当前身份时，F0 必须阻断
* 6  M3 规则引擎真实运行（allow / block 两种判定）
* 7  F0 严格模式在无真实凭据时给出 ADAPTER_BLOCK
* 8  被阻断的请求不得进入 Planner/Gateway
* 12 新增 M2 研究组件不得改变原有 Gateway 业务决策

不覆盖：9（ROS 2 下游实机）、10（M3 在线六场景）、11（DDS Enforce）。
这三项需要完整 ROS 2 运行时，本轮未启动，报告中标注 NOT_RUN。

用法
----
    python3 scripts/int_limited_verification.py --evidence <dir>
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for extra in (REPO, os.path.join(REPO, 'scripts'), os.path.join(REPO, 'tests', 'unit')):
    if extra not in sys.path:
        sys.path.insert(0, extra)

from test_team_process_protocol import (  # noqa: E402
    envelope, proceed_control, run_adapter, write_config)

RESULTS = []


#: 证据来源标签。**不得**用适配器返回的 JSON 字段冒充真实 Gateway 观测。
ADAPTER_UNIT_ONLY = 'ADAPTER_UNIT_ONLY'
REAL_ROS2_ONLINE_AUDIT = 'REAL_ROS2_ONLINE_AUDIT'


def record(item, name, expectation, result, ok, evidence_source=ADAPTER_UNIT_ONLY):
    downstream = {
        'decision': result.get('decision'),
        'reason_code': result.get('reason_code'),
        'gateway_submission': result.get('gateway_submission'),
        'submitted_to_gateway': result.get('submitted_to_gateway'),
    }
    RESULTS.append({
        'item': item, 'case': name, 'expectation': expectation,
        'decision': result.get('decision'),
        'reason_code': result.get('reason_code'),
        'downstream': downstream,
        'module_statuses': [(m.get('module'), m.get('status'))
                            for m in (result.get('modules') or [])],
        'evidence_source': evidence_source,
        'verdict': 'PASS' if ok else 'FAIL',
    })
    print(f'  [{"PASS" if ok else "FAIL"}] item {item:>2} {name}: '
          f'{result.get("decision")} {result.get("reason_code") or ""}')


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--evidence', required=True)
    args = parser.parse_args(argv)
    evidence = Path(args.evidence)
    evidence.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='intverify-'))

    # ---- 0) 受控基线：三模块均推进，受控身份模式 ----
    case = work / 'baseline'
    case.mkdir(parents=True)
    config = write_config(case, mode='mock',
                          identity_mode='CONTROLLED_TEST_ONLY')
    code, result, _err = run_adapter(case, envelope(proceed_control()), config)
    record('0-baseline', '受控基线（三模块正常）',
           'READY_FOR_GATEWAY_SUBMISSION',
           result, result.get('decision') == 'READY_FOR_GATEWAY_SUBMISSION')

    # ---- 4) M1 状态 UNKNOWN -> 不得推进 ----
    case = work / 'm1_unknown'
    case.mkdir(parents=True)
    config = write_config(case, mode='mock', identity_mode='CONTROLLED_TEST_ONLY')
    code, result, _err = run_adapter(
        case, envelope(proceed_control(comm_risk={'scenario': 'unknown'})), config)
    record('4', 'M1 UNKNOWN 必须失败关闭', 'ADAPTER_BLOCK',
           result, result.get('decision') == 'ADAPTER_BLOCK')

    # ---- 5) M2 无生产可信当前身份 -> 必须阻断 ----
    case = work / 'm2_unknown'
    case.mkdir(parents=True)
    config = write_config(case, mode='mock', identity_mode='CONTROLLED_TEST_ONLY')
    code, result, _err = run_adapter(
        case, envelope(proceed_control(identity_trust={'scenario': 'unknown'})),
        config)
    record('5', 'M2 当前身份 UNKNOWN 必须阻断', 'ADAPTER_BLOCK',
           result, result.get('decision') == 'ADAPTER_BLOCK')

    # ---- 6) M3 规则真实运行：allow 与 block ----
    case = work / 'm3_allow'
    case.mkdir(parents=True)
    config = write_config(case, mode='mock', identity_mode='CONTROLLED_TEST_ONLY')
    code, result, _err = run_adapter(
        case, envelope(proceed_control(task_risk={'scenario': 'allow'})), config)
    record('6a', 'M3 规则 allow（真实模块执行）', 'READY_FOR_GATEWAY_SUBMISSION',
           result, result.get('decision') == 'READY_FOR_GATEWAY_SUBMISSION')

    case = work / 'm3_block'
    case.mkdir(parents=True)
    config = write_config(case, mode='mock', identity_mode='CONTROLLED_TEST_ONLY')
    code, result, _err = run_adapter(
        case, envelope(proceed_control(task_risk={'scenario': 'block'})), config)
    record('6b', 'M3 规则 block 必须阻断', 'ADAPTER_BLOCK',
           result, result.get('decision') == 'ADAPTER_BLOCK')

    # ---- 7) 严格模式 + 无真实凭据 -> ADAPTER_BLOCK ----
    case = work / 'strict_no_attestation'
    case.mkdir(parents=True)
    config = write_config(case, mode='mock', identity_mode='STRICT')
    code, result, _err = run_adapter(case, envelope(proceed_control()), config)
    record('7', 'STRICT 无真实凭据必须 ADAPTER_BLOCK', 'ADAPTER_BLOCK',
           result, result.get('decision') == 'ADAPTER_BLOCK')

    # ---- 8) 被阻断请求不得进入下游 ----
    blocked_cases = [r for r in RESULTS if r['decision'] == 'ADAPTER_BLOCK']
    leaked = [r for r in blocked_cases
              if r['downstream'].get('gateway_submission')
              or r['downstream'].get('submitted_to_gateway')]
    RESULTS.append({
        'item': '8', 'case': '被阻断请求未进入 Planner（适配器层）',
        'expectation': ('所有 ADAPTER_BLOCK 结果不得带下游提交标记；'
                        '该结论仅覆盖适配器层，Gateway 实际到达与否'
                        '必须由真实在线审计另行证明，不能由本字段推断'),
        'decision': f'{len(blocked_cases)} blocked / {len(leaked)} leaked',
        'reason_code': None, 'downstream': None, 'module_statuses': [],
        'evidence_source': ADAPTER_UNIT_ONLY,
        'scope_limit': '适配器层证据；不等价于 Gateway 审计中的 0 到达',
        'verdict': 'PASS' if not leaked else 'FAIL',
    })
    print(f'  [{"PASS" if not leaked else "FAIL"}] item  8 '
          f'适配器层下游泄漏: {len(leaked)} / {len(blocked_cases)}'
          f'（Gateway 层面由真实在线审计另行验证）')

    # ---- 12) M2 研究组件不得改变原有决策 ----
    # M2 组件（src/m2_witness/**、scripts/m2_*.py）只在被显式调用时运行，
    # F0 适配器路径不引用它们。这里用"相同输入重复判定"来证明决策稳定，
    # 并记录 M2 组件文件是否被 F0 适配器导入。
    case = work / 'm2_inert'
    case.mkdir(parents=True)
    config = write_config(case, mode='mock', identity_mode='CONTROLLED_TEST_ONLY')
    code_a, result_a, _e = run_adapter(case, envelope(proceed_control()), config)
    code_b, result_b, _e = run_adapter(case, envelope(proceed_control()), config)
    same = (result_a.get('decision') == result_b.get('decision')
            and result_a.get('reason_code') == result_b.get('reason_code'))
    record('12', 'M2 组件存在不改变 F0 决策（重复判定一致）',
           '两次判定完全一致', result_b, same)
    # 注意：本项只证明 F0 适配器自身判定稳定，**不**证明 Gateway 的
    # ALLOW/BLOCK 行为未变。Gateway 权威对照必须由真实在线审计证明
    # （见 docs/integration/LIMITED_THREE_REAL_ONLINE_CLOSEOUT.md）。
    RESULTS[-1]['scope_limit'] = '仅 F0 适配器重复判定；Gateway 决策对照需真实在线证据'

    # F0 适配器是否导入 M2 研究脚本（应为否）
    adapter_source = Path(REPO, 'scripts', 'team_demo.py').read_text(encoding='utf-8')
    imports_m2 = ('m2_issue_attestation' in adapter_source
                  or 'm2_trusted_action_window' in adapter_source
                  or 'm2_witness' in adapter_source)
    RESULTS.append({
        'item': '12b', 'case': 'F0 适配器不导入 M2 研究脚本',
        'expectation': 'team_demo.py 不得引用 M2 研究组件',
        'decision': 'imported' if imports_m2 else 'not imported',
        'reason_code': None, 'downstream': None, 'module_statuses': [],
        'evidence_source': ADAPTER_UNIT_ONLY,
        'verdict': 'PASS' if not imports_m2 else 'FAIL',
    })
    print(f'  [{"PASS" if not imports_m2 else "FAIL"}] item 12b '
          f'F0 是否导入 M2 研究脚本: {imports_m2}')

    passed = sum(1 for r in RESULTS if r['verdict'] == 'PASS')
    summary = {
        'contract': 'limited-three-real-verification/1',
        'cases': len(RESULTS), 'pass': passed,
        'fail': len(RESULTS) - passed,
        'scope_note': ('本文件全部用例均为 ADAPTER_UNIT_ONLY：使用受控 Mock 驱动 F0，'
                       '证明受控决策与失败关闭。它**不**包含真实 ROS 2 下游、'
                       'M3 在线六场景与 DDS Enforce；那些结论见 '
                       'LIMITED_THREE_REAL_ONLINE_CLOSEOUT.md 的真实在线证据。'
                       '不得据此宣称 LEVEL 3 通过，也不得用本文件的 '
                       'gateway_submission 字段推断 Gateway 是否收到请求。'),
        'results': RESULTS,
    }
    out = evidence / 'limited_verification.json'
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'cases': summary['cases'], 'pass': passed,
                      'fail': summary['fail'], 'out': str(out)},
                     ensure_ascii=False, indent=2))
    return 0 if summary['fail'] == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
