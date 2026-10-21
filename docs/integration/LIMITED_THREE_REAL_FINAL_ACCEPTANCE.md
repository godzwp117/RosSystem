# 受限三真实集成最终验收

> 起点：`fdc322338499594b06fd94134a2b458a0742b847`
> 分支：`integration/three-real-limited-online-closure`
> 受测代码 SHA：**`fdc322338499594b06fd94134a2b458a0742b847`**（本轮未修改产品代码）
> run_id：`online-20261019T155522Z`
> 容器：`rg_online`（Jazzy / rmw_fastrtps_cpp / Fast DDS 2.14.6）
> Domain：64（在线）、42（普通）、43（正式 Enforce）
> 证据：`artifacts/integration/three-real-limited-online/online-20261019T155522Z/`

---

## 1. 最终评级

# `LIMITED_INTEGRATION_PASS`

该 PASS 的含义被严格限定为：

> **受限三真实集成、系统在线兼容性与安全失败关闭得到完整验收。**

它**不**表示三真实模块 LEVEL 3 正向准入通过。

## 2. 评级依据（逐条对应）

| 条件 | 结果 | 证据 |
| --- | --- | --- |
| M1/M2/M3 研究代码完成合流 | ✅ | 两次 `--no-ff` 合流，零冲突 |
| 三真实 External 调用与 Schema | ✅ | `three_real_external/`：三模块 `mode=external`、`schema_ok=true` |
| F0 STRICT 失败关闭 | ✅ | `f0_security/p0.log` 38 passed；NEG `ADAPTER_BLOCK` |
| M1/M2 无可信正向证据时正确阻断 | ✅ | comm_risk=UNKNOWN、identity_trust=UNKNOWN → `ADAPTER_MODULE_STATUS_NOT_PROCEED` |
| ROS 2 下游在线验证真实执行 | ✅ | `downstream_v2/`：栈就绪 + NEG/POS 同栈 |
| Gateway/NavSim 独立审计证明未执行 | ✅ | NEG 审计 0 行 / journal 0 行；同栈 POS 审计 3 行 / journal 1 Goal |
| M3 在线六场景实际完成 | ✅ | `m3_online/merged/verification.json`：19 checks / 0 failures |
| Gateway ALLOW/BLOCK 与 NavSim 关联正确 | ✅ | ON-01 ALLOW→1 Goal；ON-05 BLOCK→0 Goal |
| F0 P0 身份安全反例 | ✅ | 38 passed |
| 原有 DDS Enforce 正反例实际通过 | ✅ | 正式权限 7/7（S1/S2/S3/S3C/S4/S5/S6） |
| 受测代码与测试证据绑定 | ✅ | `tested_commit.json` |
| 无新的严重安全回归 | ✅ | 全仓 767 passed / 4 skipped / exit 0 |

## 3. 第 9、10 项的补齐

| 项 | 上一轮 | 本轮 |
| --- | --- | --- |
| 9 真实 ROS 2 下游 | NOT_RUN | **PASS** |
| 10 M3 在线六场景 | NOT_RUN | **PASS** |

细节见 `docs/integration/LIMITED_THREE_REAL_ONLINE_CLOSEOUT.md`。

## 4. 关键证据链（同栈 NEG + POS）

这是本轮最重要的方法学改进：**不再用 F0 的 JSON 字段推断 Gateway 行为**。

```
downstream_v2/
  gateway.log        -> GATEWAY_READY (policy_loaded=true, downstream_server_available=true)
  neg_f0.json        -> ADAPTER_BLOCK / ADAPTER_MODULE_STATUS_NOT_PROCEED
  gateway_audit.jsonl-> NEG 后 0 行
  navsim_goals.jsonl -> NEG 后 0 行
  pos_f0.json        -> READY_FOR_GATEWAY_SUBMISSION
  gateway_audit.jsonl-> POS 后 3 行     <-- 审计可用性正向对照
  navsim_goals.jsonl -> POS 后 1 行     <-- journal 可用性正向对照
```

没有 POS 对照，NEG 的"0 到达"就无法与"网关没跑 / 日志坏了"区分。本轮消除了这个歧义。

## 5. ON-06 的本轮实际后验状态

本轮：`PLANNER_RESULT_TIMEOUT`，Gateway 到达 **0**，NavSim Goal **0**。
报告不预设后验状态，也不把 TIMEOUT 记为 Gateway BLOCK。

## 6. 明确未达成的目标（不得混淆）

| 项 | 状态 | 原因 |
| --- | --- | --- |
| 三真实模块 LEVEL 3 正向准入 | **NOT ACHIEVED** | M1 无有效在线检测证据；M2 无生产可信当前身份 |
| M1 通信攻击检测有效性 | **未证明** | `duration_ms` 标签泄漏，上一轮结论已撤回 |
| M2 生产身份信任根 | **未就绪** | 对称 HMAC、同 UID、Action typesupport 未接线 |
| M2 研究组件作为身份信任根 | **禁止启用** | 越界读取虽已修复（`b0bf9cf`），仍不满足生产门槛 |

## 7. 与旧验收的差异（证据表述纠正）

旧 `scripts/int_limited_verification.py` 用受控 Mock 驱动 F0，
却把部分结论写成"三真实模块联合"，并用 `gateway_submission=null` 推断 Gateway 未收到。
本轮已纠正：

* 每个用例标注 `evidence_source=ADAPTER_UNIT_ONLY`；
* 第 8 项限定为"适配器层未提交"，并注明不等价于 Gateway 0 到达；
* 第 12 项注明只证明 F0 重复判定稳定，不含 Gateway 决策对照；
* 真实 Gateway/NavSim 结论全部来自本报告的真实在线证据。

旧用例全部保留，作为 F0 单元回归。

## 8. 环境与冻结资产

| 资产 | 状态 |
| --- | --- |
| `release/demo-2026-10-19-freeze` | 未改动（`6786ff89…`） |
| RC2 标签 `demo-2026-10-19-rc2-verified` | 未移动（`33cb4f93…`） |
| `main` / `baseline` | 未合入（`838f66f4…` / `a4c59716…`） |
| `rg_demo` 容器 | **未启动、未触碰**（运行前确认其已停止） |
| 正式 DDS 权限 `security/policies/**` | 未修改 |
| `config/task_policy.yaml` | 未修改 |
| 密钥材料 | 证据包内 0 个 `.pem`/`.key`/`.p7s` |
