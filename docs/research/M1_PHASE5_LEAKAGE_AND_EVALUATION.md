# M1 第五轮 G4：泄漏审计与独立评估

> run_id：`m1g-20261020T084933Z`
> 证据：`artifacts/research/m1-graph-dataset/m1g-20261020T084933Z/g4_model_evaluation.json`

## 1. 泄漏审计（通过）

| 检查 | 结果 |
| --- | --- |
| 禁用字段是否进入特征 | **否**（`forbidden_features_present = []`） |
| `duration_ms` | 不在特征中；且窗口固定 30 s，本身无信息量 |
| `session_id` / `scenario` / 文件名 / 资源名 | 均未进入特征 |
| `graph_poll_interval_sec` | 记录为元数据，未进入特征 |
| 标签来源 | 全部 `EXPERIMENT_CONDITION`，无模型参与 |
| 重复窗口 | 未发现完全相同特征向量 |
| 划分单位 | `session_id`，留一整个会话 |

## 2. 单特征判别力

| 特征 | AUC | 通道 |
| --- | --- | --- |
| `message_count` | 0.90+ | 消息 |
| `frequency_hz` | 0.90+ | 消息 |
| `gap_max_ms` | 0.16 | 消息（方向相反） |
| `graph_snapshot_transition_count` | 0.78 | 图 |
| 其余 | 接近 0.5 | — |

图特征 AUC 0.78 说明它**确实携带独立信息**（churn 的 45 次变化 vs 稳定的 2–3 次），
但它单独不足以覆盖全部类别。

## 3. 通道消融（留一会话）

| 特征集 | 正常最差 FPR | 异常召回 | 最差会话 F1 |
| --- | --- | --- | --- |
| 仅消息 | 见 JSON | 见 JSON | 见 JSON |
| 仅图 | 见 JSON | 见 JSON | 见 JSON |
| **消息+图** | **1.00** | **0.667** | **0.00** |

（各组合完整数字见 `g4_model_evaluation.json` 的 `ablations` 字段。）

## 4. 逐会话结果（消息+图）

| 会话 | 标签 | Recall | FPR |
| --- | --- | --- | --- |
| `anomaly-flood` ×5 | anomaly | **1.0** | — |
| `anomaly-churn` ×5 | anomaly | **1.0** | — |
| `anomaly-endpoint-recon` ×5 | anomaly | **0.0** | — |
| `normal-rate` 1–500 Hz ×9 | normal | — | **0.0** |
| **`normal-rate` 1000 Hz** | normal | — | **1.0** |
| `normal-restart` ×5 | normal | — | 0.0 |

## 5. 三个必须如实报告的失败

### 5.1 合法 1000 Hz 被全线误报（FPR = 1.0）

唯一误报的会话是**合法 1000 Hz 发布者**。这与第四轮的判断一致：
仅凭速率，合法高负载与 2000 Hz 洪泛**在观测上不可区分**。

判定：`OBSERVATIONALLY_INDISTINGUISHABLE`。
要区分它，需要**授权基线**（这个资源允许多高）或 DDS 权限审计，
而不是更聪明的模型。

### 5.2 端点侦察召回 0.0

`anomaly-endpoint-recon` 每 2 秒新建一个 publisher，30 s 内约 14 次快照变化；
而 churn 是 45 次。模型（在其余会话上训练）把 14 次的变化当作正常范围。

这不是"没观测到"（G2 已证明能观测到 14 次），
而是**变化幅度不足以与该模型学到的正常上限分开**。
要检出它需要更敏感的图特征（如变化率、端点增长率）或更长的观察窗口。

### 5.3 最差会话 F1 = 0.0

由 5.1 直接导致：留出 1000 Hz 正常会话时，该会话全部被误报，
F1 = 0。

## 6. 预登记门槛对照

| 门槛（协议 §6） | 要求 | 实测 | 判定 |
| --- | --- | --- | --- |
| 正常会话 FPR | ≤ 0.10 | **1.00** | **FAIL** |
| 每类异常 Recall | ≥ 0.80 | 1.0 / 1.0 / **0.0** | **FAIL** |
| 最差会话 F1 | ≥ 0.60 | **0.00** | **FAIL** |
| UNKNOWN 占比 | ≤ 0.20 | 未测（无正式模型） | N/A |

**总体：`INSUFFICIENT_EVIDENCE`。**

门槛是在看到数据之前写进协议 v1 的，本轮**没有**事后调整任何一条。
