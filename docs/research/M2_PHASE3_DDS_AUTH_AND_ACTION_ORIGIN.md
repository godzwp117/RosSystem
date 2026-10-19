# M2 第三轮：DDS 认证事件与请求级身份绑定

> 基准：`4741656c6f205d02b1f90a3bc73268839bb3be9a`
> 分支：`research/m2-action-origin-binding`
> run_id：`m2p3-20261019T033811Z`
> 证据：`artifacts/research/m2-phase3/m2p3-20261019T033811Z/`
> 环境：Fast DDS 2.14.6 / ROS 2 Jazzy，容器 `rg_m2p3`，**Domain 60**

---

## 1. 认证事件 API 实测结论

Fast DDS 2.14.6 提供 `DomainParticipantListener::onParticipantAuthentication`
（`DomainParticipantListener.hpp:107`），但其入参 `ParticipantAuthenticationInfo`
**只有 `status` 字段**（`AUTHORIZED_PARTICIPANT` / `UNAUTHORIZED_PARTICIPANT`），
**没有 GUID、没有身份主体**。

因此本轮实现选择：

| 需求 | 实现方式 |
| --- | --- |
| 认证状态变化事件 | `onParticipantAuthentication` 记录，标注 `guid_attributable=false` |
| **按 GUID 的认证身份** | `on_participant_discovery` 的 `identity_token_`（含证书主体） |
| 参与者退出后失效 | `REMOVED_PARTICIPANT` 时写 `PARTICIPANT_INVALIDATED` |

**不因为 `identity_token_` 非空就自动签发请求级结论** —— 见 §3。

## 2. 前置受保护入口（解决 F0 因果倒置）

F0 在 Planner/Gateway 之前运行，Gateway 收到的 SendGoal 是**后验**事件。
因此本轮实现 **Route A：F0 之前的受保护候选任务入口**：

```
已认证客户端 --DDS(自定义 CandidateTask)--> m2_ingress --JSONL--> 可信账本
                                              |
                                              +--> 供 F0/签发器绑定 request_digest + 身份
```

代码：`src/m2_witness/m2_ingress_witness.cpp`（已编译运行，见证据 `ingress.log`）。

### 2.1 请求级绑定实测

两个**不同证书**的客户端向同一入口发送请求：

| 客户端证书 | Participant GUID | Goal UUID | 请求数 | 被归属到的证书 |
| --- | --- | --- | --- | --- |
| `/CN=/m2_client_a` | `c3.4a.42.e2.fd…` | `aaaabbbb…` | 2 | **`/CN=/m2_client_a`** |
| `/CN=/m2_client_b` | `d6.8b.8c.81.cb…` | `11112222…` | 3 | **`/CN=/m2_client_b`** |

- Writer GUID 由接收侧 `SampleInfo::sample_identity.writer_guid()` 读出，
  **发送方无法伪造**；
- Writer GUID 前缀 = Participant GUID，据此查已认证身份；
- **零串号**：A 的请求没有任何一条被归到 B 的证书，反之亦然；
- 客户端退出后 `PARTICIPANT_INVALIDATED` 正确落账，旧身份不再可用。

### 2.2 DDS 原生权限拒绝（顺带验证）

首次运行时入口订阅 `/rg/candidate_task` 被 Fast DDS 原生拒绝：

```
[SECURITY Error] /rg/candidate_task topic not found in allow rule.
  (./src/cpp/security/accesscontrol/Permissions.cpp:1246)
```

说明最小权限**真实生效**。为完成实验，改用默认权限已允许的 `rt/*` 命名空间
（`rt/m2/candidate_task`），**没有放宽任何正式权限**（研究用 keystore 独立生成）。

## 3. 本轮证明了什么、没证明什么

| 命题 | 结论 |
| --- | --- |
| 已认证 Participant 的身份（证书主体）可得 | **成立**（第二轮已证，本轮复用） |
| 认证事件可观测 | **成立**，但**不能按 GUID 归因**（API 限制） |
| 样本的 Writer GUID 可得 | **成立** |
| Writer 属于哪个已认证 Participant | **成立** |
| 某条**候选任务请求**由该主体发出 | **成立**（本入口内逐条绑定） |
| 某条 **Action send_goal 请求**由该主体发出 | **未实现**（需 Action 请求类型 typesupport，见 §4） |
| 生产身份签发者就绪 | **未实现**（密钥仍对称、无独立 UID） |

## 4. 为什么没做 Action send_goal 的 DDS 层订阅

ROS 2 Action 的 `send_goal` 是**服务请求**，映射到 DDS 的 `rq/<service>` 主题，
类型为 `PatrolNavigate_SendGoal_Request`。要在原始 DDS 层订阅它需要：

1. 构建 `rg_interfaces` 生成该请求类型的 typesupport；
2. 在 C++ 中用 `rosidl_typesupport_fastrtps_cpp` 构造 `TopicDataType` 并链接；
3. 确认 rmw 生成的 DDS 主题名与 partition，避免与服务端 Reader 竞争。

本轮把时间用于先打通**同一绑定机制**（自定义类型已完整验证），
以上三点列为后续工作。**因此 `ACTION_SEND_GOAL_CAPTURED` 判 BLOCKED**，
不以"机制相同"冒充已完成。
