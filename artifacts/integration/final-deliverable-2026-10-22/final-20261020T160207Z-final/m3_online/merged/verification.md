# M3 在线联调证据复核（独立工具输出）

- 证据目录：`/ws/artifacts/integration/final-deliverable-2026-10-22/final-20261020T160207Z-final/m3_online/merged`
- Gateway 审计行数：0
- NavigationSim Goal 行数：0
- 复核检查项：42（失败 24）
- **判定：`FAIL`**

## 场景关联表

| 场景 | request_id | 适配层决策 | M3 状态 | Planner outcome | Gateway arrival | Gateway decision | Execution | Goal 数 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ON01 | `None` | ADAPTER_BLOCK | None | None | 0 | - | 0 | 0 |
| ON02 | `None` | ADAPTER_BLOCK | None | None | 0 | - | 0 | 0 |
| ON03 | `None` | ADAPTER_BLOCK | None | None | 0 | - | 0 | 0 |
| ON04 | `None` | ADAPTER_BLOCK | None | None | 0 | - | 0 | 0 |
| ON05 | `None` | ADAPTER_BLOCK | None | None | 0 | - | 0 | 0 |
| ON06 | `None` | ADAPTER_BLOCK | None | None | 0 | - | 0 | 0 |

## 检查明细

- [FAIL] `ON01` ADAPTER_LOG_MISSING :: adapter_ON01.jsonl
- [FAIL] `ON01` REQUEST_ID_MISMATCH :: 适配层记录 request_id=None 与权威清单 'on01-legal-allow-final-20261020T160207Z-final-six' 不一致
- [FAIL] `ON01` RUN_ID_MISMATCH :: 适配层记录 run_id=None 与权威清单 'final-20261020T160207Z-final-six' 不一致
- [FAIL] `ON01` BLOCK_NO_PLANNER :: outcome=None
- [PASS] `ON01` BLOCK_NO_GATEWAY_ARRIVAL :: Gateway arrival=0
- [PASS] `ON01` BLOCK_NO_GOAL :: Goal 数=0
- [PASS] `ON01` BLOCK_NO_EXECUTION :: ExecutionEvent=0
- [FAIL] `ON02` ADAPTER_LOG_MISSING :: adapter_ON02.jsonl
- [FAIL] `ON02` REQUEST_ID_MISMATCH :: 适配层记录 request_id=None 与权威清单 'on02-oor-block-final-20261020T160207Z-final-six' 不一致
- [FAIL] `ON02` RUN_ID_MISMATCH :: 适配层记录 run_id=None 与权威清单 'final-20261020T160207Z-final-six' 不一致
- [FAIL] `ON02` BLOCK_NO_PLANNER :: outcome=None
- [PASS] `ON02` BLOCK_NO_GATEWAY_ARRIVAL :: Gateway arrival=0
- [PASS] `ON02` BLOCK_NO_GOAL :: Goal 数=0
- [PASS] `ON02` BLOCK_NO_EXECUTION :: ExecutionEvent=0
- [FAIL] `ON03` ADAPTER_LOG_MISSING :: adapter_ON03.jsonl
- [FAIL] `ON03` REQUEST_ID_MISMATCH :: 适配层记录 request_id=None 与权威清单 'on03-final-20261020T160207Z-final-six' 不一致
- [FAIL] `ON03` RUN_ID_MISMATCH :: 适配层记录 run_id=None 与权威清单 'final-20261020T160207Z-final-six' 不一致
- [FAIL] `ON03` BLOCK_NO_PLANNER :: outcome=None
- [PASS] `ON03` BLOCK_NO_GATEWAY_ARRIVAL :: Gateway arrival=0
- [PASS] `ON03` BLOCK_NO_GOAL :: Goal 数=0
- [PASS] `ON03` BLOCK_NO_EXECUTION :: ExecutionEvent=0
- [FAIL] `ON04` ADAPTER_LOG_MISSING :: adapter_ON04.jsonl
- [FAIL] `ON04` REQUEST_ID_MISMATCH :: 适配层记录 request_id=None 与权威清单 'on04-final-20261020T160207Z-final-six' 不一致
- [FAIL] `ON04` RUN_ID_MISMATCH :: 适配层记录 run_id=None 与权威清单 'final-20261020T160207Z-final-six' 不一致
- [FAIL] `ON04` BLOCK_NO_PLANNER :: outcome=None
- [PASS] `ON04` BLOCK_NO_GATEWAY_ARRIVAL :: Gateway arrival=0
- [PASS] `ON04` BLOCK_NO_GOAL :: Goal 数=0
- [PASS] `ON04` BLOCK_NO_EXECUTION :: ExecutionEvent=0
- [FAIL] `ON05` ADAPTER_LOG_MISSING :: adapter_ON05.jsonl
- [FAIL] `ON05` REQUEST_ID_MISMATCH :: 适配层记录 request_id=None 与权威清单 'on05-gateway-authority-final-20261020T160207Z-final-six' 不一致
- [FAIL] `ON05` RUN_ID_MISMATCH :: 适配层记录 run_id=None 与权威清单 'final-20261020T160207Z-final-six' 不一致
- [FAIL] `ON05` BLOCK_NO_PLANNER :: outcome=None
- [PASS] `ON05` BLOCK_NO_GATEWAY_ARRIVAL :: Gateway arrival=0
- [PASS] `ON05` BLOCK_NO_GOAL :: Goal 数=0
- [PASS] `ON05` BLOCK_NO_EXECUTION :: ExecutionEvent=0
- [FAIL] `ON06` ADAPTER_LOG_MISSING :: adapter_ON06.jsonl
- [FAIL] `ON06` REQUEST_ID_MISMATCH :: 适配层记录 request_id=None 与权威清单 'on06-final-20261020T160207Z-final-six' 不一致
- [FAIL] `ON06` RUN_ID_MISMATCH :: 适配层记录 run_id=None 与权威清单 'final-20261020T160207Z-final-six' 不一致
- [FAIL] `ON06` BLOCK_NO_PLANNER :: outcome=None
- [PASS] `ON06` BLOCK_NO_GATEWAY_ARRIVAL :: Gateway arrival=0
- [PASS] `ON06` BLOCK_NO_GOAL :: Goal 数=0
- [PASS] `ON06` BLOCK_NO_EXECUTION :: ExecutionEvent=0
