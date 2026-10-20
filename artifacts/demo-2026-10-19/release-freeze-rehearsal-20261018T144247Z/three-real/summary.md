# 三真实模块联合运行摘要

- run_id: `rehearsal-20261018T144247Z-three-real`
- request_id: `legal-rehearsal-20261018T144247Z-three-real`
- 配置: `config/team_modules.three-real.yaml`
- 生成时间: 2026-10-18T14:43:10Z

| 等级 | 结果 |
| --- | --- |
| `THREE_EXTERNAL_CALLED` | **PASS** |
| `THREE_EXTERNAL_VALIDATED` | **PASS** |
| `THREE_EXTERNAL_ONLINE_PROCEED` | **BLOCKED** |

## 各模块实际调用

| 模块 | mode | rc | schema | status | 耗时ms |
| --- | --- | --- | --- | --- | --- |
| comm_risk | external | 0 | True | UNKNOWN | 120 |
| identity_trust | external | 0 | True | AUTHORIZED | 104 |
| task_risk | external | 0 | True | ALLOW_RECOMMENDED | 111 |

## F0 决策

- decision: `ADAPTER_BLOCK`
- reason_code: `ADAPTER_MODULE_STATUS_NOT_PROCEED`
- 返回码: 10

> F0 的 READY_FOR_GATEWAY_SUBMISSION 不是 Gateway ALLOW；Gateway 判定在在线阶段单独验证。

## 阻断原因

- comm_risk: status='UNKNOWN'，推进需要 'NORMAL'
- identity_trust: current_request_identity.status='UNKNOWN'，本轮没有可信的当前请求身份绑定
- F0 决策为 'ADAPTER_BLOCK'（ADAPTER_MODULE_STATUS_NOT_PROCEED），未提交 Planner

## 证据备注

- identity_trust: current_request_identity.status='UNKNOWN' binding='UNBOUND_NO_TRUSTED_CURRENT_IDENTITY_WITNESS' historical_only=False
- comm_risk: trusted_provenance='UNKNOWN' envelope_provenance='RUNTIME_LOG' gate=None controlled_test=False
