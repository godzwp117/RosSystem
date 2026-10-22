# M1 第五轮 G3：数据集来源与治理

> run_id：`m1g-20261020T084933Z`，容器 `rg_m1g`，Domain 69
> 证据：`artifacts/research/m1-graph-dataset/m1g-20261020T084933Z/g3_sessions/`

## 1. 会话构成（实测）

| 类别 | 场景 | 会话数 | 标签依据 |
| --- | --- | --- | --- |
| normal | `normal-rate` 1/2/5/10/20/50/100/200/500/1000 Hz | 10 | 合法发布，频率在授权负载内 |
| normal | `normal-restart` 节点加入后正常退出 | 5 | 重启不是违规 |
| anomaly | `anomaly-flood` 2000 Hz 无界洪泛 | 5 | 超出任何授权负载 |
| anomaly | `anomaly-churn` 持续建销节点 | 5 | 异常发现行为 |
| anomaly | `anomaly-recon` 持续新建端点 | 5 | 未授权端点操作 |
| **合计** | | **30** | |

**正常 15 个，低于协议目标 20 个** —— 这一点如实记录，
`M1_SESSION_SAMPLE_TARGET_MET` 判 **FAIL**，不因为"差 5 个"就四舍五入。
每类异常 5 个，达到目标。

## 2. 标签纪律

* `label_source = EXPERIMENT_CONDITION`，全部 30 个会话一致；
* `model_used_for_labeling = false`；
* `label_basis` 写明实验事实，例如
  `"authorized 1000 Hz publisher, within expected workload"` → normal；
* **1000 Hz 合法发布者被标为 normal** —— 这是本轮最重要的困难负例，
  它的存在直接暴露了模型的缺陷（见评估报告）。

## 3. 采集失败的如实记录

采集过程中容器被宿主重启打断：

| 会话 | 情况 | 处理 |
| --- | --- | --- |
| `g3-anom-recon-s02` | 文件 0 字节（写入中被中断） | 重新采集；旧文件保留为失败记录 |
| `g3-anom-recon-s03` | 未产出 | 补采 |
| `g3-anom-recon-s04` | 未产出 | 补采 |

补采清单单独保存为 `g3_retry_manifest.json`，**未删除任何失败痕迹**。

## 4. 每个会话保留的字段

`session_id`、`scenario`、`label`、`label_basis`、`label_source`、
`started_at`/`ended_at`、`domain_id`、`window_sec`、`graph_poll_interval_sec`、
`windows[]`（含双通道状态与特征）、`summary`、`tick_lateness_samples`、`collector`。

原始观测足以**独立重算**窗口特征：每个窗口带 `samples`、状态与全部特征，
且窗口定义（时间驱动、左闭右开、不重叠）写在契约里。

## 5. 可复现命令

```bash
# G2 机制验证（8 场景）
python3 scripts/m1_phase5_experiments.py --out <dir> --group g2 --duration 40

# G3 数据集（30 会话）
python3 scripts/m1_phase5_experiments.py --out <dir> --group g3 --duration 40

# G4 审计与评估
python3 scripts/m1_phase5_evaluate.py --sessions <dir>/g3_sessions --out <dir>/g4_model_evaluation.json
```

## 6. 限制

* 全部是**受控实验**，不是生产流量；
* 正常 15 个会话未达目标 20；
* 无最终盲测集（会话数不足以同时支撑调参与盲测）；
* 未采集 Action `send_goal`（M2 未提供可信计数）。
