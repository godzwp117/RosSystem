# M1 第六轮交接说明

> 分支：`research/m1-phase6-evaluation-observation`
> 继承：`4b216c4a04e655a9ac87255b3ef752d9d871c95f`
> run_id：`m1p6-20261020T123752Z`

## 1. 交付

| 文件 | 状态 | 作用 |
| --- | --- | --- |
| `modules/member1_comm/research/m1_metrics.py` | 新增 | 正确的指标语义（按会话类别选指标，分母为 0 返回 N/A） |
| `modules/member1_comm/research/window_aggregator.py` | 修改 | 覆盖质量：`uncovered_sec`/`late_ticks`/`graph_time_coverage_ratio`，覆盖率不足降级；导出 `raw_events` |
| `scripts/m1_graph_collector.py` | 修改 | 导出可独立复算的原始事件时间戳 |
| `scripts/m1_phase6_fusion_diagnosis.py` | 新增 | 融合失败归因（分数、系数、标准化幅度、缺失率） |
| `scripts/m1_phase5_experiments.py` | 修改 | 容器/Domain 可环境变量覆盖（修掉硬编码导致写错工作树的问题） |
| `tests/unit/test_m1_phase6_metrics.py` | 新增 | 16 项手工混淆矩阵测试 |
| `tests/unit/test_m1_time_driven_windows.py` | 修改 | 26 项，新增覆盖质量与故障注入用例 |

**未修改**：`module.py`、`config/team_modules.three-real.yaml`、F0、Gateway、
DDS 权限、M2 签发代码。**未导出模型。**

## 2. 最关键的三个结论

1. **旧评估器的"最差会话 F1"是语义错误**：正常会话没有正类，F1 恒为 0，
   于是"最差 = 0"只说明"有个会话是正常的"。v2 改为分开报告
   `overall_fpr_pooled` 与 `worst_session_fpr`，正常会话**不产出 F1**。
2. **融合失败是"裕度太薄"而非"特征被淹没"**：recon 在 graph-only 下 0.577（检），
   融合后 0.452（漏），裕度仅 0.077；而图特征在联合模型里的贡献（1.36）
   反而大于最强消息特征（0.51）。
3. **图通道零误报且是唯一能发现 churn/recon 的通道**：graph-only 在 27 个正常
   会话上 `overall_fpr = 0.000`，churn 5/5、recon 5/5。

## 3. 给集成的建议

**仍然不要启用 M1 模型。** v2 门槛下：

* `worst_session_fpr = 1.0`（合法 1000 Hz 被全线误报）→ FAIL；
* `anomaly-endpoint-recon` 召回 0.0（融合后）→ FAIL。

### 一个值得评审的中间方案（本轮未启用）

graph-only 通道在现有数据上：正常 FPR **0.000**，churn 5/5，recon 5/5，
但对 flood 完全无感（洪泛不改拓扑）。

如果产品愿意接受"只检测图可观测的异常、对其余返回 UNKNOWN"，
这个通道是**目前唯一在真实数据上零误报的候选**。
但这是产品范围决策，需要单独评审，本轮不擅自启用。

## 4. 精确阻断

| # | 阻断 | 需要什么 | 归属 |
| --- | --- | --- | --- |
| B1 | 合法高负载 vs 洪泛不可区分 | **系统内不存在速率授权基线**（task_policy 与 DDS 权限均无速率定义），需受信任策略提供 | 集成 |
| B2 | recon 融合后漏检 | 更好的图特征（端点增长率）或分通道保守融合 | M1 |
| B3 | 盲测未运行 | 需先有通过验证池门槛的候选模型 | M1 |
| B4 | Action 计数 | M2 未交付 `action_send_goal_received_count` | M2 |

## 5. 复现

```bash
python3 scripts/m1_phase5_experiments.py --out <dir> --group g3 --duration 40   # 基线数据
python3 scripts/m1_phase6_fusion_diagnosis.py --sessions <dir>/g3_sessions --out <dir>/fusion.json
python3 -m pytest tests/unit/test_m1_phase6_metrics.py tests/unit/test_m1_time_driven_windows.py -q
```
