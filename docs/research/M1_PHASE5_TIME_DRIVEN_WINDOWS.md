# M1 第五轮 G1：时间驱动窗口与双通道观测

> 分支：`research/m1-graph-observation-dataset`
> 继承：`a5e70df63521ee63195187368071f9b2299e3437`
> run_id：`m1g-20261020T084933Z`
> 容器 `rg_m1g`，Domain 69

## 1. 第四轮的真实缺陷（先复现，再修）

第四轮采集器把窗口关闭绑在**消息到达**上：

```python
def _on_message(self, _msg):
    ...
    while stamp - self.window_start >= self.window_sec:
        self._close_window(...)
```

于是没有业务消息时窗口永不关闭，`_close_window` 里
`samples < MIN_SAMPLES` 直接判不足并 return，**图特征根本没有输出路径**。
发现churn 与侦察两个异常会话因此在第四轮整段消失。

其余同源问题：

| # | 问题 | 后果 |
| --- | --- | --- |
| 1 | 窗口关闭依赖消息 | 零消息 → 无窗口 |
| 2 | 图事件无独立时间戳归属 | 变化被算到下一窗口 |
| 3 | 图与消息共用 `MIN_SAMPLES` 有效性 | 图有效也因消息少被丢弃 |
| 4 | `distinct_publishers` 跨窗口累计 | 发布者数虚高 |
| 5 | 图查询异常被当作"无变化" | 静默低估 |
| 6 | 轮询频率限制可观测性 | 短时变化漏采 |

## 2. 重构：纯逻辑聚合器 + 薄接线

拆成两层，使窗口语义可以被**确定性单测**钉死：

* `modules/member1_comm/research/window_aggregator.py`
  注入 `clock` 与 `snapshot`，无 rclpy 依赖；
* `scripts/m1_graph_collector.py`
  只做 rclpy 接线（真实单调时钟 + `get_node_names/get_topic_names_and_types`）。

### 契约 `m1-observation-window/2`

```json
{"contract":"m1-observation-window/2",
 "window_start":0.0,"window_end":30.0,"window_complete":true,
 "message_observation":{"status":"INSUFFICIENT","samples":0,
   "reason":"样本 0 < 最小样本 10；不给出间隔统计"},
 "graph_observation":{"status":"VALID","successful_polls":131,
   "failed_polls":0,"features":{"graph_snapshot_transition_count":45}},
 "overall_observation_status":"PARTIAL"}
```

关键：**消息不足 ≠ 图观测无效**；`overall` 反映两路合成，
任何一路不可用都不会谎称 `FULL`。

## 3. 时间推进语义

* 单调时钟 `time.monotonic()`，**不用墙钟**算间隔；
* 区间 `[start, end)`，左闭右开；
* 定时器每 50 ms tick，即使无任何消息也推进；
* 一次 tick 迟到跨过多个窗口时，**逐个补齐**（空窗口），不合并、不丢失；
* 会话结束把最后一个不完整窗口单独关闭并标 `window_complete=false`；
* 迟到（早于当前窗口起点）的消息**计数并丢弃**，不串到后续窗口。

## 4. 自动化测试（22 项，全部通过）

`tests/unit/test_m1_time_driven_windows.py`：

| 类别 | 覆盖 |
| --- | --- |
| 零消息 | 窗口仍关闭；无伪造间隔统计 |
| 零消息 + 图变化 | 图特征有效，合成 PARTIAL |
| 1–9 条消息 | `INSUFFICIENT`，不填充 |
| ≥10 条消息 | 正常统计 |
| 边界消息 | 恰在边界只归属后一窗口 |
| 迟到消息 | 计数并丢弃，不串窗口 |
| 多次到期 | 连续补齐 3 个窗口，首尾相接 |
| 图失败 | `FAILED` / `DEGRADED`，不当作 0 |
| 无轮询 | `NOT_RUN` |
| 发布者去重 | 按窗口重置 |
| 尾部窗口 | `window_complete=false` |
| 高频内存 | 时间戳缓冲上限生效 |
| 合成矩阵 | 4 种组合映射正确 |

## 5. 真实 ROS 2 复验

零消息冒烟（35 s、10 s 窗口）：**4 个窗口全部关闭，3 个图通道 VALID**。
第四轮在同样条件下会得到 0 个窗口。

G2 的 8 个场景全部产出 `graph_observation=VALID`，
其中 6 个 `message_observation=INSUFFICIENT` —— 正是本轮要修复的情形。

## 6. 仍未解决

* 轮询周期 0.2 s 决定了可观测性上限，短于该周期的变化会漏（见 G2-08：0 次）；
* 快照差异**不是** DDS Discovery 报文数，只是"两次轮询之间拓扑变了"；
* tick 迟到会被记录（`tick_lateness_samples`），但不会追溯补采；
* 纯查询行为在快照上不可见（见 G2-05）。
