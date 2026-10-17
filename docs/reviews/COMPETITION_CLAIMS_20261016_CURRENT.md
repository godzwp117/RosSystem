# 竞赛声明口径（2026-10-16 当前版本）

> 本文是 **2026-10-16** 的当前声明口径，**不覆盖**
> `docs/reviews/member-deliveries/COMPETITION_CLAIMS.md`（较早的独立审查快照）。
> 两份文档各自对其日期与 SHA 有效；如冲突以**本文**为准（更新、且含本轮在线实证）。
>
> 契约：`PROPOSED_V1` / `1.0.0-proposed`（**未冻结**）。
> 本轮在线证据：`artifacts/demo-2026-10-19/m3-online-m3online-20261016T134406Z/`

---

## 1. 研究能力声明表

| 研究能力 | 是否可以声明 | 必要限定 |
| --- | --- | --- |
| **ROS 2 Gateway 权威准入** | ✅ **可以声明** | 受控 NavigationSim 环境；`READY_FOR_GATEWAY_SUBMISSION ≠ Gateway ALLOW`；`Gateway ALLOW ≠ 导航执行成功` |
| **DDS-Security Enforce 最小权限** | ✅ **可以声明** | Jazzy + Fast DDS + 本仓库特定策略（域 43）；仅限受控实验范围内的结论 |
| **M3 任务风险规则推理** | ✅ **可以声明**（本轮新增在线证据） | 规则型**建议**模块，不是 Gateway；本轮在线组合中 M1/M2 仍为显式 Mock |
| **M2 DDS 身份权限分析** | ⚠️ **限定声明** | 历史受控 DDS 证据的**解释**，不是对当前请求的实时身份认证 |
| **M1 ROSPaCe 通信检测** | ⚠️ **限定声明** | **离线实验原型，性能门槛未通过**；不得声称有效检测能力 |
| **三模块全真实联合** | ❌ **暂不可声明** | 尚无完整实测（M1 缺模型、M2 对候选入口恒 UNKNOWN） |
| **ROS 2 实时入侵检测** | ❌ **暂不可声明** | 在线特征采集未完成；`RUNTIME_MONITOR=NOT_READY` |
| **DDS 动态权限调整** | ❌ **暂不可声明为已实现** | 尚无动态切换的真实集成证据；当前仅为静态最小权限 |
| **动态任务状态机** | ❌ **暂不可声明** | 独立分支 `feature/m3-dynamic-policy` 与 baseline 互不包含，模块自述 `NOT_INTEGRATED` |

---

## 2. 允许升级的表述（因本轮在线联调成功）

M3 在线联调已在 ROS 2 Jazzy 受控环境中完成（ON-01..ON-06），因此**允许**使用如下表述：

> **真实任务风险模块已在 ROS 2 Jazzy 受控环境中参与候选任务准入链路，适配层与
> Gateway 实现分层检查，并通过 NavigationSim 验证合法执行与越权阻断。**

**必须同时注明**：该在线组合中 **M1 与 M2 仍为显式 Mock**。

**不能**升级为：

> ❌ "三个研究模块全部真实联合防御。"
> ❌ "系统已完成端到端实时入侵检测。"
> ❌ "已实现动态最小权限自动调整。"

---

## 3. 支持上述声明的具体证据

| 声明 | 证据 | 位置 |
| --- | --- | --- |
| Gateway 权威准入 | ON-01：`ALLOW`/`ALLOW_IN_POLICY` + Action `EXECUTED` + NavigationSim **+1 Goal** | 本轮在线证据 `stack-a/f0_ON01.json`、`gateway_audit.jsonl`、`navsim_goals.jsonl` |
| 越权阻断（模块侧） | ON-02：M3 `BLOCK_RECOMMENDED` → `ADAPTER_BLOCK`，Planner **未启动**，Goal **0** | 同上 |
| 失败关闭（UNKNOWN/ERROR） | ON-03 / ON-04：策略缺失→`UNKNOWN`、策略损坏→`ERROR`，均阻断且 Goal **0** | 同上 |
| **Gateway 独立权威** | ON-05：M3 依 TEST_ONLY 外扩策略给出 `ALLOW_RECOMMENDED`、适配层放行，Gateway 仍 `BLOCK/OUT_OF_REGION`，Goal **0** | 同上 |
| 超时语义 | ON-06：Planner `PLANNER_RESULT_TIMEOUT`，**未**记为 Gateway BLOCK、未自动重试；同时该请求实际已被 Gateway `ALLOW` 并 `EXECUTED`，NavigationSim 记 1 条 Goal ——**超时 ≠ 未收到 ≠ BLOCK ≠ 未执行**，客户端观测与权威执行事实分别判定 | 同上 |
| 跨层可审计 | 独立复核工具 19 项检查 **全部 PASS / 0 失败** | `verification.json` / `verification.md` |
| DDS-Security Enforce | 域 43 S1–S6 **7/7 PASS**，含原生拒绝 + 正向对照 | `dds-security-regression/` |

---

## 4. 六项关键能力的裁定（更新版）

| # | 待裁定能力 | 裁定 | 依据 |
| --- | --- | --- | --- |
| 1 | 已实现实时在线检测 | ❌ **否** | M1 `RUNTIME_MONITOR=NOT_READY`；无在线特征采集代码 |
| 2 | 已实现 DDS 动态权限调整 | ❌ **否** | 仅静态最小权限；无动态切换证据 |
| 3 | 有真实三模块联合实验 | ❌ **否** | 最完整形态是 **M3 真实 + M1/M2 显式 Mock**（本轮在线验证） |
| 4 | 有模型泛化证据 | ❌ **否** | M1 两数据集 F1 均**低于恒预测攻击基线**，门槛 FAIL，且仅覆盖 1 类攻击 |
| 5 | 可声称系统级防护有效 | ⚠️ **需严格限定** | 可声明：Gateway 权威准入与越权阻断、DDS 最小权限原生拒绝均已受控实证。**不可**声明：端到端防护已在真实在线流量下验证有效 |
| 6 | 动态任务状态机已集成 | ❌ **否** | 独立分支未集成；模块自述 `dynamic_state_model: NOT_INTEGRATED` |

---

## 5. M1 性能口径（G1）

| 数据集 | F1 | 恒预测攻击基线 F1 | 门槛 |
| --- | --- | --- | --- |
| ROSPaCe reduced | **0.1312** | 0.8132 | **FAIL** |
| ROSPaCe reduced noperiodicity | **0.6346** | 0.8719 | **FAIL** |

**禁止**只展示 0.6346 并声称模型效果良好。
**禁止**声称六类攻击已完成有效评测（当前测试集仅含 1 类攻击）。
**必须**同时给出恒预测攻击基线，以体现该二分类器**低于平凡策略**。

---

## 6. M2 真实性口径（G2）

成员二是**历史 SROS 2 证据解释器**：

- ✅ 可以说明：它能核验历史权限配置与原生 DDS 拒绝信息，并做正反对照。
- ❌ 不能说明：它能认定**当前**请求已完成 DDS 身份认证。
- ❌ 不能把 `AUTHORIZED` 表述为"当前请求已通过认证"——它只表示**所引用历史实验中访问成功**。
- ❌ 不能把 `request_id`、`declared_enclave`、业务 JSON 自报身份当作 DDS 身份证明。

---

## 7. M3 真实性口径（G3）

成员三是**确定性可解释任务风险规则引擎**。

| ✅ 准确描述 | ❌ 禁止描述 |
| --- | --- |
| 任务策略匹配 | 深度学习模型 |
| 越权行为识别 | 神经网络 |
| 可解释风险建议（`rule_basis` 列出违反条款） | 未知攻击预测模型 |
| 任务边界距离（signed boundary margin） | 已完成动态 DDS 权限切换的算法 |
| 与 Gateway 的分层裁决 | 最终授权模块 |

**M3 输出 `ALLOW_RECOMMENDED` 不是执行许可**；本轮 ON-05 已实证 Gateway 可在 M3 建议允许时独立拒绝。

---

## 8. 禁止声明清单（硬性）

以下表述**一律不得出现**在报告、PPT、演示或论文中：

1. ❌ "三个研究模块全部真实联合防御。"
2. ❌ "已实现 ROS 2 实时入侵检测 / 在线 IDS。"
3. ❌ "已实现 DDS 动态最小权限自动调整。"
4. ❌ "成员一模型检测效果良好 / 已可用。"（其 F1 低于平凡基线且门槛 FAIL）
5. ❌ "成员二可认定当前请求的 DDS 身份。"
6. ❌ "Gateway ALLOW 即表示导航已成功执行。"
7. ❌ "适配层 READY 等于 Gateway 允许。"
8. ❌ "六类攻击均已有效评测。"
9. ❌ "动态任务状态机已完成集成。"
10. ❌ 任何把 Mock / 测试替身 / 离线模型表述为真实在线算法能力的说法。
11. ❌ "Planner 超时说明请求未被执行 / 未被 Gateway 接收 / 被安全策略拒绝。"
    （2026-10-16 在线实测的 ON-06 中，超时请求**已**被 Gateway `ALLOW` 且**已执行**；
    客户端超时只说明客户端未在窗口内观测到终态。）

---

## 9. 本轮新增的可声明边界

| 项 | 说明 |
| --- | --- |
| 适配层输入拒绝的可证伪性 | 已验证"明确输入拒绝"（JSON + `ADAPTER_BLOCK` + `ADAPTER_INPUT_INVALID` + rc=3 + 0 模块调用），且**不再**把崩溃/依赖缺失/配置错误记为输入拒绝 |
| `event_id` 契约解释 | `event_id` 是唯一事件标识（审计去重），**不承担**完整 `request_id` 的编码责任；跨层关联以显式 `run_id`/`request_id` 字段为准 |
| 在线证据可复核性 | 提供独立工具 `scripts/verify_m3_online_evidence.py`，含 5 类篡改反例测试，能发现串单、伪造 Goal、缺失事件、时间倒序 |

---

## 10. 引用规范

- 引用版本请用**标签或完整 SHA**，不要用浮动分支名。
- 本轮在线证据 SHA-256 清单：`artifacts/demo-2026-10-19/m3-online-m3online-20261016T134406Z/SHA256SUMS.txt`
- 历史声明口径：`docs/reviews/member-deliveries/COMPETITION_CLAIMS.md`（较早快照，未改动）
