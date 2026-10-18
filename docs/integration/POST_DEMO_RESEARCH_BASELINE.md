# 演示后 M1 / M2 专项研发共同基准

> 本文为 10 月 19 日演示之后、10 月 22 日最终成果准备期间，M1 与 M2 两个专项的
> **唯一共同代码基准**。两个专项都必须从这里的 SHA 创建分支，
> 不得再从工作 A / B1 的中间分支出发。

---

## 1. 冻结代码版本

| 项 | 值 |
| --- | --- |
| **`RESEARCH_BASE_SHA`** | **`be47ccd6c1b19460b65abc0ea8004706383d01d4`** |
| 分支 | `release/demo-2026-10-19-freeze` |
| 语义 | `DEMO_TESTED_CODE_SHA` —— 全部演示彩排与验收都在该 SHA、工作树干净的状态下执行 |
| 基线来源 | `fix/f0-trust-boundary-closeout` @ `50dd6d8`（含 P0 身份信任边界修复） |
| RC2 回退标签 | `demo-2026-10-19-rc2-verified` = `33cb4f9…`（**未移动，保持可回退**） |

### 1.1 继承链

```
baseline a4c5971
  └── chore/member-deliveries 3ce8202          （成员原始交付归档）
        └── fix/m2-m3-acceptance 19f6a25        （M2/M3 整改）
              └── integration/m3-online-evidence-20261016
                    └── integration/three-real-online e18598d   （工作 B1：三真实联合运行）
                          └── fix/f0-trust-boundary-closeout 50dd6d8  （P0 身份信任边界）
                                └── release/demo-2026-10-19-freeze be47ccd  ← 本基准
```

### 1.2 已包含的成果

| 成果 | 是否包含 | 证据 |
| --- | --- | --- |
| 工作 A：成员模块适配（M1 真实模型 + `/proc` 采集、M2 当前身份契约、F0 规则） | ✅ 已包含 | `git merge-base --is-ancestor acadbf7 be47ccd` |
| 工作 B1：三真实模块联合运行 + 在线回归 + 跨层复核 | ✅ 已包含 | `docs/integration/WORK_B1_THREE_REAL_ONLINE_REPORT.md` |
| P0：F0 身份信任边界修复（STRICT 默认） | ✅ 已包含 | `docs/integration/F0_TRUST_BOUNDARY_CLOSEOUT.md` |
| 演示发布入口与门禁 | ✅ 已包含 | `scripts/demo_20261019_release.sh` |

---

## 2. 三个模块的正式代码路径

| 模块 | 正式路径 | 入口命令 |
| --- | --- | --- |
| **M1 `comm_risk`** | `modules/member1_comm/` | `scripts/module_python.sh modules/member1_comm/module.py --model modules/member1_comm/model/comm_risk_model.json --model-sha256 <sha> --features modules/member1_comm/features.json --observation-provenance UNKNOWN` |
| **M2 `identity_trust`** | `identity_trust/` | `scripts/module_python.sh identity_trust/assessor.py --experiment-run … --evidence-root … --policy security/policies/minimal_permissions.xml --case S2` |
| **M3 `task_risk`** | `modules/member3_taskrisk/` | `scripts/module_python.sh modules/member3_taskrisk/module.py --policy config/task_policy.yaml` |

**解释器必须通过 `scripts/module_python.sh` 解析**：它会先确认候选解释器能构造
Draft 2020-12 校验器再 `exec`；系统 `python3` 的 jsonschema 3.x 会让三个模块
以退出码 2 失败关闭（看起来像"模块坏了"）。

---

## 3. 契约与 Schema 版本

| 项 | 值 |
| --- | --- |
| 契约版本 | **`1.0.0-proposed`（`PROPOSED_V1`，未冻结）** |
| 输入 | `docs/interfaces/schemas/module_input.schema.json` |
| M1 输出 | `comm_risk_evidence.schema.json` |
| M2 输出 | `identity_trust_assessment.schema.json` |
| M3 输出 | `task_risk_decision.schema.json` |
| 冻结的 Action | `PatrolNavigate` |
| 冻结的原因码 | 8 个 `DECISION_REASON_CODES`（含 `EXECUTION_TIMEOUT`） |

**公共 Schema 语义不得在专项中修改。** 需要新增信息请放在 `extensions`
（Schema 已预留），并同步更新契约说明。

---

## 4. 当前阻断（专项要解决的目标）

### 4.1 M1 的阻断

| # | 阻断 | 判据 |
| --- | --- | --- |
| 1 | 模型 `validation_gate_passed = false` | `modules/member1_comm/model/train_report.json` |
| 2 | 24 维运行时子集模型**同样**门槛未过 | `model/train_report_runtime_subset.json` |
| 3 | 部分 ROS 2 / RTPS 特征缺失（采集源是 `/proc` 主机级，不是中间件/报文层） | `modules/member1_comm/collector/proc_runtime.py` |
| 4 | 无活体 ROS 2 时采集器拒绝伪造 `request_count` | `mapping = BLOCKED_MISSING_REQUEST_COUNT` |

**结论**：`ONLINE_PROCEED_READY = FAIL`。**尚未证明具备有效的 ROS 2 在线通信攻击检测能力。**

### 4.2 M2 的阻断

| # | 阻断 | 判据 |
| --- | --- | --- |
| 1 | 无经审核的**生产** DDS 身份签发者 | `identity_trust/current_identity.py` 的 `load_trusted_issuers()` |
| 2 | `test_issuer.py` 只能签发 `TEST_ONLY`，最多得到 `AUTHENTICATED_TEST_ONLY` | 该文件拒绝 `--trust verified` |
| 3 | ROS 2 Jazzy 不向订阅端暴露"发布者已完成 DDS 认证的主体身份" | 见 `docs/MEMBER2_IMPLEMENTATION.md` |

**结论**：`ONLINE_PROCEED_READY = FAIL`。严格真实模式**不能宣称已完成当前请求身份认证**。

---

## 5. 允许修改 vs 禁止修改

### 5.1 允许专项研发修改

| 模块 | 允许目录 |
| --- | --- |
| M1 | `modules/member1_comm/**`（含 `model/`、`collector/`）、`tests/unit/test_member1_*`、`config/team_modules.member1.real.yaml`、`config/acceptance/real_scenarios.member1.yaml` |
| M2 | `identity_trust/**`、`tests/unit/test_identity_trust_*`、`tests/unit/test_identity_current_binding.py`、`config/team_modules.member2.real.yaml`、`config/acceptance/real_scenarios.member2.yaml` |
| 两者共有 | 各自新增的测试夹具（`tests/fixtures/`）与文档 |

### 5.2 **不得修改**

| 项 | 原因 |
| --- | --- |
| `config/task_policy.yaml` | Gateway 权威策略；改它等于改准入结论 |
| `security/policies/**`、`security/keystore/**` | DDS 最小权限；不得放宽 |
| `src/rg_gateway/**`、`src/rg_policy/**` | 权威准入实现 |
| `docs/interfaces/schemas/**` 的既有字段语义 | 公共契约 |
| `scripts/team_demo.py` 的安全判定语义 | P0 修复成果；如需扩展须单独评审并重跑 P0 全矩阵 |
| `user/**` | 成员原始交付，只读 |
| `artifacts/**` 下的历史证据 | 不得改写历史实验数据 |
| RC2 标签与 `release/demo-2026-10-19-freeze` | 已冻结引用 |

> 若确需改动 F0（`scripts/team_demo.py`）或 F0 安全语义，
> 必须同时重跑 `tests/unit/test_f0_identity_trust_boundary.py`（27 项）
> 与 `test_phase2_security_boundaries.py`，并在报告中说明影响。

---

## 6. 两个专项的分支起点

```
M1 专项：  git fetch origin --tags
           git worktree add -b research/m1-online-detection \
               <你的工作树路径> be47ccd6c1b19460b65abc0ea8004706383d01d4

M2 专项：  git fetch origin --tags
           git worktree add -b research/m2-current-identity \
               <你的工作树路径> be47ccd6c1b19460b65abc0ea8004706383d01d4
```

**禁止**：
- 从 `integration/member-module-adaptation`（`acadbf7`）或
  `integration/three-real-online`（`e18598d`）直接开新分支——
  这两个分支**不含** P0 身份信任边界修复，从它们出发会让"自报身份"漏洞复活；
- 从 `demo/2026-10-19-rc2`（`33cb4f9`）出发——不含三真实模块与 P0 修复。

---

## 7. 专项完成的最低验收要求

两个专项分别在各自分支完成后，必须能在**同一 SHA** 上通过：

| 验收项 | 命令 | 通过标准 |
| --- | --- | --- |
| 契约 | `python3 scripts/validate_team_contracts.py --all` | PASS |
| 全仓单测 | `python3 -m pytest tests/unit -q` | 0 failed |
| F0 安全反例 | `python3 -m pytest tests/unit/test_f0_identity_trust_boundary.py -q` | 全通过，不得放宽 |
| 模块验收 | `check_member_module.py --module <m> --real-fixture …` | `meets_pr_gate=True` |
| 三真实联合 | `scripts/run_three_real_online.py` | LEVEL 1+2 PASS |
| **专项目标** | 同上 | **LEVEL 3 从 BLOCKED 变为 PASS** |

> **LEVEL 3 一旦变成 PASS，必须同时提供**：
> 1. M1 模型达标证据（`validation_gate_passed=true` + 门槛对比）；
> 2. M2 签发者资质说明（谁、凭什么能观察 DDS 身份、密钥如何保护）；
> 3. 该 SHA 上的完整在线证据与 SHA-256 清单。

---

## 8. 环境提示（避免重复踩坑）

| 坑 | 说明 |
| --- | --- |
| 系统 `python3` 的 jsonschema 是 3.x | 永远用 `scripts/module_python.sh` 或 `.research-venv/bin/python` |
| `source install/setup.bash` 在 `set -u` 下报 `COLCON_TRACE` | 所有 sourcing 放在 `set +u` 期间 |
| M2 有防重放账本 | 同一 `request_id` 重复运行会被正确判为复用 → `UNKNOWN`；验收要么换 `request_id`，要么清账本 |
| M2 账本父目录必须存在 | 《否则 M2 失败关闭，会被误读成状态不符》 |
| `identity_attestation` 缺省即 `STRICT` | 真实配置别指望"不写就跳过检查" |
