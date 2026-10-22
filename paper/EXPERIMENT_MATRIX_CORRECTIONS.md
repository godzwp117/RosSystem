# P01–P12 矩阵证据更正（阶段 1）

> 本轮新增运行：P07 隔离实验、P09 超时重测。基线矩阵与验收文件已按真实结果更新；
> 不修改 `PAPER_FACTS_BASELINE.*`，增量记录见 `PAPER_FACTS_NEW_EXPERIMENTS.md`。

## E-001：P07 原证据不匹配 → 已用隔离实验更正

| 项 | 内容 |
| --- | --- |
| 原状态 | PASS |
| 原证据 | 三真实运行（M3 实际 `ALLOW_RECOMMENDED`）+ DDS S5 的 Gateway `OUT_OF_REGION` |
| 问题 | Gateway TaskPolicy 阻断 ≠ M3 建议阻断；原证据不能支撑目标 |
| 新实验 | `tests/integration/p07_m3_block_isolation.py`，run `p07-20261022T024200Z` |
| 真实条件 | 真实 M3 External；只读测试策略 `[0,1]²`；目标 (2.0,2.0) 在主策略内、测试策略外 |
| 实测 | M3 `BLOCK_RECOMMENDED` / `OUT_OF_REGION`；F0 `ADAPTER_BLOCK` / `ADAPTER_MODULE_STATUS_NOT_PROCEED`；detail 明确 `task_risk`；Planner `submitted=false`；无 Gateway/Goal |
| 结果 | **PASS（CONTROLLED_ISOLATION）** |
| 保留 | Gateway S5 `OUT_OF_REGION` 仍作为**独立**的 TaskPolicy 阻断结论，不再充当 P07 证据 |
| 限制 | M1/M2 为 MOCK，仅用于隔离；不是三真实结果；Gateway/NavigationSim 未启动，0 Goal 由“未提交”推出 |

## E-002：P09 超时语义重测

| 项 | 内容 |
| --- | --- |
| 原状态 | NOT_RUN（1.1.0 未重跑） |
| 新实验 | `tests/integration/p09_planner_timeout.py`，run `p09-20261022T030000Z` |
| 设置 | NavigationSim 延迟 8 s；Gateway execution timeout 10 s；Planner result timeout 1 s |
| 实测 | Planner `RESULT_TIMEOUT`、exit 2、耗时 1.573 s；Gateway `RosCommEvent` 1、`DecisionEvent ALLOW_IN_POLICY`；NavigationSim Goal 1；`ExecutionEvent EXECUTED`，`finished_at=02:37:47.665Z`，晚于 Planner 退出 |
| 结论 | Planner 超时 ≠ Gateway 未收到 ≠ BLOCK ≠ 未执行；本次超时路径**没有发送取消** |
| 限制 | 同一容器时钟；NavigationSim `recorded_only`；不得推断跨主机严格因果 |

## 其他场景复用

| 场景 | 状态 | 证据 |
| --- | --- | --- |
| 缺失身份 attestation | PASS | Gateway G2（`m2_gateway_identity_v110`） |
| 错误 request_digest / 目标绑定 | PASS | Gateway G3 + 单元测试 |
| 重放 nonce | PASS | M2 链 + Gateway + repeats |
| 签名无效 | PASS | Ed25519 单元测试 + M2 链 |
| Gateway 拒绝 | PASS | G2/G3/G4 |
| 取消与重复请求 | 部分 | 重复请求有单元测试；取消语义未在本轮新增真实运行 |

## 矩阵汇总（更新后）

| 状态 | 数量 | 条目 |
| --- | --- | --- |
| PASS | 10 | P03–P12（P07 隔离、P09 重测） |
| BLOCKED | 1 | P01（依赖 M1 受信任 NORMAL） |
| NOT_VERIFIED | 1 | P02（无真实 M1 SUSPICIOUS） |
| NOT_RUN | 0 | — |

`P01` 仍 BLOCKED；`LEVEL3` 仍 BLOCKED。P07/P09 的 PASS **不改变**三真正向结论。
