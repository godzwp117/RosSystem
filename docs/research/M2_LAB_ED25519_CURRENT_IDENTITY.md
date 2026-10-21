# M2 1.1.0：Ed25519 当前请求身份（LAB 范围）与真实 DDS 归属

> 代码：`identity_trust/current_identity.py`（v3 核验）、`identity_trust/lab_issuer.py`（TEST_ONLY 签发）、
> `src/m2_witness/m2_ingress_witness.cpp`（受信任 DDS 入口）、`scripts/team_demo.py`（F0 本地核验）
> 证据：`artifacts/acceptance/exports/m2_lab_identity_v110/`
> 环境：ROS 2 Jazzy / Fast DDS 2.14.6 / domain 45 / 容器 `rg_v110`
> 运行：`tests/integration/m2_lab_identity_chain.py --run-id <id>`，17/17 检查通过

## 1. 本轮的实质变化

| 项 | 1.0.3 / 1.1.0 基线 | 本轮 |
| --- | --- | --- |
| 签名算法 | HMAC-SHA256（对称，验证方持有同一密钥） | **Ed25519**（非对称，验证方只持公钥） |
| 信任锚 | 无受信任签发者清单，默认恒 UNKNOWN | 公钥按 **SHA-256 固定**在受信任清单；`scope: LAB` |
| 身份来源 | 无产生组件 | **真实 DDS 入口**：writer GUID → participant → `identity_token_` 证书主体 |
| 请求绑定 | 仅 request_id/resource/target 摘要 | 同上 + DDS 样本 payload 携带 `request_id|request_digest` |
| 防重放 | 原子 nonce 账本（已存在） | 保留；签发端逐条检查新鲜观测 |
| F0 接受 | 仅 `AUTHENTICATED` | 新增 `AUTHENTICATED_LAB`，**只有显式 `allow_lab_scope: true` 才接受** |
| 负向 | HMAC 篡改/重放/过期 | 增加：错误主体、篡改观测摘要、过期观测、公钥不匹配、私钥误用 |

## 2. 链路

```text
/planner 或 /operator 进程（真实证书）
        │  DDS rt/m2/candidate_task（payload = request_id|request_digest）
        ▼
m2_ingress（/witness enclave，受信任入口）
        │  SampleInfo.sample_identity().writer_guid()  ← 发送方无法伪造
        │  on_participant_discovery -> identity_token_ -> certificate_subject
        ▼
intent_events.jsonl（trusted-action-events/1）
        │  逐条：sender_authenticated=true, certificate_subject, payload, received_at
        ▼
lab_issuer.py（Ed25519 私钥，TEST_ONLY）
        │  重算 envelope 的 request_digest，与观测 payload 比对
        │  检查主体、goal UUID 约定、观测新鲜度
        ▼
attestation v3（body + ed25519 signature）
        │
        ├── current_identity.verify()：公钥指纹固定 + 签名 + 绑定 + 新鲜度 + nonce 预留
        └── F0（team_demo.py）：本地再次核验，`allow_lab_scope` 才放行
```

## 3. 本轮真实测得的事实

- 两个**不同证书**的参与者在同一受保护主题上发送请求，账本分别归属到
  `/CN=\/planner` 与 `/CN=\/operator`，**零串号**；
- writer GUID 前缀 = participant GUID，由接收侧填充；
- `/rogue` 身份没有该主题的发布权限，`create_datawriter` 失败（退出码 6），
  账本中**没有**它的样本；
- 合法请求得到 `AUTHENTICATED_LAB`，五项检查均为 `VALID/MATCH/OK/RESERVED`；
- 同一 nonce 第二次核验 → `REPLAYED` → UNKNOWN；
- 错误主体 / 篡改观测摘要 / 过期观测 → 签发端拒绝；
- 篡改签名 → 核验 `INVALID`；
- F0 在真实证据上达到 `READY_FOR_GATEWAY_SUBMISSION`，重放同一证据被阻断；
- 私钥在归档前删除，证据目录不含任何私钥或证书。

## 4. 必须原样保留的边界

1. **attested resource 是预准入意图主题，不是 ROS Action `send_goal` 服务请求。**
   本轮证明了"writer GUID → 已认证证书主体 → 该条请求内容"的绑定机制在真实
   DDS 上成立；没有证明后续 Action `send_goal` 由同一主体发出。Action 服务
   请求的 DDS 类型为 `PatrolNavigate_SendGoal_Request_`，需要 typesupport 接线，
   列为未完成项。
2. **LAB 不等于生产。** 信任根是临时实验室 CA，签发者密钥在本机文件中，
   没有 HSM、没有生产 CA、没有证书吊销/轮换流程、没有独立 UID 隔离。
   因此不得声称"生产身份认证通过"。
3. **F0 的接受是按配置显式开启的。** 默认（以及所有历史配置）仍然是
   `allow_lab_scope: false`，LAB 状态被拒绝；没有把任何既有严格路径放宽。
4. **Gateway 尚未独立核验该证据。** 本轮只做到 F0 本地核验；Gateway 的
   TaskPolicy 仍是独立业务判定，但"身份 + 策略"的联合授权尚未接线。
5. **观测盲区**：被 DDS 访问控制拒绝的发送方不会产生样本，因此 M1 不能把
   "没有样本"当作"通信正常"；缺观测必须是 UNKNOWN。

## 5. 密钥与清理

```bash
# 生成（TEST_ONLY；输出目录必须被 .gitignore 覆盖）
python3 identity_trust/lab_issuer.py --i-am-a-lab-issuer gen-key \
    --key-dir /path/to/lab-keys --issuer-id lab-ed25519-ingress-1
# 签发（要求真实观测账本中存在对应请求）
python3 identity_trust/lab_issuer.py --i-am-a-lab-issuer issue \
    --key-dir /path/to/lab-keys --envelope env.json \
    --ledger intent_events.jsonl --out attestation.json \
    --require-subject '/CN=\/planner'
# 清理
python3 identity_trust/lab_issuer.py --i-am-a-lab-issuer purge --key-dir /path/to/lab-keys
```

- 私钥 `issuer.key.pem` 权限 `0600`，公钥 `issuer.pub.pem` 可公开；
- `security/lab/` 与 `artifacts/research/**/keystore/` 已被 `.gitignore` 排除；
- 证据归档只保留公钥、受信任清单、账本、attestation 与日志。

## 6. 未完成 / 下一步

1. 把 Action `send_goal` 的 DDS 请求类型接入受信任入口（typesupport），
   将"意图绑定"升级为"Action 请求绑定"；
2. Gateway 端独立核验身份证据 + TaskPolicy，形成双层授权；
3. 在生产信任根、HSM/密钥生命周期、撤销与轮换具备后，才讨论
   `PRODUCTION_CANDIDATE`；
4. M1 的 NORMAL 仍受数据集与真实攻击证据阻断（见 M1 各专项报告）。
