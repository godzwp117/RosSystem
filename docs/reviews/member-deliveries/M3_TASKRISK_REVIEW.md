# 成员三技术审查：任务风险推理（`task_risk`）

- 审查对象：`deliveries/member3-taskrisk/`（17 个文件）
- 来源快照：`chore/member-deliveries` = `3ce820258c69b89e2ad9291e16c44dc7d2b99150`
- 来源基线：`a4c597161d254192b662ee7b8f4d17f76a89cc16`（其 `reports/*.json` 自述）
- 核心文件 SHA-256：
  - `modules/member3_taskrisk/risk_model.py` = `db724fcd754853688dbe2b44022d3e77e2d704562631c7ae6b5c2b07fe686d2c`
  - `modules/member3_taskrisk/module.py` = `5150cf2b547a8e6377f494fbb8a023ffb5043bc74a32446954781de163cae2ee`
  - `modules/member3_taskrisk/experiments.py` = `aa1873cf2ba46c3aa410d560849621cd5cf89df884ae9b6036f2c30f484ac505`
  - `modules/member3_taskrisk/online_check.py` = `294184150b2baa34342e3654bd72824bcf3767a000db42d7b0499b68b2559789`
  - `reports/offline_report.json`、`reports/generic_acceptance_report.json` 等完整值见 `EVIDENCE_INDEX.json`
- 本轮实际执行：95 项单测复测、`check_member_module.py` 通用验收复测、联合适配层联调、离线报告逐字段核对

---

## 1. 结论摘要

| 项 | 结论 | 证据等级 |
| --- | --- | --- |
| 实现类型 | **确定性可解释规则引擎**（`TASK_CONSTRAINT_RULES_V1`），**不是**机器学习/深度学习模型 | E1_CODE + E2_STATIC |
| 是否纯规则 | 是。`risk_model.infer()` 无训练产物、无概率模型、无随机性 | E1_CODE |
| 是否复刻 Mock | **否**。真实评估本地 TaskPolicy，`f0_mock` 场景开关被忽略 | E1_CODE + E4_INTEGRATION_TEST |
| 输出契约 | `TaskRiskDecision`，`policy_ref.policy_version` 来自真实策略 | E1_CODE + E3_UNIT_TEST |
| 单测 | **95 passed**（本轮复测） | E3_UNIT_TEST |
| 通用验收 | **33 PASS / 3 FAIL / 1 NOT_RUN / 1 BLOCKED**（本轮精确复现其交付报告） | E4_INTEGRATION_TEST |
| 3 项 FAIL 真实原因 | **验收脚本 Mock fixture 不兼容**，非算法逻辑错误（已证，见 §5） | E2_STATIC + E4_INTEGRATION_TEST |
| 真实算法能力 | 在真实适配层中正确给出 `ALLOW_RECOMMENDED` / `BLOCK_RECOMMENDED` | E4_INTEGRATION_TEST |
| L3 ROS 2 在线联调 | **BLOCKED**（无 ROS 运行时） | UNVERIFIED |

---

## 2. 风险推理方法与风险因子

### 2.1 方法：静态条款 + 可选历史快照

`risk_model.infer()`（`risk_model.py:192-286`）分两段：

**第一段：静态策略条款（确定性、无状态）**

| 风险因子 | 来源 | 代码位置 |
| --- | --- | --- |
| `policy_active` | 本地 TaskPolicy `active` 字段 | `risk_model.py:225,229-230` |
| `task_matches` | `envelope.candidate_action.task_id` vs `policy.task_id` | `risk_model.py:225,233-234` |
| `frame_matches` | `target.frame_id` vs `policy.coordinate_frame` | `risk_model.py:226,235-236` |
| `target_finite` | `target.x/y/z` 是否有限 | `risk_model.py:227,237-238` |
| `region_inside` / `signed_boundary_margin_m` | 目标到 `policy.region` 四边的**有符号最小距离** | `risk_model.py:239-244` |
| `request_id` 非空白 | 业务信封 | `risk_model.py:231-232` |

**第二段：可选历史推断（仅当无静态违规且配置了 `--audit-log`）**

| 风险因子 | 来源 | 代码位置 |
| --- | --- | --- |
| `duplicate_in_snapshot` | 整个会话 journal 中同 `request_id` 是否已出现 | `risk_model.py:253,255-257` |
| `admitted_in_snapshot` | 滑动 60 秒内 `decision=ALLOW` 的到达数 | `risk_model.py:181,254,258-260` |

### 2.2 明确区分：规则引擎，不是训练模型

- 无模型文件、无 `.joblib`/`.pkl`、无特征张量、无阈值学习；
- `inprocess_latency_ms_median = 1.59 ms` 是**进程内校验+规则调用**耗时，报告自身注明 `latency_note`：*"local in-process validation+rule calls, NOT realtime ROS throughput"*；
- `boundary_margin_m` 的代码注释明确写 *"distance heuristic, NOT a probability"*（`risk_model.py:56`）。

**因此禁止在任何材料中把本模块称为「深度学习风险预测」「智能风险模型」或「经训练的模型」。** 它是**可解释的确定性任务约束建议器**。

---

## 3. 与 Gateway 的语义重合（关键判断）

这是任务书点名要查的问题，结论明确：

**M3 的静态条款集是 Gateway 权威判定 `rg_policy.policy_engine.evaluate` 的 1:1 同义复刻，且复用同一份解析器与同一套原因码。**

证据：

1. **同一解析器**：`risk_model.py:18` 直接 `from rg_policy.task_policy import ... parse_task_policy`，与 Gateway 用的是**同一个函数**（`src/rg_policy/rg_policy/task_policy.py:144`）。
2. **同一套原因码**：`risk_model.py:17` `from rg_policy import reason_codes as rc`，八个原因码完全共用。
3. **条款一一对应**：

| Gateway `policy_engine.evaluate` 步骤 | M3 `infer()` 对应 |
| --- | --- |
| 1. policy absent/inactive → `POLICY_MISSING` | `policy_active` 违规 → `POLICY_MISSING` |
| 2. request_id 缺失 → `INVALID_TARGET` | `request_id.strip()` 空 → `INVALID_TARGET` |
| 3. task_id 不匹配 → `TASK_MISMATCH` | `task_matches` 假 → `TASK_MISMATCH` |
| 4. frame_id 不匹配 → `INVALID_TARGET` | `frame_matches` 假 → `INVALID_TARGET` |
| 5. 非有限数 → `INVALID_TARGET` | `target_finite` 假 → `INVALID_TARGET` |
| 6. 区域外 → `OUT_OF_REGION` | `margin < 0` → `OUT_OF_REGION` |
| 7. 否则 `ALLOW_IN_POLICY` | 无违规 → `ALLOW_IN_POLICY` |

**推论**：`offline_report.json` 中 `static_verdict_agreement = 1.0`、`false_positive_rate = 0.0`、`false_negative_rate = 0.0` **在很大程度上是构造性的**——比较器 `static_comparator` 字段自己写明是 `rg_policy.policy_engine.evaluate, NOT a live Gateway`，即**在进程内与同源规则比对**。

**不得**把「与 Gateway 静态规则一致率 100%」表述为「攻击检测准确率 100%」或「新型未知攻击检测能力」。它证明的是**条款覆盖与实现一致性**，不是检测泛化能力。

### 3.1 M3 相对 Gateway 的真实增量

| 增量 | 说明 | 价值 |
| --- | --- | --- |
| **保留全部违规** | Gateway 是 first-fail-wins；M3 聚合所有静态违规并逐条给出 `policy_field` + 解释 | 可解释性提升，便于运维定位 |
| **有符号边界距离** | `signed_boundary_margin_m`（离最近允许边界的米数），并据此给 `LOW`/`NONE` 风险等级 | **新的任务上下文安全证据**，Gateway 无此输出 |
| **历史快照推断** | 从 Gateway journal 快照推断 `DUPLICATE_REQUEST` / `RATE_LIMIT` | 与 Gateway 的并发 `RequestTracker` 不同源，属独立推断 |
| **policy_version 透传** | 输出 `policy_ref.policy_version` | 审计可追溯 |

它的定位因此是**「独立实现的建议与解释层」**，而不是「独立的新检测算法」。

---

## 4. 输入处理细节（逐条回答任务书问题）

| 问题 | 实现 |
| --- | --- |
| 任务 ID | 与 `policy.task_id` 严格相等比较；空白或不匹配 → `TASK_MISMATCH` |
| 位置与目标区域 | 闭区间包含判定；另算有符号边界距离；区域外 → `OUT_OF_REGION` |
| 频率与重复请求 | **仅在有 `--audit-log` 时**：同一 `request_id` 在 `duplicate_ttl_sec`（默认 600 s）内出现过 → `DUPLICATE_REQUEST`；60 秒内 `ALLOW` 数 ≥ `policy.max_requests_per_minute` → `RATE_LIMIT` |
| 策略缺失 | 文件不存在 → `UNKNOWN` + `POLICY_MISSING`；解析/校验失败 → `ERROR` + `POLICY_MISSING`（**两种不同状态，均为不推进**） |
| 任务状态变化 | **未实现**。`extensions.dynamic_state_model = "NOT_INTEGRATED"`，`runtime_monitor = "NOT_READY"` |
| 输出合规 | `module.py:63-66` 输出前用官方 `task_risk_decision` Schema 自校验，失败即抛错 |
| 误报/漏报 | 受控 87 场景下均为 0，但这只对**合成且由同一策略生成**的场景成立，不构成对真实流量的 FPR/FNR |

### 4.1 历史推断的严格前提（值得肯定）

`read_history()`（`risk_model.py:101-185`）对历史证据采取强约束，任何一条不满足即**失败关闭**：

- 必须由操作员指定**单个** Gateway 的完整会话 journal 与 `audit_session_start`；
- journal 超过 4 MiB / 20000 条 → `HistoryUnavailable`；
- 末尾撕裂行（无换行）→ 拒绝；
- 文件 mtime 超过 `max_history_age_sec`（默认 30 s）→ 视为陈旧；
- 事件必须成对（`RosCommEvent` ↔ `DecisionEvent`），缺失即拒绝；
- `decision` 与 `reason_code` 必须自洽（`ALLOW` ⟺ `ALLOW_IN_POLICY`）；
- 时间必须落在会话区间内，且 decision 不得早于 arrival。

代码注释亦如实声明：*"Historical inference is a snapshot, not Gateway's concurrent tracker"*、*"mtime does not prove a live node"*。**这是本模块在工程诚实度上最突出的优点。**

---

## 5. 通用验收 3 项 FAIL 的真实原因（任务书 6.4）

### 5.1 现象

本轮用正确解释器复现，结果与其交付的 `reports/generic_acceptance_report.json` **完全一致**：

```
计数: {'PASS': 33, 'FAIL': 3, 'NOT_RUN': 1, 'BLOCKED': 1}
达到 PR 合入门槛: False
FAIL: STATE-BLOCK / STATE-UNKNOWN / STATE-ERROR
```

四状态实测：

| 场景 | 期望 | 实际 | rc | schema_ok |
| --- | --- | --- | --- | --- |
| allow | `ALLOW_RECOMMENDED` | `ALLOW_RECOMMENDED` | 0 | True |
| block | `BLOCK_RECOMMENDED` | `ALLOW_RECOMMENDED` | 0 | True |
| unknown | `UNKNOWN` | `ALLOW_RECOMMENDED` | 0 | True |
| error | `ERROR` | `ALLOW_RECOMMENDED` | 0 | True |

### 5.2 根因：验收脚本用 Mock 专用通道驱动场景

`scripts/check_member_module.py:82-88`：

```python
def envelope_for(module: str, scenario: str, request_id: str) -> dict:
    env['observations'][0]['detail']['f0_mock'] = {
        'comm_risk': {'scenario': scenario},
        ...
        'task_risk': {'scenario': scenario},
    }
```

即：验收脚本把期望状态塞进 `detail.f0_mock.task_risk.scenario`，**只有基线自带的 Mock 会读这个字段**。成员三的真实模块**刻意忽略它**（这是正确做法——真实算法不应从输入里读取自己的答案），因此四个场景都用真实策略评估同一个合法目标，自然都得到 `ALLOW_RECOMMENDED`。

### 5.3 对照实验（本轮新增，决定性证据）

用基线默认配置（三个模块全为 `mode: mock`）跑同一脚本：

| 配置 | 结果 |
| --- | --- |
| `config/team_modules.example.yaml`（全 Mock）× 3 个模块 | **34 PASS / 3 NOT_RUN / 1 BLOCKED**，`达到 PR 合入门槛: True` |
| 成员三 `external` | 33 PASS / **3 FAIL** / 1 NOT_RUN / 1 BLOCKED，门槛 False |

**结论：该验收脚本对「真实外部模块」存在结构性不兼容。** 3 项 FAIL 既不能作为「成员三算法错误」的证据，也不能因为 `meets_pr_gate: False` 而否定其算法——**它只说明该脚本当前无法验收任何非 Mock 模块的四状态矩阵**。成员三在报告中如实记录了这一点（`IMPLEMENTATION_REPORT.md:20`），值得肯定。

同一原因也解释了成员一的 `baseline_checker` FAIL（`artifacts/member1/local_evidence/report.json`：*"baseline fixtures supply no real features/runtime metadata; module refuses invented mapping"*）。

---

## 6. 87 个受控场景的生成方式与覆盖范围

来自 `reports/offline_report.json`：

| 字段 | 值 |
| --- | --- |
| `dataset_source` | `controlled cases generated from local TaskPolicy; **not captured ROS traffic**` |
| `case_count` / `correct_cases` | 87 / 87 |
| `static_comparator` | `rg_policy.policy_engine.evaluate, **NOT a live Gateway**` |
| `static_verdict_agreement` | 1.0 |
| `false_positive_rate` / `false_negative_rate` | 0.0 / 0.0 |
| `geometry_only_ablation_false_negative_rate` | 0.1316 |
| `L1_REAL_CONDITIONS` / `L2_CONTROLLED_STATIC` / `L3_ROS2_ONLINE` | PASS / PASS / **BLOCKED** |

其 `IMPLEMENTATION_REPORT.md:18` 说明构成：**81 组边界网格 + 6 个任务/坐标系/策略异常条件**。

**88 个原因码覆盖分布**（`eight_code_coverage`）：

| 原因码 | 覆盖层级 |
| --- | --- |
| `ALLOW_IN_POLICY` / `TASK_MISMATCH` / `INVALID_TARGET` / `OUT_OF_REGION` / `POLICY_MISSING` | `CONTROLLED_STATIC` |
| `DUPLICATE_REQUEST` / `RATE_LIMIT` | **`UNIT_TEST_HISTORY_ONLY`** |
| `EXECUTION_TIMEOUT` | **`NOT_READY_GATEWAY_EXECUTION_ONLY`** |

即：**八个原因码中只有 5 个在受控静态实验中真实覆盖；2 个仅单测；1 个未实现。**

### 6.1 消融实验能证明什么、不能证明什么

- **能证明**：把「几何规则」单独使用（去掉 task/frame/policy 条款）时，FN 从 0 升到 13.16%——说明非几何条款对结果有实际贡献，条款集合不是冗余装饰。
- **不能证明**：模型对**未知攻击**的泛化能力；也不能作为检测准确率。因为场景由本地策略生成、比较器是同源规则，二者共享同一语义。

报告中 `disagreements_to_investigate_online` 列出的 4 条差异场景（并发去重、策略热重载、历史不可用、执行超时）**是有价值的诚实清单**，正是 L3 必须验证的内容。

---

## 7. Gateway 安全边界

| 检查 | 结果 |
| --- | --- |
| 是否绕过 Gateway 直接调用 `/rg/nav_execute` | **否**。全模块无 ROS 调用、无 Action 客户端；`online_check.py` 仅做只读联调 |
| `ALLOW_RECOMMENDED` 是否被当作执行许可 | **否**。输出 `extensions.member3.authority = "ADVISORY_ONLY"`，`rule_basis` 显式写明「建议不是执行许可」 |
| 是否修改 Gateway 权威策略 | **否**。只读 `--policy` 指定文件，并以 `policy_ref` 回填版本 |
| 是否可被输入伪造放行 | **否**。输入校验基于官方 `module_input` Schema，且 `candidate_action.action_resource` 为 `const /rg/guarded_navigate` |
| 建议允许但目标越界时 Gateway 是否仍能阻断 | **本轮在适配层验证到一半**：目标 (999,999) 时 M3 正确给出 `BLOCK_RECOMMENDED` → 适配层 `ADAPTER_BLOCK`；**Gateway 层的最终阻断本轮未复跑**（需 ROS 运行时，见 `INTEGRATION_READINESS.md`） |

**未发现「直接操作下游执行接口」的 P0 问题。**

---

## 8. 依赖与可复现性

- `module.py:15` 把 `REPO/scripts`、`REPO/src/rg_policy`、自身目录插入 `sys.path`，因此**必须在仓库布局下运行**（`modules/member3_taskrisk/`）；直接从 `deliveries/` 原地运行会 `ModuleNotFoundError`。
- 依赖 `PyYAML`（`requirements.txt`）与 **`jsonschema>=4.0`**。
- **缺陷（P2）**：当 `jsonschema < 4` 时，`vtc.load_schema()` 抛 `RuntimeError`（`scripts/validate_team_contracts.py:115`），而 `module.py:96` 只捕获 `(ValueError, TypeError, UnicodeError, RecursionError)`，**`RuntimeError` 未被捕获** → 进程带 traceback 退出 **rc=1**，且 stdout 为空，未生成受控的 `ERROR` 文档。适配层会把非零退出判为阻断（失败安全），但这是**不受控崩溃**而非设计内失败关闭。

```text
Traceback (most recent call last):
  File "modules/member3_taskrisk/module.py", line 95, in main
    validate_input(envelope)
  File "modules/member3_taskrisk/module.py", line 36, in validate_input
    errors = vtc.validate_document(envelope, vtc.load_schema("module_input"))
RuntimeError: 缺少 jsonschema>=4.0（Draft 2020-12 需要）...
```

- 其余依赖行为正常：`online_check.py` 在无 ROS 时明确退出（其报告称退出码 3）。

---

## 9. 安全审查

### 9.1 优点

- **严格 YAML**：`UniqueSafeLoader` 拒绝重复键（`risk_model.py:35-50`），防止后键覆盖前键造成的策略歧义；
- **有界读取**：策略 64 KiB、journal 4 MiB / 20000 条上限，防资源耗尽；
- **路径来自受信任 CLI 配置**，不从 stdin 读取（`module.py:79-86` 注释明确）；
- **失败关闭**：非法输入 rc=2；内部异常尝试产出 `ERROR` 文档；`UNKNOWN`/`ERROR` 均不推进；
- **非有限数防御**：`validate_input` 递归检查 NaN/Inf（`module.py:26-35`）；
- **输出自校验**：写 stdout 前用官方 Schema 校验。

### 9.2 缺陷

| 级别 | 问题 | 位置 | 触发条件 | 影响 | 修复建议 |
| --- | --- | --- | --- | --- | --- |
| **P2** | `RuntimeError` 未捕获 → rc=1 崩溃 | `modules/member3_taskrisk/module.py:96` | 运行环境 `jsonschema<4` | 无受控 ERROR 文档；适配层只能靠非零退出阻断 | 捕获 `Exception` 或至少加入 `RuntimeError`，产出 ERROR 文档并以约定码退出 |
| **P3** | `--audit-log` 走 `Path(settings.audit_log).open()`，未做符号链接/属主校验 | `risk_model.py:114` | 本地配置指向符号链接 | 可能读取非预期文件 | 增加 `is_symlink()` 拒绝，与其他成员模块保持一致（M2 已做） |
| **P3** | 历史推断的正确性依赖操作员自述前提（"dedicated complete current-session journal"），JSON 无法自证 | `risk_model.py:101-107,184` | 配置错误 | 可能基于不完整历史给出建议 | 保持现状但在文档与输出中显著提示（**代码已如实标注，属可接受局限**） |

**未发现 P0。**

---

## 10. 证据等级评定

| 结论 | 等级 | 说明 |
| --- | --- | --- |
| 确定性规则引擎，非 ML | **A** | 源码通读，无训练产物 |
| 95 项单测通过 | **A** | 本轮复测 |
| 通用验收 33/3/1/1 | **A** | 本轮精确复现其交付报告 |
| 3 项 FAIL = Mock fixture 不兼容 | **A** | 已用 Mock 对照组证明 |
| 87/87 受控静态场景正确 | **B** | 报告 JSON 完整可核对，本轮未重跑 `experiments.py` |
| 与 Gateway 静态判定同源 | **A** | 源码级证据（共用解析器与原因码） |
| `DUPLICATE_REQUEST` / `RATE_LIMIT` 能力 | **C** | 仅单测，无真实 journal 端到端证据 |
| `EXECUTION_TIMEOUT` | **N** | 未实现 |
| L3 ROS 2 在线联调 | **N** | 无证据 |

---

## 11. 最终评价

**研究贡献**：
1. 把「应用层任务约束」从 Gateway 内部逻辑**外化为一个可独立解释、可聚合多条违规的顾问模块**；
2. 引入**有符号边界距离**作为新的任务上下文风险特征（Gateway 无此输出）；
3. 建立了一套对历史证据**极其严格的 fail-closed 读取纪律**，并诚实标注其快照性质；
4. 在报告中主动暴露自身 3 项 FAIL 与 L3 BLOCKED，**没有把规则一致性包装成检测能力**。

**局限**：
1. 静态条款与 Gateway 同源，`agreement=1.0` 不构成独立检测能力证明；
2. 无动态任务状态机（`NOT_INTEGRATED`），`EXECUTION_TIMEOUT` 未覆盖；
3. 历史推断能力仅有单测证据；
4. 缺少真实 ROS 流量下的误报/漏报数据。

**集成建议**：**可以立即集成的部分**——静态条款建议器（L1 已验证、fail-closed 正确、无旁路），作为**建议与解释层**接入；**必须修改后集成**的部分——历史推断（P1 单测证据不足 + 需真实 journal）与 `jsonschema` 崩溃路径（P2）。在竞赛材料中必须表述为「**确定性规则 + 可解释建议**」，**不得**表述为机器学习模型、智能风险预测或未知攻击检测。

**验收门槛**：`MEMBER3_CODE_AUDIT` = **PASS**；`MEMBER3_TASK_EVIDENCE` = **PARTIAL**（受控静态证据充分，真实/在线证据缺失）。
