# 三真实模块联合运行摘要

- run_id: `three-final-20261020T160207Z-final`
- request_id: `legal-three-final-20261020T160207Z-final`
- 配置: `config/team_modules.three-real.yaml`
- 生成时间: 2026-10-20T16:13:54Z

| 等级 | 结果 |
| --- | --- |
| `THREE_EXTERNAL_CALLED` | **FAIL** |
| `THREE_EXTERNAL_VALIDATED` | **BLOCKED** |
| `THREE_EXTERNAL_ONLINE_PROCEED` | **BLOCKED** |

## 各模块实际调用

| 模块 | mode | rc | schema | status | 耗时ms |
| --- | --- | --- | --- | --- | --- |
| comm_risk | external | 2 | False | None | 11 |
| identity_trust | external | 2 | False | None | 10 |
| task_risk | external | 2 | False | None | 10 |

## F0 决策

- decision: `ADAPTER_BLOCK`
- reason_code: `ADAPTER_DEPENDENCY_MISSING`
- 返回码: 4

> F0 的 READY_FOR_GATEWAY_SUBMISSION 不是 Gateway ALLOW；Gateway 判定在在线阶段单独验证。

## 阻断原因

- comm_risk: 未被成功调用（rc=2 timeout=False err=None）
- identity_trust: 未被成功调用（rc=2 timeout=False err=None）
- task_risk: 未被成功调用（rc=2 timeout=False err=None）
- LEVEL 3 依赖 LEVEL 2 通过；当前 LEVEL 2=BLOCKED
