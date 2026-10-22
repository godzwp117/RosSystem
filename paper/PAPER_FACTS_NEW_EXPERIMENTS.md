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
