# M1 有效性验收（专项② 分级结论）

> 代码基准（`RESEARCH_BASE_SHA`）：`be47ccd6c1b19460b65abc0ea8004706383d01d4`
> 本专项分支：`research/m1-online-detection`
> run_id：`m1audit-20261018T160049Z`
> 证据：`artifacts/research/m1/m1audit-20261018T160049Z/`

分级依据只来自本分支上的实际执行，**不引用冻结版本的历史数字**。

---

## `M1_DATA_QUALITY_VERIFIED` = **PASS**

依据：

- 标签列经自动探测确认为第 61 列，取值 7 种（1 正常 + 6 攻击），
  逐分片分布已统计（`data_audit.json`）。
- 发现并量化了根因：**文件级划分等价于类别划分**
  （4 个分片单一类别占比 >94%），这解释了 F1 0.1312 低于平凡基线 0.8567。
- 旧划分已**降级为诊断集**，最终指标改用会话分组交叉验证。
- 特征缺失率、量纲、逐分片漂移均已输出。

限制：`windows_0.jsonl` 的窗口生成脚本不在库内，无法复核其划分算法。

---

## `M1_MODEL_EFFECTIVENESS_VERIFIED` = **PASS**

依据（会话分组交叉验证，5 折，阈值只在训练折选）：

| 项 | 值 |
| --- | --- |
| 采用模型 | logistic，6 维窗口特征 |
| 平均 F1 | **0.9919** |
| 最差折 F1 | **0.9596** |
| 恒预测攻击基线 | 0.6411 |
| 频率 99 分位规则 | 0.3290（最差折 0） |
| 消融（去掉资源名） | 0.9961 / 0.9803 —— 信号来自行为而非命名 |
| 数值一致性 | 训练侧 vs 部署侧最大差 2.55e-10 |

关键点：**模型显著优于平凡基线，且优于同等信息量的简单阈值规则**；
消融证明判别来自频率/间隔行为特征，而非资源名记忆。

限制：数据集只含 3 个标签（正常 + nmap discovery + ros2 reconnaissance），
结论不得推广到未知攻击；段内时间自相关未被完全排除。

---

## `M1_REAL_ROS2_OBSERVATION_VERIFIED` = **PASS**

依据：`modules/member1_comm/collector/ros2_window.py` 在隔离容器
`rg_m1`（Domain **57**）上真实订阅 ROS 2 话题，对已知 50 Hz 发布者测得
**49.38 Hz（误差 1.2%）**、间隔中位数 ~20 ms。

---

## `M1_TRUSTED_REQUEST_COUNT_VERIFIED` = **PARTIAL**

已达到：`request_count` 现在只来自**本进程实际收到的消息**，
不由命令行、信封或适配层自报；样本不足时明确 `INSUFFICIENT_OBSERVATION`。

未达到：计数仍停留在**话题消息级**，尚未绑定到具体 **Action goal** 的业务语义；
"这次导航请求所属资源在窗口内发生了多少次业务请求"仍无法从 ROS 2 侧可信取得。

因此该项不能判 PASS。

---

## `M1_ONLINE_INFERENCE_VERIFIED` = **PASS**

依据：`--model` 参数驱动采集器对真实 ROS 2 流量逐窗口打分，
`status=SCORED`、`windows_scored=7`；打分公式与 `module.py` 的
"signed-log1p + 标准化 + 线性"路径一致，导出时已做 1e-9 容差校验。

限制：**打分跑通 ≠ 检出攻击**。50 Hz 合成流的高分是分布外表现。

---

## `M1_ONLINE_PROCEED_READY` = **FAIL**

理由（两条，任一都足以阻断）：

1. **部署路径未切换**：`modules/member1_comm/model/comm_risk_model.json`
   （49 维，`validation_gate_passed=false`）仍是模块默认装载的模型；
   新窗口模型虽已导出且门槛通过，但尚未成为 `team_modules.three-real.yaml`
   的默认模型，也尚未替换 49 维推理路径。
2. **真实攻击流量未验证**：检出力只在 ROSPaCe 派生窗口数据上评估，
   **没有**在隔离域内构造真实 ROS 2 攻击并观测。按本专项自定标准
   （见任务书 §11 第 5 条），该项不满足。

---

## 汇总

| 分级项 | 判定 |
| --- | --- |
| `M1_DATA_QUALITY_VERIFIED` | **PASS** |
| `M1_MODEL_EFFECTIVENESS_VERIFIED` | **PASS** |
| `M1_REAL_ROS2_OBSERVATION_VERIFIED` | **PASS** |
| `M1_TRUSTED_REQUEST_COUNT_VERIFIED` | **PARTIAL** |
| `M1_ONLINE_INFERENCE_VERIFIED` | **PASS** |
| `M1_ONLINE_PROCEED_READY` | **FAIL** |

注：本专项**不要求**使三真实模块 LEVEL 3 PASS；即使 M1 完成，
M2 的生产身份来源仍为 UNKNOWN，全系统仍会被正确阻断。
