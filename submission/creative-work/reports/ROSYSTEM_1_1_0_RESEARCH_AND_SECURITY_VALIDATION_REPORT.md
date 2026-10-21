# RosSystem 1.1.0 科研级跨层安全验证报告

> 分支：`research/cross-layer-security-v1.1.0`
> 冻结基线：`creative-work-v1.0.3`（附注标签对象 `7b60b28…`，指向提交 `5773fb4…`）
> 本轮测量时点提交：`452f064`（报告提交晚于测量提交，见 §15）
> 环境：Ubuntu 22.04.5 WSL2 宿主；ROS 2 Jazzy / Fast DDS 2.14.6 / Python 3.12.3 均在
> `ros:jazzy` 派生容器 `rg_v110` 内；RMW `rmw_fastrtps_cpp`。
> 结论级别：**LEVEL C — DDS_AND_IDENTITY_LAB_VERIFIED**
> 报告日期：2026-10-21

---

## 1. 研究目标与创新问题

1.0.3 已经能证明“历史 DDS 权限证据可解释”“Gateway 能独立执行 TaskPolicy”，
但它没有回答三个跨层问题：

1. **当前这条请求是谁发的？** 历史 `AUTHORIZED` 只描述过去某次运行，不绑定当前
   `request_id`、当前目标点和当前 Action 资源。
2. **DDS 层的身份、应用层的请求、Gateway 的准入能否形成一条可核验的链？**
   DDS-Security 的认证发生在参与者建链阶段；ROS 2 Jazzy 的订阅端不暴露样本发布者身份。
   因此“DDS 已认证”不能自动推出“当前应用请求由该主体发出”。
3. **在没有生产信任根的条件下，能否用可公开复现的实验室凭据证明这条链在技术上成立，
   同时不把实验室结论冒充生产结论？**

本轮的可检验目标因此不是“让 acceptance 全绿”，而是：

- 用真实 DDS 观测把 **writer GUID → 已认证证书主体 → 请求内容摘要** 绑定起来；
- 用**非对称签名**（Ed25519）取代对称 HMAC 见证，使验证方只持公钥；
- 让 **F0 与 Gateway 各自独立核验**，而不是一层通过后另一层照抄；
- 在真实容器里重新执行 DDS Enforce 正负实验，并让证据**自带可解释所需的非秘密材料**；
- 明确记录哪些能力仍然被阻断。

## 2. 1.0.3 基线与能力缺口

### 2.1 基线事实

| 项 | 1.0.3 状态 | 本轮核验方式 |
| --- | --- | --- |
| 受控在线 40 项 | 已通过（历史证据） | 未重跑全部 40 项；用三真实 LEVEL1/2 与单元回归覆盖 |
| 三真实 | LEVEL1 PASS / LEVEL2 PASS / LEVEL3 BLOCKED | 本轮实测同样结果 |
| DDS Enforce | 历史 7/7；1.0.3 包内 **NOT_RUN** | 本轮重新生成实验室 CA 并实跑 7/7 |
| M2 当前请求身份 | 对称 HMAC、TEST_ONLY、默认 UNKNOWN | 本轮新增 Ed25519 LAB 路径 |
| M1 NORMAL | `validation_gate_passed=false` | 本轮未改变，仍为 UNKNOWN |
| 13 项身份单测 | 失败 | 本轮修复为 56/56，并保留原断言 |

### 2.2 13 项身份测试失败的根因（实测，不是推断）

归档运行 `20261009T093144Z` 保留了 S1–S6 与 S3C 的运行时日志，但**没有保留任何
`permissions.xml`**；keystore 在实验后被清理（其中含私钥，本就不应入库）。
评估器拒绝在没有生成权限文件的情况下把运行时拒绝提升为结论，因此 13 项测试失败。
这**不是**算法缺陷，也**不能**通过跳过测试或放宽断言修复。

本轮的做法：

1. 用 `scripts/setup_sros2.sh` 重新生成完整实验室 CA 与 5 个 enclave；
2. 把**非秘密**的 `permissions.xml` 作为 `tests/fixtures/sros2_lab_permissions/`
   固定下来，用策略哈希和语义断言钉住；
3. 新增 `conftest` 钩子：仅当不存在真实 CA 时，才把这份“只有权限、没有密钥”的
   fixture 物化到 `security/keystore/`，并写入 `FIXTURE_ONLY_NO_PRIVATE_KEYS` 标记；
4. 重新实跑 DDS Enforce，并把**生成权限、证书主体、CA 指纹、文件哈希、命令与退出码**
   一起归档，使新证据不再依赖被清理的 keystore。

### 2.3 能力差距矩阵（本轮实测后的状态）

| 能力 | 1.0.3 | 1.1.0 本轮 | 状态 |
| --- | --- | --- | --- |
| M1 可信观测 | 话题级/历史数据 | 真实 DDS 入口可观测 writer→证书主体→payload；M1 模型门槛仍 false | **BLOCKED** |
| M2 当前请求身份 | HMAC + TEST_ONLY + 默认 UNKNOWN | Ed25519 + 公钥指纹 + 真实 DDS 观测 + LAB scope | **LAB VERIFIED** |
| M3 任务风险 | External 建议 | 未改算法；ALLOW_RECOMMENDED 在真实运行中正确输出 | PASS |
| F0 联合准入 | 严格阻断 | 保持；新增 LAB 显式 opt-in，默认仍拒绝 | PASS（负向） |
| Planner | 受控 | 未改；P09 TIMEOUT 未重跑 | NOT_RUN |
| Gateway | TaskPolicy 独立 | **身份证据独立再核验 + TaskPolicy** | **LAB VERIFIED** |
| DDS Security | 历史 7/7；1.0.3 NOT_RUN | 新 CA 实跑 7/7 + 6 负向 | **LAB VERIFIED** |
| NavigationSim | Goal recorded_only | 未扩展状态机；继续如实标注 recorded_only | NOT_RUN（增强） |
| Web 控制台 | 历史展示 | 未改；1.1.0 证据尚未接入控制台 | NOT_RUN |
| 独立复现 | 受控在线已通过 | 本环境内复现；新压缩包独立部署未执行 | PARTIAL |

## 3. 总体架构

```text
                      ┌──────────────────────────────┐
                      │ 受信任 DDS 入口 m2_ingress    │
                      │ /witness enclave (domain 45) │
                      └──────────────┬───────────────┘
                                     │ writer GUID + identity_token_
                                     ▼
                          intent_events.jsonl
                                     │
                                     ▼
                     lab_issuer.py (Ed25519, TEST_ONLY)
                                     │  v3 attestation
              ┌──────────────────────┼───────────────────────┐
              ▼                      ▼                       ▼
      M2 assessor             F0 team_demo.py          Gateway identity_gate
   current_request_identity   (本地再核验)             (本地再核验 + 自己的账本)
              │                      │                       │
              ▼                      ▼                       ▼
        extensions 输出        READY / BLOCK           ALLOW / BLOCK + TaskPolicy
                                     │                       │
                                     └──────── Planner ──────┘
                                                             ▼
                                                   NavigationSim (recorded_only)
```

关键设计原则：

- **DDS 身份 ≠ 应用请求身份**。本轮用真实 DDS 样本把两者连接起来，但连接发生在
  “预准入意图主题”上，不是 Action `send_goal` 服务请求；这一差距在 §6.4 明确保留。
- **F0 READY ≠ Gateway ALLOW**。两层各自核验证据、各自消费 nonce。
- **LAB ≠ PRODUCTION**。scope 只能来自受信任签发者清单；证据本身不能自升 scope。

## 4. 威胁模型

### 4.1 受保护资产

- Action `/rg/guarded_navigate` 的准入决定与 `/rg/nav_execute` 的执行触发；
- 当前请求的身份声明与目标参数；
- 审计链（Gateway DecisionEvent、NavigationSim Goal、身份检查 JSONL）；
- 实验室 CA 私钥、Ed25519 签发私钥、nonce 账本。

### 4.2 攻击者能力假设

| 能力 | 本轮是否覆盖 |
| --- | --- |
| 伪造业务 JSON 自报 `authenticated=true` | 覆盖：F0 不读自报字段，用受信任材料核验 |
| 复用历史 AUTHORIZED 支撑新请求 | 覆盖：历史资源比对 + 复用账本 |
| 复制/重放当前证据 | 覆盖：nonce 原子预留 → REPLAYED |
| 篡改签名/正文/目标点 | 覆盖：Ed25519 失败关闭、摘要不匹配 |
| 换公钥/换签发者 | 覆盖：公钥 SHA-256 固定、签发者清单 |
| 使用另一 CA 的证书加入安全域 | 覆盖：N1 信任根不匹配 |
| 篡改 permissions.p7s | 覆盖：N2 |
| 把证书放进别的 enclave 目录冒充 | 覆盖：N4 |
| 关闭 Enforce 后访问 | 覆盖：N3 对照显示未授权客户端可执行 |
| 拿到签发私钥 | **未覆盖**（无 HSM，文件密钥） |
| 在生产 CA 上签发 | **未覆盖**（只有实验室 CA） |
| 在 Action 层冒充同一主体 | **未覆盖**（意图绑定不等于 Action 绑定） |

### 4.3 信任边界

1. **DDS 安全域**：参与者的证书主体由 DDS-Security 认证；受信任入口读取 writer GUID
   与 `identity_token_`。
2. **签发边界**：Ed25519 私钥只在本机文件中；公钥按 DER SHA-256 固定在受信任清单。
3. **验证边界**：F0 与 Gateway 各自持公钥、清单与 nonce 账本；任一层的判定不被另一层替代。
4. **文件边界**：attestation 经按 `request_id` 命名的 side channel 送达 Gateway；
   `request_id` 必须是安全文件名，符号链接拒绝，读取走 hardened loader。
5. **证据边界**：归档只含公钥、清单、账本、日志与非秘密权限；私钥在归档前删除。

## 5. M1 通信风险研究（本轮结论：未通过，保持阻断）

### 5.1 已具备

- 真实 ROS 2 采集器与 30 s 窗口契约；
- 会话分组交叉验证、泄漏字段排除、逐类召回与合并 FPR 的 v2 指标；
- 真实 DDS 入口（`m2_ingress_witness`）已经能提供**可信的请求级观测**：
  writer GUID、participant GUID、证书主体、payload、received_at；
- 52 个单元测试（含本轮身份相关）全部通过，M1 相关回归未退化。

### 5.2 为什么仍不能给 NORMAL

M1 的 `validation_gate_passed=false` 没有被改动。现有证据仍不满足预登记门槛：

- 真实正常窗口只有 12 个，0 误报的置信区间过宽；
- 唯一可测异常会话无法留出评估，召回不可测；
- 训练攻击语义（nmap discovery / ROS 2 reconnaissance）缺少真实复核样本；
- graph-only 攻击在消息级特征族下不可见；
- 高频负载异常未被现有模型检出（此前实测），不能反过来当作“模型已具备检出力”。

本轮**没有**用“数据不存在”解释成“通信正常”，也没有把 50 Hz/500 Hz 负载标成攻击。
M1 的 UNKNOWN 仍是失败关闭结果。

### 5.3 与 M2 观测链的关系

M2 入口现在能提供可信的 `send_goal` 类观测（意图主题），这为 M1 的未来特征
（计数、认证发送者、覆盖率、缺失观测）提供了真实来源；但**本轮没有训练/部署新模型**，
因此三真正向仍被 M1 阻断。这条边界在 §8 与 §17 再次列出。

## 6. M2 当前请求身份：Ed25519 与真实 DDS 归属

### 6.1 契约 v3

签名覆盖规范化 JSON：`contract, issuer, request_id, resource, operation,
request_digest, received_at, nonce, evidence_kind, remote_identity, producer,
witness`。`request_digest = SHA-256(canonical(request_id, action_resource,
operation, task_id, target.{frame_id,x,y,z}))`。

验证顺序：**公钥指纹固定 → Ed25519 签名 → 契约/字段 → 请求绑定 → 新鲜度 →
签发者信任/scope → 原子 nonce 预留**。状态：

- `AUTHENTICATED`：生产语义（仓库不交付生产签发者）；
- `AUTHENTICATED_LAB`：LAB scope，**只有 `allow_lab=True` 才被 F0 接受**；
- `AUTHENTICATED_TEST_ONLY` / `UNKNOWN` / `DENIED` 保持原语义。

### 6.2 真实 DDS 归属（实测）

实验环境：`/witness` 入口、`/planner` 与 `/operator` 两个不同证书的客户端、
domain 45、研究 keystore。账本逐条记录：

| 请求 | certificate_subject | sender_authenticated | writer GUID 前缀 = participant GUID |
| --- | --- | --- | --- |
| `req-lab-p01` | `/CN=\/planner` | true | 是 |
| `req-lab-p02` | `/CN=\/operator` | true | 是 |

- **零串号**：两条请求分别归属到各自证书；
- `/rogue` 没有该主题发布权限，`create_datawriter` 失败（退出码 6），账本无其样本；
- 这证明“接收侧读出的 writer GUID → 已认证参与者 → 证书主体”在真实 DDS 上成立。

### 6.3 端到端（实验室）

17/17 检查通过：

- 合法证据 → `AUTHENTICATED_LAB`，五项检查 `VALID/MATCH/OK/RESERVED`；
- 默认 F0 接受为 **false**；显式 `allow_lab_scope: true` 才 READY；
- 同一 nonce 重放 → `REPLAYED`；
- 错误主体、篡改观测摘要、过期观测 → 签发端拒绝；
- 签名篡改 → `INVALID`；
- 错误公钥 → `KEY_MISMATCH`；未知签发者 → `NOT_LISTED`；私钥误用 → `KEY_UNUSABLE`；
- F0 在真实证据上 READY，重放同一证据被阻断。

### 6.4 未证明的边界（必须保留）

1. attested resource 是 `rt/m2/candidate_task`（预准入意图），**不是** Action
   `send_goal` 的 `rq/rg/guarded_navigate/_action/send_goalRequest`。后者需要
   `PatrolNavigate_SendGoal_Request_` 的 typesupport 接线，本轮未完成。
2. 临时实验室 CA；无私钥 HSM/加密存储；无证书吊销/轮换；无独立 UID 隔离。
3. Gateway 侧证据经文件 side channel，不是 Action 协议内字段。
4. `identity_attestation.allow_lab_scope` 默认 false，既有严格配置没有被放宽。

## 7. DDS Enforce 正式实验（新 CA，独立复跑）

### 7.1 实验室凭据

- `scripts/setup_sros2.sh` 创建 keystore、5 个 enclave、governance 与签名权限；
- `scripts/verify_sros2_permissions.py` 独立复核最小权限（PASS）；
- 私钥只在 `security/keystore/`（gitignored），取证后清理；
- 证据归档包含每个 enclave 的 `permissions.xml`、证书主体、CA SHA-256 指纹、
  策略哈希、命令与退出码，**不含**私钥或证书文件。

### 7.2 正向七场景（domain 43）

| 场景 | 结果 | 关键证据 |
| --- | --- | --- |
| S1 普通模式 A 区 | PASS | Gateway ALLOW，Goal 1 |
| S2 Enforce 合法 A 区 | PASS | EXECUTED，Goal 1，ALLOW_IN_POLICY |
| S5 合法身份 B 区越界 | PASS | OUT_OF_REGION，Goal 0 |
| S3C 正向对照 `/gateway` 直连 | PASS | EXECUTED，Goal 1 |
| S3 `/planner` 直连执行接口 | PASS | 原生 `not found in allow rule`，Goal 0 |
| S4 `/unauthorized` 直连 | PASS | 原生拒绝，Goal 0 |
| S6 缺 keystore | PASS | 不静默回退，Goal 0 |

**7/7 PASS**。S3/S4 的日志保留真实交错 ANSI 字节，未做清洗后重写。

### 7.3 新增负向六场景（每项带同栈正向对照）

| 场景 | 结果 | 说明 |
| --- | --- | --- |
| N1 不同 CA 加入安全域 | PASS | 拒绝；同栈 `/gateway` 对照成功 |
| N2 篡改 `permissions.p7s` | PASS | 参与者无法完成执行，暴露安全错误 |
| N5 签名后篡改 `permissions.xml` | PASS | 新增权限**不生效**；已签名基线仍工作 |
| N4 证书/目录错配 | PASS | 不能继承 `/gateway` 权限 |
| N3 Enforce 关闭对照 | PASS | 同一未授权客户端在无安全域可执行（证明 S3/S4 的拒绝来自 DDS 安全） |
| N0 正向对照 | PASS | `/gateway` 直连成功，Goal 1 |

**6/6 PASS**。N5 的实测发现是：Fast DDS 消费 CMS 签名的 `permissions.p7s`，
单独编辑 `permissions.xml` 不会授予新权限；重新签名需要权限 CA 私钥。

### 7.4 结论分级

- `DDS_LAB_ENFORCE_VERIFIED`：**PASS**（新 CA、独立 domain、正负向、证据完整）；
- `DDS_AUTHORIZED_ENV_VERIFIED`：**部分**（有实验室授权环境，无生产运维体系）；
- `DDS_PRODUCTION_DEPLOYMENT_VERIFIED`：**NOT_RUN**。

## 8. 三真实正向闭环（本轮结论：LEVEL 1/2 PASS，LEVEL 3 BLOCKED）

真实运行 `v110three-20261021T194500Z`（配置 `config/team_modules.three-real.yaml`）：

| 等级 | 结果 | 依据 |
| --- | --- | --- |
| `THREE_EXTERNAL_CALLED` | **PASS** | 三个真实进程均被调用，命令与退出码归档 |
| `THREE_EXTERNAL_VALIDATED` | **PASS** | Schema、关联字段、证据一致 |
| `THREE_EXTERNAL_ONLINE_PROCEED` | **BLOCKED** | M1 UNKNOWN；M2 当前身份 UNKNOWN；F0 ADAPTER_BLOCK |

F0 的阻断原因原文：

```text
comm_risk: status='UNKNOWN'，推进需要 'NORMAL'
identity_trust: current_request_identity.status='UNKNOWN'，本轮没有可信的当前请求身份绑定
F0 决策为 'ADAPTER_BLOCK'（ADAPTER_MODULE_STATUS_NOT_PROCEED），未提交 Planner
```

模块输出：M1 `UNKNOWN`（`trusted_provenance=UNKNOWN`，模型门槛未通过）、
M2 历史 `AUTHORIZED` 但当前身份 `UNKNOWN`、M3 `ALLOW_RECOMMENDED`。
**没有任何一个模块用 Mock 替换，也没有把历史 AUTHORIZED 当作当前身份。**

### 8.1 为什么不用实验室 M2 证据“凑” LEVEL 3

即便把 M2 的 Lab 证据接到三真实配置，M1 仍只能给 UNKNOWN（模型门槛 false），
F0 仍必须阻断。要得到 LEVEL 3，必须先有 M1 的受信任 NORMAL；本轮没有伪造它。

### 8.2 正向链路的可替代验证

M2 + Gateway 的正向链已在**组件级真实 DDS** 上验证（§6、§9），F0 也在真实证据上
达到 READY；但“三真实模块 + 当前请求身份 + Gateway ALLOW + Goal 1”这一整链
**未被本轮证明**，不得写成已实现。

## 9. 三真实负向与 Gateway 独立授权

### 9.1 Gateway 双层判定

`identity_gate.verify_goal()` 用 Goal 的 `request_id/task_id/frame_id/x/y/z`
重建摘要覆盖字段，读取该 request_id 的证据，独立做 Ed25519/绑定/新鲜度/nonce 检查，
再交给未修改的 TaskPolicy。启用后没有静默回退。

真实运行 `v110gwlab-20261021T193500Z`，**14/14 PASS**：

| 场景 | 身份门 | TaskPolicy | 下游 Goal |
| --- | --- | --- | --- |
| G1 合法证据、目标在区内 | ALLOW | ALLOW_IN_POLICY | **1** |
| G2 该 request_id 无证据 | BLOCK | — | **0** |
| G3 证据绑定 9.0/9.0，Goal 1.5/1.5 | BLOCK（`MISMATCH`） | — | **0** |
| G4 合法证据、目标越界 9.0/9.0 | **ALLOW** | **OUT_OF_REGION** | **0** |

G4 是双层独立性的关键证据：身份层通过并不能让越界目标被执行。

### 9.2 P01–P12 矩阵（真实状态）

| 场景 | 状态 | 依据/原因 |
| --- | --- | --- |
| P01 三真实正向 | **BLOCKED** | M1 无受信任 NORMAL；LEVEL3 BLOCKED |
| P02 M1 SUSPICIOUS | **NOT_VERIFIED** | 只有受控/Mock 路径，无真实 M1 SUSPICIOUS |
| P03 M1 UNKNOWN 阻断 | **PASS** | 三真实运行：M1 UNKNOWN → F0 BLOCK |
| P04 M2 签名无效 | **PASS** | Ed25519 篡改 → INVALID；F0 阻断 |
| P05 当前身份重放 | **PASS** | REPLAYED；F0/Gateway 均阻断 |
| P06 资源无权限 | **PASS** | DDS S3/S4；权限文件与策略一致 |
| P07 M3 建议阻断 | **PASS** | S5 OUT_OF_REGION；M3 验收回归通过 |
| P08 F0 READY 但目标越界 | **PASS** | Gateway G4：身份 ALLOW、策略 BLOCK、Goal 0 |
| P09 Planner TIMEOUT | **NOT_RUN** | 本轮未重跑；1.0.3 证据仍为参考 |
| P10 Gateway 拒绝/模块超时 | **PASS** | G2/G3 + 模块超时单测 |
| P11 request_id/摘要篡改 | **PASS** | G3 `MISMATCH` + 单测 |
| P12 配置/凭据缺失 | **PASS** | S6 不回退；F0 严格配置拒绝缺材料 |

合计：**PASS 9，BLOCKED 1，NOT_RUN 1，NOT_VERIFIED 1**。
不得用单一 `overall=PASS` 代替这张表。

## 10. 跨层执行与超时语义

- Gateway 在创建下游 Goal 前写 `RosCommEvent` 与唯一的 `DecisionEvent`；
  身份检查单独写 `GatewayIdentityCheck`，两层审计可分别对账。
- G2/G3 中 planner 未得到 `EXECUTED`，NavigationSim 无 Goal；G1 只有 1 条 Goal。
- **P09 未重跑**：Planner TIMEOUT 与取消/竞态语义仍以 1.0.3 的报告与 LIMITATIONS
  为准；本轮不宣称新增超时/取消证据。
- NavigationSim 仍是 `GOAL_RECORDED_ONLY` 语义；没有把它升级为
  `ACTION_LIFECYCLE_SIMULATED` 或 `NAVIGATION_SIMULATED`。

## 11. 科研对照实验

| 组 | 配置 | 本轮是否执行 | 关键结果 |
| --- | --- | --- | --- |
| Baseline A（1.0.3） | 冻结标签 `creative-work-v1.0.3` | 未重跑全部；历史证据保留 | 受控在线通过；DDS 1.0.3 NOT_RUN |
| Baseline B（1.1.0 受控模式） | `team_modules.three-real.yaml` | **执行** | LEVEL1/2 PASS，LEVEL3 BLOCKED |
| Enhanced C（1.1.0 身份+Gateway） | 研究域 45 + Ed25519 + Gateway 身份门 | **执行** | M2 17/17，Gateway 14/14 |
| Enhanced D（DDS Enforce） | domain 43 新 CA | **执行** | 7/7 正向 + 6/6 负向 |

可比性：B/C/D 使用同一 Action 接口、同一 TaskPolicy、同一 NavigationSim；
C/D 使用独立的 laboratory domain 与独立 keystore，没有为某组放宽任务难度。
Baseline A 未在本轮全量重跑，因此**不做**逐项同难度统计对比；只比较可核验的
能力与状态变化。

## 12. 量化结果

### 12.1 重复实验

`v110rep-20261021T195500Z`：30 次独立 trial（每次新 nonce、新账本）：

| 指标 | 结果 |
| --- | --- |
| 正向 Ed25519 验证成功 | 30/30（Wilson 95% 下界 0.886） |
| Gateway 独立门成功 | 30/30 |
| 负向对照（篡改签名/重放/错目标） | 3/3 |
| 失败数 | 0 |

延迟（组件级，非完整 DDS 端到端）：

| 阶段 | p50 | p95 | p99 | 均值 |
| --- | --- | --- | --- | --- |
| 签发 issue | 0.589 ms | 0.748 ms | 0.753 ms | 0.606 ms |
| 核验 verify | 1.416 ms | 1.589 ms | 1.943 ms | 1.459 ms |
| Gateway gate | 1.494 ms | 1.720 ms | 1.733 ms | 1.520 ms |

局限：30 次是**组件级**重复，不是 30 次完整 DDS 栈；完整栈只做了 1 次正向 + 1 次
负向矩阵。未把组件延迟外推为端到端延迟。

### 12.2 其他计数

| 实验 | 通过/总数 | Wilson 95% 下界 |
| --- | --- | --- |
| DDS Enforce 正向 | 7/7 | 0.646 |
| DDS 负向（带对照） | 6/6 | 0.610 |
| M2 真实 DDS 链 | 17/17 | 0.816 |
| Gateway 双层 | 14/14 | 0.785 |
| 身份单测（原 13 项） | 56/56 | 0.936 |

这些区间只描述“在本实验条件下重复成功的概率下界”，不构成生产可靠性证明。

## 13. 安全测试结果

| 测试 | 结果 | 证据 |
| --- | --- | --- |
| 信任根不匹配 | BLOCK | N1 |
| permissions 签名损坏 | BLOCK | N2 |
| 证书/目录错配 | BLOCK | N4 |
| Enforce 关闭对照 | 未授权客户端可执行 | N3（对照，不是安全通过） |
| 签名后 XML 篡改 | 新权限不生效 | N5 |
| 签名篡改/正文篡改 | INVALID | 单元 + 链 |
| nonce 重放 | REPLAYED | 单元 + 链 + Gateway |
| 过期/未来时间戳 | STALE/FROM_FUTURE | 单元 |
| 公钥不匹配/未知签发者 | KEY_MISMATCH/NOT_LISTED | 单元 |
| 私钥当公钥 | KEY_UNUSABLE | 单元 |
| 自报 `authenticated=true` | 不影响判定 | 既有 F0 测试 |
| 历史 AUTHORIZED 复用 | 资源不匹配 + 复用账本 | 既有测试 |
| 配置缺失 | 启动/请求失败关闭 | S6 + 配置校验单测 |

**没有**把“服务不可用”“进程崩溃”“配置错误”当作授权拒绝的成功证据；
每个拒绝场景都有同栈/同窗口正向对照或显式对照条件。

## 14. 完整独立复现（本轮实际范围）

本轮完成：

1. 在 `ros:jazzy` 派生容器内重新生成实验室 CA 与 enclave；
2. 全新 `colcon build`（4 包）；
3. 重跑 DDS Enforce 7 场景；
4. 重跑 6 个 DDS 负向场景；
5. 重跑 17 项真实 DDS 身份链；
6. 重跑 14 项 Gateway 双层判定；
7. 重跑三真实 LEVEL1/2 与负向；
8. 30 次组件重复；
9. 单测全量回归。

**未完成**：从新压缩包在独立目录/独立容器中完成“下载 → 校验 → 解压 → 构建 →
全链实验 → Web 展示 → 清理”的第三方式复现；也未在新的 host/CI 上复跑。
因此独立复现状态是 **PARTIAL**，不能写成 PASS。

## 15. 发布与证据溯源

| 项 | 值 |
| --- | --- |
| 1.0.3 附注标签对象 | `7b60b2890cc70925d9618d8f3c971035651c6789` |
| 1.0.3 指向提交 | `5773fb486c8eabdf7c0dfa039b600faabacffe75` |
| 1.1.0 工作分支 | `research/cross-layer-security-v1.1.0` |
| 测量时点提交 | `452f064d5b68234978dc8c235bda940d3466c761` |
| DDS 正向 manifest | `m2_sros2_enforce_v110/evidence_manifest.json`，SHA-256 `705e8e622f903d1ae9bf7375eb2c1dc176c0fbd8a0527922db14f2e5b5f9bac4` |
| DDS 负向 manifest | `m2_sros2_enforce_v110_negative/evidence_manifest.json`，SHA-256 `e26dfe75b6cefd901a088503fa9d1bc4a128513b8e705a5d076164929643a898` |
| M2 链 manifest | `m2_lab_identity_v110/evidence_manifest.json` |
| Gateway manifest | `m2_gateway_identity_v110/evidence_manifest.json`，SHA-256 `d16f732cb07f51d65660764ad10cc1d87e111586546258589ecfc81817aef86f` |
| P01–P12 矩阵 | `research_v110/p01_p12_matrix.json` |

1.0.3 标签、发布压缩包与历史证据未被修改；历史归档仍缺 `permissions.xml` 这一事实
由测试**断言保留**，没有追溯改写。

## 16. 生产就绪程度

| 维度 | 状态 | 说明 |
| --- | --- | --- |
| 研究级可复现 | 部分 | 本环境可复现；第三方新包复现未做 |
| 实验室安全验证 | **达到** | DDS 正负、M2 身份、Gateway 双层 |
| 生产身份签发 | **未达到** | 临时 CA、文件私钥、无 HSM、无吊销/轮换 |
| Action 请求级身份 | **未达到** | 意图主题绑定 ≠ Action send_goal 绑定 |
| 生产部署 | **未达到** | 无生产信任根/运维/授权环境 |
| 生产候选（LEVEL D） | **未达到** | 需要密钥生命周期、部署检查、更多威胁测试 |

**最终级别：LEVEL C — DDS_AND_IDENTITY_LAB_VERIFIED。**
不满足 LEVEL B（三真正向），不满足 LEVEL D/E（生产）。

## 17. 尚未解决的问题

1. **M1 正向**：验证门槛仍 false；缺 ≥20 正常会话、每类攻击 ≥5 独立会话与真实攻击复核。
2. **Action 级身份**：未订阅 `send_goal` 的 DDS 请求类型；当前证据绑定意图主题。
3. **Gateway 证据通道**：文件 side channel 不是协议内字段；文件系统在 TCB 内。
4. **M1 观测盲区**：被 DDS 拒绝的发送方无样本；缺观测必须是 UNKNOWN。
5. **P02/P09**：无真实 M1 SUSPICIOUS；Planner TIMEOUT/取消未在 1.1.0 重跑。
6. **Web 控制台**：1.1.0 证据尚未接入可视化。
7. **独立部署**：新压缩包未做独立目录/主机复现。
8. **生产密钥管理**：无 HSM、无吊销、无轮换、无独立 UID。
9. **DDS 负向覆盖**：未覆盖跨主机/跨 RMW/跨 DDS 实现。

## 18. 最终科研结论

1. **相比 1.0.3 提升了什么？**
   DDS Enforce 从“1.0.3 NOT_RUN、依赖缺失权限文件”变为新 CA 下 7/7 正向 + 6/6
   负向；M2 从对称 HMAC/默认 UNKNOWN 变为 Ed25519 + 公钥指纹 + 真实 DDS 观测；
   Gateway 从仅 TaskPolicy 变为身份 + 策略双层独立判定；13 项身份测试从失败变为
   56/56，且根因是补齐合法证据而不是放宽断言。
2. **三真实模块能否在可信证据下完成正向准入？**
   **本轮不能。** LEVEL1/2 PASS，LEVEL3 BLOCKED，阻断点是 M1 无受信任 NORMAL；
   M2 的 Lab 证据也无法绕过 M1。没有伪造正向。
3. **DDS Security 能否从新包在隔离实验环境独立运行？**
   本轮从源码在容器内重新生成 CA 并实跑成功；**从新发布压缩包**的独立运行尚未执行。
4. **当前请求身份是否真正被绑定并验证？**
   在**实验室范围、意图主题**上：是。真实 DDS writer → 证书主体 → 请求摘要 →
   Ed25519 → F0/Gateway 双层核验；重放/篡改/错主体/错目标均失败关闭。
   在 **Action send_goal 层、生产范围**：否，未证明。
5. **13 项身份失败是否实质解决？**
   是。根因是归档缺 `permissions.xml`；通过重新生成合法实验室证据 + 非秘密权限
   fixture + 回归测试解决，原断言未删除。
6. **是否具备论文可用的对照与统计证据？**
   具备**实验室组件级**对照、30 次重复、置信区间与完整证据哈希；不具备三真正向
   与生产对照，因此只能支撑“实验室跨层身份/授权”章节，不能支撑“生产级 IDS”。
7. **完成级别？**
   **LEVEL C**。
8. **哪些问题阻止生产验收？**
   M1 验证门槛、Action 级身份、生产信任根/HSM/吊销、独立部署复现、跨主机 DDS
   验证、Web 证据接入与完整生产威胁测试。

> 本报告不把“实验通过”推断为“具备生产级安全能力”。所有 PASS 都附带条件、
> 证据路径与适用范围；所有未执行项均保留为 BLOCKED / NOT_RUN / NOT_VERIFIED。
