# F0 × ROSPaCe 数据适配与检测基线验收报告

## A. Git 版本

| 项 | 值 |
| --- | --- |
| 起始 SHA | `ebfe263530d10a746c172367f9d96d2f9dc5d7d4`（F0 定向整改后） |
| 分支 | `feature/f0-framework` → 本轮新建 `feature/rospace-dataset-adapter` |
| 基线核对 | HEAD 与固定提交一致；工作区外来未跟踪内容已识别并保持原样 |

## B. 数据审计

**实际路径与任务书不同**：`data/ROSPaCe_reduced/` 下同时含两个数据集与 `feature_list.xlsx`。

| 项 | 主数据集 | 去周期性 |
| --- | ---: | ---: |
| 分片数 | 15 | 10 |
| **全量行数（实测遍历全部行）** | **30,247,050** | **20,851,051** |
| 列数 | 62 | 62 |
| 压缩包 | 920,868,855 B | 697,155,970 B |

- **`feature_list.xlsx`**：`features_list` 表 483 行 × 3 列，**482 条特征**
  （Tshark 451 / OS Monitor 25 / ROS Monitor Node 5 / 空 1）。
  reduced 的 62 列**全部能在其中找到说明**，`SEMANTICS_UNKNOWN` = **0**。
- **标签是字符串而非 0/1**，实测 7 类：`observe`(正常)、`metasploit SYN flood`、
  `nmap SYN flood`、`nmap discovery`、`ros2 reconnaissance`、`ros2 node crashing`、
  `ros2 reflection`。**两套数据标签集合完全相同。**
- **关键结构发现**：每个数据集**只有 `_0` 分片带表头**，其余分片首行即数据。
  不加区分会同时丢掉每片一行真实数据、并使标签统计被静默跳过
  （首轮运行正是如此，标签只覆盖第 0 片 1,746,677 行；修正后得到全量分布）。
- 两版本**行数不同、时间戳不可对齐**（去周期性版本时间被重基到 `2023-01-01`）。

产物：`docs/data/ROSPaCe_DATA_AUDIT.md`、`ROSPaCe_FEATURE_DICTIONARY.csv`、
`ROSPaCe_LABEL_DISTRIBUTION.csv`、`ROSPaCe_DATA_MANIFEST.json`（含 27 个文件 SHA-256）。

## C. 模型训练

| 项 | 值 |
| --- | --- |
| 算法 | `SGDClassifier(loss=log_loss)`, `average=True`, `learning_rate=optimal` |
| 预处理 | `StandardScaler` + 训练集列均值填充缺失（仅训练集拟合） |
| 读取方式 | `csv.reader` 流式 + `partial_fit`，**未使用 `pandas.read_csv` 全量载入** |
| chunk | 100,000 行（可配） |
| 随机种子 | 20261011 |
| 训练/测试样本 | 3,999,996 / 2,000,000 |
| 训练耗时 / 推理耗时 | 见 `training_runs/rospace_reduced/metrics.json` |
| 峰值内存 | 584 MB（实测 `ru_maxrss`） |
| 数值特征 | 49（排除 5 个非数值列与标签列） |

**指标（Reduced）**：TP=1,958,519 FP=316 TN=24,107 FN=17,058
→ Accuracy=0.9913、Precision=0.9998、Recall=0.9914、F1=0.9956、**FPR=0.0129**

> **FULL_DATASET_STATISTICS ≠ TRAINING_SUBSET**：全量统计 30,247,050 行，
> 训练仅用 4,000,000 行子集。报告中已严格区分，未把子集规模称为完整数据集规模。

## D. 双版本对照

| 指标 | Reduced | No-periodicity | 差异 |
| --- | ---: | ---: | ---: |
| Accuracy | 0.9913 | 0.5784 | −0.4129 |
| Precision | 0.9998 | 1.0000 | +0.0002 |
| Recall | 0.9914 | 0.4581 | −0.5333 |
| F1 | 0.9956 | 0.6284 | −0.3672 |
| FPR | 0.0129 | 0.0000 | −0.0129 |

**但该差异不能归因于「去周期性」**：两版本测试集类别比例完全不同
（正常样本 24,423 / 1.2% vs 444,075 / 22.2%），且都只出现 2 种标签。
按任务书要求，**各自结果已给出，但直接数值比较的结论强度受限**。
详见 `docs/review/ROSPaCe_双版本检测基线对照报告.md`。

**本轮实测踩到并修复的坑**：首版取文件**前 N 行**，得到 `TN=0 / Accuracy=1.0000` 的
伪完美结果——分片内部按攻击类型块状排列。改为跨整个文件步长抽样后指标才具备意义。

## E. Jazzy 特征矩阵

`docs/data/ROSPaCe_JAZZY_FEATURE_FEASIBILITY.csv`（61 个模型输入特征，100% 覆盖）：

| 状态 | 数量 | 说明 |
| --- | ---: | --- |
| **A — DIRECTLY_AVAILABLE** | **4** | `src_topic`、`subscribers_count`、`publishers_count`、`msg_type`（**全部已实测**） |
| B — AVAILABLE_WITH_INSTRUMENTATION | 27 | OS Monitor 系列（`/proc/vmstat`、`/proc/net/dev`、`/proc/net/tcp` 等）+ `msg_data`；其中 6 项已实测可读 |
| C — NOT_AVAILABLE | 30 | Tshark 分组字段（SLL/IP/TCP/SSL/IPv6/ICMPv6），需 PCAP 抓包且语义与 ROS 层不对应 |
| D — UNKNOWN | 0 | 无 |

**A 类实测证据**：`rclpy` 图 API 真实返回数据 ——
`get_topic_names_and_types()` → `/rosout`、`/parameter_events`；
`get_publishers_info_by_topic()` / `get_subscriptions_info_by_topic()` → 真实
`PublisherInfo`/`SubscriptionInfo`（含 `node_name`、`topic_type`）。
**语义差异**：Action 资源需查询其 `_action/*` 子话题，裸名查询返回 0（实测确认）。

**结论**：模型依赖 57 个 B/C 类特征 → **不具备 Jazzy 在线部署能力**。
不得用 0、训练集均值、随机数或缓存 CSV 冒充在线数据。

## F. 系统适配

| 项 | 结果 |
| --- | --- |
| 独立离线推理入口 | `modules/rospace_comm/predict.py`，**已实测 4 条路径** |
| 公共 Schema 映射 | **PARTIAL/BLOCKED** —— 见下 |
| `team_demo.py` 加载 | **未执行**（见下） |

**F2 实测**：
- 真实 CSV 行推理 → exit 0，输出 `prediction_label`、模型 SHA-256、证据引用
- 缺特征 → **exit 4**（`INPUT_INCOMPATIBLE`，明确不填充 0）
- 缺模型 → **exit 3**（不默认返回"正常"）
- 输入含标签列 → 忽略并告警

**CommRiskEvidence 映射为何 BLOCKED**：ROSPaCe 特征为**分组/系统级监测数据**，
不包含具体 Action 资源名、业务 `request_id` 或真实请求数量。因此
`communication.resource`、`resource_type`、`window`、`request_count` 等字段
**无法由模型输出真实产生**。按任务书要求，**不填虚构默认值**，
只交付独立离线推理结果，F0 完整接口映射标记 **BLOCKED**。
数据集来源仅记录在 `extensions`，未冒充 DDS 身份认证证据或 F0 运行日志。

## G. 测试

| 组 | 内容 | 结果 |
| --- | --- | --- |
| DATA | 两数据集真实读取、feature_list 解析、表头差异、标签映射、全量类别统计、分块读取、异常数值 | 见 §B；关键缺陷（表头探测）已修复 |
| MODEL | 训练成功、真实测试集推理、无标签泄漏、预处理仅训练集拟合、种子固定、字段兼容、缺模型安全失败 | 通过 |
| COMPARISON | 双版本分别训练、参数可比、划分有记录、指标完整 | 通过（结论强度受限） |
| JAZZY_FEATURES | 100% 覆盖、每项有状态、A 类有实测证据、B/C/D 未宣称在线支持 | 通过 |
| F0 | 契约校验、单测、四包构建 | 通过 |

## H. 科研结论

1. **数据周期性影响**：无法从本轮对照中得出因果结论——两版本测试集类别构成不同、
   行数不同、时间戳不可对齐，不满足同划分比较的前提。**降低结论强度。**
2. **真实通信异常检测效果**：在 ROSPaCe reduced 上离线二分类可达 F1 0.9956，
   但这是**攻击占 98.8% 的测试集**上的结果，且 FPR 只在 24,423 个正常样本上测得。
   **不能外推为真实运行环境下的检测能力。**
3. **泛化性限制**：按文件划分已避免同源泄漏，但两版本测试集均只含 2 种标签，
   无法给出 6 类攻击的分别召回率。

## I. 后续任务（在线化所缺的最小工程工作）

1. **OS Monitor 采集器**（覆盖 27 个 B 类中的 21 个）：按固定窗口差分
   `/proc/net/dev`、`/proc/net/tcp`、`/proc/vmstat`、`/proc/meminfo`，
   并与 ROS 消息窗口对齐 —— 这是**最可能成功**的一条路径。
2. **ROS 图采集器**（4 个 A 类）：基于 `rclpy` 图 API 周期性采样，
   Action 需展开 `_action/*` 子话题。
3. **C 类 30 个 Tshark 特征**：需要授权的本地 PCAP/RTPS 采集链路，
   且必须先论证其语义能与非 ROSPaCe 环境等价 —— 难度最高。
4. 在上述采集链路完成并通过**时间窗口与单位一致性验证**之前，
   不得声明具备在线监测能力。

## J. 最终结论

| 门槛 | 状态 | 依据 |
| --- | --- | --- |
| **DATA_AUDIT** | **PASS** | 两套真实数据表头、字段与全量类别分布均已核实；发现并修复表头结构缺陷 |
| **MODEL_BASELINE** | **PASS** | 主数据集真实训练与评测成功，指标与混淆矩阵完整可复现 |
| **COMPARISON** | **PARTIAL** | 双版本各自独立训练评测已完成，但两版本**无法建立相同实验划分**，直接数值比较结论强度受限 |
| **JAZZY_FEATURE_AUDIT** | **PASS** | 61 个模型输入特征 100% 覆盖并四级分类；A 类 4 项均有实测证据 |
| **COMM_INTERFACE** | **BLOCKED** | 缺 Action 资源名、`request_id`、真实请求计数等业务字段，无法映射为完整 `CommRiskEvidence`；不填虚构默认值 |
| **F0_INTEGRATION** | **BLOCKED** | 未通过 `team_demo.py` 实测加载与 Gateway 联调 |
| **RUNTIME_MONITOR** | **NOT_READY** | 模型依赖 57 个 B/C 类特征，**不具备 Jazzy 实时特征获取能力**；仅为公开 CSV 离线分类 |

> **离线检测是本轮明确目标；在线监测必须有实际 Jazzy 采集证据才能宣布完成。**
> 本轮只完成了公开 CSV 的离线分类，因此 `RUNTIME_MONITOR` 如实记为 `NOT_READY`。

## 工程安全

- 原始数据**只读**：未修改、未删除、未重新下载任何原始文件。
- 未提交原始 CSV、压缩包、训练缓存或模型二进制：
  `.gitignore` 已含 `/data/**`、`/training_runs/`、`/models/`、`/.research-venv/`。
- 训练产物保存在本地 `training_runs/`（已忽略），仅提交配置与指标。
- 未修改四份公共 Schema、冻结 Action、八个业务原因码或 DDS 权限配置。
