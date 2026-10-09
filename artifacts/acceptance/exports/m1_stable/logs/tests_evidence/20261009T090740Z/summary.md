# Scenario summary

- run id: `20261009T090740Z`
- finished at: `2026-10-09T09:08:20Z`
- workspace: `/ws`
- result: **2 passed / 2 total**

| Scenario | Result | NavSim Goals | Decision sequence | Execution status | REJECTED lines |
| --- | --- | --- | --- | --- | --- |
| `A_zone_allow` | PASS | 1 | ALLOW_IN_POLICY | EXECUTED | 0 |
| `B_zone_block_out_of_region` | PASS | 0 | OUT_OF_REGION | - | 1 |

## Per-check detail

### A_zone_allow -- PASS

In-region target: Gateway ALLOW, one downstream Goal, EXECUTED.

| Check | Result | Detail |
| --- | --- | --- |
| bringup: NavigationSim ready | PASS | NAVSIM_READY seen in tests/evidence/20261009T090740Z/A_zone_allow/navsim.log |
| bringup: security_gateway ready | PASS | GATEWAY_READY seen in tests/evidence/20261009T090740Z/A_zone_allow/gateway.log |
| navsim Goal count == 1 | PASS | journal tests/evidence/20261009T090740Z/A_zone_allow/navsim_goals.jsonl has 1 line(s) |
| planner[allow] exit code == 0 | PASS | actual exit code 0 |
| planner[allow] Result.success == True | PASS | status_code='EXECUTED' detail='recorded target (1.5, 1.5, 0.0) in frame map; no path planning performed' |
| planner[allow] status_code == EXECUTED | PASS | actual status_code='EXECUTED' |
| DecisionEvent reason_code sequence == ['ALLOW_IN_POLICY'] | PASS | actual sequence ['ALLOW_IN_POLICY'] |
| ExecutionEvent count == 1 | PASS | actual 1 ExecutionEvent(s): ['EXECUTED'] |
| RosCommEvent count == DecisionEvent count == planner runs | PASS | comm=1 decision=1 planner_runs=1 |
| event_id traceability (1 RosComm + 1 Decision + <=1 Execution each) | PASS | event_id groups: 1; malformed: none |
| BLOCKed event_ids never have an ExecutionEvent | PASS | leaked event_ids: none |
| correlatable REJECTED log lines == 0 | PASS | found 0 REJECTED line(s) in tests/evidence/20261009T090740Z/A_zone_allow/gateway.log |
| executor request_id set matches the ALLOWed set | PASS | journal=['a-zone-request-0001'] expected=['a-zone-request-0001'] |

### B_zone_block_out_of_region -- PASS

Out-of-region target: Gateway BLOCK/OUT_OF_REGION, zero downstream Goals.

| Check | Result | Detail |
| --- | --- | --- |
| bringup: NavigationSim ready | PASS | NAVSIM_READY seen in tests/evidence/20261009T090740Z/B_zone_block_out_of_region/navsim.log |
| bringup: security_gateway ready | PASS | GATEWAY_READY seen in tests/evidence/20261009T090740Z/B_zone_block_out_of_region/gateway.log |
| navsim Goal count == 0 | PASS | journal tests/evidence/20261009T090740Z/B_zone_block_out_of_region/navsim_goals.jsonl has 0 line(s) |
| planner[block] exit code == 0 | PASS | actual exit code 0 |
| planner[block] Result.success == False | PASS | status_code='OUT_OF_REGION' detail="target (9.0, 9.0) outside allowed_region {'x_min': 0.0, 'x_max': 4.0, 'y_min': 0.0, 'y_max': 4.0}" |
| planner[block] status_code == OUT_OF_REGION | PASS | actual status_code='OUT_OF_REGION' |
| DecisionEvent reason_code sequence == ['OUT_OF_REGION'] | PASS | actual sequence ['OUT_OF_REGION'] |
| ExecutionEvent count == 0 | PASS | actual 0 ExecutionEvent(s): [] |
| RosCommEvent count == DecisionEvent count == planner runs | PASS | comm=1 decision=1 planner_runs=1 |
| event_id traceability (1 RosComm + 1 Decision + <=1 Execution each) | PASS | event_id groups: 1; malformed: none |
| BLOCKed event_ids never have an ExecutionEvent | PASS | leaked event_ids: none |
| correlatable REJECTED log lines == 1 | PASS | found 1 REJECTED line(s) in tests/evidence/20261009T090740Z/B_zone_block_out_of_region/gateway.log |
| every REJECTED line carries a BLOCKed request_id and event_id | PASS | blocked request_ids=['b-zone-request-0002'] |
| REJECTED lines declare downstream_goal_created=false | PASS | checked 1 line(s) |
| executor request_id set matches the ALLOWed set | PASS | journal=[] expected=[] |

