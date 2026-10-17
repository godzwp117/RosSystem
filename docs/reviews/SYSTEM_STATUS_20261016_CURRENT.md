# RosSystem 当前系统研发状态（2026-10-16 快照）

> 本文是 **2026-10-16** 的当前状态快照，**不覆盖**任何历史报告。
> 历史报告仍作为其对应日期与 SHA 的事实快照继续有效。
> 契约状态：`PROPOSED_V1` / `1.0.0-proposed`（**未冻结**）。

---

## 1. 当前 baseline SHA

| 引用 | SHA |
| --- | --- |
| `origin/baseline`（公共稳定基线） | `a4c597161d254192b662ee7b8f4d17f76a89cc16` |
| `origin/main` | `838f66f41821edf0421612a205d162ae8e9eb955` |

本轮 `git fetch origin --prune --tags` 后复核，两者**均未变化**。

---

## 2. 演示候选起始 SHA

| 引用 | SHA |
| --- | --- |
| `origin/demo/2026-10-19-rc` | `df5a0f0d3a12286b3dc3861fb104987cf10d21d3` |
| 不可变预检标签 `demo-2026-10-19-rc-preflight-20261016` | 同上 |
| `origin/fix/m2-m3-acceptance` | `19f6a256e71db7270de88e5b76b9ac2d87668cc6` |
| `origin/chore/member-deliveries` | `3ce820258c69b89e2ad9291e16c44dc7d2b99150` |

---

## 3. 本轮工作分支与提交

| 项 | 值 |
| --- | --- |
| 工作分支 | `integration/m3-online-evidence-20261016` |
| 起点 | `19f6a25`（`fix/m2-m3-acceptance`），**继承链**：`baseline` → `chore/member-deliveries` → `fix/m2-m3-acceptance` → 本分支 |
| 提交 | 见本轮报告 §12（`fix(verifier)`、`test(...)`、`docs(...)`、`evidence(...)`） |

---

## 4. PR #6 / #7 / #8 实际状态

用 GitHub REST API 实测（`gh` 未安装）：

| PR | 标题 | state | base | head | files | ± | mergeable |
| --- | --- | --- | --- | --- | --- | --- | --- |
| #6 | Chore/member deliveries | open | **main** | `chore/member-deliveries@3ce8202` | 192 | +59011/−497 | true/clean |
| #7 | Fix/m2 m3 acceptance | open | **main** | `fix/m2-m3-acceptance@19f6a25` | 272 | +71168/−497 | true/clean |
| #8 | Demo/2026 10 19 rc | open | **main** | `demo/2026-10-19-rc@df5a0f0` | 272 | +71168/−497 | true/clean |

**继承关系（`git merge-base --is-ancestor` 实测）**：

```
baseline a4c5971
   └── chore/member-deliveries 3ce8202     [PR #6]
          └── fix/m2-m3-acceptance 19f6a25  [PR #7]
                 └── demo/2026-10-19-rc df5a0f0  [PR #8]
```

- **#7 继承 #6；#8 继承 #7。**
- `git diff origin/fix/m2-m3-acceptance origin/demo/2026-10-19-rc` → **空**。
  即 **#8 相对 #7 无任何文件内容差异**（8 个提交全部是 merge 提交）。
  #8 的文件数与 ± 计数与 #7 完全相同，佐证该结论。

### 4.1 目标分支整改状态：`BLOCKED_PERMISSION`

三条 PR 的 base **均为 `main`**，而团队政策要求研究模块 PR 指向 `baseline`
（仓库已有自动守卫 `tests/unit/test_member_module_contract.py::test_no_research_module_targets_main_in_docs`）。

**未能执行整改**：本环境只有 SSH 推送权限，无 GitHub 写凭据（`gh` 未安装、
无 `GH_TOKEN`/`GITHUB_TOKEN`、无 credential helper）。匿名 API 写操作实测：

```
PATCH /repos/godzwp117/RosSystem/pulls/6  ->  HTTP 401 {"message":"Requires authentication"}
```

**不得只改文档就宣称 PR 已修复** —— 因此本报告如实标记为权限阻塞，并给出页面操作步骤（见 §12 风险 R-1）。

---

## 5. M1 / M2 / M3 当前算法类型

| 成员 | 算法类型（实测） |
| --- | --- |
| **M1** | ROSPaCe 49 特征 + 类别权重 `LogisticRegression` / `ExtraTrees` **监督二分类**；导出为纯数值 JSON 模型（格式 `member1-numeric-v1`，SHA256 校验，**拒绝 pickle/joblib**） |
| **M2** | **离线受控实验证据解释器**：源策略 XML + 生成的 `permissions.xml` + 归档 Enforce 日志三方交叉核验。**不是**在线身份认证器 |
| **M3** | **确定性可解释任务风险规则引擎**（`TASK_CONSTRAINT_RULES_V1`）：任务 ID / 坐标系 / 目标区域 / 可选可信 Gateway 审计历史 |

> 严格表述：M3 **不是**深度学习模型、神经网络或未知攻击预测模型；
> M2 只解释历史 DDS 证据，**不能**认定当前请求已完成 DDS 身份认证。

---

## 6. 三模块当前代码与实验状态

| 项 | M1 | M2 | M3 |
| --- | --- | --- | --- |
| 源码 | `deliveries/member1-comm/modules/my_comm/`（11 个 .py） | `identity_trust/assessor.py` | `modules/member3_taskrisk/{module,risk_model}.py` |
| 自带测试（本轮实跑） | **44 passed**（36+8） | **23 passed** | **95 passed** |
| 真实验收 | **未能执行**（缺 JSON 模型） | **45 PASS / gate True** | **45 PASS / gate True** |
| 可加载模型产物 | **缺失**（`training_runs/` 仅 joblib，模块拒绝） | 不适用 | 不适用 |
| 实验指标 | `validation_gate=FAIL`（详见 §6.1） | 域 43 Enforce 正反对照 | 四状态真实条件全覆盖 |
| 在线能力 | `RUNTIME_MONITOR=NOT_READY` | 不适用（离线解释器） | **本轮已在 ROS 2 在线链路中验证** |

### 6.1 M1 性能口径（不得只展示有利数字）

| 数据集 | F1 | 恒预测攻击基线 F1 | 门槛 |
| --- | --- | --- | --- |
| ROSPaCe reduced | **0.1312** | 0.8132 | **FAIL** |
| ROSPaCe reduced noperiodicity | **0.6346** | 0.8719 | **FAIL** |

测试集**仅覆盖 6 类攻击中的 1 类**（metasploit SYN flood）；漏报率 93.0% / 53.5%。
两个数据集的门槛均为 FAIL。成员一**自己如实声明** `model_performance_gate=FAIL`。

---

## 7. F0 Gateway 安全能力

| 能力 | 状态 |
| --- | --- |
| Action 主链（请求→准入→执行） | 代码已实现，**本轮在线验证通过** |
| 权威 TaskPolicy 准入（区域/速率/重复） | 代码已实现，**本轮在线验证通过** |
| 越界拒绝且不产生下游 Goal | **本轮在线验证通过**（ON-05：M3 建议允许仍被拒绝） |
| 结构化审计与事件关联 | **本轮在线验证通过**（`RosCommEvent`/`DecisionEvent`/`ExecutionEvent`） |
| 适配层失败关闭（不再以非零退出冒充输入拒绝） | **本轮修复并验证** |
| 模块无法绕过 Gateway 直达 `/rg/nav_execute` | 静态审查 + Action 拓扑确认 |

---

## 8. DDS-Security Enforce 实际证据

| 项 | 结果 |
| --- | --- |
| 域 43 Enforce 对照实验 | **7 passed / 7 total**（`run-id m3online-regression`） |
| 原生拒绝 | S3/S4 含 Fast DDS `not found in allow rule`（含 ANSI 着色） |
| 正向对照 | S3C `/gateway` → `/rg/nav_execute` 成功 |
| 最小权限核验 | 无通配符、`<default>DENY`、`/planner` 对执行端 0 授权、`/unauthorized` 业务 Action 0 授权 |
| 静默回退 | S6 确认**未发生** |
| keystore | 复用既有（未重建、未覆盖） |

---

## 9. M3 在线联调结果（本轮核心成果）

`run_id = m3online-20261016T134406Z`，域 42，`rmw_fastrtps_cpp`（**普通模式**，非 Enforce；
Enforce 回归另见 §8，两者不是同一次运行）。
配置：`comm_risk=MOCK`、`identity_trust=MOCK`、`task_risk=EXTERNAL`。

| 场景 | M3 状态 | 适配层 | Planner | Gateway | Execution | Goal |
| --- | --- | --- | --- | --- | --- | --- |
| **ON-01** 合法任务 | `ALLOW_RECOMMENDED` | `READY_FOR_GATEWAY_SUBMISSION` | 已提交，`EXECUTED` | **ALLOW** / `ALLOW_IN_POLICY` | 1 | **1** |
| **ON-02** 越界（M3 自身阻断） | `BLOCK_RECOMMENDED` | `ADAPTER_BLOCK` | **未启动** | 未到达 | 0 | **0** |
| **ON-03** UNKNOWN（策略缺失） | `UNKNOWN` | `ADAPTER_BLOCK` | **未启动** | 未到达 | 0 | **0** |
| **ON-04** ERROR（策略损坏） | `ERROR` | `ADAPTER_BLOCK` | **未启动** | 未到达 | 0 | **0** |
| **ON-05** **Gateway 独立权威** | `ALLOW_RECOMMENDED` | `READY_FOR_GATEWAY_SUBMISSION` | 已提交 | **BLOCK** / `OUT_OF_REGION` | 0 | **0** |
| **ON-06** Planner 超时 | `ALLOW_RECOMMENDED` | `READY_FOR_GATEWAY_SUBMISSION` | 超时（客户端未等到结果） | **ALLOW** / `ALLOW_IN_POLICY` | **1** | **1** |

独立复核工具 `scripts/verify_m3_online_evidence.py`：**19 项检查全部 PASS，0 失败**。

**ON-06 的正确解读（勘误）**：该场景 Planner 在 0.5s 内未返回终态（`PLANNER_RESULT_TIMEOUT`），
但按 `request_id = on06-…` 精确匹配的原始审计显示：Gateway 收到请求（1 条 `RosCommEvent`）、
给出 **`ALLOW` / `ALLOW_IN_POLICY`**、并已 **`EXECUTED`**（1 条 `ExecutionEvent`），
NavigationSim 记录 **1** 条 Goal。
即 **Planner 超时不等于 Gateway 未收到、不等于 BLOCK、也不等于未执行**；
客户端观测与权威执行事实必须分别判定。该结论仅适用于本次观测，不可推广。

**ON-05 是本轮最有价值的证据**：它证明上游 M3 在 TEST_ONLY 外扩策略下**自行推导出
`ALLOW_RECOMMENDED`**、适配层也确实放行提交，但 Gateway 依**未修改的权威策略**独立
返回 `BLOCK/OUT_OF_REGION`，且下游 Goal 为 **0**。
即 **Gateway 的权威准入没有被研究模块取代**。

---

## 10. 当前系统最完整的实际运行组合

**`M1 MOCK + M2 MOCK + M3 EXTERNAL`**（ROS 2 Jazzy，域 42，容器 `rg_jazzy`），
完整链路已验证：

```
ModuleInputEnvelope -> team_demo --online -> READY_FOR_GATEWAY_SUBMISSION
   -> Planner -> /rg/guarded_navigate -> SecurityGateway -> TaskPolicy
   -> ALLOW -> /rg/nav_execute -> NavigationSim (+1 Goal)
```

**这不是三模块全真实联合系统**：该组合中 M1 与 M2 是**显式 Mock**。

---

## 11. 尚未实现的功能

| 能力 | 状态 |
| --- | --- |
| 三模块全真实联合在线运行 | `NOT_READY`（M1 缺模型；M2 对候选入口恒 UNKNOWN） |
| ROS 2 实时入侵检测（在线特征采集） | `NOT_READY`（无 ROS 2 订阅采集代码） |
| M1 有效通信异常检测 | `NOT_READY`（性能门槛 FAIL，F1 低于平凡基线） |
| DDS 动态权限调整 | `NOT_READY`（仅静态最小权限，无动态切换证据） |
| 动态任务状态机（`feature/m3-dynamic-policy`） | `NOT_INTEGRATED`（独立分支，与 baseline 互不包含，本轮未审查其算法） |
| M2 当前请求的实时 DDS 身份认证 | `NOT_READY`（设计上不承担） |
| 六类攻击全覆盖评测 | `NOT_RUN`（当前测试集仅 1 类） |

---

## 12. 下一阶段集成任务

1. **为 M1 重训并交付数值 JSON 模型**（含 SHA256），使其可参与真实推理。
2. **PR 目标分支整改**：`#6 → baseline`、`#7 → chore/member-deliveries`、`#8` 因其无独立内容应说明后关闭或转为后续证据 PR。
3. **把 M3 在线证据纳入独立审查 PR**（分支 `integration/m3-online-evidence-20261016`），不合入 baseline 前须审查。
4. 若需 M2 参与在线链路，先为 `/rg/guarded_navigate` 补充受控安全实验，或明确其恒 UNKNOWN 为预期行为。
5. 竞赛材料按 §13 声明口径撰写。

---

## 13. 重要风险

| ID | 风险 | 级别 | 处置 |
| --- | --- | --- | --- |
| **R-1** | PR #6/#7/#8 的 base 均为 `main`，违反团队政策；本环境**无写权限**无法整改 | **P1** | 需有权限者执行：`gh pr edit 6 --base baseline`；`gh pr edit 7 --base chore/member-deliveries`；#8 说明后关闭或改 base |
| **R-2** | `#8` 无独立内容（与 #7 文件差异为零） | P2 | 不要为制造非空 PR 而改无关文件；保留分支与预检标签 |
| **R-3** | M1 无模型产物，三模块全真实联合无法进行 | **P1** | 重训导出 JSON 模型 |
| **R-4** | M1 性能低于平凡基线，若对外宣称"已实现检测"即失实 | **P1** | 按"实验原型、门槛未达标"表述 |
| **R-5** | E 宿主 `python3` 的 jsonschema 为 3.2.0，联调须在容器内执行 | P2 | 统一在容器内运行 |
| **R-6** | `event_id` 与 128 字符上限的旧验收规则冲突 | **已修复** | 验收器对齐契约，Schema 未改 |
| **R-7** | ADP-01 曾把任意非零退出当作输入拒绝 | **已修复** | 新增 10 项反例 + 正向对照 |

---

## 14. 证据与文件索引

| 内容 | 路径 |
| --- | --- |
| 本轮在线证据 | `artifacts/demo-2026-10-19/m3-online-m3online-20261016T134406Z/`（含 `SHA256SUMS.txt`） |
| 跨层复核输出 | 同上 `verification.json` / `verification.md` |
| 权威清单 | 同上 `manifest.json` |
| DDS 安全回归 | 同上 `dds-security-regression/` |
| 在线驱动器 | `scripts/m3_online_drive.sh`、`scripts/m3_online_extra.sh` |
| 复核工具 | `scripts/verify_m3_online_evidence.py` |
| 本轮报告 | `docs/reviews/M3_ONLINE_INTEGRATION_CLOSEOUT_20261016.md` |
| 竞赛声明 | `docs/reviews/COMPETITION_CLAIMS_20261016_CURRENT.md` |
| 历史状态快照 | `docs/team/PROJECT_DEVELOPMENT_STATUS.md`（对应 `046e474`） |
| 历史交付审查 | `docs/reviews/member-deliveries/` |
| 历史 M2/M3 修复 | `docs/reviews/M2_M3_FIX_REPORT.md` |
| 历史预检收尾 | `docs/reviews/DEMO_20261016_PREP_CLOSEOUT.md` |

### 状态口径

`VERIFIED_THIS_RUN` = 本轮实际执行并通过｜`HISTORICAL_REPORTED` = 历史报告声称，本轮未复测｜
`OFFLINE_ONLY` = 仅离线｜`CONTROLLED_TEST` = 受控测试｜`NOT_READY` = 能力未就绪｜
`BLOCKED` = 环境/权限受限｜`NOT_RUN` = 未执行。
