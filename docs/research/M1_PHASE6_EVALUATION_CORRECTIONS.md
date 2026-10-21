# M1 第六轮：评估方法缺陷整改（v1 → v2）

> run_id：`m1p6-20261020T123752Z`
> 证据：`artifacts/research/m1-phase6/m1p6-20261020T123752Z/g4_evaluation_v2.json`
> 旧结果 `m1g-20261020T084933Z/g4_model_evaluation.json` **原样保留，不追溯改写**

## 1. 已确认的五项缺陷

| # | 缺陷 | 后果 |
| --- | --- | --- |
| 1 | 正常会话被算 F1 | 正常会话没有正类，F1 恒为 0 |
| 2 | `worst_session_f1` = min over **全部**会话 | "最差会话 = 0" 只说明有个会话是正常的 |
| 3 | 只用单一"最差 F1"门槛 | 无法区分"总体噪声"与"某场景全线误报" |
| 4 | 单类会话未区分指标适用性 | 无负类时 FPR 无定义却仍被计算 |
| 5 | 缺 UNKNOWN/覆盖质量度量 | 数据质量差不影响结论 |

## 2. 修正（v2）

新增 `modules/member1_comm/research/m1_metrics.py`，按会话类别选择指标：

| 会话类别 | 适用 | 不适用（显式 N/A） |
| --- | --- | --- |
| normal | `fpr`、`false_positive_window_rate` | `recall`、`precision`、`f1` |
| anomaly | `recall`、`precision`、`f1` | `fpr` |

并**分开报告**两个不同量：

* `overall_fpr_pooled`：合并所有正常会话的分子分母（不是各会话 FPR 的算术平均）；
* `worst_session_fpr`：单个正常会话里最差的那个。

### 分母检查

每个指标都带分母：

* `overall_fpr_pooled_denominator` = 所有正常窗口数；
* 每类异常的 `tp`/`fn` 分别列出；
* `per_class[c].sessions_detected` / `sessions`。

### 分母为 0 一律 N/A，不写 0

`precision` 在"没有任何正类预测"时是 0/0，返回 `N/A`；
"全漏"的信息由 `recall == 0` 承载，不靠编造 precision。

## 3. 单元测试（16 项，全部通过）

`tests/unit/test_m1_phase6_metrics.py` 用**手工构造的混淆矩阵**验证：

* 正常会话不产出 F1 字段；
* 无正类 → recall/F1 = N/A；无负类 → FPR = N/A；
* 总体 FPR 是合并分子分母，且与各会话平均**确实不同**（构造了 1/102 vs 0.25 的例子）；
* `worst_session_fpr` 与 `overall_fpr_pooled` 分开；
* 每类召回合并分子分母后与"会话检出数"一致；
* 正常会话永不参与"最差会话"的 F1 语义。

## 4. 用 v2 重算旧数据的结果变化

同一份数据、同一模型，仅换指标语义：

| 指标 | v1（错） | v2（对） |
| --- | --- | --- |
| "最差会话 F1" | 0.00（把正常会话算进去） | **不再使用该指标** |
| 正常会话 FPR | 只有 `normal_fpr_worst=1.0` | `overall=0.037`，`worst=1.0`（两者分开） |
| 每类召回 | 混在 `per_class.recall` | 带 `tp/fn/sessions_detected` 分母 |

**注意**：v2 并没有把 v1 的 FAIL 变成 PASS ——
`worst_session_fpr` 仍是 1.0，`anomaly-endpoint-recon` 召回仍是 0.0。
换口径只是让数字**有意义**，不是让结论变好。

## 5. 未做的事

* 未修改任何模型或阈值；
* 未删除 v1 结果；
* 未因换口径而放宽任何门槛（v2 协议见 `M1_PHASE6_BLIND_TEST_PROTOCOL.md`）。
