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
| 2026-10-22T03:05:00Z | P07 由 DISPUTED 改为 PASS（CONTROLLED_ISOLATION） | 新增真实 M3 隔离实验，13/13；原 Gateway 证据被明确排除 | 论文可引用“M3 阻断在 F0 生效”，但必须标注 M1/M2 为 MOCK |
| 2026-10-22T03:05:00Z | P09 由 NOT_RUN 改为 PASS | 新增 1.1.0 Planner 超时重测，10/10 | 论文可写“Planner 超时 ≠ Gateway 未收到/未执行”，限制为同容器时钟 |
| 2026-10-22T03:05:00Z | 矩阵 PASS 10 / BLOCKED 1 / NOT_VERIFIED 1 | P07/P09 更新 | 三真正向仍 BLOCKED，LEVEL C 不变 |
| 2026-10-22T03:20:00Z | 新增 M2 Action 绑定探测（负结果） | 原始 DDS reader 破坏 Action 服务发现；未获得请求样本 | 论文只能写意图主题绑定；Action 级为 NOT_VERIFIED |
| 2026-10-22T03:40:00Z | 新增 Web 1.1.0 归档研究证据面板 | `/api/research` 只读展示；显式区分 ARCHIVED/REPLAY/ONLINE | 论文可写“控制台可展示归档研究证据”，不得写“在线实时展示” |
