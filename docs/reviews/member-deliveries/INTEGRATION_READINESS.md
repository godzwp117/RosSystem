# 集成就绪性与阻断问题

- 快照：`chore/member-deliveries` = `3ce820258c69b89e2ad9291e16c44dc7d2b99150`
- 公共基线：`a4c597161d254192b662ee7b8f4d17f76a89cc16`（`origin/baseline`，本轮 `git ls-remote` 复核**未变**）
- 本文件所有"本轮实测"均在独立 Git worktree `/tmp/rg-review`（detached，基于 `3ce8202`）中执行，**未改动 baseline / main / 任何成员源码**
- 运行解释器：`/home/zhangwei/project/RosSystem/.research-venv/bin/python`（Python 3.10.12，jsonschema 4.26.0，pytest 9.1.1）

---

## 1. 当前实际可运行的最完整系统形态

本轮已实测跑通的最完整形态：

```
ModuleInputEnvelope (docs/interfaces/examples/module_input_valid.json)
        │
        ├─ comm_risk      : MOCK（基线替代品，成员一模型未交付）
        ├─ identity_trust : 成员二 EXTERNAL（真实 assessor，指向被追踪 SROS2 证据）
        └─ task_risk      : 成员三 EXTERNAL（真实规则引擎，指向 config/task_policy.yaml）
        │
        ▼
   scripts/team_demo.py  →  decision = READY_FOR_GATEWAY_SUBMISSION
                             reason_code = ADAPTER_OK
```

实测输出（命令与返回码见 `README.md` §4）：

| 模块 | mode | status | schema_ok | exit_code |
| --- | --- | --- | --- | --- |
| `comm_risk` | mock | `NORMAL` | true | 0 |
| `identity_trust` | external | `AUTHORIZED` | true | 0 |
| `task_risk` | external | `ALLOW_RECOMMENDED` | true | 0 |

越界目标（`x=999, y=999`）时：

| 模块 | status |
| --- | --- |
| `comm_risk` | `NORMAL` |
| `identity_trust` | `AUTHORIZED` |
| `task_risk` | **`BLOCK_RECOMMENDED`** |

→ 适配层 `ADAPTER_BLOCK` / `ADAPTER_MODULE_STATUS_NOT_PROCEED`。

**可以确认的四层区分**：

| 层次 | 本轮是否独立观测到 |
| --- | --- |
| ① 模块输出合法（Schema） | ✅ 三者 `schema_ok=true` |
| ② 适配层允许推进 | ✅ `READY_FOR_GATEWAY_SUBMISSION` |
| ③ Gateway 实际允许 | ❌ **本轮未观测**（需 ROS 2 运行时） |
| ④ 下游真实执行（NavigationSim Goal） | ❌ **本轮未观测** |

**`READY_FOR_GATEWAY_SUBMISSION` ≠ Gateway `ALLOW` ≠ 已完成真实导航执行。** 本报告在第三章起均按此区分表述。

---

## 2. 单模块替换测试（本轮实测）

| 配置 | comm_risk | identity_trust | task_risk | 适配层决策 |
| --- | --- | --- | --- | --- |
| 基线默认（全 Mock） | mock | mock | mock | 34 PASS，门槛 True（对照） |
| 仅 M3 替换 | mock | mock | **external** | 33 PASS / 3 FAIL（harness 不兼容） |
| 仅 M2 替换（占位 run） | mock | **external** | mock | 32 PASS / 4 FAIL（4 场景均 `UNKNOWN`，失败关闭） |
| 仅 M2 替换（真实 run） | mock | **external** | mock | 32 PASS / 4 FAIL（同上，因 evidence-root 未指向被追踪路径） |
| **M2+M3 同时替换** | mock | **external** | **external** | **`READY_FOR_GATEWAY_SUBMISSION`** ✅ |
| M2+M3 同时替换 + 越界目标 | mock | external | external | `ADAPTER_BLOCK`（M3 正确阻断）✅ |

**未能测试**：三模块全部替换（成员一模型产物未交付，无法以真实模型运行）。

---

## 3. 依赖与配置兼容性矩阵

| 项 | M1 | M2 | M3 | 兼容性 |
| --- | --- | --- | --- | --- |
| 运行位置 | 必须 `repo/modules/my_comm/` | 必须 `repo/identity_trust/` | 必须 `repo/modules/member3_taskrisk/` | ⚠️ **三者都不能在 `deliveries/` 原地运行**（`ModuleNotFoundError`），必须先按各自 README 复制到仓库布局 |
| Python | 3（训练在 Windows） | 3（纯标准库） | 3 | ✅ |
| numpy / scikit-learn | 必需 | — | — | ✅ |
| PyYAML | — | —（解析 XML） | 必需 | ✅ |
| **jsonschema ≥ 4.0** | 必需（`Draft202012Validator`） | 完整仓库中必需 | 必需 | ⚠️ **共同硬依赖**，缺失时三者行为不同（见 §6） |
| ROS 2 运行时 | 不需要（离线） | 不需要（读日志） | 不需要 | ✅ 三者均可在纯 Python 下运行 |
| `ROS_DOMAIN_ID` | 受控实验用 51 | 证据为 43 | 不涉及 | ⚠️ 成员一受控实验用 **51**，M2 证据域为 **43**，不可混用 |
| 外部文件依赖 | 模型 `training_runs/member1/model.json`（**未交付**） | `security/keystore/**`（**未追踪**）、SROS2 证据目录 | `config/task_policy.yaml`（已追踪） | ⚠️ 见 §4 |
| 数据来源 | ROSPaCe 官方归档 | SROS2 受控实验 | 本地 TaskPolicy | ✅ 互不冲突 |

---

## 4. 「配置 ↔ 证据」错配（重要）

| 资源 | 是否被 Git 追踪 | 模块默认指向 | 实际可用路径 |
| --- | --- | --- | --- |
| `config/task_policy.yaml` | ✅ 已追踪 | ✅ 正确 | 无问题 |
| `security/policies/minimal_permissions.xml` | ✅ 已追踪 | ✅ 默认正确 | 无问题 |
| `security/keystore/enclaves/*/permissions.xml` | ❌ **被 `.gitignore` 忽略** | ✅ 默认路径正确，但**新克隆不存在** | 需先跑 `scripts/setup_sros2.sh` 生成 |
| SROS2 实验证据 | ❌ `tests/evidence/` **被忽略** | ❌ 默认 `tests/evidence` | ✅ 被追踪的副本在 `artifacts/acceptance/exports/m2_sros2_enforce/logs/tests_evidence/20261009T093144Z/`（7/7 PASS，domain 43） |
| 成员一模型 `training_runs/member1/model.json` | ❌ 被忽略且**未交付** | ✅ 默认路径正确 | **不存在**，需重新训练 |

**后果**：在一台全新克隆的机器上，按成员二的 `config/team_modules.member2.example.yaml` 直接运行，`identity_trust` 必然返回 `UNKNOWN`（实测报错 `missing/unsafe summary` 或 `missing or unsafe XML`）。这**不是算法失败**，而是**证据未随代码分发**。

**建议**：把成员二的配置与文档的 `--evidence-root` 改指向被追踪的 `artifacts/acceptance/exports/m2_sros2_enforce/logs/tests_evidence`，并保留 `tests/evidence` 作为「本轮新跑实验」的位置。

---

## 5. 验收脚本 `check_member_module.py` 的结构性不兼容（P1）

**现象**：三个真实模块在该脚本下均无法通过，Mock 全绿。

| 被测 | 计数 | 门槛 |
| --- | --- | --- |
| 基线 Mock（`comm_risk` / `identity_trust` / `task_risk`） | 34 PASS / 3 NOT_RUN / 1 BLOCKED | **True** |
| 成员三 `external` | 33 PASS / **3 FAIL** / 1 NOT_RUN / 1 BLOCKED | False |
| 成员二 `external` | 32 PASS / **4 FAIL** / 1 NOT_RUN / 1 BLOCKED | False |

**根因 1（3 项 STATE-* FAIL）**：脚本通过 `envelope.observations[0].detail.f0_mock.<module>.scenario` 注入期望状态（`scripts/check_member_module.py:82-88`），**只有基线 Mock 读该字段**。真实模块正确地忽略它，因此 `block`/`unknown`/`error` 三个场景都按真实策略评估同一合法目标 → 全部返回"允许"类状态。

**根因 2（`LIM-02` FAIL）**：`LIM-02 stdout 超限时立即终止且不判成功` 报 `exceeded=None stdout_bytes=0（上限 64）`。该 FAIL 在**三个 Mock 与两个成员模块上表现一致**，疑为脚本对极小 `max_stdout_bytes` 的度量问题，**不作为成员缺陷计**。

**影响**：`meets_pr_gate: False` 目前**不能**用来否定任何真实模块。成员三在其 `IMPLEMENTATION_REPORT.md:20` 已如实记录此事。

**建议（优先级高）**：为外部模块增加一条不依赖 `f0_mock` 的验收路径——例如由脚本改**输入信封本身**（构造越界目标 / 错误 task_id / 不存在的策略路径）来驱动四状态，而不是注入期望值。这也是评审中"用真实输入而非 Mock 开关"的一贯要求。

---

## 6. 解释器依赖导致的失败模式差异（P1/P2）

在 `/usr/bin/python3`（jsonschema **3.2.0**）下直接按手册命令运行：

| 模块 | 行为 | 返回码 | stdout |
| --- | --- | --- | --- |
| M3 `task_risk` | `RuntimeError: 缺少 jsonschema>=4.0` → **未被捕获的 traceback** | **1** | 空 |
| M2 `identity_trust` | 捕获异常 → `official ModuleInputEnvelope validation failed` | **2** | 空 |
| M1 `comm_risk` | 同类依赖（`Draft202012Validator`） | 非 0 | 空 |

在正确解释器（jsonschema 4.26.0）下，三者恢复正常。

**评价**：三者**都失败关闭**（非零退出 → 适配层阻断），所以**不构成放行风险**。但 M3 是**不受控崩溃**（无 ERROR 文档、无约定返回码），应修。

**建议**：交付配置不要硬编码 `python3`，改为显式解释器路径，或在模块入口前置依赖自检并返回约定的错误码。

---

## 7. 阻断项汇总

### P0（安全边界失效 / 危险执行放行）

**未发现 P0。**

本轮所有实测失败方向均为**失败关闭**：M2 彩色日志缺陷 → `UNKNOWN`（非 `AUTHORIZED`）；M3 崩溃 → rc=1（适配层阻断）；缺依赖 → 非零退出。三模块均无绕过 Gateway、无直接调用 `/rg/nav_execute`、无 UNKNOWN/ERROR 被当作允许。

### P1（影响集成、结果真实性或可靠性）

| # | 问题 | 影响模块 | 技术依据 | 建议 | 验收标准 |
| --- | --- | --- | --- | --- | --- |
| P1-1 | ANSI 彩色日志使原生 DDS 拒绝不可识别，`DENIED` 永不产生 | M2 | `assessor.py:30` 正则 vs `assessor.py:202` 未去色；两处证据根均复现 | 读取后剥离 `\x1b\[[0-9;]*m`，或让正则容忍转义序列；同时保留未去色原始文本用于取证 | S3/S4 在被追踪证据上返回 `DENIED` + `denial_layer=DDS_ACCESS_CONTROL`，且新增含 ANSI 的回归 fixture |
| P1-2 | 验收脚本以 `f0_mock` 驱动四状态，真实模块结构性无法通过 | 全部 | `scripts/check_member_module.py:82-88`；Mock 34 PASS vs 外部模块 3-4 FAIL | 改为通过构造真实输入驱动四状态 | 成员一/二/三在 `external` 模式下均能达到门槛，或脚本明确区分「Mock 模式」与「外部模式」 |
| P1-3 | M2 证据根默认指向未追踪目录，新克隆必失败 | M2 | `git check-ignore`：`.gitignore:8:/tests/evidence/` | 默认/文档改指向被追踪的 `artifacts/acceptance/exports/m2_sros2_enforce/logs/tests_evidence` | 新克隆 + `setup_sros2.sh` 后，S2 case 返回 `AUTHORIZED` |
| P1-4 | 成员一模型产物未交付，`comm_risk` 无法以真实算法运行 | M1 | 交付包内无 `model.json`；`training_runs/member1/` 不存在 | 交付模型（含 `model.sha256`）或给出确定性再训练脚本与期望指标 | 三模块全部 `external` 的联合运行可复现 |

### P2（可在时间允许时解决）

| # | 问题 | 影响模块 | 依据 |
| --- | --- | --- | --- |
| P2-1 | `jsonschema<4` 时 M3 未捕获 `RuntimeError` → rc=1 崩溃 | M3 | `module.py:96` 捕获列表不含 `RuntimeError`；本轮复现 traceback |
| P2-2 | `event_id` 不含 `request_id`，审计关联弱 | M2 | `assessor.py:280`；`check_member_module` ID-03 FAIL |
| P2-3 | 三模块均不能从 `deliveries/` 原地运行 | 全部 | 依赖 `repo/scripts`、`repo/src/rg_policy` 的 `sys.path` 注入 |
| P2-4 | `LIM-02` 验收项在 Mock 与真实模块上均 FAIL | 全部 | 疑为脚本度量问题，需先判定归属再修 |
| P2-5 | M1 测试分片取末两片，导致 6 类攻击只覆盖 1 类 | M1 | `train.py:63-66`；两数据集测试集均只含 metasploit SYN flood |

### P3（可后续研究）

| # | 问题 | 影响模块 |
| --- | --- | --- |
| P3-1 | M3 `--audit-log` 未做符号链接校验 | M3 |
| P3-2 | M2 `subject.declared_enclave` 命名易被误读为请求方自报 | M2 |
| P3-3 | M2 日志 `errors='replace'` 可能静默替换损坏字节 | M2 |
| P3-4 | M1 `--controlled-test` 开关可让未过验证门的模型输出 `NORMAL`（受信任配置约束，无强制机制） | M1 |

---

## 8. 工作量的量级判断（不给具体工期承诺）

以下仅按**改动性质**给出相对量级，依据是本轮实际定位到的代码位置：

| 项 | 改动性质 | 相对量级 | 前置依赖 |
| --- | --- | --- | --- |
| P1-1 ANSI 去色 | 单文件、少量代码 + 新增回归 fixture | **最小** | 无 |
| P1-3 证据根改指向 | 配置与文档改动 | **最小** | 无 |
| P2-1 捕获 `RuntimeError` | 单行级改动 + 补测 | **最小** | 无 |
| P2-2 `event_id` 关联 | 单行级改动 + 补测 | **最小** | 无 |
| P2-3 交付可原地运行 | 各模块加路径适配或统一 `PYTHONPATH` 约定 | **小** | 团队约定 |
| P1-2 验收脚本改造 | 需重新设计四状态驱动方式并回归三个模块 | **中** | P2-3 |
| P1-4 交付 M1 模型 | 需重跑训练并交付产物与哈希 | **小（已具备数据与脚本）** | 数据归档可获得 |
| M1 测试覆盖偏置 | 需重新设计划分（分层抽样）并重跑实验 | **中** | P1-4 |
| M3 历史推断真实化 | 需真实 Gateway journal + 端到端联调 | **中** | ROS 2 运行时 |
| L3 全链路联调 | 需 Jazzy 容器、构建、安全启动、Gateway 审计核对 | **大** | ROS 2 运行时 + 三模块就绪 |

---

## 9. 建议的集成顺序

1. **先修「不改变结论」的缺陷**：P1-1（ANSI）、P1-3（证据根）、P2-1（崩溃）、P2-2（`event_id`）。四项互不依赖，且都不触碰算法语义。
2. **修 P1-2**（验收脚本），使 `meets_pr_gate` 重新具备判定能力——否则后续所有模块都无法被机器验收。
3. **补 P1-4**（成员一模型），使三模块全部 `external` 的联合运行成为可能。
4. **再动 L3**：在 Jazzy 容器内跑通「三模块 external → 适配层 → `/rg/guarded_navigate` → Gateway → `/rg/nav_execute` → NavigationSim」，并**分别记录** DecisionEvent、Action Result、Goal 数量。
5. **最后处理研究性局限**（M1 划分偏置、M3 历史推断、M2 身份绑定），这些不影响「系统可运行」但影响「论文结论的强度」。

**明确不建议做的事**：不要为赶进度重构适配层或 Gateway；不要通过放宽 Schema、关闭 DDS-Security、或修改 Gateway 策略来让模块"通过"；不要把未过验证门的检测器设为默认模块。
