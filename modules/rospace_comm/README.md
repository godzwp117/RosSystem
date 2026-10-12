# modules/rospace_comm — ROSPaCe 通信异常检测（离线基线）

把 ROSPaCe reduced 公开数据集适配成 F0 可用的通信风险模块。

> **一句话定位**：这是**公开数据集上的离线分类器**，**不是** ROS 2 实时入侵检测器。
> 61 个模型输入特征里，Jazzy 能直接获取的只有 **4 个**（详见
> `docs/data/ROSPaCe_JAZZY_FEATURE_FEASIBILITY.csv`）。

## 文件

| 文件 | 作用 |
| --- | --- |
| `inspect_data.py` | 阶段 A：数据定位、表头审计、feature_list 解析、**全量分块统计** |
| `train.py` | 阶段 B/C：内存有界预处理 + SGDClassifier 增量训练 + 评测 |
| `predict.py` | 阶段 F2：离线推理入口（字段校验、安全失败、模型溯源） |
| `f0_adapter.py` | 阶段 F3：把模型接成 F0 外部模块（CommRiskEvidence 协议） |

## 快速开始

```bash
# 0) 隔离研究环境（不要往 ROS 2 容器里装 ML 依赖）
python3 -m venv .research-venv
.research-venv/bin/pip install numpy pandas scikit-learn openpyxl jsonschema pyyaml

# 1) 数据审计（全量统计，约 95 秒）
.research-venv/bin/python modules/rospace_comm/inspect_data.py --chunk 200000

# 2) 训练（主数据集）
.research-venv/bin/python modules/rospace_comm/train.py --dataset reduced \
    --max-train-rows 4000000 --max-test-rows 2000000 --test-files 2 --chunk 100000

# 3) 离线推理
.research-venv/bin/python modules/rospace_comm/predict.py \
    --run-dir training_runs/rospace_reduced \
    --csv-row 'data/ROSPaCe_reduced/ROSPaCe_reduced/rospace_reduced_0.csv:100'

# 4) F0 集成（只替换 comm_risk）
.research-venv/bin/python scripts/team_demo.py \
    --input <envelope.json> --config config/team_modules.rospace.example.yaml
```

## 数据事实（实测，非文档转述）

| 项 | 主数据集 | 去周期性 |
| --- | ---: | ---: |
| 分片数 | 15 | 10 |
| 全量行数 | 30,247,050 | 20,851,051 |
| 列数 | 62 | 62 |

- **每个数据集只有 `_0` 分片带表头**，其余分片首行即数据。
  不加区分会丢行，并让标签统计被静默跳过。
- 标签是**字符串**（7 类），不是 0/1。`observe` = 正常，其余 6 类 = 攻击。
- 分片内部按攻击类型**块状排列**：取文件前 N 行会得到单类别测试集
  （会伪造出 `Accuracy=1.0`）。必须跨整个文件抽样。

## 内存与可复现性

- 全程 `csv.reader` 流式 + `partial_fit`，**不使用 `pandas.read_csv` 全量载入**。
- `--chunk` / `--max-train-rows` / `--max-test-rows` / `--seed` 均可配置。
- 预处理（scaler、缺失值列均值）**只在训练分片拟合**，测试集不参与。
- 产物含模型 SHA-256、特征配置 SHA-256 与划分清单。
- **`FULL_DATASET_STATISTICS` ≠ `TRAINING_SUBSET`**：全量 30,247,050 行，
  训练只用 400 万行子集。不要混称。

## F0 接口映射的诚实边界

`f0_adapter.py` 输出 `CommRiskEvidence`。哪些字段能真实产生：

| 字段 | 来源 |
| --- | --- |
| `communication.resource` / `resource_type` | 取自输入信封的 `candidate_action` |
| `window` | 取自输入信封时间戳；`duration_ms` 由运行侧提供，否则 0（点观测） |
| `anomaly_category` / `risk_level` | **模型输出**（是模型判断，不是 DDS 事实） |
| `basis` / `extensions` | 模型 SHA-256、数据集来源、在线能力声明 |
| **`request_count`** | **只接受运行侧提供**。ROSPaCe 是逐包监测，没有"业务请求"概念 |

**`request_count` 缺失时模块拒绝产出（退出码 4）**，而不是填 0 或用均值伪装。
这是 `COMM_INTERFACE` 被标为 `BLOCKED` 的原因。

`producer.source` 与 `evidence_refs[].kind` 使用 Schema **既有枚举值**
（`EXTERNAL` / `UNKNOWN`）；"由公开数据集离线训练"这一限定写在
`evidence_refs[].note` 与 `extensions.rospace_comm` 里 ——
**没有为了迁就数据集而修改任何公共 Schema**。

## 模型版本与当前口径

| 项 | 值 |
| --- | --- |
| v1 | **历史实验**，存在预处理统计量不固定与分片字符串排序两个缺陷，结果不可用 |
| v2 | 已修复的实验，产物在 `training_runs/rospace_*_v2` |
| 原始非标签字段 | 61 |
| **v2 实际模型输入** | **49** |
| **Jazzy 可直接在线获取的模型特征** | **2**（`publishers_count`、`subscribers_count`） |
| 划分性质 | `FILE_DISJOINT_SPLIT` + `SESSION_INDEPENDENCE_UNVERIFIED` |
| 检测能力 | **尚未得到可靠实用性证明**（`DETECTOR_EFFECTIVENESS: NOT_PROVEN`） |
| 实时监测 | **`NOT_READY`** |

**指标定义（不可混用）**：

* **二分类 Macro Recall** = `(Recall_attack + Recall_normal)/2`，
  其中 `Recall_normal = TN/(TN+FP)`。二分类下它**等于 Balanced Accuracy**。
* **`macro_attack_detection_recall`** = 各**攻击类别**检测召回的平均，
  是另一个指标，名称独立。
* 正常类的 `detection_recall` 字段实际是**误报率**，正常类召回率见
  `metrics.specificity_recall_normal`。

## 安全边界

1. **不是实时检测**。`RUNTIME_MONITOR: NOT_READY`。
2. `READY_FOR_GATEWAY_SUBMISSION` **不代表** Gateway 已允许，更不代表下游已执行。
3. 模型输出**不构成** DDS 身份认证证据，也**不是** F0 运行日志。
4. 不得用 0、训练集均值、随机数或**缓存的 CSV** 冒充在线特征值。
5. 原始数据只读；模型与训练缓存不入库（见 `.gitignore`）。
