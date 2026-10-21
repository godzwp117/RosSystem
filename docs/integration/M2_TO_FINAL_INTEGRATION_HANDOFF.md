# M2 交付给最终集成的交接说明

> `RESEARCH_BASE_SHA` = `be47ccd6c1b19460b65abc0ea8004706383d01d4`
> 本分支：`research/m2-current-identity`
> 证据：`artifacts/research/m2/m2api-20261018T160244Z/`

## 1. 本次交付的代码

| 文件 | 状态 | 作用 |
| --- | --- | --- |
| `src/m2_witness/m2_identity_witness.cpp` | **新增** | C++ 见证组件：从 `ParticipantProxyData::identity_token_` 观察 DDS 原生已认证身份 |
| `scripts/m2_issue_attestation.py` | **新增** | 用真实观察到的身份签发 F0 可核验凭据（找不到主体则拒绝签发） |
| `tests/integration/m2_identity_experiments.py` | **新增** | M2-01b..M2-11 端到端安全实验矩阵 |

**未修改**：`scripts/team_demo.py`、`identity_trust/**`、任何 Gateway/策略/DDS 权限。
因此 F0 P0 的 38 项反例本轮仍 38/38 通过（已复跑确认）。

## 2. 核心结论

**DDS 原生已认证身份在应用层是**可以**取得的**——通过
`DomainParticipantListener::on_participant_discovery` 里的
`ParticipantProxyData::identity_token_`（public 成员）。
实测拿到 `DDS:Auth:PKI-DH:1.0` + `dds.cert.sn=/CN=\\/m2_peer` + `dds.ca.sn=/CN=sros2CA`。

## 3. 集成时需要做的（尚未做）

1. **把见证组件变成 ROS 2 包**：当前是独立 g++ 程序，集成时应做成
   `rclcpp` 组件或独立 sidecar，并纳入 `colcon` 构建。
2. **实现请求级绑定**：订阅 Action goal 话题，取
   `SampleInfo.sample_identity().writer_guid()` → participant GUID →
   `identity_token_`，从而把"这条请求"与"该已认证主体"直接绑定。
   这是从 `TRUSTED_INGRESS_AUTHORIZED` 升级到 `DDS_REQUEST_ORIGIN_BOUND` 的**唯一**路径。
3. **密钥非对称化**：当前 HMAC 对称密钥同时被签发器与 F0 持有；
   建议改 Ed25519，签发器持私钥、F0 只持公钥，并把签发器放到独立 UID/容器。
4. **签发者审批流程**：受信任清单里的 `reviewed_by` 目前是研究占位值，
   生产需要真实审批记录。

## 4. 验收分级

见 `docs/research/M2_END_TO_END_SECURITY_EXPERIMENTS.md` 与最终报告。

## 5. 复现命令

```bash
# 编译见证组件（容器 rg_m2 内）
g++ -std=c++17 -O2 -I/opt/ros/jazzy/include -I/opt/ros/jazzy/include/fastrtps \
    -I/opt/ros/jazzy/include/fastcdr -DHAVE_SECURITY=1 \
    src/m2_witness/m2_identity_witness.cpp -o /tmp/witness \
    -L/opt/ros/jazzy/lib -lfastrtps -lfastcdr -lpthread

# 两个已认证 Participant 互相发现
LD_LIBRARY_PATH=/opt/ros/jazzy/lib ROS_DOMAIN_ID=58 /tmp/witness --role m2_probe --keystore $KS --seconds 14 &
LD_LIBRARY_PATH=/opt/ros/jazzy/lib ROS_DOMAIN_ID=58 /tmp/witness --role m2_peer  --keystore $KS --seconds 8

# 端到端实验
./.research-venv/bin/python tests/integration/m2_identity_experiments.py \
  --evidence <dir> --witness-log <dir>/witness_probe.log \
  --key <dir>/issuer.key --identity '/CN=\\/m2_peer'
```

## 6. 不得据此宣称

- ❌ 已证明"某条 Action 请求由某 DDS 主体发出"（`DDS_REQUEST_ORIGIN_BOUND` 仍 BLOCKED）
- ❌ 生产级签发者已就绪（无审批、密钥对称、无独立 UID）
- ❌ M2 已可让三真实模块 LEVEL 3 通过（M1 仍未就绪）
