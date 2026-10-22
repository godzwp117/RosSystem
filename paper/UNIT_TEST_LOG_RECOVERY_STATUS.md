# 最终包 pytest 原始日志追溯状态

> 审计对象：`1.1.1-rc1` 最终完整包（SHA-256 `d69737cf9dbd039a4a0b8a127eb15bb3db55b5514512c119befd46d5e0fe32d2`）
> 审计时间：2026-10-22
> 原则：找不到原始日志就明确写 NOT_RECOVERED；不补造、不改判 FAIL、不把新重跑冒充旧日志。

## 1. 已记录的历史结果

```text
HISTORICAL_RESULT     = 921 passed / 17 skipped / 0 failed
HISTORICAL_DURATION   = 603.8 seconds
RESULT_SOURCE         = paper/FINAL_PACKAGE_REPRODUCTION.md
RESULT_ENVIRONMENT    = SAME_HOST_FRESH_ENV（完整包解压后的新容器，容器名 rg_last2）
```

该结果来自当时命令的**尾部输出**，不是从原始完整日志重新计算的。

## 2. 原始完整 pytest 日志

```text
ORIGINAL_FULL_PYTEST_LOG = NOT_RECOVERED
```

已知原始命令形态：

```bash
docker exec rg_last2 bash -lc \
  'source /opt/ros/jazzy/setup.bash && source /workspace/install/setup.bash && \
   cd /workspace && python3 -m pytest tests/unit -q -p no:cacheprovider \
   > /tmp/unit.log 2>&1; echo EXIT=$?; tail -3 /tmp/unit.log'
```

关键事实：完整日志被重定向到**容器内** `/tmp/unit.log`；宿主只收到了
`tail -3` 的尾部。容器 `rg_last2` 已在清理阶段删除，因此该文件不在宿主
文件系统中。

## 3. 已执行的追溯尝试

| # | 来源/命令 | 结果 |
| --- | --- | --- |
| 1 | `grep -RIn "921 passed\|17 skipped\|603.8"` 仓库（排除 `.git`/压缩包） | 只找到**派生报告**中的数字，无原始 pytest 日志 |
| 2 | `grep -RIl ... /tmp` | 无匹配文件 |
| 3 | `grep -RIl ... /root/.dsh/logs` | 无匹配 |
| 4 | DSH session cache `session_xZ-...json` | 只含会话摘要/结果文本，不含完整 pytest stdout |
| 5 | Docker `rg_last2` logs / container inspect | 容器已删除，无法读取其 `/tmp/unit.log` |
| 6 | 仓库内 JUnit XML / pytest JSON / `unit.log` | 未找到 |
| 7 | 历史任务输出 | 只有 `tail -3` 的尾部（921/17/0/603.8），无 `SKIPPED` 明细 |
| 8 | `paper/evidence/` | 原本不存在；本轮新建目录用于存放**新审计运行**，不冒充原始日志 |

## 3.1 机器可读状态

```text
LOG_RECOVERY_ATTEMPTS = [
  "repo_grep: only derived reports",
  "tmp_grep: no match",
  "dsh_logs: no match",
  "dsh_session_cache: summary only, no full stdout",
  "docker_rg_last2: container deleted",
  "junit_xml_or_json: none",
  "task_output: tail -3 only"
]
SKIP_NODEIDS_RECOVERED = 17/17 (NEW_REEXECUTION)
SKIP_REASONS_RECOVERED = 17/17 (NEW_REEXECUTION + SOURCE_CODE_ANALYSIS)
```

## 4. 新重跑的性质与边界

为了逐项解释 17 个 skipped，本轮在**新的容器**中对**同一最终包**执行了一次
带 `-rs` 的审计运行。该运行：

- 使用新 run 标识，结果标记为 **`NEW_REEXECUTION`**；
- **不是** `rg_last2` 的原始日志；
- 只用于核对 skip 条件与数量，不用于替换历史 603.8 s 结果；
- 若其结果与历史 `921/17/0` 一致，可作为“条件可重现”的辅助证据，而不是原始日志。

```text
NEW_REEXECUTION = 921 passed / 17 skipped / 0 failed / 600.79 s
                  paper/evidence/pytest_1_1_1_rc1_skip_audit_new_run.log
```

## 5. 结论

```text
FINAL_PACKAGE_TEST_RESULT_RECORDED   = PASS（结果有报告记录）
ORIGINAL_PYTEST_LOG_ARCHIVED         = NOT_RECOVERED
SKIP_NODEIDS_RECOVERED               = 17/17（NEW_REEXECUTION 2026-10-22；见 FINAL_PACKAGE_SKIPPED_TESTS.csv）
SKIP_REASONS_RECOVERED               = 17/17（同一 CSV；原始日志仍不可用）
EVIDENCE_LIMITATION                  = Original full pytest output unavailable
```

不能把本文件的结论写成 `FAIL`：没有发现新的测试失败；也不能写成
`PASS（原始日志已归档）`：原始日志确实不可恢复。
