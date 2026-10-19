# 可信 Action 事件交接给 M1

> 来源：M2 第三轮，分支 `research/m2-action-origin-binding`
> run_id：`m2p3-20261019T033811Z`
> 证据：`artifacts/research/m2-phase3/m2p3-20261019T033811Z/`

## 1. 事件从哪里产生

受保护前置入口 `src/m2_witness/m2_ingress_witness.cpp`（C++，Fast DDS 直连），
在**F0 之前的独立入口**上接收候选任务请求，逐条写 JSONL 账本。

它运行在真实的 **DDS-Security Enforce** 环境（研究用独立 keystore，Domain 60）。

## 2. 能不能关联发送方

**能，且已验证**：每条 `SEND_GOAL_RECEIVED` 事件带

- `writer_guid`：接收侧从 `SampleInfo::sample_identity.writer_guid()` 读出，不可伪造；
- `participant_guid`：writer GUID 前缀；
- `certificate_subject` / `ca_subject`：该 participant 的 DDS 认证证书主体；
- `sender_authenticated`：该 writer 所属 participant 当时是否有有效认证记录。

实测：两个不同证书的客户端共 5 条请求，归属零串号。

## 3. 计数是否可信

| 问题 | 回答 |
| --- | --- |
| 计数来源 | 受信任入口**实际收到**的样本，不由业务 JSON 声明 |
| 会不会把 Gateway ALLOW 数当请求数 | 不会。账本只记录入口收到的请求 |
| 重试如何计 | 每次重试是新 `goal_uuid`，按条计数，不合并 |
| 能否区分未认证请求 | 能，`unauthenticated_requests` 字段 |

## 4. 30 秒窗口与完整性

用 `scripts/m2_trusted_action_window.py` 聚合：

```json
{"contract":"trusted-action-count-window/1","window_start":"...","window_end":"...",
 "send_goal_count":5,"coverage":"COMPLETE","source_evidence_sha256":"..."}
```

**窗口何时才算完成**：

- `window_end = as_of - safety_lag`（默认 2 秒），用于吸收写盘延迟；
- 只有当整个窗口落在账本覆盖范围内（不早于 `INGRESS_OPENED` 水位）才是 `COMPLETE`；
- 账本有损坏行为 `PARTIAL`；账本缺失/无事件/窗口早于水位为 `UNKNOWN`。

## 5. 防止当前请求的未来结果泄漏

窗口严格取 `[as_of - lag - 30s, as_of - lag)`，
**不含**当前请求在 Gateway 的后续决策与执行结果。
账本里也根本不存在这些字段——它们从来不被写入。

## 6. 如何查询与校验

```bash
python3 scripts/m2_trusted_action_window.py \
    --ledger events.jsonl --resource <resource> \
    --as-of <RFC3339> --window 30 --out window.json
sha256sum events.jsonl     # 与 window.json 的 source_evidence_sha256 比对
```

## 7. M1 只读约束

M1 **只能读**账本与窗口输出，**不得写入**。
账本由入口进程以追加方式写；M1 侧不应持有写权限（部署时应以文件权限强制）。

## 8. 缺失/延迟如何处理

| 情况 | M1 必须怎么做 |
| --- | --- |
| `coverage != COMPLETE` | 当作 UNKNOWN，**不得当作 0 次请求** |
| `count` 为 `null` | 当作 UNKNOWN |
| 账本不存在 | 当作 UNKNOWN |
| 窗口早于 `INGRESS_OPENED` | 当作 UNKNOWN |

## 9. 给 M1 的明确建议

**必须依据新的 Action 事件来源重新采样真实正常与异常数据。**

第三轮 M1 已经证明上一轮模型的有效性结论不成立：
`duration_ms` 在训练集里几乎等于标签（三类落在互不重叠的窄带，权重 −10.6），
去掉该特征后未见攻击类别那一折 F1 只有 0.32/0.57，低于基线 0.666。

因此：

1. **禁止**直接复用 `comm_risk_window_model.json`；
2. 用本账本的 `action_send_goal_count` 作为**新的、语义明确**的计数特征，
   **不要**把它塞回旧的 `request_count` 字段冒充原模型输入；
3. 重新采集时固定窗口契约（30 秒），并在训练前显式排除与标签共线的特征
   （窗口时长、资源名、segment id）；
4. 每类至少数十个独立采集会话，再谈泛化。

## 10. 当前限制（必须一并告知 M1）

- 本账本记录的是**入口收到的候选任务请求**，不是 Gateway 的 Action `send_goal`
  （后者需要 Action 请求类型 typesupport，尚未接线）；
- 账本未做写端签名，防篡改依赖文件权限；
- 未做并发压测。
