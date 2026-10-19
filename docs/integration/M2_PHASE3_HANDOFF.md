# M2 第三轮交接说明

> 基准：`4741656c6f205d02b1f90a3bc73268839bb3be9a`
> 分支：`research/m2-action-origin-binding`
> 证据：`artifacts/research/m2-phase3/m2p3-20261019T033811Z/`

## 1. 本轮交付

| 文件 | 状态 | 作用 |
| --- | --- | --- |
| `src/m2_witness/m2_ingress_witness.cpp` | **新增** | 受保护前置入口：认证事件 + 请求级 writer→身份绑定 + JSONL 账本 |
| `scripts/m2_trusted_action_window.py` | **新增** | 账本 -> 30 秒历史计数窗口（含完整性水位） |

**未修改**：`scripts/team_demo.py`、`identity_trust/**`、Gateway、策略、DDS 正式权限。

## 2. 核心结论

1. **认证事件可观测但不能按 GUID 归因**：`ParticipantAuthenticationInfo` 只有 status。
   按 GUID 的身份归属必须走 `on_participant_discovery` 的 `identity_token_`。
2. **请求级绑定成立**：writer GUID（接收侧读出）→ participant GUID → 证书主体，
   两个不同证书客户端 5 条请求零串号。
3. **F0 因果问题用前置入口解决**：入口在 F0 之前，身份随请求到达即取得，
   不倒用 Gateway 后验结果。
4. **可信计数账本可用**：30 秒窗口 `count=5 / COMPLETE`，
   四类降级场景全部拒绝为 UNKNOWN/PARTIAL。

## 3. 仍未完成（交接时必须保留）

| 能力 | 状态 |
| --- | --- |
| 真实 Action send_goal 的 DDS 层捕获 | **BLOCKED**（缺 Action 请求 typesupport 接线） |
| 生产签发者（非对称密钥 + 独立 UID + 审批） | **FAIL**（仍为 HMAC 对称、同 UID） |
| Gateway 正向/阻断对照、M3 在线、DDS Enforce 回归 | **NOT_RUN** |
| 账本写端签名/链式哈希 | 未实现（依赖文件权限） |

## 4. 集成建议顺序

1. 先补 Action 请求 typesupport 接线，把 send_goal 也纳入同一绑定机制；
2. 再补账本防篡改（链式哈希或写端签名）；
3. 最后做签发者非对称化与独立 UID；
4. 完成后再跑 Gateway/Enforce/M3 全套回归，才可讨论 `M2_ONLINE_PROCEED_READY`。

## 5. 复现命令

```bash
# 编译
g++ -std=c++17 -O2 -I/opt/ros/jazzy/include -I/opt/ros/jazzy/include/fastrtps \
    -I/opt/ros/jazzy/include/fastcdr -DHAVE_SECURITY=1 \
    src/m2_witness/m2_ingress_witness.cpp -o /tmp/ingress \
    -L/opt/ros/jazzy/lib -lfastrtps -lfastcdr -lpthread

# 入口 + 两个不同证书客户端
LD_LIBRARY_PATH=/opt/ros/jazzy/lib ROS_DOMAIN_ID=60 /tmp/ingress --role ingress \
  --enclave m2_ingress --keystore $KS --resource rt/m2/candidate_task \
  --ledger events.jsonl --seconds 26 &
LD_LIBRARY_PATH=/opt/ros/jazzy/lib ROS_DOMAIN_ID=60 /tmp/ingress --role client \
  --enclave m2_client_a --keystore $KS --resource rt/m2/candidate_task \
  --goal-uuid aaaabbbbccccddddeeeeffff00001111 --payload 'client=A' --send 2

# 窗口聚合
python3 scripts/m2_trusted_action_window.py --ledger events.jsonl \
  --resource rt/m2/candidate_task --as-of <opened+34s> --window 30 --out window.json
```
