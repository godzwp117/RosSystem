# 2026-10-19 演示候选最终复验报告

> 契约：`PROPOSED_V1` / `1.0.0-proposed`（**未冻结**）
> 本报告全部数据来自**同一次** `scripts/final_verify_demo.py` 执行，
> 受测版本为单一 SHA，原始结果见证据目录 `test_results.json`。

---

## 1. 实测 SHA 与版本

| 项 | 值 |
| --- | --- |
| **受测 SHA（复验实际测定）** | **`f6574acbf51062a96a918ac3096e7aecf83371c6`**（不可变事实） |
| rc2 Tip（受测 SHA + 本文档与证据） | 通过标签解析：`git rev-parse demo-2026-10-19-rc2-verified^{commit}` |
| 分支 | `demo/2026-10-19-rc2`（**唯一演示候选**） |
| 工作区状态 | **干净**（`git status --porcelain` 除本地 `user/` 外为空） |
| 复验 run_id | `final-20261017T131601Z` |
| 证据目录 | `artifacts/demo-2026-10-19/final-review-final-20261017T131601Z/` |

`GIT-02` 显式要求"受测代码 == 提交内容"；**有未提交改动时该检查 FAIL**，
因此本报告的证据不可能被归因到错误的提交。

### 1.1 继承来源

```
baseline a4c5971
  └── chore/member-deliveries 3ce8202
        └── fix/m2-m3-acceptance 19f6a25
              └── integration/m3-online-evidence-20261016 (ec4258a, 含 ON-06 勘误)
                    └── demo/2026-10-19-rc2  f6574ac  ← 本报告受测版本
```

---

## 2. 运行环境

| 项 | 值 |
| --- | --- |
| 宿主 | WSL2 / Linux x86_64 |
| 容器 | `rg_jazzy`（`ros:jazzy`）/ Ubuntu 24.04 |
| ROS_DISTRO | `jazzy` |
| RMW_IMPLEMENTATION | `rmw_fastrtps_cpp` |
| ROS_DOMAIN_ID（在线联调 L3） | **42**（普通模式） |
| ROS_DOMAIN_ID（DDS 回归 L4） | **43**（Enforce） |
| DDS 安全模式（L3） | **disabled**（普通模式，未启用 DDS-Security） |
| DDS 安全模式（L4） | **enforce** |
| 容器内 Python | 3.12.3 |
| 宿主 Python | 3.10.12（`.research-venv`） |
| ROS 2 包 | 4 个（`rg_interfaces`/`rg_policy`/`rg_gateway`/`rg_demo_nodes`）可加载 |
| 模块配置（L3） | `comm_risk=MOCK`、`identity_trust=MOCK`、`task_risk=EXTERNAL` |

> **L3 与 L4 是两次独立运行**，不是同一次 Enforce 在线全链路实验。

---

## 3. 全部运行命令与实际返回码

| 层次 | ID | 命令（摘要） | 返回码 | 结果 | 耗时 |
| --- | --- | --- | --- | --- | --- |
| L0 | GIT-01 | `git rev-parse HEAD` / `git status --porcelain` | 0 | **PASS** | — |
| L0 | GIT-02 | 同上（要求工作区干净） | 0 | **PASS** | — |
| L1 | L1-01 | `python3 scripts/validate_team_contracts.py --all` | 0 | **PASS** | 0.1s |
| L1 | L1-02 | `pytest tests/unit/test_member_module_strictness.py -q` | 0 | **PASS**（27） | 10.1s |
| L1 | L1-03 | `pytest tests/unit/test_adp01_input_rejection.py -q` | 0 | **PASS**（16） | 1.4s |
| L1 | L1-04 | `pytest tests/unit/test_event_id_contract_boundaries.py -q` | 0 | **PASS**（37） | 5.1s |
| L1 | L1-05 | `pytest tests/unit/test_m3_online_evidence_counterexamples.py -q` | 0 | **PASS**（14） | 0.1s |
| L1 | L1-06 | `pytest tests/unit/test_on06_report_claims.py -q` | 0 | **PASS**（15） | 0.1s |
| L1 | L1-00 | `pytest tests/unit -q`（全仓） | 0 | **PASS**（**657 passed, 3 skipped**） | 516.8s |
| L2 | L2-01 | `check_member_module.py --module identity_trust --real-fixture …` | 0 | **PASS**（58/3/1/1，`meets_pr_gate=True`） | 2.3s |
| L2 | L2-02 | `check_member_module.py --module task_risk --real-fixture …` | 0 | **PASS**（58/3/1/1，`meets_pr_gate=True`） | 2.6s |
| L3 | L3-01 | `bash scripts/run_demo.sh` | 0 | **PASS**（`DEMO RESULT: PASS`） | 6.8s |
| L3 | L3-02 | 容器内 `bash scripts/m3_online_drive.sh <run> …`（ON-01/02/05） | 0 | **PASS** | 6.0s |
| L3 | L3-03 | 容器内 `bash scripts/m3_online_extra.sh <run> …`（ON-03/04/06） | 0 | **PASS** | 4.9s |
| L3 | L3-04 | 回收两组证据到工作区 | 0 | **PASS** | 0.03s |
| L3 | L3-05 | `verify_m3_online_evidence.py --run-dir … --claims …` | 0 | **PASS**（46 检查，0 失败） | 0.02s |
| L4 | L4-01 | 容器内 `sros2_check.py --run-id rc2-regression` | 0 | **PASS**（S1–S6 7/7） | 12.1s |

**汇总：17 项检查全部 PASS，0 FAIL。**

> 历史报告中的 `575 passed, 3 skipped` 仅作对照基线；
> 本轮在同一 SHA 上实跑得到 **657 passed, 3 skipped**（新增测试来自
> ON-06 复发防护、ADP-01 反例、event_id 边界与在线证据反例）。

---

## 4. L1 / L2 / L3 / L4 状态

| 层次 | 内容 | 状态 |
| --- | --- | --- |
| **L1_PROTOCOL** | 契约、Schema、验收器严格性、ID 关联、证据篡改反例 | **PASS** |
| **L2_ALGORITHM** | M2 / M3 真实模块验收（离线真实算法 + 真实证据） | **PASS** |
| **L3_ROS2** | Gateway/NavigationSim A/B + M3 在线六场景（域 42 普通模式） | **PASS** |
| **L4_DDS** | DDS-Security Enforce S1–S6（域 43） | **PASS** |

### 4.1 关于 `58 PASS / 3 FAIL / 1 NOT_RUN / 1 BLOCKED`

M2 与 M3 的验收报告均含 **3 个非门槛 FAIL**（`STATE-BLOCK` / `STATE-UNKNOWN` /
`STATE-ERROR`）—— 那是"Mock 场景开关对不解析该开关的真实模块不适用"的记录。
它们**保留可见**（`mandatory=False`、`gate=False`、
`applicability=NOT_APPLICABLE_REAL_MODULE`），
门槛由 `REAL-STATE-*` 承担，且 `meets_pr_gate=True`。
**未删除、未改成 PASS。**

`1 NOT_RUN`（L2 真实算法层的人工确认项）与 `1 BLOCKED`（L3 独立容器联调声明项）
为脚本内既有的层次声明，非本轮失败。

---

## 5. M3 在线六场景结果（本轮实测）

`run_id`（第一组）：`rc2-final-20261017T131601Z`
`run_id`（第二组）：`rc2b-final-20261017T131601Z`

| 场景 | request_id | M3 状态 | 适配层 | Planner outcome | Gateway 到达 | Gateway 决策 | 执行 | Goal |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **ON-01** | `on01-legal-allow-rc2-final-…` | `ALLOW_RECOMMENDED` | `READY_FOR_GATEWAY_SUBMISSION` | `PLANNER_RESULT_RECEIVED` | 1 | **ALLOW** / `ALLOW_IN_POLICY` | 1 | **1** |
| **ON-02** | `on02-oor-block-rc2-final-…` | `BLOCK_RECOMMENDED` | `ADAPTER_BLOCK` | 未启动 | **0** | — | 0 | **0** |
| **ON-03** | `on03-rc2b-final-…` | `UNKNOWN` | `ADAPTER_BLOCK` | 未启动 | **0** | — | 0 | **0** |
| **ON-04** | `on04-rc2b-final-…` | `ERROR` | `ADAPTER_BLOCK` | 未启动 | **0** | — | 0 | **0** |
| **ON-05** | `on05-gateway-authority-rc2-final-…` | `ALLOW_RECOMMENDED` | `READY_FOR_GATEWAY_SUBMISSION` | `PLANNER_RESULT_RECEIVED` | 1 | **BLOCK** / `OUT_OF_REGION` | 0 | **0** |
| **ON-06** | `on06-rc2b-final-…` | `ALLOW_RECOMMENDED` | `READY_FOR_GATEWAY_SUBMISSION` | **`PLANNER_RESULT_TIMEOUT`** | **1** | **ALLOW** / `ALLOW_IN_POLICY` | **1** | **1** |

独立复核：**46 项检查，0 失败**，`claims_checked = true`（含 ON-06 声明对账）。

### 5.1 ON-06 的实测结论（勘误后，本重复现）

本轮 ON-06 **再次复现**了与 2026-10-16 相同的事实结构：

- Planner 在 0.5s 内未返回终态 → `PLANNER_RESULT_TIMEOUT`；
- 但该请求**确实到达 Gateway**（1 条 `RosCommEvent`）；
- Gateway 决策为 **`ALLOW` / `ALLOW_IN_POLICY`**；
- 已产生 **1 条 `ExecutionEvent`**（`success=true`/`EXECUTED`）；
- NavigationSim 记录 **1 条 Goal**。

**正确表述**：Planner 超时仅表示**客户端未在窗口内观测到终态**；
请求是否到达、是否被允许、是否已执行，必须逐 `request_id` 依据 Gateway 权威审计与
NavigationSim journal 判定。**超时 ≠ 未收到 ≠ BLOCK ≠ 未执行。**

**不得推广**：本条是本次观测，不能推出"所有 Planner 超时都会执行"；
也不能据此认为超时后的执行一定安全或一定异常。

> 本轮**没有**为了匹配旧报告而修改任何原始日志；ON-06 由新 `run_id` 重新执行并
> 单独留证。

---

## 6. DDS-Security Enforce 7 项安全回归（独立于 L3）

| 场景 | 结果 |
| --- | --- |
| S1 普通模式 A 区请求（域 42，未启用安全） | PASS |
| S2 Enforce 模式合法请求：Planner→Gateway→NavigationSim | PASS |
| S5 Enforce 模式 B 区越界：身份合法但 TaskPolicy 拒绝 | PASS |
| **S3C 正向对照：`/gateway` 直连执行接口成功** | PASS |
| **S3 Enforce：`/planner` 直连执行接口被拒绝** | PASS |
| **S4 无授权身份访问执行接口被拒绝** | PASS |
| S6 安全配置失效不静默回退 | PASS |

**`SROS2 SUMMARY (7 passed / 7 total)`，返回码 0，域 43。**

- Enforce **实际启用**（非 Permissive）。
- 最小权限**未放宽**：`security/policies/minimal_permissions.xml` 与
  `config/task_policy.yaml` 在本轮 `git diff` 中均为 **0 改动**。
- keystore 复用既有（未重建、未覆盖）。
- 下游 Goal 数量符合预期（S3/S4 为 0，S2/S3C 各 1）。

### 6.1 与 L3 的关系（必须分开陈述）

| | L3 在线 M3 联调 | L4 DDS 回归 |
| --- | --- | --- |
| 域 | 42 | 43 |
| DDS-Security | **disabled（普通模式）** | **enforce** |
| 内容 | M3 EXTERNAL 参与准入链 | S1–S6 权限正反对照 |

**二者不是同一次运行。** 对外只能声明
"普通模式下真实 M3 在线集成 + 独立 Enforce 安全对照"，
**不能**声称同一次 Enforce 在线全链路已完成。
本轮**未**把 M3 在线链路迁移到 Enforce（`NOT_RUN`）。

---

## 7. 测试数量

| 项 | 数量 |
| --- | --- |
| 复验检查项（L0–L4） | **17**，全部 PASS |
| 全仓 Python 单元测试 | **657 passed / 3 skipped** |
| 验收器严格性反例 | 27 |
| ADP-01 输入拒绝反例 | 16 |
| event_id / request_id 边界 | 37 |
| 在线证据篡改反例 | 14 |
| ON-06 报告声明对账反例 | 15 |
| M2 真实验收 | 58 PASS / 3 非门槛 FAIL，gate=True |
| M3 真实验收 | 58 PASS / 3 非门槛 FAIL，gate=True |
| 在线跨层复核 | 46 检查 / 0 失败 |

---

## 8. 核心安全不变量（逐条确认）

| # | 不变量 | 本轮证据 | 结论 |
| --- | --- | --- | --- |
| 1 | Gateway 拒绝后不产生非法执行 Goal | ON-05：`BLOCK/OUT_OF_REGION`，Goal **0** | ✅ |
| 2 | DDS 权限未意外放宽 | 最小权限核验 PASS；策略文件 0 改动 | ✅ |
| 3 | M3 BLOCK 不进入 Gateway | ON-02：到达 **0**、Goal **0** | ✅ |
| 4 | UNKNOWN / ERROR 不进入 Gateway | ON-03/ON-04：到达 **0**、Goal **0** | ✅ |
| 5 | 适配器输入拒绝不能靠崩溃假通过 | ADP-N01..N08 + 旧表达式证伪测试 | ✅ |
| 6 | 模块非零退出不能假通过 | REAL-STATE `returncode_ok` 反例 | ✅ |
| 7 | Planner 超时不能假装 Gateway BLOCK | ON-06 + `TIMEOUT_MISREPORTED_AS_BLOCK` | ✅ |
| 8 | `request_id` 不一致不能算成功关联 | 证据反例 `REQUEST_ID_MISMATCH` / `ORPHAN_*` | ✅ |
| 9 | 原始日志缺失不能被视作 0 次执行 | 反例：清空审计日志 → FAIL | ✅ |
| 10 | DDS 原生拒绝必须有正向对照 | S3C 成功 + S3/S4 原生 `not found in allow rule` | ✅ |
| 11 | 证据校验器能发现被篡改数据 | 14 项篡改反例全部检出 | ✅ |
| 12 | 报告表述与原始证据一致 | claims 对账 46 检查 0 失败 | ✅ |

---

## 9. 未解决的问题

| # | 问题 | 影响 | 状态 |
| --- | --- | --- | --- |
| 1 | **PR #6/#7/#8 的 base 均为 `main`**（应指向 `baseline`） | 违反团队政策；有误合入 `main` 风险 | **BLOCKED_PERMISSION**（无 GitHub 写凭据；页面步骤见配套文档） |
| 2 | **PR #8 无独立内容** | 与 #7 文件差异为零 | 需授权后关闭或改为后续证据 PR |
| 3 | M1 无可加载的数值 JSON 模型 | 三模块全真实联合无法进行 | `NOT_READY` |
| 4 | M1 检测性能低于平凡基线 | 不得声称有效检测 | `NOT_READY` |
| 5 | M2 对 `/rg/guarded_navigate` 恒 `UNKNOWN` | 若启用会持续阻断 | 设计性收紧 |
| 6 | 在线 Enforce 全链路未执行 | 只能分别声明 L3 与 L4 | `NOT_RUN` |
| 7 | ROS 2 实时入侵检测 / DDS 动态权限 / 动态状态机 | 未实现 | `NOT_READY` |

**无未解释的安全关键失败。**

---

## 10. 最终结论

# `GO`

| 门槛条件 | 状态 |
| --- | --- |
| 1. ON-06 报告与证据一致 | ✅ 已勘误 + 46 项 claims 对账 0 失败 + 15 项复发防护测试 |
| 2. 唯一候选 SHA 已确定 | ✅ `demo/2026-10-19-rc2`，受测 SHA `f6574ac` |
| 3. 必要整改已包含在该 SHA | ✅ ADP-01、ID-03/05、ON-06 勘误均在链上 |
| 4. 单元与契约回归通过 | ✅ 657 passed / 3 skipped；契约 PASS |
| 5. 基础 ROS 2 A/B 通过 | ✅ `DEMO RESULT: PASS`，8/8 断言 |
| 6. M3 在线六场景通过 | ✅ 6/6，跨层复核 46 检查 0 失败 |
| 7. DDS Enforce 独立回归通过 | ✅ 7/7（域 43） |
| 8. 关键证据可验证且无冲突 | ✅ 58 文件 SHA-256 全通过；claims 对账一致 |
| 9. 无未解释的安全关键失败 | ✅ 12 项不变量全部确认 |

### 10.1 可演示范围（必须遵守的限定）

**可以声明**：

- 真实 M3 任务风险规则模块已在 ROS 2 Jazzy 受控环境中**参与候选任务准入链路**；
- 适配层与 Gateway 实现**分层检查**；
- 经 NavigationSim 验证**合法执行**（+1 Goal）与**越权阻断**（0 Goal）；
- **Gateway 保留独立权威**：M3 建议允许时仍可被 Gateway 拒绝（ON-05 实证）；
- DDS-Security Enforce 最小权限在**独立实验**中生效（含原生拒绝与正向对照）。

**不能声明**：

- ❌ 三模块全真实联合防御（**M1、M2 仍为显式 Mock**）；
- ❌ 同一次 Enforce 在线全链路已完成（L3 为域 42 普通模式）；
- ❌ ROS 2 实时入侵检测；
- ❌ DDS 动态权限自动调整；
- ❌ 动态任务状态机已集成；
- ❌ M1 已具备有效通信异常检测能力；
- ❌ Planner 超时说明请求未执行/被拒绝。

### 10.2 版本冻结

复验已达标，按 `DEMO_20261019_VERSION_SELECTION.md` §12.2 为该 SHA 创建不可变标签：

```
demo-2026-10-19-rc2-verified   ->  rc2 Tip
                                  （受测代码状态 = f6574ac，源码等价性见版本选定文档 §2）
```

解析方式：`git rev-parse demo-2026-10-19-rc2-verified^{commit}`。

**为什么标签指向 Tip 而非受测 SHA**：复验要求工作区干净，证据只能在复验之后提交，
因此受测 SHA 必然早于含证据的 Tip。标签指向 Tip 便于评审者 checkout 后同时获得
代码与证据；其**受测代码状态**由 `git diff f6574ac 687b075 -- scripts src config
security tests modules identity_trust docs/interfaces`（输出为空）锚定。

**2026-10-16 旧预检标签 `demo-2026-10-19-rc-preflight-20261016`（`df5a0f0`）保持不变。**

---

## 11. 证据索引

| 内容 | 路径 |
| --- | --- |
| 本轮证据根目录 | `artifacts/demo-2026-10-19/final-review-final-20261017T131601Z/` |
| 环境快照 | 同上 `environment.json` |
| 复验结果（逐命令返回码） | 同上 `test_results.json` |
| 证据清单（SHA-256） | 同上 `SHA256SUMS.txt`（58 项） |
| 本轮汇总清单 | 同上 `manifest.json` |
| M3 在线分组原始证据 | 同上 `m3-online/stack-a/`、`m3-online/stack-b/` |
| 在线跨层复核 | 同上 `m3-online/merged/verification.json` / `.md` |
| L2 验收报告 | 同上 `l2/m2/report.json`、`l2/m3/report.json` |
| 历史在线证据（**未改动**） | `artifacts/demo-2026-10-19/m3-online-m3online-20261016T134406Z/` |
| 历史预检证据（**未改动**） | `artifacts/demo-2026-10-19/preflight-20261016/` |
| DDS 回归原始日志 | 容器内 `tests/evidence/rc2-regression/`（工作区 `tests/evidence/` 为 gitignored） |
| 本报告 | `docs/reviews/DEMO_20261019_FINAL_VERIFICATION.md` |
| 版本选定说明 | `docs/reviews/DEMO_20261019_VERSION_SELECTION.md` |
| ON-06 勘误说明 | `docs/reviews/ON06_EVIDENCE_CORRECTION.md` |
