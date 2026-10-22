# 论文事实变更日志

本文件逐项追踪相对 `PAPER_FACTS_BASELINE.md` 的变化。基线文件本身不覆盖。

| 时间（UTC） | 变更 | 原因 | 影响 |
|---|---|---|---|
| 2026-10-22T02:34:45Z | 建立 `PAPER_FACTS_BASELINE.{md,json}` 与 `CLAIM_EVIDENCE_MATRIX.csv` | 固定 1.1.0 既有事实，防止后续工程导致论文引用漂移 | 论文可先按 C01–C17 写作 |
| 2026-10-22T02:34:45Z | 新增 `ERRATUM_P07.md`，P07 从 PASS 降为 DISPUTED | 原 P07 证据是 Gateway TaskPolicy 阻断，不是 M3 建议阻断 | 论文暂不得引用 P07 PASS |
| 2026-10-22T03:05:00Z | P07 由 DISPUTED 改为 PASS（CONTROLLED_ISOLATION） | 新增真实 M3 隔离实验，13/13；原 Gateway 证据被明确排除 | 论文可引用“M3 阻断在 F0 生效”，但必须标注 M1/M2 为 MOCK |
| 2026-10-22T03:05:00Z | P09 由 NOT_RUN 改为 PASS | 新增 1.1.0 Planner 超时重测，10/10 | 论文可写“Planner 超时 ≠ Gateway 未收到/未执行”，限制为同容器时钟 |
| 2026-10-22T03:05:00Z | 矩阵 PASS 10 / BLOCKED 1 / NOT_VERIFIED 1 | P07/P09 更新 | 三真正向仍 BLOCKED，LEVEL C 不变 |
| 2026-10-22T03:20:00Z | 新增 M2 Action 绑定探测（负结果） | 原始 DDS reader 破坏 Action 服务发现；未获得请求样本 | 论文只能写意图主题绑定；Action 级为 NOT_VERIFIED |
| 2026-10-22T03:40:00Z | 新增 Web 1.1.0 归档研究证据面板 | `/api/research` 只读展示；显式区分 ARCHIVED/REPLAY/ONLINE | 论文可写“控制台可展示归档研究证据”，不得写“在线实时展示” |
| 2026-10-22T13:05:00Z | 最终事实表统一到 1.1.1-rc1（921/17/0，603.8 s） | 最终包测试结果与 1.1.0 历史基线需要分栏 | 论文引用必须带版本；原始日志未归档的限制单独披露 |
| 2026-10-22T13:05:00Z | 新增 `UNIT_TEST_LOG_RECOVERY_STATUS.md` | `rg_last2` 已删除，完整 stdout 曾只存在于容器内 `/tmp/unit.log` | 原始日志记 NOT_RECOVERED；结果不改判 FAIL |
| 2026-10-22T13:40:00Z | 最终包事实统一为 1.1.1-rc1：`921 passed / 17 skipped / 0 failed / 603.8 s` | 最终包验收结果与 1.1.0 历史基线分栏 | `PAPER_FACTS_FINAL.md`、统计、CSV、报告同步；原始日志未归档单独披露 |
| 2026-10-22T13:40:00Z | 新增 `FINAL_PACKAGE_SKIPPED_TESTS.csv`（17 行）与 `FINAL_UNIT_TEST_EVIDENCE_AUDIT.md` | 逐项审计 15 个 ON06 + 2 个 M2 witness skip | 15 项旧 Demo 报告声明检查未执行；2 项源码级 GUID 检查未执行；核心动态实验另有覆盖，但不改写 skipped |
| 2026-10-22T13:40:00Z | 新增 `paper/check_paper_facts.py` 与 `paper/evidence/` | 固定最终事实、包 SHA、LEVEL C/LEVEL3/Action/第三方边界；归档 NEW_REEXECUTION 日志 | 一致性检查 14 项通过、0 错误 |
