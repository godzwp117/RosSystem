# M1 第五轮 G2：真实 ROS 图行为可观测性

> run_id：`m1g-20261020T084933Z`，容器 `rg_m1g`，Domain 69，轮询周期 0.2 s
> 证据：`artifacts/research/m1-graph-dataset/m1g-20261020T084933Z/g2_graph_scenarios/`

## 1. 实验矩阵与实测结果

每个场景独立进程、独立会话，窗口 30 s。下表取第一完整窗口：

| 场景 | 标签 | 消息通道 | 图通道 | `graph_snapshot_transition_count` | 成功轮询 |
| --- | --- | --- | --- | --- | --- |
| G2-01 稳定图 | normal | OK | VALID | **3** | 131 |
| G2-02 节点加入 | normal | INSUFFICIENT | VALID | **3** | 132 |
| G2-03 异常 churn | anomaly | INSUFFICIENT | VALID | **45** | 132 |
| G2-04 端点侦察 | anomaly | INSUFFICIENT | VALID | **14** | 133 |
| G2-05 纯查询侦察 | anomaly | INSUFFICIENT | VALID | **2** | 131 |
| G2-06 合法 500 Hz | normal | OK | VALID | **2** | 131 |
| G2-07 graph-only churn | anomaly | INSUFFICIENT | VALID | **46** | 133 |
| G2-08 极短命端点 | normal | INSUFFICIENT | VALID | **0** | 133 |

## 2. 逐项回答

### 2.1 graph-only 窗口可用（G2-03 / G2-07）

零业务消息时图通道仍给出 45 / 46 次快照变化，而稳定图只有 2–3 次。
**第四轮把这两类攻击整段丢掉的缺陷已修复。**

### 2.2 正常图活动不被误判（G2-01 / G2-02 / G2-06）

稳定、节点加入、合法 500 Hz 三种正常场景的变化数都在 2–3，
与异常 churn 的 45+ 相差一个数量级。**正常图活动不会被当成攻击**。

### 2.3 churn 可观测（G2-03）

45 次变化 / 132 次轮询 ≈ 34% 的轮询观测到拓扑变化。

### 2.4 端点侦察可观测（G2-04）

14 次变化。比 churn 低，因为每 2 秒才新建一个 publisher；
但仍显著高于稳定的 2–3。

### 2.5 纯查询侦察：**不可观测**（G2-05）

只调用 `get_node_names()` / `get_topic_names_and_types()` /
`get_service_names_and_types()`，**不改拓扑** —— 实测 2 次变化，
与稳定场景（2–3）**无法区分**。

判定：**`NOT_OBSERVABLE_WITH_GRAPH_SNAPSHOTS`**。

这条是准确的能力边界，不是失败：纯查询在网络上确实发生了，
但图快照只能看到"拓扑最终状态"，看不到"有人读了它"。
要观测它需要中间件层查询审计或 DDS 权限审计 —— 属于 M2/中间件职责。

**没有**为它插入任何人工特征来"凑出检出"。

### 2.6 极短命端点漏采（G2-08）

每 50 ms 创建并销毁一个带 publisher 的节点，持续 40 s（约 800 次端点变化），
而 0.2 s 轮询只观测到 **0 次**变化。

**这是轮询式快照的硬盲区**：寿命短于轮询周期的端点完全不可见。

## 3. 盲区的准确表述

必须区分四个层次：

| 层次 | 含义 | 本轮状态 |
| --- | --- | --- |
| 实际发生的变化 | 真实 DDS 端点/节点变更 | 由实验进程产生（未直接计数） |
| 快照观察到 | 相邻轮询签名不同 | `graph_snapshot_transition_count` |
| 未观察到的短时变化 | 两次轮询之间生灭 | G2-08 实测：全部漏掉 |
| 采集器异常导致缺失 | 轮询失败 | 计入 `failed_polls`，状态降级 |

`graph_snapshot_transition_count` **不是** DDS Discovery 报文数，
也不是端点事件总数。文档与代码里都用这个名字，避免被读成"事件计数"。

## 4. 轮询间隔的权衡

| 轮询周期 | 可见性 | 代价 |
| --- | --- | --- |
| 0.2 s（本轮） | 捕获 ≥0.2 s 的拓扑变化 | 约 130 次/30 s 窗口，CPU 可忽略 |
| 0.05 s | 捕获更短变化 | 约 600 次/窗口，查询开销上升 |
| 1 s | 只捕获 ≥1 s 的变化 | 开销最低，盲区最大 |

**不能**通过提高轮询频率宣称"能看到所有 DDS Discovery 事件" ——
轮询永远存在窗口间的盲区，只是变短。

## 5. 分级

| 项 | 判定 | 依据 |
| --- | --- | --- |
| `M1_GRAPH_ONLY_OBSERVATION_VERIFIED` | **PASS** | G2-03/07 零消息仍产出有效图特征（45/46 次变化） |
| `M1_NORMAL_GRAPH_ACTIVITY_VERIFIED` | **PASS** | 正常场景 2–3 次，未误判 |
| `M1_CHURN_OBSERVABILITY_VERIFIED` | **PASS** | 45 次 vs 稳定 3 次 |
| `M1_PURE_QUERY_OBSERVABILITY_BOUNDARY_VERIFIED` | **PASS**（边界已确证） | G2-05 实测与稳定场景不可区分 → 明确判为不可观测 |
| `M1_GRAPH_COVERAGE_VERIFIED` | **PASS（有限）** | 0.2 s 轮询下 ≥0.2 s 变化可观测；G2-08 证明更短的漏采 |
