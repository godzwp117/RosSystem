# F0 C 阶段接口建设验收报告

| 项 | 值 |
| --- | --- |
| 报告类型 | 阶段验收记录 |
| 验收对象 | F0-C01 三接口 Schema / F0-C02 统一输入信封 / F0-C03 版本与安全语义 |
| 验收时完整 Git SHA | `03fcc12511501768360ca4c4673ddbb40ec9730f` |
| 所属分支 | `feature/framework-f0` |
| F0 固定基线 | `c2d600dc6e43f989daeb577ed7bb29a6882e7edc` |
| 验收时工作区状态 | **干净**（0 项未提交改动） |
| 契约状态 | **`PROPOSED_V1`** |
| 契约版本 | `1.0.0-proposed` |
| 状态用词 | 仅 `PASS` / `FAIL` / `PARTIAL` / `BLOCKED` / `NOT_RUN` |

---

## 1. 交付物

### 1.1 Schema（4 个）

| 文件 | 作用 | SHA-256（前 16 位） |
| --- | --- | --- |
| `docs/interfaces/schemas/comm_risk_evidence.schema.json` | 通信行为分析输出 | `16f096cd8f682bdc` |
| `docs/interfaces/schemas/identity_trust_assessment.schema.json` | 身份与授权分析输出 | `a9426a872ae80533` |
| `docs/interfaces/schemas/task_risk_decision.schema.json` | 任务风险建议输出 | `cb76aa3d97afffd1` |
| `docs/interfaces/schemas/module_input.schema.json` | 统一输入信封 | `71a165fa12241187` |

全部声明 `$schema` = Draft 2020-12、独立 `$id` 与 `title`、
`additionalProperties: false`（严格字段校验）。

### 1.2 样例（10 有效 + 13 非法）

**有效样例**：`module_input_valid.json`、`comm_normal/suspicious/unknown.json`、
`identity_authorized/denied/error.json`、`task_allow_recommended/block_recommended/unknown.json`

**非法样例**（含 `manifest.json` 声明各自针对的 Schema、失败原因与失败类别）：
见第 4 节。

### 1.3 工具与测试

| 文件 | 作用 |
| --- | --- |
| `scripts/validate_team_contracts.py` | 真实 Draft 2020-12 校验工具（可 CLI 或导入） |
| `tests/unit/test_team_contracts.py` | 契约单元测试，53 项 |
| `docs/interfaces/CONTRACT_VERSION.md` | 版本管理、变更规则、八条安全边界、待确认事项 |
| `docs/interfaces/README.md` | 接口总览、协议、验证方式 |

---

## 2. 校验器名称与版本

| 项 | 值 |
| --- | --- |
| 校验器 | Python `jsonschema` |
| 版本 | **4.10.3**（Debian/Ubuntu 包 `python3-jsonschema 4.10.3-2ubuntu1`） |
| Draft | Draft 2020-12（`Draft202012Validator`） |
| 安装方式 | `apt-get install -y python3-jsonschema`（在 ROS 2 容器内执行） |
| 宿主可用性 | **不可用**：宿主为 `jsonschema 3.2.0`，仅支持 Draft 3/4/6/7，**无法校验 Draft 2020-12** |

**因此全部契约校验与契约单元测试必须在容器内执行。**
宿主上运行 `scripts/validate_team_contracts.py` 会以退出码 3 明确报出版本要求与安装方式，
不会静默跳过。

### 2.1 实测发现：`format` 声明不等于格式校验

本环境实测：

```text
Draft202012Validator.FORMAT_CHECKER 中 "date-time" 是否存在: False
非法时间戳 "2026-10-10 12:00:05" 被拒: False   ← 静默通过
纯日期     "2026-10-10"          被拒: False   ← 静默通过
```

原因：`date-time` 检查需要 `rfc3339-validator`，而本环境**既无 pip 也无对应 Debian 包**
（`apt-cache search` 只有 `python3-rfc3339`，是不同的包）。

**处置**：`scripts/validate_team_contracts.py` 注册了基于标准库的严格 RFC 3339 检查器，
并提供 `self_check_format_checker()` 自检。校验输出首行即打印该自检结果，
且单元测试 `test_format_checker_is_actually_enforced` 会在检查器未生效时**失败**——
避免所有时间戳负例测试假通过。

### 2.2 实测发现：非有限数值必须在解析阶段拒绝

Python `json` 默认接受 `NaN` / `Infinity` 字面量（它们不是合法 JSON）。
数值参与比较时会产生静默错误结论。处置：`load_json_strict()` 使用 `parse_constant`
在解析阶段拒绝，并有单元测试覆盖。

---

## 3. 实际测试命令与结果

### 3.1 契约校验工具

```bash
docker exec rg_jazzy bash -lc 'cd /ws && python3 scripts/validate_team_contracts.py --all'
```

```text
=== 格式检查器自检 ===
  date-time 严格检查生效: True
=== Schema 自身合法性 (4) ===
  [OK] comm_risk_evidence.schema.json
  [OK] identity_trust_assessment.schema.json
  [OK] module_input.schema.json
  [OK] task_risk_decision.schema.json
=== 有效样例 (10) ===        —— 全部 [OK]
=== 非法样例 (13) ===        —— 全部 [OK]（均被真实拒绝）
CONTRACT VALIDATION: PASS
```

**结果：`PASS`**

### 3.2 契约单元测试

```bash
docker exec rg_jazzy bash -lc 'cd /ws && python3 -m pytest tests/unit/test_team_contracts.py -q'
```

**结果：53 passed / 0 failed —— `PASS`**

该测试集**不依赖 ROS 环境**，可在未 source 任何 ROS 环境时运行（实测通过），
仅需 `jsonschema >= 4.0`。

### 3.3 全量单元测试

```bash
docker exec rg_jazzy bash -lc 'cd /ws && source /opt/ros/jazzy/setup.bash \
  && source install/setup.bash && python3 -m pytest tests/unit -q'
```

**结果：208 passed（原有 155 + 新增 53）—— `PASS`**

> **实测发现（重要）**：全量单测**必须先构建并 source `install/setup.bash`**。
> 未 source 时 `tests/unit/test_gateway_audit_safety.py` 与
> `tests/unit/test_interface_contract.py` 会因 `ModuleNotFoundError: No module named
> 'rg_gateway'` 在**收集阶段**中断，表现为 `1 error`（不是测试失败，而是根本没跑起来）。
> 这曾被误判为回归 —— 记入文档以免重复踩坑。

### 3.4 ROS 2 四包构建

```bash
docker exec rg_jazzy bash -lc 'cd /ws && source /opt/ros/jazzy/setup.bash \
  && colcon build --event-handlers console_direct+'
```

```text
Summary: 4 packages finished
```

**结果：`PASS`** —— 新增接口文档与测试未破坏现有工程。

### 3.5 冻结字段与原因码零改动

| 检查 | 结果 |
| --- | --- |
| `src/rg_interfaces/action/PatrolNavigate.action` 是否有改动 | **0**（未改动） |
| `src/rg_policy/rg_policy/reason_codes.py` 是否有改动 | **0**（未改动） |
| 是否新增 Action 绕行入口 | 否 |
| 是否改动 Gateway 核心业务逻辑 | 否 |

**结果：`PASS`**

---

## 4. 典型负面用例（13 项，全部被真实拒绝）

| 非法样例 | 针对 Schema | 失败类别 | 拒绝原因 |
| --- | --- | --- | --- |
| `comm_missing_required.json` | comm_risk_evidence | `missing_required` | 缺少必填字段 `basis` |
| `comm_bad_enum.json` | comm_risk_evidence | `enum_violation` | `status` 取值 `OK` 不在枚举内 |
| `comm_bad_timestamp.json` | comm_risk_evidence | `format_violation` | `observed_at` 非 RFC 3339 |
| `comm_extra_field.json` | comm_risk_evidence | `additional_property` | 出现未声明字段 `trust_me` |
| `comm_bad_version.json` | comm_risk_evidence | `version_incompatible` | `schema_version` = `2.0.0` |
| `comm_number_out_of_range.json` | comm_risk_evidence | `range_violation` | `request_count` 超上界 |
| `comm_wrong_type.json` | comm_risk_evidence | `type_violation` | `request_count` 为字符串 |
| `comm_nan_literal.json` | comm_risk_evidence | `non_finite_number` | 含 `NaN` 字面量，**解析阶段**拒绝 |
| `identity_bad_status.json` | identity_trust_assessment | `enum_violation` | `status` 取值 `TRUSTED` 不在枚举内 |
| `task_execution_target.json` | task_risk_decision | `const_violation` | 候选操作指向执行端 `/rg/nav_execute` |
| `task_bad_digest.json` | task_risk_decision | `pattern_violation` | `policy_digest` 非 64 位十六进制 |
| `input_admin_flag.json` | module_input | `additional_property` | 输入信封出现自报授权开关 `is_admin` |
| `input_execution_resource.json` | module_input | `const_violation` | 输入信封把候选操作指向执行端 |

**负例有效性保证**：每条断言检查校验器**实际返回了错误**，
而不是"校验器运行成功"。清单 `manifest.json` 同时声明失败类别，
并由 `test_manifest_covers_required_negative_categories` 校验类别覆盖完整。

---

## 5. 语义检查结果

这些约束**无法由单份 JSON Schema 证明**，故以独立语义测试覆盖。

| 语义约束 | 覆盖测试 | 结果 |
| --- | --- | --- |
| `request_id` 是业务关联标识，**不代表安全身份** | `test_request_id_semantics_are_documented_as_business_only` | `PASS` |
| `producer` 是自报信息，**不是认证凭据** | `test_producer_semantics_are_documented_as_untrusted` | `PASS` |
| 三模块 `request_id` 一致性，不一致必须可识别 | `test_mismatched_request_id_is_detectable_by_semantic_rule` | `PASS` |
| 样例体现跨模块关联（同 `run_id` + `request_id`） | `test_samples_share_the_same_request_id_for_cross_module_correlation` | `PASS` |
| 上游**无法**把候选操作指向执行端 | `test_upstream_cannot_target_execution_action` | `PASS` |
| 输入信封**不存在**自报授权开关 | `test_input_envelope_forbids_self_reported_authorization_switch` | `PASS` |
| `MOCK` 不得声称已认证身份 | `test_mock_source_never_claims_authenticated_identity` | `PASS` |
| 声称访问控制拒绝必须附原生证据 | `test_denied_example_attributes_denial_to_dds_access_control_with_evidence` | `PASS` |
| `ALLOW_RECOMMENDED` 不是最终授权 | `test_allow_recommended_is_not_final_authorization` | `PASS` |
| 可选 M3 字段缺失仍通过 | `test_optional_m3_fields_may_be_absent` | `PASS` |
| 伪造/格式错误的策略摘要被拒 | `test_fabricated_policy_digest_is_rejected` | `PASS` |
| 三个 Schema 公共定义不漂移 | `test_output_schemas_share_identical_common_definitions` | `PASS` |

### 5.1 本轮由测试暴露并修复的真实缺陷

| # | 缺陷 | 发现方式 | 处置 |
| --- | --- | --- | --- |
| 1 | 三个 Schema 的 `$defs.producer` / `$defs.evidenceRef` 定义**漂移**（描述文本不一致，部分缺少 `description`） | `test_output_schemas_share_identical_common_definitions` 自动比对 | 统一为逐字节一致的规范形，并保留比对测试防再漂移 |
| 2 | `task_risk_decision` 与 `module_input` 的 `request_id` 描述**缺少**"不代表安全身份"声明 | `test_request_id_semantics_are_documented_as_business_only` | 补齐声明 |

> 缺陷 1 说明：因为没有采用跨文件 `$ref`（为了让每个 Schema 自包含、便于独立校验），
> 公共定义被内联三份，存在漂移风险。**已用自动比对测试把该风险变成可检测的失败**，
> 而不是靠人工记得同步。

---

## 6. 与现有代码的对照结果

| 对照项 | 结论 | 结果 |
| --- | --- | --- |
| `task_id` 语义一致 | `task_risk_decision.task_id` 与 `PatrolNavigate.Goal.task_id`、权威 TaskPolicy 语义一致 | `PASS` |
| `request_id` 语义一致 | 与 `PatrolNavigate.Goal.request_id` 对应，且明确为业务关联（`planner_node.py` 中缺省用 `uuid4().hex` 生成，本契约不改该行为） | `PASS` |
| 坐标系与目标结构兼容 | `target{frame_id,x,y,z}` 对应 `geometry_msgs/PoseStamped` 的位置与坐标系部分；`frame_id` 缺省 `map` 与现有 Planner 一致 | `PASS` |
| 不把上游建议映射为最终授权 | `TaskRiskDecision` 描述显式声明"不是最终授权"；测试断言不含 `success`/`authorized` 语义 | `PASS` |
| 无新增 Action 绕行入口 | `action_resource` 由 `const` 固定为 `/rg/guarded_navigate`；未新增任何 Action 客户端 | `PASS` |
| 未改冻结字段与业务原因码 | `PatrolNavigate.action` 与 `reason_codes.py` 零改动 | `PASS` |
| 未为适配 Schema 改动 Gateway | `src/rg_gateway/` 零改动 | `PASS` |

---

## 7. 未解决问题

| # | 问题 | 状态 | 说明 |
| --- | --- | --- | --- |
| 1 | 契约尚未经团队业务确认 | `BLOCKED` | 属流程性阻塞，需相关开发者确认后才能转 `FROZEN_V1`。待确认事项清单见 `CONTRACT_VERSION.md` 第 8 节 Q1–Q8 |
| 2 | 宿主环境无法校验 Draft 2020-12 | `PARTIAL` | 宿主 `jsonschema 3.2.0` 仅到 Draft 7；已提供明确报错与安装方式，校验须在容器内进行 |
| 3 | `date-time` 格式检查依赖自实现 | `PARTIAL` | 环境缺 `rfc3339-validator` 且无 pip；已用标准库实现并通过自检，但与官方实现的边界差异未穷尽验证 |
| 4 | 适配层尚未实现 | `NOT_RUN` | 本轮只定义契约。`request_id` 一致性等语义规则目前只有测试内的参考实现，**没有真实执行代码** |
| 5 | 三个接口尚无真实模块实现 | `NOT_RUN` | 三个研究模块尚未开发；当前仅 `PROPOSED_V1` 契约与样例 |
| 6 | 跨主机 / 跨中间件的结论适用范围未标注 | `NOT_RUN` | 属待确认事项 Q8 |
| 7 | 性能与超时行为未测量 | `NOT_RUN` | 属下一阶段（Mock 与适配层）范围 |

---

## 8. 契约状态

| 项 | 值 |
| --- | --- |
| 状态 | **`PROPOSED_V1`** |
| 版本 | `1.0.0-proposed` |
| 是否已冻结 | **否** |
| 冻结前置条件 | `CONTRACT_VERSION.md` 第 8 节 Q1–Q8 经相关开发者确认，并形成新的评审记录 |
| 状态一致性 | 本报告、`CONTRACT_VERSION.md`、`README.md` 三处均标 `PROPOSED_V1`（已交叉核查） |

---

## 9. 下一阶段（Mock）可依赖的内容

以下内容已稳定，可被 Mock 与适配层直接依赖：

1. **四个 Schema 的字段与约束**——已通过 Draft 2020-12 校验与 53 项单元测试。
2. **进程级调用协议**——stdin 单 JSON / stdout 单 JSON / stderr 诊断 / 退出码语义 / 超时由调用方管理
   （见 `CONTRACT_VERSION.md` 第 6 节）。
3. **`/rg/guarded_navigate` 固定入口约束**——由 `const` 在 Schema 层强制，上游无法绕过。
4. **证据可信级别枚举**——`evidence_refs[].kind` 六类，Mock 必须标 `MOCK`。
5. **`UNKNOWN`/`ERROR` 的保守处置语义**——默认不得推动执行。
6. **一致性检查语义**——`request_id` 不一致必须拒绝；测试内有参考实现可移植。
7. **校验工具**——`scripts/validate_team_contracts.py` 可直接被适配层复用做输出校验。

### 9.1 依赖与前置条件

| 前置 | 说明 |
| --- | --- |
| `jsonschema >= 4.0` | 适配层校验输出所需；安装方式 `apt-get install -y python3-jsonschema` |
| 已构建的工作区 | 全量单测需要；契约测试本身不需要 |
| 冻结的 Action 契约 | 输入信封的 `candidate_action` 语义依赖 `PatrolNavigate.action`，该文件不得改动 |
| 团队确认 | 契约冻结后方宜投入正式适配层实现；当前可按 `PROPOSED_V1` 开展 Mock 开发 |

### 9.2 明确的非目标

- 不新增独立调度服务器、数据库、Web 控制台；
- 不新增常驻 ROS 2 服务作为必需架构；
- 不把 M3 的任务动态状态机纳入 F0 依赖；
- 不为适配接口而改动 Gateway 核心逻辑或冻结契约。

---

## 10. 结论

| 验收项 | 结果 |
| --- | --- |
| 三个输出 Schema 存在且可通过 Draft 2020-12 校验 | `PASS` |
| 统一输入信封存在且对应现有 Action 业务输入 | `PASS` |
| 每个接口有实际通过和实际拒绝的测试样例 | `PASS` |
| 身份来源、风险建议及最终授权边界明确 | `PASS` |
| `request_id` 关联规则明确并有对应测试 | `PASS` |
| `UNKNOWN`、`ERROR` 与版本不兼容行为得到定义 | `PASS` |
| `policy_epoch` / `policy_digest` 不作为 F0 必填字段 | `PASS` |
| 契约状态保持 `PROPOSED_V1` | `PASS` |
| 已有单元测试与 ROS 2 工程无回归 | `PASS`（208 单测 + 4 包构建） |
| 形成真实测试结果与本验收报告 | `PASS` |
| 契约获团队确认并冻结 | `BLOCKED`（需人工确认，非技术阻塞） |

**总体判定：技术交付 `PASS`；契约冻结 `BLOCKED`（等待团队确认）。**
