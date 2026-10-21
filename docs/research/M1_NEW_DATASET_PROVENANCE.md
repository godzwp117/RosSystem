# M1 新数据集来源与可复现性

> 分支：`research/m1-trusted-action-retraining`
> 基准：`86a8910bf4560dfe455bec09bc503600c30bf670`
> run_id：`m1retrain-20261020T023546Z`
> 证据：`artifacts/research/m1-trusted-retraining/m1retrain-20261020T023546Z/`

## 1. 数据从哪来

**不来自旧 ROSPaCe 数据集。** 旧数据集的问题（窗口时长编码标签）
已在第三轮证实，本轮**重新采集**，不使用 `windows_0.jsonl` 训练任何模型。

本轮数据由真实 ROS 2 Jazzy 采集产生：

| 项 | 值 |
| --- | --- |
| 容器 | `rg_m1r`（`ros:jazzy`） |
| Domain | **68**（独立，不碰 56/43/64） |
| 采集器 | `scripts/m1_session_collector.py` |
| 编排器 | `scripts/m1_collect_sessions.py` |
| 窗口 | 30 s 固定、不重叠、左闭右开 |
| 会话数 | 9（7 个产出可用窗口，2 个 graph-only 场景无消息窗口） |
| 可用窗口 | 14 |

## 2. 场景清单与实际结果

| 会话 | 场景 | 标签 | 窗口 | 样本 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `norm-002hz` | 正常低频 | normal | 2 | ~60 | 合法 |
| `norm-010hz` | 正常中频 | normal | 2 | ~300 | 合法 |
| `norm-050hz` | 正常高频 | normal | 2 | ~1500 | 合法 |
| `norm-500hz` | 正常极高频 | normal | 2 | ~15000 | **困难负例**：高频但完全合法 |
| `norm-irregular` | 正常抖动 | normal | 2 | 不定 | 间隔 1–60 ms 随机 |
| `norm-restart` | 正常重启 | normal | 2 | 不定 | 发布者 3 次重启 |
| `anom-topic-flood` | 2000 Hz 洪泛 | anomaly | 2 | ~60000 | 定性违规：超出任何授权负载 |
| `anom-discovery-churn` | 反复建销节点 | anomaly | **0** | **0** | **无消息 → 窗口不足** |
| `anom-recon` | 图侦察 | anomaly | **0** | **0** | **无消息 → 窗口不足** |

## 3. 一个必须记录的实验发现

两个 graph-only 异常会话（发现churn、侦察）**没有产生任何可用窗口**：
它们不发布业务消息，而本采集器的窗口以**消息到达**为驱动，
`MIN_SAMPLES=10` 直接把它们判为 `INSUFFICIENT_OBSERVATION`。

**这不是采集失败，而是特征族的表达能力边界**：当前窗口/特征体系
只能看到"消息行为"，看不到"仅有图结构变化"的攻击。
这条必须写进结论，不能因为"数据没采到"就忽略这类攻击的存在。

## 4. 标签如何产生

* 字段：`label`、`label_basis`、`label_source=EXPERIMENT_CONDITION`、
  `model_used_for_labeling=false`；
* 依据是**实验条件**（我让发布者以什么频率/模式运行、是否违反安全策略），
  不是模型输出，也不是回看模型分数贴标签；
* 500 Hz 合法发布者被**明确标为 normal** —— 高频本身不是违规。

## 5. 可复现命令

```bash
# 采集全部会话（容器内自动执行）
python3 scripts/m1_collect_sessions.py --out artifacts/research/m1-trusted-retraining/<run_id>/sessions --duration 65

# 泄漏审计 + 会话级留一评估
python3 scripts/m1_leakage_audit.py \
    --sessions artifacts/research/m1-trusted-retraining/<run_id>/sessions \
    --out artifacts/research/m1-trusted-retraining/<run_id>/leakage_audit.json
```

## 6. 数据规模与存储

本轮数据量很小（9 个会话 / 18 个窗口 / 约 960 KB JSON），
**全部随仓库提交**，没有留在外部存储，也不需要 rosbag2 或 PCAP。
每个会话文件含完整窗口记录，可独立复算。

## 7. 限制

* 全部是**受控实验**数据，不是生产真实流量；
* 会话数远低于做泛化结论所需的规模（见评估报告）；
* 只有 1 个异常会话产出可用窗口 → 无法评估召回；
* 未采集 Action `send_goal`，只有话题消息（见 `M1_TRUSTED_ACTION_FEATURES.md`）。
