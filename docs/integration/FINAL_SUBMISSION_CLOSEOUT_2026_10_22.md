# 最终封版收尾报告（2026-10-22）

> 分支：`release/final-submission-closeout-2026-10-22`
> 起点：`e455e29111032c3f54031144d58a743173697668`
> **受测代码 SHA（CLOSEOUT_TESTED_CODE_SHA）：`2f3de257c9eac873093201292f6b2a9571da4f03`**
> run_id：`closeout-20261021T023020Z`
> 证据：`artifacts/integration/final-submission-closeout/closeout-20261021T023020Z/`

---

## 1. 系统定位（封版）

**RosSystem：基于 ROS 2 Jazzy 的多模块风险评估与分层安全准入原型系统。**

演示与验收范围是**受控系统**：受控正向在线闭环可执行，
三真实 External 模块被真实调用并 Schema 校验通过，但在缺少可信正向依据时
F0 STRICT 正确阻断。**三真实 LEVEL 3 正向准入未达成，且不因本轮封版而改变。**

## 2. 本轮修复的三个问题

### 2.1 预检失败后仍继续运行（P0，已修）

旧实现：`STRICT_PREFLIGHT=1 check_env || rc_all=1` —— 预检失败只记录，继续跑全部验收。
后果比"慢失败"更糟：**预检失败会被后续步骤的失败掩盖**，汇总还可能看起来像部分通过。

现改为硬门槛：失败即标记 `PREFLIGHT`/`ACCEPTANCE` 为 FAIL，输出 `PREFLIGHT_FAIL`，
**exit 8**，且**不启动任何 ROS 进程**。

**7 项反例全部通过**（每项同时验证：非零退出、正确原因、无后续证据目录、
无伪造 `ACCEPTANCE=PASS`）：

| 案例 | 结果 |
| --- | --- |
| 未 source ROS | PASS |
| 缺 colcon | PASS |
| jsonschema 缺失 | PASS |
| 工作树不干净 | PASS |
| 非 git 仓库（SHA 不可解析） | PASS |
| 运行冲突（navigation_sim 替身） | PASS |
| ROS 2 包未构建 | PASS |

顺手修掉了 `pgrep -fc 'rg_gateway|rg_demo_nodes'` 的**自我匹配**问题：
该模式会匹配到调用者自身命令行（包括测试脚本），改为按可执行/脚本基名精确匹配
并排除当前进程组。

### 2.2 SIGTERM 清理从未被确定性验证（P0，已修）

上一轮失败的原因：信号发给了 `( script & )` 的**子 shell**，脚本本身从未收到，
于是"清理通过"实际是"脚本正常跑完了"。

新测试直接后台启动脚本、等 `GATEWAY_READY` 与 `NAVSIM_READY` 真正出现后再发 TERM，
并断言四件事：

| 断言 | 实测 |
| --- | --- |
| 节点在信号前已启动 | PASS |
| 顶层脚本确实收到 TERM（日志有 `收到 TERM`） | PASS |
| 退出码反映信号而非被吞成 0 | **130** |
| 本轮归属的非僵尸进程归零 | **7 → 0** |

**归属判定**用本轮唯一 run_id 匹配节点命令行，
既不用脚本自身 PGID（`set -m` 让每个后台作业各自成组，节点不与脚本同组），
也不用宽泛的 `pgrep -f`。

### 2.3 跨证据根目录未统一校验（P1，已修）

历史主清单 99 项**不覆盖** DDS 逐场景目录。本轮建立
`docs/integration/FINAL_SUBMISSION_EVIDENCE_MANIFEST.json`：

- 主证据 ``：**115** 个文件；
- DDS 逐场景 `dds_enforce/`：**19** 个文件；
- 合计 **134** 项，逐文件重算 SHA-256；
- 敏感材料（`.pem`/`.key`/`.p7s`）：**0**；
- `SHA256SUMS.txt`：**115/115 通过**。

两个历史证据根目录**未移动、未改写**。

## 3. ON-06 表述校正（重要）

**两次实验的 ON-06 结果不同，必须按 run 判读：**

| run_id | 受测 SHA | Planner | Gateway 到达 | 决策 | Goal |
| --- | --- | --- | --- | --- | --- |
| `closeout-20261021T023020Z`（本次封版） | `2f3de257...` | `TIMEOUT` | **0** | 无 | **0** |
| `harden-20261020T171740Z`（历史加固） | `ba16e7f...` | `TIMEOUT` | **1** | `ALLOW` | **1** |

本次封版：Gateway 审计**未记录**该请求到达，NavSim **未记录** Goal。
历史加固：同场景曾 `ALLOW` 且 Goal 1。两者都真实，**不可互相替代**。

原文曾写"超时后执行"，但现有日志**缺少可严格排序的 Planner 超时时刻**，
因此不能断言 Goal 发生在超时之后。已统一改为：

> **本次 Planner 返回 `TIMEOUT`，但同一请求在 Gateway 审计中被 `ALLOW`，
> 并由 NavigationSim 记录了 1 个 Goal。TIMEOUT 不代表请求被阻断或取消。**

只陈述"两者在同一请求上同时成立"，**不宣称时间先后**。
Gateway Action 取消协议与任务幂等留作后续工作。

## 4. 本轮实际验收结果（在 `2f3de257c9eac873093201292f6b2a9571da4f03` 上）

| 项目 | 结果 |
| --- | --- |
| 公共契约 | **PASS** |
| F0 P0 安全反例 | **38 passed** |
| 全仓单测 | **847 passed, 1 skipped** |
| 三真实 External | 调用 PASS / Schema PASS / **F0 BLOCK（预期）** |
| 受控在线（request_id 级） | **PASS** |
| M3 六场景（含 claims） | **PASS（36 checks / 0 failures，claims_checked=true）** |
| 正式 DDS Enforce | **7/7 PASS** |
| **全量验收** | **`ACCEPTANCE=PASS`** |

## 5. 能力边界（不得混淆）

| 能力 | 状态 |
| --- | --- |
| 受控 M1/M2 + 真实 M3 在线闭环 | ✅ 已验证 |
| Gateway 独立 TaskPolicy 权威 | ✅ 已验证 |
| 三真实 External 调用与 Schema | ✅ 已验证 |
| 三真实严格模式正确阻断 | ✅ 已验证 |
| 正式 DDS-Security Enforce | ✅ 已验证（独立实验，不同域） |
| **M1 在线检测有效性** | ❌ 未通过 |
| **M2 生产身份签发者** | ❌ 未就绪 |
| **三真实 LEVEL 3 正向准入** | ❌ **BLOCKED** |

**不得宣称**：NavigationSim 的 `recorded_only` 等于实体机器人完成真实导航；
三真实校验通过等于 LEVEL 3 准入成功；DDS Enforce 与在线模式是同一次实验。

## 6. 最终等级

| 门槛 | 结果 |
| --- | --- |
| `FINAL_CONTROLLED_SYSTEM_READY` | **PASS** |
| `FINAL_THREE_EXTERNAL_INTEGRATION_READY` | **PASS** |
| `FINAL_DDS_ENFORCE_READY` | **PASS** |
| `FINAL_STRICT_PREFLIGHT_FAIL_FAST` | **PASS** |
| `FINAL_SIGTERM_CLEANUP_VERIFIED` | **PASS** |
| `FINAL_EVIDENCE_CROSS_ROOT_VERIFIED` | **PASS** |
| `FINAL_TIMEOUT_SEMANTICS_ACCURATE` | **PASS** |
| `THREE_REAL_LEVEL3_READY` | **BLOCKED** |
