# 更新日志（CHANGELOG）

本文件记录**每一次项目更新**：改了哪些文件、解决了哪些问题、又暴露了哪些问题。

## 使用约定

1. 每次更新**追加一条**记录，**新的在上面**（倒序），不要改写历史条目。
2. 每条记录必须包含四个小节：`变更文件` / `解决的问题` / `暴露的问题` / `验证`。
3. `变更文件` 要能对应到具体路径；新增、修改、删除分开写。
4. **只写实际发生的事**：未运行的测试、未验证的结论一律写进"暴露的问题/未验证"，
   不得因为"代码看起来对"就记为已解决。
5. `暴露的问题` 包括两类：产品/架构层面的遗留风险，以及**验证过程中发现的
   测试脚手架自身的缺陷**（后者单列，避免与产品问题混淆）。
6. 若解决了历史条目中遗留的问题，在该问题后标注 `→ 已由 <条目号> 解决`。

### 新增条目的模板

```markdown
## U<n> · YYYY-MM-DD · <一句话标题>

**背景**：为什么要做这次更新。

### 变更文件
| 类型 | 路径 | 说明 |
| --- | --- | --- |
| 新增 | `path/to/file` | ... |
| 修改 | `path/to/file` | ... |

### 解决的问题
- <问题现象/根因> → <怎么解决的>（<验证方式>）

### 暴露的问题
- <问题>（影响面 / 当前处置）

### 验证
- 命令 / 返回码 / 结果 / 日志位置
```

---

## U6 · 2026-10-09 · M2：真实 SROS 2 / DDS-Security Enforce 集成与对照实验

**背景**：在既有真实 ROS 2 Action 系统上启用 DDS-Security，把"基础通信资源授权"与
"Gateway 的任务级策略判断"叠加成可验证的双层边界。不重写业务主链、不引入第二套生命周期框架。

**关联 Git SHA**：`9234d0c`（主体）、`03d44db`（证据导出器修复）
**证据包**：`artifacts/acceptance/exports/m2_sros2_enforce/`（`manifest.json` / `security_results.json` / `file_hashes.json` + tar.gz）

### 变更文件

| 类型 | 路径 | 说明 |
| --- | --- | --- |
| 新增 | `security/policies/minimal_permissions.xml` | 5 个 enclave 的最小权限策略（零注释，原因见下） |
| 新增 | `security/policies/README.md` | 策略设计、资源映射方向、sros2 工具链陷阱 |
| 新增 | `scripts/setup_sros2.sh` | 生成 keystore/enclave；预检策略、生成后独立复核、收紧权限 |
| 新增 | `scripts/verify_sros2_permissions.py` | 独立复核 permissions.xml，捕获静默宽松回退 |
| 新增 | `tests/integration/sros2_check.py` | S1–S6 对照实验（含正向对照 S3C） |
| 新增 | `tests/integration/rogue_action_client.py` | 受控越权测试客户端（实验仪器，非产品组件） |
| 修改 | `security/README.md` | 改写为 M2 实况：能力、运行方式、限制与风险 |
| 修改 | `tests/unit/test_interface_contract.py` | 密钥检查改为"未被 git 跟踪 + 仅限排除目录 + 排除规则真实生效" |
| 修改 | `scripts/export_acceptance.py` | `--security-summary` 路由；状态键兼容 `result`/`status`；汇总计入安全场景 |
| 未改动 | `src/**`、`config/**`、`scripts/start_system.sh`（854 行） | 业务主链与统一启动器保持不变 |

### 解决的问题

1. **Agent 的"安全已启用"不能只看开关** → 为 4 个业务角色各建**独立 enclave**
   （独立证书/私钥），并新增 `/unauthorized` 受控无授权身份；逐进程用
   `ROS_SECURITY_ENCLAVE_OVERRIDE` 指定身份，**不使用全局 enclave**。
2. **Action 的底层资源不能凭记忆写** → 先用 `ros2 security generate_policy` 对**真实 ROS 图**
   采集，得到 Jazzy 的实际展开：`_action/{send_goal,cancel_goal,get_result}`（服务）与
   `_action/{status,feedback}`（topic），再据此书写策略。
3. **sros2 会静默回退到"全开"**（本次最重要的发现）→ 实测：策略文件含 XML 注释时
   `generate_artifacts` 报 `failed to validate namespace`，**但此前已写出默认策略的
   `permissions.xml`（`rt/*`、`rq/*Request`、`rr/*Reply`，整个 domain 全开）**。
   处置：策略文件零注释 + `setup_sros2.sh` 预检 + `verify_sros2_permissions.py` 独立复核
   （出现宽松特征即失败）。
4. **节点私有参数服务的方向写错会导致节点起不来** → `/planner` 的 `~/describe_parameters`
   等误置于 `request`（客户端）一侧，实测报
   `[SECURITY Error] rq/planner_node/describe_parametersRequest topic not found in allow rule`
   并抛 `RCLError: failed to create service`。修正为 `reply`（该节点是服务端）。
5. **"客户端超时"不足以证明 DDS 权限生效** → 增设**正向对照 S3C**：同一客户端、同一时间窗口、
   以 `/gateway`（被授权）身份直连 `/rg/nav_execute` **成功**；而 `/planner`、`/unauthorized`
   身份在**创建 action client 的 DDS 端点时**即被拒绝
   （`rr/rg/nav_execute/_action/send_goalReply topic not found in allow rule`）。
   拒绝因此可归因到 DDS 访问控制层，而非"服务端没起来/客户端有 bug"。
6. **安全模式与普通模式互相污染** → 安全模式固定使用 **domain 43**，普通模式保持 **42**，
   两者不共用进程、环境变量或 ros2 daemon 缓存。
7. **密钥检查判据过时** → M2 后磁盘上必然存在 `.pem`，原测试"磁盘不得有 .pem"会误报。
   改为校验"未被 git 跟踪 + 只允许出现在 `security/keystore|enclaves` + `.gitignore`
   规则真实生效（`git check-ignore` 验证）"，比原来更严格。

### 暴露的问题

1. **sros2 0.13.6 不回退失败**：策略非法仍产出可用的（全开的）权限文件。
   工具链层面的缺陷，本项目只能用"生成前预检 + 生成后复核"两头夹住；
   若换用其他 RMW/工具链需重新评估。
2. **私钥明文落盘**：`security/keystore/private/*.key.pem` 未加密，权限已收紧至 700/go-rwx，
   但能读该目录的进程即可冒充身份；生产需文件系统加密或 HSM。
3. **结论仅覆盖本机单容器 + `rmw_fastrtps_cpp` + domain 43**：跨主机/跨 RMW/跨 DDS 实现
   的等价性**未验证**。
4. **未为 ros2 CLI 分配运维身份**：安全模式下 `ros2 action list` 等观测手段需要额外 enclave，
   因此本阶段断言全部基于文件证据（JSONL），未使用图查询。
5. **未启用证书吊销/轮换**：CA 与身份证书有效期 10 年，无 CRL 流程。
6. **`/unauthorized` 仍被授予发现类基本功**（`ros_discovery_info`、`rosout`、参数服务）：
   这是刻意的——让它作为"能正常运行的 ROS 节点"却**完全无法触碰业务资源**，
   从而使拒绝可明确归因到业务资源的访问控制，而不是"节点根本起不来"。
7. 首次尝试时因策略注释与参数服务方向两处问题连续失败 2 轮；两处都已定位到具体
   报错行并修复，**未把失败轮次计入通过**。

### 实际测试

| 场景 | 内容 | 结果 |
| --- | --- | --- |
| S1 | 普通模式（domain 42）A 区请求 | PASS：ALLOW，下游 1 条 Goal |
| S2 | Enforce（domain 43）A 区请求 | PASS：Planner→Gateway→NavigationSim 完整成功，下游 1 条 |
| S3 | Enforce 下 **Planner 身份**直连 `/rg/nav_execute` | PASS：DDS 拒绝（`not found in allow rule`），下游 0 条 |
| S3C | 正向对照：**`/gateway` 身份**直连同一资源 | PASS：成功，下游 1 条（证明链路与客户端可用） |
| S4 | Enforce 下 `/unauthorized` 身份直连 | PASS：DDS 拒绝，下游 0 条 |
| S5 | Enforce 下 B 区越界（身份合法） | PASS：TaskPolicy 阻断 `OUT_OF_REGION`，下游 0 条 |
| S6 | Enforce 下凭证缺失（keystore 不存在） | PASS：`INIT_FAILED` + `SECURITY ERROR`，未静默回退，下游 0 条 |
| 权限复核 | `verify_sros2_permissions.py` | PASS：5 个 enclave 均无 `rt/*` 等宽松通配 |
| 全量回归 | 见下表 | 30/30 PASS |

---

## U5 · 2026-10-09 · M1：可靠性加固与 P0 稳定冻结

**背景**：在冻结 P0 之前修掉三处可靠性缺陷：审计写入失败仍可能放行、构建脚本会打断
运行中的实例、`EXECUTION_TIMEOUT` 语义可能被误读为"下游已停止"。

**关联 Git SHA**：`e13199a`
**标签**：`p0-before-m1-20261009` → `59fad86`（修改前快照）、`p0-stable-v1.0` → `e13199a`
**证据包**：`artifacts/acceptance/exports/m1_stable/`（23/23 PASS）

### 变更文件

| 类型 | 路径 | 说明 |
| --- | --- | --- |
| 修改 | `src/rg_gateway/rg_gateway/security_gateway.py` | B2 审计 fail-closed；B4 超时/取消语义；新增 `audit_fault_injection`（仅测试用） |
| 修改 | `scripts/build.sh` | B3 构建前状态检查，运行中则 exit 4 拒绝 |
| 修改 | `scripts/lib.sh` | 新增运行中实例检测；`rg_reap_stragglers` 默认不再清理运行中实例 |
| 新增 | `tests/unit/test_gateway_audit_safety.py` | 15 项：故障注入只能导致失败、两类审计故障计数与文案 |
| 新增 | `tests/integration/reliability_check.py` | R1–R4、R7 故障注入 |
| 新增 | `tests/integration/build_guard_check.py` | R5、R6 构建保护（宿主机执行） |

### 解决的问题

1. **DecisionEvent 写入失败仍会创建下游 Goal（真实缺陷）** → 原代码只检查了
   `RosCommEvent` 的写入结果（第 257 行），`DecisionEvent` 的返回值被丢弃。
   现在执行前任一事件未落库即 `BLOCK(AUDIT_UNAVAILABLE)`，不再 `_forward()`。
   验证：R2 用 `/dev/full` 制造**真实 ENOSPC**；R3 注入 Decision 写失败；两者下游 Goal 均为 0。
2. **执行后审计失败不得被说成"下游没执行"** → 区分 `pre_execution` / `post_execution`
   两类审计故障并分别计数；R4 证实在 ExecutionEvent 写失败时仍如实回传 `EXECUTED`，
   且日志明写"动作不可撤销、不得解读为下游未执行"。
3. **构建会杀掉运行中的实例** → `build.sh` 改为先检查，发现运行中受管理实例即
   `exit 4` 拒绝；R5 证实在拒绝后实例节点 PID 完全不变，R6 证实空闲时构建仍成功。
4. **超时语义含糊** → 超时不再可能被读成"下游已停止"：显式给出
   `UNKNOWN_MAY_STILL_BE_RUNNING` / `NOT_CONFIRMED_CREATED` 与
   `REQUESTED_UNCONFIRMED`（取消待确认），并输出 `EXECUTION_TIMEOUT_STATE` 机器可读日志
   与 `execution_may_continue=true`。

### 暴露的问题

1. **故障注入参数属于产品代码**：为可测试性在网关增加了 `audit_fault_injection`。
   它**只能制造失败**（无任何放行分支）且默认关闭、取值非法即拒绝启动，但仍需在
   后续评审中确认是否接受这种形态，或改为依赖注入。
2. **`_finish_failure` 的 ExecutionEvent 写失败仍无补写机制**：审计链会缺口，
   仅靠 rosout 日志承载。这是刻意的（同一 event_id 只允许一条判定/执行记录），
   但意味着审计链完整性依赖日志通道。
3. **构建保护依赖实例记录文件**：若实例由其他方式启动（不经 `start_system.sh`），
   只能靠进程扫描兜底；跨容器/跨 domain 的实例无法检测。
4. **未做并发压测**：故障注入均为单请求串行验证。

### 实际测试

| 用例 | 内容 | 结果 |
| --- | --- | --- |
| R1 | 正常审计 → ALLOW，三事件齐全，下游 1 条 | PASS |
| R2 | `RosCommEvent` 写失败（真实 `/dev/full` ENOSPC） | PASS：拒绝，下游 0 条 |
| R3 | `DecisionEvent` 写失败（注入） | PASS：拒绝，下游 0 条 |
| R4 | `ExecutionEvent` 写失败（执行后） | PASS：如实回传 EXECUTED，不声称未执行 |
| R7 | 执行超时语义 | PASS：状态未知 + 取消待确认 |
| R5/R6 | 构建保护 | PASS：运行中拒绝（exit 4）、空闲可构建 |
| 全量回归 | build + 155 单元测试 + A/B 2 + 负例 12 + 生命周期 2 | 全部 PASS |

---

## U4 · 2026-10-09 · 建立标准化验收证据体系（Task A）

**背景**：此前"通过/失败"只散落在会话与 README 里，缺少可机检、可追责、可移植的
证据载体。本次引入 `artifacts/acceptance/` 与导入/校验工具。

**关联 Git SHA**：`d235051`（体系）、`b88a638`（生命周期检查）、`907ea1a`（工具自检缺陷修复）
**证据包**：本条目本身不产出阶段证据包；后续 U5/U6 的证据包均由该体系生成

### 变更文件

| 类型 | 路径 | 说明 |
| --- | --- | --- |
| 新增 | `artifacts/acceptance/schema/acceptance.schema.json` | 冻结的数据契约（JSON Schema 2020-12） |
| 新增 | `artifacts/acceptance/README.md` | 格式、生成方式、验收规则、Schema 子集说明 |
| 新增 | `scripts/export_acceptance.py` | 从真实 git/docker/ROS 采集并打包（含脱敏与哈希） |
| 新增 | `scripts/verify_acceptance.py` | 内置 Schema 子集校验器 + 7 类校验 |
| 新增 | `tests/integration/start_system_check.py` | 启动器生命周期检查（可产出证据） |
| 修改 | `.gitignore` | 排除导出的证据包与 SROS 2 密钥材料，保留 schema/工具/说明 |
| 修改 | `tests/integration/scenario_runner.py` | 输出显式 `expectations`，供期望/实际对照 |

### 解决的问题

1. **证据不可机检** → 冻结 manifest 契约；`verify_acceptance.py` 校验 Schema、必填字段、
   文件 SHA-256、日志引用存在性、PASS 是否有真实执行证据、是否含密钥材料、归档哈希。
2. **数据可能被编造** → commit SHA 取自 `git rev-parse HEAD`，镜像 ID/RepoDigest 取自
   `docker inspect`（无 RepoDigest 时写 `null` 并保留镜像 ID），失败即如实记录。
3. **脱敏** → `security/keystore`、`build/`、`install/`、`.git/` 与密钥后缀一律排除；
   正文命中私钥/证书/口令模式的文件也会被排除并记入 `excluded`。

### 暴露的问题

1. **校验器只实现 Schema 子集**（`$ref`/`type`/`required`/`properties`/`items`/`enum`/
   `pattern`/`minLength`/`minimum`/`additionalProperties`），因此 schema 被刻意限制在该子集内；
   若扩展 schema 必须同步扩展校验器。
2. **证据包不纳入版本控制**：全新 clone 无法直接复核，需在目标机重跑脚本。
3. **工具自身出过两处缺陷，由校验器捕获**：`checks[].detail` 类型为 list（违反 string 约束）
   与 `exit_code` 推导缺失（PASS 场景被判"缺乏执行证据"）。两次都是先导出、再被
   `verify_acceptance.py` 判 FAIL 后修复的 —— 这恰好验证了"导出即可信"是不成立的。

### 实际测试

| 项 | 命令 | 结果 |
| --- | --- | --- |
| 导出/校验闭环 | `export_acceptance.py` → `verify_acceptance.py` | PASS（目录与 tar.gz 两种入口） |
| 篡改检测 | 改 manifest → 校验 | PASS（哈希不一致被抓） |
| 密钥注入检测 | 放入 `leaked.key` → 校验 | PASS（密钥材料被抓） |
| PASS 无证据检测 | 清空 command/evidence → 校验 | PASS（判为证据不足） |
| 归档哈希检测 | 伪造 sidecar → 校验 | PASS（判为不一致） |
| 生命周期检查 | `start_system_check.py` | PASS 2/2 |

---

## U3 · 2026-10-09 · 建立本更新日志（CHANGELOG）并同步文档索引

**背景**：U1/U2 的改动、踩过的坑与遗留问题此前散落在会话记录与各文档里，
缺少一个统一、可累积的载体。本次新增本文件，并顺手把新文件登记进既有文档索引。
本条目同时用于演示"新增条目"的写法。

### 变更文件

| 类型 | 路径 | 说明 |
| --- | --- | --- |
| 新增 | `CHANGELOG.md` | 本文件。含使用约定、条目模板、U1/U2/U3 三条记录、未解决事项总览 |
| 修改 | `README.md` | 目录树补一行 `CHANGELOG.md`，保持交付物清单与实际一致 |
| 修改 | `logs/start_system_evidence/README.md` | 补登 `test_F_session.log`、`test_build_flag.log`、`test_autobuild.log` 三个证据文件（该文件位于 `.gitignore` 排除的 `logs/` 下） |

### 解决的问题

1. **缺少"每次更新改了什么 / 解决了什么 / 暴露了什么"的累积记录**
   → 建立倒序条目式日志，每条固定四节（变更文件 / 解决的问题 / 暴露的问题 / 验证），
   并给出可复制的模板，避免以后各写各的。
2. **遗留问题没有统一台账**：原先"未实现/未验证"散在 `README.md` §6、`ACCEPTANCE.md`
   的"真实阻塞"表和会话记录里，容易漏。
   → 新增"未解决事项总览（滚动维护）"表，每条给编号（I1、I2…）并标注首次暴露的条目，
   后续条目可直接引用编号。
3. **文档索引与实际文件不一致**：`README.md` 目录树未包含新文件。
   → 同步补登，并把证据清单补全到 `logs/start_system_evidence/README.md`。

### 暴露的问题

1. **本日志是手写的，可能与 git 历史漂移**。当前仓库只有 1 个提交
   （`4122012 Initial commit: RosSystem`），U2/U3 的改动**尚未提交**，条目里的
   "变更文件"只能人工核对（本次已用 `git status --short`、`git ls-files` 交叉验证）。
   建议后续把"改代码 + 追加条目"放在同一次提交里。
2. **证据文件位于 `logs/`（已被 `.gitignore` 排除）**，全新 clone 看不到，需在目标机器
   重新执行脚本才能复现验证表中的结果——已在 U2 条目中显式标注。
3. U1 条目部分细节取自当时的会话记录；凡无法用当前仓库内文件佐证的内容
   （例如某些尝试性失败的中间输出）**一律未写入**，以免把推测当成事实。

### 验证

| 项 | 命令 | 结果 |
| --- | --- | --- |
| 引用的路径确实存在 | 逐个 `test -e` 校验 U1/U2 中引用的日志与证据路径 | 全部存在，无悬空引用 |
| 文件计数与仓库一致 | `git ls-files \| wc -l` 与按目录归组 | 62 个，与 U1 条目声明一致 |
| 本次改动范围 | `git status --short` | `CHANGELOG.md`（新）、`README.md`（改）；`scripts/start_system.sh`（新）属 U2 |
| 回归未受影响 | 本次只改文档，未触碰 `src/`、`config/`、`tests/`、`scripts/` | 无需重跑；U2 的 17/17 结果仍然有效 |

---

## U2 · 2026-10-09 · 新增统一启动脚本 `scripts/start_system.sh`

**背景**：已有四个 ROS 2 软件包与构建/测试脚本，但缺少一个"统一入口"：
需要一键完成环境检查 → 构建 → 启动三个常驻节点 → 就绪确认 → 前台运行 → 可控退出，
并保证不会残留容器内节点、不会误杀其他 ROS 2 进程。业务请求（planner）保持独立按需提交。

**范围约束**：只做启动与生命周期管理；不新增/替换 launch 文件，不新增 ROS 节点，
不改 Action 契约、事件结构、原因码与安全判定逻辑，不引入调度服务器/数据库/Web 控制台。

### 变更文件

| 类型 | 路径 | 说明 |
| --- | --- | --- |
| 新增 | `scripts/start_system.sh` | 统一启动脚本（854 行）。含：环境初始化与挂载校验、按需/显式构建、单实例互斥、容器内启动器（内嵌生成）、就绪检测、心跳看门狗、前台运行与优雅退出 |
| 新增 | `logs/start_system_evidence/README.md` | 验证证据汇总（`logs/` 已被 `.gitignore` 排除，属运行产物） |
| 未改动 | `src/**`、`config/task_policy.yaml`、`tests/**` | 期间为故障注入临时替换过策略文件与 gateway 可执行文件，事后已校验还原（1220 B / 985 B，单元测试与 A/B 场景回归通过） |

修正范围：**仅新增 1 个受版本管理的文件**（`git status --short` 只有 `?? scripts/start_system.sh`）。

### 解决的问题

1. **`ros2 launch` 根本收不到 Ctrl+C**（最关键）
   现象：`SigIgn=0x6` 实测显示 `ros2 launch` 的 SIGINT 为 `SIG_IGN`；只有子节点因自身
   安装了 rclpy 处理器才退出。根因：非交互 bash 用 `&` 启动的后台任务按 POSIX 会把
   SIGINT/SIGQUIT 置为 `SIG_IGN`，而 **bash 的 `trap` 无法恢复"进入 shell 时已被忽略"
   的信号**，`setsid cmd &` 同样中招。
   解决：容器内先由一段极小的 Python 启动器 `signal.signal(SIGINT, SIG_DFL)` 复位、
   `os.setsid()` 建独立会话、写出自身 PID/PGID，再 `os.execvp()` 拉起 `ros2 launch`。
   验证：修复后 `/proc/<pid>/status` 的 `SigCgt` 含 SIGINT（handler），
   正常 Ctrl+C 关闭从"等满升级"降到 **3–4s**。

2. **PGID 记录竞态（严重，会导致杀错进程组并遗留孤儿）**
   现象：清理"成功"但容器里仍有 `ros2 launch` + 节点存活。
   根因：外部在 `&` 之后立刻 `ps -o pgid=` 读取，而 `os.setsid()` 约 100ms 后才执行，
   可能读到**外层 bash 的进程组**；于是 SIGINT 发给了错误的组，真正的 launch 变成孤儿。
   （旧版 `setsid(1)` 同样是"先 fork 后 setsid"，窗口极小未暴露；换成 Python 启动器后
   窗口放大到数十毫秒，问题才稳定复现。）
   解决：PID/PGID 改由**持有正确 PGID 的进程自己写文件**；宿主再独立校验
   "该进程组确实在跑 `ros2 launch rg_demo_nodes stack.launch.py`"才接受。

3. **僵尸进程污染存活/残留判定（严重，会把未就绪误判为已就绪）**
   现象：就绪检测一度报 `节点=0/3`；容器内实测已累积 **21 个僵尸**。
   根因：容器 PID 1 是 `sleep infinity`，**不回收孤儿进程**；僵尸的 cmd 里仍带
   `[navigation_sim]`、`[operator_node]`，会被"节点存活数"匹配到，从而凑满 3/3；
   僵尸同时会让"残留进程"判定永远为真，导致 25s+8s 的无谓升级等待。
   解决：`ctr_node_pids` / `ctr_node_names` / `ctr_group_alive` 全部排除 `stat` 以 `Z`
   开头的进程。验证：旧逻辑匹配到 6+5+4 行僵尸，新逻辑在同样的 21 个僵尸下返回空。

4. **看门狗日志被覆盖（证据丢失）**
   现象：看门狗确实触发了清理，但日志里查不到任何 `[watchdog]` 行。
   根因：`ros2 launch` 是 Python 程序，输出到文件时**块缓冲**；它与看门狗用不同的文件
   偏移写同一个 `launch.log`，其后续 flush 覆盖了看门狗的追加行。
   解决：拆分为 `launch.log`（仅 `ros2 launch` 输出）与 `runner.log`（启动器/看门狗），
   并对 launch 设 `PYTHONUNBUFFERED=1` 便于 `tail -f`。

5. **"策略文件不存在"报错不精确**
   原先工作区检查把 `src/` 与策略文件合并判断，策略缺失时走到"工作区内容不可用"分支。
   解决：拆成独立检查，分别给出"权威策略文件不存在（宿主视角）"与
   "策略文件在容器内不可见（挂载可能不一致）"，并保持 fail closed（exit 3）。

6. **正常退出后遗留"当前实例"指针 → 下次启动误报过期记录**
   解决：只有在**确认本实例已无存活进程**时才移除指针；若有残留则保留指针，
   使下一次启动能据此明确拒绝，而不是误判为可启动。
   验证：连续 3 次 启动→停止，过期记录警告均为 0，指针无残留。

7. **就绪失败/超时路径清理过慢**：曾需 25s+8s 才升级。修好信号处置 + 排除僵尸后，
   正常路径 3–4s；仅在"子进程挂死"的故障注入场景（F5）才走升级，约 8s。

8. **CJK 标签用 `printf '%-16s'` 按字节补齐导致错位**（中文占 2 显示列 / 3 字节）
   → 改为手工对齐到固定显示列。

9. **宿主异常死亡时无人清理**（`kill -9` 后 EXIT trap 不执行）
   → 宿主每 5s 触碰心跳文件（且仅在自己存活时），容器内看门狗发现心跳过期后，
   按 INT→TERM→KILL 接手清理**本实例进程组**。

### 暴露的问题

**产品/架构层面（仍未解决）**

1. **本执行环境无法分配 pty**（`/dev/ptmx` 打开返回 EACCES，即使 root），因此
   **未在真实交互终端按物理 Ctrl+C 验证**；只能采用等价投递语义（`SIG_DFL` + 向整个
   进程组发 SIGINT）。影响：终端行规程层的交互（如 `tcsetpgrp`）未覆盖。
2. **看门狗的"已清理"确认行可能与 runner 回收看门狗竞态而丢失**；
   但"接管清理"主证据（心跳过期 + 进程组号）保留，不影响可追溯性。
3. **重复实例检测的能力边界**：依赖实例记录 + 同容器进程扫描，
   **无法发现运行在其他容器/其他 `ROS_DOMAIN_ID` 的实例**。
4. **`ros2 action list` 只能走 daemon**（Jazzy 已移除 `--no-daemon`），daemon 缓存可能
   过期；因此就绪判定额外要求三个节点进程真实存活来兜底，但这属于"叠加判据"而非根治。
5. **脚本只支持"宿主 + Docker 容器"模式**（沿用 `lib.sh` 的 `rg_mode`）；
   原生 Jazzy 宿主的 `native` 路径未实测。
6. **SROS 2 / DDS-Security 仍未启用**：启动成功 ≠ 已实现身份认证或不可绕过的资源隔离。
   脚本在启动与结束横幅均显式打印该警告，避免误读。
7. **子进程挂死时的清理仍偏慢**（F5 约 8s 升级，最坏 ~22s 含就绪窗口）；
   若要更快只能缩短 SIGINT 宽限，会牺牲"慢但合法的优雅关闭"。
8. 观察到的既有现象（本次未修改）：三个节点收到 SIGINT 时 `destroy_node()` 打印
   `KeyboardInterrupt` 回溯、`ros2 launch` 仍以 0 退出；属既有节点收尾噪声。
9. **容器内僵尸会持续累积**（PID 1 不回收）。当前通过排除 `Z` 状态规避误判，
   但容器长期运行后 `/proc` 会膨胀，属环境层面的隐患。

**验证过程中暴露的测试脚手架缺陷（记录以免重复踩坑）**

| # | 脚手架缺陷 | 表现 | 正确做法 |
| --- | --- | --- | --- |
| S1 | 用 `&` 后台启动被测脚本后再 `kill -INT` | `SigIgn=0x6`，脚本完全不理 SIGINT，误判为产品缺陷 | 先复位 `SIG_DFL` 或使用 pty；或改用 SIGTERM |
| S2 | `pkill -f "<模式>"` 模式出现在自己的命令行里 | `pkill` 杀掉自己的 shell（exit 137） | 用方括号技巧 `security_[g]ateway` 或按 PID 精确匹配 |
| S3 | 子 shell 中 `set -e` + 被测命令返回非零 | 子 shell 立即退出，`echo $?` 未执行，退出码丢失 | 不要 `set -e`，或显式 `rc=$?` 后再判断 |
| S4 | 用**悬空符号链接**做 `docker` 遮蔽 shim | bash `command -v docker` 仍判定存在，用例没走到预期分支 | 用只含必要二进制（env/bash/mkdir/dirname）的 PATH 目录 |
| S5 | 读上一轮遗留的 `current_instance.env` 取 PGID | 拿到过期 PGID，用例自相矛盾（F6 误报 exit 4） | 等待本轮记录写出后再读，或直接从启动输出解析 |
| S6 | `kill -9` 杀 `ros2 run` 包装进程 | 真正的节点成为孤儿继续运行（U1 已踩过） | 用 `start_new_session=True` + `killpg` 按进程组清理 |

### 验证

| 测试 | 内容 | 结果 | 证据 |
| --- | --- | --- | --- |
| 构建 | `colcon build`（4 packages） | PASS，exit 0 | `logs/build.log` |
| 单元测试 | `pytest tests/unit` | PASS，140 passed | `logs/unit_tests.log` |
| 既有回归 | A/B 场景套件 `run_ab_scenarios.sh` | PASS，2/2 | `logs/scenarios_ab.log`、`tests/evidence/20261009T075518Z/` |
| A | 正常启动：3 常驻节点 + 2 Action（类型正确） | PASS，~2–3s 就绪 | `logs/start_system_evidence/test_A_E_session.log` |
| B | A 区 `(1.5,1.5)` → ALLOW，NavSim 收到 **1** 条 Goal | PASS，planner exit 0 | `<run-id>/navsim_goals.jsonl`、`audit.jsonl` |
| C | B 区 `(9.0,9.0)` → BLOCK `OUT_OF_REGION`，NavSim **0** 条新 Goal | PASS，且无 ExecutionEvent | 同上 |
| D | 运行期重复启动 | PASS，exit **4**，无重复节点 | driver 输出 |
| E | Ctrl+C（进程组 SIGINT） | PASS，exit **0**，进程组清空，容器保留，日志保留 | `test_A_E_session.log` |
| F1 | docker 命令不可用 | PASS，exit 3 | 会话输出 |
| F2 | Docker daemon 不可用 | PASS，exit 3 | 会话输出 |
| F3 | 权威策略文件不存在 | PASS，exit 3（fail closed） | 会话输出 |
| F4 | 容器工作区挂载不匹配 | PASS，exit 3，不删除/重建容器 | 会话输出 |
| F5 | Action 就绪超时（gateway 替换为无接口桩） | PASS，exit 6，并清理本实例 | 会话输出 |
| F6 | 运行期 `ros2 launch` 被 SIGKILL | PASS，exit 7，并清理本实例 | 会话输出 |
| F7 | 宿主脚本被 `kill -9` | PASS，看门狗 15s 内接管清理 | `<run-id>/runner.log` |
| 构建路径 | `--build` 与"缺少产物自动构建" | PASS，均触发 `build.sh` 后正常就绪 | `/tmp/build_flag.log`、`/tmp/autobuild.log` |
| 连续启停 | 连续 3 次 启动→停止 | PASS，每次独立目录、无陈旧指针、无残留节点 | `logs/start_system/<run-id>/` ×3 |

汇总：**17/17 通过**。未验证项已在上文"暴露的问题"中逐条列出，未计入通过。

**证据位置与可复现性说明**

* 启动类证据在 `logs/start_system/<run-id>/`（每次启动一个独立目录，互不覆盖）：
  `runner.log`（启动器/看门狗）、`launch.log`（ros2 launch 输出）、`audit.jsonl`（审计事件链）、
  `navsim_goals.jsonl`（下游 Goal 计数来源）、`instance.env`（实例记录）。
* 测试会话汇总在 [`logs/start_system_evidence/`](logs/start_system_evidence/)：
  `test_A_E_session.log`、`test_F_session.log`、`test_build_flag.log`、`test_autobuild.log`
  及其 `README.md`。
* ⚠️ `logs/` 与 `tests/evidence/` 已被 `.gitignore` 排除，属**运行产物**：
  全新 clone 不会包含这些文件，需要重新执行脚本才能复现上表中的结果。
  U1 引用的 62 个源码/文档文件则都在版本控制内。

---

## U1 · 2026-10-09 · 阶段一/二/三最小 ROS 2 业务基底首次落地

**背景**：按《ROS 2 基底系统工程搭建与集成方案 v1.2》阶段一/二/三要求，实现一个最小、
可运行、可验证的 ROS 2 机器人业务基底：真实 Action 通信 → 冻结接口契约 → 同步准入判定
→ 执行器接收/拒绝 → 可关联事件日志。不训练视觉模型、不装 Gazebo/Nav2、不做 Dashboard。

对应提交：`4122012 Initial commit: RosSystem`（2026-10-09 13:32，**62 files, 6516 insertions**）。

### 变更文件

按目录归组（共 62 个受版本管理的文件）：

| 类型 | 路径 | 说明 |
| --- | --- | --- |
| 新增 | `src/rg_interfaces/**`（3） | `action/PatrolNavigate.action`（冻结 Goal/Result/Feedback）+ `CMakeLists.txt` + `package.xml` |
| 新增 | `src/rg_policy/**`（11） | **不 import rclpy** 的纯逻辑核心：`reason_codes.py`、`task_policy.py`、`policy_engine.py`（纯函数 `evaluate`）、`request_tracker.py`、`events.py`、`futures.py` + 打包文件 |
| 新增 | `src/rg_gateway/**`（6） | `security_gateway.py`：`/rg/guarded_navigate` 的 Server + `/rg/nav_execute` 的 Client，同步准入 + 审计 |
| 新增 | `src/rg_demo_nodes/**`（10） | `operator_node.py`、`planner_node.py`、`navigation_sim.py` + `launch/{demo,stack}.launch.py` |
| 新增 | `config/**`（6） | `task_policy.yaml`（权威策略）+ 5 个负例场景策略夹具 |
| 新增 | `tests/**`（7） | `unit/`（5 个测试文件 + conftest）、`integration/scenario_runner.py`（A/B + 负例断言器） |
| 新增 | `scripts/**`（10） | `lib.sh`、`container_up.sh`、`build.sh`、`run_unit_tests.sh`、`run_{ab,negative}_scenarios.sh`、`run_all.sh`、`run_demo.sh`+`demo_live.sh`、`shell.sh` |
| 新增 | 根目录（7） | `README.md`、`ACCEPTANCE.md`、`environment.md`、`requirements.md`、`requirements.txt`、`pytest.ini`、`.gitignore` |
| 新增 | `security/README.md` | SROS 2 预留位（**未启用**，无任何密钥） |
| 新增 | `docs/plan_v1.2.extracted.txt` | 方案原文抽取文本，便于逐条对照 |

### 解决的问题

1. **宿主是 Ubuntu 22.04，而 Jazzy 官方只发布 noble(24.04) 的 deb，apt 无法安装**
   → 与用户确认后，ROS 2 运行环境放入 `ros:jazzy` 容器（容器内为真正的 Ubuntu 24.04 +
   Jazzy），工作区 bind mount 到 `/ws`；宿主机不改动。实测镜像自带全部依赖，
   **未额外 apt 安装任何包**。

2. **rclpy 7.1.12 的 Action 回调线程模型不清楚，阻塞等待可能死锁**
   → 逐行核对源码后确认：`MultiThreadedExecutor` 把回调 `submit` 到自己的
   `ThreadPoolExecutor`（`executors.py:983,1002`），`await_or_execute` 对**同步**回调是
   **内联调用**（`executors.py:108,115`）。据此确定无死锁方案：
   `MultiThreadedExecutor(num_threads=4)` + Server 与 Client **各自独立的
   `ReentrantCallbackGroup`**，并在单元测试中强制 `EXECUTOR_THREADS >= 2`。

3. **策略缺失/非法必须 fail closed，且"关键字段不得默默赋默认值"**
   → TaskPolicy 6 个字段全部强校验（类型/非空/有限数/区间/速率>0），
   `PolicyProvider` 按 `(mtime,size)` 热重载，**失败即视为无可用策略**（BLOCK）；
   事件类不设构造默认值，"无值"必须显式传 `UNKNOWN`/`NONE`。

4. **非有限目标值既要忠实记录又要保持 JSONL 严格合法**
   → `x/y/z` 有限时写数字，非有限时写 `"NaN"`/`"Infinity"`/`"-Infinity"` 字符串并置
   `target_finite:false`，序列化用 `allow_nan=False`。

5. **"验证必须基于计数/断言而非终端文本"**
   → NavigationSim **先写 JSONL 记录再执行**（含被超时/杀死的情况），场景断言以下游
   记录**行数**为 Goal 计数；每个场景额外断言 13–21 条（共 215 条）含 `event_id`
   可追溯性与"BLOCK 的 event_id 绝不出现 ExecutionEvent"。

6. **`kill -9` 只杀 `ros2 run` 包装进程会遗留孤儿节点**（开发期实测，
   并因此产生过一条 "more than one action server" 的假告警）
   → 场景驱动器改用 `start_new_session=True` + 按**进程组**清理，并在前后做 /proc 扫描兜底。

7. **rosidl 把 `bool`→`boolean`、`float32`→`float`** → 接口契约测试做显式归一化后比对，
   而非放宽断言。

8. **Jazzy 移除了 `--no-daemon`**（实测 `ros2 action list --no-daemon` 报参数错误）
   → 就绪判定在 `action list` 之外叠加"三个节点进程真实存活"作为第二判据。

### 暴露的问题

1. **SROS 2 / DDS-Security 完全未启用**：无 keystore/enclave/permissions，
   因此**不提供密码学身份认证，也不提供不可绕过的 DDS 资源隔离**；
   同域任意进程仍可直连 `/rg/nav_execute` 绕过 Gateway。
2. **`frame_id` 只做字符串相等判定**（`== policy.coordinate_frame`），
   未做 TF 可信性校验。
3. **去重与限流是 Gateway 进程内存态**，重启即清空，无持久化、无多实例一致性。
4. **未验证跨主机/跨容器 DDS 发现**：所有节点在同一容器内，并设
   `ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST`。
5. **宿主原生 Jazzy 路径未实测**（`RG_MODE=native` 已实现，但本环境无该机器）。
6. **NavigationSim 不做路径规划**；Nav2/Gazebo 未适配（`downstream_action` 已预留）。
7. **审计事件未转发为 Topic**，仅写本地 JSONL。
8. **未做 Action 层并发压测**（仅 `RequestTracker` 有 8 线程单元测试）。
9. **容器 PID 1 为 `sleep infinity`，不回收孤儿进程**：本次已观察到孤儿进程，
   但"僵尸污染存活判定"这一后果**在 U1 时未被识别，直到 U2 才暴露并修复**。
10. 环境限制：宿主为 WSL2，`docker` CLI 无法直连 Docker Hub（`docker manifest inspect`
    失败）而 daemon 可以，故 `docker pull` 成功——排障时需注意此差异。

### 验证

| 阶段 | 命令 | 结果 | 证据 |
| --- | --- | --- | --- |
| 构建 | `colcon build` | PASS，4 packages，exit 0 | `logs/build.log` |
| 单元测试 | `pytest tests/unit` | PASS，U1 收尾时 **140 passed**（首轮 139，随后补充 `rg_policy` 不依赖 rclpy 的架构约束测试后 +1） | `logs/unit_tests.log` |
| A/B 联调 | `scenario_runner.py --suite ab` | PASS，2/2；A 区下游 **1** 条、B 区 **0** 条 | `tests/evidence/20261009T045753Z/` |
| 负例联调 | `scenario_runner.py --suite negative` | PASS，12/12 | `tests/evidence/20261009T045831Z/` |
| 现场演示 | `scripts/run_demo.sh` | PASS，8 checks | `logs/demo.log` |
| 一键 | `scripts/run_all.sh` | OVERALL PASS | `logs/final_sweep_console.log` |
| launch 文件 | `stack.launch.py` / `demo.launch.py` | PASS | 见 `ACCEPTANCE.md` T7 |

阶段五 P0 验收 7/7 通过；P1（SROS 2）与 P2（Nav2/Gazebo）明确未实现，详见 `ACCEPTANCE.md`。

---

## 未解决事项总览（滚动维护）

| 编号 | 事项 | 首次暴露 | 状态 |
| --- | --- | --- | --- |
| I1 | SROS 2 / DDS-Security 未启用（无认证、无不可绕过隔离） | U1 | 未解决（P1 扩展项） |
| I2 | `frame_id` 无 TF 可信性校验 | U1 | 未解决 |
| I3 | 去重/限流无持久化、无多实例一致性 | U1 | 未解决 |
| I4 | 跨主机/跨容器 DDS 发现未验证 | U1 | 未解决 |
| I5 | 原生 24.04 + Jazzy 路径未实测 | U1 | 未解决 |
| I6 | Nav2 / Gazebo 未适配 | U1 | 未解决（P2 扩展项） |
| I7 | 审计事件未转发为 Topic | U1 | 未解决 |
| I8 | 无 Action 层并发压测 | U1 | 未解决 |
| I9 | 容器 PID 1 不回收僵尸，僵尸持续累积 | U1（后果在 U2 暴露） | 已规避误判，未根治 |
| I10 | 无法分配 pty，物理 Ctrl+C 未验证 | U2 | 环境限制，未解决 |
| I11 | 看门狗"已清理"确认行存在竞态丢失可能 | U2 | 未解决（不影响主证据） |
| I12 | 重复实例检测仅限同容器/同 ROS_DOMAIN | U2 | 未解决 |
| I13 | `ros2 action list` 只能走 daemon，缓存可能过期 | U2 | 已用"节点进程存活"兜底，未根治 |
| I14 | `start_system.sh` 仅支持容器模式 | U2 | 未解决 |
| I15 | 节点 SIGINT 收尾打印 KeyboardInterrupt 回溯 | U2（既有现象） | 未修改 |
| I16 | 本日志为手写，未与 git 提交绑定，存在与代码漂移的风险 | U3 | 未解决（建议同一次提交内追加条目） |
| I17 | 验证证据位于 `.gitignore` 排除的 `logs/`、`tests/evidence/`，全新 clone 无法直接复核 | U3 | 未解决（需重跑脚本复现） |
| I18 | sros2 0.13.6 在策略非法时静默产出**默认全开**权限文件 | U6 | 已用"预检 + 独立复核"夹住，工具链缺陷本身未消除 |
| I19 | SROS 2 私钥以明文 PEM 落盘（权限 700，未加密） | U6 | 未解决（需文件系统加密或 HSM） |
| I20 | 安全结论仅覆盖本机单容器 + rmw_fastrtps_cpp + domain 43 | U6 | 未解决（跨主机/RMW 未验证） |
| I21 | 安全模式未为 ros2 CLI 分配运维身份，观测依赖文件证据 | U6 | 未解决 |
| I22 | 未启用证书吊销/轮换（CA 与身份证书 10 年有效） | U6 | 未解决 |
| I23 | `audit_fault_injection` 位于产品代码中（仅测试用，只能制造失败） | U5 | 待评审（是否改为依赖注入） |
| I24 | 执行阶段审计写失败无补写机制，审计链完整性依赖 rosout 日志通道 | U5 | 设计取舍，已文档化 |

> 用法：后续条目解决某项时，在该行状态里写 `→ 已由 U<n> 解决`，不要删除原行，
> 以便保留"何时暴露、何时关闭"的轨迹。
