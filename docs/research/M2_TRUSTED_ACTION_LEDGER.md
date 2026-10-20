# M2 第三轮：可信 Action 事件账本（供 M1 使用）

> 代码：`src/m2_witness/m2_ingress_witness.cpp`（产生事件）、
> `scripts/m2_trusted_action_window.py`（窗口聚合）
> 证据：`artifacts/research/m2-phase3/m2p3-20261019T033811Z/{events.jsonl,window_complete.json}`

## 1. 事件契约 `trusted-action-events/1`

账本为 JSONL，每行一个事件，由**受信任入口**写入（M1 只读）。

```json
{"contract":"trusted-action-events/1","event_kind":"SEND_GOAL_RECEIVED",
 "resource":"rt/m2/candidate_task","goal_uuid":"...","request_digest":"...",
 "task_code":1001,"payload":"client=A","writer_guid":"...|...",
 "participant_guid":"...","sample_sequence":1,"sender_authenticated":true,
 "certificate_subject":"/CN=\/m2_client_a","ca_subject":"/CN=/sros2CA",
 "received_at":"2026-10-19T03:40:12.345Z","source":"TRUSTED_ACTION_INGRESS",
 "observer":"M2_TRUSTED_INGRESS"}
```

其它 `event_kind`：`INGRESS_OPENED`（覆盖起点水位）、
`PARTICIPANT_AUTHENTICATED`、`PARTICIPANT_AUTH_EVENT`（`guid_attributable=false`）、
`PARTICIPANT_INVALIDATED`。

## 2. 计数窗口契约 `trusted-action-count-window/1`

```json
{"contract":"trusted-action-count-window/1","resource":"...",
 "window_start":"...","window_end":"...","as_of":"...",
 "send_goal_count":5,"observation_source":"TRUSTED_ACTION_INGRESS",
 "coverage":"COMPLETE","source_evidence_sha256":"...",
 "authenticated_senders":["/CN=\/m2_client_a","/CN=\/m2_client_b"],
 "unauthenticated_requests":0,"notes":[...]}
```

### 因果约束

`window_end = as_of - safety_lag`（默认 2 s）。
M1 在 F0 之前判断，**只能消费已结束窗口**；当前请求在 Gateway 的后续结果
不进入任何计数。

### 覆盖度（coverage）

| 取值 | 含义 | M1 应如何用 |
| --- | --- | --- |
| `COMPLETE` | 窗口完整落在账本覆盖范围内且已过安全滞后 | 可作为计数特征 |
| `PARTIAL` | 账本有不可解析行 | **不得当作 0**，应降级为 UNKNOWN |
| `UNKNOWN` | 账本缺失 / 无该资源事件 / 窗口早于账本起点 | **必须当作 UNKNOWN** |

## 3. 实测：完整窗口

```
as_of=2026-10-19T03:40:34Z  window=[03:40:02, 03:40:32)
send_goal_count=5  coverage=COMPLETE
authenticated_senders=["/CN=\/m2_client_a","/CN=\/m2_client_b"]
```

## 4. 实测：四类降级场景（全部正确拒绝）

| 场景 | 结果 | 说明 |
| --- | --- | --- |
| 账本被截断（只留前 3 行） | `count=0, coverage=UNKNOWN` | 不得断言为 0 次请求 |
| 账本文件不存在 | `count=null, coverage=UNKNOWN` | 明确 null 而非 0 |
| 混入损坏行 | `count=5, coverage=PARTIAL` | 覆盖不完整仍计数但标注 |
| 请求错误的 resource | `count=0, coverage=UNKNOWN` | 不能跨资源复用 |

## 5. 计数语义边界（必须写清）

- 只统计**受信任入口实际收到**的请求样本；
- 区分：`send_goal_count`（收到多少条）、
  `unauthenticated_requests`（其中多少条没通过身份查询）、
  `authenticated_senders`（出现过哪些已认证主体）；
- **不包含**：Gateway ALLOW 数、NavigationSim Goal 数、执行成功数；
- 重试会产生新的 goal_uuid，按条计数，不合并。

## 6. 未完成

- 账本未做写端签名/链式哈希，防篡改依赖文件系统权限；
- 未实现并发写入的显式锁（依赖 O_APPEND 单行原子性）；
- 未接入真实 Action send_goal（见 M2_PHASE3_DDS_AUTH_AND_ACTION_ORIGIN.md §4）。
