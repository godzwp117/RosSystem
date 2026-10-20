# 三成员最终整合前状态日志

> **本文件是一次独立的状态快照，不是任何历史报告的一节。**
> 目标读者：下一位（或多个）负责三成员最终整合的智能体。
> 只读本文件即可知道：代码在哪、什么已验证、什么被阻断、下一步怎么做。

---

## 第 1 节：状态快照元数据

```yaml
snapshot_type: THREE_MEMBER_PREINTEGRATION
snapshot_date: "2026-10-20T15:27:16Z"
timezone: "UTC (容器与 Git 时间戳均取 UTC)"
repository: godzwp117/RosSystem
checked_branch: integration/three-member-preflight-2026-10-22
head_sha: "45e67a258255f70946e94f415fc51ba35918ea5b"
tested_code_sha: "45e67a258255f70946e94f415fc51ba35918ea5b"
archive_sha: "PENDING（归档提交将在本文件提交后产生）"
preintegration_branch_base: 45e67a258255f70946e94f415fc51ba35918ea5b
integration_ready: "CONDITIONAL"
three_real_level3: "BLOCKED"
evidence_run_id: "preflight-20261020T152617Z"
ros_distro: "ROS 2 Jazzy"
rmw: "rmw_fastrtps_cpp / Fast DDS 2.14.6"
docker_container: "rg_pre (ros:jazzy), online domain 72"
real_ros2_online_run_this_round: "部分（M3 extra 组真实运行；未重跑六场景全量）"
ci_status: "PENDING"
local_worktree_clean: "PASS（提交前已核对）"
```

### 本轮任务范围

只做**工程收尾与状态盘点**：核查分支、修复进程清理缺陷、跑回归、产出本状态日志。
**没有**进行三成员功能合流，**没有**修改安全策略，**没有**启用任何研究模型。

---

## 第 2 节：Git 分支与继承关系（全部实测）

### 2.1 任务提及但**不存在**的分支

| 分支 | 状态 |
| --- | --- |
| `research/m1-phase7-evidence-replay-closeout` | **NOT_FOUND** |
| `research/m2-action-production-hardening` | **NOT_FOUND** |
| `release/limited-integration-acceptance` | **NOT_FOUND** |
| `integration/final-deliverable-2026-10-22` | **NOT_FOUND** |

> 核验方式：`git rev-parse --verify -q origin/<branch>` 返回非零。
> **这四路后续研发均未产生可核验的远端提交**，因此不得作为整合输入。

### 2.2 实际存在的关键分支

| 分支 | SHA | 用途 | 含 F0 P0 | 含 M1 最新 | 含 M2 最新 | 建议纳入最终集成 |
| --- | --- | --- | --- | --- | --- | --- |
| `main` | `838f66f41821edf0421612a205d162ae8e9eb955` | 主干 | 否 | 否 | 否 | 否（受保护） |
| `baseline` | `a4c597161d254192b662ee7b8f4d17f76a89cc16` | 基线 | 否 | 否 | 否 | 否（受保护） |
| `release/demo-2026-10-19-freeze` | `71b57ff182bed0848f67d34b639dc6060d718f91` | 冻结演示 | 是 | 否 | 否 | 否（冻结） |
| `integration/three-real-limited-online-closure` | `86a8910bf4560dfe455bec09bc503600c30bf670` | 受限集成验收 | 是 | 部分 | 是 | 否（已被 M1 phase6 覆盖） |
| `research/m1-phase6-evaluation-observation` | `45e67a258255f70946e94f415fc51ba35918ea5b` | M1 最新 | 是 | 是 | 是 | **是（推荐起点）** |
| `research/m2-action-origin-binding` | `a1d699674204543afc8b15c88bd6df8c7da794de` | M2 最新 | **否** | 否 | 是 | 否（已并入 45e67a2） |
| `research/m1-graph-observation-dataset` | `4b216c4a04e655a9ac87255b3ef752d9d871c95f` | M1 第五轮 | 是 | 是 | 是 | 否（被 phase6 覆盖） |
| `integration/three-member-preflight-2026-10-22` | 见 HEAD | **本轮准备分支** | 是 | 是 | 是 | 是（含本轮修复） |

### 2.3 继承关系实测（关键，容易踩错）

| 检查 | 结果 |
| --- | --- |
| `86a8910` 是 M1 phase6 的祖先 | ✅ 是 |
| `86a8910` 是 M2 action-origin-binding 的祖先 | ❌ **不是** |
| M2 分支是否含 GUID 越界修复 `b0bf9cf` | ❌ **不含** |
| `45e67a2` 是否含 M2 最新 `a1d6996` | ✅ 含 |
| `45e67a2` 是否含 GUID 修复 `b0bf9cf` | ✅ 含 |
| `45e67a2` 是否含 F0 修复 `4e83f919` | ✅ 含 |
| `4e83f919` 是冻结演示的祖先 | ✅ 是 |

**结论（重要）**：**不要**直接合并 `research/m2-action-origin-binding`。
该分支不含 GUID 越界修复，也不含 F0 P0 与集成合并。
它的内容**已经**通过 `fb35162` 合并进 `86a8910`，并随 `45e67a2` 继承下来。
**`45e67a2` 是唯一同时含四方成果的已推送提交。**

---

## 第 3 节：三成员能力矩阵

| 模块 | 正式入口 | 已完成代码 | 最新研究 | 实际验证 | 生产准入 | 剩余阻断 |
| --- | --- | --- | --- | --- | --- | --- |
| **M1** 通信风险 | `modules/member1_comm/module.py` | 真实模块 + 49 维模型 + 窗口采集器 | 时间驱动双通道窗口、`m1_metrics` v2、融合诊断（`45e67a2`） | 进程可运行 ✅ Schema 合法 ✅ | **FAIL** | 模型有效性未过关；合法高负载误报；recon 融合后漏检；无速率授权基线 |
| **M2** 身份可信 | `identity_trust/assessor.py` | 历史授权评价 + 签名核验 | DDS `identity_token_` 观察、CandidateTask 前置入口、事件账本（`a1d6996`） | 进程可运行 ✅ Schema 合法 ✅ | **FAIL** | 无生产签发者；真实 SendGoal 未捕获；历史 AUTHORIZED ≠ 当前身份 |
| **M3** 任务风险 | `modules/member3_taskrisk/module.py` | 真实规则引擎 | — | 六场景在线实测 ✅ | **PASS（规则范围内）** | 无（脚本进程清理缺陷本轮已修） |

### 3.1 五项能力不可互相替代

| 能力 | M1 | M2 | M3 |
| --- | --- | --- | --- |
| 进程能运行 | ✅ | ✅ | ✅ |
| Schema 合法 | ✅ | ✅ | ✅ |
| 实验特征有效 | ⚠️ 图通道有效、消息通道有效，融合不稳定 | ⚠️ 研究级有效 | ✅ |
| 当前证据可信 | ❌ 模型未过门槛 | ❌ 无生产签发者 | ✅ |
| **允许正向准入** | ❌ | ❌ | ✅ |

---

## 第 4 节：完整安全架构与信任边界

```text
M1 通信风险 ──┐
M2 身份可信 ──┼──> F0 STRICT ──> Planner ──> SecurityGateway ──> NavigationSim
M3 任务风险 ──┘                                  │
                                            TaskPolicy
                                            ALLOW / BLOCK
```

DDS-Security 在**通信层**独立执行原生身份认证与资源权限控制，不经由 F0。

### 必须分别理解的等价关系（全部为「不等于」）

| 陈述 A | 不等于 | 陈述 B |
| --- | --- | --- |
| M1 `NORMAL` | ≠ | 准入授权（模型风险结论） |
| M2 历史 `AUTHORIZED` | ≠ | 当前请求可信身份 |
| M3 `ALLOW_RECOMMENDED` | ≠ | Gateway `ALLOW` |
| F0 `READY_FOR_GATEWAY_SUBMISSION` | ≠ | Gateway `ALLOW` |
| Planner `TIMEOUT` | ≠ | Gateway `BLOCK` |
| 正式 DDS Enforce | ≠ | 普通模式在线演示 |
| Mock 正向闭环 | ≠ | 三 External 正向闭环 |

---

## 第 5 节：目前能真实运行的系统能力

### A. 受控正向在线模式（演示主场景）

M1/M2 = 受控 Mock，M3 = 真实规则引擎。

已验证（历史 + 本轮部分复验）：F0 融合、Planner 提交、Gateway 独立 ALLOW/BLOCK、
NavigationSim Goal、Gateway audit、NavSim journal。

### B. 三真实严格安全模式

M1/M2/M3 全部 `external`。本轮容器内实测（历史同源）：

| 模块 | 模式 | 退出码 | 状态 | Schema |
| --- | --- | --- | --- | --- |
| `comm_risk` | external | 0 | `UNKNOWN` | 合法 |
| `identity_trust` | external | 0 | `AUTHORIZED`（历史解释） | 合法 |
| `task_risk` | external | 0 | `ALLOW_RECOMMENDED` | 合法 |

F0 → `ADAPTER_BLOCK` / `ADAPTER_MODULE_STATUS_NOT_PROCEED`。
**这是预期安全结果，不是系统崩溃。**

### C. DDS Enforce

正式权限 7/7（S1/S2/S3/S3C/S4/S5/S6）在冻结提交上实测通过（本轮未重跑，标 HISTORICAL_VERIFIED_EVIDENCE）。

### D. 三真实正向 LEVEL 3

**`BLOCKED`**。A、B、C 的独立结果**不得**拼成 D 的 PASS。

---

## 第 6 节：测试与证据总表

> 纪律：**不同 SHA 的通过数字不得混用**。「本轮」= 在 `45e67a2` 上实跑；「历史」= 其它 SHA 的已归档证据。

| # | 测试 | 分支 / SHA | run_id | 环境 | 本轮/历史 | 结果 | 适用范围 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 公共契约 `validate_team_contracts.py --all` | preflight / `45e67a2` | `preflight-20261020T152617Z` | 宿主 venv | **本轮** | **PASS** | 全仓 Schema |
| 2 | F0 P0 安全反例（2 文件） | 同上 | `preflight-20261020T152617Z` | 宿主 | **本轮** | **38 passed** | F0 身份边界 |
| 3 | 全仓单元测试 | 同上 | `preflight-20261020T152617Z` | 宿主 | **本轮** | **809 passed / 4 skipped / exit 0** | 全仓 |
| 4 | M1/M2/M3 关键回归（4 文件） | 同上 | `preflight-20261020T152617Z` | 宿主 | **本轮** | **141 passed / 1 skipped** | GUID 越界 + 指标语义 + 双通道窗口 + M3 规则 |
| 5 | m3_online_extra.sh 残留清理 | 同上 | `preflight-20261020T152617Z` | `rg_pre` / domain 72 | **本轮** | **STRAY_GROUPS=0, exit 0** | 进程清理 |
| 6 | M3 在线六场景 ON-01..06 | freeze / `be47ccd` | `freeze-verify-20261020T134804Z` | `rg_freeze` / 71 | 历史 | **19 checks / 0 failures / PASS** | M3 在线 |
| 7 | 三真实 External 联合调用 | freeze / `be47ccd` | 同上 | 同上 | 历史 | CALLED=PASS / VALIDATED=PASS / PROCEED=**BLOCKED** | 三真实 |
| 8 | DDS Enforce 7/7 | freeze / `be47ccd` | 同上 | 正式域 42/43 | 历史 | **7/7 PASS** | 正式权限 |
| 9 | M1 双通道窗口 + 指标语义 | phase6 / `45e67a2` | `m1p6-20261020T123752Z` | `rg_m1p6` / 70 | 历史 | 26 + 16 项 PASS | M1 研究 |
| 10 | M1 30 会话采集与 v2 评估 | phase6 / `45e67a2` | 同上 | 同上 | 历史 | 30 会话；`INSUFFICIENT_EVIDENCE` | M1 研究 |
| 11 | M2 DDS 身份 / 账本 | m2 / `a1d6996` | `m2p3-20261019T033811Z` | `rg_m2p3` / 60 | 历史 | 9/9 受控实验 PASS | M2 研究 |

**证据根目录**：`artifacts/integration/three-member-preflight/preflight-20261020T152617Z/`

---

## 第 7 节：遗留缺陷与风险

| # | 问题 | 影响 | 严重度 | 位置 | 状态 | 责任 | 阻断演示 | 阻断 LEVEL3 | 阻断报告 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| R1 | M1 模型有效性未过关（合法 1000 Hz 被全线误报；recon 融合后召回 0） | 不能作为准入依据 | 高 | `docs/research/M1_PHASE6_*` | 未解决 | M1 | 否 | **是** | 否 |
| R2 | M1 观测盲区：纯查询侦察不可见、短命端点漏采、图不反映消息洪泛 | 检测覆盖不完整 | 中 | 同上 | 已量化、未解决 | M1 | 否 | **是** | 否 |
| R3 | M1 无可信 Action 请求计数 | 缺业务级特征 | 中 | — | BLOCKED（依赖 M2） | M2→M1 | 否 | **是** | 否 |
| R4 | 无速率授权基线（`task_policy.yaml` 与 DDS 权限均无速率定义） | 合法高负载与洪泛在观测上不可区分 | 高 | `config/task_policy.yaml` | 未解决 | 集成 | 否 | **是** | 否 |
| R5 | M2 无生产签发者（对称 HMAC、同 UID、无审批/撤销） | 不能作为身份信任根 | 高 | `scripts/m2_issue_attestation.py` | 未解决 | M2 | 否 | **是** | 否 |
| R6 | M2 真实 Action `send_goal` 未捕获（仅 CandidateTask 入口） | 请求级身份绑定不完整 | 高 | `src/m2_witness/**` | 未解决 | M2 | 否 | **是** | 否 |
| R7 | `m3_online_extra.sh` 残留进程 | 演示后需人工确认 | 中 | `scripts/m3_online_extra.sh` | **本轮已修**（trap + 幂等 cleanup + 残留非零退出） | 集成 | 否 | 否 | 否 |
| R7b | 该脚本 SIGTERM 早退路径未获**确定性**实测（TERM 打到了子 shell） | 修复正确性证据不完整 | 低 | 同上 | 部分验证 | 集成 | 否 | 否 | 否 |
| R8 | M1 phase6 的 `raw_events` 只保留最近 20000 条，且窗口末事件可能不在快照内 | 极高频场景复算不完全 | 低 | `window_aggregator.py` | 已记录 | M1 | 否 | 否 | 否 |
| R9 | 图覆盖率用"首末轮询跨度"估算，两次轮询之间的空洞无法识别 | 可能高估覆盖 | 中 | 同上 | 已记录 | M1 | 否 | 否 | 否 |
| R10 | M2 研究分支不含 GUID 越界修复与 F0 P0 | **若直接合并 M2 分支会回退安全修复** | **高** | 分支拓扑 | 已识别，用 `45e67a2` 规避 | 集成 | 否 | **是** | 否 |

---

## 第 8 节：最终合流建议（**仅计划，本轮不执行**）

1. **推荐最终整合起点 SHA**：`45e67a258255f70946e94f415fc51ba35918ea5b`
   （唯一同时含 M1 最新 + M2 最新 + GUID 修复 + F0 P0 的已推送提交）
2. **M1 应吸收**：`45e67a2`（即起点本身，已含 `d5f03af`→`4b216c4`→`45e67a2` 全部）
3. **M2 应吸收**：`a1d6996` —— 但**必须通过 `45e67a2` 继承，不得直接 merge M2 分支**（见 R10）
4. **M3 使用**：`modules/member3_taskrisk/module.py`，即 `45e67a2` 中的版本（与冻结演示一致）
5. **F0 基准**：`scripts/team_demo.py` @ `45e67a2`（含 `4e83f919` 的 P0 修复）
6. **可能冲突的文件**：
   - `scripts/m3_online_extra.sh`（本轮已改）
   - `scripts/m1_phase5_experiments.py`（容器可覆盖）
   - `docs/integration/*`（多处新增，一般不冲突）
7. **禁止改动**：`main`、`baseline`、`release/demo-2026-10-19-freeze`、RC2 标签、
   `user/**`、`config/task_policy.yaml`、`security/policies/**`、正式 keystore、
   F0 身份判定规则、Gateway 决策规则
8. **只归档不部署**：M1 全部研究模型（未导出）、M2 `src/m2_witness/**`、
   M1 `scripts/m1_*` 研究工具
9. **必须保持严格失败关闭**：`config/team_modules.three-real.yaml`
   （M1/M2 UNKNOWN → F0 BLOCK，不得改成 mock）
10. **集成后必须重跑**：契约、全仓单测、F0 P0 38 项、三真实 External、
    M3 六场景、DDS Enforce 7/7、进程清理回归
11. **如何验证未污染冻结演示**：
    `git merge-base --is-ancestor release/demo-2026-10-19-freeze <新分支>` 应为**假**；
    `git diff --stat release/demo-2026-10-19-freeze..<新分支> -- user/ config/task_policy.yaml security/` 应为空
12. **批准最终系统验收的条件**：
    - 三真实 External 的 CALLED/VALIDATED 保持 PASS；
    - `THREE_REAL_LEVEL3_READY` 仍为 BLOCKED 时**不得**宣称 LEVEL 3；
    - 所有本轮 PASS 项在新分支上重跑通过；
    - 无新增安全回退。

---

## 第 9 节：10 月 22 日交付准备度

| 维度 | 评价 |
| --- | --- |
| 代码能否提交 | ✅ 可（分支干净、CI 可跑） |
| 统一执行入口 | ✅ `scripts/demo_20261019_release.sh` + `m3_online_drive/extra.sh` |
| 文档齐全度 | ✅ 演示 4 件套 + 研究 10+ 篇 + 本状态日志 |
| 实际功能可运行 | ✅ 受控闭环与三真实调用均可运行 |
| 安全测试证据 | ✅ F0 P0 38、DDS 7/7、契约、809 单测 |
| M1/M2 限制如实记录 | ✅ 多份报告与本节 R1–R6 |
| 可引用成果 | 三真实集成、F0 P0、DDS Enforce、M3 在线、M1 观测体系、M2 身份研究 |
| 可作后续工作 | M1 模型、M2 签发者、速率授权基线 |
| 关键阻断 | **无阻断交付的问题**；有阻断 LEVEL 3 的问题（R1–R6、R10） |

### 两个独立等级

- **`CONTROLLED_SYSTEM_DELIVERY_READY` = PASS**
  （受控演示可交付，证据齐全，回退路径存在）
- **`THREE_REAL_LEVEL3_READY` = BLOCKED**
  （M1 模型无效 + M2 无生产签发者 + 无速率授权基线）

---

## 第 10 节：下一位集成智能体直接使用的输入清单

```text
推荐起点 SHA：45e67a258255f70946e94f415fc51ba35918ea5b
M1 来源分支/SHA：research/m1-phase6-evaluation-observation @ 45e67a2（已含于起点）
M2 来源分支/SHA：research/m2-action-origin-binding @ a1d6996（已含于起点；禁止直接 merge）
M3 来源：modules/member3_taskrisk/module.py @ 45e67a2
F0 来源：scripts/team_demo.py @ 45e67a2（含 4e83f919 P0 修复）
Gateway 来源：src/rg_gateway/** @ 45e67a2（权威，不改）
DDS 权限来源：security/policies/minimal_permissions.xml（正式，不改）
禁止改动路径：user/** config/task_policy.yaml security/policies/** security/keystore/**
             src/rg_gateway/** scripts/team_demo.py 的身份判定规则
必须保留配置：config/team_modules.three-real.yaml（严格失败关闭）
可复用脚本：scripts/demo_20261019_release.sh
           scripts/m3_online_drive.sh scripts/m3_online_extra.sh（本轮已修清理）
           scripts/verify_m3_online_evidence.py scripts/int_online_downstream_check.sh
           scripts/m1_*（研究，仅归档不部署）
必须修复的阻断：R4（速率授权基线）、R5/R6（M2 签发者与 SendGoal）、R1（M1 模型）
必跑测试：契约 / 全仓单测 / F0 P0 38 / 三真实 External / M3 六场景 / DDS 7/7 / 进程清理
已知实验环境：rg_demo(56/43 冻结) rg_pre(72) rg_freeze(71/42/43) rg_m1p6(70) rg_m2p3(60)
证据根目录：artifacts/integration/three-member-preflight/<run_id>/
           artifacts/demo-2026-10-19/freeze-verify-<run_id>/
           artifacts/research/m1-phase6/<run_id>/
最终交付要求：受控演示可用 + 能力边界如实 + 不得宣称 LEVEL 3
```

### 明确不可作为整合输入的条目

| 条目 | 原因 |
| --- | --- |
| `research/m1-phase7-evidence-replay-closeout` | **NOT_FOUND** |
| `research/m2-action-production-hardening` | **NOT_FOUND** |
| `release/limited-integration-acceptance` | **NOT_FOUND** |
| `integration/final-deliverable-2026-10-22` | **NOT_FOUND** |
| 任何本地未推送的研究工作 | 未形成远端固定版本，不可作为整合输入 |
