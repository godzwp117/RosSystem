# 受控在线 request_id 级验收

- 目录：`artifacts/integration/final-deliverable-2026-10-22/harden-20261020T170655Z/controlled_online/stack-a`
- 检查：40 项，失败 0 项
- 结论：**PASS**

| 场景 | request_id | F0 | Gateway 到达 | 决策 | Goal |
| --- | --- | --- | --- | --- | --- |
| ON01 | `on01-legal-allow-harden-20261020T170655Z-controlled` | READY_FOR_GATEWAY_SUBMISSION | 1 | ALLOW | 1 |
| ON02 | `on02-oor-block-harden-20261020T170655Z-controlled` | ADAPTER_BLOCK | 0 | - | 0 |
| ON05 | `on05-gateway-authority-harden-20261020T170655Z-controlled` | READY_FOR_GATEWAY_SUBMISSION | 1 | BLOCK | 0 |
