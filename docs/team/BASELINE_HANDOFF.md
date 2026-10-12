# RosSystem 团队研发基线（`baseline`）

> **统一约定（全团队一致）**
>
> ```bash
> git clone https://github.com/godzwp117/RosSystem.git
> cd RosSystem
> git fetch origin
> git switch baseline
> git pull --ff-only origin baseline
> git rev-parse HEAD          # 记录你这次开发所基于的完整 SHA
> ```
>
> 成员分支：`feature/member1-comm`、`feature/member2-identity`、
> `feature/member3-taskrisk`、`feature/member4-integration`。
>
> **Pull Request 的 `base` 一律选 `baseline`。**
> **不要**把研究模块提交到 `main`；当前也不把 `baseline` 合并至 `main`。
>
> **关于固定 SHA**：文档中出现的历史 SHA（如 `b031d4ba…`）是
> **历史教学参考提交**，不是当前分支 HEAD。开发时请以上面
> `git rev-parse HEAD` 得到的**当次实际 SHA** 为准并记录下来。


> 本分支是 **RosSystem 团队的公共研发基线**：一个可构建、可运行、可交接的稳定起点。
>
> **它不是最终竞赛发布分支，也不代表三个研究算法已经完成。**

---

## 1. 版本信息

| 项 | 值 |
| --- | --- |
| 分支名 | `baseline` |
| 用途 | 团队并行研发的稳定起点（成员一至成员四各自从此分支拉功能分支） |
| 来源分支 | `feature/framework-f0` |
| **F0 来源 SHA** | `ebfe263530d10a746c172367f9d96d2f9dc5d7d4` |
| 如何获取本分支发布 SHA | `git rev-parse HEAD`（或 `git ls-remote --heads origin baseline`） |
| 发布日期 | 2026-10-12 |
| ROS 2 | Jazzy（容器内 Ubuntu 24.04） |
| RMW | `rmw_fastrtps_cpp` |
| 宿主 | Ubuntu 22.04（WSL2），**不在宿主安装 ROS 2** |
| 默认 ROS_DOMAIN_ID | 42（安全实验 43；成员开发 51~54） |

> **为什么本文件不写自己的提交 SHA**：写入 SHA 会改变提交内容，导致 SHA 再次变化。
> 最终 SHA 请在发布消息、GitHub PR 或外部交接记录中查阅。

### 实际测试结果（F0 来源提交上实测）

| 项目 | 结果 |
| --- | --- |
| F0 Python 单元测试 | **295 passed / PASS** |
| 契约校验（四份 Schema + 样例） | **PASS** |
| ROS 2 四包构建 | **PASS** |
| F0-T01~T15 全量验收 | **15 / 15 PASS** |
| SROS 2 Enforce 对照实验（Domain 43） | **7 / 7 PASS**（含正向对照） |
| 依赖检查 `scripts/check_deps.sh` | **PASS** |

---

## 2. 研发说明（必读）

### 接口与契约状态

| 项 | 状态 |
| --- | --- |
| 接口状态 | **`PROPOSED_V1`** |
| 契约版本 | **`1.0.0-proposed`** |
| 公共 Schema | 已实现**技术校验**（Draft 2020-12，53 项契约测试） |
| 正式业务冻结 | **仍需相关成员确认**（`CONTRACT_VERSION.md` §7.5 的 Q1–Q8 尚未获得确认） |

**两条必须明确的边界：**

- **`E-CONTRACT` 不会自动变为 PASS。** 自动化测试通过 ≠ 契约冻结。
  在相关成员逐条确认 Q1–Q8 之前，契约保持 `PROPOSED_V1`。
- **`E-HANDOFF` 不会自动变为 PASS。** 在**至少一名其他成员独立复现**之前，
  团队交接门槛保持 BLOCKED。

### 研究模块状态

| 模块 | 当前默认实现 | 说明 |
| --- | --- | --- |
| 通信行为风险分析 | **Mock** | `mock_modules/comm_risk_mock.py` |
| DDS 身份与权限安全分析 | **Mock** | `mock_modules/identity_trust_mock.py` |
| 任务风险推理 | **Mock** | `mock_modules/task_risk_mock.py` |

**Mock 的定位：仅用于协作与接口联调**，输出标记 `producer.source = MOCK` 与
`evidence_refs[].kind = MOCK`。**Mock 不是安全算法，不构成任何安全保证。**

- 真实研究算法应从**各自的功能分支**替换，做法见下方"替换自己的模块"。
- **ROSPaCe 通信检测模块属于实验功能**，不包含在本基线内。
  研究分支：`feature/rospace-dataset-adapter`。其当前状态：
  * 已完成数据审计、双版本对照、特征可获取性矩阵与 F0 离线适配；
  * **检测能力尚未得到可靠实用性证明**（详见该分支的
    `docs/review/ROSPaCe_可信评测与接口缺陷修复报告.md`）；
  * `RUNTIME_MONITOR: NOT_READY`（不具备 ROS 2 实时特征采集链路）。
- **M3 动态任务状态机不包含在 F0 baseline 中**（`task_phase` / `policy_epoch` /
  `policy_digest` 均为可选字段）。

### 替换自己的模块

只修改**自己那一个模块**的 `mode` 与 `command`，不需要改动其他模块或 Gateway：

```yaml
# config/team_modules.example.yaml
modules:
  comm_risk:
    mode: external                       # mock -> external
    interface: comm_risk_evidence
    command: ["python3", "path/to/your_module.py"]   # 必须是参数数组
    timeout_sec: 10
    max_stdout_bytes: 65536
```

> `command` 只能是**参数数组**。字符串形式会被适配层拒绝（会被 Shell 解释）。

---

## 3. 安全边界（必须理解，不可误读）

1. **三个研究模块的输出只是建议。** 它们不构成授权。
2. **只有三个模块都满足推进条件**，适配层才允许向 Gateway 提交候选请求
   （`READY_FOR_GATEWAY_SUBMISSION`）。
3. **SecurityGateway 保留最终权威准入。** 已实测：三个模块全部建议放行 +
   目标越界时，Gateway 仍以 `OUT_OF_REGION` 阻断，下游 Goal 数为 0。
4. **DDS 身份权限独立于业务 `request_id`。** 业务标识**不是** DDS 安全身份。
5. **禁止绕过 `/rg/guarded_navigate`。**
6. **不允许直接控制 `/rg/nav_execute`** —— 该接口只应由 Gateway 调用。
7. **`UNKNOWN` 与 `ERROR` 不能当作允许。** 未知状态一律不得推进执行。
8. **Mock 输出不得作为真实安全证据。** 也不得把 Mock 的自报身份当作认证结果。

---

## 4. 新成员使用命令

### 获取基线

```bash
git clone https://github.com/godzwp117/RosSystem.git
cd RosSystem

git switch baseline
git pull --ff-only origin baseline
```

### 从基线创建自己的开发分支

```bash
# 成员一：通信行为风险分析
git switch -c feature/member1-comm

# 成员二：DDS 身份与权限安全分析
git switch -c feature/member2-identity

# 成员三：任务风险推理
git switch -c feature/member3-taskrisk

# 成员四：安全框架维护与模块集成
git switch -c feature/member4-integration
```

### 建立自己的运行环境（**每名成员独立**）

```bash
# 成员一至四分别使用 1/2/3/4 档位：一成员一容器一开发 Domain
RG_MEMBER=1 scripts/container_up.sh

# 检查依赖（契约校验与适配层需要 jsonschema >= 4.0）
scripts/check_deps.sh

# 编译
scripts/build.sh
```

> **不要让多名成员共享同一个容器或同一个运行实例。**
> 成员档位与 Domain 的对应关系（`RG_MEMBER` → 容器名 / Domain）：
> 1→`rg_member1`/51、2→`rg_member2`/52、3→`rg_member3`/53、4→`rg_member4`/54。
> 显式的 `RG_CONTAINER` / `ROS_DOMAIN_ID` 优先于 `RG_MEMBER`；
> 两者同时给出且不一致时会**直接报错**，不会猜测。

### 完整上手流程

见 `docs/onboarding/README.md`（17 步可复制指南 + 故障排查索引 + 安全边界）。

---

## 5. 本基线包含什么

| 内容 | 位置 |
| --- | --- |
| ROS 2 四个基础包 | `src/rg_interfaces`、`src/rg_policy`、`src/rg_gateway`、`src/rg_demo_nodes` |
| 冻结的 Action 契约 | `src/rg_interfaces/action/PatrolNavigate.action` |
| 权威准入点 | `src/rg_gateway/`（SecurityGateway） |
| 下游执行模拟 | `src/rg_demo_nodes/`（NavigationSim） |
| SROS 2 / DDS-Security 基础能力 | `scripts/setup_sros2.sh`、`security/` |
| 四份公共 JSON Schema | `docs/interfaces/schemas/` |
| 三个可替换 Mock | `mock_modules/` |
| 模块适配层 | `scripts/team_demo.py` |
| 模块配置样例 | `config/team_modules.example.yaml` |
| 独立成员开发环境 | `scripts/member_env.sh`、`scripts/container_up.sh` |
| Onboarding 指南 | `docs/onboarding/README.md` |
| F0-T01~T15 验收工具 | `tests/integration/team_handoff_check.py` |
| 精确进程清理与 T14 安全整改 | `tests/integration/scenario_runner.py` |

**不包含**：ROSPaCe 研究模块、模型与训练产物、M3 动态状态机、原始数据集。

---

## 6. 协作约定

- 各成员在自己的功能分支开发，通过 **Pull Request** 合入 `baseline`。
- **不要直接修改共享基线。**
- 不得修改：冻结的 `PatrolNavigate.action`、八个 Gateway 业务原因码、
  `src/rg_gateway/` 核心准入逻辑、DDS 权限配置。
- 本地归档文件 `gitlog.md` **不得上传**。
- 大体积本地物（数据集、模型、训练缓存、研究用虚拟环境）已在 `.gitignore` 中排除，
  请勿用 `git add -f` 强行加入。

---

## 7. 相关分支

```text
main                                M2 稳定历史版本（本基线不基于它）
  └─ feature/framework-f0           F0 研发线（本基线的来源）
        ├─ baseline                 ← 本分支，团队稳定起点
        │     ├─ feature/member1-comm
        │     ├─ feature/member2-identity
        │     ├─ feature/member3-taskrisk
        │     └─ feature/member4-integration
        └─ feature/rospace-dataset-adapter    ROSPaCe 研究线（实验性，非默认依赖）
```

ROSPaCe 研究线允许持续实验，**不必为了追赶模型指标频繁修改团队基线**。
正式参赛版本后续另行创建（例如 `release/competition-2026`），当前不创建发布标签。
