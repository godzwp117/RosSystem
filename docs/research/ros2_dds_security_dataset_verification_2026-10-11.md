# ROS 2 / DDS 网络安全公开数据集核查报告

- 核查日期：**2026-10-11（UTC）**
- 核查方式：对每个 URL 逐个真实发起访问（HTML 抓取 + `curl` HTTP 状态码实测），并用官方 API 交叉验证元数据：GitHub REST API、DataCite REST API、Zenodo REST API、Crossref、Europe PMC、IEEE DataPort 页面
- 原则：**只写实测到的内容**；链接打不开、页面被拦截、字段看不到的，一律标注「链接失效 / 未能核实」，不做推测

---

## 0. 核查环境限制（先说清楚哪些 URL 我"真的没能访问"）

| 站点 | 实测结果 | 对核查的影响 |
| --- | --- | --- |
| `springernature.figshare.com` / `figshare.com` / `api.figshare.com` | HTML 页面返回 **HTTP 202**（AWS WAF JS 挑战，空响应体）；API 与 `ndownloader` 路径返回 **HTTP 403** | ROSPaCe 的 figshare 落地页与下载页**无法在本环境渲染**。其条目 URL、字节数、许可证、日期改用 **DataCite REST API（HTTP 200）**核实（DataCite 记录里就是 figshare 的 URL/大小/许可） |
| `zenodo.org` | 记录页 / 文件预览页 / API JSON **HTTP 200**；但用 `curl` 直接下载文件（含 1.6 MB 的小文件）返回 **HTTP 403**（Cloudflare 拦数据中心客户端） | Zenodo 上的数据集**元数据与文件清单已核实**，但压缩包内容**未能解包核验** |
| `dropbox.com` / `drive.google.com` | 连接超时（**HTTP 000**，20–45 s） | HCRL 的 Dropbox 下载直链**未能实测** |
| `kaggle.com` | 搜索 API 与数据集页返回 **reCAPTCHA 挑战页** | 仅通过 DataCite 核实其 DOI 记录 |
| `docs.ros.org` | 多个候选 URL 均返回 `Making sure you're not a bot!` 验证页 | ROS 2 官方安全教程正文**未能核实**；改用 `ros2/sros2` 仓库文件树作为权限样本证据 |
| `mdpi.com` / `sciencedirect.com` | **HTTP 403** | 相关论文正文改用 Europe PMC 全文 XML / Crossref 元数据核实 |

---

## 1. ROSPaCe（figshare 集合标题写作 "ROSpace"）

| 项目 | 核查结果 |
| --- | --- |
| **正式名称** | 论文名：*ROSPaCe: Intrusion Detection Dataset for a ROS2-Based Cyber-Physical System and IoT Networks*；figshare 集合名：*ROSpace: Intrusion Detection Dataset for a ROS2-Based Cyber-Physical System*（两处拼写不一致，如实并列） |
| **发布单位 / 通讯作者** | 意大利特伦托大学（University of Trento, Via Sommarive 9, 38124 Trento, Italy）。作者：**Tommaso Puccetti（通讯作者）**、Simone Nardi、Cosimo Cinquilli、Tommaso Zoppi、Andrea Ceccarelli |
| **官方介绍页 URL** | ① GitHub：<https://github.com/tommasopuccetti/rospace_dataset> — **HTTP 200**，README 已完整读取（仓库描述：*"This repository includes all the codes used for the paper"*，即**代码仓库**，数据在 figshare）<br>② figshare 集合：<https://springernature.figshare.com/collections/ROSpace_Intrusion_Detection_Dataset_for_a_ROS2-Based_Cyber-Physical_System/6924364> — **HTTP 202（AWS WAF 挑战，未能渲染）** |
| **实际下载 URL（逐条分开）** | 全部为 figshare 条目（URL 与大小来自 DataCite 记录 `api.datacite.org`，HTTP 200）。**本环境未能真正发起下载**：<br>• `ROSPaCe_complete` <https://springernature.figshare.com/articles/dataset/ROSPaCe_complete/25594347> — 40,226,661,349 B ≈ **40.2 GB**（DOI 10.6084/m9.figshare.25594347）<br>• `ROSPaCe_reduced` <https://springernature.figshare.com/articles/dataset/ROSPaCe_reduced/25594860> — 920,868,855 B（DOI 10.6084/m9.figshare.25594860）<br>• `ROSPaCe_reduced_noperiodicity` <https://springernature.figshare.com/articles/dataset/ROSPaCe_reduced_noperiodicity/25594854> — 697,155,970 B<br>• `ROSPaCe_complete_noperiodicity` <https://springernature.figshare.com/articles/dataset/ROSPaCe_complete_noperiodicity/25604433> — 27,651,002,892 B ≈ **27.7 GB**<br>• `tshark_pcaps` <https://springernature.figshare.com/articles/dataset/tshark_pcaps/25605789> — 6,439,516,604 B ≈ **6.4 GB**<br>• `feature_list` <https://springernature.figshare.com/articles/dataset/feature_list/24542824> — 29,271 B<br>集合 DOI：`10.6084/m9.figshare.c.6924364`（DataCite：Created 2024-05-03，Updated 2024-05-06） |
| **配套论文** | arXiv：<https://arxiv.org/abs/2402.08468>（2024-02-13 提交，DOI 10.48550/arXiv.2402.08468，**HTTP 200**）<br>期刊版：*Scientific Data* **11, 481 (2024)**，DOI <https://doi.org/10.1038/s41597-024-03311-2>（10.1038/s41597-024-03311-2）<br>全文（已读取正文，含 Data Records 与 Methods）：<https://pmc.ncbi.nlm.nih.gov/articles/PMC11087584/> 及 Europe PMC 全文 XML（均 HTTP 200） |
| **实际数据文件格式（含出处）** | • **CSV**：DataCite 条目摘要写 *"encoded in the ROSPaCe_complete.csv file"*；论文 Data Records 写完整集为 `ROSPaCe_complete.csv`，精简版拆成 15 个 CSV，非周期版压缩包内含 10 个 1 GB 文件<br>• **pcap**：`tshark_pcaps` 条目的 DataCite 摘要写 *"The .pcap files collected during the experimental campaign of ROSPaCe"*；论文写原始抓包为 `.pcap`/`.pcapng`（Tshark 采集），随后转 JSON/CSV<br>• **xlsx**：论文正文写明 *"available as a .xlsx file in the dataset repository (feature_list.xlsx)"*<br>• **没有 rosbag2 / MCAP**：论文明确写 ROS Monitor 节点刻意不用 `/rosout` 的 bag 记录（*"Producing a bag file is invasive and burdensome"*），GitHub 仓库文件树（`api.github.com/.../git/trees/HEAD?recursive=1`，truncated=false）中也无 `.db3`/`.mcap` 文件 |
| **数据规模** | **30,247,050 行**；列数：README 写 *"482 columns excluding the label"*，论文 Data Records 写 *"481 columns excluding the label"*（**两处不一致，如实并列**）；4 天实验；**78% 攻击 / 22% 正常**（约 2300 万攻击点、650 万+正常点）；体积：论文 38 GB / DataCite 摘要 37.46 GB / DataCite 字节数 40.2 GB（口径不同） |
| **标签** | **有**。每行一个 label：`normal` 或具体攻击名（论文原话：*"we label each data point indicating if it is recorded during the normal (attack-free) operation, or while the system is under attack"*）。标签粒度＝**逐行（数据点）**，且数据集按时间序列排列"正常段 ↔ 攻击段"交替，可用于测量检测时延 |
| **攻击类型清单（6 种，3 种 ROS2 特有）** | ① Nmap Discovery（发现类）② **ROS2 Reconnaissance**（ROS2/DDS 特有，发现类）③ Flooding Meta（DoS）④ Flooding Nmap（DoS）⑤ **ROS2 Node Crashing**（ROS2/DDS 特有，DoS）⑥ **ROS2 Reflection**（ROS2/DDS 特有，DoS） |
| **许可证与再分发** | 论文：**CC BY 4.0**；figshare 集合：**CC BY 4.0**；各数据条目（complete / reduced / noperiodicity / pcaps / feature_list）：**CC0 1.0**（DataCite `rightsList` 实测）；GitHub 代码仓库：**GPL-3.0**（GitHub API `license.spdx_id` 实测）。CC0/CC BY → 再分发限制很低，署名即可 |
| **下载门槛** | 公开条目（figshare 公共数据集）。**本环境因 AWS WAF 无法实测"是否需要账号"**，标注为：公开、无需申请的官方说明未直接读到 → **未能实测确认** |
| **最近可访问性** | GitHub 仓库 HTTP 200，`created_at 2023-08-30`、`pushed_at 2025-12-23`（GitHub API）；figshare/DataCite 记录更新日期 2024-05-06 |
| **迁移限制** | ROS 2 **Foxy** + Ubuntu 20.04（论文实测）；**中间件厂商未写明**（论文只写 DDS；我 grep 了 Fast DDS / Cyclone / FastRTPS 均无命中）→ 具体 DDS 实现**未能核实**；ROS 语义特征只有 **5 个**（`src_topic`、`subscribers_count`、`publisher_count`、`msg_type`、`msg_data`），其余 452 个是 Tshark 网络特征、25 个是 Linux `/proc` 特征；无 rosbag；不保留消息 payload |

---

## 2. HCRL RTPS Attack Dataset

| 项目 | 核查结果 |
| --- | --- |
| **正式名称 / 发布单位 / 联系人** | *RTPS ATTACK DATASET*（IEEE DataPort 标题：*Real-Time Publish Subscribe ATTACK DATASET*）。**高丽大学（Korea University）Hacking and Countermeasure Research Lab (HCRL), School of Cybersecurity**。联系人：**Dong Young Kim（klgh1256@korea.ac.kr）**、**Huy Kang Kim（cenda@korea.ac.kr）** |
| **官方介绍页 URL** | <https://ocslab.hksecurity.net/Datasets/rtps-attack-dataset> — **HTTP 200**，2026-10-11 抓取到完整正文（含 INTRODUCTION / PUBLICATION / DATASET DESCRIPTION / DOWNLOAD / CONTACT 五节） |
| **实际下载 URL** | ① 页面第 4 节 "Download Link : Download" 指向 **Dropbox**：`RTPS_ATTACK_DATASET.zip`（`https://www.dropbox.com/scl/fi/5duy7qzotlt0axk9cxdr7/RTPS_ATTACK_DATASET.zip?rlkey=...`）→ **本环境连接超时（HTTP 000），未能实测**<br>② **IEEE DataPort**：<https://ieee-dataport.org/documents/real-time-publish-subscribe-attack-dataset> — **HTTP 200**；页面明确显示 `LOGIN TO ACCESS DATASET FILES` 与 `Subscription Required`，文件为 `RTPS_ATTACK_DATASET.zip (Size: 284.13 MB)`；DOI **10.21227/ffta-jy18**；页面 Date Created **2025-11-19** |
| **配套论文** | arXiv：<https://arxiv.org/abs/2311.14496>（**HTTP 200**；v4 = 2024-04-02；arXiv 许可证 **CC BY-NC-ND 4.0**；Comments 明确写 *"This manuscript is written in Korean"*）<br>HTML 全文（已读取第 7 节 Dataset Information）：<https://arxiv.org/html/2311.14496v4><br>另有韩文技术报告 PDF（Dropbox，未能访问） |
| **实际数据文件格式（含出处）** | 来源：HCRL 页面第 3 节 + arXiv 7.2 节<br>• **.pcap**：机器人（受害）侧 `[number].pcap`；攻击者侧 `_labeled_[number].pcap`<br>• **.csv**：标签文件，字段含 `Time`、`Source IP / Destination IP`、`Source MAC / Destination MAC`、RTPS 子消息值（如 INFO_TS、writerEntity）、`ARP Opcode`，以及两个标签字段<br>• **无 rosbag2** |
| **数据规模** | 采集时长 180 / 300 / 600 / 1200 秒，每档 **30 个场景**，共 **240 个场景**。论文 Table 1：机器人 pcap 240 个（1,068.2 MB）、攻击 pcap **2,948** 个（124.9 MB）、标签文件 8 个（3,148.7 MB）、合计 **3,196 个文件 / 4,341.8 MB**（注：论文 7.1 节正文写 *"240 files"* 与 Table 1 的 2,948 不一致，如实并列）。IEEE DataPort 版本压缩包 **284.13 MB** |
| **标签** | **有，逐包、双标签**：`Command Injection`(0/1) 与 `ARP Spoofing`(0/1)。判定方法（论文 6.4 节）：比对 INFO_TS、writerEntity、UDP checksum、源/目的 IP；ARP 侧检查 Opcode=2 且源 MAC 为攻击者 MAC |
| **攻击类型清单** | ① **Command Injection**（含两个子模式：**Flooding** 固定数据洪泛、**Fuzzing** 随机数据）② **Command Injection + ARP Spoofing** |
| **许可证与再分发** | HCRL 页面第 4 节原文：*"We share datasets for both academic and non-commercial purposes only. Also, This dataset follows 'CC BY-NC' Creative Commons Licenses."* → **CC BY-NC 4.0，禁止商用**；同时 IEEE DataPort 版本要求**付费订阅**才能取文件（两处口径不同，值得注意） |
| **下载门槛** | 无申请表单：Dropbox 直链（页面公开）或 IEEE DataPort **订阅**。**未见邮箱审批流程** |
| **最近可访问性** | HCRL 页面 2026-10-11 **HTTP 200**；站点左侧数据集列表已包含 *"UAVCAN Attack Dataset 2026 (LUMI)"*，说明站点 2026 年仍在维护；IEEE DataPort 页面 200、创建于 2025-11-19 |
| **迁移限制** | ROS 2 **Foxy** + **Fast-DDS**（论文原文：*"This product was equipped with ROS2, and Fast-DDS uses RTPS as its communication protocol"*；IEEE DataPort 摘要也写 "ROS2 and Fast-DDS environments"）；受害机器人为 **Stella N1**（Raspberry Pi 4B，Raspbian）；**纯网络层（RTPS/ARP）流量，无 ROS 语义特征**；测试台路由器不连外网 |

---

## 3. 其他 ROS / ROS 2 / DDS 安全数据集（本次主动搜索并逐个核实）

### 3.1 ROSIDS23（ROS 1，注意迁移限制）

| 项目 | 核查结果 |
| --- | --- |
| 名称 / 单位 / 通讯作者 | **ROSIDS23: Network intrusion detection dataset for robot operating system**；土耳其 Eskişehir Osmangazi University 计算机工程系（IFARLab-DIH 实验室）；**通讯作者 Elif Değirmenci（edegirmenci@ogu.edu.tr）**，ORCID 0000-0001-8772-4543；合作者 Yunus Sabri Kırca、İlker Özçelik、Ahmet Yazıcı |
| 介绍页 / 下载页 | ① Zenodo 记录页 <https://zenodo.org/records/10014434> — **HTTP 200**（文件清单已核实）② Zenodo API <https://zenodo.org/api/records/10014434> — **HTTP 200** ③ Kaggle 镜像 DOI `10.34740/kaggle/dsv/6683233`（DataCite 记录核实；Kaggle 页面因 reCAPTCHA 未能渲染） |
| 实际下载 URL | 记录页逐文件直链（全部公开）：`processed.zip`(93.4 MB)、`ROSIDS23.csv`(72.5 MB)、`raw_noattack.zip`(879.3 MB)、`raw_DoS.zip`(1.2 GB)、`raw_subscriberflood.zip`(950.2 MB)、`raw_unauthorizedpublisher.zip`(395.5 MB)、`raw_unauthorizedsubscriber.zip`(530.5 MB)。**本环境 `curl` 下载返回 HTTP 403（Cloudflare），文件内容未能解包核验** |
| 配套论文 | *Data in Brief* 2023，**DOI 10.1016/j.dib.2023.109739**（Crossref 已核实；PMC10654526，**CC BY**，2023-10-17 上线） |
| 文件格式 | **pcap（tcpdump 原始抓包）+ CSV（CICFlowMeter 提取的流特征）**。出处：论文正文 *"Benign and attack traffic was collected via tcpdump in pcap format. The CICFlowMeter tool was employed to extract traffic features and assign labels"* |
| 规模 | Zenodo 记录页 Files **4.1 GB / 7 个文件**；CSV 为 **83 特征 + label** 的多分类数据集，记录数：benign **62,511**、DoS **31,000**、subscriber flood **30,064**、unauthorized subscribe **5,289**、unauthorized publish **7,817** |
| 标签 | **有，多分类 5 类**：`Benign, DoS, Unauthorized Publish, Unauthorized Subscribe, Subscriber Flood`（论文 Table 1 + 正文实测） |
| 许可证 | **CC BY 4.0**（Zenodo 记录页 rights 与论文页脚均实测） |
| 下载门槛 | **完全公开直链，无需注册/申请**（Zenodo open access） |
| 可访问性 | 记录页 2026-10-11 HTTP 200；Published 2023-10-17，无更新（Created/Modified 均 2023-10-17）；下载量 2,120 次 |
| **迁移限制（重要）** | **ROS 1**：论文正文写受害网络包含 *"a switch, robotic arm, controller device, and a **ROS master**"*（ROS master 是 ROS 1 独有概念），未提 ROS 2 / DDS。→ **不可直接迁移为 ROS 2/DDS 检测基准**；只有网络流特征，无 ROS 语义特征 |
| 生态活跃度（旁证） | MDPI *Electronics* 2026, 15(12):2707《Topology-Independent SHAP-Based Explainable Intrusion Detection for ROS Networks》(DOI 10.3390/electronics15122707，Crossref 已核实) 仍以 ROSIDS23 为评测集，说明该数据集 2026 年仍被使用 |

### 3.2 "Simulated attacks Rosbags against mobile robot in ROS 2"（本次找到的 **rosbag 格式** ROS 2 攻击数据）

| 项目 | 核查结果 |
| --- | --- |
| 名称 / 单位 / 作者 | **Simulated attacks Rosbags against mobile robot in ROS 2**；**Universidad de León（西班牙莱昂大学）Robotics Group**；**David Sobrín Hidalgo（联系人，ORCID 0009-0005-7673-5921）** |
| 介绍页 / 下载页 | <https://zenodo.org/records/17649537> — **HTTP 200** |
| 实际下载 URL | `Experiment_1.zip`（1.6 MB）与 `Experiment_2.zip`（3.1 GB），均为记录页公开直链；**本环境 curl 下载 403，未能解包核验** |
| 配套论文 | **未见配套论文**（记录页无 related work 指向论文；资助：TESCAC 项目 / INCIBE / EU NextGeneration-EU） |
| 文件格式 | 记录页描述原文 *"several **rosbag files** recorded during the execution of two proof-of-concept experiments"*。**具体是 rosbag2 的 `.db3`+`metadata.yaml` 还是 MCAP，压缩包内文件未能核实** |
| 规模 | Files **3.1 GB**（记录页显示 Data volume 53.1 GB，口径不同）；实验 1：2 次运行；实验 2：3 次运行（每次 2 个 bag：`full_rosbag` + `camera_descriptions`） |
| 标签 | **有，但粒度为"整段运行"**：`E1-1` 正常、`E1-2` 攻击；`E2-1` 正常、`E2-2`/`E2-3` 攻击。**无逐消息标签** |
| 攻击类型 | ① DoS：以 **500 Hz** 向 `/input_joy/cmd_vel` 洪泛值为 0 的速度指令；② 相机图像替换（用室外图 / 走廊图替换室内原图，含 VLM 生成的图像文本描述） |
| 许可证 | **CC BY 4.0** |
| 下载门槛 | **公开直链，无需注册** |
| 可访问性 | 页面 2026-10-11 HTTP 200；Published **2025-11-19**；下载 37 次 |
| 迁移限制 | ROS 2（关键词含 "ros 2"），但**发行版与 DDS 中间件均未写明 → 未能核实**；含真实 ROS 语义数据（话题、图像消息、cmd_vel），是本清单中**唯一提供 rosbag 级 ROS 2 安全实验数据**的公开集；攻击面偏"应用/感知层"（话题洪泛、相机欺骗），不是 DDS 协议层攻击 |

### 3.3 RESILMESH – ALIAS – Pilot2（含 **ROS 2 Foxy pcap + ROS2 DDS Injection 攻击**）

| 项目 | 核查结果 |
| --- | --- |
| 名称 / 单位 / 作者 | **RESILMESH - ALIAS - Pilot2 - 40min & 8 attacks**；Zenodo 社区 **Resilmesh_Platform_Project**（欧盟 Horizon Europe Resilmesh 项目，GA 101119681）；作者 **Paul Zabalegui** |
| 介绍页 / 下载页 | <https://zenodo.org/records/20729823> — **HTTP 200** |
| 实际下载 URL | 记录页直链：`ros2_foxy.pcap`(729.6 MB)、`ros_noetic.pcap`(888.6 MB)、`openplc.pcap`(269.2 MB)、`ur_dashboard.pcap`(335.4 MB)、4 个 `*_snmp.csv`、`ur_coordinates.csv`、`attack_history.csv`(767 B)、`attack_timeline.md`(3.9 kB)、`file_timestamps.md`。**pcap 未能下载核验；但两个小文本文件已通过 Zenodo 预览接口读取全文** |
| 配套论文 | 记录页**未给论文**；属 Resilmesh 项目交付物 |
| 文件格式 | pcap（tcpdump，按容器拆分）+ CSV（SNMP 每 5 s、UR 坐标每 5 s）+ Markdown/CSV 攻击时间线 |
| 数据规模 | 记录页 Files **2.9 GB**（Data volume 5.1 GB）；采集窗口 `2026-06-16T17:55:03Z → 18:30:20Z`（约 35 分 17 秒），含 8 次攻击 |
| 标签 | **有时间窗标签**：`attack_history.csv`（机器可读攻击窗口）+ `attack_timeline.md` 列出每次攻击的脚本、目标、起止 UTC 时间与是否被检出（6/8 检出）。**非逐包标签** |
| 攻击类型 | 8 种：Default Credentials、Network Scan(nmap)、**ROS1 XML-RPC Injection**、**ROS2 DDS Injection（目标 `172.19.0.4:7400`，即 RTPS 端口）**、Modbus Write、**ROS Bridge DoS**、UR Dashboard Injection、**ROS Parameter Hijacking** |
| 许可证 | **CC BY 4.0** |
| 下载门槛 | **公开直链，无需注册** |
| 可访问性 | 页面 2026-10-11 HTTP 200；Published **2026-06-17**（很新） |
| 迁移限制 | 混合 IT/OT/机器人靶场：ROS 1 Noetic 容器 + **ROS 2 Foxy** 容器 + OpenPLC + UR 机器人仿真；**纯 pcap/SNMP，无 ROS 语义数据，无 rosbag**；ROS 2 相关攻击仅 1 条（DDS Injection），样本量偏小 |

### 3.4 ROS2 Security Experimental Data（**不是流量数据集**，是源码分析/模型检验工件）

| 项目 | 核查结果 |
| --- | --- |
| 名称 / 作者 | *ROS2 Security Experimental Data*；创建者署名为 **Anonymous**（匿名上传）；版本 v0.3 |
| 介绍页 / 下载页 | <https://zenodo.org/records/6984492> — **HTTP 200**（概念 DOI 10.5281/zenodo.6746383） |
| 文件 | 8 个文件共 72.5 MB：`Code Property Graph Details.pdf`、`Model Checking Details.txt`、`error_handling_labels.txt`、`source_cpg_rcl.zip`、`source_cpg_rcl_cpp.zip`、`source_cpg_rmw.zip`、`source_cpg_rmw_fastrtps.zip`、`summarized_dots.zip` |
| 配套论文 | 记录页明确写这是投稿 **"On the (In)Security of Secure ROS2"** 的支持材料；该论文为 **ACM CCS 2022**，DOI **10.1145/3548606.3560681**（Crossref 已核实） |
| 许可 / 门槛 | **CC BY 4.0**；公开直链 |
| 可访问性 | 页面 200；Published 2022-06-26，Modified 2024-07-16；记录注明 *"materials are for revision and not finalized"* |
| 与 DDS 安全的关系 | 覆盖 `rmw` / `rmw_fastrtps` 的代码属性图与模型检验结果，与 **SROS2 / DDS-Security 实现缺陷**直接相关；但**不含网络流量、不含权限配置样本、不含访问控制日志**，不能当 IDS 训练数据 |

### 3.5 RUBICON Research Dataset（工业机器人 UEBA；ROS/DDS 相关性未能核实）

| 项目 | 核查结果 |
| --- | --- |
| 名称 / 单位 | *RUBICON Research Dataset: Robotics UEBA for Industrial Cyber Operations and Networks*；Obsidian Innovation Institute – Associação、Nevuli Unipessoal Lda.；欧盟 Resilmesh Open Call #2 资助 |
| 介绍页 / 下载页 | <https://zenodo.org/records/23194894> — **HTTP 200**；单文件 `rubicon_dataset_package.zip`（29.0 MB） |
| 规模 / 标签 | r10 研究包：**169,426 事件 / 92 次运行 / 354 条标注**；E24 验证补充：**81,994 事件 / 198 次运行 / 826 条标注**；含"labelled behavioural sequences"、网络流与抓包材料、schema、数据卡与 codebook |
| 设备 | DOBOT Nova 2 Industry 协作机器人、Waveshare RoArm-M2-S、AgileX Tracer 2.0、Waveshare UGV Beast |
| 许可 / 门槛 | **CC BY-NC 4.0**（禁商用）；公开直链 |
| 可访问性 | 页面 2026-10-11 HTTP 200；Published **2026-10-06**  |
| **迁移限制 / 未核实项** | 记录页描述**完全未提 ROS 1/ROS 2/DDS** → **是否包含 ROS 2 / DDS 流量未能核实**；如需使用必须先下载 `rubicon_dataset_package.zip` 检查。采集期 2026-08-17 ~ 2026-09-27 |

### 3.6 相关但**不是数据集**的公开工件（避免误当作数据集引用）

| 工件 | 实测内容 |
| --- | --- |
| `attack_error_latencies`（figshare，**非** Springer Nature 域） | DOI `10.6084/m9.figshare.26808259`，1,228,171,653 B（≈1.2 GB），**Apache-2.0**，创建者 Tommaso Puccetti；DataCite 摘要写明是论文 *"Detection Latencies of Anomaly Detectors: An Overlooked Perspective?"* 的代码/序列数据，**输入是 ROSPaCe 与 Arancino 两个已有数据集**。→ 它是 ROSPaCe 的**衍生产物**，不是新数据集；figshare 页面本环境不可渲染（WAF） |
| `Timsmall94/CPS-Intrusion-Detection`（GitHub） | 描述原文 *"Machine learning-based intrusion detection research for ROS2 cyber-physical systems using the ROSPaCe dataset"*；仅 10 个文件（脚本 + 结果图 + `experiment_results.csv`），**无自有数据**，无 LICENSE |
| `SandyDash19/Intrusion-Detection-Latency-The-Neglected-Metric` | 2 个文件（`ADL_ROSPaCe`、README），论文表格复现代码，**无数据** |
| `fgaranda/cavecanem`（GitHub） | *"extensible monitoring and intrusion detection system based on the … DDS standard"*，**LGPL-3.0**，最后 push **2017-11-09**（已停更）；仓库树中无数据集文件 → **DDS IDS 软件，不是数据集** |
| 明确排除（非 DDS/ROS 2） | HCRL 的 `MAVLink Message ID Sequence Dataset`、`UAVCAN Attack Dataset`（机器人总线/无人机协议，非 DDS）；`CarDS`（athene-center：*Controller Area Network and Automotive Ethernet Realistic Data Set*，CAN/车载以太网，非 DDS） |

---

## 4. SROS 2 permissions / DDS-Security 访问控制：样本 vs 日志

### (A) 已核实的**公开权限/策略配置文件样本**（是配置文件，不是日志）

| 来源 | 实测内容 | 许可 |
| --- | --- | --- |
| **`ros2/sros2`**（官方 SROS 2 工具仓库）<https://github.com/ros2/sros2> | GitHub API 文件树（132 项，truncated=false）实测存在：<br>• `sros2/test/policies/permissions/{add_two_ints, minimal_action, sample, single_context, talker_listener}/permissions.xml`（例：`sample/permissions.xml` 21,635 B）<br>• `sros2/test/policies/*.policy.xml`（策略源文件，如 `talker_listener.policy.xml` 已读取全文，含 `<enclave path="/talker_listener/talker">` 与 `<topics publish="ALLOW"><topic>chatter</topic>`）<br>• `sros2/sros2/policy/defaults/dds/governance.xml`（**已读取全文**：DDS-Security governance，domain 0，`enable_join_access_control=true`，`discovery/liveliness=ENCRYPT`、`rtps=SIGN`，读写访问控制全开）<br>• `sros2/sros2/policy/defaults/policy.xml`、`schemas/dds/{governance,permissions}.xsd`、`templates/dds/permissions.xsl`、`verb/create_keystore.py`、`verb/create_permission.py` | **Apache-2.0**（GitHub API 实测）；仓库 `pushed_at 2026-10-07` |
| **`OpenDDS/OpenDDS`** DDS-Security 测试 | 已通过 GitHub API 读取 `tests/security/SingleParticipantWithSecurity/governance.xml`（DDS-3.20 分支，1,439 B；内容含 *"Domain 4 is an 'open domain'"*、`allow_unauthenticated_participants=true`）。同类 `tests/security/**` 下还有更多 governance/permissions 样例 | 仓库 license 为 `NOASSERTION`（**具体许可未能核实**）；仓库 `pushed_at 2026-10-08`，1,517 stars |
| ROS 2 官方安全教程 | `docs.ros.org` 对本环境返回反爬验证页 → **正文未能核实**（无法确认教程里是否附带 demo 权限文件的具体路径） | — |

> 结论（区分概念）：这些是**"权限/治理策略配置文件样本"**，可用于测试 `sros2` 工具链、验证 DDS-Security 插件行为；它们**不是**任何真实系统的访问控制运行记录。

### (B) **访问控制日志类数据集：未发现（明确结论）**

本次核查未找到任何公开的"SROS 2 权限拒绝事件 / DDS-Security 认证失败 / 访问控制日志"数据集。核查动作与证据：

1. DataCite 全库检索 `SROS2` → 命中 **4 条**，全部是论文/预印本（arXiv:2208.02615 *SROS2: Usable Cyber Security Tools for ROS 2*、arXiv:2308.16482、以及两条 2026 年 Zenodo 文本），**无数据集**。
2. GitHub 仓库检索 `ROS2 security dataset` → `total_count = 0`；`rosbag2 security` → `0`；`DDS intrusion detection` → 3 个仓库，其中只有 `cavecanem`（DDS IDS 软件，2017 停更，无数据）。
3. DataCite 数据集检索 `DDS security intrusion` → `total = 0`。
4. Zenodo / DataCite 上以 ROS/DDS 安全为主题的数据集，只有本报告第 1–3 节列出的那些（ROSPaCe、HCRL RTPS、ROSIDS23、ROS 2 rosbags、RESILMESH、RUBICON 等），其中**均未包含 SROS2 访问控制日志**（ROSPaCe 的监视器是 `/proc` + 自定义 ROS 监视节点 + tshark，论文未提 SROS2 日志）。
5. ROS 2 Discourse / ROS Answers 检索未得到任何附带日志数据的帖子（仅返回 ROSCon SROS 幻灯片、OpenDDS 测试配置等技术文档）。

> 若项目需要"访问控制日志数据集"，现实做法是：**自己搭建 SROS 2 enclave + 故意越权发布/订阅，采集 DDS-Security 插件与 `sros2` 侧日志**，并以 `ros2/sros2` 的 `test/policies/permissions/*/permissions.xml` 作为权限配置基线。

---

## 5. 汇总表

| # | 数据集 | 发布方 | ROS 版本 / 中间件 | 格式 | 规模 | 攻击类型数 | 标签粒度 | 许可 | 下载门槛 | 本环境可访问性 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | **ROSPaCe**（ROSpace） | 特伦托大学（Puccetti 等） | **ROS 2 Foxy** / Ubuntu 20.04；DDS 具体实现**未能核实** | **CSV + pcap + xlsx**；**无 rosbag** | 30,247,050 行 × 481/482 列；complete **40.2 GB**、reduced 0.92 GB、no-periodicity 27.7 GB、pcaps 6.4 GB | **6**（3 种 ROS2/DDS 特有） | **逐行**（normal + 攻击名） | 数据 **CC0 1.0**；集合/论文 **CC BY 4.0**；代码 GPL-3.0 | 公开（**账号要求未能实测**） | GitHub 200；DataCite 200；**figshare 202/403（WAF）** |
| 2 | **HCRL RTPS Attack Dataset** | 高丽大学 HCRL | **ROS 2 Foxy + Fast-DDS** | **pcap + csv**；**无 rosbag** | 240 场景；3,196 文件 / 4,341.8 MB（论文）；IEEE 版 zip 284.13 MB | **2**（Command Injection、+ARP Spoofing；各含 Flooding/Fuzzing） | **逐包双标签**（0/1 × 2） | **CC BY-NC 4.0**（禁商用）；IEEE 版需订阅 | 公开 Dropbox 直链 / IEEE 订阅 | 页面 200；**Dropbox HTTP 000 超时**；IEEE 页面 200 |
| 3 | **ROSIDS23** | Eskişehir Osmangazi Univ. | **ROS 1**（ROS master） | **pcap + CICFlowMeter CSV** | 4.1 GB；137k 级记录（benign 62,511 / DoS 31,000 / flood 30,064 / unsub 5,289 / unpub 7,817） | **4** | **多分类 5 类**（按流） | **CC BY 4.0** | 公开直链 | 记录页 200；**文件下载 403** |
| 4 | **Simulated attacks Rosbags (ROS 2)** | Univ. de León（Sobrín Hidalgo） | ROS 2（发行版/中间件未写，**未能核实**） | **rosbag**（是否为 rosbag2 `.db3` 未核实） | 3.1 GB；5 次运行 | **2**（cmd_vel 洪泛 500 Hz、相机图像替换） | **整段运行**（无逐消息标签） | **CC BY 4.0** | 公开直链 | 页面 200；**文件下载 403** |
| 5 | **RESILMESH – ALIAS – Pilot2** | Resilmesh 项目（P. Zabalegui） | **ROS 2 Foxy + ROS 1 Noetic** 容器 | **pcap + SNMP/坐标 CSV + 时间线** | 2.9 GB；~35 min；8 次攻击 | **8**（含 **ROS2 DDS Injection**、ROS Bridge DoS、ROS Param Hijacking、ROS1 XML-RPC） | **攻击时间窗**（非逐包） | **CC BY 4.0** | 公开直链 | 页面 200；小文本文件预览已读全文 |
| 6 | **ROS2 Security Experimental Data** | 匿名（CCS 2022 论文工件） | ROS 2（`rmw_fastrtps` 源码分析） | PDF / TXT / ZIP（CPG） | 72.5 MB | 0（非流量数据集） | 无 | **CC BY 4.0** | 公开直链 | 页面 200 |
| 7 | **RUBICON** | Obsidian Innovation Inst. 等 | **未提 ROS/DDS → 未能核实** | ZIP（事件/标注/网络流+抓包） | 29 MB；169,426 + 81,994 事件 | 未分类说明 | 有标注（354 / 826 条） | **CC BY-NC 4.0** | 公开直链 | 页面 200 |

---

## 6. 明确「未能核实 / 链接失效 / 受限」清单

1. **figshare（ROSPaCe 全部下载页与数据条目）**：HTTP 202（WAF 挑战）/ 403 —— 落地页与下载页**未能渲染**，实际下载**未能发起**；条目 URL、字节数、许可证、日期来自 DataCite API（可信第三方权威元数据，但**不等同于我亲眼看到 figshare 页面**）。
2. **HCRL 的 Dropbox 直链**：HTTP 000 连接超时 —— **未能实测能否下载、文件结构与体积**。
3. **所有 Zenodo/figshare 大文件的内容**：均**未能解包核验**（403 WAF/Cloudflare），因此 3.2 节中"rosbag 具体格式（`.db3` vs MCAP）"、RESILMESH pcap 内部结构、RUBICON 是否含 ROS 2/DDS 流量，均标注为**未能核实**。
4. **ROSPaCe 的列数**：README 482 列 vs 论文 481 列，**两者不一致，未能判定哪个为准**。
5. **ROSPaCe 的体积口径**：论文 38 GB / DataCite 摘要 37.46 GB / DataCite 字节 40.2 GB；`ROSPaCe_reduced` 论文写 15 个 CSV 共 14.5 GB，而 DataCite 只给 920,868,855 B —— **文件清单与体积口径未能核实**。
6. **ROSPaCe 的 DDS 中间件厂商**：论文只写 "DDS"，检索 Fast DDS / Cyclone / FastRTPS 均无命中 —— **未能核实**。
7. **HCRL 论文 Table 1 与正文的文件数矛盾**（攻击 pcap 2,948 vs 正文 240）—— **未能核实**哪个正确。
8. **docs.ros.org 官方安全教程内容**：反爬验证页 —— **未能核实**。
9. **MDPI / ScienceDirect 正文**：HTTP 403 —— 相关结论均改由 Crossref / Europe PMC 元数据与摘要支撑。
10. **SROS 2 / DDS-Security 访问控制日志数据集**：**未发现任何公开数据集**（检索范围见 4(B)）；只能确认存在**权限配置文件样本**（ros2/sros2、OpenDDS 测试）。
