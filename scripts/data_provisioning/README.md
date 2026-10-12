# 数据集接入环境供应脚本（F0 数据集专项检索配套）

本目录记录 **2026-10-11 数据集专项检索**期间实际验证过的环境供应步骤与探测证据。
所有命令都在项目既有的 `rg_jazzy` 容器（镜像 `ros:jazzy`，`/ws` 挂载仓库根目录）中真实执行过。

> 重要：本目录不含任何数据集原始数据，也不含 Mock 结果。
> 它只记录「读数据需要什么工具」以及「哪些下载通道在本网络下被拒绝」。

---

## 1. 已实际验证的能力（证据）

| 能力 | 状态 | 验证方式 |
| --- | --- | --- |
| ROS 2 Jazzy + `rmw_fastrtps_cpp` | ✅ 可用 | `rg_jazzy` 容器内 `ROS_DISTRO=jazzy`、`RMW_IMPLEMENTATION=rmw_fastrtps_cpp` |
| rosbag2 **MCAP** 写入 | ✅ 可用 | `ros2 bag record -s mcap` 实测生成 `bag3_0.mcap`，118 条消息 / 15.31 s |
| rosbag2 回放 + rclpy 订阅 | ✅ 可用 | `ros2 bag play` + rclpy 订阅实测 39 条消息，提取出频率/间隔字段 |
| PCAP 解析（tshark 4.2.2） | ✅ 可用 | 实际抓取 64 个 RTPS 包并导出字段 |
| RTPS 子消息/实体字段提取 | ✅ 可用 | `rtps.sm.id` / `rtps.guidPrefix.src` / `rtps.sm.wrEntityId` / `rtps.domain_id` |
| python3-scapy 2.5.0 / pandas 2.1.4 | ✅ 可用（经 apt 安装） | `import scapy, pandas` 成功 |
| pip 安装（files.pythonhosted.org） | ❌ 容器内 DNS 解析失败 | `pip install scapy` 报 `Name or service not known` |
| Zenodo 数据集下载 | ❌ 被来源方限流 | 见 §3 |
| figshare 数据集下载 | ❌ 被 AWS WAF 挑战拦截 | 见 §3 |

### 关键结论

- **Python 依赖请走 apt（`python3-scapy` / `python3-pandas`），不要依赖 pip**：本环境下容器内 pip 无法解析
  `files.pythonhosted.org`。apt 通道正常。
- `ros:jazzy` 基础镜像**不含** `demo_nodes_cpp`，也不含 `tcpdump`/`tshark`/`scapy`/`pandas`，需按下节补齐。

---

## 2. 可复现供应步骤

```bash
# 在 rg_jazzy 容器内执行（镜像 ros:jazzy，/ws 挂载仓库）
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
    python3-pip python3-scapy python3-pandas tshark tcpdump sqlite3

# 校验
python3 -c "import scapy, pandas; print(scapy.__version__, pandas.__version__)"
tshark -v | head -1
```

实测版本：`tshark 4.2.2`、`scapy 2.5.0`、`pandas 2.1.4`、`sqlite3 3.45.1`。

### ⚠️ 本次对 `rg_jazzy` 容器所做的实际改动（透明记录）

为完成本次检索的可复现验证，2026-10-11 在项目既有 `rg_jazzy` 容器内执行了以下安装
（均落在**容器可写层**，不影响宿主机，也未覆盖任何已有数据卷）：

| 包 | 版本 | 用途 |
| --- | --- | --- |
| `tshark` | 4.2.2 | PCAP/RTPS 字段解析 |
| `tcpdump` | 4.99.x | 受控抓包验证（仅 lo 回环） |
| `sqlite3` | 3.45.1 | 为 rosbag2 `.db3` 读取做准备 |
| `python3-pip` | 24.0 | 尝试 pip（**失败**，见 §1） |
| `python3-scapy` | 2.5.0 | 报文解析（**仅解析，未发送任何报文**） |
| `python3-pandas` | 2.1.4 | 窗口统计 |

同时创建的临时文件（均在容器 `/tmp` 下，可安全删除）：
`/tmp/rtps_probe/`、`/tmp/rg_bagtest3/`、`/tmp/pub.py`、`/tmp/t.pcap`。

**容器内未启用 SROS 2、未启动任何监听服务、未向外部网络发送任何报文。**

如需回退：
```bash
docker exec rg_jazzy bash -lc "apt-get remove -y tshark tcpdump sqlite3 python3-scapy python3-pandas"
docker exec rg_jazzy bash -lc "rm -rf /tmp/rtps_probe /tmp/rg_bagtest3 /tmp/pub.py /tmp/t.pcap"
```

### ROS 2 侧

```bash
source /opt/ros/jazzy/setup.bash
export ROS_DOMAIN_ID=42          # 与项目基线一致；数据实验建议另开独立 domain
ros2 bag record -s mcap -o <bag_dir> <topic>
ros2 bag info <bag_dir>
ros2 bag play <bag_dir>
```

---

## 3. 本次实际遇到的下载体受限情况（如实记录）

| 来源 | 现象 | HTTP | 证据文件 |
| --- | --- | --- | --- |
| Zenodo 记录 17649537 (`Experiment_1.zip`) | `Access to this resource has been restricted due to unusual traffic from your network` | 403 | `data/access_probes/zenodo_403_experiment1.html` |
| Zenodo REST API (`/api/records/...`) | 同上 | 403 | 同上 |
| figshare (`api.figshare.com`, `springernature.figshare.com`) | `x-amzn-waf-action: challenge` | 403 / 202 | 未落盘（响应体为空） |
| `raw.githubusercontent.com` | `OpenSSL SSL_connect: Connection reset by peer` | — | 未落盘 |

**含义**：这些数据集本身是**公开且免费**的（Zenodo 记录标注 CC BY 4.0）。
上述拦截是**本机网络出口的反自动化策略**，不是数据集访问限制。
需要用浏览器手动下载，或改用有正常出口的机器/代理。

`api.github.com` 在本网络**可用**（用于核验仓库许可证与文件树）。

---

## 4. RTPS → CommRiskEvidence 提取器（`pcap_to_commrisk.py`）

本目录提供可直接运行的转换器，把 RTPS/PCAP 或 HCRL 风格标注 CSV 转成
**符合 `docs/interfaces/schemas/comm_risk_evidence.schema.json` 严格校验**的 JSON。

```bash
# 从 tshark 导出的 TSV 提取（推荐，最快）
python3 scripts/data_provisioning/pcap_to_commrisk.py \
  --tsv data/access_probes/rtps.tsv \
  --resource "/rg/telemetry" --resource-type Topic --operation PUBLISH \
  --baseline-hz 0.167 \
  --schema docs/interfaces/schemas/comm_risk_evidence.schema.json

# 直接从 pcap 提取（内部调用 tshark）
python3 scripts/data_provisioning/pcap_to_commrisk.py --pcap <file>.pcap --resource "<resource>"

# 从 HCRL 风格标注 CSV 提取
python3 scripts/data_provisioning/pcap_to_commrisk.py --labeled-csv <labeled>.csv --time-col Time

# ROSPaCe 精简版：按 ROS 2 话题过滤（src_topic 列直接给出话题名）
python3 scripts/data_provisioning/pcap_to_commrisk.py \
  --labeled-csv ROSPaCe_reduced/rospace_reduced_0.csv \
  --time-col timestamp --resource-col src_topic \
  --resource-filter "/rosout" --resource "/rosout"
```

### 该脚本内建的安全约束（与契约八条边界一致）

| 行为 | 说明 |
| --- | --- |
| 无基线 → `UNKNOWN` | 未提供 `--baseline-hz` 时**不做频率正常性判断**，输出 `UNKNOWN`，**绝不默认放行** |
| 无基线抖动 → 不判抖动 | 未提供 `--baseline-p95-ratio` 时**不对抖动做异常判定**（见下方"两次真实数据修正"） |
| 缺标识列 → 不做重复检测 | 无 `writerEntityId`/`seqNumber` 时**不判定重复调用**，只如实说明未做该检测 |
| 空输入 → `UNKNOWN` | 样本数为 0 时输出 `UNKNOWN`，不输出 `NORMAL` |
| 窗口 > 24 h → `ERROR` | 超过契约上界直接拒绝，不输出失真结论 |
| `frequency_hz` 无法计算时省略 | **不用 0 冒充"无频率"** |
| 间隔统计**不剔除任何观测** | 如实报告 中位数 / p95 / 最大值；不擅自丢弃真实流量形态 |
| 突发流量显式标注 | 若样本成簇到达，声明"Hz 只是窗口均值，不代表稳定速率" |
| `producer.source = EXTERNAL` | 不谎称 MOCK，也不冒充认证来源 |
| `evidence_refs[].kind` 显式传入 | 默认 `CONTROLLED_SECURITY_EXPERIMENT`；自采数据请改 `RUNTIME_LOG` |

### ⚠️ 两次真实数据修正（本工具最重要的设计记录）

早期版本在**合成/自采小样本**上"看起来正常"，一接真实 ROSPaCe 数据就暴露了两个**误报**。
两者都已修正，且修正过程保留在此，供后续开发者判断可信度：

| # | 误报现象 | 根因 | 修正 |
| --- | --- | --- | --- |
| 1 | 一次"剔除"掉 **1056 个间隔**，并把**所有话题**判为 `TIMING_DEVIATION` | 原用"p95/中位数 ≥ 阈值"作为**无基线**判据；成簇发送的话题中位间隔≈0，该比值高达 10⁴，恒超阈值 | ① **不再剔除任何观测**，改为如实报告中位数/p95/最大值；② 抖动判据改为**必须与基线抖动比较**（`--baseline-p95-ratio`），否则只报告不判定 |
| 2 | ROSPaCe 话题被误判为 `DUPLICATE_CALL_PATTERN` | 重复判据依赖 RTPS 标识列；缺列时所有行折叠成同一个空签名，"重复 N 次" | ① 先检查标识列是否存在；② 判据从"总计数"改为**连续相同签名的最大游程**（连续重复才是重放特征） |

**教训（已写入本报告结论）**：无基线的"绝对形态"判据在真实机器人流量上极易误报；
任何异常判定都应当相对于**该话题自身的基线**，且不得为了让指标好看而丢弃真实观测。

### 实测用例（2026-10-11 于 `rg_jazzy` 容器）

| 用例 | 输入 | 期望 | 实测结果 |
| --- | --- | --- | --- |
| T1 | 本机 RTPS 抓包（64 包 / 3000.2 ms），无基线 | 不得判 NORMAL | ✅ 通过 Schema 校验；`SUSPICIOUS`/`DUPLICATE_CALL_PATTERN` —— 依据是**连续相同签名游程 64**（61 个包 `seqNumber=1`），属真实发现 |
| T2 | 同一抓包 + `--baseline-hz 1.0` | 频率异常 | ✅ `REQUEST_RATE_ANOMALY` / `HIGH`（21.0×） |
| T3 | 空 TSV | 不得判 NORMAL | ✅ `UNKNOWN` / `UNKNOWN` / `UNKNOWN` |
| T4 | **真实 ROSPaCe** `/rosout`（15201 样本 / 1.9 h） | 无基线时不得乱判 | ✅ `UNKNOWN`/`UNKNOWN`/`UNKNOWN`，并说明"未做重复检测"与"未对抖动判定" |
| T5 | 真实 ROSPaCe `/mansarda1/image/image_raw`（28525 样本） | 同上 | ✅ `UNKNOWN`/`UNKNOWN`/`UNKNOWN`，`frequency_hz=4.22` |

> T4/T5 的价值在于**没有**输出 `SUSPICIOUS`。修正前它们都被误判为异常——
> 一个在正常数据上乱报警的检测器，在报告里比"无结论"更糟糕。

### 使用限制（必须遵守）

- **不得**用它为公开数据集编造"已认证身份"结论；脚本只输出通信统计，不输出身份认证结果。
- `--resource` 必须如实填写。RTPS 抓包**不含 ROS 2 话题名**，若无法确定资源名，
  应填 DDS 端点标识并在报告中说明，**不得**伪造成 `/rg/guarded_navigate`。

---

## 5. ROSPaCe 窗口化脚本（`rospace_windows.py`）

ROSPaCe 的采集结构是「30 s 正常 → 攻击 ≤60 s → 10 s 恢复」交替 400 次。
**直接对整个 CSV 做统计会得到一个跨数小时的巨大窗口，结论没有意义**
（实测：`/rosout` 的 p95/中位数 高达 15668，任何话题都会被误判）。
正确单位是 **block（正常段 + 紧随的攻击段）**，这也与作者 `usage_note_B` 的划分方式一致。

```bash
python3 scripts/data_provisioning/rospace_windows.py \
  --csv data/ROSPaCe_reduced/ROSPaCe_reduced/rospace_reduced_0.csv \
  --out data/ROSPaCe_reduced/windows_0.jsonl \
  --min-gap-s 20
```

**实测结果**（`rospace_reduced_0.csv`）：

| 项 | 数值 |
| --- | --- |
| 解析样本 | 1,746,677 行（跳过 0） |
| 采集段 | 10 段（间隔 > 20 s 切分） |
| block | **918 个，全部单一标签** |
| 窗口记录 | 22,591 条 → `windows_0.jsonl`（14 MB） |
| 首个 `observe` block | **29.97 s**（与论文 30 s 设计吻合） |
| 超过契约 24 h 上界 | **0** |

输出字段：`segment_index` / `block_index` / `source_label` / `communication` /
`window` / `request_count` / `frequency_hz` / `gap_median_ms` / `gap_p95_ms` /
`gap_max_ms` / `_provenance`。

> **`source_label` 是数据源原生标签**，不是本项目的安全结论。脚本只做划分与统计，
> **不做异常判定**——异常判定请另行基于基线执行（见 §4 的 `--baseline-hz` 等参数）。

---

## 6. RTPS → CommRiskEvidence 手工提取片段（已实测）

```bash
# 1) 抓包（容器内，需要 cap_net_raw；无需 cap_net_admin 即可抓 lo）
tcpdump -i lo -U -w rtps.pcap udp

# 2) 导出字段（注意：多值字段必须用 tab 分隔，否则会与逗号冲突产生空 CSV）
tshark -r rtps.pcap -Y rtps -T fields -E header=y -E separator=/t -E occurrence=a \
  -e frame.number -e frame.time_epoch -e frame.len -e ip.src -e ip.dst \
  -e rtps.sm.id -e rtps.guidPrefix.src -e rtps.sm.wrEntityId \
  -e rtps.sm.seqNumber -e rtps.domain_id > rtps.tsv
```

实测输出（25 Hz 发布者，3 秒窗口）：

```json
{"rows": 64, "request_count": 64, "window_duration_ms": 3000.2,
 "frequency_hz": 20.999, "mean_gap_ms": 47.62, "max_gap_ms": 3000.02}
```

可直接映射到 `CommRiskEvidence.window.duration_ms` / `.request_count` / `.frequency_hz`。

### 身份字段的**可信性边界**（必须写进报告）

`rtps.guidPrefix.src` 与 `rtps.sm.wrEntityId` 是**线路上可观察的 DDS 端点标识**，
不是 DDS-Security 认证结论。因此：

- 这些字段只能作为 `subject.observed_name` 类观察值；
- **不得**用于填写 `subject.authenticated_identity`；
- 缺少访问控制日志时，`identity_evidence.kind` 只能是 `UNKNOWN` 或 `MOCK`，
  不能标 `DDS_ACCESS_CONTROL_LOG`。

---

## 7. 与项目契约的一致性

本目录的结论遵循 `docs/interfaces/CONTRACT_VERSION.md` 的八条强制安全边界，特别是：
规则一（自报字段不是认证凭据）、规则六（证据可信性分级）。
