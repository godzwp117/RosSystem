# 最终报告证据索引（2026-10-22）

> 受测 SHA：`0563fe7cc8aab6901bb7a91d6ece3b9cdd960a04`
> 证据根：`artifacts/integration/final-deliverable-2026-10-22/final-20261020T160207Z-v3/`

## 可直接写入报告的数字

| 指标 | 数值 | 证据文件 |
| --- | --- | --- |
| 公共契约 | PASS | `contracts.log` |
| 全仓单元测试 | 826 passed, 1 skipped | `unit_tests.log` |
| F0 P0 安全反例 | 38 passed | `f0_p0.log` |
| 三真实模块 | 3 external，schema 全合法，F0 ADAPTER_BLOCK | `three_real/f0.json` |
| 受控在线 | Gateway 审计 5 行 / NavSim Goal 1 | `controlled_online/stack-a/` |
| Gateway 独立阻断 | BLOCK，Goal 0 | `controlled_online/stack-a/gateway_audit.jsonl` |
| M3 六场景 | 19 checks / 0 failures / PASS | `m3_online/merged/verification.json` |
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
