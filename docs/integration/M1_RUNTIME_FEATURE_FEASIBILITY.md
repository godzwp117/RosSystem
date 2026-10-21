# M1 运行时特征可采集性（第二阶段 P1）

| 项 | 值 |
| --- | --- |
| 结论 | 49 维模型输入**无法**在目标环境按等价语义获得；24 维可真实采集 |
| 采集器 | `modules/member1_comm/collector/proc_runtime.py`（Linux `/proc`，无需额外权限） |
| 真实观测 | `docs/integration/evidence/PHASE2_EVIDENCE.json` → `m1_runtime_collection` |
| 可行性矩阵 | `docs/integration/m1_feature_feasibility.json`（49 行逐特征） |
| 子集模型 | `modules/member1_comm/model/comm_risk_model_runtime_subset.json`（24 维，门槛 **FAIL**） |
| 在线检测 | **NOT_READY**（无 ROS 2 运行时、无业务请求计数、模型未过门槛） |

---

## 1. 方法：先证可观测性，再谈模型

按任务要求，本轮**没有**重新盲目训练同一个模型，而是先把特征按"能否真实采到"
分类。分类依据不是名字相似，而是：

1. 数据集自带的 `feature_list.xlsx`（482 个字段，含 `monitor` 列：Tshark / OS Monitor /
   ROS Monitor Node）；
2. 本机实测：`/proc` 逐文件可读性与字段存在性、`ros2`/`tshark`/`tcpdump` 是否存在。

## 2. 结果：49 维的构成

| 分类 | 数量 | 含义 |
| --- | --- | --- |
| `COLLECTABLE_RUNTIME_OK` | **24** | 已实现真实 `/proc` 读取，实测可取到数值 |
| `COLLECTABLE_RUNTIME_MISSING_ON_HOST` | **1** | `pgalloc_dma`：本机 `/proc/vmstat` 无此键（只有 `pgalloc_dma32/normal/movable`） |
| `REQUIRES_PCAP_DISSECTION` | **22** | Wireshark 逐包解剖字段（`layers.*`），需要 pcap + tshark；本环境无 tshark |
| `REQUIRES_ROS_GRAPH` | **2** | `subscribers_count` / `publishers_count`：需要 ROS 2 图内省；本环境无 ROS 2 |

本机环境（写入证据 JSON 的 `environment_probe`）：

```text
ros_available = False          # 没有 /opt/ros，也没有 ros2 可执行文件
tshark        = None           # tcpdump 存在，但只能给原始字节，无法伪造解剖语义
tcpdump       = /usr/bin/tcpdump
kernel        = 6.18.54.1-microsoft-standard-WSL2
/proc 可读     = net/dev, net/snmp, net/tcp, net/tcp6, meminfo, vmstat, diskstats 全部可读
```

## 3. 名称相似 ≠ 特征等价

矩阵里每一行都记录了 `semantic_equivalence: "UNVERIFIED"`。原因：

* 数据集文档只写 "OS Monitor" + 官方文档链接，**没有**写采样周期、单位、
  累计计数器还是窗口增量；
* `Tcp_Established/Listen/TimeWait/Close/Syn` 在数据集里是 5/16/0/0/0 这样的
  **socket 状态计数**，与 `/proc/net/snmp` 的 `ActiveOpens` 等累计量不是同一个量。
  本采集器按 `/proc/net/tcp` 的状态码计数复现（01=ESTABLISHED、06=TIME_WAIT…），
  数值量级一致，但"数据集是否也这样算"仍未证实；
* `Disk_Read/Disk_Write` 采用 `/proc/diskstats` 的 sectors（整盘设备），
  数据集单位未标注。

因此矩阵**不**声称等价，只声称"值可取到，且口径已记录在
`feature_provenance` 里"。

## 4. 采集器实测（REAL_RUNTIME）

```bash
python3 -m modules.member1_comm.collector.emit_observation \
    --duration 1.0 --interval 0.25 --out /tmp/snapshot.json
```

一次真实输出（节选）：

```text
features = 24 / missing = {pgalloc_dma: field absent on this host}
window   = 2026-10-17T17:28:22.466Z .. 2026-10-17T17:28:23.270Z (804 ms, 5 samples)
window_deltas: pgpgin +3348, pgfault +7950, Disk_Read +6696, nr_active_file +856,
               MemFree -7440, Cached +3508 ...
measurement_sha256 = 6e8c7802...（对测量内容做 SHA-256，可复核）
```

"窗口内确有计数器变化"是**判据**，不是装饰：测试
`test_collector_reads_live_proc_counters` 会断言至少一个计数器在窗口内发生偏移，
以排除"读到静态常量却声称在采样"。

## 5. `request_count` 不会被伪造（这一点决定在线可用性）

`f0_runtime.request_count` 是**业务请求数**（ROS 2 Action 触发次数），
不是采样次数、不是报文数、不是 TCP 连接数。没有 ROS 2 运行时就没有这个计数，
因此采集器：

* **不提供** `--request-count` 时，观测块里没有 `f0_runtime`，并写入
  `mapping_blocked.reason`；M1 会以**退出码 4**（`MAPPING_BLOCKED`）失败关闭；
* **提供** `--request-count` 时，观测块带
  `request_count_source: "OPERATOR_DECLARED_CONTROLLED_TEST"`，明确它不是自动采集。

实测：`m1_module_without_request_count.returncode == 4`（证据 JSON）。
这不是缺陷，而是"缺少必要证据就不产出结论"的正确行为。

## 6. 子集模型（OFFLINE_RESEARCH）：结果同样不支持在线检测

只保留 24 维可采集特征，用**同一套审计过的采样**按列投影
（`export_runtime_subset_samples.py`，不重新抽样、不改标签/行号/时间戳）重新训练：

| 指标 | 24 维子集 | 49 维原模型 |
| --- | --- | --- |
| 算法 / 阈值 | ExtraTrees / 0.90 | ExtraTrees / 0.75 |
| 测试集 F1 | **0.0891** | 0.1312 |
| Recall | 0.0466 | 0.0702 |
| Specificity | 1.0000 | 1.0000 |
| Balanced accuracy | 0.5233 | 0.5351 |
| PR-AUC | 0.7526 | 0.7424 |
| 恒预测攻击基线 F1 | 0.8132 | 0.8132 |
| 验证门槛 | **FAIL** | **FAIL** |

另一个必须说清的现象：该模型在验证分片（11/12）上 F1=0.978，在测试分片（13/14）
上 F1=0.089。**同一份离线数据、按文件不相交的划分，验证与测试差距如此之大**，
正好说明"文件分片独立 ≠ 采集会话独立"。任何据此声称泛化的说法都不成立。

用真实 `/proc` 特征驱动这个子集模型（`CONTROLLED_TEST` 的 request_count）：

```text
status = UNKNOWN, score = 0.655（阈值 0.90）, schema 合法
reason = MODEL_NOT_ACCEPTED_OR_UNTRUSTED_OBSERVATION: normal prediction withheld
```

## 7. 为什么仍然不是"在线检测"

| 条件 | 状态 |
| --- | --- |
| 真实 ROS 2 运行时（Jazzy + Fast DDS） | **缺失**（本机无 ROS 2） |
| 业务请求计数（`request_count`） | **缺失**（需 ROS 2 Action 计数） |
| 22 维逐包特征 | **缺失**（需 tshark 解剖；本机无） |
| 2 维 ROS 图特征 | **缺失**（需 ROS 2 图内省） |
| 模型验证门槛 | **FAIL**（两个模型都未通过） |
| 特征语义等价性 | **UNVERIFIED** |

结论：M1 的 `ONLINE_PROCEED_READY` 保持 **FAIL**。本轮新增的是"真实采集器 +
真实缺失证明 + 子集模型的诚实结果"，不是"在线检测能力"。

## 8. 复现命令

```bash
PY=tests/evidence/research-venv/bin/python

# 1) 可行性矩阵（需要数据集文档，不入库）
$PY modules/member1_comm/export_feasibility_matrix.py \
    --xlsx /path/to/ROSPaCe_reduced/feature_list.xlsx \
    --out docs/integration/m1_feature_feasibility.json

# 2) 真实观测
$PY -m modules.member1_comm.collector.emit_observation \
    --duration 1.0 --interval 0.25 --out /tmp/snapshot.json

# 3) 子集训练（需要已审计的采样目录与官方归档）
$PY modules/member1_comm/export_runtime_subset_samples.py \
    --samples data/member1_samples/reduced \
    --features modules/member1_comm/features_runtime_subset.json \
    --out data/member1_samples/reduced_runtime_subset
$PY modules/member1_comm/train.py --samples data/member1_samples/reduced_runtime_subset \
    --output training_runs/member1_runtime_subset

# 4) 相关测试
$PY -m pytest tests/unit/test_member1_runtime_observation.py -q
```
