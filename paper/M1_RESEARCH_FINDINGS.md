# M1 通信风险研究结论（六小时轮次）

> 证据：`artifacts/research/v110/m1/`、`artifacts/research/m1*/`、`docs/research/M1_*.md`
> 结论：**M1 `VALIDATION_GATE` 继续保持 false；三真正向 LEVEL 3 继续 BLOCKED。**
> 本轮没有为了得到正向而修改模型门槛、阈值或测试断言。

## 1. 直接回答：模型不足、观测不足，还是二者兼有？

**二者兼有，且相互独立：**

1. **模型侧不足**：部署中的 49 维模型 `validation_gate_passed=false`；
   唯一通过门槛的 6 维窗口模型（`comm_risk_window_model.json`）**没有部署**，
   因为它把 `duration_ms` 作为特征，而该特征在训练集中与标签强相关
   （`observe` 均值 29,909 ms；`nmap discovery` 21,957 ms；
   `ros2 reconnaissance` 9,931 ms），高 F1 很大程度上是在读窗口长度。
   第六轮修正指标后，融合模型的 `worst_session_fpr=1.0`，
   `anomaly-endpoint-recon` 召回为 0.0。
2. **观测侧不足**：M1 采集器当前只能提供话题级窗口；
   没有真实 Action `send_goal` 的可信计数；graph-only 异常（churn/侦察）
   不产生业务消息，窗口“样本不足”，模型看不到。
   因此即使模型更好，也缺少与“当前 Action 请求”绑定的可信观测。

## 2. 数据事实（既有证据，本轮未重采集训练集）

| 项 | 值 | 来源 |
| --- | --- | --- |
| ROSPaCe 窗口 | 22,591 | `training_report.json` |
| 标签 | observe 11,347；nmap discovery 10,845；ros2 reconnaissance 399 | 同上 |
| 采集段 | 10 个 segment；GroupKFold by segment | 同上 |
| 类别 | 数据审计发现 6 类攻击，不止二分类 | `M1_DATA_AUDIT.md` |
| 正常真实窗口 | 12 个（9 会话中的正常部分） | `M1_MODEL_DEPLOYMENT_ACCEPTANCE.md` |
| 异常真实会话 | 1 个（无法留出评估） | 同上 |
| 真实正常误报回归 | 2/10/50/100 Hz 各 1 窗口，0 误报；500 Hz 风暴未检出 | `M1_REAL_NORMAL_FALSE_POSITIVE.md` |
| 第六轮融合指标 | pooled FPR 0.037；worst session FPR 1.0；endpoint-recon recall 0.0 | `g4_evaluation_v2.json` |

> 12 个正常窗口、0 误报的 Wilson 95% 置信区间下界仍然很低，不能写成
> “误报率已验证”。1 个异常会话不能提供可测召回。数据量不足是本轮不训练新模型的
> 直接原因，而不是时间不够。

## 3. 本轮新增的可信观测证据（真实 DDS）

从 M2 真实链的账本 `v110m2lab-20261021T184500Z/intent_events.jsonl` 聚合：

| 项 | 值 |
| --- | --- |
| resource | `rt/m2/candidate_task`（**意图主题**，不是 Action send_goal） |
| 窗口 | `17:33:34Z–17:33:54Z`，safety lag 2 s |
| send_goal_count | **2** |
| coverage | **COMPLETE** |
| authenticated_senders | `/CN=\/planner`、`/CN=\/operator` |
| unauthenticated_requests | 0 |
| 缺失账本对照 | `count=null`、`coverage=UNKNOWN`（不是 0） |

证据：`artifacts/research/v110/m1/trusted_window_from_m2.json` 与
`trusted_window_missing.json`。

这证明“可信观测链在意图主题上已经可用”，但**不能**证明 Action `send_goal`
级计数；后者仍是 M1 的观测缺口。

## 4. 为什么不能把候选窗口模型直接启用

- 训练与评估的窗口时长分布与标签强相关，`duration_ms` 是伪相关来源；
- 真实高负载误报只有每场景 1 个窗口，样本量不足；
- 没有独立的真实攻击复核样本（训练内攻击类别）；
- graph-only 异常在消息特征族下不可见；
- 预登记门槛要求“独立异常检出”和“可接受 UNKNOWN 比例”，两者都未满足。

因此 `paper` 与工程都不得把 6 维模型的 0.9919 F1 写成“生产 IDS 已通过”。

## 5. 解阻条件（下一轮，不是本轮声明）

1. ≥20 个独立正常会话（含不同负载/时段），≥5 个/攻击类别的独立会话；
2. 去掉 `duration_ms` 或证明其在部署分布中不携带标签信息；
3. 接入真实 Action `send_goal` 计数（需 typesupport/受信任入口）；
4. 预先登记阈值与指标，冻结测试集后再评估；
5. 通过后仍需保持 `validation_gate_passed` 可审计、可回滚。

在这些条件满足前，M1 只能输出 `UNKNOWN`，三真实 LEVEL 3 保持 `BLOCKED`。
