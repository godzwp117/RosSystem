# 成员交付物审查（`docs/reviews/member-deliveries/`）

本目录是对 RosSystem 三名成员研发交付物的**只读证据审查**结果。
审查目标是**真实性、可追溯性与系统安全边界的准确性**，不以增加 PASS 数量或美化结论为目的。

---

## 1. 审查范围与固定提交

| 项 | 值 |
| --- | --- |
| 仓库 | `https://github.com/godzwp117/RosSystem` |
| 本地路径 | `/home/zhangwei/project/RosSystem` |
| **公共 baseline** | `origin/baseline` = `a4c597161d254192b662ee7b8f4d17f76a89cc16`（本轮 `git ls-remote` 复核**未变化**） |
| **被审查快照** | `chore/member-deliveries` = `3ce820258c69b89e2ad9291e16c44dc7d2b99150`（归档提交，2026-10-15 00:42 +08:00） |
| 审查工作分支 | `docs/member-delivery-review`（基于被审查快照新建，**未写入 baseline / main**） |
| 审查日期 | 2026-10-14（UTC） / 2026-10-15（CST） |
| 审查者 | 研发审查智能体（本轮会话） |
| 运行时 | Python 3.10.12，`jsonschema` 4.26.0，`pytest` 9.1.1（`<repo>/.research-venv`）；宿主 Ubuntu，无 ROS 2 |

### 1.1 关于"原始交付"与"后续修复"的分离

- 本轮审查固定在上表的归档快照 `3ce8202` 上；**该快照本身即"原始交付的归档版本"**。
- 归档者已说明：成员一的交付包内含一份完整仓库快照（582 文件），经逐文件比对后**只归档真正新增的 71 项**，其余为本仓库已有的行尾差异文件；归档时文本统一归一化为 LF。**因此 `deliveries/member1-comm/` 中的文件内容与成员一原始 ZIP 可能仅存在行尾差异。**
- 成员一原始 ZIP 仍保留在本地 `user/RosSystem-member1-delivery(1).zip`（SHA-256 见 §5），可用于逐字节比对。
- **本轮未发现任何成员交付的"后续修复版本"。**

### 1.2 编号警告（重要）

`artifacts/acceptance/` 中的 **`m1_stable` / `m2_sros2_enforce` / `m3_dynamic_policy` 是系统工程验收阶段名称**，
与**成员一 / 成员二 / 成员三**不是同一编号体系。本目录所有文档均按「M1 = 通信风险成员」使用该符号，
涉及验收阶段时一律写全名（如 `exports/m2_sros2_enforce`）。

---

## 2. 阅读导航

| 文件 | 内容 |
| --- | --- |
| `README.md` | 本文件：范围、固定提交、导航、主要结论、验收门槛 |
| [`M1_COMM_REVIEW.md`](M1_COMM_REVIEW.md) | 成员一（通信行为可信分析）完整技术审查 |
| [`M2_IDENTITY_REVIEW.md`](M2_IDENTITY_REVIEW.md) | 成员二（DDS 身份与资源权限）完整技术审查 |
| [`M3_TASKRISK_REVIEW.md`](M3_TASKRISK_REVIEW.md) | 成员三（任务风险推理）完整技术审查 |
| [`CROSS_MODULE_COMPARISON.md`](CROSS_MODULE_COMPARISON.md) | 三模块方法、完成度、证据与局限对照（含系统级对照表） |
| [`INTEGRATION_READINESS.md`](INTEGRATION_READINESS.md) | 实际集成就绪性、单模块替换与联合测试、阻断问题分级 |
| [`COMPETITION_CLAIMS.md`](COMPETITION_CLAIMS.md) | 竞赛材料：可声明 / 需限定 / 禁止声明 |
| `EVIDENCE_INDEX.json` | 机器可读证据索引（78 个交付文件 + 24 条结论 + 验收门槛状态） |

---

## 3. 主要结论（摘要）

### 3.1 三个模块的真实性判断

| 模块 | 真实算法结论 | 一句话 |
| --- | --- | --- |
| **M1 通信风险** | **真实存在的离线监督学习原型**，但**未达可用门限** | 算法、训练、评估流程完整且**已完整复现**（本轮两份数据集的混淆矩阵与 F1 逐位一致），但两个数据集的 F1 **均低于恒预测攻击基线**，`validation_gate=FAIL`，且测试集**只覆盖 6 类攻击中的 1 类**；无在线采集链路 |
| **M2 身份权限** | **真实存在的离线证据解释器**，**不是**身份认证器 | 对「源策略 ↔ 生成的 DDS 权限 ↔ 受控 Enforce 实验日志」做三方交叉核验；S2 实测返回 `AUTHORIZED`，但输出与当前请求**无因果关系**；且核心的"原生 DDS 拒绝识别"因 **ANSI 彩色日志缺陷**在真实证据上失效（`DENIED` 不可达） |
| **M3 任务风险** | **真实存在的确定性可解释规则引擎**，**不是**机器学习模型 | 静态条款与 Gateway 权威判定**同源**（共用 `parse_task_policy` 与原因码），`agreement=1.0` 在很大程度上是构造性的；真实增量是**聚合违规解释 + 有符号边界距离 + journal 快照推断**；历史推断仅有单测证据 |

### 3.2 关键实验结论

- **M1 `reduced`**：测试集 F1 **0.1312**、Recall **0.0702**、BalancedAcc **0.5351**、FPR 0.0；恒预测攻击 F1 **0.8132** → **模型低于平凡基线 0.682**。
- **M1 `noperiodicity`**：F1 **0.6346**、Recall **0.4648**、BalancedAcc **0.7324**、FPR 0.0；恒预测攻击 F1 **0.8719** → **仍低于平凡基线 0.237**。**本轮独立重跑两份数据集，混淆矩阵与 F1 均逐位一致**（仅 PR-AUC 有千分位差异，源于 sklearn 版本）。
- **M1 测试覆盖**：两个数据集留出测试集的攻击**只有 `metasploit SYN flood` 一类**，其余 5 类 `NOT_EVALUATED`。
- **M2 SROS 2 Enforce**：7/7 PASS（S1/S2/S3/S3C/S4/S5/S6），`secure_domain=43`，含原生 Fast DDS 拒绝与 S3C 正向对照；**属历史运行记录（等级 B），本轮未复跑**。
- **M3 受控实验**：87/87 符合预期（81 组边界网格 + 6 个异常条件）；比较器为**进程内** `rg_policy.policy_engine.evaluate`，**非运行中的 Gateway**；几何消融 FN 13.16%。
- **基线契约**：`scripts/validate_team_contracts.py --all` **PASS**（4 Schema 自检 + 10 有效样例 + 13 非法样例按预期被拒）。

### 3.3 单元测试（本轮全部实跑）

| 模块 | 结果 | 备注 |
| --- | --- | --- |
| M1 | **36 passed** | 必须在仓库布局（`modules/my_comm/`）下运行 |
| M2 | **22 passed** | 与成员自述一致 |
| M3 | **95 passed** | 与成员自述一致 |

**注意**：`deliveries/` 中的模块**不能原地运行**（依赖 `repo/scripts`、`repo/src/rg_policy` 的 `sys.path` 注入）。本轮在独立 Git worktree `/tmp/rg-review`（detached，基于 `3ce8202`）中按各成员 README 的布局复制后运行。

---

## 4. 本轮实际执行的测试（可复现命令）

所有命令均在独立 worktree `/tmp/rg-review` 内、以 `<repo>/.research-venv/bin/python` 运行；**未改动 baseline / main / 成员源码**。

```bash
# 0) 基线契约校验
python3 scripts/validate_team_contracts.py --all                  # → CONTRACT VALIDATION: PASS

# 1) 三个成员模块单测（需先把 deliveries/ 内容按各自 README 复制到仓库布局）
python3 -m pytest modules/my_comm/test_module.py -q               # → 36 passed
python3 -m pytest tests/unit/test_identity_trust_assessor.py -q   # → 22 passed
python3 -m pytest tests/unit/test_member3_taskrisk.py -q          # → 95 passed

# 2) 通用验收（Mock 对照组 / 真实模块）
python3 scripts/check_member_module.py --module task_risk \
    --config config/team_modules.example.yaml                     # → 34 PASS，门槛 True（Mock 对照）
python3 scripts/check_member_module.py --module task_risk \
    --config config/team_modules.member3.yaml                     # → 33 PASS / 3 FAIL / 1 NOT_RUN / 1 BLOCKED

# 3) 联合适配层运行（M2+M3 external，M1 mock）
python3 scripts/team_demo.py \
    --config config/team_modules.review_m2m3.yaml \
    --input docs/interfaces/examples/module_input_valid.json \
    --log /tmp/mr/adapter_final.jsonl                             # → READY_FOR_GATEWAY_SUBMISSION / ADAPTER_OK

# 4) 越界目标（验证模块建议 vs 适配层阻断）
python3 scripts/team_demo.py --config config/team_modules.review_m2m3.yaml \
    --input /tmp/mr/env_out_of_region.json                        # → ADAPTER_BLOCK（M3 BLOCK_RECOMMENDED）

# 5) 成员二解析器直连真实证据（缺陷复现）
python3 identity_trust/assessor.py --experiment-run 20261009T093144Z --case S3 \
    --evidence-root artifacts/acceptance/exports/m2_sros2_enforce/logs/tests_evidence \
    < docs/interfaces/examples/module_input_valid.json            # → UNKNOWN（应为 DENIED）

# 6) 成员一离线实验独立复现（官方归档 MD5 校验通过）
python3 modules/my_comm/train.py \
    --archive data/ROSPaCe_reduced/ROSPaCe_reduced_noperiodicity.tar.gz \
    --samples /tmp/mr/samples_noperiodicity --output /tmp/mr/run_noperiodicity
```

**未执行**：L3 ROS 2 真实联调。宿主无 ROS 2，仅有已停止的 `rg_jazzy` 容器；按任务书「不要清理/干扰其他成员进程与容器」，本轮**未启动**该容器。

---

## 5. 严重缺陷

**本轮未发现 P0（安全边界失效 / 危险执行放行）。**

所有实测失败方向均为**失败关闭**（`UNKNOWN`、非零退出、适配层阻断），不存在绕过 Gateway、直接调用 `/rg/nav_execute`、或把 `UNKNOWN`/`ERROR` 当作允许的情况。

已确认的 P1：

| 编号 | 问题 | 影响 | 位置 |
| --- | --- | --- | --- |
| **P1-1** | ANSI 彩色日志使 Fast DDS 原生拒绝不可识别，`DENIED` 永不产生 | M2 | `deliveries/member2-identity/identity_trust/assessor.py:30,202` |
| **P1-2** | 验收脚本以 `f0_mock` 驱动四状态，真实模块结构性无法通过（Mock 34 PASS vs 真实模块 3-4 FAIL） | 全部 | `scripts/check_member_module.py:82-88` |
| **P1-3** | M2 默认证据根 `tests/evidence/` 被 `.gitignore` 忽略，新克隆必失败 | M2 | `deliveries/member2-identity/config/team_modules.member2.example.yaml` |
| **P1-4** | 成员一模型产物未交付，`comm_risk` 无法以真实算法运行 | M1 | 交付包内无 `training_runs/member1/model.json` |

详见 `INTEGRATION_READINESS.md` §7。

---

## 6. 当前系统可运行程度

**已实测跑通的最完整形态**：

```
comm_risk(MOCK) + identity_trust(EXTERNAL) + task_risk(EXTERNAL)
        → scripts/team_demo.py → READY_FOR_GATEWAY_SUBMISSION / ADAPTER_OK
```

四层区分（本轮独立观测）：

| 层次 | 状态 |
| --- | --- |
| ① 模块输出合法（Schema） | ✅ 三者 `schema_ok=true` |
| ② 适配层允许推进 | ✅ 已观测 |
| ③ Gateway 实际允许 | ❌ **未观测**（需 ROS 2 运行时） |
| ④ 下游真实执行（NavigationSim Goal） | ❌ **未观测** |

---

## 7. 验收门槛状态

| 门槛 | 状态 | 说明 |
| --- | --- | --- |
| `SOURCE_DISCOVERY` | **PARTIAL** | 三成员源码均已在 `deliveries/` 定位；但**预期分支 `feature/member1-comm` / `member2-identity` / `member3-taskrisk` 在远端均不存在**，成员一自述分支 `feature/member1-comm-offline-baseline` 亦不存在，交付仅经 `chore/member-deliveries` 归档 |
| `MEMBER1_CODE_AUDIT` | **PASS** | 15 个模块文件全部通读 |
| `MEMBER2_CODE_AUDIT` | **PARTIAL** | 源码通读 + 缺陷定位；实时认证能力与源码结构矛盾 |
| `MEMBER3_CODE_AUDIT` | **PASS** | 源码通读 + 同源性已核实 |
| `MEMBER1_ALGORITHM_EVIDENCE` | **FAIL** | 性能门 FAIL，F1 低于平凡基线，测试仅覆盖 1/6 攻击类 |
| `MEMBER2_SECURITY_EVIDENCE` | **PARTIAL** | 既有 Enforce 实验 B 级；成员二解析器 `DENIED` 路径失效 |
| `MEMBER3_TASK_EVIDENCE` | **PARTIAL** | 受控静态充分；真实流量与历史推断证据不足 |
| `MODULE_CONTRACTS` | **PASS** | 三者输出均通过官方 Schema；契约仍为 `PROPOSED_V1` |
| `L1_PROTOCOL` | **PARTIAL** | 单测与联合运行通过；`event_id` 关联缺失、验收脚本不兼容、依赖崩溃路径 |
| `L2_ALGORITHMS` | **FAIL** | 无任一模块达到"真实研究算法经真实输入验证"的标准 |
| `L3_F0_INTEGRATION` | **NOT_RUN** | 无 ROS 2 运行时；未启动他人容器 |
| `DDS_SECURITY` | **PARTIAL** | 有 B 级历史 Enforce 证据（7/7）；本轮未复跑 |
| `GATEWAY_AUTHORITY` | **PARTIAL** | 适配层已观测阻断；Gateway 层最终阻断未在本轮观测 |
| `CROSS_MODULE_COMPATIBILITY` | **PARTIAL** | M2+M3 联合通过；三模块全真实联合未完成 |
| `RESEARCH_REPRODUCIBILITY` | **PARTIAL** | M1 离线实验可复现（noperiodicity 逐位一致）；模型与数据未随仓库分发 |
| `CRITICAL_ISSUES` | **NO_CONFIRMED_P0** | 4 项 P1 已定位并给出验收标准 |
| `CHATGPT_HANDOFF_REPORT` | **PASS** | 本目录 8 份文档自洽、独立、可定位到源码与证据 |

---

## 8. 版本差异：并行修复分支（单列，不重写本报告结论）

本报告的**全部结论固定在原始交付快照 `3ce8202`** 上。审查期间，工作区中存在一个**由另一修复智能体并行开展**的修复分支：

| 项 | 值 |
| --- | --- |
| 分支 | `fix/m2-m3-acceptance` |
| 起点 | `3ce820258c69b89e2ad9291e16c44dc7d2b99150`（与本次审查同一快照） |
| 审查时的状态 | **只有未提交的工作区改动，尚无提交**；未被推送（见本表下方【状态更新】） |
| 已改动的文件 | `scripts/check_member_module.py`（审查时 +574 / −7）、新增 `tests/unit/test_identity_trust_real_logs.py`、`tests/unit/test_member3_real_acceptance.py`、`identity_trust/`、`config/acceptance/`、`config/scenarios/task_policy_{absent,corrupt,tight_region}` 等（**最终值见下方【状态更新】**） |

> **【状态更新 / 后补事实】** 审查当时的"尚无提交、未被推送"已不成立。后续进展：
>
> - 修复分支已提交并推送：`origin/fix/m2-m3-acceptance` = `f649c19`（3 个提交，基于同一快照 `3ce8202`）。
>   最终差异为 **28 个文件，+6400 / −7**；其中 `scripts/check_member_module.py` 为 **+621 / −7**（上表 +574 / −7 是审查当时的中途值）。全量回归 **548 passed, 3 skipped**。
> - 已用**同一组命令**重跑并单独留证，结果见 `docs/reviews/M2_M3_FIX_REPORT.md` 与
>   `artifacts/acceptance/m2_m3_fix/`：M2 证据层 S3/S4 已能取出原生拒绝
>   （`rr/rg/nav_execute/_action/send_goalReply`，2 条记录）；`check_member_module.py`
>   在真实 fixture 模式下达到门槛（`45 PASS / 门槛 True`）。
> - **重要澄清**：M2 的 S3/S4 在**评估结论层**仍为 `UNKNOWN`，而不是 `DENIED`。本表下方
>   "尤其是 S3/S4 是否返回 `DENIED`"一问的准确答案是：**证据层为 `DENIED`（拒绝资源=
>   `/rg/nav_execute`，已保留），评估层为 `UNKNOWN`** —— 因为当前候选入口是
>   `/rg/guarded_navigate`，历史拒绝不得跨资源搬运。这是**收紧**而非放松。
> - **对 P1-1 影响面的补充限定**（不修改原文结论）：原文「`DENIED` 永不产生」在交付版上**成立且可复现** —— `envelope_check` 强制候选资源为 `/rg/guarded_navigate`，而 DENIED 场景（S3/S4）的资源是 `/rg/nav_execute`，且交付版只在 `AUTHORIZED` 分支做资源比较，因此 `assessment()` 的顶层 `status` 无法取到 `DENIED`。
>   由此，ANSI 缺陷在交付版上的**实际后果是原生拒绝证据被丢弃并失败关闭为 `UNKNOWN`**（安全方向），而不是产生错误的 `DENIED`。修复后资源一致时证据层可正常得到 `DENIED`。
> - 原文结论不因该更新而修改；本节仅记录后继版本的实际结果。

**该分支正在修复的内容与本报告独立定位的缺陷高度重合**，构成互相印证：

| 本报告编号 | 本报告结论（快照 `3ce8202`） | 并行分支的对应动作 |
| --- | --- | --- |
| **P1-1** | `DENIAL_RE` 不匹配带 ANSI 颜色的真实 Fast DDS 日志，S3/S4 的原生拒绝证据被整体丢弃（证据层无法得到 `DENIED`） | 新增 `tests/unit/test_identity_trust_real_logs.py`，其文件头以**相同的字节序列与相同的根因**描述该缺陷，并做 ANSI 规范化 + 归档真实字节回归 |
| **P1-2** | 验收脚本以 `detail.f0_mock.scenario` 驱动四状态，真实模块结构性无法通过 | 在 `scripts/check_member_module.py` 中新增「真实模块场景（L2 入口）」：受信任本地 fixture + `real_command_profiles`，并显式说明 *"`detail.f0_mock.scenario` 是参考 Mock 的控制开关……用 Mock 开关无法触发真实模块的四种状态，旧脚本只能得到 3 个 FAIL"* |

**处理原则**（遵照任务书）：

- 本报告**不因修复分支的存在而修改任何结论**——结论是对 `3ce8202` 这一**原始交付快照**的审查结果，历史不得重写；
- 修复分支的成果应作为**独立的后继版本**另行验收：需在其提交完成后，用**同一组命令**重跑并单独记录结果（尤其是 S3/S4 是否返回 `DENIED`、`check_member_module` 在 `external` 模式下是否达到门槛）；
- 在修复分支被独立验证之前，`COMPETITION_CLAIMS.md` 中的表述边界**依然适用**（特别是 L4：不得声称当前交付版本已能识别 DDS 原生拒绝）；
- 本报告作者**未修改、未提交、未回滚** `fix/m2-m3-acceptance` 上的任何工作区改动。

---

## 9. 约束遵守声明

本轮遵守的边界：

- ✅ **未**修改 baseline、**未**修改 main、**未**合并任何成员研究分支；
- ✅ **未**修改三个成员的算法、**未**改动公共 Schema、**未**改动 Gateway、**未**改动 DDS 权限；
- ✅ **未**覆盖历史报告、**未**修改实验指标、**未**伪造缺失日志；
- ✅ 所有验证在独立 Git worktree 与 `/tmp` 临时目录内进行，未触碰其他成员工作区与容器；
- ✅ 报告未写入任何私钥、Token 或凭据（`security/keystore/` 仅作路径引用，未读取密钥内容）；
- ✅ 明确区分「本轮新验证」与「原交付报告记录」，历史结果一律标注 `HISTORICAL_REPORTED` / 等级 `B`。

如需将本目录推送到 GitHub，应使用独立分支并先确认公开内容，**不得直接提交到共享 `baseline`**。
