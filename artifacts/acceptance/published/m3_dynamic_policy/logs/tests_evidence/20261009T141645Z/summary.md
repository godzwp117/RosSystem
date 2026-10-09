# Scenario summary

- run id: `20261009T141645Z`
- finished at: `2026-10-09T14:20:18Z`
- workspace: `/ws`
- result: **12 passed / 12 total**

| Scenario | Result | NavSim Goals | Decision sequence | Execution status | REJECTED lines |
| --- | --- | --- | --- | --- | --- |
| `policy_file_missing` | PASS | 0 | POLICY_MISSING | - | 1 |
| `policy_missing_required_field` | PASS | 0 | POLICY_MISSING | - | 1 |
| `policy_nonfinite_region` | PASS | 0 | POLICY_MISSING | - | 1 |
| `policy_inactive` | PASS | 0 | POLICY_MISSING | - | 1 |
| `task_id_mismatch_request_side` | PASS | 0 | TASK_MISMATCH | - | 1 |
| `task_id_mismatch_policy_side` | PASS | 0 | TASK_MISMATCH | - | 1 |
| `frame_id_invalid` | PASS | 0 | INVALID_TARGET | - | 1 |
| `target_nan` | PASS | 0 | INVALID_TARGET | - | 1 |
| `target_infinite` | PASS | 0 | INVALID_TARGET | - | 1 |
| `duplicate_request_id` | PASS | 1 | ALLOW_IN_POLICY, DUPLICATE_REQUEST | EXECUTED | 1 |
| `rate_limit` | PASS | 2 | ALLOW_IN_POLICY, ALLOW_IN_POLICY, RATE_LIMIT | EXECUTED, EXECUTED | 1 |
| `execution_timeout` | PASS | 1 | ALLOW_IN_POLICY | EXECUTION_TIMEOUT | 0 |

## Per-check detail

### policy_file_missing -- PASS

Authoritative policy file absent: fail closed with POLICY_MISSING.

| Check | Result | Detail |
| --- | --- | --- |
| bringup: NavigationSim ready | PASS | NAVSIM_READY seen in tests/evidence/20261009T141645Z/policy_file_missing/navsim.log |
| bringup: security_gateway ready | PASS | GATEWAY_READY seen in tests/evidence/20261009T141645Z/policy_file_missing/gateway.log |
| navsim Goal count == 0 | PASS | journal tests/evidence/20261009T141645Z/policy_file_missing/navsim_goals.jsonl has 0 line(s) |
| planner[missing] exit code == 0 | PASS | actual exit code 0 |
| planner[missing] Result.success == False | PASS | status_code='POLICY_MISSING' detail='no authoritative TaskPolicy is loaded' |
| planner[missing] status_code == POLICY_MISSING | PASS | actual status_code='POLICY_MISSING' |
| DecisionEvent reason_code sequence == ['POLICY_MISSING'] | PASS | actual sequence ['POLICY_MISSING'] |
| ExecutionEvent count == 0 | PASS | actual 0 ExecutionEvent(s): [] |
| RosCommEvent count == DecisionEvent count == planner runs | PASS | comm=1 decision=1 planner_runs=1 |
| event_id traceability (1 RosComm + 1 Decision + <=1 Execution each) | PASS | event_id groups: 1; malformed: none |
| BLOCKed event_ids never have an ExecutionEvent | PASS | leaked event_ids: none |
| correlatable REJECTED log lines == 1 | PASS | found 1 REJECTED line(s) in tests/evidence/20261009T141645Z/policy_file_missing/gateway.log |
| every REJECTED line carries a BLOCKed request_id and event_id | PASS | blocked request_ids=['neg-policy-0001'] |
| REJECTED lines declare downstream_goal_created=false | PASS | checked 1 line(s) |
| executor request_id set matches the ALLOWed set | PASS | journal=[] expected=[] |

### policy_missing_required_field -- PASS

Policy lacks coordinate_frame: schema error, fail closed.

| Check | Result | Detail |
| --- | --- | --- |
| bringup: NavigationSim ready | PASS | NAVSIM_READY seen in tests/evidence/20261009T141645Z/policy_missing_required_field/navsim.log |
| bringup: security_gateway ready | PASS | GATEWAY_READY seen in tests/evidence/20261009T141645Z/policy_missing_required_field/gateway.log |
| navsim Goal count == 0 | PASS | journal tests/evidence/20261009T141645Z/policy_missing_required_field/navsim_goals.jsonl has 0 line(s) |
| planner[badfield] exit code == 0 | PASS | actual exit code 0 |
| planner[badfield] Result.success == False | PASS | status_code='POLICY_MISSING' detail='no authoritative TaskPolicy is loaded' |
| planner[badfield] status_code == POLICY_MISSING | PASS | actual status_code='POLICY_MISSING' |
| DecisionEvent reason_code sequence == ['POLICY_MISSING'] | PASS | actual sequence ['POLICY_MISSING'] |
| ExecutionEvent count == 0 | PASS | actual 0 ExecutionEvent(s): [] |
| RosCommEvent count == DecisionEvent count == planner runs | PASS | comm=1 decision=1 planner_runs=1 |
| event_id traceability (1 RosComm + 1 Decision + <=1 Execution each) | PASS | event_id groups: 1; malformed: none |
| BLOCKed event_ids never have an ExecutionEvent | PASS | leaked event_ids: none |
| correlatable REJECTED log lines == 1 | PASS | found 1 REJECTED line(s) in tests/evidence/20261009T141645Z/policy_missing_required_field/gateway.log |
| every REJECTED line carries a BLOCKed request_id and event_id | PASS | blocked request_ids=['neg-policy-0002'] |
| REJECTED lines declare downstream_goal_created=false | PASS | checked 1 line(s) |
| executor request_id set matches the ALLOWed set | PASS | journal=[] expected=[] |

### policy_nonfinite_region -- PASS

Policy region bound is NaN: never coerced, fail closed.

| Check | Result | Detail |
| --- | --- | --- |
| bringup: NavigationSim ready | PASS | NAVSIM_READY seen in tests/evidence/20261009T141645Z/policy_nonfinite_region/navsim.log |
| bringup: security_gateway ready | PASS | GATEWAY_READY seen in tests/evidence/20261009T141645Z/policy_nonfinite_region/gateway.log |
| navsim Goal count == 0 | PASS | journal tests/evidence/20261009T141645Z/policy_nonfinite_region/navsim_goals.jsonl has 0 line(s) |
| planner[nanregion] exit code == 0 | PASS | actual exit code 0 |
| planner[nanregion] Result.success == False | PASS | status_code='POLICY_MISSING' detail='no authoritative TaskPolicy is loaded' |
| planner[nanregion] status_code == POLICY_MISSING | PASS | actual status_code='POLICY_MISSING' |
| DecisionEvent reason_code sequence == ['POLICY_MISSING'] | PASS | actual sequence ['POLICY_MISSING'] |
| ExecutionEvent count == 0 | PASS | actual 0 ExecutionEvent(s): [] |
| RosCommEvent count == DecisionEvent count == planner runs | PASS | comm=1 decision=1 planner_runs=1 |
| event_id traceability (1 RosComm + 1 Decision + <=1 Execution each) | PASS | event_id groups: 1; malformed: none |
| BLOCKed event_ids never have an ExecutionEvent | PASS | leaked event_ids: none |
| correlatable REJECTED log lines == 1 | PASS | found 1 REJECTED line(s) in tests/evidence/20261009T141645Z/policy_nonfinite_region/gateway.log |
| every REJECTED line carries a BLOCKed request_id and event_id | PASS | blocked request_ids=['neg-policy-0003'] |
| REJECTED lines declare downstream_goal_created=false | PASS | checked 1 line(s) |
| executor request_id set matches the ALLOWed set | PASS | journal=[] expected=[] |

### policy_inactive -- PASS

Policy valid but active:false: treated as no authority, fail closed.

| Check | Result | Detail |
| --- | --- | --- |
| bringup: NavigationSim ready | PASS | NAVSIM_READY seen in tests/evidence/20261009T141645Z/policy_inactive/navsim.log |
| bringup: security_gateway ready | PASS | GATEWAY_READY seen in tests/evidence/20261009T141645Z/policy_inactive/gateway.log |
| navsim Goal count == 0 | PASS | journal tests/evidence/20261009T141645Z/policy_inactive/navsim_goals.jsonl has 0 line(s) |
| planner[inactive] exit code == 0 | PASS | actual exit code 0 |
| planner[inactive] Result.success == False | PASS | status_code='POLICY_MISSING' detail="authoritative policy '1.0-inactive' is marked active: false" |
| planner[inactive] status_code == POLICY_MISSING | PASS | actual status_code='POLICY_MISSING' |
| DecisionEvent reason_code sequence == ['POLICY_MISSING'] | PASS | actual sequence ['POLICY_MISSING'] |
| ExecutionEvent count == 0 | PASS | actual 0 ExecutionEvent(s): [] |
| RosCommEvent count == DecisionEvent count == planner runs | PASS | comm=1 decision=1 planner_runs=1 |
| event_id traceability (1 RosComm + 1 Decision + <=1 Execution each) | PASS | event_id groups: 1; malformed: none |
| BLOCKed event_ids never have an ExecutionEvent | PASS | leaked event_ids: none |
| correlatable REJECTED log lines == 1 | PASS | found 1 REJECTED line(s) in tests/evidence/20261009T141645Z/policy_inactive/gateway.log |
| every REJECTED line carries a BLOCKed request_id and event_id | PASS | blocked request_ids=['neg-policy-0004'] |
| REJECTED lines declare downstream_goal_created=false | PASS | checked 1 line(s) |
| executor request_id set matches the ALLOWed set | PASS | journal=[] expected=[] |

### task_id_mismatch_request_side -- PASS

Goal task_id differs from the authoritative policy: TASK_MISMATCH.

| Check | Result | Detail |
| --- | --- | --- |
| bringup: NavigationSim ready | PASS | NAVSIM_READY seen in tests/evidence/20261009T141645Z/task_id_mismatch_request_side/navsim.log |
| bringup: security_gateway ready | PASS | GATEWAY_READY seen in tests/evidence/20261009T141645Z/task_id_mismatch_request_side/gateway.log |
| navsim Goal count == 0 | PASS | journal tests/evidence/20261009T141645Z/task_id_mismatch_request_side/navsim_goals.jsonl has 0 line(s) |
| planner[taskmismatch] exit code == 0 | PASS | actual exit code 0 |
| planner[taskmismatch] Result.success == False | PASS | status_code='TASK_MISMATCH' detail="request task_id 'patrol_b_042' != policy task_id 'patrol_a_001'" |
| planner[taskmismatch] status_code == TASK_MISMATCH | PASS | actual status_code='TASK_MISMATCH' |
| DecisionEvent reason_code sequence == ['TASK_MISMATCH'] | PASS | actual sequence ['TASK_MISMATCH'] |
| ExecutionEvent count == 0 | PASS | actual 0 ExecutionEvent(s): [] |
| RosCommEvent count == DecisionEvent count == planner runs | PASS | comm=1 decision=1 planner_runs=1 |
| event_id traceability (1 RosComm + 1 Decision + <=1 Execution each) | PASS | event_id groups: 1; malformed: none |
| BLOCKed event_ids never have an ExecutionEvent | PASS | leaked event_ids: none |
| correlatable REJECTED log lines == 1 | PASS | found 1 REJECTED line(s) in tests/evidence/20261009T141645Z/task_id_mismatch_request_side/gateway.log |
| every REJECTED line carries a BLOCKed request_id and event_id | PASS | blocked request_ids=['neg-task-0001'] |
| REJECTED lines declare downstream_goal_created=false | PASS | checked 1 line(s) |
| executor request_id set matches the ALLOWed set | PASS | journal=[] expected=[] |

### task_id_mismatch_policy_side -- PASS

Authoritative policy is for patrol_b_999: a patrol_a_001 Goal is TASK_MISMATCH.

| Check | Result | Detail |
| --- | --- | --- |
| bringup: NavigationSim ready | PASS | NAVSIM_READY seen in tests/evidence/20261009T141645Z/task_id_mismatch_policy_side/navsim.log |
| bringup: security_gateway ready | PASS | GATEWAY_READY seen in tests/evidence/20261009T141645Z/task_id_mismatch_policy_side/gateway.log |
| navsim Goal count == 0 | PASS | journal tests/evidence/20261009T141645Z/task_id_mismatch_policy_side/navsim_goals.jsonl has 0 line(s) |
| planner[taskmismatch2] exit code == 0 | PASS | actual exit code 0 |
| planner[taskmismatch2] Result.success == False | PASS | status_code='TASK_MISMATCH' detail="request task_id 'patrol_a_001' != policy task_id 'patrol_b_999'" |
| planner[taskmismatch2] status_code == TASK_MISMATCH | PASS | actual status_code='TASK_MISMATCH' |
| DecisionEvent reason_code sequence == ['TASK_MISMATCH'] | PASS | actual sequence ['TASK_MISMATCH'] |
| ExecutionEvent count == 0 | PASS | actual 0 ExecutionEvent(s): [] |
| RosCommEvent count == DecisionEvent count == planner runs | PASS | comm=1 decision=1 planner_runs=1 |
| event_id traceability (1 RosComm + 1 Decision + <=1 Execution each) | PASS | event_id groups: 1; malformed: none |
| BLOCKed event_ids never have an ExecutionEvent | PASS | leaked event_ids: none |
| correlatable REJECTED log lines == 1 | PASS | found 1 REJECTED line(s) in tests/evidence/20261009T141645Z/task_id_mismatch_policy_side/gateway.log |
| every REJECTED line carries a BLOCKed request_id and event_id | PASS | blocked request_ids=['neg-task-0002'] |
| REJECTED lines declare downstream_goal_created=false | PASS | checked 1 line(s) |
| executor request_id set matches the ALLOWed set | PASS | journal=[] expected=[] |

### frame_id_invalid -- PASS

Goal frame_id=camera_link while policy coordinate_frame=map: INVALID_TARGET.

| Check | Result | Detail |
| --- | --- | --- |
| bringup: NavigationSim ready | PASS | NAVSIM_READY seen in tests/evidence/20261009T141645Z/frame_id_invalid/navsim.log |
| bringup: security_gateway ready | PASS | GATEWAY_READY seen in tests/evidence/20261009T141645Z/frame_id_invalid/gateway.log |
| navsim Goal count == 0 | PASS | journal tests/evidence/20261009T141645Z/frame_id_invalid/navsim_goals.jsonl has 0 line(s) |
| planner[badframe] exit code == 0 | PASS | actual exit code 0 |
| planner[badframe] Result.success == False | PASS | status_code='INVALID_TARGET' detail="target frame_id 'camera_link' != policy coordinate_frame 'map'" |
| planner[badframe] status_code == INVALID_TARGET | PASS | actual status_code='INVALID_TARGET' |
| DecisionEvent reason_code sequence == ['INVALID_TARGET'] | PASS | actual sequence ['INVALID_TARGET'] |
| ExecutionEvent count == 0 | PASS | actual 0 ExecutionEvent(s): [] |
| RosCommEvent count == DecisionEvent count == planner runs | PASS | comm=1 decision=1 planner_runs=1 |
| event_id traceability (1 RosComm + 1 Decision + <=1 Execution each) | PASS | event_id groups: 1; malformed: none |
| BLOCKed event_ids never have an ExecutionEvent | PASS | leaked event_ids: none |
| correlatable REJECTED log lines == 1 | PASS | found 1 REJECTED line(s) in tests/evidence/20261009T141645Z/frame_id_invalid/gateway.log |
| every REJECTED line carries a BLOCKed request_id and event_id | PASS | blocked request_ids=['neg-frame-0001'] |
| REJECTED lines declare downstream_goal_created=false | PASS | checked 1 line(s) |
| executor request_id set matches the ALLOWed set | PASS | journal=[] expected=[] |

### target_nan -- PASS

Goal target.x = NaN: INVALID_TARGET, never coerced.

| Check | Result | Detail |
| --- | --- | --- |
| bringup: NavigationSim ready | PASS | NAVSIM_READY seen in tests/evidence/20261009T141645Z/target_nan/navsim.log |
| bringup: security_gateway ready | PASS | GATEWAY_READY seen in tests/evidence/20261009T141645Z/target_nan/gateway.log |
| navsim Goal count == 0 | PASS | journal tests/evidence/20261009T141645Z/target_nan/navsim_goals.jsonl has 0 line(s) |
| planner[nan] exit code == 0 | PASS | actual exit code 0 |
| planner[nan] Result.success == False | PASS | status_code='INVALID_TARGET' detail='target.x is not a finite number: nan' |
| planner[nan] status_code == INVALID_TARGET | PASS | actual status_code='INVALID_TARGET' |
| DecisionEvent reason_code sequence == ['INVALID_TARGET'] | PASS | actual sequence ['INVALID_TARGET'] |
| ExecutionEvent count == 0 | PASS | actual 0 ExecutionEvent(s): [] |
| RosCommEvent count == DecisionEvent count == planner runs | PASS | comm=1 decision=1 planner_runs=1 |
| event_id traceability (1 RosComm + 1 Decision + <=1 Execution each) | PASS | event_id groups: 1; malformed: none |
| BLOCKed event_ids never have an ExecutionEvent | PASS | leaked event_ids: none |
| correlatable REJECTED log lines == 1 | PASS | found 1 REJECTED line(s) in tests/evidence/20261009T141645Z/target_nan/gateway.log |
| every REJECTED line carries a BLOCKed request_id and event_id | PASS | blocked request_ids=['neg-nan-0001'] |
| REJECTED lines declare downstream_goal_created=false | PASS | checked 1 line(s) |
| executor request_id set matches the ALLOWed set | PASS | journal=[] expected=[] |

### target_infinite -- PASS

Goal target.y = inf: INVALID_TARGET, never coerced.

| Check | Result | Detail |
| --- | --- | --- |
| bringup: NavigationSim ready | PASS | NAVSIM_READY seen in tests/evidence/20261009T141645Z/target_infinite/navsim.log |
| bringup: security_gateway ready | PASS | GATEWAY_READY seen in tests/evidence/20261009T141645Z/target_infinite/gateway.log |
| navsim Goal count == 0 | PASS | journal tests/evidence/20261009T141645Z/target_infinite/navsim_goals.jsonl has 0 line(s) |
| planner[inf] exit code == 0 | PASS | actual exit code 0 |
| planner[inf] Result.success == False | PASS | status_code='INVALID_TARGET' detail='target.y is not a finite number: inf' |
| planner[inf] status_code == INVALID_TARGET | PASS | actual status_code='INVALID_TARGET' |
| DecisionEvent reason_code sequence == ['INVALID_TARGET'] | PASS | actual sequence ['INVALID_TARGET'] |
| ExecutionEvent count == 0 | PASS | actual 0 ExecutionEvent(s): [] |
| RosCommEvent count == DecisionEvent count == planner runs | PASS | comm=1 decision=1 planner_runs=1 |
| event_id traceability (1 RosComm + 1 Decision + <=1 Execution each) | PASS | event_id groups: 1; malformed: none |
| BLOCKed event_ids never have an ExecutionEvent | PASS | leaked event_ids: none |
| correlatable REJECTED log lines == 1 | PASS | found 1 REJECTED line(s) in tests/evidence/20261009T141645Z/target_infinite/gateway.log |
| every REJECTED line carries a BLOCKed request_id and event_id | PASS | blocked request_ids=['neg-inf-0001'] |
| REJECTED lines declare downstream_goal_created=false | PASS | checked 1 line(s) |
| executor request_id set matches the ALLOWed set | PASS | journal=[] expected=[] |

### duplicate_request_id -- PASS

Same request_id sent twice: ALLOW then DUPLICATE_REQUEST (replay guard).

| Check | Result | Detail |
| --- | --- | --- |
| bringup: NavigationSim ready | PASS | NAVSIM_READY seen in tests/evidence/20261009T141645Z/duplicate_request_id/navsim.log |
| bringup: security_gateway ready | PASS | GATEWAY_READY seen in tests/evidence/20261009T141645Z/duplicate_request_id/gateway.log |
| navsim Goal count == 1 | PASS | journal tests/evidence/20261009T141645Z/duplicate_request_id/navsim_goals.jsonl has 1 line(s) |
| planner[first] exit code == 0 | PASS | actual exit code 0 |
| planner[replay] exit code == 0 | PASS | actual exit code 0 |
| planner[first] Result.success == True | PASS | status_code='EXECUTED' detail='recorded target (2.0, 2.0, 0.0) in frame map; no path planning performed' |
| planner[first] status_code == EXECUTED | PASS | actual status_code='EXECUTED' |
| planner[replay] Result.success == False | PASS | status_code='DUPLICATE_REQUEST' detail="request_id 'neg-dup-0001' was already received within the duplicate window" |
| planner[replay] status_code == DUPLICATE_REQUEST | PASS | actual status_code='DUPLICATE_REQUEST' |
| DecisionEvent reason_code sequence == ['ALLOW_IN_POLICY', 'DUPLICATE_REQUEST'] | PASS | actual sequence ['ALLOW_IN_POLICY', 'DUPLICATE_REQUEST'] |
| ExecutionEvent count == 1 | PASS | actual 1 ExecutionEvent(s): ['EXECUTED'] |
| RosCommEvent count == DecisionEvent count == planner runs | PASS | comm=2 decision=2 planner_runs=2 |
| event_id traceability (1 RosComm + 1 Decision + <=1 Execution each) | PASS | event_id groups: 2; malformed: none |
| BLOCKed event_ids never have an ExecutionEvent | PASS | leaked event_ids: none |
| correlatable REJECTED log lines == 1 | PASS | found 1 REJECTED line(s) in tests/evidence/20261009T141645Z/duplicate_request_id/gateway.log |
| every REJECTED line carries a BLOCKed request_id and event_id | PASS | blocked request_ids=['neg-dup-0001'] |
| REJECTED lines declare downstream_goal_created=false | PASS | checked 1 line(s) |
| executor request_id set matches the ALLOWed set | PASS | journal=['neg-dup-0001'] expected=['neg-dup-0001'] |

### rate_limit -- PASS

max_requests_per_minute=2: third in-region Goal is RATE_LIMIT.

| Check | Result | Detail |
| --- | --- | --- |
| bringup: NavigationSim ready | PASS | NAVSIM_READY seen in tests/evidence/20261009T141645Z/rate_limit/navsim.log |
| bringup: security_gateway ready | PASS | GATEWAY_READY seen in tests/evidence/20261009T141645Z/rate_limit/gateway.log |
| navsim Goal count == 2 | PASS | journal tests/evidence/20261009T141645Z/rate_limit/navsim_goals.jsonl has 2 line(s) |
| planner[r1] exit code == 0 | PASS | actual exit code 0 |
| planner[r2] exit code == 0 | PASS | actual exit code 0 |
| planner[r3] exit code == 0 | PASS | actual exit code 0 |
| planner[r1] Result.success == True | PASS | status_code='EXECUTED' detail='recorded target (1.0, 1.0, 0.0) in frame map; no path planning performed' |
| planner[r1] status_code == EXECUTED | PASS | actual status_code='EXECUTED' |
| planner[r2] Result.success == True | PASS | status_code='EXECUTED' detail='recorded target (2.0, 2.0, 0.0) in frame map; no path planning performed' |
| planner[r2] status_code == EXECUTED | PASS | actual status_code='EXECUTED' |
| planner[r3] Result.success == False | PASS | status_code='RATE_LIMIT' detail='more than 2.0 admitted requests within 60.0s' |
| planner[r3] status_code == RATE_LIMIT | PASS | actual status_code='RATE_LIMIT' |
| DecisionEvent reason_code sequence == ['ALLOW_IN_POLICY', 'ALLOW_IN_POLICY', 'RATE_LIMIT'] | PASS | actual sequence ['ALLOW_IN_POLICY', 'ALLOW_IN_POLICY', 'RATE_LIMIT'] |
| ExecutionEvent count == 2 | PASS | actual 2 ExecutionEvent(s): ['EXECUTED', 'EXECUTED'] |
| RosCommEvent count == DecisionEvent count == planner runs | PASS | comm=3 decision=3 planner_runs=3 |
| event_id traceability (1 RosComm + 1 Decision + <=1 Execution each) | PASS | event_id groups: 3; malformed: none |
| BLOCKed event_ids never have an ExecutionEvent | PASS | leaked event_ids: none |
| correlatable REJECTED log lines == 1 | PASS | found 1 REJECTED line(s) in tests/evidence/20261009T141645Z/rate_limit/gateway.log |
| every REJECTED line carries a BLOCKed request_id and event_id | PASS | blocked request_ids=['neg-rate-0003'] |
| REJECTED lines declare downstream_goal_created=false | PASS | checked 1 line(s) |
| executor request_id set matches the ALLOWed set | PASS | journal=['neg-rate-0001', 'neg-rate-0002'] expected=['neg-rate-0001', 'neg-rate-0002'] |

### execution_timeout -- PASS

Executor stalls past execution_timeout_sec: EXECUTION_TIMEOUT, audited.

| Check | Result | Detail |
| --- | --- | --- |
| bringup: NavigationSim ready | PASS | NAVSIM_READY seen in tests/evidence/20261009T141645Z/execution_timeout/navsim.log |
| bringup: security_gateway ready | PASS | GATEWAY_READY seen in tests/evidence/20261009T141645Z/execution_timeout/gateway.log |
| navsim Goal count == 1 | PASS | journal tests/evidence/20261009T141645Z/execution_timeout/navsim_goals.jsonl has 1 line(s) |
| planner[timeout] exit code == 0 | PASS | actual exit code 0 |
| planner[timeout] Result.success == False | PASS | status_code='EXECUTION_TIMEOUT' detail='downstream Goal f978be88d84a40829e6a8a0fa1c50f8c WAS created and accepted, but its execution result did not arrive withi' |
| planner[timeout] status_code == EXECUTION_TIMEOUT | PASS | actual status_code='EXECUTION_TIMEOUT' |
| DecisionEvent reason_code sequence == ['ALLOW_IN_POLICY'] | PASS | actual sequence ['ALLOW_IN_POLICY'] |
| ExecutionEvent count == 1 | PASS | actual 1 ExecutionEvent(s): ['EXECUTION_TIMEOUT'] |
| RosCommEvent count == DecisionEvent count == planner runs | PASS | comm=1 decision=1 planner_runs=1 |
| event_id traceability (1 RosComm + 1 Decision + <=1 Execution each) | PASS | event_id groups: 1; malformed: none |
| BLOCKed event_ids never have an ExecutionEvent | PASS | leaked event_ids: none |
| correlatable REJECTED log lines == 0 | PASS | found 0 REJECTED line(s) in tests/evidence/20261009T141645Z/execution_timeout/gateway.log |
| executor request_id set matches the ALLOWed set | PASS | journal=['neg-timeout-0001'] expected=['neg-timeout-0001'] |

