# 交接简报：成员交付审查 + M2/M3 修复验收

> 用途：向外部审查方（ChatGPT / 成员四）说明**两批独立工作**的结论与边界。
> 两批工作由**不同会话并行完成**，审查基准不同，**不可互相替代**。
> 本简报只陈述已实际执行并留证的事实；未执行项一律标注 `NOT_RUN` / `BLOCKED`。
>
> 生成时间：2026-10-15 ｜ 仓库：`godzwp117/RosSystem`

---

## 0. 一分钟摘要（先看这段）

| 项 | 事实 |
|---|---|
| 公共基线 | `origin/baseline` = `a4c5971`（**始终未被移动**） |
| 被审查的交付归档 | `chore/member-deliveries` = `3ce8202`（三成员交付物归档提交） |
| 契约 | `PROPOSED_V1` / `1.0.0-proposed`（**未冻结**） |
| 修复分支 | `origin/fix/m2-m3-acceptance` = `5c3aee0`（5 个提交，基于 `3ce8202`） |
| A. 交付审查 | 只读审查 `3ce8202`，8 份文档，结论固定在该快照上 |
| B. 修复与验收 | 修 M2 日志解析 + M3 验收兼容，28 文件，全量回归 548 passed |
| **未做** | ROS 2 在线联调（无环境，`BLOCKED`）；未创建 PR |

**最容易搞错的一点**：审查报告说 M2 的 S3/S4"应返回 `DENIED` 却返回 `UNKNOWN`"；
修复后 S3/S4 **仍然是 `UNKNOWN`**。这不是没修好 —— 修复目标是**不再丢弃拒绝证据**，
而不是让当前 guarded 请求变成 `DENIED`。详见 §3.2。

---

## 1. 两批工作的基准与关系

```
a4c5971 (origin/baseline, 公共基线，未动)
   │
3ce8202 (chore/member-deliveries = 三成员交付归档)  ← 两批工作共同起点
   │
   ├── A. 交付审查        →  8 份文档，只读审查 3ce8202
   │                         结论固定于 3ce8202，不随后续修复改变
   │
   └── B. 修复与验收      →  28 个文件，修复 M2/M3 缺陷
                             origin/fix/m2-m3-acceptance = 5c3aee0
```

- **A 是"体检报告"**：判断成员交付物在原始快照上是否真实、可追溯、安全边界描述是否准确。
- **B 是"治疗 + 复检"**：修复其中被确认的缺陷，并用**同一组命令**重跑留证。
- A 的结论**不因 B 而修改**（A 自己的版本原则要求历史不得重写）；
  B 的结果作为**独立后继版本**单独记录。二者构成互相印证。

---

## 2. 批次 A：成员交付审查（8 份文档）

位置：`docs/reviews/member-deliveries/`

| 文件 | 内容 |
|---|---|
| `README.md` | 范围、固定 SHA、导航、主要结论、验收门槛 |
| `M1_COMM_REVIEW.md` | 成员一（通信行为可信分析）技术审查 |
| `M2_IDENTITY_REVIEW.md` | 成员二（DDS 身份与资源权限）技术审查 |
| `M3_TASKRISK_REVIEW.md` | 成员三（任务风险推理）技术审查 |
| `CROSS_MODULE_COMPARISON.md` | 三模块方法/完成度/证据/局限对照 |
| `INTEGRATION_READINESS.md` | 集成就绪性、单模块替换与联合测试、阻断问题分级 |
| `COMPETITION_CLAIMS.md` | 竞赛材料：可声明 / 需限定 / 禁止声明 |
| `EVIDENCE_INDEX.json` | 机器可读证据索引（78 个文件 + 24 条结论 + 验收门槛状态） |

### 2.1 已做的独立核验（这批文档可信度如何）

| 核验项 | 结果 |
|---|---|
| `EVIDENCE_INDEX.json` 的 78 条 sha256 | **逐条实测复算：78 OK / 0 mismatch** |
| 索引引用的 78 个文件是否存在 | 78/78 存在 |
| `EVIDENCE_INDEX.json` 结构 | 合法 JSON，字段完整 |
| 敏感信息扫描 | 无 |
| 与 reset 提交比对 | 7 文件字节一致；`README.md` 为较新版本 |

### 2.2 A 的编号体系警告（引用时必须注意）

`artifacts/acceptance/` 里的 **`m1_stable` / `m2_sros2_enforce` / `m3_dynamic_policy`
是"系统工程验收阶段"名称**，与**成员一/二/三**不是同一编号体系。
引用时一律写全名（如 `exports/m2_sros2_enforce`），否则会把 M1 的验收包误当成成员二的。

### 2.3 A 定位的主要缺陷（P1 级）

| 编号 | 缺陷 | 涉及 | 状态 |
|---|---|---|---|
| **P1-1** | ANSI 彩色日志使 Fast DDS 原生拒绝不可识别 | M2 | **已修复并回归**（见 §3.1） |
| **P1-2** | 通用验收器以 `detail.f0_mock.scenario` 驱动四状态，真实模块结构性无法通过 | M3 | **已修复并回归**（见 §3.3） |

---

## 3. 批次 B：修复与验收（28 个文件，5 个提交）

提交：
`86d383e` 修复 → `85691f3` 测试+报告 → `f649c19` 证据 → `d417ccc`/`5c3aee0` 归档审查

### 3.1 M2：DDS 拒绝日志解析（P1-1）

**缺陷**：交付版 `DENIAL_RE = r'\[\s*SECURITY\s+Error\s*\].{0,600}?not found in allow rule'`
无法匹配真实归档日志。真实字节显示控制序列**插进 `SECURITY` 与 `Error` 之间**：

```
b'...\x1b[31;1m[\x1b[37;1mSECURITY\x1b[31;1m Error] \x1b[37mrr/rg/nav_execute/...'
```

**决定性证据**：只删 ANSI、不改任何文字，旧正则**立刻匹配** →
说明 ANSI 是唯一阻断因素，日志本身语义完整：

```
S3: after ANSI-strip only -> OLD DENIAL_RE match = True
S4: after ANSI-strip only -> OLD DENIAL_RE match = True
```

**修复**：有界 ANSI 规范化（正规文法，仅内存，原始日志零改写）+ 单行原生签名
（`SECURITY…Error]` + `not found in allow rule` + `Permissions.cpp:<行号>`）
+ 拒绝资源核对。

**修复前后对比（真实归档日志）**：

| 场景 | 交付版 | 修复后 |
|---|---|---|
| S2 | `AUTHORIZED` | `AUTHORIZED` |
| S3C | `UNKNOWN` | `UNKNOWN`（历史对照成功，资源不同） |
| **S3** | `UNKNOWN`，**拒绝证据被整体丢弃** | `UNKNOWN`，**证据保留**：拒绝资源 `rr/rg/nav_execute/_action/send_goalReply`、日志行号 1 |
| **S4** | 同上 | 同上 |

**门禁收紧（重要）**：超时、Action Server 不可达、业务 TaskPolicy BLOCK、普通异常
**一律不再可能**被解释为 DDS 权限拒绝；跨行拼接不再构成证据（旧正则 `.{0,600}?` 可跨行）。

### 3.2 必须澄清：S3/S4 修复后仍是 `UNKNOWN`（不是 `DENIED`）

这是**最容易误读**的一点，务必按此理解：

1. **契约强制**：`module_input` Schema + `envelope_check` 把候选入口固定为
   `/rg/guarded_navigate`（guarded Action）。
2. **历史实验拒绝的是执行端**：S3/S4 的资源是 `/rg/nav_execute`（execute 通道）。
3. 两者**资源不同**，所以历史拒绝**不能**搬运到当前请求上。

因此：
- **证据层 `examine()`** = `DENIED`（拒绝资源 `/rg/nav_execute`，已完整保留）
- **评估结论层 `assessment()`** = `UNKNOWN`，且
  `extensions.current_request_binding = HISTORICAL_RESOURCE_MISMATCH`

**修复的真实目标**是"不再丢弃拒绝证据"，**不是**"让当前 guarded 请求变成 `DENIED`"。
把后者的达成当作验收标准是**错误的**。这一层是**收紧**，不是放松。

> 交付版还有一个结构性事实（已实测确认）：因为交付版只在 `AUTHORIZED` 分支比较资源，
> 而 DENIED 场景资源与候选项永不相等，所以交付版 `assessment()` 顶层
> `status` **结构上取不到 `DENIED`**。审查报告"`DENIED` 永不产生"的判断**成立**。
> 由此 P1-1 在交付版上的**实际后果是"证据被丢弃 + 失败关闭为 `UNKNOWN`"**
> （错在安全方向），而不是产生错误的 `DENIED`。
> **建议成员四据此下调 P1-1 的风险定级**——本次未替其改定级。

### 3.3 M3：真实模块验收兼容（P1-2）

**根因**：验收器用 `detail.f0_mock.scenario` 注入场景，而真实规则模块
**不解析该开关**，它依据候选 Action / Task ID / 坐标系 / 目标位置 / TaskPolicy
计算建议。故三种阻断状态在真实模块上**不可触发**。

**已实测复现交付报告**：用修复前验收器跑出 `33 PASS / 3 FAIL / 1 NOT_RUN / 1 BLOCKED`，
与 `deliveries/member3-taskrisk/reports/generic_acceptance_report.json` **计数逐项一致**，
证明复现环境与交付方一致、不是环境差异。

**关键事实：M3 算法源码无需任何修改**（`module.py`/`risk_model.py` 与交付**字节一致**）。
问题 100% 在验收器一侧 —— 没有用"改模块迁就测试"的方式解决。

**修复**：新增 `--real-fixture` 真实场景机制。四状态全部由**真实条件**触发：

| 场景 | 真实触发条件 | 实测结果 |
|---|---|---|
| allow | 目标 (2.0,2.0) 在权威策略 `[0,4]²` 内 | `ALLOW_RECOMMENDED` |
| block | 同一目标超出隔离策略 `[0,1]²` | `BLOCK_RECOMMENDED` |
| unknown | 受信任配置指向**不存在**的策略文件 | `UNKNOWN` |
| error | 受信任配置指向**损坏**策略文件（非法 YAML） | `ERROR` |

四条均 `schema_ok=True`、`traceability_ok=True`，输出符合**原有 Schema**。

**安全设计要点**：
- 命令只能来自受信任配置的 `real_command_profiles`；fixture 只能引用**档案名**
- 业务 JSON 携带 `command/exec/policy/env/cwd/script` 等 15 类字段**一律拒绝**（已实测 15/15 拒绝）
- 验收器**独立**判定策略文件真实状态（不依赖模块自报），伪造策略引用无法通过
- 缺失/损坏策略为**隔离 fixture**；权威策略 `config/task_policy.yaml` **未被修改**
- **未改**公共 Schema、Gateway 权威规则、DDS 权限配置

**验收结果**：M2 / M3 真实模块**各 45 PASS，门槛 True**。

---

## 4. 实际执行的测试与结果

**运行环境**：Linux 6.18 WSL2 ｜ Python 3.10.12 ｜ pytest 9.1.1 ｜ jsonschema 4.26.0
｜ PyYAML 6.0.3 ｜ **无 ROS 2**（无 `/opt/ros`，`ros2` 不在 PATH）

| 命令 | 结果 |
|---|---|
| `pytest tests/unit -q` | **548 passed, 3 skipped**，rc=0 |
| `test_identity_trust_assessor.py` | 23 passed |
| `test_identity_trust_real_logs.py`（新增） | 56 passed |
| `test_member3_taskrisk.py`（交付） | 95 passed |
| `test_member3_real_acceptance.py`（新增） | 41 passed |
| 受影响 F0/契约测试（7 个文件） | 180 passed |
| 真实模块验收（M2 / M3） | 各 45 PASS / 门槛 True / rc=0 |
| Mock 模式回归（3 模块） | 各 34 PASS，逐项与修复前一致 |
| 4 个公共 Schema | 加载+自检通过，**SHA-256 与快照一致** |
| **ROS 2 Jazzy + DDS-Security Enforce** | **NOT_RUN / BLOCKED** |

**反假通过测试**：静默退出、挂起、非法 JSON、恒返回 ALLOW、缺状态字段、
伪造策略引用的模块**全部判 FAIL**；把期望状态改成与真实条件不符也被判负。

### 4.1 关于报告里的 `3 FAIL`（不要误读）

M2/M3 的验收报告都是 `45 PASS / 3 FAIL / 1 NOT_RUN / 1 BLOCKED`，门槛 `True`。
那 `3 FAIL` 是 `STATE-BLOCK / STATE-UNKNOWN / STATE-ERROR` ——
把 Mock 场景开关套用到**不解析该开关的真实模块**。它们：

- **如实保留在报告中并显示 FAIL**（未删除、未改成 PASS）
- 标记 `gate=False`、`applicability=NOT_APPLICABLE_REAL_MODULE`
- 门槛由真实条件矩阵 `REAL-STATE-*` 承担

这是"如实记录不适用"，**不是**"删除失败检查或降低门槛"。
未给出 `--real-fixture` 时，Mock 矩阵仍是**强制项**，行为与修复前完全一致。

---

## 5. 本次没有做到的事（禁止据此过度声明）

- **没有**执行任何 ROS 2 / DDS-Security Enforce 在线实验（无环境）
- **没有**取得 Gateway 决策或 NavigationSim Goal 证据
- **没有**让 M2 成为在线 DDS 身份认证器，也**不声称**它现在是
  （它仍是**离线证据解释器**：`AUTHORIZED` 只表示所引用历史实验中访问成功）
- **没有**证明 M3 对未知攻击的泛化能力
- **没有**修改或复跑历史 S1–S6 实验，只是**读取**其归档日志作为证据
- **没有**冻结 `PROPOSED_V1` 契约
- **没有**创建 PR、**没有**推送 `baseline`/`main`

---

## 6. 请外部审查方回答 / 裁定的事项

| # | 事项 | 说明 |
|---|---|---|
| Q1 | **P1-1 风险定级是否下调** | 交付版该路径为**失败关闭**（错在安全方向），审查报告原定级可能偏高 |
| Q2 | **契约张力 R-1 如何裁定** | `ID-03` 要求 `event_id` 含完整 `request_id`，但 Schema 将 `event_id` 限为 ≤128 字符 → `request_id` > 80 字符时**数学上无法同时成立**。现选择保证 Schema 合法性 |
| Q3 | **PR 目标分支** | `origin/baseline` 停在 `a4c5971`，比本分支基点 `3ce8202` **更旧**；直接对 `baseline` 开 PR 会把成员交付归档一并带入。需确认团队合流顺序 |
| Q4 | **L3 联调安排** | 需具备 ROS 2 Jazzy + DDS-Security Enforce 的环境才能执行 |
| Q5 | **M2 正面对候选入口结论是否要补实验** | 现有受控实验中，针对 `/rg/nav_execute` 的拒绝不能用于 `/rg/guarded_navigate`。若希望 M2 对候选入口给出正面结论，需**新增针对候选入口的受控实验** |
| Q6 | **M3 遗留项是否纳入下一阶段** | `runtime_monitor = NOT_READY`、`dynamic_state_model = NOT_INTEGRATED`（交付方自述，本次未改变） |

---

## 7. 状态口径（请沿用，不要混用）

| 标记 | 含义 |
|---|---|
| `FIXED` | 源码已修且有测试证明 |
| `VERIFIED` | 本轮**实际重新执行**并通过 |
| `PARTIAL` | 部分验证 |
| `NOT_RUN` | 尚未执行 |
| `BLOCKED` | 受环境限制无法执行 |
| `SKIPPED` | **不计入 PASS** |

**总体结论：`PARTIAL`。**
M2/M3 的**离线与 L2 真实模块层面已达到进入下一阶段集成的条件**；
**L3 在线联调未达到**，任何材料中不得写成已完成。

---

## 8. 关键路径索引

| 内容 | 路径 |
|---|---|
| 交付审查（8 份） | `docs/reviews/member-deliveries/` |
| 修复与验收报告 | `docs/reviews/M2_M3_FIX_REPORT.md` |
| 验收证据（2 份 JSON） | `artifacts/acceptance/m2_m3_fix/` |
| 交付↔修复 diff | `artifacts/acceptance/m2_m3_fix/diff.m2_assessor.patch` |
| M2 原始安全证据（只读） | `artifacts/acceptance/exports/m2_sros2_enforce/logs/tests_evidence/20261009T093144Z/` |
| M3 交付原始报告 | `deliveries/member3-taskrisk/reports/generic_acceptance_report.json` |
| M2 修复实现 | `identity_trust/assessor.py` |
| M3 接入点（未改算法） | `modules/member3_taskrisk/` |
| 通用验收器 | `scripts/check_member_module.py` |
| 真实场景 fixture | `config/acceptance/real_scenarios.member{2,3}.yaml` |
