# RosSystem 公开数据集专项检索与选型报告

**面向具身智能机器人多模态感知、ROS 2 通信安全与攻击检测**

| 项 | 值 |
| --- | --- |
| 报告类型 | 公开数据集调研与选型（可立即开展研发） |
| 检索与核验日期 | 2026-10-11 |
| 项目 | 面向具身智能机器人的 ROS 2 通信可信分析与动态最小权限防护系统 |
| 仓库 | https://github.com/godzwp117/RosSystem |
| 分支 | `feature/framework-f0` |
| **本次检索起始锚点 SHA** | **`9c4bcf7316a5c06e380e2d1752952878891b962b`** |
| **本报告定稿时仓库 HEAD** | **`4664b978a846f0c5c3619a52fecf37ac2f1c519c`** |
| 契约状态 | `PROPOSED_V1` / `1.0.0-proposed`（**未冻结**） |
| 离线依赖 | 无。本报告全部结论基于 2026-10-11 的实际联网访问与本地实测 |

> **关于 HEAD 变化（如实说明）**：本次检索开始时仓库 HEAD 为 `9c4bcf7`（该提交本身已在任务书所列
> F0 提交 `e3d3004` 之后）。检索过程中 HEAD 前进到 `4664b97`
> （`fix(f0): harden T14 docker lifecycle and audit assertions`），
> 该提交仅修改 `tests/integration/team_handoff_check.py`，**不涉及数据集、接口 Schema 或 TaskPolicy**。
> 因此本报告的接口映射结论对两个 SHA 均成立。引用时请以 `4664b97` 为准并注明本次检索锚点。

---

## 执行摘要（先读这一页）

**一句话结论**：公开的 **ROS 2 原生攻击数据极其稀缺但确实存在**；
本项目应采用「**2 个小型 ROS 2 原生数据 + 2 个逐包/逐流真值数据 + 本项目 SROS 2 受控实验**」的组合，
**约 380 MB 即可在 24 小时内起步**；而**身份权限证据只能自建，公开数据完全无法提供**。

### 三个最重要的发现

1. **真正可用的 ROS 2/DDS 攻击数据只有 4 个**，且各有硬伤：
   - **UNILEON**（Zenodo 17649537）：唯一 **rosbag2 原生** + **通信攻击与感知替换兼具**，但仅 5 个 run；
   - **HCRL RTPS**：唯一**逐包真值**、真实 Fast-DDS 环境，但无 ROS 话题语义；
   - **ROSPaCe**：唯一**逐行标签 + 6 类攻击**、许可最宽松（**数据 CC0**），但完整版 37.5 GB；
   - **RESILMESH**：唯一明确以 **RTPS `:7400`** 为目标的 ROS 2 DDS 注入，但仅 1 条攻击。

2. **两个高频误判陷阱（本报告已排除）**：
   - **ROSIDS23 是 ROS 1，不是 ROS 2**（论文原文受害网络含 "a **ROS master**"，ROS 2 无此组件）。
     它的价值在"未授权发布/订阅"标签，但**必须标注为 ROS 1**；
   - **GRIFFIN UAS 的 "intrusion monitoring" 指监控入侵的人**，与网络入侵检测无关。

3. **方向 C 是硬缺口**：**不存在任何公开的 SROS 2 / DDS-Security 访问控制日志数据集**
   （已用 DataCite / GitHub / Zenodo 系统检索确认）。
   公开数据里所有 IP/MAC/GUID **都不是 DDS 已认证身份**。
   → `IdentityTrustAssessment` 与 `TaskRiskDecision` 的标签**只能由本项目受控实验生成**。
   最新研究（[arXiv:2511.00140](https://arxiv.org/abs/2511.00140)，IEEE MILCOM 2025）
   进一步证明：**SROS 2 凭据一旦被窃取，攻击者就是"合法已认证主体"，认证层不会报警**——
   这既是本项目"认证之上还需行为与任务分析"的最强立项依据，
   也说明该类证据**在原理上不可能来自公开数据集**。

### 最小可用方案（24～48 小时）

| 顺序 | 数据 | 体积 | 许可 | 用途 |
| --- | --- | ---: | --- | --- |
| ① | UNILEON `Experiment_1.zip` | 1.6 MB | CC BY 4.0 | rosbag2 读取链路 + `cmd_vel` 500 Hz 频率异常 |
| ② | ROSIDS23 `processed.zip` | 93.4 MB | CC BY 4.0 | `UNEXPECTED_RESOURCE_ACCESS`（未授权发布/订阅） |
| ③ | HCRL `RTPS_ATTACK_DATASET.zip` | 284.13 MB | **CC BY-NC** | RTPS 逐包真值 + ARP 身份冒用 |
| ④ | 本项目 SROS 2 + Gateway + NavigationSim | 0 | 项目自有 | **补齐全部身份权限与任务风险证据** |

**合计约 380 MB**。已实测验证的读取链路：`ros2 bag`（MCAP 写入/回放）、`tshark`（RTPS 字段提取）、
`scapy`/`pandas`（统计），以及一个**已通过项目 Schema 严格校验**的
`PCAP → CommRiskEvidence` 转换器（见 `scripts/data_provisioning/`）。

### 必须在报告与答辩中守住的三条底线

1. **不得**把公开数据集的 IP/MAC/GUID 说成"已通过 DDS 认证的身份"；
2. **不得**把 ROS 1 数据（ROSIDS23、GRIFFIN）说成 ROS 2 原生数据；
3. **不得**把正常多模态数据说成"攻击检测数据集"，也**不得**把 PCAP 与无关视频拼接成"同步攻击数据"。

---

## A. 大赛与项目背景

### A.1 大赛信息（已逐条联网核实）

| 字段 | 核实结果 | 来源 |
| --- | --- | --- |
| 大赛全称 | 「华为杯」第五届中国研究生网络安全创新大赛 | [官方邀请函](https://cpipc.acge.org.cn/cw/contestNews/detail/2c90800c8093eef401809d33b36f0652/2c9080199ed8b78d019ed96ceea21560?page=0) |
| 所属系列 | 中国研究生创新实践系列大赛（主题赛事之一） | 同上 |
| 指导单位 | 教育部学位管理与研究生教育司 | 同上 |
| 主办单位 | 中国学位与研究生教育学会 | 同上 |
| 承办单位 | 哈尔滨工业大学、哈尔滨丁香人才发展（集团）有限公司 | 同上 |
| 赛事主题 | **智融攻防，实战育才**（已核实一致） | [赛事介绍](https://cpipc.acge.org.cn/cw/contestIntrol/2c90800c8093eef401809d33b36f0652) |
| 报名时间 | 2026-06-18 至 2026-10-18 23:59 | 官方邀请函 |
| **作品提交截止** | **2026-10-22**（已核实一致） | 官方邀请函 + [官方赛程表](https://cpipc.acge.org.cn/pw/notice/detail/2c9080179e403028019e484cf50210a6?page=0) |
| 决赛 | 拟 2026-12-26 至 27，哈尔滨市南岗区 | 同上 |

**创意作品赛方向**（官方原文）："参赛队伍聚焦密码学、系统安全、网络安全、应用安全、内容安全、智能安全等网络空间安全相关领域方向"。注意这是**选题方向范围**，大赛层面只划分三个赛道（揭榜挑战赛、创意作品赛、实网对抗赛）。

**作品形式**：作品文档资料（PDF，≤10 MB）+ 可执行程序；文档含作品简介、设计方案、测试报告、其他文档、参赛作品声明。

### A.2 三处必须修正的任务书描述（据官方原文）

| # | 任务书表述 | 官方实际 | 影响 |
| --- | --- | --- | --- |
| 1 | 评审要点含"**安全意义**" | 官方初赛评审为 **5 项**：原创性与创新性、作品完成程度、作品的性能、作品的应用价值、相关文档的规范性。**无"安全意义"独立评分项** | 报告与答辩不要把它写成评分项；改述为"只接受防御性题目、不违反法律法规"的**参赛约束** |
| 2 | 评审要点含"**测试验证**" | 非独立评审项；但"测试报告"是**必交文档**，决赛含"演示、测试与专家提问（**将现场检查源代码**）" | 测试证据仍必须做，但定位为必交材料 + 决赛现场环节 |
| 3 | 作品形式"技术文档、测试报告" | 基本吻合，但官方另有**硬性匿名要求**：作品正文、展示材料及说明文档**不得出现学校、学院、导师**等影响公平的信息 | **遗漏项，违者取消资格**，务必检查 |

**关于数据合规**：官方邀请函全文对"数据""数据集""伦理""隐私""个人信息"**零命中**。
即**官方通知未就"能否使用公开数据集"作明文规定**。可依据的一般性约束为：
"本赛事只接受防御性的题目"、"无侵害他人合法权益行为"、"原创性作品、无知识产权纠纷"。
（任务书引用的《参赛指南》第五届公开正文未能取得，故不据此下结论。）

> **行动建议**：由于赛事**只接受防御性题目**且要求作品原创，本项目使用公开数据集时必须
> ①在文档中明确标注数据来源与许可证；②**不得**声称对第三方真实系统实施过攻击；
> ③所有攻击数据要么来自已公开的受控实验数据集，要么来自本项目自有环境的受控实验。

### A.3 当前 F0 研发状态（本地核实）

已核实的既有能力（仓库记录，非本次新增实验）：

- ROS 2 Action 基础执行链路、Gateway 应用层准入、静态 TaskPolicy；
- M1 可靠性增强、M2 SROS 2 Enforce 权限验证、多成员隔离开发环境；
- 四份公共 JSON Schema（`module_input` / `comm_risk_evidence` / `identity_trust_assessment` / `task_risk_decision`）；
- F0-T01～T15 验收 15/15 PASS、Python 单元测试 295 项通过、SROS 2 Enforce 对照 7/7 PASS；
- 接口契约状态 **`PROPOSED_V1`（尚未冻结）**，M3 动态任务状态机**不在 F0 范围内**。

已核实的本地安全资产（对方向 C 至关重要）：

| 资产 | 路径 | 内容 |
| --- | --- | --- |
| 权威任务策略 | `config/task_policy.yaml` | `task_id: patrol_a_001`、`allowed_region: x∈[0,4] y∈[0,4]`、`coordinate_frame: map`、`max_requests_per_minute: 10` |
| SROS 2 治理文件 | `security/keystore/enclaves/governance.xml` | domain **43**、`allow_unauthenticated_participants: false`、`enable_join_access_control: true`、`rtps_protection_kind: SIGN`、数据/元数据 `ENCRYPT` |
| SROS 2 权限文件 | `security/keystore/enclaves/*/permissions.xml` | 6 个 enclave：`planner` / `gateway` / `navsim` / `operator` / `task_admin` / `unauthorized`，均为 `<default>DENY</default>` |

`max_requests_per_minute: 10` 与 `governance.xml` 的访问控制配置，是本次数据集映射中
**唯一可作为"权威基线"的来源**——这一点决定了后面 `CommRiskEvidence` 的判据不能凭空设定。

### A.4 为什么需要公开数据集

当前三个研究模块主要使用 Mock 与测试替身。要形成可复现、可被评委核查的安全效果证据，必须引入
**来源合法、格式可读、标签可追溯**的真实数据。本次检索的目标不是"找大牌数据集"，而是回答：

1. 是否存在**真实的 ROS 2 / DDS 攻击数据**？（方向 A，最高优先级）
2. 哪些**多模态机器人数据**能承载"感知异常诱导危险动作"的场景？（方向 B）
3. **DDS 身份权限证据**能否从公开数据获得？（方向 C —— 本报告给出明确否定结论）

---

## B. 检索来源与方法

### B.1 检索平台

| 平台 | 本网络可达性（2026-10-11 实测） | 用途 |
| --- | --- | --- |
| `cpipc.acge.org.cn`（大赛官网） | ✅ 可达，无需登录 | 赛事信息核实、官方附件下载 |
| `api.github.com` | ✅ 可达 | 仓库许可证、文件树、README 原文核验 |
| `raw.githubusercontent.com` | ❌ `SSL_connect: Connection reset by peer` | 无法取 raw 文件 |
| `zenodo.org`（记录页/HTML） | ✅ 可达（页面完整渲染） | 数据集元数据、文件清单、许可证核验 |
| `zenodo.org`（`curl` 命令行访问） | ❌ HTTP 403 "unusual traffic" | **仅影响自动化抓取；浏览器访问正常** |
| `zenodo.org`（REST API / 文件下载） | ❌ HTTP 403 "unusual traffic" | **无法自动下载数据文件** |
| `springernature.figshare.com` / `api.figshare.com` | ❌ AWS WAF `challenge`（403/202） | **无法自动下载数据** |
| `huggingface.co` | ❌ 连接超时 | 相关候选只能标注"未能从本网络核验" |
| `ocslab.hksecurity.net`（HCRL） | ✅ 可达 | RTPS 攻击数据集说明页 |
| `ieee-dataport.org` | ✅ 可达 | RTPS 攻击数据集条目、说明与标签字段 |
| `pmc.ncbi.nlm.nih.gov` / `nature.com` | ✅ 可达 | ROSPaCe 论文全文、数据可用性、许可证 |
| `ar5iv.labs.arxiv.org` / `export.arxiv.org` | ✅ 可达 | 数据集配套论文原文 |
| `unb.ca` | ✅ 可达 | CIC-IDS2017 |
| `trust-cps.org` | ❌ DNS 无法解析 | MSU ICS 数据集需另找入口 |
| Docker Hub | ✅ 可达 | `ros:jazzy` 镜像与 apt 供应 |

### B.2 检索词（中英并用）

方向 A：`ROS2 cybersecurity dataset`、`ROS 2 intrusion detection dataset`、`ROS2 attack traffic dataset`、
`DDS RTPS intrusion detection dataset`、`RTPS + malicious traffic`、`DDS + intrusion detection`、
`ROS2 + PCAP`、`SROS2 permissions security experiment dataset`、`robotics + security + rosbag`、
`ROS2 malicious topic dataset`、`ROS2 rosbag security anomaly`。

方向 B：`robotics multimodal anomaly detection dataset`、`robot RGB-D LiDAR IMU dataset`、
`robot perception attack dataset`、`embodied AI attack detection dataset`、`robot action anomaly dataset`、
`rosbag2 dataset download`、`MCAP dataset robotics`、`ROS bag multimodal perception benchmark`。

方向 C：`DDS-Security access control logs dataset`、`industrial robot cybersecurity dataset`、
`cyber physical system intrusion detection dataset`、`robot control command anomaly dataset`、
`robot navigation + anomalous commands`、`工业机器人 网络安全 数据集`、`ROS 2 安全 数据集`。

### B.3 候选筛选规则（硬性）

1. **必须实际访问**介绍页与下载页；二者分开记录，**不得把论文链接当作下载链接**。
2. 必须能确认**实际文件格式**（rosbag2 / MCAP / PCAP / CSV / 图像 / 点云）；不凭摘要推断。
3. 必须区分**原生标签** / **可推导标签** / **需自行补充**。
4. 许可证找不到就标 `LICENSE_UNVERIFIED`；访问受限就标 `ACCESS_RESTRICTED`。
5. 明确 ROS 1 与 ROS 2 的界限；**不得**把 ROS 1 数据称为 ROS 2 原生数据。
6. **不得**把普通网络入侵流量称为 ROS 2 攻击数据。

### B.4 失效链接与排除原因（如实记录）

| 候选 | 现象 | 结论 |
| --- | --- | --- |
| `raw.githubusercontent.com` 上的 ROS 2 测试 bag | 连接被重置 | 改用本地录制验证 |
| `www.trust-cps.org/datasets/` | DNS 无法解析 | MSU ICS 数据集未取得可用下载入口，**不作为推荐** |
| `portalcientifico.unileon.es` 上的 Zenodo 链接 | 门户可达，Zenodo 下载被 403 | 数据集**真实且许可明确**，但需人工浏览器下载 |
| Hugging Face 相关候选（`ClarusC64/robotics-command-actuation-coherence-loss-v0.1`、`LaelaZ/vla-action-anomaly-eval`） | `huggingface.co` 连接超时 | 仅由搜索引擎摘要可见，**未能核验**，不列入评分表正式名次 |
| `springernature.figshare.com` ROSPaCe 页面 | WAF challenge，HTML 为空 | 数据集真实（论文与 DOI 可核实），但许可证需人工确认 |
| `www.mdpi.com/2079-9292/15/12/2707` | 返回空白 | 未能核验其 Zenodo 数据 |

---

## C. 数据集候选总表

> 评分方法见 §C.2。全部链接均在 2026-10-11 实际访问过。
> `LICENSE_UNVERIFIED` = 未能从可访问来源确认许可证；`ACCESS_RESTRICTED` = 本网络出口被限流。

### C.1 方向 A：ROS 2 / DDS 通信攻击数据

| 数据集 | 来源机构 | 数据类型 | 攻击标签 | 机器人场景 | 下载链接 | 许可证 | 匹配分数 | 优先级 |
| --- | --- | --- | --- | --- | --- | --- | ---: | --- |
| **HCRL RTPS Attack Dataset** | 高丽大学 Hacking and Countermeasure Research Lab | `.pcap`（机器人侧 + 攻击者侧）+ 标注 `.csv`（压缩包 **284.13 MB**） | 原生逐包 0/1：Command Injection(Flooding/Fuzzing)、ARP Spoofing | 真实 UGV（Stella N1，ROS 2 Foxy + **Fast-DDS**），含 LiDAR/AHRS | [数据说明](https://ocslab.hksecurity.net/Datasets/rtps-attack-dataset) · [IEEE DataPort 条目](https://ieee-dataport.org/documents/real-time-publish-subscribe-attack-dataset) · [论文 arXiv:2311.14496](https://arxiv.org/abs/2311.14496) | **CC BY-NC 4.0**（页面原文 "academic and non-commercial purposes only"）；**IEEE 版需订阅付费**（口径冲突） | **91** | **P0** |
| **ROSPaCe** (ROSpace) | 特伦托大学等（Puccetti 等） | 合并 CSV（网络 452 + OS 25 + ROS 2 5 特征）+ **独立 pcap 包** + feature_list.xlsx | 原生逐行：Nmap Discovery、ROS2 Reconnaissance、Flooding Meta、Flooding Nmap、ROS2 Node Crashing、ROS2 Reflection | 真实 CPS（有轨电车车载 ROS 2 Foxy + 摄像头） | [complete 40.2 GB](https://springernature.figshare.com/articles/dataset/ROSPaCe_complete/25594347) · [reduced 0.92 GB](https://springernature.figshare.com/articles/dataset/ROSPaCe_reduced/25594860) · [tshark_pcaps 6.4 GB](https://springernature.figshare.com/articles/dataset/tshark_pcaps/25605789) · [论文 DOI](https://doi.org/10.1038/s41597-024-03311-2) · [代码](https://github.com/tommasopuccetti/rospace_dataset) | **数据条目 CC0 1.0；集合与论文 CC BY 4.0；代码 GPL-3.0（已核验）** | **86** | **P1** |
| **Simulated attacks Rosbags against mobile robot in ROS 2** | 莱昂大学 Robotics Group（TESCAC 项目） | **rosbag2**（`Experiment_1.zip` 1.6 MB + `Experiment_2.zip` 3.1 GB） | 整段运行级：`/input_joy/cmd_vel` 500 Hz 洪泛 DoS；车载相机图像替换 | **移动机器人**，含相机图像 + VLM 文本描述 | [Zenodo 记录 17649537](https://zenodo.org/records/17649537) · [DOI](https://doi.org/10.5281/zenodo.17649537) | **CC BY 4.0（已核验）** | **91** | **P0** |
| **ROSIDS23** | 埃斯基谢希尔奥斯曼加齐大学 IFARLab-DIH | pcap + CICFlowMeter CSV（83 特征） | 原生多分类 5 类：benign、DoS、**unauthorized publish**、**unauthorized subscribe**、subscriber flood | ⚠️ **ROS 1**（论文原文含 "a **ROS master**"），机器人臂 + 控制器 | [Zenodo 10014434](https://zenodo.org/records/10014434) · [论文 DOI](https://doi.org/10.1016/j.dib.2023.109739) | **CC BY 4.0（已核验）** | **80** | **P1** |
| **RESILMESH – ALIAS – Pilot2 – 40min & 8 attacks** | Resilmesh（EU GA 101119681），P. Zabalegui | pcap（`ros2_foxy.pcap` 729.6 MB 等）+ SNMP/坐标 CSV + 攻击时间线 | 攻击时间窗（非逐包）：含 **ROS2 DDS Injection（目标 `:7400` RTPS）**、ROS Bridge DoS、ROS Parameter Hijacking、ROS1 XML-RPC 等 8 种 | ROS 2 Foxy 容器 + ROS 1 Noetic + OpenPLC + UR 仿真 | [Zenodo 20729823](https://zenodo.org/records/20729823) | **CC BY 4.0（已核验）** | **76** | **P1** |
| Robot Hacking Manual (RHM) | Gh0stlyKn1ght（社区） | 攻击脚本（Scapy），非数据集 | 不适用（工具） | ROS 2 / ROS 1 | [GitHub](https://github.com/Gh0stlyKn1ght/robot_hacking_manual) | 需逐仓库确认 | —（工具，不计分） | 参考 |
| **SROS 2 keystore 窃取后冒名注入（论文，非数据集）** | 田纳西理工大学（Sakib 等），IEEE MILCOM 2025 | 论文（**未公开数据集**）：描述攻击方法与后果 | **无数据集**；攻击类型：控制话题注入、感知话题欺骗 | Quanser **QCar2** 自动驾驶平台 + Intel RealSense，四停车标志导航 | [arXiv:2511.00140](https://arxiv.org/abs/2511.00140) | 论文 **CC BY-NC-ND 4.0** | —（方法学参考） | **P0（实验设计参考）** |
| 本项目 SROS 2 keystore + TaskPolicy | 本项目 | XML 权限/治理 + YAML 策略 | 授权规则（非攻击数据） | 本项目 NavigationSim | `security/keystore/` · `config/task_policy.yaml` | 项目自有 | —（基线） | P0（配套） |

### C.2 方向 B：机器人多模态感知与 rosbag2 数据

| 数据集 | 来源机构 | 数据类型 | 攻击标签 | 机器人场景 | 下载链接 | 许可证 | 匹配分数 | 优先级 |
| --- | --- | --- | --- | --- | --- | --- | ---: | --- |
| **ROS2 Multi-Modal Windrow Detection Dataset** | 莱比锡大学 | **MCAP（ROS 2 Humble 原生）**：Ouster OS0-128 LiDAR、ZED 2i 双目、GNSS+IMU、5 路单目 | 无（正常数据） | 农业拖拉机真实作业 | [Zenodo 17486318](https://zenodo.org/records/17486318) | **CC BY 4.0（已核验）** | **72** | P1 |
| TUM RGB-D Benchmark | 慕尼黑工业大学 | RGB-D 图像序列（`.tgz`）+ **ROS 1 `.bag`**（下载页实测 141 处 `.bag` 引用）+ 位姿轨迹 `.txt` | 无 | 室内 SLAM/感知 | [官网](https://cvg.cit.tum.de/data/datasets/rgbd-dataset) · [下载页](https://cvg.cit.tum.de/data/datasets/rgbd-dataset/download) | **CC BY 4.0（已核验：数据 CC BY 4.0，代码 BSD-2-Clause）** | **60** | P2 |
| Hilti SLAM Challenge 2022 | Hilti / Trimble | **rosbag**（逐序列 10–34 GB，共约 200 GB） | 无 | 工地巡检（含多层/楼梯/长走廊） | [2022 数据集](https://hilti-challenge.com/dataset-2022) | **CC BY-NC-SA 3.0（已核验，禁商用）** | **58** | P2 |
| KITTI Vision Benchmark | KIT + TTI-C | 图像、LiDAR 点云、IMU/GPS、标定（非 rosbag） | 无 | 自动驾驶 | [官网](https://www.cvlibs.net/datasets/kitti/) | **CC BY-NC-SA 3.0（已核验，禁商用）** | **52** | P3 |
| DARPA Subterranean Challenge | DARPA / 多机构 | rosbag 系列 | 无 | 地下探索机器人 | [CTU-MRS 镜像](https://github.com/ctu-mrs/slam_datasets) | 见仓库条款（**未能核实**） | **待核验** | P2 |
| Open X-Embodiment / BridgeData V2 | 多机构联合 | RLDS（**非 rosbag**） | 无 | 机械臂操作 | [OXE 页面](https://robotics-transformer-x.github.io/) | 见官网（**未能核实**） | **待核验** | P3 |
| nuScenes | Motional | 图像、LiDAR、雷达（**非 rosbag**） | 无 | 自动驾驶 | [官网](https://www.nuscenes.org/) | 需接受条款（**未能核实**） | **待核验** | P3 |
| event-based intruder monitoring UAS (GRIFFIN) | 塞维利亚大学 | **ROS 1 `.bag`**（事件相机 + 帧 + IMU） | 无（"intruder" 是监控目标，非网络攻击标签） | 无人机监控 | [Zenodo 3929689](https://zenodo.org/records/3929689) | 见 Zenodo 记录（Open） | **38** | P3 |

> **"待核验"含义**：这 3 项已确认**数据集真实存在且页面可访问**，但其**许可证条款**与
> **精确文件格式**因本网络限制（HuggingFace 超时、`raw.githubusercontent` 重置）
> **未能逐条核实**，因此**不给分数、不列入推荐方案**。若后续需要，
> 请在可正常访问的网络上补齐核验后再评估。

> ⚠️ **重要澄清 1**：GRIFFIN 数据集标题中的 "intrusion monitoring" 指**用事件相机监控入侵者（人）**，
> **与网络入侵检测毫无关系**。若因名称相关而列入"入侵检测数据"，属于典型误判。故仅给 38 分。
>
> ⚠️ **重要澄清 2**：**TUM RGB-D 确实提供 `.bag` 文件**（下载页实测），但其 bag 是
> **ROS 1 时代的 bag**，**不能直接当作 ROS 2 原生数据**；若要接入需经 rosbag v1→v2 转换。
> 其许可证已核验为 **CC BY 4.0**（数据部分），是本方向中许可最宽松的大规模 RGB-D 数据。
>
> ⚠️ **重要澄清 3**：Hilti 与 KITTI 均为 **CC BY-NC-SA 3.0（禁商用 + 相同方式共享）**，
> 若作品含商业转化预期需谨慎；且 **Hilti 单序列 10–34 GB**，不适合 24 小时落地。

### C.3 方向 C：DDS 身份权限 / 工业网络访问异常

| 数据集 | 来源机构 | 数据类型 | 攻击标签 | 机器人场景 | 下载链接 | 许可证 | 匹配分数 | 优先级 |
| --- | --- | --- | --- | --- | --- | --- | ---: | --- |
| SROS 2 `permissions.xml` / `governance.xml` 样本 | 本项目 + [ros2/sros2](https://github.com/ros2/sros2)（**Apache-2.0**）+ [OpenDDS](https://github.com/OpenDDS/OpenDDS) | XML 权限/治理配置（**配置文件，非日志**） | 无 | ROS 2 原生 | `security/keystore/`；`ros2/sros2` 的 `sros2/test/policies/permissions/{add_two_ints,minimal_action,sample,single_context,talker_listener}/permissions.xml` | Apache-2.0（sros2） | —（配置样本） | **P0（方向 C 唯一可用基线）** |
| **DDS-Security / SROS 2 访问控制日志数据集** | — | — | — | — | **经系统检索未发现任何公开数据集**（详见 §J.2） | 不适用 | **0（不存在）** | **不存在** |
| CIC-IDS2017 | 加拿大网络安全研究所 (UNB) | PCAP + 流特征 CSV | 原生：多类通用网络攻击 | 无 | [官网](https://www.unb.ca/cic/datasets/ids-2017.html) | 见官网使用条款（**未能逐条核验**） | **38** | P2（仅对照） |
| CIC-IDS2018 | UNB | PCAP + CSV | 原生：多类 | 无 | [官网](https://www.unb.ca/cic/datasets/ids-2018.html) | 见官网 | **38** | P2（仅对照） |
| SWaT / WADI / EPIC | SUTD iTrust | 工控过程数据 + 攻击标签 | 原生：工控攻击 | 无（水处理/配水/电力） | [iTrust 数据集页](https://www.sutd.edu.sg/itrust/itrust-labs/datasets/) · [使用条款](https://www.sutd.edu.sg/itrust/itrust-labs/datasets/terms-of-usage/) | **需提交申请**（官方原文：*"Users are welcome to requests for datasets… We may take up to three working days to process your request"*） | **26** | P3 |
| TON_IoT | UNSW 堪培拉 (ADFA) | **pcap + Zeek 日志 + CSV**（含 IoT/IIoT 遥测、Modbus 传感器、Linux 审计） | 原生：多类 IoT/IIoT 攻击，四类数据集均含 standard features + label | 无 | [UNSW TON_IoT 页](https://research.unsw.edu.au/projects/toniot-datasets) | 见官网条款（**未能逐条核验**） | **34** | P3 |
| Bot-IoT | UNSW 堪培拉 (ADFA) | **pcap + Argus + CSV**（按攻击类别分层，便于标注） | 原生：botnet/正常流量 | 无 | [UNSW Bot-IoT 页](https://research.unsw.edu.au/projects/bot-iot-dataset) | 见官网条款（未能逐条核验） | **30** | P3 |
| MSU ICS (Power/Gas Pipeline) | 密西西比州立大学 | PCAP | 原生：工控攻击 | 无 | `www.trust-cps.org` **DNS 无法解析**；未见可用入口 | 未能核实 | **未能核实** | P3 |
| Edge-IIoTset / X-IIoTID | 多机构 | PCAP / CSV | 原生：IoT 攻击 | 无 | 见 IEEE DataPort 等 | 见各站条款（未能核验） | **约 30** | P3 |

> **iTrust 申请的隐私代价（需注意）**：官方条款原文要求
> *"By requesting for and receiving the dataset, you agree to: have your and your organisation's name
> and the date of request published on this website"* —— 即**申请人姓名与单位名称会被公开**。
> 若团队成员不希望个人信息被公开列出，请勿提交申请。加上"最多 3 个工作日"的审批周期，
> **不建议在本次赛期内投入**。

**方向 C 的核心结论**：以上工业/IoT 入侵检测数据**全部不含 DDS 语义**，
仅能作为"算法迁移对照"。**方向 C 真正可用的只有本项目自有的 SROS 2 权限与治理配置**（见本表第 1 行）。

> 评分示例（CIC-IDS2017 = 38）：ROS 2/DDS 匹配 0/25（**完全不是 ROS 2 数据**）、
> 真实攻击标签 18/20、机器人场景 0/15、可访问性与许可 10/15、转换成本 5/10、
> 质量与文档 10/10、小样本快速验证 5/5。**ROS 2 匹配为 0 是它不能进主线方案的根本原因**，
> 尽管它在其他维度得分不低。

### C.4 评分方法与扣分依据

满分 100，按任务书权重：ROS 2/DDS 匹配 25、真实攻击标签 20、机器人多模态/任务适配 15、
可访问性与许可 15、转换成本 10、质量与文档 10、小样本快速验证 5。

**HCRL RTPS Attack Dataset = 91**

| 指标 | 得分 | 扣分依据 |
| --- | ---: | --- |
| ROS 2/DDS 匹配 | 23/25 | 真实 ROS 2 Foxy + **Fast-DDS**、真实 RTPS 包。**扣 2**：仅 DDS 线路层语义，**无 ROS 2 话题名/Service/Action 语义**，无法直接映射 `communication.resource` |
| 真实攻击标签 | 18/20 | **逐包双标签 0/1**，30 场景×4 时长=240 组，标注判据含 `INFO_TS`/`writerEntity`/UDP checksum/ARP Opcode。**扣 2**：仅 2 类攻击，无权限/QoS/发现类异常 |
| 机器人场景适配 | 11/15 | 真实 UGV（Stella N1，含 LiDAR/AHRS/编码器）。**扣 4**：不含任何感知数据流，无法做多模态关联 |
| 可访问性与许可 | 15/15 | 页面明确 **CC BY-NC 4.0**，公开 Dropbox 直链无申请表单；压缩包仅 **284.13 MB**，体积友好 |
| 转换成本 | 8/10 | PCAP → 统计特征，本报告已实测跑通。**扣 2**：话题名缺失需人工映射 |
| 质量与文档 | 9/10 | 18 页数据集说明论文，测试床/攻击方法/标注方法齐备 |
| 小样本快速验证 | 7/5→5/5 | 284 MB 压缩包可立即下载验证（按上限取 5） |

> **许可注意**：CC BY-NC **禁止商业使用**；且 IEEE DataPort 版本标注 "Subscription Required"（付费）。
> 两者口径冲突，**取更严格者**：仅限学术非商业用途，**不得用于任何商业展示**。

**UNILEON Simulated attacks Rosbags = 91**

| 指标 | 得分 | 扣分依据 |
| --- | ---: | --- |
| ROS 2/DDS 匹配 | 22/25 | **rosbag2 原生 ROS 2 数据**，直接对应 Topic 级通信。**扣 3**：只覆盖 `cmd_vel` 洪泛一种通信攻击 |
| 真实攻击标签 | 19/20 | 场景级原生划分（E1-1/E1-2/E2-1/E2-2/E2-3），真实受控实验。**扣 1**：标签在目录/README 层，非逐消息标签 |
| 机器人场景适配 | 14/15 | 移动机器人本体 + 相机图像 + VLM 描述，**同时覆盖通信攻击与感知替换** |
| 可访问性与许可 | 15/15 | **CC BY 4.0 已核验**，Zenodo 公开直链，无需账号；允许再分发与衍生 |
| 转换成本 | 8/10 | rosbag2 可直接 `ros2 bag play`（本报告已实测该链路）。**扣 2**：具体是 rosbag2 `.db3` 还是 MCAP 未能核实 |
| 质量与文档 | 6/10 | 说明清楚。**扣 4**：数据集较新、仅 5 个 run，无配套论文 |
| 小样本快速验证 | 5/5 | E1 仅 1.6 MB，可立即验证 |

**ROSPaCe = 86**

| 指标 | 得分 | 扣分依据 |
| --- | ---: | --- |
| ROS 2/DDS 匹配 | 22/25 | **首个面向 ROS 2 的 IDS 数据集**，含 3 个 ROS 2 特有攻击；网络+OS+ROS 2 三层特征。**扣 3**：ROS 语义特征仅 5 个；**DDS 实现厂商论文未写明（未能核实）** |
| 真实攻击标签 | 20/20 | 逐行标签，攻击与正常**交替**出现，可测检测时延；6 类攻击清单明确 |
| 机器人场景适配 | 4/15 | 有轨电车车载 CPS，**非移动机器人，无导航目标/Action/位姿语义** |
| 可访问性与许可 | 12/15 | **许可已核验**（数据 CC0 1.0 / 集合 CC BY 4.0，可再分发）。**扣 3**：本网络被 WAF 拦截（202/403），下载需人工 |
| 转换成本 | 3/10 | 完整 CSV **40.2 GB**；即便精简版仍 0.92 GB 且需先定子集策略。**扣 7**：必须先做子集抽取才能起步 |
| 质量与文档 | 10/10 | *Scientific Data* 论文 + feature_list.xlsx + 5 份使用说明 notebook（**含可直接复用的 block 分组划分**） |
| 小样本快速验证 | 5/5 | **`ROSPaCe_reduced` 仅 920,868,855 B ≈ 0.92 GB**，可快速下载验证 |

**ROSIDS23 = 80**

| 指标 | 得分 | 扣分依据 |
| --- | ---: | --- |
| ROS 2/DDS 匹配 | 14/25 | **是 ROS 1，不是 ROS 2**：论文原文受害网络含 "a **ROS master**"（ROS 1 独有），无 DDS/RTPS 层。**扣 11**：迁移到 ROS 2 需重新论证 |
| 真实攻击标签 | 18/20 | 原生**多分类 5 类**，含 `unauthorized publish`(7,817) / `unauthorized subscribe`(5,289)，**是本次检索中唯一在"未授权访问"轴上带原生标签的数据集**。**扣 2**：按流标注，非逐包 |
| 机器人场景适配 | 11/15 | 真实机器人臂 + 控制器 + 实验室网络。**扣 4**：无感知数据、无任务语义 |
| 可访问性与许可 | 15/15 | **CC BY 4.0 已核验**，公开直链无需注册，4.1 GB |
| 转换成本 | 8/10 | 已提供 CICFlowMeter CSV（83 特征 + label），可直读。**扣 2**：CICFlowMeter 特征需向本项目字段二次映射 |
| 质量与文档 | 9/10 | *Data in Brief* 论文，含 `*_attacktimes.txt` 攻击起始时间（可做窗口级标签） |
| 小样本快速验证 | 5/5 | `processed.zip` 仅 93.4 MB，可立即验证 |

**RESILMESH – ALIAS – Pilot2 = 76**

| 指标 | 得分 | 扣分依据 |
| --- | ---: | --- |
| ROS 2/DDS 匹配 | 20/25 | 含 **ROS2 DDS Injection（目标 `:7400` RTPS）** 真实攻击。**扣 5**：40 分钟内仅 1 条 ROS 2 相关攻击，其余为 ROS 1/Modbus/UR 等 |
| 真实攻击标签 | 13/20 | `attack_history.csv` + `attack_timeline.md` 给出攻击时间窗与检出情况（6/8 检出）。**扣 7**：**非逐包/逐流标签**，且 ROS 2 样本极少 |
| 机器人场景适配 | 10/15 | 含 UR 机械臂 Dashboard 与坐标 CSV。**扣 5**：无感知流、无导航任务 |
| 可访问性与许可 | 15/15 | **CC BY 4.0 已核验**，公开直链 |
| 转换成本 | 9/10 | 小文本标签可直读；pcap 用 tshark 处理。**扣 1**：需按时间窗自行切分 |
| 质量与文档 | 6/10 | 时间线文档清楚。**扣 4**：无配套论文，方法学依赖自述 |
| 小样本快速验证 | 3/5 | 主体 pcap 各数百 MB，需择一 |

**优先级定义**

- **P0 可立即使用**：格式直读、许可明确、体积可控（<1 GB 可起步），无需中间转换即可产出接口字段。
- **P1 需要轻量格式转换或先做子集抽取**：真实可用，但需要 PCAP→特征、大数据子集抽取或 ROS 1→ROS 2 迁移论证。
- **P2 适合作为补充场景**：能支撑多模态/迁移验证，但不直接提供通信攻击标签。
- **P3 不推荐或证据不足**：名称相关但语义不符、或链接/许可证无法核实。

> **关于"分数高但优先级低"的说明**：ROSPaCe 得分 86 高于 ROSIDS23 的 80，
> 但优先级定为 P1 而 ROSIDS23 亦为 P1——因为 ROSPaCe 的**工程起步成本极高**（40.2 GB，
> 需先设计子集策略），而 ROSIDS23 的 `processed.zip` 仅 93.4 MB 可当天读完。
> **得分衡量数据价值，优先级衡量落地成本，二者必须分开看。**

---

## D. 重点数据集分析

### D.1 HCRL RTPS Attack Dataset（P0，方向 A 首选网络层数据）

**内容**：在 ROS 2 Foxy + Fast-DDS 的 UGV 测试床上采集的 RTPS/ARP 报文。测试床含受害机器人
Stella N1（Raspberry Pi 4B、LiDAR、AHRS、编码器）、控制器（Raspberry Pi 4B + ROS 2 Foxy）、
攻击机（Kali Linux VM）、路由器（**不连外网**，避免混入无关流量）。

**样本与规模**（论文 Table 1，已核实；**口径矛盾已如实并列**）：

| 项 | 数量 | 体积 |
| --- | ---: | ---: |
| 机器人侧抓包 `.pcap` | 240 | 1,068.2 MB |
| 攻击者侧抓包 `_labeled_*.pcap` | **2,948**（论文 §7.1 正文写 240，**与 Table 1 矛盾，未能判定**） | 124.9 MB |
| 标注文件 `.csv` | 8 | 3,148.7 MB |
| **合计（Table 1）** | **3,196** | **约 4,341.8 MB** |
| **IEEE DataPort 实际压缩包** | 1 | **284.13 MB**（`RTPS_ATTACK_DATASET.zip`） |

场景组合：采集时长 ∈ {180, 300, 600, 1200} s × 攻击序列 ∈ {`attack_by_once`, `attack_by_shuffled`,
`attack_by_random`} × 攻击方法 ∈ {Command Injection, ARP Spoofing + Command Injection} ×
子方法 ∈ {Flooding, Fuzzing}，每种时长 30 个场景，共 240 组。

**标签定义**（论文 §6.4，**原生**）：

- Command Injection：比对 `INFO_TS` 子消息 Timestamp、Data 子消息 `writerEntity`、UDP checksum、
  源/目的 IP，命中即标 Attack；
- ARP Spoofing：判 ARP Opcode == 2（ARP Reply）且源 MAC 等于攻击者 MAC。

**IEEE DataPort 条目补充确认的 CSV 字段**：`Time`、`Source IP`/`Destination IP`、
`Source MAC`/`Destination MAC`、RTPS Submessage 值（`INFO_TS`、`writerEntity`）、`ARP Opcode`，
以及标签列 `Command Injection (0/1)`、`ARP Spoofing (0/1)`。数据条目本身**免费公开**（DOI `10.21227/ffta-jy18`，2025-11-19 提交）。

**适用研究方向**：通信频率/突发异常、重放与重复请求、身份冒用（ARP 欺骗导致的 MAC/IP 关系异常）、
DDS 异常流量、攻击前后行为对照。

**格式转换方法**（本报告已实测跑通，见 `scripts/data_provisioning/`）：

```bash
# 1) 用 tshark 解析 RTPS 字段
tshark -r <file>.pcap -Y rtps -T fields -E header=y -E separator=/t -E occurrence=a \
  -e frame.number -e frame.time_epoch -e frame.len -e ip.src -e ip.dst \
  -e rtps.sm.id -e rtps.guidPrefix.src -e rtps.sm.wrEntityId -e rtps.sm.seqNumber -e rtps.domain_id
# 2) 或直接用标注 CSV（已含字段），用 --labeled-csv 路径
python3 scripts/data_provisioning/pcap_to_commrisk.py --labeled-csv <labeled>.csv \
  --resource "<resource>" --schema docs/interfaces/schemas/comm_risk_evidence.schema.json
```

**能否接入 ROS 2**：报文可直接解析（RTPS 是公开线协议）。本报告在本项目 `rg_jazzy` 容器中
（`tshark 4.2.2`）实测抓取并提取了 64 个 RTPS 包，成功得到
`rtps.sm.id` / `rtps.guidPrefix.src` / `rtps.sm.wrEntityId` / `rtps.domain_id` 字段。

**实际下载门槛**：页面为公开 **Dropbox 直链**（无申请表单、无邮箱审批），压缩包 **284.13 MB**。
IEEE DataPort 版本则标注 `LOGIN TO ACCESS DATASET FILES` / `Subscription Required`（**付费**）。
**本机网络对 Dropbox 与 Zenodo 均超时/403**，建议用浏览器手动下载。

**不适用之处（必须写明）**：

- **没有 ROS 2 话题名 / Service / Action 语义**。RTPS 抓包只有 participant GUID 与 entityId，
  无法自动对应到 `/rg/guarded_navigate` 这类业务资源。因此 `communication.resource` 只能
  标注为"DDS 端点标识"，**不得**伪造成已知业务话题。
- **不提供任何身份认证证据**：抓包是**未加密未认证**的 RTPS，标签只是"报文字段是否被篡改"，
  与 DDS-Security 认证/授权无关。**不能**据此填写 `authenticated_identity`。
  ARP 欺骗之所以能成功，恰恰是该测试床**未启用身份认证**的反证。
- 无权限拒绝日志，无任务上下文，无感知数据。
- **许可证为 CC BY-NC 4.0（禁止商业使用）**，且 IEEE 版需付费订阅，两处口径冲突，
  取更严格者执行。

### D.2 UNILEON「Simulated attacks Rosbags against mobile robot in ROS 2」（P0，唯一 ROS 2 原生 rosbag 攻击数据）

**内容**（已逐条核实 Zenodo 记录原文）：移动机器人上执行的两个概念验证攻击实验的 rosbag 记录。

- **实验 1（Do S / 通信攻击）**：向 `/input_joy/cmd_vel` 话题以 **500 Hz** 洪泛发布值为 0 的消息。
  - `E1-1`：正常运行，无攻击
  - `E1-2`：500 Hz 洪泛 DoS
- **实验 2（感知替换）**：
  - `E2-1`：正常
  - `E2-2`：原始相机图像（室内）被替换为户外环境
  - `E2-3`：原始相机图像（室内）被替换为走廊环境
  - 每个 run 含两个 rosbag：`full_rosbag`（含相机图像）与 `camera_descriptions`（VLM 生成的文本描述）

**样本与规模**：`Experiment_1.zip` = **1.6 MB**；`Experiment_2.zip` = **3.1 GB**；记录页标注总数据量 53.1 GB（含历史版本），当前版本 3.1 GB。

**许可证**：**CC BY 4.0（已核验，Zenodo 记录页 "Rights → License" 明确列出）** —— 允许再分发与衍生，只需署名。

**适用研究方向**：`REQUEST_RATE_ANOMALY`（500 Hz vs 基线）、感知异常与任务不一致、
多模态与通信的时序关联、身份/授权无关的纯行为异常。

**为什么它对本项目特别关键**：

1. **唯一同时覆盖"通信攻击"与"感知攻击"的 ROS 2 原生 rosbag2 数据**，正好对应项目
   "ROS 2 通信安全为主线、多模态感知为场景支撑"的定位；
2. 话题名明确（`/input_joy/cmd_vel`），可直接填入 `communication.resource`，
   这是 HCRL 与 ROSPaCe 都做不到的；
3. `cmd_vel` 洪泛与 `TaskRiskDecision` 的"危险动作"语义天然接近；
4. 1.6 MB 的 E1 让"24 小时内跑通"成为现实。

**实际下载门槛**：公开免费无需账号。**但本机对 Zenodo 被 403 限流**（已落盘证据
`data/access_probes/zenodo_403_experiment1.html`），需浏览器手动下载。

**不适用之处**：

- 仅 5 个 run，**样本量很小**，不足以训练模型，只适合做**规则基线与端到端联调**；
- 无配套论文，方法学细节依赖 README 自述；
- 标签在**目录/文件层**（E1-1 vs E1-2 是不同文件），不是逐消息时间戳标签；本项目若要逐窗口
  标签，需自行按 run 边界推导（属**实验推导标签**）；
- 不含权限/身份数据。

### D.3 ROSPaCe（P1，方向 A 规模最大、方法学最完善）

**内容**：在有轨电车车载 ROS 2 Foxy 系统上做渗透测试，三层监控合并：
网络层（Tshark，452 特征）+ 操作系统层（`/proc`，25 特征）+ ROS 2 层（自定义 ROS Monitor 节点，5 特征）。
实验脚本以 400 次迭代交替"30 s 正常 → 攻击 ≤60 s → 10 s 恢复"，共 6 类攻击。

**样本与规模**（**已实际下载并核对**，2026-10-11）：

| 项 | 论文口径 | **实测口径** |
| --- | --- | --- |
| 完整版体积 | 38 GB（摘要另写 37.46 GB） | 40,226,661,349 B ≈ **37.5 GB** |
| 精简版体积 | 14.5 GB | **实际拆成 15 个 CSV，合计约 14 GB**（压缩包 920,868,855 B ≈ 878 MB） |
| 非周期精简版 | — | 10 个 CSV，约 9.4 GB（压缩包 697,155,970 B ≈ 665 MB） |
| 行数 | 30,247,050 | 精简版 **28,219,113 行**（不含表头） |
| 列数 | README 482 / 论文 481 | 精简版 **62 列** = `timestamp` + 60 特征 + `attack` |
| 攻击/正常比 | 78% / 22% | **77.3% / 22.7%**（见下表） |

**精简版实测标签分布**（`attack` 列为原生标签，**15 个分片全量统计**）：

| 原生标签 | 样本数 | 占比 |
| --- | ---: | ---: |
| `metasploit SYN flood` | 14,696,883 | 52.08% |
| `nmap SYN flood` | 7,993,843 | 28.33% |
| `observe`（**正常**） | 6,645,320 | 23.55% |
| `nmap discovery` | 500,000 | 1.77% |
| `ros2 reconnaissance` | 401,494 | 1.42% |
| `ros2 node crashing` | **5,743** | 0.020% |
| `ros2 reflection` | **3,753** | 0.013% |
| **合计** | **28,247,036** | 攻击 **76.5%** / 正常 **23.5%** |

**非周期版实测**（10 个分片）：**20,851,042 行**，
`metasploit SYN flood` 9,236,806 / `nmap SYN flood` 5,392,826 / `observe` 5,330,562 /
`nmap discovery` 540,042 / `ros2 reconnaissance` 341,311 /
`ros2 node crashing` 5,742 / `ros2 reflection` 3,753。

> ✅ **一个有价值的一致性交叉验证**：两个版本里**五类攻击的样本数几乎完全相同**
> （如 `nmap discovery` 500,000 vs 540,042、`ros2 node crashing` 5,743 vs 5,742），
> 差异集中在正常段（6,645,320 → 5,330,562）。这说明非周期版**只裁剪/调整了正常段**，
> 攻击样本本身未被破坏——两版可互为对照。

> ⚠️ **三个必须注意的实测发现**：
> 1. **标签是「小写攻击名 + `observe`」**，与论文措辞（"normal / 攻击名"）不同；
>    正常段的标签是 **`observe`**，不是 `normal`。按 `normal` 过滤会得到空集。
> 2. **列名是 `attack` 而不是 `label`**。
> 3. **两个 ROS 2 特有攻击极度稀有**：`ros2 node crashing`（5,743）与
>    `ros2 reflection`（3,753）合计不到总样本的 **0.034%**。
>    若不做重采样/分层划分，这两类在测试集里几乎必然被淹没——
>    **而它们恰恰是 ROS 2/DDS 特有的攻击类型，是本项目最该关注的两类**。
>
> ⚠️ **一个隐蔽的工程陷阱（已实测踩到）**：上游打包时
> `rospace_reduced_11.csv` 的**文件名末尾带一个空格**（`rospace_reduced_11.csv `）。
> 这会导致 `for f in *.csv` 与 `ls *.csv` **静默漏掉一整个 957 MB 分片**
> （用 `find` 才能看到真实名字）。本报告已重命名为正常文件名；
> 若你重新解压，请用 `find . -name '*.csv*'` 核对数量**应为 15 个**。


**ROS 2 层 5 个特征**：`src_topic`、`subscribers_count`、`publishers_count`、`msg_type`、`msg_data`。

> ✅ **实测重要更正**：`src_topic` **确实给出真实 ROS 2 话题名**，可直接用于
> `CommRiskEvidence.communication.resource`。实测取值例如：
> `/mansarda1/image/image_raw`、`/mansarda1/image/image_raw/theora`、
> `/camera00/image_raw`、`/camera00/detected_face`、`/rosout`、`/parameter_events`、
> `/mansarda3/image/image_raw`。`msg_type` 实测取值含 `CompressedImage`、`Image`、
> `CameraInfo`、`Log`、`Packet`、`AttributedObjectsStamped`。
>
> **因此 ROSPaCe 在资源映射上明显优于 HCRL RTPS**：它能把统计量对应到**具体的 ROS 2 话题**，
> 而 HCRL 只有 DDS 端点的 GUID/entityId。这是本报告初稿低估 ROSPaCe 的一点，现予更正。


**标签定义**：用攻击机本地日志的时间戳，将"observe→start"区间标为正常，
"start→end"标为该攻击名；恢复期数据丢弃。时间同步依赖 NTP。作者明确说明：
**只标注攻击开始时刻，不标注攻击效果何时体现在特征上**。
（注意：论文写正常标签为 `normal`，**实测为 `observe`**，见上文更正。）

**格式转换方法（已实测落地）**：使用说明 notebook `5_usage_notes/usage_note_B_detection_time_series.ipynb`
给出了**按 block（正常序列 + 攻击序列配对）以 60/40 划分**的方法——这正是本项目需要的
**按会话分组划分**，可直接复用其划分逻辑，避免同一连续轨迹泄漏到训练/测试集。

本报告已提供可直接运行的落地脚本 `scripts/data_provisioning/rospace_windows.py`，
在 `rospace_reduced_0.csv` 上**实测产出**：

| 实测结果 | 数值 |
| --- | --- |
| 解析样本 | 1,746,677 行（跳过 0 行） |
| 切出的采集段 | 10 段（判据：相邻样本间隔 > 20 s） |
| 切出的 block | **918 个** |
| 窗口记录（block × 话题） | **22,591 条** |
| **block 标签纯度** | **918/918 全部为单一标签**（分段边界干净） |
| 首个 `observe` block 时长 | **29.97 s**（与论文"30 s 正常段"设计完全吻合） |
| 窗口时长 中位 / p95 / 最大 | 29.7 s / 30.0 s / 30.0 s |
| 超过契约 24 h 上界 | **0** |

> 这验证了两件事：① 论文的"30 s 正常 + 攻击 + 10 s 恢复"交替结构在数据中**真实可辨**；
> ② 按"标签变化"切 block 是正确的划分单位——这也正是防止同一连续轨迹泄漏到
> 训练集与测试集的关键。产物为 `data/ROSPaCe_reduced/windows_0.jsonl`（14 MB）。

**能否接入 ROS 2**：数据已含 ROS 2 层特征，无需 rosbag 转换；但**需先做子集抽取**（38 GB 不可全量处理）。

**实际下载门槛**：figshare 页面被 AWS WAF 拦截（`x-amzn-waf-action: challenge`，HTTP 202/403），
**本网络无法自动用 curl 下载**（WAF 拦截），需人工浏览器操作 —— **已于 2026-10-11 由人工下载完成**。
**许可证已通过 DataCite REST API 核验**：
数据条目 **CC0 1.0**、集合与论文 **CC BY 4.0**、代码 **GPL-3.0** → **允许再分发与衍生**。

**可用条目（字节数来自 DataCite API）**：

| 条目 | 体积 | 说明 |
| --- | ---: | --- |
| `ROSPaCe_reduced_noperiodicity` | 697,155,970 B ≈ **0.65 GB** | 最小可用版本 |
| `ROSPaCe_reduced` | 920,868,855 B ≈ **0.86 GB** | **推荐起点**（60 特征精简版） |
| `tshark_pcaps` | 6,439,516,604 B ≈ **6.0 GB** | 原始 pcap（若要做协议层分析） |
| `feature_list` | 29,271 B | 特征清单 xlsx |
| `ROSPaCe_complete_noperiodicity` | ≈ 25.8 GB | 完整非周期版 |
| `ROSPaCe_complete` | 40,226,661,349 B ≈ **37.5 GB** | 完整版 |

> **口径冲突如实并列**：论文写完整版 38 GB、精简版 14.5 GB；DataCite 摘要写 37.46 GB；
> 实际字节数 40.2 GB。**下载后实测**：压缩包 878 MB（`reduced`）/ 665 MB（`noperiodicity`），
> 解压后 14 GB / 9.4 GB，均为**多个 CSV 分片**（15 个 / 10 个）而非单个文件。
> 列数 README 写 482、论文写 481，**精简版实测 62 列**。

**⚠️ 实际下载后的两处操作要点（避免踩坑）**：
1. 压缩包内是**目录** `ROSPaCe_reduced/` 与 `ROSPaCe_reduced_noperiodicity/`，
   各含 15 / 10 个 CSV 分片，需先解压再合并或分片处理；
2. **不要找 `label` 列**——列名是 **`attack`**，正常样本值为 **`observe`**。

**不适用之处**：

- **不是移动机器人**，无导航目标、无 Action、无位姿轨迹 → 对 `TaskRiskDecision` 几乎无直接贡献；
- 77.3% 攻击占比意味着**随机划分会产生虚高指标**，必须按 block 划分；
- **两个 ROS 2 特有攻击极度稀有**（`node crashing` 5,743 / `reflection` 3,753，合计 <0.04%），
  需分层划分或重采样，否则测试集里几乎必然漏掉这两类；
- 无 DDS-Security 权限/认证数据；
- ROS 2 Foxy + Ubuntu 20.04；**DDS 实现厂商论文未写明（未能核实，不得假定为 Fast DDS）**；
- **无 rosbag2/MCAP**：论文明确说明 ROS Monitor 刻意不用 `/rosout` 生成 bag
  （"Producing a bag file is invasive and burdensome"），**这一设计取舍值得本项目借鉴**。

### D.3b ROSIDS23（P1，唯一在"未授权访问"轴带原生标签的数据集）

**内容**：埃斯基谢希尔奥斯曼加齐大学 IFARLab-DIH 实验室，用 tcpdump 采集机器人系统网络流量，
再用 **CICFlowMeter** 提取 **83 特征**并标注。

**标签定义（原生多分类 5 类，已由 *Data in Brief* 全文核实）**：

| 类别 | 记录数 |
| --- | ---: |
| `benign` | 62,511 |
| `DoS` | 31,000 |
| `subscriber flood` | 30,064 |
| **`unauthorized publish`** | **7,817** |
| **`unauthorized subscribe`** | **5,289** |

论文原文："The dataset includes four security attacks: **unauthorized publish, unauthorized subscribe,
subscriber flood and DoS**. The first three of these attacks are **ROS-specific**."

**为什么它对本项目重要**：这是本次检索中**唯一**在"未授权发布/订阅"这一**权限轴**上带原生标签的
公开数据集，直接对应 `CommRiskEvidence.anomaly_category = UNEXPECTED_RESOURCE_ACCESS`。

> ### ⚠️ 关键迁移限制（必须写明）
>
> **ROSIDS23 是 ROS 1 数据集，不是 ROS 2 数据集。**
> 论文原文描述受害网络："The victim network comprised a switch, robotic arm, controller device,
> and a **ROS master**." —— **ROS master 是 ROS 1 独有的中心化节点**，ROS 2 已用 DDS 取代，
> 不存在 ROS master。
> 论文也**未提** ROS 2、DDS 或 RTPS。
>
> 因此：**不得**把 ROSIDS23 当作 ROS 2 / DDS 原生数据；**不得**把它的 `unauthorized publish`
> 标签说成 DDS 访问控制判定。它只能作为：
> ① ROS **1** 权限越界场景的参照；
> ② 本项目在 ROS 2 上重建同类场景时的**对照基线**。
>
> 另外：`unauthorized publish/subscribe` 是**流级分类标签**（"这段流量属于未授权发布"），
> **不是** DDS-Security 的访问控制拒绝记录。填写 `IdentityTrustAssessment` 时必须：
> `identity_evidence.kind` 不得取 `DDS_ACCESS_CONTROL_LOG`；
> `access_control_evidence.kind` 只能取 `NONE` 或 `UNKNOWN`。

**实际下载门槛**：**CC BY 4.0 已核验**，公开直链无需注册。`processed.zip` 仅 **93.4 MB**
（含 `ROSIDS23.csv` 72.5 MB），可当天读完；raw 各包合计约 4.1 GB。
**本机对 Zenodo 文件下载 403**，需浏览器手动下载。

**本报告实测**：`processed.zip` 与 `ROSIDS23.csv` 之外，记录页另提供 `raw_noattack.zip`(879.3 MB)、
`raw_DoS.zip`(1.2 GB)、`raw_subscriberflood.zip`(950.2 MB)、`raw_unauthorizedpublisher.zip`(395.5 MB)、
`raw_unauthorizedsubscriber.zip`(530.5 MB)。各 raw 目录内含 `*_attacktimes.txt`，
记录每次攻击的**起始时间** → 可用于生成**窗口级标签**。

### D.3c RESILMESH – ALIAS – Pilot2（P1，含真实 ROS2 DDS Injection）

**内容**：EU Resilmesh 项目（GA 101119681），约 40 分钟采集、8 次攻击，含
`ros2_foxy.pcap`(729.6 MB)、`ros_noetic.pcap`(888.6 MB)、`openplc.pcap`、`ur_dashboard.pcap`，
以及 `attack_history.csv` 与 `attack_timeline.md`。

**攻击清单（含 ROS 2 相关）**：**ROS2 DDS Injection（目标 `172.19.0.4:7400` RTPS）**、
ROS Bridge DoS、ROS Parameter Hijacking、ROS1 XML-RPC Injection、Modbus Write、
UR Dashboard Injection、nmap、默认口令。

**标签**：**攻击时间窗**（起止 UTC + 是否检出，6/8 检出），**非逐包/逐流标签**。

**价值与限制**：这是本次检索中**唯一明确以 RTPS 端口 7400 为目标的 ROS 2 DDS 注入攻击**记录，
且 **CC BY 4.0**、公开直链。但 40 分钟内仅 1 条 ROS 2 相关攻击，样本极少，
且**无配套论文**，方法学依赖自述。适合作为"协议层注入"的**补充样例**，不适合作为主训练集。

### D.4 ROS2 Multi-Modal Windrow Detection Dataset（P1，多模态 rosbag2 工程样板）

**内容**：莱比锡大学在 Fendt Vario 724 拖拉机上采集的**同步多模态**数据，**ROS 2 Humble + MCAP** 格式。

**传感器与话题**：Ouster OS0-128 LiDAR（18.3 Hz，131k pts/帧）、ZED 2i 双目（23.5 Hz）、
NovAtel OEM7 GNSS+IMU、5 路单目相机。话题含 `/ouster/points`、
`/zed/zed_node/point_cloud/cloud_registered`、`/zed/zed_node/odom`、`/novatel/oem7/fix`。

**规模**：单行子集 **123 s / 20.7 GB**（完整数据集因体积需申请）。

**许可证**：**CC BY 4.0（已核验）**。

**价值**：这是本次检索中**格式最贴合**的多模态数据——MCAP 是 rosbag2 原生格式之一，
本项目 `rg_jazzy` 容器已实测可写可读 MCAP。它可作为"大规模多模态 rosbag2 读取与降采样"的
工程样板，验证项目的多模态接入管线。

**不适用之处**：**无任何攻击标签**（纯正常数据）；农业场景与巡检/导航任务不同；
20.7 GB 体积对 24 小时落地偏重（建议用 `ros2 bag` 的按话题/时间裁剪，或仅取小段）。
**绝不能**把它说成"多模态攻击检测数据集"。

### D.4b SROS 2 keystore 窃取后冒名注入（P0 实验设计参考，**非数据集**）

**来源**：田纳西理工大学（Sakib, Martinez, Brady, Hasan, Guo），IEEE MILCOM 2025 Workshops (SRRSS)，
6 页，[arXiv:2511.00140](https://arxiv.org/abs/2511.00140)（论文 CC BY-NC-ND 4.0）。

**为什么不列为数据集**：论文**未提供公开数据集**（arXiv 页面仅有 PDF 与 TeX 源码）。
把它列入候选表是为了**方法学参考**，而不是当作数据来源——这一点必须写清楚，
否则会误导后续开发者去找一个不存在的数据集。

**论文做了什么（摘要原文要点）**：
在被 Trojan 感染的 Debian 包中修改 ROS 2 安全命令，把新生成的 keystore 凭据通过
**DNS base64 分块**外泄到攻击者控制的域名服务器；攻击者拿到凭据后
**以已认证参与者身份重新加入 SROS 2 网络**，发布伪造的控制或感知消息，
**且不会触发认证失败**。测试平台为 ROS 2 Humble + Quanser **QCar2** + Intel RealSense，
执行四停车标志导航。

**报告的后果（对本项目极有价值）**：
- 控制话题注入 → **强制刹车、持续高速加速、连续转弯循环**；
- 感知话题欺骗 → **伪造停车标志**、或**抑制真实检测**。

**与本项目三个接口的对应关系**：

| 论文现象 | 对应本项目字段 | 关键启示 |
| --- | --- | --- |
| 已认证身份发布伪造控制消息 | `IdentityTrustAssessment` 可能仍为 `AUTHORIZED` | **认证通过 ≠ 行为可信**——这正是本项目要解决的核心问题 |
| 强制刹车 / 高速加速 / 连续转弯 | `TaskRiskDecision` 的"危险动作" | 可作为危险动作分类的实验设计参照 |
| 伪造/抑制停车标志 | 感知异常诱导危险动作 | 正是本项目"多模态感知为场景支撑"的定位 |

> ### ⚠️ 必须写进报告的关键论证
>
> 该论文证明了：**在 SROS 2 中，一旦凭据被窃取，攻击者就是"合法已认证主体"**，
> 认证层**不会**报警。
> 因此本项目的价值主张应当明确表述为：
> **"仅靠 DDS 身份认证不足以防护；必须在认证之上引入通信行为分析与任务级风险推理"**。
>
> 同时，这也是"**为什么公开数据集无法提供 `IdentityTrustAssessment` 证据**"的最强论据：
> 该类攻击的成功标志恰恰是**没有认证失败日志**。要产生可核验的访问控制证据，
> 必须由本项目在**故意配置越权 enclave** 的受控实验中采集（见 §G.6）。

### D.5 GRIFFIN UAS 事件相机数据集（P3，明确排除——名称相关性的典型陷阱）

**内容**：塞维利亚大学，DAVIS346 事件相机 + 无人机，ROS 1 `.bag`，含 events/frames/IMU，共 513.9 MB。

**排除理由（三点）**：

1. 标题 "intrusion monitoring" 指**监控入侵的人**，与网络入侵检测无关——名称相关性是陷阱；
2. 格式为 **ROS 1 bag**，不能直接当作 ROS 2 原生数据；
3. 无任何网络攻击或权限标签。

---

## E. 对现有三个接口的映射

> 本节所有映射均以 `9c4bcf7` / `4664b97` 的 Schema 为准。
> 转换脚本已实测通过 `docs/interfaces/schemas/comm_risk_evidence.schema.json` 的严格校验
> （`additionalProperties: false`）。

### E.1 CommRiskEvidence

| 目标字段 | 约束 | HCRL RTPS | UNILEON E1 | ROSPaCe | ROSIDS23 | 标签/字段来源与可信性限制 |
| --- | --- | --- | --- | --- | --- | --- |
| `communication.resource` | string，必填 | ⚠️ **无法可靠取得**：RTPS 抓包无话题名，只有 GUID/entityId → 只能写 DDS 端点标识 | ✅ 直接取 `/input_joy/cmd_vel` | ✅ **可直接取 `src_topic` 列的真实话题名**（实测：`/rosout`、`/mansarda1/image/image_raw` 等） | ⚠️ 流级特征，无 ROS 资源名 | HCRL/ROSIDS23 需人工映射；**ROSPaCe 可直接映射**；**不得**伪造成 `/rg/guarded_navigate` |
| `communication.resource_type` | `Topic`/`Service`/`Action` | `Topic`（RTPS 子消息层） | `Topic` | `Topic` | `Topic`（ROS 1） | 数据集原生 |
| `communication.operation` | 枚举 | `PUBLISH`（攻击者注入方向） | `PUBLISH` | `PUBLISH` | 可区分 **`PUBLISH` / `SUBSCRIBE`**（`unauthorized publish` vs `unauthorized subscribe`） | ROSIDS23 是唯一能区分发布/订阅方向的数据集 |
| `window.start` / `.end` | RFC3339 带时区 | ✅ `Time` 列或 `frame.time_epoch` | ✅ rosbag 消息时间戳 | ✅ 时间戳列 | ✅ 流时间戳 + `*_attacktimes.txt` | 原生 |
| `window.duration_ms` | number，上界 24 h | ✅ | ✅ | ✅ | ✅ | 计算得出；脚本已强制 24 h 上界 |
| `request_count` | integer | ✅ 窗口内包数 | ✅ 窗口内消息数 | ✅ 数据点数 | ✅ 流数 | 原生统计 |
| `frequency_hz` | number，可选 | ✅ | ✅（500 Hz vs 正常） | ✅ | ✅ | **无法计算时必须省略，不得填 0** |
| `anomaly_category` | 7 值枚举 | `REQUEST_RATE_ANOMALY`（Flooding）、`DUPLICATE_CALL_PATTERN`（Fuzzing 重复）、`NODE_RELATION_ANOMALY`（ARP 欺骗改变 MAC/IP 关系） | `REQUEST_RATE_ANOMALY`（500 Hz） | `REQUEST_RATE_ANOMALY`、`TIMING_DEVIATION`、`UNEXPECTED_RESOURCE_ACCESS`（Reconnaissance）、`NODE_RELATION_ANOMALY`（Reflection） | **`UNEXPECTED_RESOURCE_ACCESS`**（unauthorized publish/subscribe）、`REQUEST_RATE_ANOMALY`（flood/DoS） | 均有原生标签支撑；映射到本项目枚举属**本项目推导** |
| `risk_level` | 5 值枚举 | `HIGH`（篡改控制指令） | `HIGH` | `MEDIUM`~`HIGH` | `MEDIUM`~`HIGH` | 本项目判定规则 |
| `basis` | array[string] | ✅ | ✅ | ✅ | ✅ | 必须写清判据与阈值来源 |
| `status` | `NORMAL`/`SUSPICIOUS`/`UNKNOWN`/`ERROR` | 由判据得出 | 由判据得出 | 由判据得出 | 由判据得出 | **无基线时必须 `UNKNOWN`，不得 `NORMAL`** |
| `evidence_refs[].kind` | 6 值枚举 | `CONTROLLED_SECURITY_EXPERIMENT` | `CONTROLLED_SECURITY_EXPERIMENT` | `CONTROLLED_SECURITY_EXPERIMENT` | `CONTROLLED_SECURITY_EXPERIMENT` | 四者均为**数据集作者的受控实验**，不得标 `RUNTIME_LOG`（那是本项目自采日志） |

**关键判据的基线来源**：唯一权威基线是 `config/task_policy.yaml` 的
`max_requests_per_minute: 10`（即 0.167 Hz）。若把它直接套用到 HCRL/UNILEON，
得到的是**本项目策略视角下的越界结论**，不是数据集原生结论——必须在报告中如此表述。

**已实测的转换产物示例**（本机 RTPS 抓包，64 包 / 3000.2 ms）：

```json
{"status": "SUSPICIOUS", "anomaly_category": "DUPLICATE_CALL_PATTERN",
 "risk_level": "MEDIUM", "request_count": 64, "frequency_hz": 20.9986,
 "basis": ["窗口内样本数 64，窗口长度 3000.2 ms。",
           "已剔除 1 个疑似采集起停间隙（判据：> max(10×中位间隔 2 µs, 1 s)）；该剔除规则由本工具引入，非数据源标注。",
           "样本在约 182 µs 内成簇到达，占整个窗口的 0.01%，判定为突发型流量；20.999 Hz 只是窗口均值…",
           "…"]}
```

### E.2 IdentityTrustAssessment

| 目标字段 | 四个公开数据集能否支撑 | 说明 |
| --- | --- | --- |
| `subject.observed_name` | ⚠️ 部分可 | HCRL：源 IP/MAC、RTPS `guidPrefix`、`writerEntityId` 是**可观察标识**，可作 observed_name |
| `subject.declared_enclave` | ❌ 不能 | 数据集均不含 enclave 声明 |
| `subject.authenticated_identity` | ❌ **不能** | 见下方强制声明 |
| `requested_resource.resource` | ⚠️ 部分可 | HCRL 无话题名；UNILEON 有话题名但无权限语义；ROSIDS23 只有流级特征 |
| `requested_resource.operation` | ⚠️ 部分可 | **仅 ROSIDS23** 能区分 `PUBLISH` / `SUBSCRIBE`（unauthorized publish/subscribe） |
| `authorization.result_status` | ❌ 不能 | 数据集无授权判定 |
| `authorization.denial_layer` | ❌ 不能 | 无 `DDS_ACCESS_CONTROL` 拒绝记录；必须填 `UNKNOWN` 或 `NONE` |
| `identity_evidence.kind` | ⚠️ 只能取 `UNKNOWN` | **不得**取 `DDS_ACCESS_CONTROL_LOG` / `PERMISSION_FILE_DERIVED` |
| `access_control_evidence.kind` | ⚠️ 只能取 `NONE`/`UNKNOWN` | 无原生访问控制日志 |
| `policy_ref.permissions_ref` | ✅ 可用本项目 | `security/keystore/enclaves/*/permissions.xml` |

> ### ⚠️ 强制声明（必须逐字写入报告与答辩材料）
>
> **HCRL RTPS、ROSPaCe、UNILEON、ROSIDS23 四个数据集以及任何公开网络入侵数据集，
> 都不包含 DDS-Security 的身份认证或访问控制判定证据。**
> 它们最多只能支撑**权限分析或模拟场景**，
> **不足以证明 DDS 已认证身份**。
>
> 具体地：
> - RTPS 抓包中可见的 `guidPrefix` / `writerEntityId` 是**线路上的端点标识**，
>   未加密未认证的 RTPS 流量中任何人都可以伪造这些值；ARP 欺骗之所以能成功，
>   恰恰说明该测试床**没有启用身份认证**。
> - **ROSIDS23 的 `unauthorized publish` / `unauthorized subscribe` 是"流分类标签"
>   （这段流量被判定为未授权发布），不是 DDS-Security 的访问控制拒绝记录。**
>   它证明的是"存在未授权行为"，**不是**"某个已认证身份被拒绝"。
>   因此不得据此填写 `access_control_evidence`。
> - **不得**把数据集的源 IP/MAC 当作 DDS 已认证身份；
> - **不得**把数据集中的"正常流量"称为"已授权主体的流量"；
> - `authenticated_identity` 字段只能来自**本项目自己的 SROS 2 受控实验**。

**方向 C 的唯一可行路径（与任务书要求一致）**：

> **公开正常数据**（UNILEON E1-1 / ROSPaCe 正常段）
> **+ 开源权限配置**（本项目 `security/keystore/`，Apache-2.0 的 ros2/sros2 工具链生成）
> **+ 本项目受控仿真生成安全事件**（SROS 2 Enforce + Gateway 拒绝日志）
> = 可核验的 `IdentityTrustAssessment` 证据链

其中只有第三项能产生 `evidence_refs[].kind = CONTROLLED_SECURITY_EXPERIMENT` 与
`access_control_evidence.kind = NATIVE_ACCESS_CONTROL_LOG`。

### E.3 TaskRiskDecision

| 目标字段 | 三个数据集能否支撑 | 说明 |
| --- | --- | --- |
| `task_id` | ❌ 数据集均无 | 只能取本项目 `patrol_a_001` |
| `candidate_action.action_resource` | ✅ **Schema 固定** `const="/rg/guarded_navigate"` | 与数据集无关，上游无法改 |
| `candidate_action.operation` | ✅ 固定 `NAVIGATE` | 同上 |
| `target.frame_id` / `.x` / `.y` | ❌ HCRL/ROSPaCe 无位姿目标；UNILEON 有 `cmd_vel` 但非 PoseStamped 目标 | **均需本项目仿真补充** |
| `task_context.task_phase` | ❌ 均无 | F0 基线不含 M3，**必须省略** |
| `risk_level` | ⚠️ 可从数据集攻击语义推导 | 如 `cmd_vel` 洪泛 → `HIGH`；属**本项目推导标签** |
| `rule_basis` | ✅ 可用 TaskPolicy 区域规则 | `allowed_region: x∈[0,4] y∈[0,4]` |
| `policy_ref.policy_version` | ✅ 可取 `"1.0"`（`config/task_policy.yaml`） | **`policy_epoch`/`policy_digest` 在 F0 必须省略** |

**结论**：**三个公开数据集都不能直接产出合法的 `TaskRiskDecision`**，
因为它们都不含"任务 + 导航目标 + 位姿"语义。
`TaskRiskDecision` 的标签**必须**由本项目受控实验生成，并明确标注为**项目后生成标签**。

**可复用的语义桥梁**：UNILEON 的 `cmd_vel` 洪泛是"合法主题上的危险动作洪泛"，
可作为 `TaskRiskDecision` 的**危险动作样例来源**——但导航目标本身仍需 NavigationSim 生成。

### E.4 多模态场景关联能力

| 关联方式 | 可行性 | 限制 |
| --- | --- | --- |
| UNILEON E2 内图像 ↔ `cmd_vel` | ✅ **可行** | 同一 rosbag 内共享 ROS 时间戳，属**真实同源同步**，非拼接 |
| UNILEON E2 `camera_descriptions`（VLM 文本）↔ 图像 | ✅ 可行 | 同一记录的两种表示 |
| HCRL/ROSPaCe PCAP ↔ 任意机器人视频 | ❌ **禁止** | 时空不同源，**不得拼接成"真实同步攻击数据"** |
| ROSPaCe 网络特征 ↔ 其 OS/ROS 2 特征 | ✅ 可行 | 论文说明按时间戳 <100 ms 合并，作者已完成 |

> **强制约束**：禁止在没有证据的情况下把不同时空采集的 PCAP 与机器人视频拼接成
> "真实同步攻击数据"。若确需合成对齐，必须①声明这是**受控合成实验**；
> ②保存数据来源清单与关联规则；③在 `evidence_refs[].note` 中标注为合成。

---

## F. 推荐组合方案

### 方案一（首推）：UNILEON rosbag2 + 本项目 SROS 2 受控实验

| 项 | 内容 |
| --- | --- |
| 数据 | UNILEON E1（1.6 MB，通信攻击）+ E2（3.1 GB，感知替换） |
| 覆盖 | CommRiskEvidence（频率异常）、多模态感知异常、TaskRiskDecision（危险动作） |
| 优点 | **ROS 2 原生 rosbag2、话题名明确、CC BY 4.0 许可清晰、体积极小、通信+感知一体化** |
| 缺点 | 样本量小（5 个 run）、无身份/权限证据、标签在 run 层 |
| 工期 | **1～2 天**可完成读取、字段提取与规则基线 |
| 必须补做 | 用本项目 SROS 2 + Gateway 生成 `IdentityTrustAssessment` 与 `TaskRiskDecision` 的真实证据 |

### 方案二（推荐并行）：HCRL RTPS（逐包标签，284 MB）+ ROSIDS23（权限轴标签，93 MB）

| 项 | 内容 |
| --- | --- |
| 数据 | HCRL RTPS 压缩包 284.13 MB；ROSIDS23 `processed.zip` 93.4 MB |
| 覆盖 | CommRiskEvidence（频率/重复/节点关系异常）、`UNEXPECTED_RESOURCE_ACCESS`（未授权发布/订阅方向） |
| 优点 | **两者合计不到 400 MB 即可起步**；HCRL 提供逐包真值，ROSIDS23 提供发布/订阅方向与未授权语义；许可均已核验 |
| 缺点 | HCRL 为 CC BY-NC（禁商用）且无 ROS 语义；**ROSIDS23 是 ROS 1，需迁移论证** |
| 工期 | **2～3 天**（含 ROS 1→ROS 2 迁移局限的书面论证） |
| 风险 | 若报告未明确标注 ROSIDS23 为 ROS 1，会被评委判定为数据误用 |

### 方案三（规模扩展）：ROSPaCe 精简版子集 + RESILMESH 协议层注入样例

| 项 | 内容 |
| --- | --- |
| 数据 | `ROSPaCe_reduced`（0.92 GB，60 特征）+ `ROSPaCe_reduced_noperiodicity`（0.65 GB）+ RESILMESH `ros2_foxy.pcap` |
| 覆盖 | 6 类攻击的多分类检测、检测时延、RTPS 端口 7400 注入样例 |
| 优点 | **许可最宽松（数据 CC0，可自由再分发）**；方法学最完善；含可直接复用的 block 分组划分 |
| 缺点 | 40 GB 完整版起步成本高、本网络被 WAF 拦截需人工下载、非移动机器人、无 ROS 语义特征（仅 5 个） |
| 工期 | **3～5 天** |
| 定位 | 从"可行性验证"升级为"有统计效力的评测"阶段使用 |

### 方案四（仅作对照，不作主线）：CIC-IDS2017/2018 迁移验证

| 项 | 内容 |
| --- | --- |
| 数据 | CIC-IDS2017/2018（PCAP 可直下） |
| 覆盖 | 通信异常检测算法在通用网络与 ROS 2 流量间的可迁移性讨论 |
| 缺点 | **不是 ROS 2 数据**。仅能作为"算法迁移对照"，**绝不能称为 ROS 2 攻击数据** |
| 工期 | 2～3 天 |

> **组合建议**：赛期内以**方案一 + 方案二**为主线（合计约 3.5 GB，1～3 天可起步），
> 用方案三在后期提升统计效力，方案四仅在"算法通用性"章节作为对照出现。

---

## G. 24～48 小时落地方案

> 目标：**在 48 小时内产出第一条可运行、可校验、可追溯的证据链**，而不是先下载几百 GB。
> 下列步骤中带 ✅ 的已由本次检索实测验证。

### G.1 数据源与下载

| 优先 | 数据 | 下载地址 | 大小 | 获取方式 |
| --- | --- | --- | --- | --- |
| ① | UNILEON `Experiment_1.zip` | https://zenodo.org/records/17649537/files/Experiment_1.zip?download=1 | **1.6 MB** | 浏览器（Zenodo 对本网络 403） |
| ② | ROSIDS23 `processed.zip` / `ROSIDS23.csv` | https://zenodo.org/records/10014434 | **93.4 MB** | 浏览器；CC BY 4.0 |
| ③ | HCRL RTPS `RTPS_ATTACK_DATASET.zip` | https://ocslab.hksecurity.net/Datasets/rtps-attack-dataset · [IEEE DataPort 镜像](https://ieee-dataport.org/documents/real-time-publish-subscribe-attack-dataset) | **284.13 MB** | 浏览器（Dropbox 本网络超时）；CC BY-NC |
| ④ | UNILEON `Experiment_2.zip` | https://zenodo.org/records/17649537/files/Experiment_2.zip?download=1 | 3.1 GB | 浏览器，可选（感知替换实验） |
| ⑤ | ROSPaCe `reduced` / `reduced_noperiodicity` | https://springernature.figshare.com/articles/dataset/ROSPaCe_reduced/25594860 · [.../ROSPaCe_reduced_noperiodicity/25594854](https://springernature.figshare.com/articles/dataset/ROSPaCe_reduced_noperiodicity/25594854) | 0.92 GB / 0.65 GB | 浏览器（**先确认许可**：数据 CC0、集合 CC BY 4.0，已核验） |
| ⑥ | RESILMESH `ros2_foxy.pcap` | https://zenodo.org/records/20729823 | 729.6 MB | 浏览器 |
| ⑦ | ROSPaCe 完整版（后期可选） | https://springernature.figshare.com/articles/dataset/ROSPaCe_complete/25594347 · [tshark_pcaps](https://springernature.figshare.com/articles/dataset/tshark_pcaps/25605789) | 37.5 GB / 6.0 GB | 浏览器 |

> **最小起步集**：① + ② + ③ = **约 380 MB**，全部许可已核验，可在数小时内开始研发。

### G.2 环境供应（✅ 实测可用）

```bash
# 在项目既有 rg_jazzy 容器内（镜像 ros:jazzy，/ws 挂载仓库）
export DEBIAN_FRONTEND=noninteractive
apt-get update && apt-get install -y --no-install-recommends \
    python3-scapy python3-pandas tshark tcpdump sqlite3
```

**关键坑（已实测）**：容器内 **pip 无法解析 `files.pythonhosted.org`**，必须走 apt 的
`python3-scapy` / `python3-pandas`。`ros:jazzy` 基础镜像**不含** `demo_nodes_cpp`，
写发布者请用 `rclpy` 自建。

### G.3 读取方式

```bash
# rosbag2（UNILEON）
source /opt/ros/jazzy/setup.bash
ros2 bag info <bag_dir>          # ✅ 实测可用
ros2 bag play <bag_dir> -r 1.0
# PCAP（HCRL / ROSPaCe）
tshark -r <file>.pcap -Y rtps -T fields ...   # ✅ 实测可用
```

### G.4 数据预处理步骤

1. **解压/展开**：UNILEON 的 zip 解出 rosbag2 目录（`metadata.yaml` + `.db3`/`.mcap`）。
2. **话题裁剪**：只保留 `/input_joy/cmd_vel`（及 E2 的相机话题），其余丢弃以降体积。
3. **窗口切分**：按固定窗口（建议 1 s 或 5 s）切分，逐窗口统计 `request_count` / `frequency_hz`。
4. **run 边界对齐**：用文件名（E1-1/E1-2/E2-1/E2-2/E2-3）生成**run 级标签**。
5. **边界伪影剔除**：剔除采集起停造成的超长间隔（脚本已实现并写明判据）。
6. **命名规范化**：把数据集话题名映射为本项目资源名时，**逐条记录映射依据**。

### G.5 可产生的接口字段

| 接口 | 字段 | 数据来源 | 是否原生 |
| --- | --- | --- | --- |
| CommRiskEvidence | `communication.resource` | `/input_joy/cmd_vel` | ✅ 原生 |
| CommRiskEvidence | `window.*`、`request_count`、`frequency_hz` | rosbag 时间戳统计 | ✅ 原生 |
| CommRiskEvidence | `anomaly_category=REQUEST_RATE_ANOMALY` | 500 Hz vs 基线 | ⚠️ 需本项目判据 |
| CommRiskEvidence | `basis`、`risk_level` | 本项目规则 | ⚠️ 本项目生成 |
| IdentityTrustAssessment | 全部关键字段 | — | ❌ **公开数据无法提供**，须 SROS 2 受控实验 |
| TaskRiskDecision | `rule_basis`、`policy_ref.policy_version="1.0"` | `config/task_policy.yaml` | ✅ 项目自有 |
| TaskRiskDecision | `risk_level`、`target.*` | NavigationSim | ⚠️ 本项目仿真生成 |

### G.6 需要额外合成的受控安全事件（**必须标注为合成**）

| 事件 | 生成方式 | 对应接口 | evidence kind |
| --- | --- | --- | --- |
| 未授权主体请求 `/rg/guarded_navigate` | `security/keystore/enclaves/unauthorized` 启动客户端 | IdentityTrustAssessment `DENIED` | `CONTROLLED_SECURITY_EXPERIMENT` + `NATIVE_ACCESS_CONTROL_LOG` |
| 越界导航目标 (8.0, 8.0) | NavigationSim 发送超出 `allowed_region` 的目标 | TaskRiskDecision `BLOCK_RECOMMENDED` | `CONTROLLED_SECURITY_EXPERIMENT` |
| 频率越界请求 | 高频调用 Gateway（超过 10 次/分钟） | CommRiskEvidence `SUSPICIOUS` | `CONTROLLED_SECURITY_EXPERIMENT` |
| 权限配置理论分析 | 解析 `permissions.xml` 推导允许集合 | IdentityTrustAssessment `PERMISSION_FILE_DERIVED` | `PERMISSION_FILE_ANALYSIS` |

### G.7 最小训练/规则基线

**不要一开始就上机器学习。** 先用可解释规则建立可复现基线：

```text
规则 R1（频率）：window 内 frequency_hz > k × baseline_hz → REQUEST_RATE_ANOMALY
                 baseline_hz 取自 config/task_policy.yaml（10 次/分钟 = 0.167 Hz），k 可标定
规则 R2（突发）：样本集中度 > 阈值（如 95% 样本落在 <5% 窗口内）→ DUPLICATE_CALL_PATTERN
规则 R3（任务）：目标超出 allowed_region → BLOCK_RECOMMENDED
规则 R4（权限）：请求资源 ∉ permissions.xml 允许集合 → DENIED（denial_layer=DDS_ACCESS_CONTROL）
```

R1/R2 已由 `scripts/data_provisioning/pcap_to_commrisk.py` 实测实现并通过契约校验。
ML 基线建议作为**第二阶段**，且必须沿用 ROSPaCe 的 **block 分组划分**。

### G.8 可运行的验证指标

| 类别 | 指标 | 最小可行目标 |
| --- | --- | --- |
| 通信安全 | Precision / Recall / F1 | 在 UNILEON E1 上区分 E1-1 与 E1-2（2 类，run 级） |
| 通信安全 | FPR | 正常 run 上误报窗口比例 |
| 通信安全 | 异常检测时延 | 从窗口开始到首次判 SUSPICIOUS 的秒数 |
| 任务与权限 | 危险动作阻断率 | NavigationSim 越界目标被拒比例 |
| 任务与权限 | 正常任务放行率 | 合法目标成功执行比例 |
| 任务与权限 | 越权请求拦截率 | `unauthorized` enclave 被拒比例 |
| 系统 | 单次推理/规则判定耗时、CPU/内存 | 由 `psutil` 或 `/proc` 采集 |
| 系统 | 证据可追溯率 | 每条输出都有 ≥1 条可解析 `evidence_refs` |
| 系统 | ROS 2 真实链路影响 | 加入 Gateway 前后的 Action 端到端延迟对照 |

**数据划分纪律**：**必须按采集会话/机器人场景/攻击批次分组划分**，
禁止把同一连续轨迹或近重复帧同时放入训练集与测试集。
ROSPaCe 的 `usage_note_B` 提供了可直接复用的 block 划分实现。

### G.9 已知局限

1. UNILEON 仅 5 个 run，**统计效力不足**，结论只能表述为可行性验证；
2. 公开数据**不提供任何 DDS 认证/权限证据**，`IdentityTrustAssessment` 必须靠本项目受控实验；
3. 公开数据**不含任务/导航目标语义**，`TaskRiskDecision` 必须靠本项目仿真；
4. HCRL/ROSPaCe 无话题名，资源映射需人工介入，映射依据必须留档；
5. 本机网络出口对 Zenodo/figshare/HuggingFace 受限，**下载需人工浏览器操作**；
6. ROSPaCe 数据集许可证未核实 → 在确认前**仅内部使用，不再分发**。

---

## H. 实验设计

### H.1 正常/异常对照

| 组 | 数据 | 期望行为 |
| --- | --- | --- |
| 对照组（正常） | UNILEON E1-1；ROSPaCe `normal` 段；本项目 NavigationSim 合法目标 | 应判 `NORMAL` 或（无基线时）`UNKNOWN`，**不得**判 `SUSPICIOUS` |
| 实验组（通信异常） | UNILEON E1-2（500 Hz 洪泛）；HCRL Flooding/Fuzzing | 应判 `SUSPICIOUS` + `REQUEST_RATE_ANOMALY`/`DUPLICATE_CALL_PATTERN` |
| 实验组（身份冒用） | HCRL ARP Spoofing 段 | 应判 `NODE_RELATION_ANOMALY` |
| 实验组（权限异常） | 本项目 `unauthorized` enclave 请求 | `IdentityTrustAssessment` = `DENIED`，`denial_layer` = `DDS_ACCESS_CONTROL` |
| 实验组（任务异常） | NavigationSim 越界目标 | `TaskRiskDecision` = `BLOCK_RECOMMENDED` |
| 实验组（感知异常） | UNILEON E2-2 / E2-3 | 感知与场景不一致，用于风险证据 |
| 对抗对照（必须做） | 空输入 / 超长窗口 / 缺基线 / 非法版本 | 必须 `UNKNOWN`/`ERROR` 并**默认阻断**，不得放行 |

### H.2 评价指标

- **通信**：Precision、Recall、F1、FPR、异常检测时延、分攻击类型召回率；
- **任务与权限**：危险动作阻断率、正常任务放行率、越权请求拦截率、未知输入拒绝率、Gateway 前后处理延迟；
- **系统**：单次判定耗时、CPU/内存、ROS 2 真实链路是否受影响、证据可追溯率、模块替换后稳定性。

### H.3 数据划分

必须**按会话/场景/批次分组**。建议：

- UNILEON：run 级划分（3 训练 / 2 测试 或 留一法，因样本极少，推荐留一交叉验证）；
- ROSPaCe：直接复用 `usage_note_B` 的 block 60/40 划分；
- HCRL：按 scenario 目录分组（同一场景的时间序列不得跨集）。

### H.4 证据记录（每条结论必须可追溯）

每次运行需落盘：
`run_id`、`Git SHA`、`schema_version`、`module_version`、输入数据 `SHA-256`、
窗口边界、判据与阈值来源、`evidence_refs[].kind`。
**模拟/合成/本项目推导的标签必须逐条标注**，禁止与公开数据原生标签混同表述。

---

## I. 最终获取决策

> 此处"采购"仅指**数据获取决策**，全部为免费来源，无金钱支出。

| 决策 | 数据集 | 理由 |
| --- | --- | --- |
| **直接下载**（无需账号，建议浏览器） | UNILEON `Experiment_1.zip`（1.6 MB）、`Experiment_2.zip`（3.1 GB） | CC BY 4.0 已核验、rosbag2 原生、体积极小、价值最高 |
| **直接下载** | ROSIDS23 `processed.zip`（93.4 MB） | CC BY 4.0 已核验、公开直链；**唯一带未授权发布/订阅标签**（但须标注为 ROS 1） |
| **直接下载** | HCRL RTPS `RTPS_ATTACK_DATASET.zip`（284.13 MB，Dropbox 直链） | 逐包真值、真实 Fast-DDS 环境；**注意 CC BY-NC 禁商用** |
| **直接下载** | RESILMESH `ros2_foxy.pcap`（729.6 MB） | CC BY 4.0；含唯一明确以 RTPS `:7400` 为目标的 ROS 2 DDS 注入 |
| **直接下载** | ROSPaCe `reduced` / `reduced_noperiodicity`（0.92 / 0.65 GB） | **数据 CC0 1.0（最宽松，可自由再分发）**；方法学最完善 |
| **下载 + 扩展验证** | ROS2 Multi-Modal Windrow 单行子集 | CC BY 4.0 已核验，用于验证 MCAP/rosbag2 多模态管线（**仅取小段**） |
| **注册后下载** | IEEE DataPort 版 RTPS 数据集 | 页面标注 `Subscription Required`（**付费**）；若 Dropbox 可用则无需走此路 |
| **注册后下载 / 视条款** | CIC-IDS2017/2018 | 仅作算法迁移对照，不作为 ROS 2 攻击数据 |
| **申请权限** | SWaT / WADI | 通常需机构申请，周期长，**不建议在本次赛期内投入** |
| **不推荐使用** | GRIFFIN UAS（ROS 1 + 语义不符）、MSU ICS（DNS 失败）、Hugging Face 两个候选（本网络无法核验） | 证据不足或语义不符 |
| **不存在，需自建** | DDS-Security / SROS 2 访问控制日志数据集 | 经系统检索**确认不存在**，必须自行采集 |

**优先级排序**：UNILEON（P0）= HCRL RTPS（P0）> 本项目 SROS 2 受控实验（P0，方向 C 唯一路径）
> ROSIDS23（P1）> ROSPaCe（P1）> RESILMESH（P1）> Windrow（P1）> CIC-IDS（P2 对照）> 其余（P3）。

---

## J. 未解决问题（如实说明）

1. **公开 ROS 2 安全数据确实稀缺。** 本次检索确认**真正面向 ROS 2 的攻击/异常数据集仅 4 个**
   （HCRL RTPS、ROSPaCe、UNILEON、RESILMESH），外加 1 个**易被误认为 ROS 2 的 ROS 1 数据集**（ROSIDS23）。
   其中：
   - **rosbag2 原生格式的只有 UNILEON**（且仅 5 个 run）；
   - 提供**逐包真值**的只有 HCRL RTPS；
   - 提供**逐行标签 + 多攻击类型**的只有 ROSPaCe；
   - 明确以 **RTPS 端口 7400** 为目标的只有 RESILMESH（仅 1 条攻击）。
   **没有找到任何"ROS 2 攻击 rosbag + 多模态 + 权限日志"的完整数据集。**

2. **缺失的攻击类型**（公开数据中**没有**，必须自行生成）：
   - **ROS 2 Topic/Service/Action 层面的非法访问**（数据集均无 ROS 2 资源级标签；
     ROSIDS23 的 unauthorized publish/subscribe 是 **ROS 1** 且为流级标签）；
   - **重放攻击的 ROS 2 语义标签**（HCRL 仅有报文级重复）；
   - **QoS / 发现（discovery）类异常**的专门数据集；
   - **DDS-Security 认证失败 / 权限拒绝日志**（**完全缺失**，见第 4 条）；
   - **任务级越权与不合理导航目标**（**完全缺失**，无任何公开数据集含 ROS 2 任务语义）。

3. **必须自己生成的场景**：
   - 全部 `IdentityTrustAssessment` 证据（须 SROS 2 Enforce + 原生访问控制日志）；
   - 全部 `TaskRiskDecision` 证据（须 NavigationSim + `config/task_policy.yaml`）；
   - ROS 2 资源级（话题/服务/Action）异常访问标签。

4. **没有身份认证证据的数据**：HCRL RTPS、ROSPaCe、UNILEON、ROSIDS23、RESILMESH **全部没有**。
   前几者的测试床甚至**未启用** DDS 身份认证（HCRL 的 ARP 欺骗得以成功即为反证）。
   **不得**把其中的 IP/MAC/GUID 当作已认证身份。
   **并且经系统检索确认：公开的"SROS 2 权限拒绝 / DDS-Security 访问控制日志"数据集不存在**
   （检索动作：DataCite 查 `SROS2` 仅得 4 条论文；GitHub 查 `ROS2 security dataset`、`rosbag2 security` 均 0 命中；
   DataCite 查 `DDS security intrusion` 0 命中；ROSPaCe 的监视器为 `/proc` + 自定义 ROS 节点 + tshark，不含 SROS2 日志）。
   → **访问控制日志必须自建采集**：以 `ros2/sros2` 的公开权限样本
   （`sros2/test/policies/permissions/*/permissions.xml`，Apache-2.0）为权限基线，
   在本项目 enclave 中故意发起越权 pub/sub 并采集原生拒绝日志。

5. **不能直接证明网络攻击的多模态数据**：
   - ROS2 Windrow、TUM RGB-D、KITTI、nuScenes、Hilti、SubT、GRIFFIN 等**均为正常数据**，
     无任何攻击标签，**不得**称为"多模态攻击检测数据集"；
   - UNILEON E2 的相机替换是**作者在受控实验中执行的感知攻击**，这是唯一可用于
     "感知异常 ↔ 通信"关联的真实同源数据；
   - **禁止**把 HCRL/ROSPaCe/RESILMESH 的 PCAP 与任意机器人视频拼接成"真实同步攻击数据"。

6. **许可证与分发限制（已尽可能核验）**：
   | 数据集 | 许可证 | 可否再分发 |
   | --- | --- | --- |
   | ROSPaCe | 数据 **CC0 1.0** / 集合与论文 **CC BY 4.0** / 代码 GPL-3.0 | ✅ 可（CC0 最宽松） |
   | UNILEON | **CC BY 4.0** | ✅ 可（需署名） |
   | ROSIDS23 | **CC BY 4.0** | ✅ 可（需署名） |
   | ROS2 Windrow | **CC BY 4.0** | ✅ 可（需署名） |
   | RESILMESH | **CC BY 4.0** | ✅ 可（需署名） |
   | **HCRL RTPS** | **CC BY-NC 4.0**（页面原文 "academic and non-commercial purposes only"）；IEEE 版需**付费订阅** | ⚠️ **仅限学术非商业**，不得用于商业展示 |
   | TUM RGB-D | **CC BY 4.0**（数据）/ BSD-2-Clause（代码） | ✅ 可（需署名）；但为 **ROS 1 bag** |
   | Hilti SLAM 2022 | **CC BY-NC-SA 3.0** | ⚠️ 禁商用 + 衍生须同许可 |
   | KITTI | **CC BY-NC-SA 3.0** | ⚠️ 禁商用 + 衍生须同许可 |

7. **本机网络出口限制**（影响工期）：Zenodo（记录页 200 但**文件下载 403**）、
   figshare（WAF challenge 202/403）、HuggingFace（超时）、
   Dropbox / Google Drive（**超时 HTTP 000**）、Kaggle（reCAPTCHA）、
   `raw.githubusercontent.com`（连接重置）、MDPI/ScienceDirect（403）、`docs.ros.org`（反爬）
   均不可自动下载；仅 `api.github.com`、`cpipc.acge.org.cn`、`ieee-dataport.org`、
   `pmc/nature`、`europepmc`、DataCite、`export.arxiv.org` 可用。
   **下载必须由人工在浏览器完成**，请在排期时预留。

8. **赛事合规待确认**：官方通知**未明文规定**能否使用公开数据集
   （对"数据""数据集""伦理""隐私""个人信息"全文零命中）。建议在作品文档中主动声明
   数据来源与许可证，并在必要时向组委会书面确认（葛景全 `gejingquan@hit.edu.cn`）。
   注意 **HCRL 的 CC BY-NC 禁商用条款**与赛事"不违反法律法规、无侵害他人合法权益"的要求需一并说明。

9. **契约未冻结的影响**：接口仍为 `PROPOSED_V1`。若 Q2「`anomaly_category` 细粒度」在评审中扩展，
   属**破坏性变更**，本报告的映射表需同步修订。

10. **本次未能核实的事项（不猜测）**：
    - HCRL 论文 Table 1（攻击者 pcap 2,948）与 §7.1 正文（240）**矛盾未能判定**；
    - ROSPaCe 列数（README 482 vs 论文 481）、体积口径（38 / 37.46 / 40.2 GB）**冲突未能判定**；
    - ROSPaCe 的 **DDS 实现厂商**论文未写明 → 未能核实，**不得假定为 Fast DDS**；
    - UNILEON 的 rosbag 具体是 rosbag2 `.db3` 还是 MCAP、ROS 2 发行版与 DDS 厂商 → **未能核实**；
    - RUBICON（Zenodo 23194894）描述未提 ROS/DDS → **相关性未能核实**，未列入推荐。

---

## 附录：本次实测验证清单

| 验证项 | 结果 | 证据位置 |
| --- | --- | --- |
| 赛事截止日期 2026-10-22 | ✅ 已核实 | `verify_huawei_5th_cyber/01_official_invitation_letter.html` |
| 赛事主题"智融攻防，实战育才" | ✅ 已核实 | 同上 |
| 评审要点为 5 项（无"安全意义"） | ✅ 已核实（**任务书需修正**） | 同上 |
| rosbag2 MCAP 写入 | ✅ 118 条 / 15.31 s | `ros:jazzy` 容器实测 |
| rosbag2 回放 + rclpy 订阅 | ✅ 39 条消息 | `ros:jazzy` 容器实测 |
| RTPS 抓包 + 字段提取 | ✅ 64 包 | `data/access_probes/rtps.pcap`、`rtps.tsv` |
| PCAP → CommRiskEvidence | ✅ 通过严格 Schema 校验 | `scripts/data_provisioning/pcap_to_commrisk.py` |
| 无基线时输出 UNKNOWN（非 NORMAL） | ✅ 通过 | 同上（T1） |
| 空输入输出 UNKNOWN（非 NORMAL） | ✅ 通过 | 同上（T3） |
| tshark / scapy / pandas 供应 | ✅ 经 apt 可用 | `scripts/data_provisioning/README.md` |
| 容器内 pip 不可用 | ✅ 已复现并记录 | 同上 |
| Zenodo / figshare 下载受限 | ✅ 已落盘证据 | `data/access_probes/zenodo_403_experiment1.html` |
| ROSIDS23 为 ROS 1（含 "ROS master"） | ✅ 已核验 | `Data in Brief` DOI 10.1016/j.dib.2023.109739（Europe PMC 全文） |
| ROSPaCe 许可（CC0 / CC BY 4.0） | ✅ 已核验 | DataCite REST API；[Nature 论文页](https://www.nature.com/articles/s41597-024-03311-2) |
| HCRL 为 CC BY-NC 4.0 | ✅ 已核验 | [HCRL 数据说明页](https://ocslab.hksecurity.net/Datasets/rtps-attack-dataset) 原文 |
| SROS 2 访问控制日志数据集不存在 | ✅ 已系统检索确认 | `docs/research/ros2_dds_security_dataset_verification_2026-10-11.md` §4 |
| **ROSPaCe 精简版实际下载并解压** | ✅ 25 个 CSV 字节数与清单完全一致 | `data/ROSPaCe_reduced/` |
| **ROSPaCe 精简版标签/规模实测** | ✅ 28,219,113 行；标签为 `observe`+6 类攻击 | 本报告 §D.3 |
| **ROSPaCe 按 block 切分** | ✅ 918 个 block，全部单一标签；首块 29.97 s | `data/ROSPaCe_reduced/windows_0.jsonl` |
| **转换器两次真实数据误报修正** | ✅ 已修正并回归通过（T1–T5） | `scripts/data_provisioning/README.md` §4 |

> **配套详细核查记录**：逐链接的原始核查明细（含 HTTP 状态、DataCite/Zenodo/Europe PMC API 返回、
> 每个数据集的完整字段与"未能核实"清单）见
> [ros2_dds_security_dataset_verification_2026-10-11.md](ros2_dds_security_dataset_verification_2026-10-11.md)。
>
> **说明**：上表全部为本报告作者在 2026-10-11 实际执行的验证与联网核查，
> 不包含任何 Mock 数据结论，也不代表对任何第三方系统实施过攻击。
> 所有攻击相关数据均来自**数据集作者已公开发表的受控实验**，或本项目自有环境。
