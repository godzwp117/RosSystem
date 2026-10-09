# 证据包索引

每个阶段的结论对应哪个包，以及该包的自我声明。

**注意**：`archive_sha256` 为 null 是刻意的 —— 归档哈希写在包外的 `.publish.json`，
避免"归档哈希写回包内 manifest 导致归档变化"的循环依赖。

| run_id | 阶段 | 状态 | 安全模式 | 通过/总数 | 源 commit | 已脱敏 |
| --- | --- | --- | --- | --- | --- | --- |
| `m1_stable` | M1 | PASS | disabled | 23/23 | `e13199aa86da` | 否（本地原始包） |
| `m2_sros2_enforce` | M2 | PASS | enforce | 30/30 | `9ea929c2c37d` | 否（本地原始包） |
| `m3_20261009T135839Z` | M3 | PASS | disabled | 7/7 | `6a1a105123b7` | 否（本地原始包） |
| `m3_20261009T135946Z` | M3 | PASS | disabled | 7/7 | `6a1a105123b7` | 否（本地原始包） |
| `m3_20261009T140038Z` | M3 | PASS | disabled | 7/7 | `6a1a105123b7` | 否（本地原始包） |
| `m3_dynamic_policy` | M3 | PASS | enforce | 43/43 | `ba828a1ceb5f` | 否（本地原始包） |
| `p0_before_m1` | P0 | PASS | disabled | 16/16 | `907ea1aee39d` | 否（本地原始包） |

公开（已脱敏）副本位于 `evidence/m3` 分支：

```text
https://github.com/godzwp117/RosSystem/tree/evidence/m3/artifacts/acceptance/published/
```

本地原始包（未脱敏，仅在受控环境）位于 `artifacts/acceptance/exports/<run_id>/`。
