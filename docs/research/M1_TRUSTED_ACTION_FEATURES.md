# M1 可信 Action 特征对接评估

> 基准：`86a8910bf4560dfe455bec09bc503600c30bf670`
> 参考：`docs/integration/TRUSTED_ACTION_EVENT_HANDOFF_TO_M1.md`（M2 第二轮交付）

## 1. 结论先行

**`M1_TRUSTED_ACTION_DATA_SOURCE_READY` = BLOCKED**

理由：截至共同基准，M2 的研究入口只证明过**自定义 `CandidateTask`**
的接收与身份绑定，**没有**证明能捕获 Gateway 的真实 Action `SendGoal`。
因此 M1 拿不到可信的 `action_send_goal_received_count`。

## 2. 两个计数语义必须分开

| 语义 | 来源 | 现状 |
| --- | --- | --- |
| `candidate_task_received_count` | M2 自定义前置入口账本 | 研究阶段已验证（Domain 60，研究 keystore） |
| `action_send_goal_received_count` | Gateway 的 `rq/rg/guarded_navigate/_action/send_goalRequest` | **未实现**（需 Action 请求类型 typesupport 接线） |

**不得**把前者重命名为后者。本轮 M1 的窗口特征里，
`message_count` 严格是**话题消息数**，与上述两者都不同。

## 3. 对 M2 接口的核验结果

按任务书要求逐项核验 `trusted-action-events/1`：

| 核验项 | 结果 |
| --- | --- |
| 真实接收位置 | 自定义 DDS 主题 `rt/m2/candidate_task`（研究 keystore） |
| 是否运行在安全 Domain | 是（Domain 60，Enforce，研究 keystore） |
| 资源与操作 | 记录 `resource`，但**不是** `/rg/guarded_navigate` 的 Action |
| Goal UUID | 有（自定义载荷内） |
| 时间窗口 | 30 s，含 `INGRESS_OPENED` 覆盖水位 |
| 缺口检测 | 有（`coverage=COMPLETE/PARTIAL/UNKNOWN`） |
| 来源认证 | 有（writer GUID → participant → 证书主体） |
| M1 只读可达 | 是（JSONL 文件） |
| 计数可独立复算 | 是（窗口聚合器可从原始事件重算） |
| 有原始 ROS 2 数据对照 | 部分（M2 有事件日志，非 Gateway 审计） |

**判定：`RESEARCH_CONTROLLED_OBSERVATION`。**
它满足研究可用性，但**不满足**作为正式在线安全输入的条件。

## 4. 如果将来对接，M1 只读适配器必须具备

1. Schema 与版本校验（`trusted-action-count-window/1`）；
2. 完整性校验：`coverage != COMPLETE` → **UNKNOWN**，绝不当作 0；
3. 时间范围判断：`window_end <= as_of - safety_lag`，只消费已结束窗口；
4. 资源与操作匹配；
5. Domain 校验；
6. 重复事件去重；
7. 缺失/错误 → UNKNOWN（失败关闭）。

## 5. F0 因果边界

M1 位于 F0 准入之前，因此：

* 只能用**决策前已经关闭**的历史窗口；
* **不得**使用当前请求在 Gateway 的 ALLOW/BLOCK、执行结果或 NavigationSim Goal；
* 本轮采集的特征里不存在这些字段（采集时它们尚未发生）。

## 6. 本轮实际做法

本轮 M1 **没有依赖** M2 的任何 Action 计数：
所有特征都来自本进程直接观测的话题消息与图变化。
因此本轮结论不因 M2 未完成而失效，但也因此**无法**提供
"基于业务请求数的风险特征"。
