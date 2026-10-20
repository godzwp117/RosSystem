# 成员一技术审查：通信行为可信分析（`comm_risk`）

- 审查对象：`deliveries/member1-comm/`（53 个文件：15 个模块源码/配置 + 35 个运行证据 + 补丁与 CI）
- 来源快照：`chore/member-deliveries` = `3ce820258c69b89e2ad9291e16c44dc7d2b99150`
- 成员自述来源：`REVISION.txt` → `baseline_sha=a4c597161d254192b662ee7b8f4d17f76a89cc16`，`branch=feature/member1-comm-offline-baseline`，`head_sha=21f528085ebe6d6a9df9e15c6c82c6465c80c84a`
- 核心文件 SHA-256：
  - `modules/my_comm/module.py` = `f2513ccace14d6b01ff965e70c8ff40cc6d9c6ee54270ab5892a1564114d2a3a`
  - `modules/my_comm/train.py` = `01b4e3d3af07b0588fcde85230ba080f842f2958c141af493c32524a3ed02af2`
  - `modules/my_comm/data.py` = `86724dfaeacc0d14459268350126fb12cb98b46dcdd6a50b70e4e18c46347897`
  - `modules/my_comm/metrics.py` = `91a528d3594710874b5f5d3c6d466ec26c96ec88f40ea342f52a58d26b10bbbd`
  - `modules/my_comm/features.json` = `55907932184efebb3df15f8aae05d5409060ee5e2026720d6986d66d2de0da23`
- **本轮实际执行**：36 项单测复测；**两份数据集的离线训练与评估完整独立重跑**；报告 JSON 逐字段核对

---

## 1. 结论摘要

| 项 | 结论 | 证据等级 |
| --- | --- | --- |
| 实际算法 | `member1-numeric-v1`：**离线监督二分类**。候选 LogisticRegression 与 ExtraTreesClassifier，由**验证集**选择算法与阈值 | E1_CODE + **A（本轮复现）** |
| 监督/无监督/规则 | **监督学习**（标签仅用于训练与评价，推理不接触标签） | E1_CODE + E2_STATIC |
| 模型输入 | 49 维数值特征向量（`feature_names` 严格顺序匹配） | E1_CODE |
| 数据集 | ROSPaCe_reduced（30,247,050 行 / 15 分片）、ROSPaCe_reduced_noperiodicity（20,851,051 行 / 10 分片），**官方归档 MD5 校验通过** | **A（本轮复现）** |
| 划分 | `FILE_DISJOINT_SPLIT`：按分片序号切分（train 前段 / validation 次末 2 / test 末 2）；`SESSION_INDEPENDENCE: UNVERIFIED` | E1_CODE |
| 标签泄漏 | **未发现**。特征名黑名单 + 推理期二次校验；采样与标签无关 | E2_STATIC |
| 模型产物 | **未交付**（`training_runs/member1/model.json` 不存在） | A（实测缺失） |
| 性能门 | **FAIL**（两数据集均 FAIL） | **A（本轮复现）** |
| 在线采集 | **未实现**。`RUNTIME_MONITOR=NOT_READY` | E1_CODE |
| 输出 `CommRiskEvidence` | 合法，Schema 校验通过 | E4_INTEGRATION_TEST |
| 能否触发 F0 阻断 | **能**。`SUSPICIOUS` → 适配层 `ADAPTER_BLOCK` | E4_INTEGRATION_TEST（历史证据 + 本轮代码核对） |

**一句话**：这是一个**工程诚实度极高、可完全复现**的离线通信异常检测**研究原型**；但其**检测性能未达门限**——F1 在两个数据集上都**低于"全部判为攻击"的平凡基线**，且**测试集只覆盖 6 类攻击中的 1 类**。成员一自己在 `REVISION.txt` 中已如实标注 `model_performance_gate=FAIL`、`L3_effective_detector=NOT_READY`、`RUNTIME_MONITOR=NOT_READY`。

---

## 2. 算法与实现

### 2.1 训练流程（`train.py`）

1. **读取官方 tar 归档**并校验 MD5/大小（`data.py:63-71`，`OFFICIAL_ARCHIVES` 常量）；
2. **逐行审计 + 均匀蓄水池抽样**：每个分片扫全量行，抽样决策**不使用标签或特征值**（`data.py:33-53`）；
3. **预处理仅在训练集拟合**（`train.py:21-29`）：
   - 全缺失列直接报错；
   - `impute = nanmedian(train)`（训练集中位数）；
   - 变换 `sign(x)·log1p(|x|)`；
   - `StandardScaler` 拟合；
4. **候选模型**（`train.py:80-81`）：
   - `LogisticRegression(class_weight='balanced', C=0.1, max_iter=1000, random_state=42)`
   - `ExtraTreesClassifier(n_estimators=48, max_depth=12, min_samples_leaf=10, class_weight='balanced', n_jobs=2, random_state=42)`
5. **阈值网格** `{0.1, 0.25, 0.5, 0.75, 0.9}`，按验证集 `(balanced_accuracy, f1)` 选择算法与阈值；**测试集只在选择完成后评估一次**（`train.py:87-95,106`）；
6. **性能门**（`train.py:97-99`）：
   ```python
   gate = (validation['f1'] > attack_baseline['f1']      # 必须优于恒预测攻击
           and validation['balanced_accuracy'] > 0.5
           and validation['recall'] >= 0.5
           and validation['specificity'] >= 0.5)
   ```
7. **部署一致性断言**（`train.py:108-116`）：在**留出测试集**上断言纯 Python 推理与 sklearn 预测一致（`max|Δp| ≤ 1e-6` 且分类零不一致），否则报错。

**选型结果**：两份数据集均为 `extra_trees`，阈值 **0.75**。

### 2.2 推理与安全设计（`module.py`）

| 机制 | 位置 | 说明 |
| --- | --- | --- |
| **不使用 pickle/joblib** | `module.py:64` | 模型是**纯 JSON 数值表**（`format=member1-numeric-v1`），由 `strict_json` 解析（拒绝重复键与非有限数）。**彻底规避不可信模型反序列化** |
| **模型路径受限** | `module.py:56-57` | 必须位于仓库 `training_runs/` 下 |
| **大小上限** | `module.py:19,58` | 32 MiB |
| **SHA-256 强制校验** | `module.py:61-63` | `--model-sha256` 缺失或不匹配即拒绝 |
| **标签/时间/分组泄漏黑名单** | `module.py:20,68-69,118-119` | `{attack, label, target, timestamp, session_id, group_id}`；**加载与推理两处**拦截 |
| **形状校验** | `module.py:73-108` | 预处理数组长度、scale>0、阈值范围、树结构（子索引、特征索引、叶概率）全部校验 |
| **特征顺序强约束** | `module.py:113-117` | `feature_names` 必须逐项相同，否则 `FEATURE_NAMES_ABSENT_OR_ORDER_MISMATCH` |
| **显式缺失语义** | `module.py:120-122` | `null` = 数据集缺失，用**训练集中位数**填补；**缺失特征名直接拒绝** |
| **观测时效性** | `module.py:167,171-172` | 观测时间与信封 `created_at` 相差 >300 s 或为未来 → `UNKNOWN` |
| **窗口一致性** | `module.py:151-155` | 窗口起止与 `duration_ms` 必须自洽（±1 ms），观测必须落在窗口内 |
| **资源一致性** | `module.py:148-149` | `communication.resource` 必须等于观测 `source` |

### 2.3 失败关闭行为（值得肯定）

`module.py:186-198` 对 `NORMAL` 施加了**双重前置条件**：

```python
elif model['validation_gate_passed'] and obs['kind'] in {'RUNTIME_LOG','CONTROLLED_SECURITY_EXPERIMENT'}:
    state = 'NORMAL'
elif context.get('controlled_test'):
    state = 'NORMAL'          # 受信任测试配置专用
else:
    reason = 'MODEL_NOT_ACCEPTED_OR_UNTRUSTED_OBSERVATION: normal prediction withheld'
    # 状态保持 UNKNOWN
```

即：**未通过验证门的模型不得输出 `NORMAL`**，未通过验证门且无 `--controlled-test` 时**保持 `UNKNOWN`**。这一设计直接把「性能门 FAIL」转化为运行时的**不推进**，与团队安全原则一致。

返回码约定：输入非法 **2**、模型缺失 **3**、其他内部错误 **4**；`UNKNOWN`/`ERROR` 均为不推进。

---

## 3. 特征与数据

### 3.1 特征（49 维，`features.json`）

三类来源混合：

| 类别 | 示例 | 数量级 |
| --- | --- | --- |
| `tshark` 协议层字段 | `layers.sll.sll.pkttype`、`layers.ip.ip.flags_tree.ip.flags.df`、`layers.tcp.tcp.flags_tree.tcp.flags.syn`、`layers.ssl.ssl.record.ssl.record.content_type`、`layers.ipv6.ipv6.tclass_tree.ipv6.tclass.ecn` 等 | 22 |
| 主机资源计数器（`/proc` 风格） | `Net_Sent`、`Net_Received`、`pgpgin`、`pgfault`、`MemFree`、`Cached`、`pgmajfault`、`SwapFree`、`Tcp_Syn`、`Tcp_Established` 等 | 25 |
| ROS 图计数 | `subscribers_count`、`publishers_count` | 2 |

**注意**：`features.json` 注释声明该清单源自 `feature/rospace-dataset-adapter` 的可行性列表，且实际归档头在 `prepare()` 中被逐个校验（`data.py:110-111`）。**本轮核实其自述属实**——49 个特征名在数据集中均存在（否则 `prepare` 会报错，而本轮重跑成功）。

### 3.2 数据与划分

| | `reduced` | `noperiodicity` |
| --- | --- | --- |
| 归档 | `ROSPaCe_reduced.tar.gz` | `ROSPaCe_reduced_noperiodicity.tar.gz` |
| 官方大小 / MD5 | 920,868,855 / `63d2723577250282361b4c073b4912e5` | 697,155,970 / `493995c64efe23e33047f6d820c61979` |
| 审计总行数 | **30,247,050** | **20,851,051** |
| 分片数 | 15 | 10 |
| 抽样 | 10,000 行/分片（均匀蓄水池） | 同 |
| 划分 | train 0–10 / val 11–12 / **test 13–14** | train 0–5 / val 6–7 / **test 8–9** |
| `SESSION_INDEPENDENCE` | `UNVERIFIED` | `UNVERIFIED` |

`data.py:23-30` 处理了官方归档中 `rospace_reduced_11.csv `（**带尾随空格**）的已知异常，保留原名于证据、仅在识别时归一化——细节考究。

### 3.3 标签泄漏核查（任务书问题 8）

**未发现训练/测试泄漏**，理由：

1. 特征名黑名单在**加载模型**与**推理**两处拦截 `attack`/`label`/`timestamp`/`session_id`/`group_id`；
2. 采样为**与标签无关**的均匀蓄水池；
3. 预处理（中位数与标准化）**只在训练集拟合**，`fit_preprocess` 的注释与调用点均如此；
4. 阈值选择只用验证集，测试集仅评估一次；
5. `prepare()` 显式拒绝把 `attack`/`timestamp` 作为特征（`data.py:60`）。

**但存在另一类问题（非泄漏，属评估偏置）**：见 §4.3 的测试集类别覆盖。

---

## 4. 实验指标（本轮逐字段核对 + 独立重跑）

### 4.1 交付报告记录的指标

| 指标 | `reduced` | `noperiodicity` |
| --- | --- | --- |
| 混淆矩阵 | tp 962 / tn 6297 / **fp 0** / fn 12741 | tp 7184 / tn 4543 / **fp 0** / fn 8273 |
| Precision | 1.0 | 1.0 |
| **Recall** | **0.0702** | **0.4648** |
| Specificity / FPR | 1.0 / 0.0 | 1.0 / 0.0 |
| **F1** | **0.1312** | **0.6346** |
| **Balanced Accuracy** | **0.5351** | **0.7324** |
| PR-AUC（average precision） | 0.7442 | 0.9234 |
| `validation_gate_passed` | **False** | **False** |
| `detector_effectiveness` | `NOT_PROVEN` | `NOT_PROVEN` |

### 4.2 与平凡基线的比较（关键）

`train.py:144` 强制报告两个平凡基线，本轮核对：

| | `reduced` | `noperiodicity` |
| --- | --- | --- |
| 模型 F1 | 0.1312 | 0.6346 |
| **恒预测攻击 F1** | **0.8132** | **0.8719** |
| **差值** | **−0.682** | **−0.237** |
| 恒预测正常 F1 | 0.0 | 0.0 |

**结论：两个数据集上，模型的 F1 都显著低于「全部判为攻击」。** 仅在 Balanced Accuracy 上优于随机（0.5351 / 0.7324）。**任何只引用 F1=0.6346 的表述都会产生误导。**

需要说明的是：这是一个**类别极不平衡**的问题（测试集攻击占比 68.5% / 77.3%），F1 本身受先验影响大；模型选择了极保守的工作点（阈值 0.75，FPR=0）导致召回极低。**在本轮证据范围内，不能推断其根本原因**（可能是特征可分性不足、划分偏置或模型容量问题），需要额外实验才能归因。

### 4.3 测试集类别覆盖（最严重的评估设计问题）

| 攻击类别 | `reduced` 测试集 | `noperiodicity` 测试集 |
| --- | --- | --- |
| `metasploit SYN flood` | 13,703 | 15,457 |
| `nmap SYN flood` | **0 → NOT_EVALUATED** | **0 → NOT_EVALUATED** |
| `nmap discovery` | **0 → NOT_EVALUATED** | **0 → NOT_EVALUATED** |
| `ros2 reconnaissance` | **0 → NOT_EVALUATED** | **0 → NOT_EVALUATED** |
| `ros2 node crashing` | **0 → NOT_EVALUATED** | **0 → NOT_EVALUATED** |
| `ros2 reflection` | **0 → NOT_EVALUATED** | **0 → NOT_EVALUATED** |

`macro_attack_detection_recall` 因此**只等于单一类别的召回**（0.0702 / 0.4648），**不具备"宏平均"的语义**——尽管 `metrics.py:34-37` 的实现本身是正确的（对无样本类别返回 `None` 并不计入）。

**根因**：`train.py:63-66` 取 `files[-test_shards:]`，即**按分片序号取末两片**。而 ROSPaCe 的分片按采集会话组织，末两片恰好只含 `metasploit SYN flood`。这不是数据泄漏，而是**划分策略导致的测试覆盖偏置**。

**因此任务书所要求的"每攻击类别检测效果"在现有交付中只能对 1/6 类给出答案。**

### 4.4 独立复现结果（本轮新增，证据等级 A）

本轮在独立 worktree 中用 `train.py` 从官方归档重跑完整流程（含 MD5 校验、逐行审计、抽样、训练、阈值选择、留出评估）：

| 指标 | 交付报告 | **本轮重跑** | 一致性 |
| --- | --- | --- | --- |
| `reduced` 混淆矩阵 | 962/6297/0/12741 | **962/6297/0/12741** | ✅ 完全一致 |
| `reduced` F1 | 0.13119672690078418 | **0.13119672690078418** | ✅ **逐位一致** |
| `reduced` Recall | 0.07020360504998906 | **0.07020360504998906** | ✅ 逐位一致 |
| `reduced` BalancedAcc | 0.5351018025249945 | **0.5351018025249945** | ✅ 逐位一致 |
| `reduced` PR-AUC | 0.7442155754267716 | 0.7424323285204703 | ⚠️ 差 0.0018 |
| `noperiodicity` 混淆矩阵 | 7184/4543/0/8273 | **7184/4543/0/8273** | ✅ 完全一致 |
| `noperiodicity` F1 | 0.6346009451879334 | **0.6346009451879334** | ✅ **逐位一致** |
| `noperiodicity` Recall | 0.4647732418968752 | **0.4647732418968752** | ✅ 逐位一致 |
| `noperiodicity` BalancedAcc | 0.7323866209484375 | **0.7323866209484375** | ✅ 逐位一致 |
| `noperiodicity` PR-AUC | 0.9234355456012058 | 0.9229604601185579 | ⚠️ 差 0.0005 |
| 各分片 `full=` 行数与标签分布 | 见 `*.training.log` | **逐个分片完全一致** | ✅ |
| 选定算法 / 阈值 | extra_trees / 0.75 | **extra_trees / 0.75** | ✅ |
| `validation_gate` | FAIL | **FAIL** | ✅ |

**唯一差异是 PR-AUC（千分位量级）**，且混淆矩阵与 F1 逐位一致，说明**样本集合完全相同**；差异来自 `sklearn.metrics.average_precision_score` 的版本实现细节（交付侧环境 vs 本轮 `scikit-learn` 版本）。这不影响任何结论。

**这是本次审查中证据强度最高的成果：成员一的离线实验具备完整的可复现性。**

---

## 5. 离线与在线能力判定（任务书 5.4）

| 能力 | 状态 | 依据 |
| --- | --- | --- |
| `OFFLINE_TRAINING` | ✅ **已实现且已复现** | 本轮重跑成功 |
| `OFFLINE_INFERENCE` | ✅ **已实现** | 纯 Python 数值推理 + 与 sklearn 的留出集一致性断言（PASS） |
| `CONTROLLED_REPLAY` | ✅ **已实现** | `local_evidence/` 四状态受控输入输出 |
| `ONLINE_FEATURE_COLLECTION` | ❌ **未实现** | 源码中无 `rclpy` 订阅、无 ROS 图采集；`RUNTIME_MONITOR=NOT_READY` |
| `ONLINE_INFERENCE` | ❌ **未实现** | 无在线输入链路 |
| `REALTIME_RUNTIME_MONITORING` | ❌ **未实现** | `RUNTIME_MONITOR=NOT_READY`（代码中三处显式声明） |

### 5.1 对"ROS 受控协议联调 PASS"的正确解读

`artifacts/member1/ros_controlled_protocol/report.json` 记录 `live_ros_protocol: PASS`，四个场景（normal/suspicious/unknown/error）预期与实际一致，`goal_delta` 分别为 1/0/0/0。**但同一文件明确写着**：

```json
"model": "CONTROLLED_NUMERIC_FIXTURE_NOT_TRAINED_MODEL",
"source_kind": "MOCK",
"real_detector_online": "NOT_READY",
"scope": "Module + adapter + actual secure Gateway/NavigationSim protocol; no IDS effectiveness claim"
```

**因此该实验证明的是"模块↔适配层↔Gateway↔NavigationSim 的协议链路可用"，不是"检测器在线可用"。** 不得表述为在线异常检测成功。

### 5.2 `SECURITY_MODE` 与域

该实验在 `security_mode: Enforce`、`domain: 51` 下运行；`no_leftover_nodes: true`。域 51 与团队约定的成员一开发域一致（成员二证据用域 43）。

---

## 6. 与 F0 适配层的接口符合性

| 检查 | 结果 |
| --- | --- |
| 输出 `CommRiskEvidence` Schema | 通过（受控四状态的 `schema: PASS`） |
| `run_id` / `request_id` 一致 | 通过 |
| 非法 JSON → 失败关闭 | 通过（rc=2） |
| 模型缺失 → 失败关闭 | 通过（rc=3，`MODEL_ABSENT`） |
| `SUSPICIOUS` 触发适配层阻断 | 通过（`ADAPTER_BLOCK` / `ADAPTER_MODULE_STATUS_NOT_PROCEED`） |
| `UNKNOWN` / `ERROR` 不推进 | 通过 |
| `producer.source = EXTERNAL` | 是，但**不构成算法有效性的证明**（与其代码中的 `RUNTIME_MONITOR: NOT_READY` 自述一致） |

`artifacts/member1/local_evidence/report.json` 如实记录了基线验收器 `baseline_L1_checker: FAIL`，原因是 *"baseline fixtures supply no real features/runtime metadata; module refuses invented mapping"* ——这与本报告在 `INTEGRATION_READINESS.md` §5 中独立发现的**验收脚本 `f0_mock` 不兼容**是同一根因，成员一的处理是**正确且诚实**的（宁可不通过，也不伪造映射）。

---

## 7. 安全审查

### 7.1 优点（E2_STATIC）

- 无命令注入面：无 `shell=True`、无 `eval`、无动态 `exec`；
- 无可信反序列化风险：模型为纯 JSON，且强制哈希校验；
- 文件访问受限：模型路径必须在 `training_runs/` 内、大小上限、符号链接未复检但路径受限；
- 输入有界：`MAX_INPUT = 1 MiB`（`module.py:18,232-234`）；
- 数值健壮：`number()` 拒绝 bool、拒绝非有限（`module.py:42-45`）；logistic 的 `z` 被裁剪到 ±700 防溢出；
- 时间严格：复用基线的 `check_rfc3339`；
- 输出自校验后才写 stdout。

### 7.2 缺陷

| 级别 | 问题 | 位置 | 触发条件 | 影响 | 修复建议 |
| --- | --- | --- | --- | --- | --- |
| **P2** | `--controlled-test` 开关可让 `validation_gate_passed=False` 的模型输出 `NORMAL` | `modules/my_comm/module.py:194-196,229` | 受信任配置中加入该参数 | 未过性能门的模型进入"允许"状态 | 该开关目前无强制约束机制；建议在输出中保留 `controlled_test=true` 标记（**已有**），并在集成时禁止生产配置启用 |
| **P3** | 训练日志暴露作者个人路径 | `artifacts/member1/offline_experiments/*.training.log`（`C:\Users\YOGA\...`） | — | 轻微信息暴露 | 归档前脱敏 |
| **P3** | 模型未复检符号链接 | `module.py:55-56` | 本地 `training_runs/` 被植入符号链接 | 需配合路径限制才可利用，风险低 | 增加 `is_symlink()` 拒绝 |

**未发现 P0。** 无绕过 Gateway、无直接操作下游执行接口、无 `UNKNOWN`/`ERROR` 被当作允许。

---

## 8. 证据等级评定

| 结论 | 等级 |
| --- | --- |
| 算法为离线监督学习、模型为纯 JSON 数值表、无 pickle | **A** |
| 49 维特征在数据集中真实存在 | **A**（本轮重跑未报缺失） |
| `reduced` / `noperiodicity` 全部指标与混淆矩阵 | **A（本轮独立复现，逐位一致）** |
| 测试集只覆盖 1/6 攻击类别 | **A** |
| 模型 F1 低于恒预测基线 | **A** |
| 模型产物未交付 | **A**（实测缺失） |
| ROS 受控协议联调 PASS（用受控 fixture） | **B** |
| 在线检测 / 实时监测 | **N** |

---

## 9. 最终评价

**真实成果**：
1. 一条**完整、可复现、无标签泄漏**的离线监督学习流水线（数据审计 → 抽样 → 训练 → 验证选型 → 留出评估 → 部署一致性断言）；
2. 一套**明显高于同类研究代码的工程安全设计**：纯 JSON 模型 + SHA-256、路径/大小限制、特征名黑名单、严格的信封与窗口一致性校验；
3. **强制报告恒预测基线**，以及"未过验证门不得输出 NORMAL"的运行时纪律。

**核心局限（必须在所有材料中如实呈现）**：
1. **性能门 FAIL**：两个数据集 F1 均低于平凡基线；召回 7.0% / 46.5%；
2. **测试覆盖偏置**：测试集只含 1 类攻击，5/6 类无法评估；
3. **无在线能力**：无特征采集链路，`RUNTIME_MONITOR=NOT_READY`；
4. **模型未交付**：无法端到端运行真实算法。

**集成建议**：**不建议**把 `comm_risk` 作为真实检测模块集成（性能未达门限，且模型缺失）。**建议**：
- 立即可沉淀其**工程机制**（JSON 模型 + 哈希、泄漏黑名单、部署一致性断言、平凡基线对照）为团队公共资产；
- 若要作为演示模块，必须以 `--controlled-test` + `controlled_test=true` 标记、并**明确标注为受控演示**，禁止设为默认安全模块；
- 修复测试划分（分层抽样，保证 6 类攻击均进入测试集）后再评估是否具备研究价值。

**验收门槛**：`MEMBER1_CODE_AUDIT` = **PASS**；`MEMBER1_ALGORITHM_EVIDENCE` = **FAIL**（研究流程真实且可复现，但**检测能力未获证明**）。
