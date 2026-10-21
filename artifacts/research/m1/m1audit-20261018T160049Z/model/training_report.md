# M1 窗口级模型评估（会话分组）

- 生成时间：2026-10-18T16:03:10Z
- 输入窗口数：22591
- 会话（segment）数：10
- 折数：5（GroupKFold by segment）

## 类别分布

| 标签 | 窗口数 |
| --- | --- |
| observe | 11347 |
| nmap discovery | 10845 |
| ros2 reconnaissance | 399 |

## 候选对比（每折都超过基线才算强）

| 候选 | 平均 F1 | 最差折 F1 | 最好折 F1 |
| --- | --- | --- | --- |
| `logistic` | 0.9946 | 0.9729 | 1.0 |
| `extra_trees` | 0.984 | 0.9319 | 1.0 |
| `random_forest` | 0.8916 | 0.4999 | 1.0 |
| `hist_gb` | 0.7977 | 0.0055 | 1.0 |
| `rule_frequency_99pct` | 0.329 | 0.0 | 0.4623 |

**恒预测攻击基线平均 F1 = 0.6411**

超过基线的候选：['extra_trees', 'hist_gb', 'logistic', 'random_forest']
