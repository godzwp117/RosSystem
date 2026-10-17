# 工作 A 报告：三成员真实模块适配、兼容性修复与必要重构

| 项 | 值 |
| --- | --- |
| 工作包 | **A**（成员真实模块适配 / 兼容性修复 / 必要重构） |
| 目标分支 | `integration/member-module-adaptation` |
| 开发基准 | `demo-2026-10-19-rc2-verified` = `33cb4f93d5e5fd268878fe83fc040c655d632a70` |
| 工作树 | 以基准标签新建的**独立 git worktree**（见第 9.1 节的路径说明） |
| 成员源码 | `/home/zhangwei/project/RosSystem/user`（**只读来源**，从未作为仓库根） |
| 交接文件 | `docs/integration/MEMBER_MODULE_HANDOFF.md`、`docs/integration/member_module_handoff.yaml` |
| 结论 | M1/M2 真实模块已可被 F0 真实调用且证据可追溯，但**都不得推进**；M3 通过；无伪造 |

---

## 0. 先给结论（逐模块四项就绪状态）

| 模块 | CALLABLE_REAL | SCHEMA_VALID | EVIDENCE_VALID | ONLINE_PROCEED_READY |
| --- | --- | --- | --- | --- |
| M1 `comm_risk` | **PASS** | **PASS** | **PASS** | **FAIL** |
| M2 `identity_trust` | **PASS** | **PASS** | **PASS** | **FAIL** |
| M3 `task_risk` | **PASS** | **PASS** | **PASS** | **PASS** |

每项的判定依据见 `docs/integration/member_module_handoff.yaml` 的
`modules.<name>.readiness_evidence`，以及本报告第 6 节的测试结果。

**三项必须被原样理解的边界（不得在任何汇报中被压缩成"通过"）：**

1. M1 的四项中三项 PASS 只证明"模型真实推理链路可用、输出合规、证据可追溯"，
   **不**证明检测有效：交付模型 `validation_gate_passed=false`，
   测试集 F1 0.1312 低于恒预测攻击基线 0.8132。
2. M2 的 `EVIDENCE_VALID` 指"历史证据被完整、可追溯地解释"，
   **不**指"当前请求已通过 DDS 身份认证"——恰恰相反，当前身份恒为 UNKNOWN。
3. M3 的 `ONLINE_PROCEED_READY=PASS` 指"真实规则引擎可在真实条件下给出
   ALLOW_RECOMMENDED"，`ALLOW_RECOMMENDED` 仍然**不是** Gateway 准入。

因此三模块联合运行的正确结果是 `ADAPTER_BLOCK`。能到
`READY_FOR_GATEWAY_SUBMISSION` 的只有受控测试配置。

---

## 1. 成员交付代码清单

调查起点（真实执行结果，非假设）：

```text
user/COLCON_IGNORE                                   ← 防止 user/ 被 colcon 当作包
user/RosSystem-member1-delivery/{REVISION.txt, RosSystem-member1-changes.patch, RosSystem/}
user/RosSystem_Member2_DDS_Identity_Delivery/{identity_trust, config, docs, scripts, tests}
user/RosSystem_member3_taskrisk_source_v0.1.0/RosSystem_member3_taskrisk_source_v0.1.0/{MANIFEST.json, ...}
```

* `user/` **不是** git 子模块、无嵌套 `.git`、无符号链接；它被
  `.git/info/exclude` 中的 `user/` 规则排除，因此 `git ls-files -- user` 为空。
* 因此新建 worktree **不会**带上 `user/`；本次是**逐文件选择性读取**，不是整体复制。
* 未复制任何模型缓存、数据集、私钥、旧构建产物或嵌套 Git 元数据。

### 1.1 成员一

交付形态：**整个 RosSystem 的旧快照**（`baseline_sha=a4c5971`）加上他自己的
`modules/my_comm`。`REVISION.txt` 自述：`contract_status=PROPOSED_V1`、
`model_performance_gate=FAIL`、`L3_effective_detector=NOT_READY`、
`RUNTIME_MONITOR=NOT_READY`。

实际成员代码：`modules/my_comm/{module,data,train,metrics}.py`、
`features.json`、`test_module.py`、`test_integration.py`、`run_*_protocol.py`、
`download_data.py`、`write_config.py`、`README.md`、`requirements.txt`。
逐文件处置见第 2 节与交接文件 §1.1。

### 1.2 成员二

交付形态：`identity_trust/assessor.py` + 一份 example 配置 + 一份 adapter 检查脚本
+ 单元测试 + 实现说明。**该 assessor 是旧版本**：主线版本已包含 ANSI 规范化、
原生 Fast DDS 拒绝的行内匹配、非 DDS 结果排除、历史资源错配等修复。

### 1.3 成员三

交付形态：`MANIFEST.json` 声明 `packaging_change_only=true`，`modules/member3_taskrisk`
与 `tests/unit/test_member3_taskrisk.py`、`config/team_modules.member3.yaml` 与主线
**SHA-256 完全一致**。M3 已经完成真实在线联调（RC2 ON-01..ON-06），本次不做重写。

---

## 2. 与完整系统的差异与冲突（逐文件处置）

处置：`REUSE` / `ADAPT` / `REFACTOR` / `REJECT` / `DEFER`。
完整表格见 `docs/integration/MEMBER_MODULE_HANDOFF.md` §1；此处只列**冲突**与**决策要点**。

### 2.1 发现的三类真实冲突

| 编号 | 冲突 | 事实 | 处置 |
| --- | --- | --- | --- |
| C-1 | 成员一交付包 = 旧系统快照 | `scripts/team_demo.py`、`docs/interfaces/schemas/*`、`config/task_policy.yaml`、`tests/unit/*` 都是**旧版本** | **REJECT**：不整体覆盖；只吸收 `modules/my_comm`。主线这些文件更新，覆盖会回退已验证修复 |
| C-2 | 成员二交付的 assessor 落后于主线 | 主线已修复 ANSI 控制序列插入 `SECURITY Error` 内部、原生拒绝行内匹配、超时≠DDS 拒绝 | **REJECT 该版本**，在主线超集上做 REFACTOR；交付版本的修复一个都不回退 |
| C-3 | 三个"旧接口"假设与现系统不符 | (a) 成员一默认模型只能放 `training_runs/`（已 gitignore）；(b) 成员一/二的观察来源可信性取自业务 JSON 自报字段；(c) 历史 `AUTHORIZED` 被适配层当成推进条件 | 全部 **REFACTOR**：模型放 `modules/member1_comm/model/` 并入库；来源可信性改由受信任配置声明；适配层新增当前身份绑定要求 |

### 2.2 语义冲突（最重要的一项）

`identity_trust` 的顶层 `status` 表达"依据所列证据的授权判断"，其证据来自
**历史受控实验**。原适配层的推进条件是 `status == AUTHORIZED`，于是：

> 一次 2026-10-09 的历史实验成功 → 一条 2026-10-17 的全新候选请求被放行。

这不是实现 bug，而是**语义越界**：历史证据只覆盖它当时那次运行中的主体与资源。
处置见第 3.2 节。**没有**通过放宽 Schema 或修改 `status` 含义来解决
（那会违反 `docs/interfaces/CONTRACT_VERSION.md` §4.2）。

---

## 3. 实际完成的模块适配或重构

### 3.1 M1 通信风险（`modules/member1_comm`）

代码迁移：`modules/my_comm` → `modules/member1_comm`（算法、训练流程、失败关闭设计未改写）。

| 改动 | 为什么 | 可验证结果 |
| --- | --- | --- |
| 模型根目录白名单（`training_runs/` + `modules/member1_comm/model/`） | 原实现只允许 `training_runs/`，而该目录被 `.gitignore` 排除 → 交付模型无法入库、无法追溯 | 模型（1.3 MB）随仓库交付并有 SHA-256；任意路径仍被拒绝 |
| 新增 `--features` 特征清单校验 | 防止"模型 feature_names 与清单漂移"造成静默错配 | 清单不一致 → `ERROR / MODEL_FEATURE_LIST_MISMATCH` |
| NORMAL 增加**受信任来源**条件 | 原实现用 `observations[].kind`（业务输入自报）判断"来源可信"；若门槛通过，一条自报 `RUNTIME_LOG` 就能换来 NORMAL | NORMAL 需同时满足：门槛通过 + 受信任配置 `--observation-provenance` 声明 + 信封自报一致；三者缺一即 UNKNOWN |
| `extensions.my_comm` → `extensions.member1_comm`，新增 `reason_code`/`trusted_provenance`/`envelope_provenance` | 可追溯性与机器可读原因 | 验收器与单测按 `reason_code` 断言 |
| 新增 `export_probe_rows.py` + 真实 held-out fixture | 四状态可达性必须用**真实数据行**证明，不能用随机数或标签反推 | 3 条真实行（分片号/原始 CSV 行号/标签/打分可追溯） |

模型重训（用成员交付的训练代码 + 官方归档）：

* 归档：`ROSPaCe_reduced.tar.gz`，尺寸 + MD5 校验通过（`SIZE_MD5_PASS`），
  审计 30,247,050 行，每分片均匀蓄水池抽样 10,000 行（共 150,000），
  按文件不相交划分 train 0–10 / validation 11–12 / test 13–14。
* 结果：ExtraTrees（48 棵，深度 ≤12），阈值 0.75，**门槛 FAIL**；
  测试集 F1 **0.1312**、Recall **0.0702**、Specificity **1.0**、
  PR-AUC 0.7424；恒预测攻击基线 F1 **0.8132**。
* 数值一致性：部署的纯 Python 推理与 sklearn 在 20,000 条 held-out 行上
  最大概率误差 3.3e-16，分类不一致 0（`PASS`）。
* **没有**用测试集调参、没有用标签反推、没有随机补值、没有固定 NORMAL。
  `validation_gate_passed=false` 被原样保留在模型与清单里。

### 3.2 M2 身份与权限（`identity_trust`）

保留（REUSE，来自主线超集，全部不得回退）：
SROS 2 权限文件核对、Fast DDS 原生拒绝日志解释、S3/S4 原生拒绝、S3C 正向对照、
历史资源匹配、ANSI 规范化、非 DDS 结果（超时/业务阻断）不得冒充 DDS 拒绝、
`IdentityTrustAssessment` 输出。

重构（REFACTOR）：

1. **历史证据与当前身份分离**：新增 `extensions.current_request_identity`
   （`status`/`evidence_kind`/`binding`/`reason`/`historical_only`），
   顶层 `status` 语义**不变**。
2. **当前身份绑定核验器**（新文件 `identity_trust/current_identity.py`）：
   * 定义可信证据契约（`contract_description()`）；
   * HMAC-SHA256 签名核验（密钥路径只能来自受信任配置）；
   * 请求绑定校验：`request_id` / `resource` / `operation`；
   * 新鲜度窗口（`MAX_REMOTE_AGE_SEC=30s`）与时钟偏差（`5s`）；
   * nonce 重放检测；
   * **没有证据时恒为 UNKNOWN**，并给出缺失原因与所需能力。
3. **历史授权复用检测**：`--identity-ledger` 记录
   $(case, experiment_run, request id, resource)$，第二次解释同一组合 →
   `HISTORICAL_AUTHORIZATION_REUSE` → UNKNOWN。
4. **适配层硬性要求**：身份位置必须 `current_request_identity.status == AUTHENTICATED`
   且 `historical_only != true`，否则 `ADAPTER_CURRENT_IDENTITY_UNBOUND`。

**能力边界的诚实结论**：ROS 2 Jazzy / rclpy **没有**公开稳定的 API 让订阅端取得
"该样本发布者已完成 DDS-Security 认证的身份"；DDS-Security 的认证发生在参与者
建链阶段，不随消息传递，Fast DDS 的 `DataReaderListener` 也不携带身份且未经 rclpy
暴露。因此：

* 不虚构中间件 API；不从 `request_id` 推断身份；不把自报 enclave 当认证；
* "可信证据产生组件"**未实现**，列为未完成条件 A-3；
* 本次交付的是**契约 + 核验器 + 失败关闭默认路径**，不是"已能认证当前请求"。

### 3.3 M3 任务风险（`modules/member3_taskrisk`）

* 核心规则引擎：**REUSE**（`module.py`/`risk_model.py` 与交付 SHA-256 一致，未重写）。
* 交付内的 `experiments.py`/`online_check.py`/`test_module.py`：**DEFER**（非联合运行必需）。
* 本次为 M3 新增的是**回归与联合证据**（第 6.4 节）：四状态真实运行、超时与异常路径、
  `request_id`/`run_id`/`event_id` 关联、与 M1/M2 同调用时的进程与资源隔离。
* `ALLOW_RECOMMENDED` 未被接入任何 Gateway 准入路径；权威策略
  `config/task_policy.yaml` 与 `security/policies/minimal_permissions.xml` **未被修改或放宽**。

### 3.4 系统侧（F0 / 验收器）的配套改动

| 文件 | 改动 | 为什么 |
| --- | --- | --- |
| `scripts/team_demo.py` | 新增 `REQUIRED_CURRENT_IDENTITY`、`REASON_CURRENT_IDENTITY_UNBOUND`；身份位置增加当前身份绑定校验 | 让"历史授权不得冒充当前身份"成为**适配层规则**，而不是文档约定 |
| `scripts/check_member_module.py` | 基础信封注入真实通信观测块；真实 fixture 支持 `expect.adapter_decision/adapter_reason`；`reason_code` 读取 `extensions.member1_comm`；正向对照替身补 `current_request_identity(MOCK_FIXTURE)` | 原验收器只构造 `f0_mock` 场景开关，真实 M1 会（正确地）退出 4，协议层检查失去意义 |
| `docs/interfaces/CONTRACT_VERSION.md` | 新增"规则九：当前请求身份绑定"；`extensions.current_request_identity` 字段定义；版本记录一行 | 语义变更必须留痕；且必须说明这是 §4.1 允许的**兼容扩展**，不是静默改字段含义 |

**公共 Schema 未改动**，`schema_version` 仍为 `1.0.0-proposed`。

---

## 4. 三模块真实运行命令

工作目录：仓库根目录。`PY` 必须是装有 `jsonschema>=4.0` 的解释器
（本报告使用 `tests/evidence/research-venv/bin/python`，3.10.12）。

```bash
# M1（生产语义：低于阈值只能 UNKNOWN）
$PY modules/member1_comm/module.py \
    --model modules/member1_comm/model/comm_risk_model.json \
    --model-sha256 d45d272eea9dfef67b2b0066af0fd078270d559a4a4e350b7558d072c21c40df \
    --features modules/member1_comm/features.json --observation-provenance UNKNOWN \
    < envelope.json

# M2（历史证据 + 当前身份核验；默认 UNKNOWN）
$PY identity_trust/assessor.py \
    --experiment-run 20261009T093144Z \
    --evidence-root artifacts/acceptance/exports/m2_sros2_enforce/logs/tests_evidence \
    --policy security/policies/minimal_permissions.xml --keystore security/keystore \
    --case S2 --identity-ledger logs/all-real/identity_ledger.jsonl < envelope.json

# M3（权威策略只读）
$PY modules/member3_taskrisk/module.py --policy config/task_policy.yaml < envelope.json
```

经 F0（唯一正确的准入前置路径）：

```bash
$PY scripts/team_demo.py --input envelope.json --config config/team_modules.member1.real.yaml
$PY scripts/team_demo.py --input envelope.json --config config/team_modules.member2.real.yaml
$PY scripts/team_demo.py --input envelope.json --config config/team_modules.member3.real.yaml
$PY scripts/team_demo.py --input envelope.json --config config/team_modules.all-real.yaml
```

`config/team_modules.all-real.yaml` 的真实结果是 `ADAPTER_BLOCK`
（`ADAPTER_MODULE_STATUS_NOT_PROCEED`，comm_risk=UNKNOWN），
且**三个模块都已被真实调用**（F0 先调用全部再判定）。

---

## 5. 配置与依赖

| 文件 | 作用 | 关键点 |
| --- | --- | --- |
| `config/team_modules.member1.real.yaml` | M1 真实化，M2/M3 保持 Mock | 5 个命令档案：`model_valid`/`model_controlled_test`/`model_trusted_provenance`/`model_absent`/`model_bad_hash` |
| `config/team_modules.member2.real.yaml` | M2 真实化 | 未改语义；账本默认不启用（保证验收可重复） |
| `config/team_modules.member3.real.yaml` | M3 真实化 | 4 个策略档案（合法/紧区域/缺失/损坏） |
| `config/team_modules.all-real.yaml` | 三模块全真实 | 结果应为 ADAPTER_BLOCK；M2 启用 `--identity-ledger` |
| `config/team_modules.all-real.controlled-test.yaml` | 受控测试 | M1 加 `--controlled-test`；**仍会阻断**（M2 当前身份 UNKNOWN） |
| `config/acceptance/real_scenarios.member1.yaml` | M1 真实验收 fixture | 5 个场景，全部由真实 held-out 行或真实坏模型触发 |
| `config/acceptance/real_scenarios.member2.yaml` | M2 fixture（已更新） | S2 增加 `adapter_decision: ADAPTER_BLOCK` |

依赖：

| 模块 | 运行时依赖 | ROS 2 依赖 |
| --- | --- | --- |
| M1 | `jsonschema>=4.20`、`PyYAML`（训练/导出另需 numpy、scikit-learn） | 无 |
| M2 | Python 标准库 | 无 |
| M3 | `jsonschema>=4.0`、`PyYAML` | 无 |

**解释器陷阱（必须传给 B1）**：交付配置里是裸 `python3`。若其 `jsonschema<4.0`，
三个模块都会**失败关闭**（非零退出或 ERROR），适配层记为
`ADAPTER_MODULE_EXIT_NONZERO`。本机 `/usr/bin/python3` 正是 `jsonschema 3.2.0`，
因此报告中的所有命令都显式使用带依赖的解释器。

---

## 6. 测试结果

### 6.1 全仓单元测试

```bash
$PY -m pytest tests/unit -q
```

```text
704 passed, 3 skipped in 520.75s (0:08:40)
```

对照基线（同一解释器、同一环境）：RC2 记录为 **657 passed / 3 skipped**。
本次新增 **47** 个测试函数（M1 21 + M1×F0 6 + M1 验收 2 + M2 当前身份 13 +
联合运行 5），全部通过；**没有删除或跳过任何既有测试**，也没有把失败项改成
"非强制"来换取绿色（`STATE-*` 的 `mandatory=False` 是 RC2 既有设计，
本工作只是把它的适用性标注为 `NOT_APPLICABLE_REAL_MODULE`）。

### 6.2 成员一

```text
modules/member1_comm/test_module.py + test_integration.py   44 passed
tests/unit/test_member1_comm_real.py                        21 passed
tests/unit/test_member1_adapter_integration.py               6 passed
tests/unit/test_member1_real_acceptance.py                   2 passed
check_member_module --module comm_risk
  → meets_pr_gate=True, PASS=60 FAIL=3 NOT_RUN=1 BLOCKED=1
    algorithm_evidence=NOT_READY, runtime_integration=BLOCKED
```

覆盖到的失败关闭路径：非法 JSON / 重复键 / NaN 字面量（退出码 2）；
模型缺失（3）；模型路径越出白名单、SHA-256 不符、特征清单不符（ERROR）；
特征向量缺失/截断（UNKNOWN）；观测不在窗口内、缺 `f0_runtime` 映射（4）；
观测过期（UNKNOWN）；**业务 JSON 自报 `kind=RUNTIME_LOG` 不能换来 NORMAL**；
`--controlled-test` 是唯一能让未过门槛模型给出 NORMAL 的路径（且输出写明
`CONTROLLED_TEST_ONLY`）。

### 6.3 成员二

```text
tests/unit/test_identity_trust_assessor.py
+ tests/unit/test_identity_trust_real_logs.py               56 passed
tests/unit/test_identity_current_binding.py                 13 passed
check_member_module --module identity_trust
  → meets_pr_gate=True, PASS=58 FAIL=3 NOT_RUN=1 BLOCKED=1
    全部 REAL-ADP-* 决策均为 ADAPTER_BLOCK
```

覆盖：历史 `AUTHORIZED` 不等于当前身份；自报 enclave/身份不能被提升；
签名证据可认证（测试密钥）；签名篡改、串单、跨资源复用、过期、nonce 重放
全部拒绝；未认证主体 → DENIED；历史授权复用 → UNKNOWN；
顶层 `AUTHORIZED` + 当前身份 UNKNOWN → 适配层 `ADAPTER_CURRENT_IDENTITY_UNBOUND`。

### 6.4 成员三 + 联合运行

```text
tests/unit/test_member3_taskrisk.py                          （既有，REUSE）
tests/unit/test_member3_real_acceptance.py                   （既有，四状态真实运行）
tests/unit/test_joint_three_modules.py                       5 passed
check_member_module --module task_risk
  → meets_pr_gate=True, PASS=58 FAIL=3 NOT_RUN=1 BLOCKED=1
```

联合运行验证点：三模块各自独立 PID/PGID；三个 `event_id` 互不相同；
`request_id`/`run_id` 一致且通过 F0 的一致性检查；单模块超时只终止该次调用的
进程组，后续模块不受影响；交付的 `all-real.yaml` 可被 F0 直接加载并给出
三份 schema 合法的输出 + `ADAPTER_BLOCK`。

### 6.5 CI 等价检查（本地复现）

```text
validate_team_contracts.py --all --quiet   PASS
check_schema_coverage.py                   PASS（4 Schema / 10 合法样例 / 13 非法样例）
Python 语法（ast.parse）                    PASS
模板与工具自测                              PASS
敏感材料/大文件/凭据扫描（第 9.3 节）         PASS
```

---

## 7. 模型、身份及任务证据来源

| 模块 | 证据 | 来源 | 可追溯性 | 是否可被业务输入伪造 |
| --- | --- | --- | --- | --- |
| M1 | 模型推理结果 + 观察窗口 + 请求计数 | ROSPaCe 离线数据集训练出的数值模型（SHA-256 固定） | `model_manifest.json` + `train_report.json` + fixture 行号 | 特征值与模型 SHA 不可伪造；自报 `kind` 无法换来 NORMAL |
| M2 | 历史受控实验（S2/S3/S3C/S4）、SROS 2 权限文件、原生 Fast DDS 拒绝日志 | `artifacts/acceptance/exports/m2_sros2_enforce/logs/tests_evidence/20261009T093144Z`（只读归档） | 实验运行 ID、拒绝资源、`Permissions.cpp:<行号>`、正向对照 | 历史证据不可伪造；**但它不覆盖当前请求** |
| M3 | 权威 TaskPolicy + 命中规则 | `config/task_policy.yaml`（只读，未修改） | 策略版本 + `rule_basis` + `extensions.member3` | 策略路径只能来自受信任配置 |

离线 / 受控 / 实时划分：

* **离线**：M1 训练与评估（ROSPaCe CSV）；M3 的规则设计。
* **受控**：M1 的 L1 fixture（真实 held-out 行）；M2 的 S2/S3/S3C/S4 归档实验；
  M3 的四个策略档案。
* **实时**：**无**。当前没有任何模块消费实时 ROS 2 通信特征。

---

## 8. 安全边界验证

| 边界 | 验证方式 | 结果 |
| --- | --- | --- |
| M1 输出不是 DDS 身份证明 | `extensions.member1_comm.request_id_is_identity=False`；文档与输出同时声明 | 保持 |
| M2 历史实验不是当前认证 | 新增 `current_request_identity=UNKNOWN`；适配层硬性要求 AUTHENTICATED | **新增强制** |
| M3 `ALLOW_RECOMMENDED` 不是 Gateway 准入 | 适配层 READY 仍只是"可提交"；Gateway 独立判定；`gateway_decision=None` 在所有用例中断言 | 保持 |
| F0 READY 不是 Gateway ALLOW | 所有测试断言 `gateway_decision is None` 且 `navsim_goal_id is None` | 保持 |
| 无可信证据必须失败关闭 | 缺模型→3；坏模型→ERROR；缺特征→UNKNOWN；无身份证据→UNKNOWN；M2 真实路径全阻断 | 保持并加强 |
| 不得放宽权威策略 | `security/policies/minimal_permissions.xml` 与 `config/task_policy.yaml` **未修改** | 已核对 |
| 不得伪造证据 | 无随机补值、无标签反推、无固定 NORMAL、无测试集调参；门槛 FAIL 原样保留 | 已核对 |
| 命令只来自受信任配置 | fixture 的 `envelope_patch` 拒绝 command/exec/policy/env 等字段；模型/证据路径只能来自配置 | 保持 |
| 进程与资源隔离 | 每模块独立会话/进程组；超时只杀本组；stdout 有界读取 | 保持（新增联合测试） |
| Planner 绕过 Gateway | 未新增任何下游通道；联合探针只调用模块，不提交 Action | 已核对 |

---

## 9. 可供 B1 合入的提交 SHA

```text
4ab1f4535b38284725bd5480b2c93bc5f1ec547f
```

该提交包含本报告所述的全部代码、配置、fixture 与文档改动
（`git show --stat <sha>` 可复核）。记录 SHA 的这一行本身位于随后一条
**仅修改本文件**的提交中，因此上面给出的是**功能提交**的 SHA——它不会
因为记录动作而变化。

### 9.1 关于工作树的说明（与建议路径的差异）

任务建议工作树路径为 `/home/zhangwei/project/RosSystem-worktrees/work-a`。
本执行环境的文件沙箱只允许在会话工作区
（`/home/zhangwei/project/RosSystem`）内写入，该路径**不可创建**
（`mkdir: Permission denied`）。因此实际使用：

* 分支：`integration/member-module-adaptation`（从
  `demo-2026-10-19-rc2-verified` = `33cb4f9` 新建）
* 工作树：`/home/zhangwei/project/RosSystem/.worktrees/work-a`
  （独立 checkout；本地 `.git/info/exclude` 增加 `/.worktrees/`，
  **不修改任何被跟踪文件**，主工作树 `git status` 保持干净）

所有正式修改与提交都发生在该工作树内；主仓库工作区与 `user/` 未被改写。

### 9.2 复验方式

```bash
cd /home/zhangwei/project/RosSystem/.worktrees/work-a
git log --oneline -5
git status --short          # 应为空
git rev-parse HEAD
```

### 9.3 合并前的 CI 等价自检

```text
git ls-files 中无 data/、training_runs/、models/、*.joblib、*.tar.gz
无 *.pem/*.key/*.p12/... （security/keystore 与 security/enclaves 除外，且它们未入库）
无 >5 MB 的被跟踪文件（模型 1.3 MB）
无凭据特征串（AKIA… / gh[pousr]_… / BEGIN … PRIVATE KEY）
```

---

## 10. 未完成项

| 编号 | 未完成项 | 现状 | 影响 | 解除条件 |
| --- | --- | --- | --- | --- |
| A-1 | M1 实时通信特征采集 | 未实现 | 无法做在线检测 | 在 Jazzy 上实现 49 维等价采集并证明分布可比 |
| A-2 | M1 模型门槛 | FAIL（F1 0.1312 < 0.8132） | 生产语义下永远得不到 NORMAL | 重新设计特征/算法并在独立采集会话复现；不得用测试集调参 |
| A-3 | M2 可信当前身份绑定 | 只有契约 + 核验器；产生组件未实现 | 当前身份恒 UNKNOWN，联合运行必阻断 | 中间件层身份绑定或签名见证的真实产生组件 |
| A-4 | 三模块联合"全绿" | 不可达 | 系统级联调只能到 ADAPTER_BLOCK | 依赖 A-1/A-2/A-3 |
| A-5 | 训练数据不入库 | 14 GB 归档需自行下载 | 新环境重建需时间 | 已提供下载与尺寸/MD5 校验；模型本体已入库 |
| A-6 | SROS2 keystore 不入库 | 本地生成 | 干净环境下 M2 部分测试 skip | 由 `scripts/setup_sros2.sh` 在目标环境生成 |
| A-7 | M3 交付内 experiments/online_check | 未纳入 | 无 | 另行评审后合入 |
| A-8 | `--identity-ledger` 使联合验收不可重复 | 设计使然 | 同一 `request_id` 二次运行被判历史复用 | 每次清理账本或使用新 `request_id`（已写入交接 §5.4） |
| A-9 | 裸 `python3` 的解释器依赖 | 配置层面 | 解释器缺 jsonschema≥4 时三模块失败关闭 | B1 固定解释器 |
