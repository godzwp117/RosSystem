# M1 第六轮：观测覆盖质量与可追溯性

> run_id：`m1p6-20261020T123752Z`
> 代码：`modules/member1_comm/research/window_aggregator.py`

## 1. 修复的三个覆盖缺陷

### 1.1 `_uncovered_sec` 从未被正确累计

第五轮里它是一个恒为 0 的字段（只有一处 `+= 0.0`）。
现在 `tick(expected_period=...)` 会检测实际间隔，
超过预期周期 2 倍即记一次迟到，并把 `gap - expected_period` 累加进未覆盖时长。

### 1.2 `_late_ticks` 只存在于接线层，聚合器内部看不到

第五轮由 collector 自己统计、且只保留前 20 条样本；
现在聚合器自身计数，`summary()['late_ticks']` 与 `uncovered_sec` 一起输出。

### 1.3 单次成功轮询被当成"整窗口被观察"

这是最危险的一条：只轮询一两次也会得到 `status=VALID`，
于是"没有变化"可能只是"几乎没看"。

现在每个窗口输出：

```json
"polls_expected": 150,
"successful_polls": 131,
"observed_span_sec": 29.8,
"graph_time_coverage_ratio": 0.993,
```

并且**覆盖率 < 50% 时状态降为 `DEGRADED`**，附原因：
`"图观测仅覆盖 x% 的窗口…不能据此断言该窗口没有拓扑变化"`。

## 2. 状态语义（不得混淆）

| 状态 | 含义 |
| --- | --- |
| `VALID` | 轮询成功且覆盖足够 |
| `DEGRADED` | 有失败轮询，或覆盖率不足 |
| `FAILED` | 全部轮询失败 |
| `NOT_RUN` | 本窗口根本没有轮询（采集器可能未运行） |

`overall_observation_status` 由两通道合成：
`FULL` 需消息 `OK` **且** 图 `VALID`；只有一路可用是 `PARTIAL`；都不可用是 `INSUFFICIENT`。

## 3. 原始事件导出（可独立复算）

每个会话新增 `raw_events`：

```json
{"messages": [0.02, 0.04, ...],
 "graph_transitions": [3.4, 18.2, ...],
 "polls": [0.0, 0.2, ...],
 "messages_truncated": 0}
```

只含**时间戳**（相对会话起点），不含消息内容，因此非敏感。
有了它，任何第三方都能用窗口定义重算 `gap_median/p95/max/cv` 与
`graph_snapshot_transition_count`，不必信任我方聚合结果。

## 4. 确定性故障注入测试

新增/更新 26 项窗口测试，其中覆盖类：

* 只有 1 次成功轮询 → `DEGRADED` + 覆盖率 < 0.5；
* 覆盖整窗口的轮询 → `VALID`；
* tick 停顿 5 秒 → `late_ticks ≥ 1` 且 `uncovered_sec > 0`；
* `polls_expected` 被正确输出；
* 轮询全失败 → `FAILED`，不当作"无变化"。

## 5. 旧 `tested_commit.json` 的 SHA 错误

第五轮证据里 `m1_tested_code_sha` 写的是 **`a5e70df…`（父提交）**，
而实际产出证据的代码是 `4b216c4…`。这是**记录错误**，已确认。

本轮修正做法：

1. 先提交代码；
2. 用提交后的 HEAD 作为 `M1_TESTED_CODE_SHA` 写入证据；
3. 证据里同时记录 `parent_sha` 与 `tested_sha`，两者都不可混淆。

旧文件**不追溯改写**，只在新一轮证据中记录正确值并说明差异。
