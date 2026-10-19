# M2 可信身份见证与凭据签发（专项③ P1）

> 代码：`src/m2_witness/m2_identity_witness.cpp`、`scripts/m2_issue_attestation.py`
> 证据：`artifacts/research/m2/m2api-20261018T160244Z/`

## 1. 组成

```
[Fast DDS 安全域]
   │  PKI-DH 认证
   ▼
C++ 见证组件 ── on_participant_discovery ──> identity_token_
   │                                          （原生证书主体）
   │ stdout JSON
   ▼
签发器 scripts/m2_issue_attestation.py
   │ 绑定 request_digest + nonce，HMAC-SHA256 签名
   ▼
witness.json（current-identity-attestation/2）
   │
   ▼
F0 STRICT：identity_trust/current_identity.py:verify()
   签名 → 请求绑定 → 新鲜度 → 签发者信任 → 原子 nonce 预留
```

## 2. 它证明了什么（精确表述）

| 命题 | 是否成立 |
| --- | --- |
| 某已认证 Participant 存在，且其证书主体为 X | **成立**（原生 `identity_token_`） |
| 该证据字节未被篡改 | **成立**（HMAC + 只有 F0 持有的核验密钥） |
| 该证据对应本次请求的 task/资源/目标 | **成立**（`request_digest` 绑定） |
| 该证据只能用一次 | **成立**（F0 侧原子 nonce 预留） |
| **该请求由该 Participant 发出** | **不成立** —— 绑定动作发生在受保护入口一侧 |

因此其安全语义是 **`TRUSTED_INGRESS_AUTHORIZED`**，
不是 **`DDS_REQUEST_ORIGIN_BOUND`**。

## 3. 签发器的失败关闭行为（实测）

- 见证日志里**没有**出现要求的主体 → `REFUSED`，拒绝签发；
- 非 32 位十六进制 nonce → `REFUSED`；
- 路径必须是绝对路径（由 F0 侧校验）；
- 密钥 0600（`current_identity.load_key` 拒绝更宽权限）。

## 4. 单一权威消费路径

nonce 的**唯一**权威消费点是 F0（`verify()` 内部 `Ledger.reserve_nonce`）。
签发器只生成 nonce，不消费；M2 分析器不接触该凭据。
若 M2 与 F0 指向同一 witness，F0 在配置校验阶段直接判
`ADAPTER_IDENTITY_ATTESTATION_CONFIG_INVALID`（已有回归用例覆盖）。

## 5. 密钥隔离的实际状态（诚实说明）

当前实现：签发器与 F0 使用**同一把 HMAC 密钥**（对称），文件权限 0600。

- **优点**：实现简单，F0 侧无需新增依赖；
- **缺点**：同 UID 的其他进程理论上可读该密钥；无法做到"签发者持有私钥、
  验证者只持公钥"。

**建议的下一步**（未在本轮实现）：改用 Ed25519 非对称签名，
签发器持私钥、F0 只持公钥，并把签发器放到独立 UID/容器。
本轮**不宣称**已具备该隔离能力。

## 6. 与 F0 的关系

F0 的 P0 修复（`4e83f91`）已经实现"不信任自报身份、自行核验原始证据"。
本专项**复用**该能力，未修改 `scripts/team_demo.py`，因此 P0 的 38 项安全
反例无需重跑即可保持有效（本轮仍执行了 38 项，全部通过）。

## 7. 限制清单

1. 请求与主体的绑定由受保护入口完成，属于信任假设，不是原生证据；
2. 密钥对称，同 UID 隔离不足；
3. 未实现 DDS 层 Action 订阅，因此无法证明原始发送者；
4. 见证组件未做长期运行的资源/异常管理（当前为短时观测原型）。
