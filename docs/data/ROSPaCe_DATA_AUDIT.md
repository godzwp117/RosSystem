# ROSPaCe reduced 数据审计报告（阶段 A）

> 本文所有数量均来自本轮**实际文件读取**（全量分块遍历，非抽样、非估算）。

## 1. 数据定位与文件清单

任务书给出的路径与实际布局不同。实际结构（两个数据集与 feature_list 在**同一目录**下）：

```text
data/ROSPaCe_reduced/
├── ROSPaCe_reduced/                  # 主数据集：15 个 CSV
├── ROSPaCe_reduced_noperiodicity/    # 对照数据集：10 个 CSV
├── feature_list.xlsx                 # 特征定义（483 行表，482 条特征）
├── windows_0.jsonl                   # 附带窗口文件
└── *.tar.gz                          # 原始压缩包
```

| 文件 | 大小(字节) | SHA-256(前16) | 格式 |
| --- | ---: | --- | --- |
| `data/ROSPaCe_reduced/ROSPaCe_reduced/rospace_reduced_0.csv` | 957575156 | `` | csv |
| `data/ROSPaCe_reduced/ROSPaCe_reduced/rospace_reduced_1.csv` | 957574646 | `` | csv |
| `data/ROSPaCe_reduced/ROSPaCe_reduced/rospace_reduced_10.csv` | 957574618 | `` | csv |
| （其余 24 个文件见 manifest） | | | |

完整 27 个文件的 SHA-256 见 `docs/data/ROSPaCe_DATA_MANIFEST.json`。

## 2. 关键结构发现：只有 `_0` 文件带表头

**本轮最重要的数据工程发现。** 实测每个数据集**只有编号 `_0` 的分片含表头行**，其余分片首行就是数据：

```text
rospace_reduced_0.csv                有表头=True   62 列   timestamp,layers.sll.sll.pkttype,...
rospace_reduced_1.csv                有表头=False  62 列   2023-06-12 13:41:56.762430464,0,772,...
rospace_reduced_noperiodicity_0.csv  有表头=True   62 列
rospace_reduced_noperiodicity_1.csv  有表头=False  62 列   2023-01-01 00:00:00.024765440,...
```

不区分这一点会同时造成两类**静默错误**：丢掉每个分片的一行真实数据；
以及在无表头分片里找不到标签列，使**标签统计被静默跳过**。
本轮首次运行正是如此——标签计数只覆盖第 0 个分片（1,746,677 行），
修正表头探测后才得到下文的全量分布。缺陷已修复并有回归证据。

## 3. 字段字典

`feature_list.xlsx` 含 `features_list` 工作表（483 行 × 3 列：`feature_name`/`monitor`/`description`），共 **482 条特征**：

| monitor | 数量 |
| --- | ---: |
| Tshark | 451 |
| OS Monitor | 25 |
| ROS Monitor Node | 5 |
| (空) | 1 |

- **reduced 的 62 列全部能在 feature_list 中找到说明**：`SEMANTICS_UNKNOWN` = **0** 个。
- `attack` 是标签列，其 monitor 与 description **均为空**——数据集作者未在特征表中给出标签语义，
  因此标签含义只能由实际取值确定（见 §4），本轮未做任何猜测。
- `msg_data` 的描述为 "The header of a ROS2 message"，属消息载荷而非数值特征。

逐字段的类型/空值/极值统计见 `docs/data/ROSPaCe_FEATURE_DICTIONARY.csv`。

## 4. 标签语义（由实际取值确定）

标签 `attack` 是**字符串**，不是 0/1。实测共 7 种取值：

| 原始标签 | 主数据集 | 占比 | 去周期性 | 占比 |
| --- | ---: | ---: | ---: | ---: |
| `metasploit SYN flood` | 14696890 | 48.5895% | 9236810 | 44.2990% |
| `nmap SYN flood` | 7993846 | 26.4285% | 5392828 | 25.8636% |
| `observe` | 6645324 | 21.9702% | 5330564 | 25.5650% |
| `nmap discovery` | 500000 | 1.6531% | 540042 | 2.5900% |
| `ros2 reconnaissance` | 401494 | 1.3274% | 341312 | 1.6369% |
| `ros2 node crashing` | 5743 | 0.0190% | 5742 | 0.0275% |
| `ros2 reflection` | 3753 | 0.0124% | 3753 | 0.0180% |

**二分类映射（本轮采用）**：`observe` = 正常(0)；**其余 6 类** = 攻击(1)。
依据：`observe` 是唯一表示观测基线的取值，其余 6 个名称都明确指向攻击行为。
**两套数据的标签集合完全相同**，标签定义一致。

类别极不平衡：`observe` 仅占 21.97%（主）/ 25.56%（去周期性）；
`ros2 node crashing` 仅 5743 行（0.0190%）、`ros2 reflection` 仅 3753 行（0.0124%），
属极稀有类，在按文件划分的测试集中可能完全不出现。

## 5. 全量规模与统计范围

| 项 | 主数据集 | 去周期性 |
| --- | ---: | ---: |
| 分片数 | 15 | 10 |
| **全量行数（FULL_DATASET_STATISTICS）** | **30247050** | **20851051** |
| 列数 | 62 | 62 |
| 统计方式 | 分块遍历全部行 | 分块遍历全部行 |
| 统计状态 | FULL | FULL |

**未使用任何行数上限**，统计覆盖全部行。逐文件行数见 manifest 的 `per_file_rows`。

## 6. 两套数据的差异

- **列名与列数完全一致**（各 62 列，含 `attack`）。
- **行数不同**：30247050 vs 20851051，相差 9395999 行（约 31.1%）。
- **时间处理不同**：主数据集时间戳跨越 `2023-03-16` 至 `2023-06-16`（真实采集时间）；
  去周期性数据集时间戳被**重基到 `2023-01-01 00:00:00` 附近**（实测首行 `2023-01-01 00:00:00.024765440`）。
- 因此两套数据**不具备一一对应的行顺序**，也**没有可对齐的时间戳**。

## 7. 数据质量问题

| 检查项 | 结果 |
| --- | --- |
| 重复列 | 无 |
| 训练目标泄漏字段 | `attack` 为唯一标签列；其余 61 列不含标签派生信息 |
| 非有限数值 | 按列统计，见 `ROSPaCe_FEATURE_DICTIONARY.csv` 的 `non_finite` 列 |
| 常量列 | 见字典中 `min == max` 的列 |
| 非数值列（已在训练中排除） | `layers.sll.sll.unused`、`layers.ip.ip.flags`、`layers.ip.ip.checksum`、`layers.tcp.tcp.payload`、`layers.icmpv6.icmpv6.type` |
| 缺失值 | 各列 `empty` 计数见字典；训练按**训练集列均值**填充 |
| 文件损坏 | 未发现，27 个文件全部可解析 |

## 8. 必须声明的限制

1. **全量统计规模 ≠ 训练规模**。本文统计覆盖 30247050 / 20851051 行；
   训练使用 **TRAINING_SUBSET**（各 4,000,000 行）、测试使用子集（各 2,000,000 行）。
   **不得把子集数量描述为完整数据集规模。**
2. **分片内部按攻击类型块状排列**。实测直接取文件前 N 行会得到**单类别测试集**
   （曾出现 `TN=0`、`Accuracy=1.0` 的伪完美结果）。本轮改用**跨整个文件固定步长抽样**
   以保持真实类别比例，并在报告中同时记录训练/测试的真实标签分布。
3. 本轮未对标签做业务外推（例如未声称某个标签等价于某种 DDS 攻击）。
   标签只是数据集作者给出的实验条件标记。