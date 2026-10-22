# 论文事实变更日志

本文件逐项追踪相对 `PAPER_FACTS_BASELINE.md` 的变化。基线文件本身不覆盖。

| 时间（UTC） | 变更 | 原因 | 影响 |
|---|---|---|---|
| 2026-10-22T02:34:45Z | 建立 `PAPER_FACTS_BASELINE.{md,json}` 与 `CLAIM_EVIDENCE_MATRIX.csv` | 固定 1.1.0 既有事实，防止后续工程导致论文引用漂移 | 论文可先按 C01–C17 写作 |
| 2026-10-22T02:34:45Z | 新增 `ERRATUM_P07.md`，P07 从 PASS 降为 DISPUTED | 原 P07 证据是 Gateway TaskPolicy 阻断，不是 M3 建议阻断 | 论文暂不得引用 P07 PASS |

## 待登记

- P07 隔离实验（本轮）
- P09 超时重测（本轮）
- M1 新观测/评估（本轮）
- Web 1.1.0 证据展示（本轮）
- 最终包复现（本轮）
