# 2026-10-19 演示版本冻结：本轮复验记录

> 发布分支：`release/demo-2026-10-19-freeze` @ `6786ff89ee9a60f5084668f67d5d067bf143a193`
> 受测代码提交（`DEMO_TESTED_CODE_SHA`）：`be47ccd6c1b19460b65abc0ea8004706383d01d4`
> 冻结提交（含文档与证据）：`6786ff89ee9a60f5084668f67d5d067bf143a193`
> run_id：`freeze-verify-20261020T134804Z`
> 容器 `rg_freeze`（Domain 71 在线 / 42·43 正式 Enforce）
> 证据：`artifacts/demo-2026-10-19/freeze-verify-freeze-verify-20261020T134804Z/`

## 1. 本轮做了什么

冻结版本在上一轮已建立（4 份演示文档、发布脚本、交接文档、证据）。
本轮做的是**在同一冻结提交上重新实际执行验收**，而不是继承历史结论。

## 2. 复验结果（本轮实测）

| 项 | 命令 | 结果 |
| --- | --- | --- |
| 公共契约 | `validate_team_contracts.py --all` | **PASS** |
| F0 P0 安全反例 | `pytest test_phase2_security_boundaries test_f0_identity_trust_boundary` | **38 passed** |
| 全仓单元测试 | `pytest tests/unit` | **763 passed, 3 skipped in 531.54s (0:08:51)**（exit 0） |
| M3 在线六场景 | `m3_online_drive.sh` + `m3_online_extra.sh` | **19 checks / 0 failures / PASS** |
| 三真实联合调用 | `run_three_real_online.py --expect-block` | `THREE_EXTERNAL_CALLED=PASS`、`VALIDATED=PASS`、`ONLINE_PROCEED=BLOCKED` |
| DDS Enforce | `tests/integration/sros2_check.py`（正式域 42/43） | **7/7 PASS** |

### 2.1 M3 六场景（本轮 run_id）

| 场景 | 结果 |
| --- | --- |
| ON-01 合法执行 | Gateway ALLOW，NavSim **1 Goal** |
| ON-02 M3 阻断 | 未提交，0 Goal |
| ON-03 M3 UNKNOWN | 未提交，0 Goal |
| ON-04 M3 ERROR | 未提交，0 Goal |
| ON-05 Gateway 独立阻断 | ALLOW_RECOMMENDED → Gateway `OUT_OF_REGION` BLOCK，0 Goal |
| ON-06 Planner TIMEOUT | 本轮实际：audit 0 / journal 0 |

校验器对 ON-06 的判定是"超时未记为 Gateway BLOCK"，即 TIMEOUT 与 BLOCK 明确区分。

### 2.2 三真实模块（本轮实测状态）

| 模块 | 模式 | 退出码 | 状态 | Schema |
| --- | --- | --- | --- | --- |
| `comm_risk` | external | 0 | **UNKNOWN** | 合法 |
| `identity_trust` | external | 0 | `AUTHORIZED`（历史解释） | 合法 |
| `task_risk` | external | 0 | `ALLOW_RECOMMENDED` | 合法 |

F0：`ADAPTER_BLOCK` / `ADAPTER_MODULE_STATUS_NOT_PROCEED`。
**这是正确行为，不是故障**：M1 无有效在线模型证据，严格模式必须阻断。

### 2.3 DDS Enforce 7/7（正式 SROS 2 权限）

S1 普通模式、S2 合法 Enforce 链、S3 Planner 直连执行端被拒绝、
S3C Gateway 正向对照、S4 未授权主体被拒绝、S5 TaskPolicy 越界拒绝、
S6 安全配置失效不静默降级 —— 全部 PASS。

**与 M3 在线场景是不同 Domain、不同 run 的独立证据**，不得合并陈述为"同次三真实 Enforce 联调"。

## 3. 本轮发现的一个真实问题

`m3_online_extra.sh` 结束后残留 **`STRAY=6`** 个进程
（drive 组是 `STRAY_RG_PROCS=0`）。已手工清理，但这说明 extra 脚本的
进程组回收不完整，属已知缺陷，记录在此供后续修复。
**它不影响本轮结论**（场景证据已落盘），但现场演示前必须确认无残留。

## 4. 能力边界（不得混淆）

| 能力 | 状态 |
| --- | --- |
| M1/M2 MOCK + M3 EXTERNAL 在线闭环 | **已验证**（演示主场景） |
| 三真实模块联合**调用** | **已验证**（真实进程、Schema 合法） |
| 三真实模块联合**正向准入** | **BLOCKED**（M1 模型无效、M2 无生产签发者） |
| F0 STRICT 身份防伪造 | **已验证**（38 项反例） |
| DDS-Security 原生最小权限 | **已验证**（7/7） |
| 三真实模块 LEVEL 3 | **未达成** |

## 5. 结论

`DEMO_FREEZE_PASS`（受控演示范围）。

冻结版本可复现、可回退（RC2 `33cb4f93` 未动）、可审计。
但**不等于**三真实模块在线正向安全准入已完成。
