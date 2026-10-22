# 论文创新点（仅限有证据的部分）

> 每个贡献都给出实现位置、实验和**不能**声称的边界。Action 级身份与 M1 正向
> 不列为已完成贡献。

## C1. 从 DDS 认证主体到应用请求的可验证证据桥接（意图主题）

**问题**：DDS-Security 只证明参与者证书，不自动证明“当前应用请求由该主体发出”；
ROS 2 Jazzy 订阅端不暴露样本发布者身份。

**实现**：
- `src/m2_witness/m2_ingress_witness.cpp`：接收侧读取
  `SampleInfo::sample_identity().writer_guid()`，用 GUID 前缀查
  `on_participant_discovery` 的 `identity_token_`，得到证书主体；
- payload 携带 `request_id|request_digest`，入口独立校验；
- `artifacts/acceptance/exports/m2_lab_identity_v110`：两个不同证书的客户端，
  账本零串号；`/rogue` 无发布权限，不产生样本。

**证据**：17/17；`m2_lab_identity_v110`；论文可写“意图主题上的
writer→subject→content 绑定在实验室 DDS 中成立”。

**边界**：不是 Action `send_goal`；不是生产身份；被 DDS 拒绝的发送方不可见。

## C2. Ed25519 当前请求证明与失败关闭（LAB scope）

**实现**：
- `identity_trust/current_identity.py` v3：公钥 DER SHA-256 固定在受信任清单，
  scope 只来自清单；
- 请求绑定覆盖 `request_id/resource/operation/task_id/target.frame_id,x,y,z`；
- 新鲜度窗口、原子 nonce 账本（`flock` + 重读-判重-追加-fsync）；
- `lab_issuer.py` 只在真实观测通过后签发；`AUTHENTICATED_LAB` 与
  `AUTHENTICATED` 严格分离，F0 默认拒绝 LAB。

**证据**：M2 17/17；30/30 组件重复；篡改/重放/过期/错主体/错目标均失败关闭；
`paper/STATISTICAL_ANALYSIS.md` 延迟 p50 1.40 ms。

**边界**：实验室 CA、文件私钥；不是生产 PKI/HSM；不是 Action 级。

## C3. F0 与 Gateway 的双层独立授权

**问题**：F0 READY 不等于 Gateway ALLOW；单层授权会把“可提交”误当“可执行”。

**实现**：
- F0：`team_demo.py` 用受信任材料**自行核验**，不读模块自报；
- Gateway：`identity_gate.py` 重建 Goal 的摘要字段，用**自己的**公钥/清单/
  nonce 账本再核验，再交给未修改的 TaskPolicy；
- `GatewayIdentityCheck` 与 `DecisionEvent` 分开审计。

**证据**：14/14；G1 ALLOW/1 Goal；G2/G3 BLOCK/0；G4 身份 ALLOW 但
TaskPolicy `OUT_OF_REGION`/0。P08 因此有直接证据。

**边界**：证据经文件 side channel；非 Action 协议内字段；LAB scope。

## C4. 可复现的 DDS 安全实验室：正负对照 + 非秘密证据归档

**实现**：
- `scripts/setup_sros2.sh` 生成实验室 CA/enclave/签名权限；
- `scripts/archive_dds_evidence.py` 归档运行日志 + 生成 `permissions.xml`
  + 证书主体 + CA 指纹 + 文件哈希 + 命令/退出码，**不含私钥/证书**；
- `dds_lab_negative.py` 6 个负向，每项带同栈正向对照。

**证据**：7/7 + 6/6；N5 实测“签名后改 permissions.xml 不生效”；
N1 不同 CA 拒绝；N3 Enforce-off 对照显示未授权客户端可执行。

**边界**：临时实验室 CA；未覆盖跨主机/跨 RMW；不是生产部署。

## C5. 证据优先的科研方法：主动纠错与负结果

**实现/结果**：
- 发现 P07 原 PASS 把 Gateway TaskPolicy 阻断当作 M3 建议阻断，发布 erratum，
  用真实 M3 隔离实验重新验证（13/13），并保留独立 Gateway 结论；
- 13 项身份测试失败根因是归档缺 `permissions.xml`，用非秘密 fixture 修复，
  不跳过/不放宽断言；
- Action 原始 DDS 订阅导致 `NO_ACTION_SERVER`，如实记为负结果，不把意图证据
  改名。

**价值**：这些是论文 Threats to Validity / 工程可复现性的直接材料，而不是
“全部 PASS”的装饰。

## 不应列为创新成果的内容

- Action `send_goal` 请求级身份（NOT_VERIFIED）；
- M1 生产级 IDS 或受信任 NORMAL（gate=false）；
- 三真正向 LEVEL3（BLOCKED）；
- 生产 CA/HSM/撤销/轮换（未实现）；
- 实体机器人导航（NavigationSim 只是 recorded_only 存根）。
