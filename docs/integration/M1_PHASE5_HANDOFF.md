# M1 第五轮交接说明

> 分支：`research/m1-graph-observation-dataset`
> 继承：`a5e70df63521ee63195187368071f9b2299e3437`
> 共同安全基准：`86a8910bf4560dfe455bec09bc503600c30bf670`

## 1. 本轮交付

| 文件 | 状态 | 作用 |
| --- | --- | --- |
| `modules/member1_comm/research/window_aggregator.py` | 新增 | 纯逻辑的时间驱动双通道窗口聚合器（可注入时钟/快照） |
| `scripts/m1_graph_collector.py` | 新增 | rclpy 接线：真实单调时钟 + 图快照轮询 |
| `scripts/m1_phase5_experiments.py` | 新增 | G2 机制验证 + G3 数据集采集编排 |
| `scripts/m1_phase5_evaluate.py` | 新增 | 双通道泄漏审计与留一会话评估 |
| `tests/unit/test_m1_time_driven_windows.py` | 新增 | 22 项确定性窗口语义测试 |

**未修改**：`modules/member1_comm/module.py`（生产推理路径）、
`config/team_modules.three-real.yaml`、F0、Gateway、DDS 权限、M2 签发代码。

## 2. 给集成的建议

**继续让 M1 返回 UNKNOWN。** 本轮没有可上线的模型，
且已证明当前特征族无法区分合法 1000 Hz 与 2000 Hz 洪泛。

如果需要 M1 提供**有限但可信**的信号，可以考虑：
只对"图 churn"这一类给出 SUSPICIOUS（该类实测召回 1.0、正常场景变化数低一个数量级），
其余一律 UNKNOWN。**但这是新的产品决策，需要单独评审**，
本轮不擅自启用。

## 3. 接口稳定性

`m1-observation-window/2` 是新契约，**不影响**现有
`CommRiskEvidence` 输出 Schema 与 F0 状态语义。
生产推理路径（`module.py`）未改动，旧配置继续可用。

## 4. 复现

```bash
python3 scripts/m1_phase5_experiments.py --out <dir> --group g2 --duration 40
python3 scripts/m1_phase5_experiments.py --out <dir> --group g3 --duration 40
python3 scripts/m1_phase5_evaluate.py --sessions <dir>/g3_sessions --out <dir>/g4_model_evaluation.json
pytest tests/unit/test_m1_time_driven_windows.py -q
```
