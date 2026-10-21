# M2 1.1.0：Gateway 独立身份 + 业务双层授权

> 代码：`src/rg_gateway/rg_gateway/identity_gate.py`、`security_gateway.py`
> 证据：`artifacts/acceptance/exports/m2_gateway_identity_v110/`
> 环境：ROS 2 Jazzy / Fast DDS / domain 45 / research keystore / 容器 `rg_v110`
> 运行：`tests/integration/gateway_identity_lab.py --run-id <id>`，**11/11 通过**

## 1. 为什么 Gateway 必须再判一次

F0 的 `READY_FOR_GATEWAY_SUBMISSION` 只表示“可以提交”，不表示“可以执行”。
1.0.3 的 Gateway 只做 TaskPolicy 判定；1.1.0 增加第二条独立判据：

```text
F0: 证据核验 + 三模块联合准入          Gateway: 身份证据再核验 + TaskPolicy
        │                                        │
        └────── READY (可提交) ──────────────────┘
                                                 │
                                           ALLOW (可执行) → NavigationSim
```

两层使用**各自的 nonce 账本**，同一请求在两层各消费一份新鲜证明；F0 的消费
不会让 Gateway 误判为重放，反之亦然。Gateway 不读取 F0 的判定结果作为身份依据。

## 2. 实现

`identity_gate.verify_goal(goal, ...)`：

1. 用 Action Goal 的 `request_id/task_id/frame_id/x/y/z` 重建被摘要覆盖的字段；
2. 从受信任配置的 `identity_attestation_dir/<request_id>.json` 读取证据
   （`request_id` 必须匹配安全文件名；符号链接拒绝）；
3. 调用 `identity_trust.current_identity.verify()`：Ed25519 签名 + 公钥指纹固定
   + 签发者 scope + 请求绑定 + 新鲜度 + Gateway 自己的原子 nonce 预留；
4. `checks` 五项全部成立且 `trust_scope=LAB` 时，才 `ALLOW`；否则 `BLOCK`。

`security_gateway.py` 新增参数（默认关闭，保持 1.0.3 行为）：

```text
identity_attestation_dir     证据目录（绝对路径；空 = 关闭）
identity_public_key          Ed25519 公钥（PEM）
identity_issuers             受信任签发者清单（含 scope=LAB 与公钥 SHA-256）
identity_nonce_ledger        Gateway 自己的重放账本
identity_allow_lab_scope     是否接受 LAB 范围（默认 false）
identity_audit_path          独立的 GatewayIdentityCheck JSONL
```

启用后**没有静默回退**：目录/公钥/清单/账本缺失会在启动时失败；每次请求的
身份审计写失败也会阻断 Goal。

## 3. 真实结果

| 场景 | 证据 | Gateway 判定 | 下游 Goal |
| --- | --- | --- | --- |
| G1 证据有效、目标在策略内 | 真实 DDS 入口观测 + Ed25519 | `ALLOW_IN_POLICY` | **1** |
| G2 该 request_id 无证据 | 目录中无文件 | `IDENTITY_ATTESTATION_REJECTED` | **0** |
| G3 证据绑定 9.0/9.0，Goal 为 1.5/1.5 | 摘要不匹配 | `IDENTITY_ATTESTATION_REJECTED` | **0** |

G1 的 `GatewayIdentityCheck` 记录：

```json
{"request_id":"req-gw-lab-001","decision":"ALLOW",
 "status":"AUTHENTICATED_LAB","scope":"LAB",
 "checks":{"signature":"VALID","issuer":"VERIFIED_LAB_IDENTITY_SOURCE",
           "request_binding":"MATCH","freshness":"OK","replay":"RESERVED"}}
```

G3 的 `request_binding` 为 `MISMATCH`；G2 的 `status` 为 `null`（没有证据）。
planner 在 G2/G3 均未得到 `EXECUTED`，NavigationSim 只收到 G1 的一条 Goal。

## 4. 边界（不得省略）

1. 这是**实验室**信任根与 LAB scope；不是生产身份认证。
2. 证据经 side channel（按 request_id 命名的文件）送达 Gateway，因为冻结的
   Action 接口没有签名字段。文件的完整性与新鲜度由 Ed25519 证据和 Gateway 的
   nonce 账本保证，但文件系统仍是受信任计算基的一部分。
3. 被 DDS 访问控制拒绝的请求不会产生观测证据；这类请求在 Gateway 侧同样会被
   “无证据”阻断，但**不能**把它解释成“身份已核验且授权”。
4. 仍未证明后续 Action `send_goal` 的 DDS 写入者与意图提交者是同一主体；
   见 `M2_LAB_ED25519_CURRENT_IDENTITY.md` 的未完成项。
5. Gateway 的 TaskPolicy 判定逻辑未被修改；身份门只会在策略之上增加阻断，
   不存在“身份通过就绕过策略”的路径。

## 5. 复现

```bash
scripts/setup_m2_ingress_lab.sh                 # 研究域 45 的 TEST_ONLY keystore
docker exec rg_v110 bash -lc 'cd /ws && source /opt/ros/jazzy/setup.bash && \
  source install/setup.bash && \
  python3 tests/integration/gateway_identity_lab.py --run-id <new-id>'
python3 scripts/archive_dds_evidence.py --run-dir tests/evidence/<new-id> \
  --out-dir artifacts/acceptance/exports/m2_gateway_identity_v110 \
  --keystore artifacts/research/v110/m2-ingress/keystore \
  --policy security/policies/research/m2_ingress_lab.xml --expected-domain 45
```

复跑必须使用新的 run-id 与新的 nonce 账本；复用旧证据会（正确地）被判重放。
