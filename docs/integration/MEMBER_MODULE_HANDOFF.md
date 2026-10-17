# 成员模块交接（工作 A → 工作 B1）

| 项 | 值 |
| --- | --- |
| 交接版本 | `member_module_handoff/1.0.0`（**第二阶段更新：见 §10**） |
| 产出工作包 | 工作 A：成员真实模块适配、兼容性修复与必要重构 |
| 目标分支 | `integration/member-module-adaptation` |
| 开发基准 | `demo-2026-10-19-rc2-verified` = `33cb4f93d5e5fd268878fe83fc040c655d632a70` |
| 机器可读版 | `docs/integration/member_module_handoff.yaml`（B1 应以它为准） |
| 模块可执行性总表 | 见文末第 7 节 |

> 本文件是 **B1 的正式接口输入**。凡涉及"能不能用"、"怎么调用"、"什么不算证据"，
> 都以本文件与 `.yaml` 为准；两者冲突时以 `.yaml` 的字段值为准并请提出修订。

---

## 0. 一页结论

| 模块 | 真实可调用 | 输出合规 | 证据可追溯 | 能否真实推进 |
| --- | --- | --- | --- | --- |
| M1 `comm_risk` | PASS | PASS | PASS | **FAIL** |
| M2 `identity_trust` | PASS | PASS | PASS | **FAIL** |
| M3 `task_risk` | PASS | PASS | PASS | PASS |

**为什么 M1/M2 是 FAIL（都不是工程缺陷，而是如实的能力边界）：**

* M1：交付模型的验证门槛 `validation_gate_passed=false`（测试集 F1 0.1312 < 恒预测攻击基线 0.8132），
  且 ROSPaCe 的 49 维特征在 ROS 2 Jazzy 运行时没有等价的实时采集器。
  生产语义下它只能给 UNKNOWN 或 SUSPICIOUS，**不会给 NORMAL**。
* M2：历史受控实验（S2/S3/S3C/S4）能解释**当时那次运行**的授权结论，
  但无法证明**当前**这条候选请求的发送方是谁——ROS 2 Jazzy 不暴露
  "订阅端对端主体身份"。当前身份恒为 UNKNOWN，适配层因此阻断。

**因此：** 三模块联合运行的正确结果是 `ADAPTER_BLOCK`。
能走到 `READY_FOR_GATEWAY_SUBMISSION` 的只有受控测试配置
（`--controlled-test` 或显式 Mock），这些结果**不得**写入任何"检测有效/身份已认证"的结论。

---

## 1. 目录与文件处置

处置语义：`REUSE` 直接复用 / `ADAPT` 接口与路径适配 / `REFACTOR` 必须重构 /
`REJECT` 不应合入 / `DEFER` 非本次整合必需。

### 1.1 成员一（M1）

原始交付：`user/RosSystem-member1-delivery/RosSystem`
（`REVISION.txt`: branch `feature/member1-comm-offline-baseline`, head `21f5280`,
baseline `a4c5971`, `contract_status=PROPOSED_V1`, `model_performance_gate=FAIL`,
`RUNTIME_MONITOR=NOT_READY`）

成员一的交付包是**整个 RosSystem 的旧快照加上他自己的 `modules/my_comm`**。
因此必须逐文件判断：只有 `modules/my_comm` 是成员代码，其余是旧系统副本。

| 交付文件 | 处置 | 目标 | 说明 |
| --- | --- | --- | --- |
| `modules/my_comm/module.py` | ADAPT | `modules/member1_comm/module.py` | 包名迁移；模型根白名单；特征清单校验；受信任观察来源；`extensions` 改名 |
| `modules/my_comm/data.py` | ADAPT | `modules/member1_comm/data.py` | 仅 import 路径 |
| `modules/my_comm/train.py` | ADAPT | `modules/member1_comm/train.py` | 仅 import 路径 |
| `modules/my_comm/metrics.py` | REUSE | `modules/member1_comm/metrics.py` | 字节一致 |
| `modules/my_comm/features.json` | REUSE | `modules/member1_comm/features.json` | 49 维特征清单，字节一致 |
| `modules/my_comm/test_module.py` | ADAPT | `modules/member1_comm/test_module.py` | 仅 import 路径 |
| `modules/my_comm/test_integration.py` | ADAPT | `modules/member1_comm/test_integration.py` | import 路径 + 受控模型补 `--features` |
| `modules/my_comm/example_config.yaml` | REFACTOR | `modules/member1_comm/example_config.yaml` | 换成真实模型 SHA 与真实路径 |
| `modules/my_comm/README.md` | REFACTOR | `modules/member1_comm/README.md` | 面向系统集成重写；保留能力边界 |
| `modules/my_comm/requirements.txt` | REUSE | `modules/member1_comm/requirements.txt` | numpy/sklearn/jsonschema/PyYAML/pytest |
| `modules/my_comm/download_data.py` | DEFER | `modules/member1_comm/download_data.py` | 复现数据获取用，运行时不使用 |
| `modules/my_comm/run_controlled_protocol.py` | DEFER | `modules/member1_comm/run_controlled_protocol.py` | 需 Jazzy + SROS2，本环境无 ROS |
| `modules/my_comm/run_ros_controlled_protocol.py` | DEFER | 未纳入 | 需 ROS 2 运行时与 SROS2 keystore |
| `modules/my_comm/write_config.py` | DEFER | 未纳入 | 生成本地配置的便利脚本，与受信任配置流程重复 |
| `src/`、`scripts/`、`mock_modules/`、`security/`、`templates/`、`.github/`、`docs/interfaces/schemas/`、`tests/`、`pytest.ini`、`config/task_policy.yaml` | **REJECT** | 不带入 | 这是**旧系统快照**。主线同名文件更新（例如 F0 适配层、公共 Schema、策略、单元测试）。整体覆盖会回退已验证修复 |
| `artifacts/member1/**` | DEFER | 未带入 | 成员本地证据包；已在 `deliveries/member1-comm/` 归档，报告中按其数值引用 |
| `REVISION.txt`、`RosSystem-member1-changes.patch` | REUSE | 保持 `deliveries/member1-comm/` 归档 | 来源与版本证据 |

新增（不属于成员交付，但属于本次适配的产物）：

| 文件 | 说明 |
| --- | --- |
| `modules/member1_comm/model/comm_risk_model.json` | 用交付训练代码 + 官方 ROSPaCe 归档重新训练得到的纯数值模型（1.3 MB） |
| `modules/member1_comm/model/model_manifest.json` | 模型身份清单：SHA-256 / 算法 / 阈值 / 门槛 / 数据来源 / 复现命令 |
| `modules/member1_comm/model/train_report.json` | 训练/验证/测试报告（含门槛判定与数值一致性校验） |
| `modules/member1_comm/export_probe_rows.py` | 从 held-out 分片导出真实数据行作为 fixtures |
| `tests/fixtures/member1/rospace_comm_rows.json` | 3 条真实 held-out 行（分片/原始行号/标签/打分可追溯） |
| `config/team_modules.member1.real.yaml`、`config/acceptance/real_scenarios.member1.yaml` | 真实验收配置与 fixture |

### 1.2 成员二（M2）

原始交付：`user/RosSystem_Member2_DDS_Identity_Delivery`（`deliveries/member2-identity` 已归档）

| 交付文件 | 处置 | 目标 | 说明 |
| --- | --- | --- | --- |
| `identity_trust/assessor.py`（`b287822e…`） | **REJECT 该版本** | — | 主线的 `identity_trust/assessor.py` 是它的**超集**：已修复 ANSI 控制序列插进 `SECURITY Error` 字样、原生拒绝行内匹配（`Permissions.cpp:<行号>`）、超时/业务阻断不得当作 DDS 拒绝、历史资源错配等。用交付版本覆盖会回退这些修复 |
| `identity_trust/`（主线版本） | REFACTOR | `identity_trust/assessor.py` | 新增 `extensions.current_request_identity`；历史证据与当前身份分离；重放/复用账本 |
| — | REFACTOR(新增) | `identity_trust/current_identity.py` | 可信证据契约 + HMAC 核验 + 新鲜度/串单/跨资源/重放检查 |
| `config/team_modules.member2.example.yaml` | REUSE | `config/team_modules.member2.real.yaml`（主线已存在） | 内容已在主线定稿 |
| `scripts/member2_adapter_check.py` | REUSE | 主线同名文件（字节一致） | — |
| `tests/unit/test_identity_trust_assessor.py` | REUSE | 主线同名文件（主线为超集版本） | 本工作补充了 `test_identity_current_binding.py` |
| `docs/MEMBER2_IMPLEMENTATION.md` | REUSE | `deliveries/member2-identity/docs/` 归档 | 不重复入库 |
| `config/acceptance/real_scenarios.member2.yaml` | ADAPT | 主线同名文件 | S2 场景新增 `expect.adapter_decision: ADAPTER_BLOCK` |

### 1.3 成员三（M3）

原始交付：`user/RosSystem_member3_taskrisk_source_v0.1.0/RosSystem_member3_taskrisk_source_v0.1.0`
（`MANIFEST.json`: `packaging_change_only=true`, source commit `00f3f21`）

| 交付文件 | 处置 | 目标 | 校验 |
| --- | --- | --- | --- |
| `modules/member3_taskrisk/module.py` | REUSE | 主线同名 | SHA-256 完全一致 |
| `modules/member3_taskrisk/risk_model.py` | REUSE | 主线同名 | SHA-256 完全一致 |
| `tests/unit/test_member3_taskrisk.py` | REUSE | 主线同名 | SHA-256 完全一致 |
| `config/team_modules.member3.yaml` | REUSE | 主线同名 | SHA-256 完全一致 |
| `modules/member3_taskrisk/README.md` / `example_config.yaml` / `requirements.txt` | REUSE | 主线同名 | 一致 |
| `modules/member3_taskrisk/experiments.py` | DEFER | 未纳入 | 离线实验驱动；联合运行不需要 |
| `modules/member3_taskrisk/online_check.py` | DEFER | 未纳入 | 已被 `scripts/m3_online_*` 与 ON-01..ON-06 归档证据替代 |
| `modules/member3_taskrisk/test_module.py` | DEFER | 未纳入 | shim 测试入口；主线用 `tests/unit/test_member3_taskrisk.py` |
| `docs/member3/`、`reports/`、`member3.patch`、`MANIFEST.json`、`START_HERE.md` | REUSE(归档) | `deliveries/member3-taskrisk/` | 来源证据 |

**结论**：M3 无需重构。本次对 M3 的工作是**回归证明**（四状态、超时、异常路径、
ID 关联、与 M1/M2 的资源隔离）与**联合配置**，不是改规则引擎。

---

## 2. 三模块真实运行命令

工作目录统一为仓库根目录。`PY` 必须是装有 `jsonschema>=4.0` 的解释器。

```bash
# 环境自检（缺依赖会失败关闭，而不是静默放行）
$PY -c "from jsonschema import Draft202012Validator; print('contract deps ok')"

# ---- M1：真实模型推理（生产语义：低于阈值只能 UNKNOWN）----
$PY modules/member1_comm/module.py \
    --model modules/member1_comm/model/comm_risk_model.json \
    --model-sha256 d45d272eea9dfef67b2b0066af0fd078270d559a4a4e350b7558d072c21c40df \
    --features modules/member1_comm/features.json \
    --observation-provenance UNKNOWN \
    < envelope.json

# ---- M2：历史证据解释 + 当前身份绑定（默认 UNKNOWN）----
$PY identity_trust/assessor.py \
    --experiment-run 20261009T093144Z \
    --evidence-root artifacts/acceptance/exports/m2_sros2_enforce/logs/tests_evidence \
    --policy security/policies/minimal_permissions.xml \
    --keystore security/keystore \
    --case S2 \
    --identity-ledger logs/all-real/identity_ledger.jsonl \
    < envelope.json

# ---- M3：确定性规则引擎（权威策略只读）----
$PY modules/member3_taskrisk/module.py --policy config/task_policy.yaml < envelope.json
```

### 经 F0 适配层调用（唯一正确的准入前置路径）

```bash
# 单模块真实化（其余保持 Mock）
$PY scripts/team_demo.py --input envelope.json --config config/team_modules.member1.real.yaml

# 三模块全部真实：正确结果是 ADAPTER_BLOCK
$PY scripts/team_demo.py --input envelope.json --config config/team_modules.all-real.yaml

# 受控测试配置（M1 加 --controlled-test；M2 仍会阻断）——仅用于链路验证
$PY scripts/team_demo.py --input envelope.json --config config/team_modules.all-real.controlled-test.yaml
```

`READY_FOR_GATEWAY_SUBMISSION` **不是** Gateway ALLOW；`ADAPTER_BLOCK` 是适配层
的本地阻断，两者都不改变 Gateway 的权威判定。

---

## 3. 输入 / 输出契约与退出码

| 项 | 值 |
| --- | --- |
| 输入 | `ModuleInputEnvelope`（`docs/interfaces/schemas/module_input.schema.json`），stdin 单对象 |
| 输出 | 每模块一个 Schema：`comm_risk_evidence` / `identity_trust_assessment` / `task_risk_decision`，stdout 单对象 |
| 契约版本 | `1.0.0-proposed`（**未改**；新增内容都在 `extensions` 内） |
| 诊断 | 只写 stderr；stdout 出现多余内容由适配层拒绝（`ADAPTER_MODULE_STDOUT_INVALID`） |

| 模块 | 退出码 | 含义 |
| --- | --- | --- |
| M1 | 0 / 2 / 3 / 4 | 正常产出（状态可能是阻断态）/ 输入非法 / 模型缺失 / 无法形成映射 |
| M2 | 0 / 2 | 正常产出 / 输入非法 |
| M3 | 0 / 2 / 4 | 正常产出 / 输入或配置非法 / 内部异常无法构造输出 |

适配层对一切非零退出统一记为 `ADAPTER_MODULE_EXIT_NONZERO` 并阻断；
`UNKNOWN`/`ERROR` **状态** 则记为 `ADAPTER_MODULE_STATUS_NOT_PROCEED`。

---

## 4. 证据来源与可信性（B1 必须原样转述）

| 模块 | 证据种类 | 离线 / 受控 / 实时 | 是否可被业务 JSON 伪造 |
| --- | --- | --- | --- |
| M1 | 离线数值模型的推理结果 + 观察窗口/请求计数 | 离线训练；观察块目前只能由受控 fixture 构造 | 自报 `kind` **不能**换来 NORMAL（需受信任配置声明）；特征值与模型 SHA 不可伪造 |
| M2 | 历史受控实验（S2/S3/S3C/S4）+ 本地 SROS2 权限文件 + 原生 Fast DDS 拒绝日志 | 受控实验归档（只读） | 历史证据不可伪造；**但历史证据不能证明当前请求** |
| M3 | 权威 TaskPolicy + 命中规则 + 可选可信审计日志 | 规则引擎（确定性） | 策略路径只能来自受信任配置 |

**明确否认**（任何报告都不得写成能力）：

* M1 不是在线 IDS，没有实时通信特征采集，没有攻击类型识别；
* M2 的 `AUTHORIZED` 不是身份认证，也不是当前请求的授权；
* M3 的 `ALLOW_RECOMMENDED` 不是 Gateway 准入；
* 三者的任何状态都不能替代 DDS-Security 的通信权限控制。

---

## 5. 本轮对系统侧（F0 / 验收器）的改动 —— B1 必须知道

1. **`scripts/team_demo.py`**：身份位置新增硬性要求
   `extensions.current_request_identity.status == "AUTHENTICATED"` 且
   `historical_only != true`，否则 `ADAPTER_CURRENT_IDENTITY_UNBOUND`。
   Mock/替身必须显式给出该字段（`MOCK_FIXTURE`）。
2. **调用顺序与短路**：F0 会**先调用全部三个模块**再统一判定推进条件；
   只有进程/协议级故障（超时、非零退出、Schema 非法）才立即中断。
   因此一次 F0 调用即可拿到三份真实证据。
3. **`scripts/check_member_module.py`**：
   * 基础信封现在附带一份**真实**通信观测块（来自已提交的 held-out 真实行），
     否则真实 M1 会（正确地）以退出码 4 失败，导致协议层检查失去意义；
   * 真实 fixture 支持 `expect.adapter_decision` / `expect.adapter_reason`；
   * `reason_code` 会读取 `extensions.member1_comm`；
   * 对真实模块，`STATE-*` mock 矩阵标记为 `NOT_APPLICABLE_REAL_MODULE` 且不入门槛。
4. **运行时状态**：`--identity-ledger` 会持久化。**重复使用同一 `request_id` 的
   第二次联合运行会被正确判为"历史授权复用" → UNKNOWN**。可重复验收时要么
   每次清理账本，要么每次使用新的 `request_id`。
5. **解释器**：交付配置里是裸 `python3`。若其 `jsonschema<4.0`，三个模块都会
   失败关闭（非零退出）。B1 必须固定解释器。
6. **公共 Schema 未改动**，契约版本仍为 `1.0.0-proposed`。语义新增记在
   `docs/interfaces/CONTRACT_VERSION.md` 的"规则九"。

---

## 6. 测试与结果

```bash
PY=tests/evidence/research-venv/bin/python        # 或任何装了 jsonschema>=4 的解释器

# 全仓单元测试
$PY -m pytest tests/unit -q

# 成员一
$PY -m pytest modules/member1_comm/test_module.py modules/member1_comm/test_integration.py -q
$PY -m pytest tests/unit/test_member1_comm_real.py tests/unit/test_member1_adapter_integration.py \
              tests/unit/test_member1_real_acceptance.py -q
$PY scripts/check_member_module.py --module comm_risk \
    --config config/team_modules.member1.real.yaml \
    --real-fixture config/acceptance/real_scenarios.member1.yaml \
    --out-dir /tmp/m1 --run-id m1-real

# 成员二
$PY -m pytest tests/unit/test_identity_trust_assessor.py tests/unit/test_identity_trust_real_logs.py \
              tests/unit/test_identity_current_binding.py -q
$PY scripts/check_member_module.py --module identity_trust \
    --config config/team_modules.member2.real.yaml \
    --real-fixture config/acceptance/real_scenarios.member2.yaml \
    --out-dir /tmp/m2 --run-id m2-real

# 成员三（含 RC2 回归）
$PY -m pytest tests/unit/test_member3_taskrisk.py tests/unit/test_member3_real_acceptance.py -q
$PY scripts/check_member_module.py --module task_risk \
    --config config/team_modules.member3.real.yaml \
    --real-fixture config/acceptance/real_scenarios.member3.yaml \
    --out-dir /tmp/m3 --run-id m3-real

# 三模块联合（关联 / 隔离 / 交付配置）
$PY -m pytest tests/unit/test_joint_three_modules.py -q
```

结果见 `docs/integration/WORK_A_MODULE_ADAPTATION_REPORT.md` 第 6 节（含每条命令的真实输出摘要）。

**本地依赖**：`tests/unit/test_identity_trust_real_logs.py` 与联合测试需要
`security/keystore`（SROS2 密钥材料，已 `.gitignore` 排除）。缺失时相关测试会
**skip 并说明原因**，而不是静默通过。

---

## 7. 就绪状态总表（唯一权威版本，第二阶段复核后）

| 模块 | CALLABLE_REAL | SCHEMA_VALID | EVIDENCE_VALID | ONLINE_PROCEED_READY |
| --- | --- | --- | --- | --- |
| M1 `comm_risk` | PASS | PASS | PASS※ | **FAIL** |
| M2 `identity_trust` | PASS | PASS | PASS※※ | **FAIL** |
| M3 `task_risk` | PASS | PASS | PASS | PASS |

※ M1 的 `EVIDENCE_VALID` 仅覆盖"真实 Linux `/proc` 子集（24 维，窗口级、主机级）
+ 离线模型"这一范围；不覆盖 22 维逐包特征与 2 维 ROS 图特征（不可得），
也不覆盖任何"在线检测"声明。

※※ M2 的 `EVIDENCE_VALID` 仅覆盖"历史受控实验证据 + 签名/绑定/新鲜度/防重放核验"
这一范围；**不**覆盖"当前请求的 DDS 身份认证"——该能力不存在，见 §10.3。

证据见 `.yaml` 中 `modules.<name>.readiness_evidence`。四项取值只能取
PASS / FAIL / NOT_RUN / BLOCKED；本表中没有任何一项是"大概通过"。

---

## 8. 未完成项与阻断条件（必须原样带入 B1 的计划）

| 编号 | 未完成项 | 影响 | 需要什么才能解除 |
| --- | --- | --- | --- |
| A-1 | M1 实时通信特征采集缺失 | 无法做在线检测 | 在 Jazzy 上实现 49 维特征的等价采集（tshark/pcap + `/proc`），并证明与训练分布可比 |
| A-2 | M1 模型门槛未通过 | 生产语义下无法给 NORMAL | 重新设计特征/算法并在**独立采集会话**上复现；不得用测试集调参 |
| A-3 | M2 可信当前身份绑定缺失 | 当前身份恒 UNKNOWN，联合运行必阻断 | 需要可信证据产生组件（中间件层身份绑定或签名见证）；本仓库只交付了契约与核验器 |
| A-4 | 三模块联合"全绿"不可达 | 系统级联调只能到 ADAPTER_BLOCK | 依赖 A-1/A-2/A-3；在此之前任何"全链路放行"只能来自受控测试配置 |
| A-5 | M1 训练数据不入库 | 新环境需自行下载 14 GB 归档 | 已提供下载工具与尺寸/MD5 校验；模型本体已入库并有 SHA-256 |
| A-6 | SROS2 keystore 不入库 | M2 部分测试在干净环境会 skip | 由 `scripts/setup_sros2.sh` 在目标环境生成 |
| A-7 | M3 交付内 `experiments.py`/`online_check.py` 未纳入 | 无 | 若需要离线实验入口，另行评审后合入 |

---

## 9. 给 B1 的最小合入清单

1. 取分支 `integration/member-module-adaptation` 上**已提交**的 SHA（见报告第 9 节）；
2. 不要依赖工作树中未提交的修改（本工作结束时工作树应为干净）；
3. 若需要联合运行，直接复用 `config/team_modules.all-real.yaml`；
4. 若需要 `READY` 证据，只能在受控测试配置下取得，并在报告中显式标注；
5. 任何接口变更请先改本目录下的两个交接文件，再改代码。

---

## 10. 第二阶段更新（真实模块可信化）

### 10.1 本轮基准与提交

| 项 | 值 |
| --- | --- |
| 上一轮基准 | `f51bab800d7bb3fe325d7e096bb15438178f5122` |
| 本轮功能提交 | `c6f6755e3c5b21febf23d3f8a0f5ce57e5957715` |
| 分支 | `integration/member-module-adaptation`（已推送，见 §10.9） |
| 证据包 | `docs/integration/evidence/PHASE2_EVIDENCE.json` |
| 专题文档 | `WORK_A_PHASE2_SECURITY_REVIEW.md`、`M1_RUNTIME_FEATURE_FEASIBILITY.md`、`M2_CURRENT_IDENTITY_TRUST_BOUNDARY.md` |

### 10.2 接口变更（仅 `extensions` 与受信任参数，Schema 未改）

| 变更 | 类型 | 兼容性 |
| --- | --- | --- |
| `extensions.current_request_identity` 增加 `checks`/`verifier`/`attestation` | 兼容扩展（§4.1） | 旧消费方忽略即可；新消费方应用 `f0_accepts()` |
| 证据契约 `current-identity-witness/1` → `current-identity-attestation/2` | **测试件内部**契约 | 旧证据不再被接受（无生产签发者，无影响） |
| 新增受信任参数 `--identity-issuers` | 进程参数 | 未配置时永不 AUTHENTICATED |
| `--identity-ledger` 由可选变为 AUTHENTICATED 必要条件 | 语义收紧 | 旧配置若不配账本，只会更严格（继续阻断） |
| 新增 `identity_trust/test_issuer.py` | TEST_ONLY 工具 | 只能产出 `AUTHENTICATED_TEST_ONLY` |
| 新增 M1 采集器与 24 维子集模型 | 新增能力 | 不改 49 维命令的语义 |

### 10.3 信任边界（必须原样转述）

* **HMAC 有效 ≠ 身份已认证。** 签名只证明字节完整性；身份可信只来自受信任签发者
  清单，而仓库不交付该清单、也不存在能签发它的组件。
* 因此 M2 的真实输出恒为 `UNKNOWN`（或 `DENIED`）；测试签发器最多给出
  `AUTHENTICATED_TEST_ONLY`。
* `ONLINE_PROCEED_READY` 保持 **FAIL**。测试签发器不能把它改成 PASS。

### 10.4 模块执行命令（第二阶段）

```bash
PY=tests/evidence/research-venv/bin/python

# M1 真实观测（REAL_RUNTIME）：产出 /tmp/m1_snapshot.json 与可合并的观测块
$PY -m modules.member1_comm.collector.emit_observation \
    --duration 1.0 --interval 0.25 \
    --out /tmp/m1_snapshot.json --observation-out /tmp/m1_observation.json
#   不给 --request-count 时 mapping=BLOCKED_MISSING_REQUEST_COUNT
#   （M1 随后以退出码 4 失败关闭）。给 --request-count 时该数字会被标注为
#   OPERATOR_DECLARED_CONTROLLED_TEST。

# M1 24 维子集模型（离线训练，门槛 FAIL）
$PY modules/member1_comm/module.py \
    --model modules/member1_comm/model/comm_risk_model_runtime_subset.json \
    --model-sha256 9de89b7a96928c5fc1b5f1d0a24870d3ac9e091e179ea2988454e820097ce588 \
    --features modules/member1_comm/features_runtime_subset.json \
    --observation-provenance RUNTIME_LOG < envelope.json

# M2（生产语义：无签发者清单 -> 恒 UNKNOWN）
$PY identity_trust/assessor.py \
    --experiment-run 20261009T093144Z \
    --evidence-root artifacts/acceptance/exports/m2_sros2_enforce/logs/tests_evidence \
    --policy security/policies/minimal_permissions.xml --keystore security/keystore \
    --case S2 --identity-ledger logs/m2/ledger.jsonl < envelope.json
#   受控测试时再加 --identity-issuers <TEST_ONLY 清单> 与受控测试签发器产出的证据
```

### 10.5 测试结果

```text
tests/unit/test_identity_current_binding.py            27 passed
tests/unit/test_phase2_security_boundaries.py           9 passed, 2 xfailed   ← 2 项是已知 F0 缺口反例
tests/unit/test_member1_runtime_observation.py          7 passed
全仓：734 passed, 3 skipped, 2 xfailed in 532.64s (0:08:52)
```

### 10.6 B1 必须做的事（P0-2）

F0 目前只比较 `extensions.current_request_identity.status` 字符串。实测：一个只写
`"status": "AUTHENTICATED"` 的模块即可让适配层给出
`READY_FOR_GATEWAY_SUBMISSION / ADAPTER_OK`。

要求的改法（一行）：

```python
from identity_trust.current_identity import f0_accepts
current = (outputs['identity_trust'].get('extensions') or {}).get('current_request_identity')
if not f0_accepts(current):
    raise AdapterBlock(REASON_CURRENT_IDENTITY_UNBOUND, '当前身份未通过受信任核验')
```

反例（当前 `xfail`，修好后改普通断言）：

* `tests/unit/test_phase2_security_boundaries.py::test_f0_rejects_bare_status_self_report`
* `tests/unit/test_phase2_security_boundaries.py::test_f0_rejects_mock_fixture_identity`

### 10.7 未完成的在线条件

| 编号 | 条件 | 当前 |
| --- | --- | --- |
| A-1 | ROS 2 运行时（Jazzy） | 缺失（本机无 `/opt/ros`、无 `ros2`） |
| A-2 | 业务请求计数 | 缺失（需 ROS 2 Action 计数；不得用包数/采样数代替） |
| A-3 | 22 维逐包 + 2 维图特征 | 缺失（需 tshark / ROS 图内省） |
| A-4 | 模型验证门槛 | 两个模型均 FAIL |
| A-5 | 特征语义等价性 | UNVERIFIED |
| A-6 | 真实身份签发者 | 不存在 |
| A-7 | F0 身份判定 | 仍信任裸状态（owner B1） |
| A-8 | 密钥/核验器隔离 | 同 uid，无强隔离 |

### 10.8 是否可供 B1 合流

**模块与证据侧：可以合流。** 结论：`MERGEABLE_WITH_B1_FOLLOWUP`——
前提是 P0-2（`f0_accepts`）在 B1 侧同期或随后落地；否则 `identity` 自报仍可绕过。
合入前请先跑两个 `xfail` 用例确认 F0 现状，再决定是否把它们翻正。

### 10.9 复验与推送

```bash
cd /home/zhangwei/project/RosSystem/.worktrees/work-a
git log --oneline -3
git status --short          # 应为空
git rev-parse HEAD
git rev-parse origin/integration/member-module-adaptation   # 应一致
```
