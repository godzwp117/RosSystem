# RosSystem 实验情况交接简报（供外部顾问给出下一步计划）

> 用途：粘贴给不具备本项目上下文的顾问/模型，请其给出下一步计划。
> 所有数字均为**本轮实测**，不含估算。

---

## 1. 项目定位

**RosSystem** 是一个面向「ROS 2 具身智能机器人通信安全」的研究工程，目标是为参赛/论文
建立**可复现的真实安全检测能力**。整体分两条线：

- **F0**：最小可运行协作框架（三名研究者的模块 + 一个权威 SecurityGateway）。
- **M3**：动态任务状态机（独立分支，**本轮未合并**）。

技术栈：ROS 2 Jazzy（Docker 容器内 Ubuntu 24.04）、`rmw_fastrtps_cpp`、
宿主 Ubuntu 22.04 WSL2。仓库 `github.com/godzwp117/RosSystem`。

### F0 已建成的东西（真实可用，非纸面）

- 四个 ROS 2 包：`rg_interfaces` / `rg_policy` / `rg_gateway` / `rg_demo_nodes`。
- 冻结 Action：`PatrolNavigate.action`；八个业务原因码。
- 三个研究模块接口（`CommRiskEvidence` / `IdentityTrustAssessment` /
  `TaskRiskDecision`）+ `ModuleInputEnvelope`，各带 Draft 2020-12 JSON Schema。
- 模块适配层 `scripts/team_demo.py`：以进程级 JSON 协议调用外部模块，
  支持**逐模块替换**；只有 `READY_FOR_GATEWAY_SUBMISSION` 与本地阻断两种结论。
- **SecurityGateway 是权威准入点**：已实测「三个模块全部建议放行 + 目标越界
  → 仍被 Gateway 以 `OUT_OF_REGION` 阻断、下游 Goal 数为 0」。
- 真实 ROS 2 Action 端到端链路可用；SROS 2 Enforce 对照实验 7/7 通过。

---

## 2. 本轮做的事：ROSPaCe 公开数据集适配

### 数据集

- 主数据集 `ROSPaCe_reduced`：**30,247,050 行 / 15 个分片**。
- 对照 `ROSPaCe_reduced_noperiodicity`：**20,851,051 行 / 10 个分片**。
- 各 62 列、7 类字符串标签，两套标签集合相同：
  `observe`(正常) + `metasploit SYN flood` / `nmap SYN flood` /
  `nmap discovery` / `ros2 reconnaissance` / `ros2 node crashing` / `ros2 reflection`。

### 方法

- 全程 `csv.reader` 流式 + `partial_fit`，**未用 `pandas.read_csv` 全量载入**；峰值内存 584 MB。
- 49 个数值特征；按**文件**划分训练/测试（不虚构 group_id）。
- 预处理（`StandardScaler` + 训练集列均值填充）**只在训练分片拟合**。
- `SGDClassifier(loss=log_loss)`，固定种子，训练 400 万行 / 测试 200 万行。

### 结果

| 指标 | Reduced | No-periodicity |
| --- | ---: | ---: |
| Accuracy | 0.9913 | 0.5784 |
| Precision | 0.9998 | 1.0000 |
| Recall | 0.9914 | 0.4581 |
| F1 | 0.9956 | 0.6284 |
| FPR | 0.0129 | 0.0000 |

---

## 3. 三个必须让顾问知道的关键事实

### 事实一：**只有 4 / 61 个模型输入特征能在 ROS 2 里拿到**

对模型的**每一个**输入特征做了四级分类：

| 级别 | 数量 | 含义 |
| --- | ---: | --- |
| **A 可直接获取** | **4** | `src_topic`、`publishers_count`、`subscribers_count`、`msg_type`（均已用 `rclpy` 图 API 实测） |
| B 需新增采集器 | 27 | OS Monitor 类（`/proc/net/dev`、`/proc/net/tcp`、`/proc/vmstat`、`/proc/meminfo`）+ `msg_data` |
| C 当前拿不到 | 30 | Tshark 分组字段（SLL/IP/TCP/SSL/IPv6/ICMPv6），需 PCAP 抓包且语义与 ROS 层不对应 |
| D 未知 | 0 | — |

**结论：现有模型依赖 57 个 B/C 类特征，不具备在线部署能力。**

### 事实二：**双版本对照不构成因果结论**

两版本测试集的**正常样本占比完全不同**（1.2% vs 22.2%），行数不同，时间戳不可对齐
（去周期性版本被重基到 `2023-01-01`）。所以 Recall 0.99 → 0.46 的落差
**不能说成「去周期性导致性能下降」**，只能报各自结果。

另外两版本测试集都**只出现 2 种标签**，无法给出 6 类攻击的分别召回率。

### 事实三：**离线分类 ≠ 实时检测**

Reduced 的 F1 0.9956 是在**攻击占 98.8%** 的测试集上得到的，FPR 只在 24,423 个正常样本上测得。
**不能外推为真实运行环境下的检测能力。**

---

## 4. 七个门槛的独立判定（不合并）

| 门槛 | 状态 | 说明 |
| --- | --- | --- |
| DATA_AUDIT | **PASS** | 两套真实数据表头、字段、全量类别分布已核实 |
| MODEL_BASELINE | **PASS** | 主数据集真实训练与评测成功，指标与混淆矩阵完整 |
| COMPARISON | **PARTIAL** | 各自独立训练完成，但**无法建立相同实验划分** |
| JAZZY_FEATURE_AUDIT | **PASS** | 61 个特征 100% 覆盖并四级分类，A 类均有实测证据 |
| COMM_INTERFACE | **PARTIAL** | 输出通过 `CommRiskEvidence` Schema 校验；但 `request_count` 无法由 ROSPaCe 产生，只能由运行侧提供 |
| F0_INTEGRATION | **PARTIAL** | `team_demo.py` 已实际加载外部模块并返回 `ADAPTER_OK`，其他两模块保持 mock；但为**离线**集成，未做 Gateway 联调核对 |
| **RUNTIME_MONITOR** | **NOT_READY** | 不具备 Jazzy 实时特征获取能力 |

F0 自身的三个发布门槛：`E-TECH: PASS`、`E-CONTRACT: BLOCKED`（契约仍为
`PROPOSED_V1`，未获团队确认）、`E-HANDOFF: BLOCKED`（无第二名成员实际参与）。

---

## 5. 尚未做的

1. **未建「仅 A 类特征」的子集模型** —— 因此**没有在线精度损失数据**。
2. `preprocess.py` / `evaluate.py` 未从 `train.py` 拆出（功能已实现并测试）。
3. 未做 Jazzy 实时采集器。
4. 未做 Gateway 在线联调（`online.enabled=False`）。
5. 契约未冻结、无独立团队复现。

---

## 6. 请顾问回答的问题

1. **在线化路线**：优先做「OS Monitor 采集器（21 个 B 类，最可行）」还是
   「ROS 图采集器（4 个 A 类）+ A 类子集模型」？两者投入产出比如何？
   是否应该先训一个 A 类子集模型，用**在线精度损失**这个数字来驱动路线决策？

2. **科研叙事**：`RUNTIME_MONITOR: NOT_READY` 是硬伤还是可讲的诚实结论？
   若目标是在竞赛/论文中成立，应该把叙事重心放在
   「公开数据集的离线基线」还是「F0 框架的权威准入 + 分层阻断」上？

3. **对照实验补救**：两版本无法同划分比较，有没有可行办法做出**公平对照**
   （例如按标签分层抽样对齐两版本测试集，或只在共同标签上比较）？
   还是应当放弃这个对照、换一个更有说服力的实验设计？

4. **特征工程**：C 类 30 个 Tshark 特征是否值得投入 PCAP 采集链路？
   如果改用「只用 A+B 类特征重训」，预期精度会掉多少、是否仍具竞争力？

5. **优先级**：在当前资源下，下一步最该做的一件事是什么？
   请给出可执行的第一步与验收标准。

---

## 7. 代码与复现

- 分支 `feature/rospace-dataset-adapter`，提交
  `3090de8` → `ac0e7e8` → `59cc28b` → `5594843`（已推送）。
- 模块：`modules/rospace_comm/`（`inspect_data.py` / `train.py` / `predict.py` /
  `f0_adapter.py` / `README.md`）。
- 配置：`config/team_modules.rospace.example.yaml`（只替换 `comm_risk`）。
- 报告：`docs/review/F0_ROSPaCe数据适配与检测基线验收报告.md`、
  `docs/review/ROSPaCe_双版本检测基线对照报告.md`。
- 数据审计：`docs/data/ROSPaCe_*.{md,csv,json}`。
- 测试：`tests/research/test_rospace_adapter.py`（**20 项全部通过**）。

复现命令（隔离研究环境 `.research-venv`，未污染 ROS 2 容器）：

```bash
.research-venv/bin/python modules/rospace_comm/inspect_data.py --chunk 200000
.research-venv/bin/python modules/rospace_comm/train.py --dataset reduced \
    --max-train-rows 4000000 --max-test-rows 2000000 --test-files 2
.research-venv/bin/python -m pytest tests/research/test_rospace_adapter.py -q
```
