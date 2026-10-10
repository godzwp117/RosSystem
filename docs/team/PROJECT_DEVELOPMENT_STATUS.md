```text
文档类型：团队开发共享状态
适用工程：RosSystem F0
对应提交：03fcc12511501768360ca4c4673ddbb40ec9730f
接口状态：PROPOSED_V1
更新日期：2026-10-10
说明：本文只描述公共研发环境、代码能力、接口与验证状态。
```

# RosSystem 项目开发共享状态

> 本文用于让所有开发成员用一份文档准确了解项目当前状态。
> **只描述技术研发状态，不涉及个人分工、任务分配或人员评价。**
> 文中所有状态均区分「代码已实现」「仓库文档报告完成」「有可复核测试证据」
> 「本轮实际运行验证通过」「尚未验证」「环境条件不具备」。

---

## 第一章：项目概况

本项目面向具身智能机器人，研究 **ROS 2 通信可信分析与动态最小权限防护**。

系统关注的不是机器人业务功能本身，而是"谁在通信、通信行为是否异常、
该操作在当前任务下是否被允许"。核心技术要素：

| 要素 | 说明 |
| --- | --- |
| ROS 2 Jazzy | 目标运行平台 |
| DDS-Security | 通信身份认证与资源访问控制（基于 SROS 2） |
| 通信行为分析 | 观察通信资源的行为特征，判断是否异常 |
| 身份权限分析 | 判断某主体对某资源的访问是否获得授权 |
| 任务风险建议 | 判断候选操作是否符合当前任务约束 |
| 安全网关 | 对业务请求做权威的准入判定 |
| 导航仿真执行端 | 承载被允许的执行动作 |
| 结构化审计 | 记录通信、判定与执行结果，供追溯 |

**架构边界**：研究模块输出的是**分析结论与建议**，不构成授权。
最终业务操作必须经过安全网关判定。

---

## 第二章：当前代码版本

| 项 | 值 |
| --- | --- |
| 仓库 | `https://github.com/godzwp117/RosSystem` |
| 当前 F0 开发分支 | `feature/framework-f0` |
| **F0 技术状态对应提交** | **`03fcc12511501768360ca4c4673ddbb40ec9730f`**（Schema 与契约语义、校验工具、53 项契约测试） |
| F0 固定基线提交 | `c2d600dc6e43f989daeb577ed7bb29a6882e7edc` |
| M2 稳定基线 | `838f66f41821edf0421612a205d162ae8e9eb955` |
| M2 稳定标签 | `m2-secure-v1.0` |
| 接口契约状态 | **`PROPOSED_V1`**（版本 `1.0.0-proposed`） |
| F0 正式稳定标签 | **尚未发布** |

**两条独立开发线**：F0 与 M3 均从 M2 基线分出，**互不包含**。

| 开发线 | 内容 | 与 F0 的关系 |
| --- | --- | --- |
| F0（`feature/framework-f0`） | 协作框架、环境隔离、公共接口 | 本文描述对象 |
| M3（`feature/m3-dynamic-policy`） | 动态任务最小权限研究 | **不含于 F0**，F0 不依赖其状态机 |
| 证据分支（`evidence/m3`） | 脱敏后的公开验收证据 | 孤儿分支，**只读，不参与代码合并** |

> 本文的数据截至上表所列**固定提交**。请勿用浮动分支名充当版本号。
>
> **关于文档自身的提交**：本文档在技术提交之后单独加入，且不含技术内容变更。
> 文档无法在自己的内容里写出自己的提交 SHA（写入会改变该 SHA）。
> 需要知道文档所在提交时，请用：
> `git log -1 --format=%H -- docs/team/PROJECT_DEVELOPMENT_STATUS.md`
> 需要复现本文描述的技术状态时，请检出上表的**技术状态对应提交**。

---

## 第三章：当前已实现的功能

| 能力 | 状态 | 证据来源 |
| --- | --- | --- |
| ROS 2 Action 主链（请求 → 准入 → 执行） | 代码已实现，历史验证通过 | M1/M2 验收包 |
| 安全网关准入判定 | 代码已实现，历史验证通过 | M1/M2 验收包 |
| 任务策略（区域、速率、重复请求约束） | 代码已实现，历史验证通过 | M1/M2 验收包 |
| 导航仿真执行端 | 代码已实现，历史验证通过 | M1/M2 验收包 |
| 结构化审计与事件关联 | 代码已实现，历史验证通过 | M1/M2 验收包 |
| M1 可靠性机制（审计失败不放行、构建保护、超时语义） | 代码已实现，历史验证通过 | M1 验收包 |
| M2 SROS 2 强制模式（独立身份 + 最小权限） | 代码已实现，历史验证通过 | M2 验收包 |
| 容器复用前配置核对 | **本轮实际运行验证通过** | `tests/integration/env_isolation_check.py` |
| 成员实例容器与 ROS Domain 配置 | **本轮实际运行验证通过** | 同上 |
| 三个模块公共接口契约 | **本轮实际运行验证通过（技术层面）** | `tests/unit/test_team_contracts.py` |

**关于历史 PASS 数量的说明**：
历史实验的通过数量对应**各自当时的测试版本**，不代表本轮重新执行过。
- M2 验收：30/30 PASS（对应归档提交 `838f66f`；测试时版本为 `9ea929c`）
- F0 环境隔离：ENV-01~ENV-10 共 6 组用例全部通过（**本轮实际执行**）
- 公共接口契约：53 项测试通过（**本轮实际执行**）
- 全量单元测试：208 项通过（**本轮实际执行**）

**本轮未重新执行**的功能（Action 主链端到端、SROS 2 对照实验等）不在此声称"本轮已验证"。

---

## 第四章：软件结构

四个 ROS 2 包：

| 包 | 职责 |
| --- | --- |
| `rg_interfaces` | 接口定义。**冻结的** `action/PatrolNavigate.action` 在此 |
| `rg_policy` | 纯 Python 策略与事件模型（可脱离 ROS 独立单测） |
| `rg_gateway` | 安全网关：准入判定、审计、执行调用 |
| `rg_demo_nodes` | 演示节点：请求发起、执行端模拟、启动配置 |

关键位置：

| 内容 | 路径 |
| --- | --- |
| 冻结的 Action 契约 | `src/rg_interfaces/action/PatrolNavigate.action` |
| 业务原因码（**冻结，八个**） | `src/rg_policy/rg_policy/reason_codes.py` |
| 准入判定逻辑 | `src/rg_policy/rg_policy/policy_engine.py` |
| 安全策略配置 | `config/task_policy.yaml` |
| 安全网关 | `src/rg_gateway/rg_gateway/security_gateway.py` |
| 仿真执行端 | `src/rg_demo_nodes/rg_demo_nodes/` |
| 启动配置 | `src/rg_demo_nodes/launch/stack.launch.py` |
| 审计与测试 | `tests/`（单元 `unit/`、集成 `integration/`、证据 `evidence/`） |
| **公共接口（本轮新增）** | `docs/interfaces/` |
| 安全配置与权限 | `security/`（密钥库已排除出版本控制） |
| 研发过程记录 | `docs/review/`、`docs/team/`、`docs/ARCHIVE_SPEC.md` |

---

## 第五章：公共接口 v1 提案

**当前状态：`PROPOSED_V1`（已完成技术实现与校验，尚待业务确认）**

| 接口 | 用途 | Schema | 样例 |
| --- | --- | --- | --- |
| `CommRiskEvidence` | 通信行为是否异常 | `docs/interfaces/schemas/comm_risk_evidence.schema.json` | `examples/comm_normal.json` 等 3 个 |
| `IdentityTrustAssessment` | 访问是否获授权 | `docs/interfaces/schemas/identity_trust_assessment.schema.json` | `examples/identity_authorized.json` 等 3 个 |
| `TaskRiskDecision` | 候选操作是否符合任务约束 | `docs/interfaces/schemas/task_risk_decision.schema.json` | `examples/task_allow_recommended.json` 等 3 个 |
| `ModuleInputEnvelope` | 三模块统一输入信封 | `docs/interfaces/schemas/module_input.schema.json` | `examples/module_input_valid.json` |

**输入输出关系**：适配层构造输入信封 → 通过 stdin 传给模块 →
模块通过 stdout 返回对应输出 → 适配层校验一致性与版本 → 交给现有请求发起方 →
经安全网关判定 → 执行端。

**状态枚举**：

| 接口 | 取值 |
| --- | --- |
| `CommRiskEvidence` | `NORMAL` / `SUSPICIOUS` / `UNKNOWN` / `ERROR` |
| `IdentityTrustAssessment` | `AUTHORIZED` / `DENIED` / `UNKNOWN` / `ERROR` |
| `TaskRiskDecision` | `ALLOW_RECOMMENDED` / `BLOCK_RECOMMENDED` / `UNKNOWN` / `ERROR` |

**错误处理**：`UNKNOWN`（证据不足）与 `ERROR`（模块失败）**默认都不得推动执行**。
字段缺失、版本不兼容、非法 JSON、超时一律拒绝。

**可信来源限制**：

- `producer` 是自报信息，**不是安全认证凭据**；
- `request_id` 是业务关联标识，**不代表安全身份**；
- `evidence_refs[].kind` 必须标注来源级别（`MOCK` / `RUNTIME_LOG` /
  `PERMISSION_FILE_ANALYSIS` / `CONTROLLED_SECURITY_EXPERIMENT` / `UNIT_TEST` / `UNKNOWN`）；
- 身份证据分四级强度，`CLIENT_ASSERTED`（客户端自报）**不可作为认证依据**；
- `candidate_action.action_resource` 由 Schema 固定为 `/rg/guarded_navigate`，
  上游**无法**把候选操作指向执行端。

**版本状态**：`1.0.0-proposed`，契约状态 `PROPOSED_V1`。
版本管理、变更规则与八条强制安全边界见 `docs/interfaces/CONTRACT_VERSION.md`。

---

## 第六章：开发与运行环境

| 项 | 值 |
| --- | --- |
| 宿主 | Ubuntu 22.04（WSL2） |
| ROS 2 环境 | **Docker 容器**（ROS 2 Jazzy 只打包给 Ubuntu 24.04，故不在宿主安装） |
| 默认容器镜像 | `ros:jazzy` |
| 中间件实现（RMW） | `rmw_fastrtps_cpp` |
| 工作区挂载 | 宿主仓库 → 容器内 `/ws` |
| 默认 ROS Domain | `42`（容器创建时固定） |
| 安全测试 Domain | `43`（保留独立用途） |
| 成员开发 Domain 约定 | `51`–`54` |

### 6.1 环境变量（均经代码核对）

| 变量 | 作用 | 默认值 |
| --- | --- | --- |
| `RG_MEMBER` | 选择成员档位，一次性设定容器名与开发 Domain（`1`–`4`） | 未设置 |
| `RG_CONTAINER` | 容器名。显式设置时优先于 `RG_MEMBER` | `rg_jazzy` |
| `ROS_DOMAIN_ID` | 通信域。显式设置时优先于 `RG_MEMBER` | 容器创建时的值 |
| `RG_CONTAINER_WS` | 容器内挂载点 | `/ws` |
| `RG_IMAGE` | 容器镜像 | `ros:jazzy` |
| `RG_RMW` | 中间件实现 | `rmw_fastrtps_cpp` |
| `RG_MODE` | 强制运行模式 `native` / `container` | 自动探测 |
| `RG_LAUNCH_PKG` / `RG_LAUNCH_FILE` | 启动配置的包与文件 | 见 `scripts/start_system.sh` |

> **注意**：`RG_MEMBER` 与显式的 `RG_CONTAINER` / `ROS_DOMAIN_ID` **冲突时会直接报错**，
> 不做猜测——避免"以为在自己的环境里"却实际用了别人的容器或通信域。
> 容器创建时固化的环境变量**不会**因宿主后来修改变量而更新。

### 6.2 成员档位（开发约定）

| 成员档位 | 容器名 | 开发 Domain |
| --- | --- | --- |
| `RG_MEMBER=1` | `rg_member1` | 51 |
| `RG_MEMBER=2` | `rg_member2` | 52 |
| `RG_MEMBER=3` | `rg_member3` | 53 |
| `RG_MEMBER=4` | `rg_member4` | 54 |

> **这些只是开发约定，不是 DDS 安全身份，也不提供密码学隔离。**
> ROS Domain 只做发现隔离。真正的身份与授权由安全配置承担。
> 单机共享同一容器的场景**不能**声称实现了成员间的强身份隔离。

### 6.3 两种运行模式

| 模式 | 说明 |
| --- | --- |
| **普通开发模式** | 不启用 DDS-Security，用于日常开发与接口联调 |
| **SROS 2 Enforce 模式** | 启用安全通信（独立身份 + 最小权限），用于安全实验；使用独立 Domain |

### 6.4 日志与证据位置

| 内容 | 路径 |
| --- | --- |
| 构建/运行日志 | `logs/` |
| 集成测试证据 | `tests/evidence/<run_id>/` |
| 验收归档 | `artifacts/acceptance/` |
| 开发共享文档 | `docs/team/` |
| 阶段验收报告 | `docs/review/` |

---

## 第七章：如何验证当前框架

### 7.1 构建（在线，需 Docker）

```bash
scripts/container_up.sh          # 确保容器就绪（复用前会核对配置）
scripts/build.sh                 # 构建四个包，输出 BUILD RESULT: PASS
```

**实测结果**：`Summary: 4 packages finished`，`BUILD RESULT: PASS`。

### 7.2 单元测试（在线，需 Docker）

```bash
scripts/run_unit_tests.sh
```

**实测结果**：`208 passed`，`UNIT TEST RESULT: PASS`。

> **重要**：全量单测**必须先构建并 source `install/setup.bash`**。
> 上表脚本会自动处理。若手工执行 `pytest tests/unit` 而**未** source，
> 会因 `ModuleNotFoundError: No module named 'rg_gateway'` 在**收集阶段**中断，
> 表现为 `1 error`（不是测试失败，而是根本没跑起来）。

### 7.3 接口契约校验（离线，仅需 `jsonschema >= 4.0`）

```bash
scripts/shell.sh "python3 scripts/validate_team_contracts.py --all"
```

**实测结果**：`CONTRACT VALIDATION: PASS`。

契约测试本身**不依赖 ROS 环境**，也可直接运行：

```bash
python3 -m pytest tests/unit/test_team_contracts.py -q     # 53 passed
```

单个文件校验：

```bash
scripts/shell.sh "python3 scripts/validate_team_contracts.py \
  --doc docs/interfaces/examples/comm_normal.json --schema comm_risk_evidence"
```

### 7.4 现有基础链路测试（在线）

```bash
scripts/run_all.sh               # 全量集成测试
scripts/start_system.sh          # 统一启动（含就绪探测）
```

### 7.5 查看 Action Result 与审计记录

| 目标 | 方式 |
| --- | --- |
| 查看启动与判定日志 | `logs/` 下的对应日志文件 |
| 查看结构化审计 | `tests/evidence/<run_id>/` 下的事件与日志 |
| 查看历史验收归档 | `artifacts/acceptance/`（含 `README.md` 说明） |

**离线测试与在线测试的区分**：

| 类别 | 是否需要 Docker/ROS 2 |
| --- | --- |
| 接口契约校验、契约单元测试 | **不需要** |
| 其余单元测试、集成测试、构建、运行 | **需要** |

### 7.6 在容器内执行任意命令

```bash
scripts/shell.sh '<command>'      # 非交互执行，自动 source ROS 与 install/
scripts/shell.sh                  # 有终端时进入交互式 shell
```

---

## 第八章：当前尚未完成的能力

| 能力 | 状态 | 说明 |
| --- | --- | --- |
| 可替换 Mock 模块 | **已完成** | `mock_modules/` 三个 Mock，支持各自 4 个状态与受控故障注入 |
| 统一适配层 | **已完成** | `scripts/team_demo.py`：严格解析、跨模块一致性、失败关闭、进程组生命周期管理；默认离线，`--online` 才提交 Planner |
| 全链路联调（F0-T01~T15） | **已完成（T14/T15 已补齐）** | 见 `docs/review/F0_D2_真实Action联调与GAP05验收报告.md`；T01~T15 均有真实证据 |
| 独立交接复现 | **尚未完成** | 需由另一名开发者在干净环境独立走通并记录 |
| 新成员环境指南 | 部分完成 | 本文档与 `README.md` 提供命令；独立完整指南待补 |
| F0 公共契约冻结 | **待确认** | 需相关开发者确认 `CONTRACT_VERSION.md` 第 8 节 Q1–Q8 |
| M3 动态策略状态机 | **不在 F0 内** | F0 不依赖它；相关字段为可选扩展 |
| 研究素材归集目录 | 尚未建立 | 样本与标签口径待定义 |
| CI 构建校验 | 尚未建立 | 当前 CI 只做静态校验与仓库卫生 |
| 性能指标（时延、切换耗时） | **未测量** | 属后续阶段 |

**需要专项验证的安全限制**：

1. 单机共享容器下，成员之间**无法**声明强身份隔离；
2. `policy_digest` 类摘要**不是数字签名**，不能抵御有写权限的主体；
3. 安全结论目前**只覆盖单机单容器与单一中间件实现**，跨主机等价性未验证；
4. 状态文件与审计记录之间**没有跨文件原子性**。

**不得把规划中的能力写成已上线能力。**

---

## 第九章：后续模块接入流程（计划中）

> **本章为计划中的流程。** 本轮未开发 Mock 或适配层，
> 因此**不存在**可直接运行的接入命令。以下步骤在相应组件开发完成后生效。

1. 阅读 `docs/interfaces/README.md` 与三个输出 Schema，确认字段与状态语义；
2. 用 `examples/` 下的合法与非法样例验证自己的校验流程；
3. 实现约定的进程级 JSON 输入输出（stdin 单对象 / stdout 单对象 / stderr 诊断）；
4. 在模块配置中声明模块实现（模拟或真实）——**该配置机制尚未实现**；
5. 执行接口契约测试，确认输出符合 Schema；
6. 执行全链路联调，确认请求经安全网关到达执行端；
7. 获取并核对安全网关判定与执行端的实际记录（**不能只看调用方输出**）；
8. 保留结构化证据：提交 SHA、环境变量、模块身份、Schema 版本、
   实际命令、返回码、模块输出、网关判定、执行端记录。

**契约变更**：任何字段增删都必须走 `CONTRACT_VERSION.md` 第 4 节的变更流程，
并更新样例与测试。

---

## 第十章：已知限制与下一阶段工作

| # | 事项 | 性质 |
| --- | --- | --- |
| 1 | 公共契约仍待确认（`PROPOSED_V1`） | 流程性，需相关开发者确认 |
| 2 | Mock 模块与可替换适配层待开发 | 技术性，下一阶段主体工作 |
| 3 | 替换测试待开发（需与 Mock 不同实现的测试替身） | 技术性 |
| 4 | 跨 Domain 发现探测：已改为进程内 rclpy 直接探测，不再依赖共享 daemon 缓存 （`tests/integration/domain_ready_probe.py`）。原始误报在本环境未能复现 | 已缓解 |
| 5 | SROS 2 密钥与容器权限边界：共享容器内成员可读彼此私钥 | 技术性，需按成员隔离目录权限并如实声明适用范围 |
| 6 | F0 与 M3 尚未合流 | 架构决策，需明确收敛方式 |
| 7 | 环境依赖：宿主 `jsonschema` 版本过低（3.2.0），无法校验 Draft 2020-12 | 环境性，契约校验须在容器内进行 |
| 8 | `date-time` 格式检查依赖自实现（环境缺 `rfc3339-validator`） | 环境性，已用标准库实现并自检 |
| 9 | 研究素材目录与 CI 构建校验待增强 | 工程性 |
| 10 | 性能类指标未采集 | 研究性，不阻塞当前阶段 |

---

## 附：本文档的核对方式

本文档中的路径与命令均已核对：

- 所有路径在仓库中实际存在（未实现的目录明确标注为"尚未完成"，不提供链接）；
- 所有命令均已实际运行或最小参数验证（`build.sh`、`run_unit_tests.sh`、
  `validate_team_contracts.py`、`shell.sh` 均实测通过）；
- 接口状态在 `docs/interfaces/README.md`、`CONTRACT_VERSION.md`、
  `docs/review/F0_C阶段接口建设验收报告.md` 与本文四处一致，均为 `PROPOSED_V1`。

**若发现本文与代码不一致，以代码为准，并请更新本文。**
