# 最终报告证据索引（2026-10-22，封版优先）

> **当前正式受测代码 SHA**：`2f3de257c9eac873093201292f6b2a9571da4f03`
> **最终归档 HEAD**：`842edf2b1bec4d83d8aef4c4782d0c9a245f05b9`
> **当前 run_id**：`closeout-20261021T023020Z`
> **当前证据目录**：`artifacts/integration/final-submission-closeout/closeout-20261021T023020Z/`
>
> 历史加固版（仅作对照）：`harden-20261020T171740Z` @ `ba16e7f39261bd5898a186d29561170a46c950d5`
> 历史证据目录：`artifacts/integration/final-deliverable-2026-10-22/harden-20261020T171740Z/`

---

## 0. 最新提交可直接引用的实验数据

| 指标 | 数值 | 证据 |
| --- | --- | --- |
| 公共契约 | PASS | `contracts.log` |
| 全仓单测 | **847 passed, 1 skipped** | `unit_tests.log` |
| F0 P0 安全反例 | **38 passed** | `f0_p0.log` |
| 受控在线（request_id 级） | **40 checks / 0 failures / PASS** | `controlled_online/controlled_verification.json` |
| 三真实 External | 调用 PASS / Schema PASS / **F0 BLOCK（预期）** | `three_real/f0.json` |
| M3 六场景（含 claims） | **36 checks / 0 failures / PASS**，claims_checked=true | `m3_online/merged/verification.json` |
| 正式 DDS Enforce | **7/7 PASS** | `dds_enforce/` |
| 全量验收 | **ACCEPTANCE=PASS** | `summary.txt` |
| 证据计数 | **115 独立文件**（134 条索引，19 条 DDS 重复引用） | `FINAL_SUBMISSION_EVIDENCE_MANIFEST.json` |

### ON-06（两次运行结果不同，必须按 run 判读）

| run_id | 受测 SHA | Planner | Gateway 到达 | 决策 | Goal |
| --- | --- | --- | --- | --- | --- |
| `closeout-20261021T023020Z`（**本次封版**） | `2f3de257c9eac873093201292f6b2a9571da4f03` | `TIMEOUT` | **0** | 无 | **0** |
| `harden-20261020T171740Z`（历史加固） | `ba16e7f39261bd5898a186d29561170a46c950d5` | `TIMEOUT` | **1** | `ALLOW` | **1** |

**Planner TIMEOUT ≠ Gateway BLOCK ≠ 任务取消 ≠ 未执行。** 必须看每次运行的原始审计。

---

## 1. 历史实验及其适用范围（数字不得挪用到本轮）

| 历史版本 | 受测 SHA | 当时关键数字 | 适用范围 |
| --- | --- | --- | --- |
| 加固版 | `ba16e7f39261bd5898a186d29561170a46c950d5` | M3 **39 checks** / 0 failures；ON-06 Gateway ALLOW + Goal **1** | 仅该 run |
| 交付版 | `0563fe7cc8aab6901bb7a91d6ece3b9cdd960a04` | 全仓 826 passed；M3 19 checks | 仅该 run |
| 冻结演示 | `be47ccd6c1b19460b65abc0ea8004706383d01d4` | 763 passed；M3 6/6；DDS 7/7 | 仅该 run |

---

## 可直接写入报告的数字

| 指标 | 数值 | 证据文件 |
| --- | --- | --- |
| 公共契约 | PASS | `contracts.log` |
| 全仓单元测试 | **847 passed, 1 skipped** | `unit_tests.log` |
| F0 P0 安全反例 | 38 passed | `f0_p0.log` |
| 三真实模块 | 3 external，schema 全合法，F0 ADAPTER_BLOCK | `three_real/f0.json` |
| 受控在线 | **request_id 级 40 checks PASS** | `controlled_online/controlled_verification.json` |
| Gateway 独立阻断 | BLOCK，Goal 0 | `controlled_online/stack-a/gateway_audit.jsonl` |
| M3 六场景 | **36 checks / 0 failures**，claims_checked=true | `m3_online/merged/verification.json` |
| DDS Enforce | 7/7 PASS | `dds_enforce/sros2_check.log` |
| 全量验收 | ACCEPTANCE=PASS | `summary.txt` |
| 证据校验 | SHA256SUMS 全部 OK | `SHA256SUMS.txt` |

## 适合做图表的素材

1. **分层准入架构图**：M1/M2/M3 → F0 → Planner → Gateway(TaskPolicy) → NavSim，旁挂 DDS-Security；
2. **两种模式对照表**：受控在线（Mock+Real M3）vs 三真实严格（全 External → BLOCK）；
3. **六场景结果表**：ON-01..06 的 F0 决策 / Gateway 到达 / Gateway 决策 / Goal；
4. **M1 通道能力对比**：message-only / graph-only / both 的 FPR 与分类召回；
5. **DDS Enforce 七项**：S1/S2/S3/S3C/S4/S5/S6 各自验证的安全属性。

## 不可作为结论引用的历史数据

- 冻结演示（`be47ccd`）的 763 passed / M3 6/6 / DDS 7/7 —— 不同 SHA，仅作对照；
- M1 早期 0.9919 F1 —— **已撤回**（duration_ms 标签泄漏）；
- M2 CandidateTask 身份绑定 —— 研究级，非生产。

## 历史加固实验（`harden-20261020T171740Z`，受测 `ba16e7f`）的可引用事实

> 以下数字属于**上一轮加固实验**，不是本次封版结果，引用时必须带 run_id。

| 事实 | 数值 | 证据 |
| --- | --- | --- |
| 受控在线 request_id 级检查 | 40 checks / 0 failures | `controlled_online/controlled_verification.json` |
| 验收器反例测试 | 21 项全部被正确拒绝 | `tests/unit/test_final_controlled_verifier.py` |
| M3 六场景声明校验（历史） | claims_checked=true，**39 checks** | 历史证据目录 |
| **ON-06（历史加固轮）** | 同一请求上 **Planner TIMEOUT 与 Gateway ALLOW / NavSim Goal 1 并存**；不宣称时间先后 | 历史证据 `harden-20261020T171740Z/timeout_audit/` |

> **ON-06 值得在报告里单列**：它证明"Planner 超时"与"请求未执行"是两件不同的事。
> 历史加固轮中，同一请求上 **Planner TIMEOUT 与 Gateway ALLOW、NavSim Goal 1 同时成立**；
> 本次封版轮中，同一场景的 Planner 同样 TIMEOUT，但 Gateway 审计记录 **0 到达、0 Goal**。
> 现有日志缺可严格比较的时间戳，因此**两种结果都不宣称事件先后**。
