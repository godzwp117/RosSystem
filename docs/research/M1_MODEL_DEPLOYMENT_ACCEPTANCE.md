# M1 模型部署验收与分级结论

> 分支：`research/m1-trusted-action-retraining`
> 基准：`86a8910bf4560dfe455bec09bc503600c30bf670`
> `M1_TESTED_CODE_SHA`：见 `artifacts/research/m1-trusted-retraining/<run_id>/tested_commit.json`
> run_id：`m1retrain-20261020T023546Z`

## 1. 本轮做了什么、没做什么

**做了**：重新建立采集/标签规范；真实 ROS 2 采集 9 个会话；
禁止字段检查；会话级留一评估；诚实的失败记录。

**没做**：没有训练并导出新的正式模型。原因不是时间，而是
**数据条件不成立**（见下），训练只会得到一个不可辩护的产物。

## 2. 为什么不导出新模型

| 条件（任务书 §10） | 现状 |
| --- | --- |
| 1 数据来源可信 | ✅ 受控实验、可复现、标签来自实验条件 |
| 2 窗口契约一致 | ✅ 30 s 固定、采集端与规范一致 |
| 3 特征运行时真实可观测 | ✅ 全部来自订阅侧与图回调 |
| 4 无已知严重标签泄漏 | ✅ 禁用字段全部缺席 |
| 5 独立正常流量误报可接受 | ⚠️ 12 个窗口 0 误报，**样本不足以下结论** |
| 6 独立异常检出达门槛 | ❌ **无法测量**（唯一异常会话无法留出） |
| 7 UNKNOWN 比例可接受 | ⚠️ 未测（无正式模型） |
| 8 推理延迟达标 | ⚠️ 纯数值推理，延迟远低于窗口周期，但未做正式基准 |

条件 6 不成立，且 5 的证据强度不足。**因此不导出新模型、
不修改 `config/team_modules.three-real.yaml`、不启用任何新模型。**

旧的 `comm_risk_window_model.json` 同样**保持不启用**
（第三轮已证明其判别力来自 `duration_ms` 泄漏）。

## 3. 分级结论

| 分级项 | 判定 | 依据 |
| --- | --- | --- |
| `M1_DATA_PROVENANCE_VERIFIED` | **PASS** | 规范 + 采集清单 + 哈希 + 可复现命令 |
| `M1_SESSION_INDEPENDENCE_VERIFIED` | **PASS** | 以 session_id 分组；留一按会话；无跨会话窗口 |
| `M1_LABEL_LEAKAGE_REMOVED` | **PASS** | `forbidden_features_present=[]`；`duration_ms` 已排除且窗口固定 |
| `M1_TRUSTED_ACTION_DATA_SOURCE_READY` | **BLOCKED** | M2 只有候选任务入口，无真实 send_goal 捕获 |
| `M1_DATASET_REPRODUCIBLE` | **PASS** | 一条命令重采；产物随仓库提交；SHA256 可校验 |
| `M1_NORMAL_FPR_VERIFIED` | **FAIL（证据不足）** | 12 个正常窗口、0 误报；置信区间过宽，不构成"已验证" |
| `M1_ATTACK_RECALL_VERIFIED` | **FAIL** | 唯一异常会话无法留出评估；召回不可测 |
| `M1_OOD_UNKNOWN_VERIFIED` | **PARTIAL/BLOCKED** | 不足样本→INSUFFICIENT→UNKNOWN 的机制存在且实测生效；但无正式模型可谈 OOD |
| `M1_ONLINE_INFERENCE_VERIFIED` | **NOT_RUN** | 本轮未部署新模型，因此没有新的在线推理可验 |
| `M1_ONLINE_PROCEED_READY` | **FAIL** | 条件 6 不成立、Action 数据源 BLOCKED、误报证据不足 |

## 4. 必须一起说明的两个技术发现

1. **graph-only 攻击在现有特征族下不可见**：发现churn 与侦察两个异常会话
   不产生业务消息，窗口因此"样本不足"，模型永远看不到它们。
   这是特征族的**表达能力边界**，不是采集 bug。
2. **唯一可测异常使 AUC=1.0 失去意义**：`message_count` 单独 AUC=1.0，
   只是因为 2000 Hz 洪泛与最高 500 Hz 正常之间差一个数量级。
   模型在此数据上只会学到"速率阈值"。

## 5. 下一轮要做什么（供集成负责人排期）

1. 把窗口驱动从"消息到达"扩展为"时间驱动"，使 graph-only 会话也能产出窗口
   （否则异常类别永远缺一半）；
2. 每个攻击类别至少 5 个独立会话，正常至少 20 个会话，覆盖不同负载与时段；
3. 与 M2 对接真实的 `action_send_goal_received_count`（需 typesupport 接线完成）；
4. 只有在 2、3 完成并再次通过泄漏审计后，才谈模型导出与在线准入。
