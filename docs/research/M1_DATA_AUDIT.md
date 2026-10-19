# M1 数据与标签审计（专项② P0）

> 代码基准：`be47ccd6c1b19460b65abc0ea8004706383d01d4`
> 审计脚本：`scripts/m1_data_audit.py`
> run_id：`m1audit-20261018T160049Z`
> 证据：`artifacts/research/m1/m1audit-20261018T160049Z/data_audit/{data_audit.json,data_audit.md}`

本文件只记录**实测事实**。所有数字可用 `scripts/m1_data_audit.py` 复现。

---

## 1. 要回答的问题

修复前 M1 的两个模型测试 F1 分别是 **0.1312**（49 维）与 **0.0891**（24 维），
而"恒预测攻击"的平凡基线 F1 却有约 **0.81**。

**一个模型比"一律报警"还差一个数量级**，说明问题不在模型容量。
在改模型之前必须先把数据事实查清楚：标签在哪、分布如何、划分是否等价于类别划分。

---

## 2. 数据来源

| 项 | 值 |
| --- | --- |
| 归档 | `data/ROSPaCe_reduced/ROSPaCe_reduced.tar.gz`（920,868,855 字节） |
| 解包目录 | `data/ROSPaCe_reduced/ROSPaCe_reduced/`（15 个 CSV，合计约 14 GB） |
| 列数 | **62 列，无表头** |
| 标签列 | **第 61 列**（0 起算，即最后一列）——脚本自动探测，不假设位置 |
| 特征清单 | `modules/member1_comm/features.json`（49 维，tshark 字段名） |
| 列名来源 | `data/ROSPaCe_reduced/feature_list.xlsx`（519 条共享字符串，含 monitor 说明） |

> 注意：`features.json` 的 49 维是 62 列中的子集，且 CSV 无表头，
> 因此"按顺序取前 49 列"是一个**假设**，已在审计输出
> `feature_column_mapping.assumption` 中显式声明。

---

## 3. 关键发现一：类别远多于二分类

采样（每片 20,000 行，等距、与标签无关）得到的标签分布：

| 标签 | 样本数 | 占比 |
| --- | --- | --- |
| `metasploit SYN flood` | 149,803 | 49.71% |
| `observe`（正常） | 75,528 | 25.06% |
| `nmap SYN flood` | 65,466 | 21.72% |
| `nmap discovery` | 5,756 | 1.91% |
| `ros2 reconnaissance` | 4,715 | 1.56% |
| `ros2 node crashing` | 65 | 0.02% |
| `ros2 reflection` | 38 | 0.01% |
| `attack`（原始粗标签） | 1 | 0.00% |

**结论**：数据集实际包含 **6 类攻击**（2 类 SYN flood、nmap discovery、
ros2 reconnaissance、ros2 node crashing、ros2 reflection），
而此前把"非 observe"统一当"攻击"做二分类，没有区分攻击类型，
因此无法回答"哪些攻击被检出、哪些完全失效"。

### 3.1 平凡基线（任何模型的最低可接受线）

| 策略 | F1 |
| --- | --- |
| 恒预测"攻击" | **0.8567** |
| 恒预测"正常" | 0.4008 |

> 原 49 维模型的 0.1312 **低于两条平凡基线**。这不是"检测能力不足"，
> 而是**评估口径失效**：测出的数字没有解释力。

---

## 4. 关键发现二：文件级划分 ≈ 类别划分（这是根因）

逐分片标签纯度：

| 分片 | 主导类别占比 | 标签分布（抽样） |
| --- | --- | --- |
| `rospace_reduced_0.csv` | 61.14% | nmap discovery=5756, observe=12275, ros2 reconnaissance=2045 |
| `rospace_reduced_1.csv` | 86.59% | observe=17385, ros2 reconnaissance=2670, ros2 reflection=22 |
| `rospace_reduced_2.csv` | 99.70% | observe=20158, ros2 node crashing=45, ros2 reflection=16 |
| `rospace_reduced_3.csv` | 57.39% | nmap SYN flood=11480, observe=8503, ros2 node crashing=20 |
| `rospace_reduced_4.csv` | **95.57%** | nmap SYN flood=19131, observe=887 |
| `rospace_reduced_5.csv` | **94.33%** | nmap SYN flood=18920, observe=1138 |
| `rospace_reduced_6.csv` | 79.64% | metasploit SYN flood=3229, nmap SYN flood=15935, observe=846 |
| `rospace_reduced_7.csv` | **97.77%** | metasploit SYN flood=19716, observe=450 |
| `rospace_reduced_8.csv` | **98.23%** | metasploit SYN flood=19665, observe=355 |

**每个分片是一次独立采集会话，且被某一类攻击主导。**
原先的"按文件划分"（训练 1–11、验证 12–13、测试 14–15）因此近似于
"按攻击类别划分"：训练集几乎见不到测试集的主导攻击类型，
特征分布也随之整体漂移。

这同时解释了两件事：

1. **测试 F1 崩到 0.13**：模型学到的是训练分片的类内模式，迁移到新分片即失效；
2. **验证集与测试集差距巨大**：两个划分的主导攻击类别不同。

> 审计脚本对此给出显式警告：
> `存在单一类别占比 >95% 的分片：文件级划分近似类别划分，
> 在该划分上报告的高指标不能代表泛化能力。`

---

## 5. 关键发现三：旧测试集已被反复使用

49 维与 24 维模型的阈值、特征子集、以及多轮诊断都在这同一组划分上进行过。
因此该划分**不能**再承担"最终独立验证"的角色。

本次工作据此规定：

- 旧划分一律降级为 **研究诊断集**，只用于定位问题，不用于报告最终指标；
- 最终指标改用**会话分组交叉验证**（`GroupKFold` by `segment_index`），
  训练折与验证折不共享采集会话；
- 阈值只能在训练折上选，验证折不参与阈值选择。

---

## 6. 特征缺失与量纲

审计对 49 维逐特征统计了缺失率与均值/极值（见 `data_audit.json` 的
`worst_missing_features` 与各分片的 `feature_missing_rate`）。
缺失普遍存在，此前用"训练中位数插补"，这一点本身合理，
但在**分布已经因分片而漂移**的前提下，插补无法弥补表征层面的错配。

---

## 7. 审计结论

| 问题 | 结论 |
| --- | --- |
| 标签定义是否清楚 | **是**（第 61 列，7 个取值，含 6 类攻击） |
| 是否做过分类别评估 | **此前没有**；本次改为逐类别报告 |
| 文件级划分是否等价于类别划分 | **是，且这是 F1 崩塌的主因** |
| 旧测试集可否继续用作最终验证 | **不可**，已降级为诊断集 |
| 数据是否有会话级分组信息 | **有**（分片即会话）；窗口数据另有 `segment_index` |
| 缺失值处理是否泄漏 | 全量中位数会泄漏；已改为**只用训练折**的中位数 |

**下一步**（见 `M1_MODEL_EXPERIMENTS.md`）：改用能在运行时真实观测的
窗口级特征，并按会话分组做交叉验证。
