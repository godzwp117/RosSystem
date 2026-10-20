# M3 在线联调证据复核（独立工具输出）

- 证据目录：`/home/zhangwei/project/RosSystem-worktrees/demo-freeze/artifacts/demo-2026-10-19/release-freeze-rehearsal-20261018T144247Z/m3/merged`
- Gateway 审计行数：5
- NavigationSim Goal 行数：1
- 复核检查项：39（失败 0）
- **判定：`PASS`**

## 场景关联表

| 场景 | request_id | 适配层决策 | M3 状态 | Planner outcome | Gateway arrival | Gateway decision | Execution | Goal 数 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ON01 | `on01-legal-allow-rehearsal-20261018T144247Z-m3a` | READY_FOR_GATEWAY_SUBMISSION | ALLOW_RECOMMENDED | PLANNER_RESULT_RECEIVED | 1 | ALLOW/ALLOW_IN_POLICY | 1 | 1 |
| ON02 | `on02-oor-block-rehearsal-20261018T144247Z-m3a` | ADAPTER_BLOCK | BLOCK_RECOMMENDED | NOT_SUBMITTED_ADAPTER_BLOCK | 0 | - | 0 | 0 |
| ON03 | `on03-rehearsal-20261018T144247Z-m3b` | ADAPTER_BLOCK | UNKNOWN | NOT_SUBMITTED_ADAPTER_BLOCK | 0 | - | 0 | 0 |
| ON04 | `on04-rehearsal-20261018T144247Z-m3b` | ADAPTER_BLOCK | ERROR | NOT_SUBMITTED_ADAPTER_BLOCK | 0 | - | 0 | 0 |
| ON05 | `on05-gateway-authority-rehearsal-20261018T144247Z-m3a` | READY_FOR_GATEWAY_SUBMISSION | ALLOW_RECOMMENDED | PLANNER_RESULT_RECEIVED | 1 | BLOCK/OUT_OF_REGION | 0 | 0 |
| ON06 | `on06-rehearsal-20261018T144247Z-m3b` | READY_FOR_GATEWAY_SUBMISSION | ALLOW_RECOMMENDED | PLANNER_RESULT_TIMEOUT | 0 | - | 0 | 0 |

## 检查明细

- [PASS] `ON01` M3_PROPOSED :: M3 状态='ALLOW_RECOMMENDED'
- [PASS] `ON01` SUBMITTED_TO_GATEWAY :: Gateway arrival=1
- [PASS] `ON01` ACTION_RESULT_GOAL_CONSISTENT :: Action Result=EXECUTED 且 Goal 数=1
- [PASS] `ON02` BLOCK_NO_PLANNER :: outcome='NOT_SUBMITTED_ADAPTER_BLOCK'
- [PASS] `ON02` BLOCK_NO_GATEWAY_ARRIVAL :: Gateway arrival=0
- [PASS] `ON02` BLOCK_NO_GOAL :: Goal 数=0
- [PASS] `ON02` BLOCK_NO_EXECUTION :: ExecutionEvent=0
- [PASS] `ON03` BLOCK_NO_PLANNER :: outcome='NOT_SUBMITTED_ADAPTER_BLOCK'
- [PASS] `ON03` BLOCK_NO_GATEWAY_ARRIVAL :: Gateway arrival=0
- [PASS] `ON03` BLOCK_NO_GOAL :: Goal 数=0
- [PASS] `ON03` BLOCK_NO_EXECUTION :: ExecutionEvent=0
- [PASS] `ON04` BLOCK_NO_PLANNER :: outcome='NOT_SUBMITTED_ADAPTER_BLOCK'
- [PASS] `ON04` BLOCK_NO_GATEWAY_ARRIVAL :: Gateway arrival=0
- [PASS] `ON04` BLOCK_NO_GOAL :: Goal 数=0
- [PASS] `ON04` BLOCK_NO_EXECUTION :: ExecutionEvent=0
- [PASS] `ON05` M3_PROPOSED :: M3 状态='ALLOW_RECOMMENDED'
- [PASS] `ON05` SUBMITTED_TO_GATEWAY :: Gateway arrival=1
- [PASS] `ON06` M3_PROPOSED :: M3 状态='ALLOW_RECOMMENDED'
- [PASS] `ON06` TIMEOUT_NOT_BLOCK :: 超时未记为 Gateway BLOCK（outcome=PLANNER_RESULT_TIMEOUT）
- [PASS] `ON01` GATEWAY_ARRIVAL_MISMATCH :: 声明 gateway_arrival=1 vs 实测 1
- [PASS] `ON01` GATEWAY_DECISION_MISMATCH :: 声明 gateway_decision='ALLOW' vs 实测 'ALLOW'
- [PASS] `ON01` GATEWAY_REASON_MISMATCH :: 声明 gateway_reason_code='ALLOW_IN_POLICY' vs 实测 'ALLOW_IN_POLICY'
- [PASS] `ON01` GATEWAY_EXECUTION_MISMATCH :: 声明 gateway_execution=1 vs 实测 1
- [PASS] `ON01` NAVSIM_GOAL_MISMATCH :: 声明 navsim_goals=1 vs 实测 1
- [PASS] `ON02` GATEWAY_ARRIVAL_MISMATCH :: 声明 gateway_arrival=0 vs 实测 0
- [PASS] `ON02` GATEWAY_EXECUTION_MISMATCH :: 声明 gateway_execution=0 vs 实测 0
- [PASS] `ON02` NAVSIM_GOAL_MISMATCH :: 声明 navsim_goals=0 vs 实测 0
- [PASS] `ON03` GATEWAY_ARRIVAL_MISMATCH :: 声明 gateway_arrival=0 vs 实测 0
- [PASS] `ON03` GATEWAY_EXECUTION_MISMATCH :: 声明 gateway_execution=0 vs 实测 0
- [PASS] `ON03` NAVSIM_GOAL_MISMATCH :: 声明 navsim_goals=0 vs 实测 0
- [PASS] `ON04` GATEWAY_ARRIVAL_MISMATCH :: 声明 gateway_arrival=0 vs 实测 0
- [PASS] `ON04` GATEWAY_EXECUTION_MISMATCH :: 声明 gateway_execution=0 vs 实测 0
- [PASS] `ON04` NAVSIM_GOAL_MISMATCH :: 声明 navsim_goals=0 vs 实测 0
- [PASS] `ON05` GATEWAY_ARRIVAL_MISMATCH :: 声明 gateway_arrival=1 vs 实测 1
- [PASS] `ON05` GATEWAY_DECISION_MISMATCH :: 声明 gateway_decision='BLOCK' vs 实测 'BLOCK'
- [PASS] `ON05` GATEWAY_REASON_MISMATCH :: 声明 gateway_reason_code='OUT_OF_REGION' vs 实测 'OUT_OF_REGION'
- [PASS] `ON05` GATEWAY_EXECUTION_MISMATCH :: 声明 gateway_execution=0 vs 实测 0
- [PASS] `ON05` NAVSIM_GOAL_MISMATCH :: 声明 navsim_goals=0 vs 实测 0
- [PASS] `ON06` PLANNER_OUTCOME_MISMATCH :: 声明 planner_outcome='PLANNER_RESULT_TIMEOUT' vs 实测 'PLANNER_RESULT_TIMEOUT'
