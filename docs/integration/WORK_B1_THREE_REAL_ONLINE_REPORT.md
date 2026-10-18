# 工作 B1：三真实模块联合运行与 ROS 2 系统级在线整合报告

> 契约：`PROPOSED_V1` / `1.0.0-proposed`（未冻结）
> 本报告所有结论均来自本工作树内实际执行。
> **权威证据目录**：`artifacts/integration/three-real/b1p2-20261018T065613Z/`
> （94 个文件，SHA-256 全部校验通过）——对应合流工作 A **第二阶段**后的代码。
> 第一阶段证据保留在 `artifacts/integration/three-real/b1-20261018T061235Z/` 作为历史对照。

---

## 0. 最终状态

# `B1_INTEGRATED_BLOCKING`

三个真实模块**都能运行并真实参与 F0 的状态与证据判定**（LEVEL 1 + LEVEL 2 通过），
在缺乏可信当前证据时**能安全阻断**；但**尚未**证明三个真实模块共同满足在线正向准入
（LEVEL 3 = **BLOCKED**）。

**不得**把本状态声明为 `B1_FULL_ONLINE_VERIFIED`。

---

## 1. 开发起始 RC2 SHA

| 项 | 值 |
| --- | --- |
| 起始标签 | `demo-2026-10-19-rc2-verified` |
| 起始提交 | `33cb4f93d5e5fd268878fe83fc040c655d632a70` |
| B1 分支 | `integration/three-real-online` |
| B1 工作树 | `/home/zhangwei/project/RosSystem-worktrees/work-b1`（独立于主工作区） |
| 功能提交（本报告所测代码） | `a8d07ab`（合流 A 第二阶段后的 merge 提交） |
| 前一次功能提交（第一阶段） | `18088347cdccb93bb88749358f73444867aea0a1` |

RC2 作为回退底座**未被破坏**：主工作区仍在 `demo/2026-10-19-rc2`，标签未移动。

---

## 2. 原有 M3 在线回归结果（B1-1）

在**独立容器** `rg_b1`（独立挂载工作树、**ROS_DOMAIN_ID=54**）上用**新 run_id**
`b1-20261018T061235Z` 重跑六个场景：

| 场景 | M3 状态 | 适配层 | Planner | Gateway | 执行 | Goal |
| --- | --- | --- | --- | --- | --- | --- |
| ON-01 | `ALLOW_RECOMMENDED` | `READY` | `RECEIVED` | **ALLOW**/`ALLOW_IN_POLICY` | 1 | **1** |
| ON-02 | `BLOCK_RECOMMENDED` | `ADAPTER_BLOCK` | 未启动 | 0 | 0 | **0** |
| ON-03 | `UNKNOWN` | `ADAPTER_BLOCK` | 未启动 | 0 | 0 | **0** |
| ON-04 | `ERROR` | `ADAPTER_BLOCK` | 未启动 | 0 | 0 | **0** |
| ON-05 | `ALLOW_RECOMMENDED` | `READY` | `RECEIVED` | **BLOCK**/`OUT_OF_REGION` | 0 | **0** |
| ON-06 | `ALLOW_RECOMMENDED` | `READY` | **`PLANNER_RESULT_TIMEOUT`** | **0 事件** | 0 | **0** |

独立复核器：**39 项检查，0 失败**，`claims_checked=true`。

### 2.1 ON-06 本轮与 RC2 不同，且这是重要发现

| # | 运行 | Planner | Gateway 到达 | 决策 | 执行 | Goal |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 2026-10-16（RC2，域 42） | TIMEOUT | **1** | **ALLOW** | **1** | **1** |
| 2 | 2026-10-18 `b1-20261018T061235Z`（B1 阶段一） | TIMEOUT | **0** | — | **0** | **0** |
| 3 | 2026-10-18 `b1p2-20261018T065613Z`（B1 阶段二） | TIMEOUT | **1** | **ALLOW** | **1** | **1** |

**三次都是真实观测，且下游结果出现 1→0→1 的摆动。**
这实证了 **Planner 超时后的下游结果是运行时不确定的**：
同一份代码、同一个 0.5s 超时窗口，有时请求已经送达并执行完毕，有时根本没送到 Gateway。

因此：
- 超时**不能**被预设有任何下游结论（既不能假定"已执行"，也不能假定"未执行"）；
- 必须逐次从 Gateway 权威审计与 NavigationSim journal 按 `request_id` 读取；
- 本轮复核器一开始正是因为沿用了 RC2 的固定期望而报 5 项 FAIL，
  改为**只声明不变量**（适配层放行 + Planner 超时）后通过。
  **这次 FAIL 是校验器正确工作**，不是工具缺陷。

---

## 3. 三 External 配置与运行入口

| 交付物 | 说明 |
| --- | --- |
| `config/team_modules.three-real.yaml` | 三模块全部 `mode: external`；解释器统一为 `scripts/module_python.sh` |
| `scripts/module_python.sh` | **解释器固定点**：先自检候选解释器能构造 Draft 2020-12 校验器，再 `exec`；全部不合格则失败关闭 |
| `scripts/run_three_real_online.py` | 联合运行器：阶段 A 直采三模块完整输出，阶段 B 跑一次 F0，二者**交叉核对**；输出 LEVEL 1/2/3 判定 |
| `tests/integration/three_real_online_check.py` | T1–T5 自动化回归（11 项） |

### 3.1 为什么必须固定解释器（真实故障）

交付配置用裸 `python3`，而本机系统 `python3` 的 `jsonschema` 是 **3.2.0**，无法构造
Draft 2020-12 校验器。三个模块会在输入校验阶段抛 `ImportError`：

```
INPUT_INVALID: ImportError          # M1 退出码 2
```

F0 如实记录 `ADAPTER_MODULE_EXIT_NONZERO` —— 安全上正确（失败关闭），
但现象会被误读成"模块坏了"。工作 A 的交接文件已明确要求 B1 固定解释器，
`scripts/module_python.sh` 就是该固定点。**不得**靠改模块来绕过。

---

## 4. 三真实模块调用证据（LEVEL 1 = PASS）

同一次 F0 调用中三个真实进程全部执行，`run_id`/`request_id` 一致：

| 模块 | mode | 退出码 | Schema | 状态 | 实际命令入口 |
| --- | --- | --- | --- | --- | --- |
| `comm_risk` | external | 0 | ✅ | `UNKNOWN` | `modules/member1_comm/module.py` |
| `identity_trust` | external | 0 | ✅ | `AUTHORIZED`（历史） | `identity_trust/assessor.py` |
| `task_risk` | external | 0 | ✅ | `ALLOW_RECOMMENDED` | `modules/member3_taskrisk/module.py` |

**证明"不是 Mock"的三重依据**：

1. 三个命令的 `.py` 目标都不在 `mock_modules/`；
2. 三份输出的 `producer.source` 均为 **`EXTERNAL`**（Mock 会写 `MOCK`）；
3. 运行器在 `guard_no_mock()` 里对 `mode != external` 或命令含 `mock_modules`
   的配置**直接拒绝运行**（退出码 2），并有专门回归用例
   `test_runner_refuses_mock_config` 验证该守卫。

可复现性：同一配置在宿主 venv 与容器 `rg_b1`（ROS 2 Jazzy）内**结果一致**。

---

## 5. 真实 Schema 与证据校验（LEVEL 2 = PASS）

对三份真实输出逐项核验：

| 检查 | 结果 |
| --- | --- |
| 公共 Schema（Draft 2020-12） | 三份全部通过 |
| `run_id` 与信封一致 | ✅ |
| `request_id` 与信封一致 | ✅ |
| `event_id` 非空、1..128、三份互不重复 | ✅ |
| `evidence_refs` 非空 | ✅ |
| `comm_risk.communication.resource` == 候选动作资源 | ✅ |
| `comm_risk` 观察时间落在声明窗口内 | ✅ |
| `task_risk.task_id` / `action_resource` / `target` 与候选任务一致 | ✅ |
| 严格 JSON（拒绝重复键、NaN/Infinity、顶层非对象） | ✅ |
| `producer.source == EXTERNAL` | ✅ |
| F0 观察到的状态 == 直采状态 | ✅（账本隔离后一致） |

### 5.1 一处必须说明的构造细节

`identity_trust` 有**防历史授权复用账本**（`--identity-ledger`）：
同一 `(case, experiment_run, request_id, resource)` 只能被解释一次，第二次会被
正确判为复用 → `UNKNOWN`。

阶段 A 直采与阶段 B（F0）若共用同一账本，第二次必然变 `UNKNOWN`，
交叉核对就会误报"运行不确定性"。因此**阶段 A 使用证据目录内的独立账本**，
让两次调用各自都是首次解释；账本复用本身的反例由 T3 单独验证，
**没有被顺手抹掉**。

---

## 6. M1 / M2 的可信在线输入状态

这是 LEVEL 3 无法达成的**根本原因**，也是本轮最重要的技术结论。

### 6.1 M1 `comm_risk`：`ONLINE_PROCEED_READY = FAIL`

**合流工作 A 第二阶段后，M1 的阻断理由已改变，必须按新事实表述：**

| 维度 | 第一阶段 | **第二阶段（当前）** |
| --- | --- | --- |
| 运行时采集器 | **完全没有** | **已有**：`modules/member1_comm/collector/proc_runtime.py`，从 `/proc` 真实读取 24 维特征（`Net_Sent`、`pgpgin`、`Tcp_Syn`、`pgfault` 等） |
| 特征与模型 | 49 维 ROSPaCe，无映射 | 24 维运行时子集清单 + `comm_risk_model_runtime_subset.json` |
| 模型门槛 | `validation_gate_passed = false` | **仍为 `false`** |
| `request_count` | — | 采集器**拒绝伪造**：无活体 ROS 2 时 `mapping = BLOCKED_MISSING_REQUEST_COUNT` |
| 实测结论 | `UNKNOWN` | **仍为 `UNKNOWN`** |

**决定性实验**（本轮实际执行）：用采集器真实产出观测块（`--request-count` 显式给出、
`mapping = COMPLETE`）+ 运行时子集模型 + 受信任来源 `--observation-provenance RUNTIME_LOG`：

```
provenance=RUNTIME_LOG    rc=0   status=UNKNOWN
provenance=UNKNOWN        rc=0   status=UNKNOWN
```

即**即使当前观测真实可信、来源受信任、模型与特征匹配，M1 仍然给出 `UNKNOWN`**。
根因收敛为**一个**：`validation_gate_passed = false`，生产语义下低于阈值不得放行 `NORMAL`。

> 因此"缺实时采集器"不再是 M1 的首要阻断理由（该能力第二阶段已补上）；
> 首要阻断是**模型未通过验证门槛**。报告若继续沿用第一阶段的措辞即为失实。

### 6.2 M2 `identity_trust`：`ONLINE_PROCEED_READY = FAIL`

| 维度 | 事实 |
| --- | --- |
| 顶层 `status` | `AUTHORIZED` —— 这是**历史受控实验**（S2）当时的授权结论 |
| `extensions.current_request_identity.status` | **`UNKNOWN`** |
| `binding` | `UNBOUND_NO_TRUSTED_CURRENT_IDENTITY_WITNESS` |
| `historical_only` | `false`（不是靠该字段区分，而是靠**当前身份缺失**） |
| 缺失原因 | ROS 2 Jazzy / rclpy **不向订阅端暴露**"该样本发布者已完成 DDS 认证的身份"；认证发生在参与者建链阶段，不随消息传递 |

即：**同一个模块可以同时是"历史上授权过"和"当前请求身份未绑定"**。
F0 必须后者说了算。

### 6.3 M3 `task_risk`：`ONLINE_PROCEED_READY = PASS`

真实确定性规则引擎，本轮对合法候选任务给出 `ALLOW_RECOMMENDED`，
`rule_basis` 可解释、策略版本可追溯。但 `ALLOW_RECOMMENDED` **不是** Gateway 准入。

---

## 7. F0 的修改及安全影响

### 7.1 工作 A 引入、B1 接收并验证的规则

| 变更 | 安全含义 |
| --- | --- |
| `REQUIRED_CURRENT_IDENTITY = {'identity_trust': 'AUTHENTICATED'}` | 身份位置**额外**要求当前请求身份绑定；历史 `AUTHORIZED` 单独不再构成推进条件 |
| 新原因码 `ADAPTER_CURRENT_IDENTITY_UNBOUND` | 阻断原因可审计、可区分于其它阻断 |
| 缺 `extensions.current_request_identity` / 非 `AUTHENTICATED` / `historical_only=true` → 阻断 | 三条独立防线，任一命中即不推进 |

字段位于 Schema 预留的 `extensions` 中，**未改动任何既有字段含义**，
**未改契约版本**（仍 `1.0.0-proposed`）。

### 7.2 B1 自己的补充

| 变更 | 作用 |
| --- | --- |
| `scripts/module_python.sh` | 解释器固定，避免依赖缺失被误读为模块故障 |
| `config/team_modules.three-real.yaml` | 三 external + 固定解释器 + 产物隔离到 `logs/three-real/` |
| `run_three_real_online.py` 的 `guard_no_mock()` | 配置若被改回 Mock/替身则**拒绝运行**，杜绝静默降级 |
| `run_three_real_online.py` 的阶段 A/B 交叉核对 | 防止"F0 看到的"与"模块实际输出的"不一致 |

### 7.3 没有做的事（有意为之）

- 未修改 Gateway TaskPolicy；
- 未修改 DDS 最小权限；
- 未修改三个模块的算法源码；
- 未把 Mock 重命名为 External；
- 未为了让 LEVEL 3 通过而放宽任何条件。

---

## 8. Gateway / NavigationSim 在线结果

B1-1 的在线部分（域 54，普通模式）证明：

| 结论 | 证据 |
| --- | --- |
| 合法任务经 Gateway ALLOW 并真实执行 | ON-01：`ALLOW`/`ALLOW_IN_POLICY` + `EXECUTED` + **1 Goal** |
| **Gateway 独立权威**（M3 建议允许时仍可拒绝） | ON-05：M3 `ALLOW_RECOMMENDED` 且适配层放行，Gateway **`BLOCK`/`OUT_OF_REGION`**，**0 Goal** |
| 适配层阻断不进入 Gateway | ON-02/03/04：到达 0、Goal 0 |
| 超时不被记为 Gateway BLOCK | ON-06：`PLANNER_RESULT_TIMEOUT`，审计中 0 条事件 |

**ON-05 同时构成任务书 T6（Gateway 独立阻断）**：真实上游（M3）在该场景下
确实给出了可推进建议并被适配层放行，Gateway 依未修改的正式策略独立拒绝。
**未修改 `config/task_policy.yaml`**（`git diff` 为 0）。

> 注意：T6 的"真实上游可合法建议推进"在本轮是 **M3 真实 + M1/M2 Mock** 的
> RC2 模式；三真实模块同时可推进的条件**尚不具备**（见 §6）。

---

## 9. DDS Enforce 验收（T7）

在独立容器 `rg_b1`、**域 43** 执行 `tests/integration/sros2_check.py`：

```
SROS2 SUMMARY (7 passed / 7 total)
  [PASS] S1  普通模式合法 A 区请求（域 42，未启用安全）
  [PASS] S2  Enforce 合法 A 区请求：Planner→Gateway→NavigationSim
  [PASS] S5  Enforce B 区越界：身份合法但 TaskPolicy 拒绝
  [PASS] S3C 正向对照：/gateway 身份直连执行接口成功
  [PASS] S3  Enforce：/planner 身份直连执行接口被拒绝
  [PASS] S4  无授权身份访问执行接口被拒绝
  [PASS] S6  安全配置失效不静默回退
```

- Enforce **实际启用**（非 Permissive）；
- 最小权限**未放宽**（策略文件 0 改动）；
- keystore 以**只读**挂载使用，未重建、未覆盖；
- 原生 DDS 拒绝与正向对照（S3C）成对存在。

**与在线 M3 不是同一次运行**：L3 为域 54 普通模式，L4 为域 43 Enforce。

### 9.1 三真实模块 + Enforce 同次运行：`NOT_RUN`

原因（精确）：F0 的 Planner 提交走 `ros2 run rg_demo_nodes planner_node`，
该路径**没有**为子进程注入 `ROS_SECURITY_*` 环境与 enclave 选择逻辑。
要在 Enforce 下跑通三真实联合链路，需要给 F0 的 Planner 启动增加安全上下文接线，
属于**架构改动**，超出本轮"不重设计安全架构"的边界；RC2 基线同样从未做过。
按任务书要求标记 `NOT_RUN`，**不拼接**成"同次 Enforce 全链路成功"。

---

## 10. 与工作 A 的合流记录

| 项 | 值 |
| --- | --- |
| 工作 A 分支 | `integration/member-module-adaptation` |
| 工作 A 提交 | `f51bab800d7bb3fe325d7e096bb15438178f5122` |
| B1 起点（RC2） | `33cb4f93d5e5fd268878fe83fc040c655d632a70` |
| 合流方式 | `git merge --no-ff`（A 基于 RC2，合流干净，无冲突） |
| 合流提交（阶段一） | `18088347cdccb93bb88749358f73444867aea0a1` |
| **工作 A 第二阶段** | **`acadbf7654036a11d74aff9f507bef34b4223aa8`**（`c6f6755` 安全加固 + M1 `/proc` 采集 + `acadbf7` 文档） |
| 合流提交（阶段二） | `a8d07ab` |
| 交接文件 | `docs/integration/MEMBER_MODULE_HANDOFF.md`、`member_module_handoff.yaml` |

合流后立即执行：全仓单元测试、三模块验收、三真实联调、M3 在线回归、DDS Enforce，
全部结果见 §12。**未直接复制 A 的未提交工作树内容**，只按固定 SHA 合流。

A 的 `readiness` 四项已被 B1 独立复核（不是照抄）：

| 模块 | A 声明 | B1 复核 |
| --- | --- | --- |
| M1 | CALLABLE/SCHEMA/EVIDENCE=PASS，ONLINE_PROCEED=FAIL | 一致：真实进程 rc=0、Schema 通过、状态 UNKNOWN |
| M2 | 同上，ONLINE_PROCEED=FAIL | 一致：`AUTHORIZED` 但当前身份 `UNKNOWN` |
| M3 | 四项全 PASS | 一致：`ALLOW_RECOMMENDED`，规则可解释 |

---

## 11. 未解决的风险

| # | 风险 | 级别 | 影响 |
| --- | --- | --- | --- |
| R-1 | M1 模型 `validation_gate_passed=false`（F1 低于恒预测攻击基线） | **P1** | 生产语义下只能 `UNKNOWN`；不得宣称检测有效 |
| R-2 | ~~M1 无实时采集器~~ → **第二阶段已补 `/proc` 采集器（24 维）**，但采集器在无活体 ROS 2 时不给 `request_count`（`BLOCKED_MISSING_REQUEST_COUNT`），且该子集模型同样门槛未过 | P2 | 采集能力已具备，剩余阻断是模型门槛 |
| R-3 | M2 无当前请求身份绑定组件（ROS 2 无可用中间件 API） | **P1** | 三真实模块永远停在 `ADAPTER_CURRENT_IDENTITY_UNBOUND` |
| R-4 | 交付配置用裸 `python3`，系统 jsonschema 3.2.0 会导致三模块假性失败 | P2 | 已由 `scripts/module_python.sh` 缓解；仍需上游修正配置 |
| R-5 | 三真实 + Enforce 同次运行未打通（F0 Planner 启动无安全上下文接线） | P2 | 只能分别声明 L3 与 L4 |
| R-6 | `identity_trust` 账本使"同 request_id 重跑"必然变 UNKNOWN | P2 | 已文档化；验收需每次新 request_id 或清理账本 |
| R-7 | PR #6/#7/#8 base 仍为 `main`（应指向 `baseline`） | **P1** | 本环境无 GitHub 写凭据，仍未整改 |

**无未解释的安全关键失败。**

---

## 12. 全部实际测试结果

| 项 | 命令/入口 | 结果 |
| --- | --- | --- |
| 全仓单元测试 | `pytest tests/unit -q` | **734 passed, 3 skipped, 2 xfailed** |
| 契约与 Schema | `validate_team_contracts.py --all` | PASS（随单元测试） |
| M1 验收 | `check_member_module.py --module comm_risk --real-fixture …` | **60 PASS / 3 非门槛 FAIL**，`gate=True` |
| M2 验收 | 同上 `identity_trust` | **58 PASS / 3 非门槛 FAIL**，`gate=True` |
| M3 验收 | 同上 `task_risk` | **58 PASS / 3 非门槛 FAIL**，`gate=True` |
| T1 三真实调用 | `three_real_online_check.py::test_t1` | **PASS** |
| T2 失败关闭矩阵 | 6 个用例（SUSPICIOUS / UNKNOWN / ERROR / DENIED / BLOCK / 超时 / 崩溃 / 非法输出） | **全部 PASS** |
| T3 历史授权冒用 | 全真实模块（M1 受控测试标注） | **PASS** |
| T4 离线正常冒用 | 真实 M1 两种语义 | **PASS** |
| T5 真实正向推进 | `run_three_real_online.py` | **BLOCKED（预期）** |
| T6 Gateway 独立阻断 | ON-05（在线） | **PASS** |
| T7 DDS Enforce | `sros2_check.py --run-id b1-enforce` | **7/7 PASS** |
| 三真实联调守卫 | `test_runner_refuses_mock_config` | **PASS** |
| M3 在线六场景 | `m3_online_drive.sh` + `m3_online_extra.sh` | **6/6，复核 39 检查 0 失败** |
| 三真实 + Enforce 同次 | — | **NOT_RUN**（理由见 §9.1） |

> 3 条非门槛 `FAIL` 是"Mock 场景开关对不解析该开关的真实模块不适用"的记录
> （`mandatory=False`、`gate=False`、`applicability=NOT_APPLICABLE_REAL_MODULE`），
> **保留可见**，未删除、未改成 PASS。

### 12.1 环境

| 项 | 值 |
| --- | --- |
| 宿主 | WSL2 Linux x86_64 |
| 容器 | `rg_b1`（`ros:jazzy`），独立挂载 B1 工作树，**ROS_DOMAIN_ID=54** |
| RMW | `rmw_fastrtps_cpp` |
| 在线域 | 54（普通模式） |
| Enforce 域 | 43 |
| 模块模式 | 三模块全部 `external` |
| 解释器 | `scripts/module_python.sh` → jsonschema ≥ 4（Draft 2020-12） |
| 隔离 | 独立工作树、独立构建产物、独立日志目录、独立 DDS 域、keystore 只读挂载 |

---

## 13. 当前完整集成 SHA

| 角色 | 值 |
| --- | --- |
| 功能提交（本报告全部测试所测代码，阶段二） | `a8d07ab`（完整 SHA 见下方） |
| 分支 | `integration/three-real-online` |
| 报告提交 | 本文件所在提交（在其之后，仅文档与证据） |
| 回退底座 | `demo-2026-10-19-rc2-verified` = `33cb4f9…`（未移动） |

---

## 14. 结论：对任务书最终提问的回答

### 14.1 是否已实现三成员真实模块的共同在线运行？

**是（LEVEL 1 + LEVEL 2）。**
三个真实成员程序在同一次 F0 调用中被真实执行（`producer.source=EXTERNAL`、
`mode=external`），输出全部通过公共 Schema 与关联字段校验。

### 14.2 是否已实现可信的三模块联合安全准入？

**否（LEVEL 3 = BLOCKED）。**
缺少的是**可信的当前证据**，不是框架：

- M1 模型门槛未通过，且无 ROS 2 实时特征采集 → 只能 `UNKNOWN`；
- M2 无当前请求身份绑定 → 只能 `current_request_identity=UNKNOWN`。

### 14.3 实际证据

| 结论 | 证据位置 |
| --- | --- |
| 三真实模块被调用且非 Mock | `three-real/summary.json`、`three-real/<module>.json`、`producer.source=EXTERNAL` |
| 历史授权不能冒充当前身份 | T3 用例：三状态看似可推进，F0 仍以 `ADAPTER_CURRENT_IDENTITY_UNBOUND` 阻断 |
| 离线正常不能冒充当前安全 | T4 用例：同一离线样本，无受信任来源→扣留；受控测试→NORMAL 但仍阻断 |
| 无可信证据失败关闭 | T2 八个故障用例全部阻断且无下游 Goal |
| Gateway 独立权威 | ON-05：M3 允许、适配层放行、Gateway BLOCK、0 Goal |
| 超时语义不定 | 本轮 ON-06 到达 0 vs RC2 到达 1，均按日志如实记录 |
| DDS 最小权限未放宽 | T7 7/7，策略文件 0 改动 |

### 14.4 剩余阻断（精确）

1. **M1**：`validation_gate_passed=false`；49 维特征无运行时采集器。→ 需重训达标 + 建立采集映射。
2. **M2**：无"当前请求可信身份"产生组件。→ 需 ROS 2 中间件层面的主体身份旁证机制。
3. **R-7**：PR base 未整改（权限阻塞，非技术阻塞）。

三者中前两项属**真实能力缺口**，**不得**用 Mock、自报身份或历史结果填补。

---

## 15. 复现方式

```bash
# 1) 工作树
git worktree add -b integration/three-real-online \
    /home/zhangwei/project/RosSystem-worktrees/work-b1 \
    'demo-2026-10-19-rc2-verified^{commit}'
cd /home/zhangwei/project/RosSystem-worktrees/work-b1
git merge --no-ff integration/member-module-adaptation

# 2) 运行时依赖（宿主）
ln -sfn ../../RosSystem/.research-venv .research-venv
# 容器内需 python3-jsonschema>=4 与 python3-yaml

# 3) 三真实模块联合运行（离线，无需 ROS）
./.research-venv/bin/python scripts/run_three_real_online.py \
    --run-id <RUN_ID> --out-dir artifacts/integration/three-real/<RUN_ID>

# 4) T1–T5 回归
./.research-venv/bin/python -m pytest tests/integration/three_real_online_check.py -q

# 5) M3 在线（容器，独立域）
docker exec rg_b1 bash -lc 'source /opt/ros/jazzy/setup.bash && cd /ws && \
  bash scripts/m3_online_drive.sh <RUN_ID> /tmp/m3_online/<RUN_ID>'

# 6) DDS Enforce
docker exec rg_b1 bash -lc 'source /opt/ros/jazzy/setup.bash && cd /ws && \
  export ROS_DOMAIN_ID=43 && python3 tests/integration/sros2_check.py --run-id b1-enforce'
```
