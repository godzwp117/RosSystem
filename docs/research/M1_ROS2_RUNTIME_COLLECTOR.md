# M1 真实 ROS 2 运行时观测采集器（专项② P1）

> 代码基准：`be47ccd6c1b19460b65abc0ea8004706383d01d4`
> 采集器：`modules/member1_comm/collector/ros2_window.py`
> 证据：`artifacts/research/m1/m1audit-20261018T160049Z/observation/`
> 环境：容器 `rg_m1`（`ros:jazzy`），**ROS_DOMAIN_ID=57**，独立于演示域 56/43

## 1. 它解决什么问题

窗口级模型要用的特征必须**从真实 ROS 2 通信事件测出来**，
不能由实验算子在 JSON 里自报。此前 `request_count` 由适配层直接写死
（`f0_runtime.request_count = 12`），这在本专项中被明确认定为不合格：
它是**自报值**，不是观测值。

本采集器改用 rclpy 真实订阅，按实际到达时间戳计算：

| 特征 | 定义 |
| --- | --- |
| `request_count` | 该窗口内**本进程实际收到**的消息数 |
| `frequency_hz` | `request_count / 窗口秒数` |
| `gap_median_ms` | 相邻消息到达间隔中位数 |
| `gap_p95_ms` | 相邻消息到达间隔 95 分位 |
| `gap_max_ms` | 相邻消息到达间隔最大值 |
| `duration_ms` | 窗口时长 |

与训练集 `windows_0.jsonl` 同名同定义；但**采样位置不同**
（训练来自 PCAP 侧统计，本采集器来自 ROS 2 订阅侧），
因此语义等价、数值不保证逐点相同 —— 这一点写进了输出的
`feature_semantics.alignment_note`，避免"字段名相同就推定等价"。

## 2. 准确性验证（有真值可比）

用一个**已知频率**的发布者作为真值，检验测量误差：

```bash
ros2 topic pub --rate 50 /m1_probe/tick std_msgs/msg/String "{data: tick}"
python3 modules/member1_comm/collector/ros2_window.py \
    --topic /m1_probe/tick --type std_msgs/msg/String \
    --duration 6 --interval 1 --out window_50hz.json
```

实测（5 个窗口，共 250 条消息）：

| 窗口 | count | freq_hz | gap_median_ms | gap_p95_ms | duration_ms |
| --- | --- | --- | --- | --- | --- |
| 1 | 47 | 46.08 | 19.89 | 20.48 | 1020.0 |
| 2 | 50 | 50.00 | 20.02 | 20.23 | 1000.0 |
| 3 | 51 | 50.01 | 19.98 | 20.24 | 1019.7 |
| 4 | 51 | 50.82 | 20.00 | 20.24 | 1003.5 |
| 5 | 51 | 50.00 | 19.98 | 20.24 | 1020.1 |

**真值 50 Hz，测量均值 49.38 Hz，误差 1.2%**；间隔中位数 ~20 ms，
与 50 Hz 理论值 20 ms 一致。

> 窗口 1 偏低（46.08）是订阅建立瞬态，属真实观测噪声，**未做修正或丢弃**。

## 3. 失败关闭（重要）

采集器设计上**拒绝在样本不足时给结论**：

```
2 Hz 发布者，interval=2s：
  verdict = INSUFFICIENT_OBSERVATION
  reason  = 所有窗口样本数均 < 8，拒绝据此给出风险结论
```

即"少样本 -> 不编数字"。这与 M1 模块"缺证据失败关闭"的语义一致。

## 4. 在线推理链路（端到端）

```bash
python3 modules/member1_comm/collector/ros2_window.py \
    --topic /m1_probe/tick --type std_msgs/msg/String \
    --duration 8 --interval 1 \
    --model modules/member1_comm/model/comm_risk_window_model.json \
    --out window_scored_50hz.json
```

结果：7 个窗口全部打分，`status=SCORED`，`score_mean=1.0`。

**如何解读这个 1.0（必须谨慎）**：

- 它证明**采集 → 特征 → 纯数值推理**整条链在真实 ROS 2 上跑通，
  且数值与训练侧一致（导出时已校验 2.55e-10）；
- 它**不**证明"检测到了攻击"。50 Hz 合成 ticker 相对训练分布是异常的，
  模型按"分布外"给了高分，这是**输入分布外**的表现，不是攻击识别。
- 因此本专项**不宣称**已在真实 ROS 2 攻击流量上验证检出力。

## 5. 仍未解决的观测缺口

| 缺口 | 现状 | 影响 |
| --- | --- | --- |
| Action 业务请求级计数 | 采集器按**话题消息**计数，尚不能把计数绑定到具体 Action goal 语义 | 无法给出"本请求所属资源在窗口内的业务请求数" |
| 22 维逐包 RTPS 特征 | 未采集（需要抓包侧，订阅侧不可见） | 只能用窗口聚合特征，不能用包级特征 |
| 2 维 ROS 图特征 | 未完成可靠等价映射 | 模型不含节点/端点数量类特征 |
| 真实攻击流量 | 未在隔离域内构造真实 ROS 2 攻击并观测 | 检出力仍未在真实在线数据上验证 |

这些缺口是 `M1_TRUSTED_REQUEST_COUNT_VERIFIED` 判定为 PARTIAL/BLOCKED 的直接原因。
