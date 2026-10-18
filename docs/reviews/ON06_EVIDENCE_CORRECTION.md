# ON-06 证据勘误说明（2026-10-16 → 2026-10-17 修订）

> 本文记录一次**真实的报告事实错误**、其原始证据、正确结论、修复范围、
> 复发防护测试与安全含义。
> 原始日志未被修改；被修改的只有**报告文本**与**校验能力**。

---

## 1. 被发现的矛盾

2026-10-16 的在线联调收尾报告
（`docs/reviews/M3_ONLINE_INTEGRATION_CLOSEOUT_20261016.md`）
把 **ON-06（Planner 超时）** 场景表述为：

- Gateway **无决策**
- Gateway **无事件**
- NavigationSim Goal 为 **0**
- "未完成提交"

**同一份报告内部还自相矛盾**：其 §9 又写"全 run 共 2 条 Goal（分别属于 ON-01 与另一次
ON-06 的受理；ON-06 的 Goal 记录存在但无 ExecutionEvent）"。

---

## 2. 原始证据（事实依据）

- 证据目录：`artifacts/demo-2026-10-19/m3-online-m3online-20261016T134406Z/`
- `run_id`：`m3online-20261016T134406Z`
- ON-06 的 `request_id`（取自 `manifest.json`）：**`on06-m3online-20261016T134406Z`**
- 关联方式：**按 `request_id` 精确匹配**，不使用文件总行数推断单场景结果

### 2.1 `f0_ON06.json`

| 字段 | 值 |
| --- | --- |
| `decision` / `reason_code` | `READY_FOR_GATEWAY_SUBMISSION` / `ADAPTER_OK` |
| `request_id` | `on06-m3online-20261016T134406Z` |
| `run_id` | `m3online-20261016T134406Z` |
| M3 状态 | `ALLOW_RECOMMENDED`（`schema_ok=true`） |
| `online.outcome` | **`PLANNER_RESULT_TIMEOUT`** |
| `online.planner_exit_code` | `null` |
| `online.planner_result` | `null` |
| `online.detail` | "Planner 在 0.5s 内未给出终态。**该请求可能已经到达 Gateway，甚至已到达下游执行端**；不自动重试、不新建 request_id、不记为 Gateway BLOCK。请依据 Gateway 审计记录核对。" |

### 2.2 `gateway_audit.jsonl`（该 `request_id` 的 3 条事件）

| # | `event_type` | 关键字段 | 时间 |
| --- | --- | --- | --- |
| 1 | `RosCommEvent` | target=(1.5, 1.5) | `2026-10-16T13:44:16.261Z` |
| 2 | `DecisionEvent` | **`ALLOW`** / `ALLOW_IN_POLICY` | `2026-10-16T13:44:16.262Z` |
| 3 | `ExecutionEvent` | `success=true` / `EXECUTED` | `2026-10-16T13:44:16.266Z` |

### 2.3 `navsim_goals.jsonl`（该 `request_id` 的 1 条 Goal）

| `goal_id` | target | 时间 |
| --- | --- | --- |
| `f430a6e0af3943a0a540166d58384688` | (1.5, 1.5) | `2026-10-16T13:44:16.264Z` |

### 2.4 `verification.json`（独立复核工具的原始输出）

```json
{
  "cid": "ON06",
  "request_id": "on06-m3online-20261016T134406Z",
  "adapter_decision": "READY_FOR_GATEWAY_SUBMISSION",
  "m3_status": "ALLOW_RECOMMENDED",
  "planner_outcome": "PLANNER_RESULT_TIMEOUT",
  "planner_started": true,
  "gateway_arrivals": 1,
  "gateway_decisions": [{"decision": "ALLOW", "reason_code": "ALLOW_IN_POLICY"}],
  "gateway_executions": 1,
  "navsim_goals": 1
}
```

**关键判断：原始日志与复核工具本身都是正确的。错误完全出在人工书写的报告文本里。**

---

## 3. 正确事实

| 项目 | 正确值 |
| --- | --- |
| M3 状态 | `ALLOW_RECOMMENDED` |
| F0 决策 | `READY_FOR_GATEWAY_SUBMISSION` |
| Planner 结果 | `PLANNER_RESULT_TIMEOUT`（客户端未在 0.5s 内观测到终态） |
| Gateway 到达次数 | **1** |
| Gateway DecisionEvent | **`ALLOW` / `ALLOW_IN_POLICY`** |
| Gateway ExecutionEvent | **1**（`success=true` / `EXECUTED`） |
| NavigationSim Goal | **1** |

### 3.1 本次 run 的完整计数（全部按 request_id 归属）

| request_id | RosComm | Decision | Execution | Goal |
| --- | --- | --- | --- | --- |
| `on01-legal-allow-…` | 1 | 1（ALLOW/ALLOW_IN_POLICY） | 1 | 1 |
| `on05-gateway-authority-…` | 1 | 1（**BLOCK**/OUT_OF_REGION） | 0 | 0 |
| `on06-…` | 1 | 1（ALLOW/ALLOW_IN_POLICY） | 1 | 1 |
| ON-02 / ON-03 / ON-04 | 0 | 0 | 0 | 0 |
| **合计** | **3** | **3** | **2** | **2** |

与原始文件总计一致：`gateway_audit.jsonl` **8 行**（3+3+2），
`navsim_goals.jsonl` **2 行**（ON-01 与 ON-06 各 1）。

---

## 4. 正确的安全含义

1. **Planner 等待超时 ≠ Gateway 未收到请求。** 本次请求确实到达 Gateway。
2. **Planner 等待超时 ≠ Gateway BLOCK。** Gateway 给出的是 `ALLOW`，不是 `BLOCK`。
3. **Planner 等待超时 ≠ 未执行。** 本次已产生 `ExecutionEvent` 与 1 条下游 Goal。
4. 客户端超时只说明**客户端未在超时窗口内观测到终态**；请求是否到达、是否被允许、
   是否已执行，**必须**依据 Gateway 权威审计与 NavigationSim journal 逐 `request_id` 判定。
5. 适配层在超时分支的行为是正确的：**不自动重试、不新建 `request_id`、不记为
   Gateway BLOCK**，并明确提示请求可能已到达甚至已执行。

### 4.1 必须避免的过度推广

- 本条**仅是本次观测**，**不得**推广为"所有 Planner 超时都会执行"。
- 也**不得**据此认为超时后的执行一定安全或一定异常 —— 执行是否被允许由 Gateway 决定，
  而客户端是否观测到结果与执行事实是两件不同的事。
- **不得**把超时后的执行当作"已通过安全检查"的证据。

---

## 5. 修复范围

### 5.1 报告文本（仅改文本，未改日志）

| 文件 | 修改内容 |
| --- | --- |
| `docs/reviews/M3_ONLINE_INTEGRATION_CLOSEOUT_20261016.md` | §5 场景表 ON-06 行；§5.2 超时语义整节重写（含逐层实测表）；§7 DecisionEvent 表；§8 Action Result 表与说明；§9 Goal 数量表与合计说明 |
| `docs/reviews/SYSTEM_STATUS_20261016_CURRENT.md` | §9 场景表 ON-06 行；新增 ON-06 正确解读段；补充"域 42 普通模式、非 Enforce"的作用域声明 |
| `docs/reviews/COMPETITION_CLAIMS_20261016_CURRENT.md` | 超时语义行补充执行事实；新增禁止声明第 11 条 |

所有修改均在原处标注了 **"勘误"**，保留错误痕迹以便追溯，不做静默覆盖。

### 5.2 校验代码与测试

| 文件 | 新增内容 |
| --- | --- |
| `scripts/verify_m3_online_evidence.py` | `validate_claims()` + `--claims` 参数；`UNOBSERVED` 保留字；超时语义不变量 |
| `artifacts/demo-2026-10-19/m3-online-m3online-20261016T134406Z/report_claims.json` | **报告声明的结构化形式**（来自勘误后文本，非从证据自动生成，以保持可证伪性） |
| `tests/unit/test_on06_report_claims.py` | 15 项复发防护测试 |

---

## 6. 复发防护机制

### 6.1 声明与证据分离校验

`report_claims.json` 记录**报告声称的事实**；校验器把它与**原始证据**逐字段比对。
两者不一致即报 `FAIL`。由于声明不是从证据生成的，**篡改任一方都会被检出**。

### 6.2 超时语义不变量（硬校验）

当声明的 `planner_outcome == PLANNER_RESULT_TIMEOUT` 时：

| 错误声明 | 报错代码 |
| --- | --- |
| 记为 `gateway_decision = BLOCK` | `TIMEOUT_MISREPORTED_AS_BLOCK` |
| 记为 `gateway_arrival = 0` | `TIMEOUT_MISREPORTED_AS_NO_ARRIVAL` |
| 声明未执行但审计有 ExecutionEvent | `TIMEOUT_MISREPORTED_AS_NOT_EXECUTED` |
| 声明 Goal 为 0 但 journal 有 Goal | `TIMEOUT_MISREPORTED_AS_NO_GOAL` |

另对适配层阻断场景校验：不得声称到达 / 执行 / Goal / Gateway ALLOW，
否则报 `BLOCK_SCENARIO_CLAIMS_DOWNSTREAM` / `BLOCK_SCENARIO_CLAIMS_ALLOW`。

### 6.3 校验结果

```
verify_m3_online_evidence.py --run-dir <evidence> --claims report_claims.json
  -> verdict = PASS, checks = 46, failures = 0, claims_checked = True
```

### 6.4 反例测试（必须失败）

`tests/unit/test_on06_report_claims.py` 共 **15 项通过**，覆盖任务书要求的 5 个反例：

| # | 反例 | 预期报错 | 实测 |
| --- | --- | --- | --- |
| 1 | 声明 ON-06 未执行（删/忽略 ExecutionEvent） | `GATEWAY_EXECUTION_MISMATCH` / `TIMEOUT_MISREPORTED_AS_NOT_EXECUTED` | 检出 |
| 2 | 修改 ON-06 的 Gateway 决策声明 | `GATEWAY_DECISION_MISMATCH` + `TIMEOUT_MISREPORTED_AS_BLOCK` | 检出 |
| 3 | 修改 ON-06 Goal 的 `request_id` | `ORPHAN_GOAL_REQUEST` / `NAVSIM_GOAL_MISMATCH` | 检出 |
| 4 | 把 ON-06 错记为 Gateway BLOCK | `TIMEOUT_MISREPORTED_AS_BLOCK` | 检出 |
| 5 | 把 ON-06 错记为"未收到请求" | `TIMEOUT_MISREPORTED_AS_NO_ARRIVAL` | 检出 |

附加反例：ON-06 记为 0 Goal、阻断场景声称下游存在、阻断场景声称 ALLOW、
声明不存在场景、**审计日志被清空时不得静默按 0 处理**。

另有 3 项**阳性断言**，锁定原始证据本身：ON-06 确有到达/ALLOW/执行/1 Goal；
事件按 `request_id` 归属（ON-01 3 事件、ON-05 2 事件、ON-06 3 事件，
而不是用 8 行总数推断）；勘误后的声明与证据一致。

---

## 7. 结论

- 原始证据**无需修改**，也不可能被修改来迁就报告。
- 错误性质是**报告撰写错误**，不是系统行为错误，也不是校验器缺陷。
- 该错误在安全表述上具有**方向性风险**：把"已被允许并执行"说成"未执行/被拒绝"，
  会同时**低估**实际执行范围与**误述** Gateway 行为。因此在竞赛材料中
  新增了明确的禁止声明条目。
- 已通过**机器可校验的声明对账 + 超时语义不变量 + 15 项反例测试**
  使同类错误在再次出现时被自动检出。
