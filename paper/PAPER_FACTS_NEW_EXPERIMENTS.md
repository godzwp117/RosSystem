# 本轮新增实验事实（增量）

> 本文件只记录**本轮六小时任务**新增或重跑的实验；不修改
> `PAPER_FACTS_BASELINE.*`。每条必须带 run_id、命令、退出码、证据路径与限制。

（阶段 1 起逐条追加。）

## N-001 P07 隔离实验（2026-10-22）

- run_id：`p07-20261022T024200Z`
- 命令：`python3 tests/integration/p07_m3_block_isolation.py --run-id p07-20261022T024200Z`
- 结果：13/13 PASS；真实 M3 `BLOCK_RECOMMENDED`；F0 `ADAPTER_BLOCK`；Planner 未提交
- 证据：`artifacts/research/v110/p07/p07-20261022T024200Z/`
- 限制：M1/M2 为 MOCK；Gateway/NavigationSim 未启动；不是三真实正向

## N-002 P09 Planner 超时重测（2026-10-22）

- run_id：`p09-20261022T030000Z`
- 命令：`python3 tests/integration/p09_planner_timeout.py --run-id p09-20261022T030000Z`
- 结果：10/10 PASS；Planner `RESULT_TIMEOUT`；Gateway ALLOW；Goal 1；ExecutionEvent `EXECUTED` 晚于 Planner 退出
- 证据：`artifacts/research/v110/p09/p09-20261022T030000Z/`
- 限制：同一容器时钟；NavigationSim recorded_only；未新增取消实验

## N-003 M2 Action send_goal 绑定探测（负结果）

- 结果：**BLOCKED / NOT_VERIFIED**
- 已证明：Action 请求 typesupport 存在；原始 reader 可创建
- 关键负结果：带 `--action-capture` 时 Planner `NO_ACTION_SERVER`；同栈不带该 reader 时 `EXECUTED`
- 证据：`artifacts/research/v110/m2-action-probe/summary.json`
- 影响：不得把意图主题 17/17 写成 Action 级身份；论文需保留该边界

## N-004 Web 1.1.0 研究证据展示

- 结果：`/api/research` 200；页面含研究证据面板；18 项 dashboard 测试通过
- 类别：`ARCHIVED_RESEARCH_EVIDENCE`，`online_evidence=false`
- 证据：`artifacts/research/v110/web/`、`paper/WEB_EVIDENCE_VERIFICATION.md`
- 限制：无无头浏览器，截图 NOT_RUN

## N-005 1.1.1-rc1 最终包单测与日志边界

- 最终包：`1.1.1-rc1`，SHA-256 `d69737cf…`
- 单测：**921 passed / 17 skipped / 0 failed / 603.8 s**
- 历史基线：1.1.0 `920 passed / 4 skipped`（HISTORICAL_BASELINE）
- 注意：结果有记录，但**原始完整 pytest 日志未恢复**
- 证据：`paper/FINAL_PACKAGE_REPRODUCTION.md`、`paper/UNIT_TEST_LOG_RECOVERY_STATUS.md`
- 17 skipped 不计入 passed；不得写成 921 次独立实验
