# 最终验收加固报告（2026-10-22）

> 分支：`integration/final-acceptance-hardening-2026-10-22`
> 起点：`70fefa47a4333cf2bb3e1631525366897a3cbc81`
> 代码提交：`d0c6450035f0156a111e7c6c632cf77253789613`
> **受测 SHA：`ba16e7f39261bd5898a186d29561170a46c950d5`**
> run_id：`harden-20261020T171740Z`
> 证据：`artifacts/integration/final-deliverable-2026-10-22/harden-20261020T171740Z/`

---

## 1. 修复的核心缺陷：受控在线验收的弱断言

### 优化前

```bash
[ "$n_audit" -ge 2 ] && [ "$n_goal" -ge 1 ]
```

这个断言**无法证明每个请求的决策正确**：
两个请求都 BLOCK、外加一条无关 Goal，也能通过。

### 优化后

新增 `scripts/verify_final_controlled_online.py`，从**原始** F0 输出、
Gateway audit、NavSim journal 按 **request_id** 逐条核对：

| 场景 | 不变量 |
| --- | --- |
| ON-01 | F0 READY；提交；到达**恰好 1**；ALLOW/ALLOW_IN_POLICY；执行事件 1；Goal **恰好 1** |
| ON-02 | F0 ADAPTER_BLOCK；未提交；到达 **0**；Goal **0** |
| ON-05 | M3 ALLOW_RECOMMENDED；F0 READY；提交；到达 1；BLOCK/OUT_OF_REGION；**无成功执行事件**；Goal **0** |

附加：run_id 一致性、重复 DecisionEvent 拒绝、
**外来 request_id 必须被报出**（不得静默忽略）。

本轮实测：**40 checks / 0 failures / PASS**。

## 2. 反例测试（验证器必须能拒绝错误）

`tests/unit/test_final_controlled_verifier.py`，**21 项全部通过**：

ON-01 被 BLOCK / 缺 Goal / 两个 Goal / 缺执行事件；
ON-02 出现到达 / 出现非法 Goal；
ON-05 错误 ALLOW / 出现 Goal / 出现成功执行事件；
request_id 被替换；run_id 错配；audit 缺失/损坏；journal 缺失/损坏；
F0 与审计矛盾；混入另一次实验的事件；重复 DecisionEvent；
ON-02 却显示已提交。

> **一个只会说 PASS 的验收器毫无价值。** 21 项反例全部被拒绝，
> `FINAL_CONTROLLED_VERIFIER_NEGATIVE_TESTS=PASS`。

## 3. ON-06 异步超时的**本轮真实事实**（重点）

`timeout_outcome_audit.json` 记录的真实事件序列：

| 项 | 实际值 |
| --- | --- |
| F0 决策 | `READY_FOR_GATEWAY_SUBMISSION` |
| Planner 结果 | **`PLANNER_RESULT_TIMEOUT`** |
| Gateway 到达 | **1** |
| Gateway 决策 | **`ALLOW`** |
| Gateway 执行事件 | **1** |
| NavSim Goal | **1**（goal_id `0d8c17b6…`） |

**结论：Planner 超时后，请求实际被 Gateway 放行并执行了。**

上一轮同一场景是「到达 0 / Goal 0」，本轮是「到达 1 / ALLOW / Goal 1」。
两种结果都真实出现过 —— 这正是不能用「TIMEOUT ⇒ BLOCK」这种推断的原因。

### 语义纪律（已写入工具与文档）

- TIMEOUT **不等于** BLOCK；
- TIMEOUT **不等于**未执行；
- **没有 Action 取消协议证据，因此不声明请求已取消**；
- 超时后的 Gateway/Goal 事实**必须原样保留**，不得隐藏。

> 本轮**未**改造 Gateway 取消协议或任务幂等机制 —— 那是真实机器人部署前的后续工作。

## 4. 环境预检强制化

`--check`（诊断）与 `acceptance`（正式）已区分：

- 诊断模式允许 WARN，`CHECK_RESULT=PASS` 只表示列出的条件通过；
- 正式验收启用 `STRICT_PREFLIGHT=1`，以下任一不满足即 **`PREFLIGHT_FAIL` 非零退出**：
  完整 40 位 SHA、工作树干净、`ROS_DISTRO` 已 source、colcon 可用、
  `rg_interfaces`/`rg_demo_nodes`/`rg_gateway` 已构建、jsonschema 可导入、
  无残留 ROS 节点。

预检只在**开始时**执行一次，因此运行中正常生成的证据不会被误判为"测试前不干净"。

## 5. M3 六场景 claims 校验

此前 `claims_checked=false`。现在由**原始审计与 journal 生成** `claims.json`，
再交给 `verify_m3_online_evidence.py --claims` 比对：

本轮：**`claims_checked=true`，39 checks / 0 failures / PASS**
（比上一轮的 19 checks 多出 20 项声明比对）。

claims 的 ON-06 条目同样按实际事实填写，不是硬编码旧结果。

## 6. DDS Enforce 证据归档

- 正式权限绑定 domain 43，必须在设计域上运行；
- 本轮 `7/7 PASS`，逐场景原始证据（`tests/evidence/enforce-<run_id>/`）已归档；
- **未提交任何 keystore、私钥或签名秘密**（证据包 `*.pem`/`*.key` 计数为 0）；
- `security/keystore` 为本地受控 fixture（`.gitignore` 已排除）。

## 7. 本轮完整验收结果

| 项目 | 结果 |
| --- | --- |
| 公共契约 | **PASS** |
| F0 P0 安全反例 | **38 passed** |
| 全仓单测 | **847 passed, 1 skipped** |
| 受控在线（request_id 级） | **PASS（40 checks）** |
| 三真实 External | 调用 PASS / **F0 BLOCK（预期）** |
| M3 六场景（含 claims） | **PASS（39 checks）** |
| 正式 DDS Enforce | **7/7 PASS** |
| 全量验收 | **`ACCEPTANCE=PASS`** |

## 8. 首轮失败记录（保留）

第一次加固验收在 DDS Enforce 处失败，原因是本工作树缺少
`security/keystore` fixture（正式权限绑定 domain 43，无法认证）。
补齐后整轮重跑通过。失败轮证据保留在 `harden-20261020T170655Z`，
**未删除**，以便审计看到完整过程。

## 9. 与上一版交付的对比

| 项 | `70fefa4`（上一版） | 本轮 `ba16e7f` |
| --- | --- | --- |
| 受控在线断言 | 审计行数 ≥2 且 Goal ≥1 | **request_id 级逐场景不变量** |
| 验证器反例测试 | 无 | **21 项** |
| M3 claims | `claims_checked=false` | **`true`，39 checks** |
| ON-06 事实 | 记录了当时结果 | **记录了本轮不同结果，并明确 TIMEOUT≠BLOCK** |
| 预检 | 诊断为主 | **正式验收强制门槛，失败即 PREFLIGHT_FAIL** |
| 单测 | 826 passed | **847 passed** |

## 10. 仍存在的限制（未变，且不得因加固而升级）

- M1 在线检测有效性**未通过**；
- M2 生产签发者**未就绪**，真实 Action SendGoal **未捕获**；
- **无可信速率授权基线**；
- **`THREE_REAL_LEVEL3_READY = BLOCKED`** —— 验收器变严格**不会**提升生产能力等级。

## 11. 后续工作（本轮明确不做）

Gateway 的 Action 取消协议、任务幂等、执行中止机制。
本轮只做审计与状态语义修复。
