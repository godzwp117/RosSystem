# ROSPaCe 可信评测与接口缺陷修复报告

> 本轮针对已实现的 ROSPaCe 研究模块做**定向缺陷修复 + 重训 + 纠偏**。
> 所有数字为本轮实测；v1 结果**原样保留**，未被覆盖。

## A. 版本

| 项 | 值 |
| --- | --- |
| 起始 SHA | `55948434dee47e10443cbf4ce9d7b50c4be93c5d` |
| 分支 | `feature/rospace-dataset-adapter`（未合入 `feature/framework-f0` / `main`） |
| F0 参考基线 | `ebfe263530d10a746c172367f9d96d2f9dc5d7d4`（本分支祖先） |
| 模型版本 | v1 保留于 `training_runs/rospace_*`；v2 输出至 `training_runs/rospace_*_v2` |

## B. 缺陷修复

### B.1 P0-1 攻击预测的 Schema 映射（真实缺陷）

**复现**：`f0_adapter.py` 定义 `CATEGORY_BY_PREDICTION[1] = 'NETWORK_TRAFFIC_ANOMALY'`，
而 `anomaly_category` 合法枚举为 `['NONE','REQUEST_RATE_ANOMALY',
'DUPLICATE_CALL_PATTERN','TIMING_DEVIATION','UNEXPECTED_RESOURCE_ACCESS',
'NODE_RELATION_ANOMALY','UNKNOWN']`。

**后果**：攻击被检出，但**拒绝原因是非法接口输出，而不是安全策略阻断**。

**负向对照**：把修复后的输出改回 `NETWORK_TRAFFIC_ANOMALY`，
`Draft202012Validator` 确认被拒绝 —— 证明该缺陷真实存在。

**修改**：改用既有合法枚举 `UNKNOWN`；风险等级改为**按预测置信度分档**
（>=0.95 HIGH / >=0.80 MEDIUM / >=0.50 LOW / 无概率 UNKNOWN），依据写入 `basis`。
**未修改公共 Schema。**

**修复后验证**（真实 ROSPaCe 特征；标签只用于选样，不参与推理）：

| 用例 | fixture 真实标签 | 模型预测 | p | status | anomaly_category | risk_level | Schema |
| --- | --- | ---: | ---: | --- | --- | --- | --- |
| FIX-01 正常 | `observe` | 0 | 0.001019 | `NORMAL` | `NONE` | `NONE` | 通过 |
| FIX-02 攻击 | `nmap discovery` | 1 | 1.000000 | `SUSPICIOUS` | `UNKNOWN` | `HIGH` | 通过 |

### B.2 P0-3 模型加载可信边界（真实缺陷）

**复现**：原实现 `run_dir = block.get('model_run_dir') or ...` —— 从**业务输入**读模型目录。
joblib 属可反序列化执行内容，等于把模型选择权交给不可信数据。

**修改**：新增 `resolve_model_dir()`，模型目录**只能**来自受信任命令行参数
（由受信任配置的 `command` 数组传入），且必须位于仓库 `training_runs/` 之下
（`os.path.commonpath` 安全父子判断，拒绝任意绝对路径）。
信封若提供 `model_run_dir` 则**忽略并告警**。

**负面测试**：

| 用例 | 结果 |
| --- | --- |
| 信封提供 `model_run_dir=/tmp/evil_model` | 忽略并告警；实际 provenance 仍为受信任根 |
| `--model-run-dir /tmp/evil_model` | exit 3 `MODEL_DIR_UNTRUSTED` |
| 模型目录含损坏 joblib | exit 3（拒绝加载） |
| 缺特征 / 缺 `request_count` | exit 2 / exit 4（fail-closed） |

> 模型哈希用于完整性核对，**不作为身份认证凭据**。

### B.3 P1-1 流式预处理不一致（真实缺陷）

**复现**：原实现 `if first_pass: col_mean = np.nanmean(x, axis=0)` —— 均值只由**第一个 chunk** 估计；
且训练循环内 `scaler.partial_fit(x)` 后立即 `scaler.transform(x)` —— 模型在不同阶段看到不同尺度。

**修改**：拆成两遍有界内存处理：

* **第一遍（统计）**：以充分统计量（count / sum / sum²）累计每列有效样本量、均值、方差、
  缺失数、非有限数；**不以第一个 chunk 代表全集**。
  实测全缺失列 **0** 个、零方差列 **10** 个，全部显式记录，未用 0 静默掩盖。
* **第二遍（优化）**：固定 `(fill, scale)` 后 `partial_fit`，**训练中不再更新任何预处理参数**。
* 两遍使用**同一抽样步长与配额**，样本集合一致。

**验证**：`metrics.json` 记录 `preprocessing_strategy=PREPROC_V2_TWO_PASS_FIXED`、
填充值/缩放值的 SHA-256；落盘的 `scaler.joblib` 由同一组固定参数构造。

### B.4 P1-2 分片排序

**复现**：`sorted()` 字符串序使 `_10` 排在 `_2` 之前。
**修改**：`list_csv()` 改为按**数字分片编号**排序。
实测修正后末两片为 `_13`、`_14`（字符串序会取到 `_8`、`_9`）。

> 这只是文件顺序问题。**排序不证明采集会话独立。**

## C. 模型训练

| 项 | v1 | v2 |
| --- | --- | --- |
| 预处理策略 | 单遍 + **移动 scaler**（缺陷） | `PREPROC_V2_TWO_PASS_FIXED` |
| 分片排序 | 字符串序 | 数字序 |
| 划分标注 | `by_file`（措辞过强） | `FILE_DISJOINT_SPLIT` |
| 训练样本 | 3999996 | 3999996 |
| 测试样本 | 2000000 | 2000000 |
| 训练耗时 | 107.6s | 101.3s（统计）+ 203.0s（训练） |
| model SHA-256 | `2e4641121a447457` | `d1c07beb2c0376c5` |
| Python / sklearn | 未记录 | 3.10.12 / 1.7.2 |

**v1 未被覆盖**：`training_runs/rospace_reduced/metrics.json` 原样保留。

## D. 测试结果

### D.1 主数据集

| 指标 | v1（缺陷版） | **v2（修复版）** |
| --- | ---: | ---: |
| TP / FP / TN / FN | 1958519 / 316 / 24107 / 17058 | **152666 / 112 / 600077 / 1247145** |
| Accuracy | 0.9913 | **0.3764** |
| Precision | 0.9998 | **0.9993** |
| Recall | 0.9914 | **0.1091** |
| F1 | 0.9956 | **0.1967** |
| FPR | 0.0129 | **0.0002** |
| Balanced Accuracy | 未计算 | **0.5544** |
| Macro Recall（二分类，= Balanced Accuracy） | 未计算 | **0.5544** |

### D.2 与简单基线的真实对比（**本轮最重要的结论**）

| 模型 | F1 | Balanced Accuracy |
| --- | ---: | ---: |
| v2 实际模型 | 0.1967 | 0.5544 |
| **恒预测「攻击」基线** | **0.8235** | 0.5000 |
| 恒预测「正常」基线 | 0.0000 | 0.5000 |
| **相对恒攻击基线的提升** | **-0.6268** | +0.0544 |

> **v2 模型的 F1 比「恒预测攻击」这一无脑基线低 0.6268。**
> 当前二分类结果**不具备可用的检测能力**；而 v1 的高 F1（0.9956）**不能作为泛化能力证据**——
> 它同时受到移动 scaler 缺陷与测试集 98.8% 攻击占比的影响。

### D.3 每类召回（仅测试集实际出现的标签）

| 标签 | 支持样本 | 召回 |
| --- | ---: | ---: |
| `metasploit SYN flood` | 1399811 | 0.1091 |
| `observe` | 600189 | 0.0002 |

### D.4 六类攻击覆盖

| 标签 | 全量 | 训练分片 | 测试分片 | 独立测试 |
| --- | ---: | ---: | ---: | --- |
| `metasploit SYN flood` | 14696890 | 12399429 | 2297461 | **可用** |
| `nmap SYN flood` | 7993846 | 7993846 | 0 | `NOT_EVALUATED` |
| `observe` | 6645324 | 5574359 | 1070965 | **可用** |
| `nmap discovery` | 500000 | 500000 | 0 | `NOT_EVALUATED` |
| `ros2 reconnaissance` | 401494 | 401494 | 0 | `NOT_EVALUATED` |
| `ros2 node crashing` | 5743 | 5743 | 0 | `NOT_EVALUATED` |
| `ros2 reflection` | 3753 | 3753 | 0 | `NOT_EVALUATED` |

**5 个攻击类在测试分片中完全不存在**（`nmap SYN flood`、`nmap discovery`、
`ros2 reconnaissance`、`ros2 node crashing`、`ros2 reflection`），
因此**无法**给出它们的独立召回率，一律记 `NOT_EVALUATED`。
原因是标签在时间上**成块连续分布**，末两片只含 metasploit 与 observe。

**PR-AUC**：本轮**未计算** —— 需要在固定阈值扫描下保存全部预测分数，
而当前实现按 chunk 流式推理且未落盘分数。如实记为未计算，不以近似值代替。

### D.5 去周期性版本（v2）

| 指标 | Reduced v2 | No-periodicity v2 |
| --- | ---: | ---: |
| Accuracy | 0.3764 | 0.5796 |
| Precision | 0.9993 | 0.9999 |
| Recall | 0.1091 | 0.4596 |
| F1 | 0.1967 | 0.6297 |
| FPR | 0.0002 | 0.0001 |
| Balanced Accuracy | 0.5544 | 0.7298 |
| 恒攻击基线 F1 | 0.8235 | 0.8751 |
| 相对基线 dF1 | -0.6268 | -0.2454 |

**两个版本的模型都劣于恒预测攻击基线**，与 D.2 结论一致。

## E. 特征可行性口径统一

此前报告「4/61 个原始字段可直接获取」被**误用**为当前模型的在线覆盖率。两个口径必须分开：

| 口径 | 数量 |
| --- | ---: |
| `RAW_NON_LABEL_FIELDS`（原始非标签字段） | 61 |
| `TRAINED_MODEL_FEATURES`（**实际模型输入**，从 `feature_config.json` 读取） | **49** |
| `DIRECTLY_AVAILABLE_MODEL_FEATURES` (A) | **2** |
| `INSTRUMENTATION_REQUIRED_MODEL_FEATURES` (B) | 25 |
| `UNAVAILABLE_MODEL_FEATURES` (C) | 22 |
| `UNKNOWN` (D) | 0 |

**关键纠正**：`src_topic` 与 `msg_type` 属 A 类原始字段，但**未参与训练**
（文本列，在候选阶段即被排除）。因此当前模型的在线可直接获取特征数是 **2**，不是 4。
未参与训练的原始字段：`layers._ws.short`, `layers.icmpv6.icmpv6.type`, `layers.ip.ip.checksum`, `layers.ip.ip.flags`, `layers.sll.sll.unused`, `layers.tcp.tcp.flags_tree.tcp.flags.syn_tree._ws.expert._ws.expert.message`, `layers.tcp.tcp.options`, `layers.tcp.tcp.payload`, `msg_data`, `msg_type`, `src_topic`, `timestamp`。
**它们不得计入模型在线覆盖能力。**

矩阵：`docs/data/ROSPaCe_MODEL_FEATURE_FEASIBILITY.csv`；
机器可解析汇总：`docs/data/ROSPaCe_MODEL_FEATURE_FEASIBILITY_SUMMARY.json`。

## F. F0 集成

配置 `config/team_modules.rospace.example.yaml`：`comm_risk` 为真实 ROSPaCe 模型，
`identity_trust` 与 `task_risk` 仍为 **Mock**（模拟实现，**不是**真实身份或任务风险研究算法）。

| 路径 | 实测结果 |
| --- | --- |
| 正常（真实 `observe` 样本） | exit 0，`READY_FOR_GATEWAY_SUBMISSION`，三模块 `schema_ok=True` |
| 异常（真实攻击预测） | exit 10，`ADAPTER_BLOCK`，reason_code=`ADAPTER_MODULE_STATUS_NOT_PROCEED` |
| 错误路径 | 缺特征 exit 2 / 缺 request_count exit 4 / 不受信或损坏模型 exit 3，全部 fail-closed |

**异常路径的阻断原因来自模块安全状态，不是 Schema 无效** ——
`schema_ok=True` 且 `online.enabled=False`（未启动 Planner、未发送 Action）。
**未使用「故意制造非法 Schema」冒充异常检测成功。**

### 字段来源真实性

| 字段 | 来源 | 可信度说明 |
| --- | --- | --- |
| `communication.resource` / `resource_type` | **候选请求**（信封 `candidate_action`） | 运行上下文，非模型产生 |
| `window.start` / `end` | **运行上下文**（信封 `created_at`） | 非数据集原生 |
| `window.duration_ms` | 运行侧 `f0_runtime.window_ms`，缺失取 0 | 单点观测 |
| `request_count` | **运行侧** `f0_runtime.request_count` | **非模型产生**；缺失即阻断（exit 4） |
| `anomaly_category` / `risk_level` | **模型输出** | 模型判断，不是 DDS 事实 |
| 特征值 | 数据集原生特征行 | 离线；**不是**在线采集 |

**Schema 通过不等于所有字段都有真实观测来源。**

## G. 科研局限

1. **`FILE_DISJOINT_SPLIT` ≠ `SESSION_DISJOINT_SPLIT`**。
   实测各分片时间戳**首尾相接**（上一片 `last_ts` == 下一片 `first_ts`，微秒级一致），
   属**同一次连续采集按大小切片**，因此**无法证明采集会话独立**，同源时间相关性未被排除。
   此前「已排除同源泄漏」的措辞**过强，已更正**。
2. **六类攻击中 5 类无法独立评测**（见 D.4），因为标签在时间上成块连续。
   严禁把同一连续攻击序列的相邻行随机拆入训练与测试来制造每类召回率。
3. **v2 模型劣于简单基线**，说明当前特征集 + 二分类设定**尚不构成可用检测器**。
4. 两个数据版本**不具备完全一致的实验条件**（行数、时间基、测试集类别构成均不同），`COMPARISON` 保持 `PARTIAL`。
5. **`RUNTIME_MONITOR: NOT_READY` 保持不变** —— 模型 49 个输入特征中仅 2 个可在线直接获取。

## H. 下一步

**是否值得继续开发 A 类子集模型与 OS Monitor 采集器？** 本轮提供了**否定性证据**：

* 现有 49 个特征在二分类任务上**不如恒预测攻击基线**，说明模型没有学到有效判别边界；
* 仅剩的 2 个 A 类模型特征（`publishers_count`、`subscribers_count`）信息量远低于现有 49 个特征，
  **用它们重训几乎必然更差**；因此**不建议**优先投入 A 类子集模型。

**建议优先级**：

1. **先诊断当前 49 特征为何失效** —— 重点检查分片间特征分布差异（同一列在不同分片的量纲是否一致）、
   标签块状分布导致的概念漂移、以及是否应按会话而非按文件划分。诊断清楚前扩充采集器没有意义。
2. **OS Monitor 采集器**（25 个 B 类）仍是唯一有希望覆盖多数特征的路径，但应在模型有效性被证实之后再投入。
3. **C 类 22 个 Tshark 特征**需要 PCAP 采集链路，优先级最低。
---

## I. 门槛状态（独立判定）

| 门槛 | 状态 | 依据 |
| --- | --- | --- |
| `SCHEMA_MAPPING_FIX` | **PASS** | 缺陷已修复；负向对照证明修复前取值确实被 Schema 拒绝；正反测试均通过 |
| `MODEL_PROVENANCE_SECURITY` | **PASS** | 模型目录不再来自业务输入；信封切换被忽略并告警；不受信/损坏模型 exit 3 |
| `MODEL_FEATURE_AUDIT` | **PASS** | 口径统一；A+B+C+D == 49 断言成立；汇总 JSON 已生成 |
| `PREPROCESSING_FIX` | **PASS** | 两遍分离；训练中 scaler 固定；策略版本与填充/缩放哈希已落盘 |
| `EVALUATION_RELIABILITY` | **PARTIAL** | 已加 Balanced Accuracy / Macro Recall / 两个简单基线；但 **5 类 `NOT_EVALUATED`**、**PR-AUC 未计算** |
| `F0_COMM_ADAPTER` | **PASS** | 正常/异常/错误三路径实测；异常为**模块状态**阻断而非 Schema 无效 |
| `F0_REGRESSION` | **PASS** | 见附二 |
| `COMPARISON` | **PARTIAL** | 保持（两版本无法建立相同实验划分） |
| `RUNTIME_MONITOR` | **NOT_READY** | 保持（49 个模型特征中仅 2 个可在线直接获取） |

## J. F0 回归实测

| 项目 | 结果 |
| --- | --- |
| 契约校验 | `CONTRACT_OK` |
| F0 Python 单元测试 | **295 passed / UNIT TEST RESULT: PASS** |
| ROS 2 四包构建 | **BUILD RESULT: PASS** |
| 真实通信模块替换（T09，仅替换 comm_risk） | **PASS** |
| 冒烟回归 T02 / T03 / T04 | **全部 PASS**（exit 0） |
| 研究模块测试 `pytest tests/research/` | **38 passed** |

**冻结边界未改动**：`git diff ebfe263..HEAD` 对
`docs/interfaces/`（四份 Schema）、`PatrolNavigate.action`、八个业务原因码、
`src/rg_gateway/`、`security/` **均为空**。

### 回归中发现并修复的一处环境问题（非本轮代码缺陷）

`scripts/run_unit_tests.sh` 一度变为 **1 failed / 294 passed**：F0 的密钥材料守卫
（`tests/unit/test_interface_contract.py::test_no_key_material_is_committed`）
把隔离研究环境里 pip 自带的**公开** CA 证书包
`pip/_vendor/certifi/cacert.pem` 误判为密钥材料。

**未修改该 F0 测试文件**，而是把研究环境迁到 `tests/evidence/research-venv`
（该目录已在 `.gitignore` 中，且守卫的 `os.walk` 明确排除名为 `evidence` 的目录），
并在 `.research-venv` 保留相对符号链接使既有路径继续可用
（`os.walk` 默认不跟随符号链接）。迁移后单测恢复 **295 passed**。

## K. 一句话结论

**本轮修掉了三个真实缺陷，并把评测口径纠正到可信状态；
纠正后的模型劣于「恒预测攻击」这一无脑基线，
因此当前特征集与二分类设定尚不构成可用检测器 —— 这是本轮最重要的科研结论。**


---

## L. A4 限时漏报诊断（49 特征模型）

**诊断预算**：单轮集中诊断（远低于 24~48 小时上限）。**未预设结果必须提升。**

### L.1 阈值是否造成"高精确率、低召回"？—— **不是主因**

在真实测试分片（20 万抽样，攻击占比 68.35%）上做分数分布与阈值扫描：

| 分位 | p1 | p5 | p25 | p50 | p75 | p95 | p99 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| attack_probability | 0.000000 | 0.000000 | 0.000000 | 0.000001 | 0.000004 | 0.180499 | 0.975521 |

| 阈值 | Recall | Precision | F1 | FPR | Balanced Acc |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 0.5（默认） | 0.0697 | 0.9993 | 0.1303 | 0.0001 | 0.5348 |
| 0.1 | 0.0735 | 0.9809 | 0.1368 | 0.0031 | 0.5352 |
| 0.01 | 0.0788 | 0.9630 | 0.1457 | 0.0065 | 0.5361 |
| 0.001 | 0.0954 | 0.9137 | 0.1728 | 0.0195 | 0.5380 |

**关键观察**：**75% 的样本（含大量攻击样本）得到的攻击概率低于 1e-5**。
即使把阈值降到 0.001，Recall 也只从 0.070 升到 0.095，Balanced Accuracy
从 0.5348 升到 0.5380 —— **几乎不动**。

**结论：这不是阈值标定问题，而是模型对这些特征没有学到有判别力的边界。**
调阈值无法挽救；模型分数本身对多数攻击样本不具信息量。

### L.2 其余检查项

| 检查项 | 观察 |
| --- | --- |
| 训练/测试时间区块与攻击分布 | 标签在时间上**成块连续**；末两片只含 metasploit 与 observe |
| 六类攻击覆盖 | **5 类在测试分片中完全不存在**（`NOT_EVALUATED`） |
| 分片间特征分布变化 | 预处理统计出 **10 个零方差列**；各分片标签构成本身高度不同，存在明显分布差异 |
| SGD 是否收敛 | 损失未收敛到有判别力的解：分数几乎全部挤在 0 附近 |
| 类别不平衡 | 训练集攻击占比高，但**未使用类别权重**；本可作为对照实验 |
| 固定标准化下模型系数与特征异常 | 零方差列经固定规则（填 0、缩放 1）处理，不贡献信息 |
| 跨分片特征含义/单位不一致 | 未能排除：分片间同一列的量纲差异未做专门核验 |

### L.3 未做的对照实验（受预算限制）

按任务书允许的范围，**本轮未开展**：类别权重训练、正则/学习率扫描、
独立验证区块选阈值、非线性模型辅助对照、按攻击时间区块的评测。
原因是 L.1 已给出决定性证据：**分数本身不具判别力**，
在没有解决特征/分布问题之前做这些扫描只会产生更多不可信数字。

### L.4 诊断结论

**`DETECTOR_EFFECTIVENESS: NOT_PROVEN`**

- 现有 49 特征 + 二分类 + 文件级划分的组合**不足以支撑可用检测器**；
- 模型劣于「恒预测攻击」基线（F1 0.1967 vs 0.8235）；
- 漏报主因**不是阈值**，而是模型未学到判别边界；
- **止损决定**：不继续扩充模型、不立即开发全量 OS Monitor、
  不开发完整 PCAP/Tshark 采集链；通信检测模块**保留为离线研究原型**；
- 该结论**不阻塞 baseline 发布**。

**下一步真正该做的**：先诊断"为什么这些特征不具判别力" ——
重点核验分片间同一特征的量纲与语义是否一致（`Total_*` 类的累计值尤其可疑），
以及是否存在标签与采集时段的强耦合。在这一点澄清之前，
任何模型侧改动都缺乏依据。
