# RosSystem —— ROS 2 Jazzy 多模块风险评估与分层安全准入原型系统

> **最终交付分支：`release/final-submission-closeout-2026-10-22`**
> 受测代码 SHA：`2f3de257c9eac873093201292f6b2a9571da4f03`
> 文档归档 HEAD：`842edf2b1bec4d83d8aef4c4782d0c9a245f05b9`（文档修订不改变受测代码 SHA）
> 上一版稳定回退：`integration/final-deliverable-2026-10-22` @ `70fefa47a4333cf2bb3e1631525366897a3cbc81`
> 交付日期：2026-10-22
> 验收结论：**`FINAL_CONTROLLED_SYSTEM_PASS`**（受控系统交付通过，验收器已加固）
> 三真实 LEVEL 3：**`BLOCKED`**（原因见 §0.1 与 §9）

---

## 0. 最终交付摘要（先读这一节）

本分支在既有研究基础上完成**工程交付**，交付一套可部署、可运行、可复验、
具备明确安全边界的 ROS 2 分层安全准入原型。

### 0.1 系统能做什么

| 能力 | 状态 | 说明 |
| --- | --- | --- |
| 受控正向在线闭环 | ✅ 可运行 | M1/M2 受控 Mock + M3 真实规则；F0→Planner→Gateway→NavigationSim 全部真实进程 |
| Gateway 独立权威阻断 | ✅ 可运行 | 越界任务由 TaskPolicy 独立 BLOCK，Goal 为 0 |
| 三真实 External 严格准入 | ✅ 可运行（结果为阻断） | M1/M2/M3 均为真实进程，Schema 合法，F0 STRICT 正确 `ADAPTER_BLOCK` |
| M3 任务风险规则引擎 | ✅ 可运行 | 在线六场景 ON-01..ON-06 实测通过 |
| 正式 DDS-Security Enforce | ✅ 可运行 | 正式权限 S1/S2/S3/S3C/S4/S5/S6 **7/7** |
| F0 身份防伪造 | ✅ 可运行 | 38 项 P0 安全反例通过 |
| **M1 在线检测有效性** | ❌ **未通过** | 模型未达验收门槛（详见 §9） |
| **M2 生产身份签发者** | ❌ **未就绪** | 仅研究级，不能作为生产信任根 |
| **三真实 LEVEL 3 正向准入** | ❌ **BLOCKED** | 缺少 M1/M2 可信正向依据 |

### 0.2 统一执行入口

所有模式通过一个脚本进入：

```bash
scripts/final_system.sh --check                    # 环境与版本自检
scripts/final_system.sh --mode controlled          # 受控正向在线闭环
scripts/final_system.sh --mode three-real-strict   # 三真实严格准入
scripts/final_system.sh --mode enforce             # 正式 DDS Enforce
scripts/final_system.sh --mode acceptance          # 全量验收
```

通用参数：`--run-id <id>`、`--out-dir <dir>`、`--domain <n>`。
每个模式都会把代码 SHA、run_id、命令与退出码写入证据目录；
任何关键失败都以**非零退出**，不会用 `|| true` 掩盖。

### 0.3 本轮真实验收结果（在本受测 SHA 上执行）

| 项目 | 结果 | 证据 |
| --- | --- | --- |
| 公共契约 | **PASS** | `contracts.log` |
| 全仓单元测试 | **847 passed, 1 skipped** | `unit_tests.log` |
| F0 P0 安全反例 | **38 passed** | `f0_p0.log` |
| 三真实 External | 调用 PASS / Schema PASS / **F0 BLOCK（预期）** | `three_real/` |
| 受控在线正向 | **request_id 级严格验收 PASS**（40 checks），Gateway ALLOW / NavSim Goal **1** | `controlled_online/controlled_verification.json` |
| Gateway 独立阻断 | **BLOCK，Goal 0** | `controlled_online/` |
| M3 在线六场景 | **36 checks / 0 failures / PASS**，`claims_checked=true` | `m3_online/merged/verification.json` |
| 正式 DDS Enforce | **7/7 PASS** | `dds_enforce/` |
| 验收器反例测试 | **21 项全部被正确拒绝** | `tests/unit/test_final_controlled_verifier.py` |
| 预检硬门槛反例 | **7 项全部中止且无后续执行** | `tests/integration/test_preflight_failfast.sh` |
| SIGTERM 顶层清理 | **7 → 0 残留，exit 130** | `tests/integration/test_sigterm_cleanup.sh` |
| 全量验收 | **`ACCEPTANCE=PASS`** | `summary.txt` |
| 证据文件计数 | **115 个独立文件**（清单 134 条索引，含 19 条 DDS 重复引用） | `FINAL_SUBMISSION_EVIDENCE_MANIFEST.json` |

证据根目录：
`artifacts/integration/final-submission-closeout/closeout-20261021T023020Z/`
（含 `SHA256SUMS.txt`，可 `sha256sum -c` 复核）
历史加固证据：`artifacts/integration/final-deliverable-2026-10-22/harden-20261020T171740Z/`
首轮失败证据：`artifacts/integration/final-deliverable-2026-10-22/harden-20261020T170655Z/`

### 0.4 两种运行模式的本质区别

| 模式 | M1 | M2 | M3 | 预期结果 |
| --- | --- | --- | --- | --- |
| 受控在线 | MOCK | MOCK | **EXTERNAL** | 合法任务可执行；越界任务被 Gateway 阻断 |
| 三真实严格 | **EXTERNAL** | **EXTERNAL** | **EXTERNAL** | 当前 M1/M2 证据不足 → F0 STRICT **BLOCK** |

**严格模式的 BLOCK 是正确安全行为，不是系统故障。**
正式 DDS Enforce 是**第三类独立实验**，运行在正式权限绑定的域上，
不能与在线模式拼成"同次安全通信链路"。

### 0.5 ON-06（Planner 超时）：两次实验的结果不同，必须按 run 判读

| run_id | 受测代码 SHA | Planner | Gateway 到达 | Gateway 决策 | NavSim Goal |
| --- | --- | --- | --- | --- | --- |
| `closeout-20261021T023020Z`（**最终封版**） | `2f3de257c9eac873093201292f6b2a9571da4f03` | `PLANNER_RESULT_TIMEOUT` | **0** | 无 | **0** |
| `harden-20261020T171740Z`（历史加固） | `ba16e7f39261bd5898a186d29561170a46c950d5` | `PLANNER_RESULT_TIMEOUT` | **1** | `ALLOW` | **1** |

在最终封版实验 `closeout-20261021T023020Z` 中，ON-06 的 Planner 返回 TIMEOUT，Gateway 审计**未记录**该请求到达，
NavigationSim **未记录**对应 Goal。在上一轮加固实验 `harden-20261020T171740Z` 中，同类场景曾出现
Planner TIMEOUT、Gateway `ALLOW` 与 Goal 1。

**两组实验表明：Planner TIMEOUT 本身不能等同于 Gateway BLOCK、任务取消或未执行**，
必须结合每次运行的原始审计与执行日志判断。

- 不得把"Gateway 无到达记录"写成 Gateway BLOCK；
- 不得把本轮 Goal 0 解释为系统已执行取消；
- 不得把历史 Goal 1 误写为本轮结果；
- 现有日志无可严格比较的时间戳，因此**不推断** Goal 是否发生在超时之后。

**`--check` ≠ 正式验收预检。**
`--check` 是诊断模式，允许 WARN，`CHECK_RESULT=PASS` 只表示列出的条件通过；
`--mode acceptance` 启用严格预检，SHA 不完整、工作树脏、ROS 未 source、
colcon 缺失、包未构建、jsonschema 缺失或有残留节点，都会直接
`PREFLIGHT_FAIL` 并非零退出。

---

## 关于 `baseline` 与 `main`（历史语境，仍然有效）

> **团队研发基线分支：`baseline`**
> 三个研究模块从 `baseline` 拉功能分支并行研发，成果经审查后合回 `baseline`。
> **`main` 不接收研究模块的直接合并。**

以下第 1 节起的内容描述的是 **baseline 研发协作语境**。
其中"模块尚未实现"等表述反映的是该历史时点的状态，
**不代表**本最终交付分支的当前能力 —— 当前能力以本节 §0 为准。

---

## 1. 项目名称与研究目标

**RosSystem** 的目标是为 ROS 2 具身智能机器人建立**跨层安全防护**：
在系统层验证通信身份与资源权限，在应用层约束任务语义，
由权威准入点对每一次候选动作做出最终放行或阻断判定，并留下可追溯的审计证据。

**安全定位**：

> **系统安全为基础，应用安全为核心，通信证据、身份权限和任务上下文相结合，
> SecurityGateway 负责最终权威准入。**

| 层次 | 内容 |
| --- | --- |
| **系统安全** | DDS 身份、通信资源权限、通信行为证据 |
| **应用安全** | 任务约束、Action 准入、越权操作阻断 |
| **跨层协同** | 通信风险、身份权限、任务风险三路建议联合 |
| **最终裁决** | SecurityGateway 依据权威 TaskPolicy 判定 |
| **执行审计** | Action 执行、拒绝与安全证据可追溯 |

**本基线不包含**：多模态感知模型、M3 动态任务状态机、任何已证明有效的在线入侵检测器。

---

## 2. 当前架构

```text
ROS 2 候选动作 / 通信上下文
                |
                v
     ModuleInputEnvelope
                |
                v
    +-------------------------+
    |  三个研究风险分析模块   |
    |  CommRiskEvidence       |
    |  IdentityTrustAssessment|
    |  TaskRiskDecision       |
    +-------------------------+
                |
                v
       team_demo.py 适配层
       契约校验 / 状态核对
       不满足条件 -> 本地阻断
                |
                v
       Planner / ROS 2 Action
                |
                v
      /rg/guarded_navigate
                |
                v
        SecurityGateway
        权威 TaskPolicy
         ALLOW / BLOCK
                |
           ALLOW only
                |
                v
         /rg/nav_execute
                |
                v
          NavigationSim

安全横向能力：
SROS 2 / DDS-Security Enforce
结构化审计与请求关联
```

### 必须理解的五条边界

1. **三个研究模块只提供建议**，不是授权。
2. **适配层负责协议与安全推进门槛**：三个模块都满足推进条件才允许提交候选请求。
3. **SecurityGateway 才是最终准入决策点**（依据权威 TaskPolicy）。
4. **DDS 资源权限 ≠ 任务语义授权**：拥有合法通信权限的节点，其动作仍可能违反任务约束。
5. **没有经过 Gateway 的 Action 不是合法执行路径**。

---

## 3. 已实现 / 未实现能力

### 已实现（有实测证据）

| 能力 | 证据 |
| --- | --- |
| ROS 2 四个基础包与 Action 主链 | `src/`；构建 PASS |
| 冻结 Action 契约 | `PatrolNavigate.action` |
| **权威准入点 SecurityGateway** | T03：三模块全放行 + 越界 → `OUT_OF_REGION`、Goal **0** |
| 下游执行与审计 | NavigationSim + 结构化审计 JSONL |
| 三份研究输出 Schema + 统一输入信封 | `docs/interfaces/schemas/`（Draft 2020-12） |
| 逐模块替换适配层 | `scripts/team_demo.py` |
| 三个可替换 Mock | `mock_modules/` |
| 成员独立容器与 ROS_DOMAIN_ID | `scripts/member_env.sh`、`container_up.sh` |
| **DDS 原生访问控制实验** | `sros2_check.py` S1–S6，**7/7 PASS**（含正向对照） |
| 进程所有权安全清理 | `tests/integration/reap_ownership_check.py`，7/7 PASS |
| 端到端验收工具 | `tests/integration/team_handoff_check.py`（T01–T15） |

### 未实现（如实声明）

| 项 | 状态 |
| --- | --- |
| 三个研究模块的**真实算法** | **尚无** —— 基线默认是 Mock |
| Jazzy 在线通信特征采集链路 | **未实现**，`RUNTIME_MONITOR: NOT_READY` |
| 有效可靠的通信入侵检测模型 | **未证明**（见 §8） |
| M3 动态任务状态机 | 独立研究分支，**未并入 baseline** |
| 分支保护 | 需仓库管理员手动配置 |

---

## 4. baseline 的用途

`baseline` 是**团队研究与集成的公共起点**：

- 三名研究成员从这里拉功能分支并行研发；
- 成果经模块验收 + 契约校验 + 审查后**合回 baseline**；
- `baseline` **保持稳定且默认安全**：默认模块配置仍是明确标记 `MOCK` 的实现。

它**不是**最终竞赛发布分支，也**不代表**三个研究算法已完成。

---

## 5. 快速开始

```bash
# 1) 获取基线
git clone https://github.com/godzwp117/RosSystem.git
cd RosSystem
git fetch origin
git switch baseline
git pull --ff-only origin baseline
git rev-parse HEAD          # 记录你这次开发所基于的完整 SHA

# 2) 创建自己的功能分支
git switch -c feature/member1-comm        # 成员一
# feature/member2-identity（成员二）
# feature/member3-taskrisk（成员三）
# feature/member4-integration（成员四）

# 3) 建立独立开发环境（一成员一容器一 Domain，只改你自己的档位）
RG_MEMBER=1 scripts/container_up.sh
scripts/check_deps.sh
scripts/build.sh
```

> **不要让多名成员共享同一个容器或同一个运行实例。**
> `RG_MEMBER` 档位：1→`rg_member1`/Domain 51、2→52、3→53、4→54。
> 显式 `RG_CONTAINER` / `ROS_DOMAIN_ID` 优先于 `RG_MEMBER`；两者冲突时**直接报错**。

完整上手流程见 **[docs/onboarding/README.md](docs/onboarding/README.md)**。

---

## 6. ROS 2 构建与测试

```bash
# 依赖（契约校验与适配层需要 jsonschema >= 4.0）
scripts/check_deps.sh

# 构建四个包
scripts/build.sh

# 契约校验（四份 Schema + 样例）
scripts/shell.sh 'cd /ws && python3 scripts/validate_team_contracts.py --all'

# Python 单元测试
scripts/run_unit_tests.sh

# 三个 Mock 能否独立运行
scripts/shell.sh 'cd /ws && python3 mock_modules/comm_risk_mock.py < /tmp/env.json'

# 端到端验收（容器内 14 项 + 宿主机 T14）
scripts/shell.sh 'cd /ws && python3 tests/integration/team_handoff_check.py --scenario T02'
python3 tests/integration/team_handoff_check.py --scenario T14

# SROS 2 Enforce 对照实验（Domain 43）
scripts/shell.sh 'cd /ws && source install/setup.bash && \
  python3 tests/integration/sros2_check.py'

# 进程所有权回归
python3 tests/integration/reap_ownership_check.py
```

### 测试口径说明（重要）

本 README **不把历史报告中的 PASS 当作当前结论**。

| 项 | 说明 |
| --- | --- |
| **实际最新代码基线** | 见 §14「版本与引用」；以 `git rev-parse HEAD` 为准 |
| **对应测试报告** | `docs/review/` 下的验收报告，均在报告中注明其审查基准 SHA |
| **测试命令** | 见本节上方 |
| **历史 vs 本轮** | 报告中的 PASS 是**该报告写作时**的实测结果；本 README 不重复声明当前全绿 |
| **历史快照** | 早期阶段的一百四十项单测等数字属**历史快照**，见 `docs/archive/` |

> **若你运行测试时发现不全通过，不得声称整个 baseline 已完全通过本轮验证。**

---

## 7. 三个模块接口与替换方法

### 协议

```text
输入：stdin  一个 ModuleInputEnvelope（JSON）
输出：stdout 一个研究输出（JSON）—— 只能有一个 JSON 对象
诊断：stderr （绝不污染 stdout）
```

### 模块与输出映射

| 模块 ID | 输出 Schema | 允许推进的状态 |
| --- | --- | --- |
| `comm_risk` | `CommRiskEvidence` | `NORMAL` |
| `identity_trust` | `IdentityTrustAssessment` | `AUTHORIZED` |
| `task_risk` | `TaskRiskDecision` | `ALLOW_RECOMMENDED` |

其余风险 / 未知 / 错误状态**一律不推进**（`UNKNOWN`、`ERROR` 不得当作允许）。

### 替换自己的模块

只改**自己那一个模块**的 `mode` 与 `command`：

```yaml
# config/team_modules.example.yaml
modules:
  comm_risk:
    mode: external                    # mock -> external
    interface: comm_risk_evidence
    command: ["python3", "path/to/your_module.py"]   # 必须是参数数组
    timeout_sec: 10
    max_stdout_bytes: 65536
```

> `command` 只能是**参数数组**。字符串形式会被适配层拒绝（会被 Shell 解释）。

### 相关工具

| 工具 | 用途 |
| --- | --- |
| `templates/member_module/` | **最小模块工程模板**（起点） |
| `scripts/check_member_module.py` | **统一模块验收脚本** |
| `scripts/team_demo.py` | 适配层（离线/在线） |
| `scripts/validate_team_contracts.py` | 契约校验 |

```bash
# 用模板起步
python3 scripts/init_member_module.py --module comm_risk --dest modules/my_comm

# 验收自己的模块
python3 scripts/check_member_module.py --module comm_risk \
  --config config/team_modules.local.yaml
```

---

## 8. 数据集与真实研究证据来源

**三类来源必须严格区分，不得拼接后宣称原生同步数据。**

### ① 公开数据集 ROSPaCe reduced → 成员一

| 项 | 值 |
| --- | --- |
| 官方合集 | https://springernature.figshare.com/collections/ROSpace_Intrusion_Detection_Dataset_for_a_ROS2-Based_Cyber-Physical_System/6924364 |
| 本地路径 | `data/ROSPaCe_reduced/` |
| 主数据集 | `ROSPaCe_reduced`，15 分片，约 **3,024.7 万条** |
| 对照 | `ROSPaCe_reduced_noperiodicity`，10 分片，约 **2,085.1 万条** |
| 特征依据 | `feature_list.xlsx`（482 条特征） |
| 每条记录 | 62 列（含标签 `attack` 与时间戳） |

**如实声明的负面结论**：

- 实验用 **49 个数值模型特征**；原始非标签字段 **61 个** —— **两者不得混用**；
- **直接在线可获取的模型特征仅 2 个**；
- 当前模型 **F1 0.1967 / Recall 0.1091**，而"恒预测攻击"简单基线 **F1 0.8235** —— **模型劣于无脑基线**；
- 漏报主因**不是阈值**：75% 样本攻击概率 < 1e-5，降阈值几乎不改善；
- 数据划分为 `FILE_DISJOINT_SPLIT`，**不足以证明跨会话泛化**；
- **`RUNTIME_MONITOR: NOT_READY`**。

> **ROSPaCe 是已选定的公开研究基准，不等于已获得具有可靠在线部署性能的检测模型。**
> 研究代码位于独立分支 `feature/rospace-dataset-adapter`，与 `baseline` 分离。
> **不得宣称已实现 Jazzy 在线入侵检测。**

### ② F0 与 SROS 2 Enforce 真实安全证据 → 成员二

来源：ROS 2 Jazzy、Fast DDS、SROS 2、DDS-Security **Enforce**、Permissions、Enclave、
**真实拒绝日志**、受控授权正反对照。

必须区分：配置层面的权限判断 / **真实 DDS 访问拒绝** / 应用层业务身份 /
ROS 2 `request_id` / Mock 自报身份。

> **不得**把字符串 `AUTHORIZED` 解释为 DDS 完成了身份认证。
> **不得**把 ROSPaCe 的攻击分类标签伪装成 DDS 身份认证结论。

### ③ TaskPolicy 与 Gateway 受控任务实验 → 成员三

来源：`config/task_policy.yaml`、F0 场景配置、合法与越权目标位置、任务 ID、
Action 请求、Gateway DecisionEvent、NavigationSim Goal。

重点验证：**节点可能拥有合法通信权限，但其候选动作仍违反当前任务约束。**
典型违规：区域越界、任务不匹配、无效目标、重复请求、频率限制、策略缺失。

> 这些数据由项目依据真实策略生成受控实验，**不得虚构为 ROSPaCe 自带的攻击标签**。

**TUM RGB-D**：`OPTIONAL / NOT_INTEGRATED`，不是任何成员的交付前置条件。

---

## 9. SROS 2 / DDS-Security

| 项 | 值 |
| --- | --- |
| 默认开发模式 | Domain **42**，未启用 DDS-Security |
| 安全实验模式 | Domain **43**，`DDS-Security Enforce` |
| Keystore | `security/keystore/`（权限 700，**已在 `.gitignore` 中，绝不可提交**） |
| 权限策略 | `security/policies/` |
| 生成脚本 | `scripts/setup_sros2.sh`（幂等） |
| 对照实验 | `tests/integration/sros2_check.py`（S1–S6） |

**已实测事实**：S3/S4 的拒绝来自 **Fast DDS 安全插件的原生访问控制报错**
（`nd_goalReply topic not found in allow rule`），**不是客户端超时**；
S3C 提供**正向对照**（授权身份成功）；S5 区分业务层拒绝与 DDS 层拒绝；
S6 验证安全配置失效时**不会静默回退**为无认证通信。

> **不得把 Enforce 实验模式与默认普通开发模式混为一谈。**
> **不得**为了通过测试而修改 DDS 权限配置或把 Enforce 降级为 Permissive。

---

## 10. 团队分工与成员指引

以 **[docs/网络安全研发分工方案 V3.docx](docs/网络安全研发分工方案%20V3.docx)** 为正式分工依据。

| 成员 | 主责 | 核心证据 | 专属指引 |
| --- | --- | --- | --- |
| 成员一 | ROS 2 通信异常分析 | ROSPaCe reduced、去周期性对照 | [成员1指引](docs/成员1-任务指引和提示词.md) |
| 成员二 | DDS 身份与资源权限安全分析 | SROS 2 Enforce、Permissions | [成员2指引](docs/成员2-任务指引和提示词.md) |
| 成员三 | 任务风险及任务语义授权研究 | TaskPolicy、Action、Gateway | [成员3指引](docs/成员3-任务指引和提示词.md) |
| 成员四 | baseline、SecurityGateway、安全集成与竞赛交付 | F0 安全链路、系统验收与审计 | 见 V3 |

每份指引**独立完整**，含源码阅读顺序、接口契约、实现里程碑、独立运行命令、
必须完成的测试、不可修改的安全边界，以及**可直接复制给大模型**的完整提示词。

---

## 11. 分支与 PR 流程

```bash
# 成员分支
feature/member1-comm        # 成员一
feature/member2-identity    # 成员二
feature/member3-taskrisk    # 成员三
feature/member4-integration # 成员四

git push -u origin feature/member1-comm
```

然后在 GitHub 创建 **Pull Request，`base` 选择 `baseline`**（**不是 `main`**）。

### 规则

- **所有研究模块 PR 的目标分支是 `baseline`。**
- **禁止**把研究模块直接提交到 `main`；**当前不将 `baseline` 合并至 `main`。**
- PR 模板见 `.github/PULL_REQUEST_TEMPLATE.md`，含算法真实性、接口、测试、安全边界清单。
- 历史悬挂 PR 已清理；今后新 PR 可在审查期间短暂保持 OPEN，
  但审查结束后**必须合并或拒绝关闭**，不得长期保留无人负责的 PR。
- **不要**为了减少开放 PR 数量而绕过审查直接推送。

### 合入门槛（摘要）

baseline 来源正确 · diff 范围合理 · 契约校验通过 · 模块验收通过 ·
必需单测通过 · 风险/UNKNOWN/ERROR 失败关闭 · 无机密材料 · 无大型原始数据 ·
不改冻结安全边界 · 真实算法或实验原型如实标记 · 至少一名授权审查人批准 ·
无未解释的关键回归。

---

## 12. 安全边界

**绝对禁止**：

- 修改 `src/rg_gateway/` 核心准入逻辑；
- 修改冻结的 `PatrolNavigate.action`；
- 修改八个冻结业务原因码；
- 修改四份公共 JSON Schema 来迁就自己的实现；
- 削弱 DDS-Security 配置（含把 Enforce 降为 Permissive）；
- 绕过 `/rg/guarded_navigate`，或直接控制 `/rg/nav_execute`；
- 把业务 `request_id` 当作 DDS 安全身份；
- 把 Mock 输出当作真实算法结果；
- 把离线数据预测当作 Jazzy 实时监测；
- 提交原始数据集、模型缓存或 Git 凭据；
- 为了通过测试加入恒真断言。

**契约状态：`PROPOSED_V1` / `1.0.0-proposed`。**
**不得擅自标记为 FROZEN。**

### 本地守卫与 CI 的边界

仓库提供本地 Git 守卫脚本：

```bash
scripts/install_git_hooks.sh    # 安装 scripts/hooks/{pre-commit,pre-push}
```

**注意**：

- 本地守卫**需要每位开发者单独安装**，不会自动分发；
- 它们**无法取代仓库端 CI**；
- 现有 CI（`.github/workflows/repo-hygiene.yml`）只做**仓库卫生与轻量结构检查**：
  它**不执行**完整 ROS 2 构建、SROS 2 Enforce 实验或 F0-T01~T15 回归；
- 因此**不得**声称仅靠仓库卫生检查已经完成全部 ROS 2 安全验证。
- `.gitignore` **不是**服务器端安全审查（对 `git add -f` 无效）。

---

## 13. 已知限制

| 限制 | 说明 |
| --- | --- |
| 三个研究模块默认是 Mock | 仅用于协作与接口联调，**不构成安全保证** |
| 通信检测无可靠在线模型 | 见 §8 ①；`DETECTOR_EFFECTIVENESS: NOT_PROVEN` |
| `RUNTIME_MONITOR: NOT_READY` | 无 Jazzy 在线特征采集全链路 |
| M3 未并入 | 独立研究资产，非基线默认功能 |
| Docker/Domain 隔离非强身份隔离 | 仅开发环境通信隔离；成员间凭证权限未分离 |
| 单机单中间件 | 现有安全结论**不覆盖**跨主机或跨 RMW 等价性 |
| 分支保护未启用 | 需仓库管理员手动配置 |
| CI 覆盖有限 | 见 §12 |
| 契约未冻结 | `E-CONTRACT` 需团队签收；`E-HANDOFF` 需其他成员独立复现 |

---

## 14. 版本与引用

| 项 | 值 |
| --- | --- |
| 团队基线分支 | `baseline` |
| 接口状态 | **`PROPOSED_V1`** |
| 契约版本 | **`1.0.0-proposed`** |
| 获取当前基线 SHA | `git rev-parse origin/baseline` |
| ROS 2 | Jazzy（容器内 Ubuntu 24.04） |
| RMW | `rmw_fastrtps_cpp` |
| 宿主 | Ubuntu 22.04（WSL2），**不在宿主安装 ROS 2** |

### 关键文档

- [研发分工方案 V3](docs/网络安全研发分工方案%20V3.docx) —— 正式分工依据
- [Baseline 交接说明](docs/team/BASELINE_HANDOFF.md)
- [Onboarding 指南](docs/onboarding/README.md)
- [接口契约与版本](docs/interfaces/CONTRACT_VERSION.md)
- [项目开发状态](docs/team/PROJECT_DEVELOPMENT_STATUS.md)
- [安全代码审查报告](docs/review/baseline_安全代码审查与整改验收报告.md)
- [历史阶段归档](docs/archive/README_阶段一二三历史版.md)

---

## 15. 竞赛复现与贡献

**赛事**：「华为杯」第五届中国研究生网络安全创新大赛 · 创意作品赛
**作品提交截止**：**2026 年 10 月 22 日**

### 复现步骤

```bash
git clone https://github.com/godzwp117/RosSystem.git
cd RosSystem
git switch baseline && git pull --ff-only origin baseline
RG_MEMBER=1 scripts/container_up.sh
scripts/check_deps.sh && scripts/build.sh
scripts/run_unit_tests.sh
scripts/shell.sh 'cd /ws && python3 scripts/validate_team_contracts.py --all'
```

### 贡献方式

1. 从 `baseline` 创建 `feature/member*-*` 分支；
2. 按对应成员指引实现真实算法；
3. 用 `scripts/check_member_module.py` 验收自己的模块；
4. 按 PR 模板填写并创建 **base = `baseline`** 的 PR；
5. 通过审查与测试门槛后合入。

**不要直接向 `main` 合并研究代码。**
