# 核心技术术语（中英对照与规范用法）

> 核实日期：2026-10-22
> 每条给出：中文术语 / 英文术语 / 规范定义 / 来源 / 在 RosSystem 中的用法 / 常见误用。
> 编号对应 `references_ieee.md`，citation key 对应 `references.bib`。
> **总体要求**：论文中同一概念只用一个译名，首次出现给出英文原文与缩写。

---

## 1. DDS Security

- **中文**：DDS 安全（规范）
- **英文**：DDS Security
- **定义**：OMG 制定的安全模型与 **SPI（Service Plugin Interface）** 插件架构，包含认证、访问控制、密码学、日志与数据标记五类插件；由 DDS 实现调用这些 SPI 来强制执行安全模型。
- **版本事实**：当前正式版为 **1.2（formal/25-03-06，2026 年 2 月采纳）**；历史版本 1.0（2016-08）、1.1（2018-07）[32]。ROS 2 的 enclave 设计与 Fast DDS 2.14 文档仍以 1.1 为参照 [35][37]。
- **在 RosSystem 中**：作为第 1 层，由 SROS 2 工具链生成 keystore/governance/permissions 后启用；RosSystem **未修改** DDS 实现或规范。
- **常见误用**：
  - ✗ "DDS Security 认证了应用请求"——它认证的是 DomainParticipant；
  - ✗ "RosSystem 增强了 DDS Security"——本项目只在应用层叠加机制。

## 2. SROS 2

- **中文**：SROS 2（ROS 2 安全工具与库）
- **英文**：SROS 2 (Secure ROS 2)
- **定义**：面向 ROS 2 的开发者工具与库集合，用于为计算图生成密钥、划分 enclave、分发权限策略，强调可用性与 DevSecOps 流程 [1][2]。
- **在 RosSystem 中**：`scripts/setup_sros2.sh` 调用 `ros2 security` 生成实验室 CA、enclave 与签名权限文件。
- **常见误用**：
  - ✗ 把 SROS 2 写成"一个加密协议"——它是工具链与集成约定的集合；
  - ✗ 把 SROS 2 当作本项目贡献。

## 3. Enclave

- **中文**：安全区（ROS 2 语境）/ 飞地
- **英文**：Enclave
- **定义**：ROS 2 中一组运行时安全制品（证书、私钥、governance、permissions）的目录，对应一个 **context / DomainParticipant**。ROS 2 规定一个 participant 只能使用**一个**安全身份，故同一进程内多节点需共享同一套凭据 [35]。
- **在 RosSystem 中**：作为 DDS 层的配置单位；论文用它解释"为什么参与者级身份无法区分同进程内的不同应用请求"。
- **常见误用**：
  - ✗ 与 Intel SGX 的 "enclave"（硬件可信执行环境）混为一谈——ROS 2 enclave 只是**文件与配置的组织单位**，不提供硬件隔离；
  - ✗ 说"每个请求一个 enclave"。

## 4. Authentication（认证）

- **中文**：认证 / 身份鉴别
- **英文**：Authentication
- **定义**：验证某个实体（此处为 DomainParticipant）确实持有其声称身份的凭据；DDS Security 使用 X.509 证书与挑战-响应完成相互认证 [32][37]。
- **在 RosSystem 中**：DDS 层完成参与者认证；应用层再做"当前请求证明"。
- **常见误用**：
  - ✗ 把认证等同于授权；
  - ✗ 写"请求已被认证"而实际只做了签名校验——应写"请求证明通过验证"。

## 5. Authorization（授权）

- **中文**：授权
- **英文**：Authorization
- **定义**：在认证之后判定某主体能否对某资源执行某操作。DDS 层由 governance/permissions 文档表达，判据是 topic/partition 等资源 [32][36]；应用层可由 ABAC 等模型表达 [41]。
- **在 RosSystem 中**：Gateway 的 TaskPolicy 是应用层授权；身份门是准入前置条件。
- **常见误用**：
  - ✗ "DDS 授权通过 = 任务可执行"——资源权限与任务策略是不同判据。

## 6. Attestation（证明 / 远程证明）

- **中文**：远程证明（完整说法）；单独出现时译"证明"
- **英文**：Remote Attestation
- **定义**：由可信硬件（如 TPM）对**平台/软件栈的完整性度量**出具可验证证据，使对端能确认其运行的是预期代码 [6]。
- **在 RosSystem 中**：**未实现远程证明**。RosSystem 的 "证明" 是对**请求摘要的 Ed25519 签名**，属于"请求来源与完整性证明"，**不是**平台度量证明。
- **常见误用**：
  - ✗ 把 RosSystem 的签名称为 "attestation"——应在英文中写 `signed request proof` 或 `request-bound signature`，避免与 remote attestation 混淆；
  - ✗ 声称"已实现可信证明链"。

## 7. Request Binding（请求绑定）

- **中文**：请求绑定
- **英文**：Request Binding / Request-level Binding
- **定义**：把一次具体请求与其声称的主体、内容、新鲜度密码学地关联起来，使请求不能被冒名、篡改或重放。三要素：主体→消息、消息→内容、内容→新鲜。
- **在 RosSystem 中**：`request_digest` 覆盖 `request_id/resource/operation/task_id/target`，配 nonce 与时间窗，由 F0 与 Gateway 独立核验（意图主题）。
- **常见误用**：
  - ✗ 只签 `request_id` 就称"请求绑定"——未覆盖内容；
  - ✗ 把会话级 TLS/DDS 加密称为请求绑定。

## 8. Replay Protection（重放保护）

- **中文**：重放保护 / 防重放
- **英文**：Replay Protection
- **定义**：通过 nonce、时间戳、序列号或挑战-响应，使已捕获的合法消息不能被再次使用。
- **在 RosSystem 中**：单调 nonce 的原子账本（`flock` + 重读-判重-追加-fsync）加时间窗；重放/过期样本失败关闭。
- **常见误用**：
  - ✗ 只用时间戳——在时钟不同步时可被绕过；
  - ✗ 声称"nonce 机制是本文创新"。

## 9. Fail-closed

- **中文**：失败关闭 / 默认拒绝
- **英文**：Fail-closed（对应 Fail-open / Fail-safe）
- **定义**：当判定所需证据缺失、过期或无法验证时，系统选择**拒绝**而非放行；源自 fail-safe defaults 原则 [15]。
- **在 RosSystem 中**：LAB 身份默认不被 F0 接受；M1 UNKNOWN 时 LEVEL 3 阻断；缺失账本记为 `coverage=UNKNOWN` 而非 0。
- **常见误用**：
  - ✗ 写成 "fail-safe"——fail-safe 通常指转向安全状态，语义不同；
  - ✗ 只讲安全不讲可用性代价。

## 10. Admission Control（准入控制）

- **中文**：准入控制
- **英文**：Admission Control
- **定义**：在执行开始**之前**，依据策略与证据决定是否允许该操作进入执行阶段；与"执行中监控"互补。
- **在 RosSystem 中**：F0 与 Gateway 构成两层准入；阻断表现为"0 Goal"或"未提交"。
- **常见误用**：
  - ✗ 与"访问控制"混用——访问控制关注资源访问，准入控制关注**执行许可**；
  - ✗ 声称准入通过即执行成功（见术语 12）。

## 11. Policy Enforcement（策略执行）与 PEP/PDP

- **中文**：策略执行点（PEP）/ 策略决策点（PDP）
- **英文**：Policy Enforcement Point / Policy Decision Point
- **定义**：PDP 依据策略与上下文作出决策，PEP 在资源访问或操作路径上强制执行该决策；零信任架构要求二者分离并可持续评估 [40]。执行监控的可执行策略类有理论边界 [14]。
- **在 RosSystem 中**：F0 与 Gateway 兼具决策与执行中介角色；二者的判定分别记录（`GatewayIdentityCheck`、`DecisionEvent`）。
- **常见误用**：
  - ✗ 把建议性风险模块（M1/M3）称为 PDP；
  - ✗ 声称可强制执行任意策略。

## 12. Goal Lifecycle（Goal 生命周期）

- **中文**：目标生命周期
- **英文**：Goal Lifecycle / Goal State Machine
- **定义**：ROS 2 Action 服务端为每个被接受的 goal 维护状态机：
  **活动态** ACCEPTED、EXECUTING、CANCELING；
  **终止态** SUCCEEDED、ABORTED、CANCELED。
  转移由 `send_goal`、`execute`、`cancel_goal`、`succeed`、`abort`、`canceled` 触发；cancel 请求被接受才进入 CANCELING，是否最终 CANCELED 由状态话题与 result 服务体现 [34]。
- **在 RosSystem 中**：用于解释 P09——Planner 侧 `RESULT_TIMEOUT` 只是客户端放弃等待结果，**不触发** cancel，故下游仍可 `EXECUTED`。
- **常见误用**：
  - ✗ "超时即取消"；
  - ✗ "发送 goal 即执行"（还需被接受）；
  - ✗ "收到 result 才算执行"（结果可缓存、可后取）。

## 13. Out-of-Distribution（OOD，分布外）

- **中文**：分布外（检测）
- **英文**：Out-of-Distribution (OOD) Detection
- **定义**：识别输入来自与训练分布不同的分布，从而避免模型对未知输入给出高置信错误预测；与数据集偏移、概念漂移密切相关 [11][27]。
- **在 RosSystem 中**：M1 的部署风险部分源于分布偏移（训练数据为 ROSPaCe 离线窗口，部署为 Jazzy 运行时）；当前以 `UNKNOWN` 表达"不可判定"。
- **常见误用**：
  - ✗ 把 OOD 检测等同于异常检测；
  - ✗ 用训练集内的异常类别冒充 OOD 评估。

---

## 14. 补充术语（本项目高频，易混）

| 中文 | 英文 | 规范含义 | 来源 | 常见误用 |
|---|---|---|---|---|
| 拒识 / 拒绝选项 | Reject Option | 分类器在低置信时拒绝判定，在错误率与拒识率之间权衡 | [44] | 把"拒识"写成"检测为异常" |
| 不可判定 | UNKNOWN | 证据不足导致**无法判定**，与"判定为 0/正常"不同 | 本项目 | 把 UNKNOWN 记成 0 |
| 数据泄漏 | Data Leakage | 训练时使用了预测时不可得的信息 | [10] | 仅用"过拟合"解释 |
| 捷径特征 | Shortcut / Spurious Cue | 与标签相关但在目标分布不成立的线索 | [11] | 与"特征工程错误"混用 |
| 分组验证 | Grouped Cross-Validation | 按会话/分段等结构分组切分，避免同组泄漏 | [26] | 用随机 K 折处理时序数据 |
| 概念漂移 | Concept Drift | 输入-输出关系随时间变化 | [27] | 与"数据噪声"混用 |
| 检查项 | Check Item | 测试/实验中的一个断言或判定项 | 本项目 | 把检查项数当独立实验数 |
| 使用期限（凭据） | Credential Lifetime | 密钥/证书的有效期与轮换周期 | [32] | 声称已实现轮换 |
| TOCTOU | Time-of-Check to Time-of-Use | 检查时刻与使用时刻之间状态变化导致的竞态 | 安全工程常识（本项目未实现防护） | 声称已消除 TOCTOU |
| 审计事件 | Audit Event | 记录"谁在何时基于何证据做了什么判定"的结构化记录 | [47] | 只记结果不记证据来源 |
| 证据融合 | Evidence Fusion | 把多源证据按规则合成判断；需处理冲突与可信度 | [25] | 把"并列展示"称为融合 |

---

## 15. 术语使用检查清单（投稿前自查）

- [ ] "认证"与"授权"没有混用；
- [ ] "请求绑定"未被简化为"签名"；
- [ ] "证明（attestation）"未被误用于请求签名；
- [ ] "enclave"首次出现时注明是 ROS 2 配置单位，非硬件 TEE；
- [ ] "UNKNOWN"与"0/正常"未混用；
- [ ] "准入控制"与"访问控制"区分；
- [ ] "超时"未被表述为"取消"或"失败"；
- [ ] "检查项/测试项"未被表述为"独立实验"；
- [ ] 中英文缩写首次出现均有全称。
