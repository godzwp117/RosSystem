# RosSystem 核心文献清单（A 级，16 篇）

> 核实日期：2026-10-22
> 元数据来源：Crossref（DOI 解析）+ 出版方/规范页面
> 摘要来源：Semantic Scholar / Crossref 记录的出版方摘要
> **阅读深度声明**：本轮对下列文献的核实级别为「元数据 + 出版方摘要」，除特别注明外
> **未获取全文**。因此本文只陈述摘要明确支持的内容，不转述未核实的实验细节或数字。
> 文献编号与 `references_ieee.md` / `references_gbt7714.md` 一致，citation key 与
> `references.bib` 一致。

分级说明：**A = 核心依据**（可直接支持研究背景、技术方案、研究差距或主要实验讨论）。

---

## A. ROS 2 / DDS 安全格局

### L01 · `white2018` — Procedurally Provisioned Access Control for Robotic Systems

- **作者 / 年份 / 来源**：R. White, H. I. Christensen, G. Caiazza, A. Cortesi，2018，IEEE/RSJ IROS 2018，pp. 1–9
- **DOI**：10.1109/IROS.2018.8594462
- **研究问题**：ROS 2 开始支持 Secure DDS 后，如何为机器人软件**程序化地供给访问控制策略**，而不是手工编写权限文件。
- **技术方法**：提出一个面向机器人软件的访问控制策略程序化供给框架；从节点接口/计算图推导策略，再映射到 DDS Security 的 governance/permissions 机制。
- **核心结论**（摘要支持）：ROS 2 以 Secure DDS 为目标，使安全部署成为可能；该工作给出了策略自动供给的框架，降低人工配置权限的成本与出错概率。
- **局限性**：策略对象是**参与者与资源**（topic/service 等），不是"某一次任务请求"；未涉及应用层请求内容与请求级身份。
- **与 RosSystem 的关系**：这是 RosSystem **第 1 层（DDS 资源权限）** 的直接技术前身。RosSystem 并未重新发明该层，而是把它当作既有能力使用（`scripts/setup_sros2.sh` 生成 CA/enclave/权限文件），并明确承认该层不能替代应用层判定。
- **建议引用位置**：Related Work「DDS 参与者认证与资源授权」；Introduction 说明 SROS 2 的定位。
- **核实级别**：Crossref 元数据 + 出版方摘要（arXiv:1810.08125 为同文预印本，未单独引用）。

### L02 · `vilches2022` — SROS2: Usable Cyber Security Tools for ROS 2

- **作者 / 年份 / 来源**：V. Mayoral-Vilches, R. White, G. Caiazza, M. Arguedas，2022，IEEE/RSJ IROS 2022，pp. 11253–11259
- **DOI**：10.1109/IROS47612.2022.9982129
- **研究问题**：如何让 ROS 2 的security 工具**可用**（usability-centric），使开发者能系统性地为计算图加密钥与权限。
- **技术方法**：SROS 2 工具链与库；以 DevSecOps 模式组织密钥生成、enclave 划分与策略分发。
- **核心结论**（摘要支持）：SROS 2 提供了一套系统性保护 ROS 2 计算图的开发者工具与方法论，强调可用性而非仅提供密码学原语。
- **局限性**：工具解决"如何正确配置通信安全"，不解决"某条应用请求是否应被执行为某个任务"；密钥生命周期仍依赖部署方。
- **与 RosSystem 的关系**：RosSystem 的 DDS 层直接复用 SROS 2 生态（`ros2 security` 生成的 keystore、`ROS_SECURITY_*` 环境变量）。论文必须把 SROS 2 写成**被集成的既有基础设施**，而不是本文贡献。
- **建议引用位置**：Related Work；System Architecture「第 1 层」。
- **核实级别**：Crossref 元数据 + 摘要（arXiv:2208.02615）。

### L03 · `dieber2017` — Security for the Robot Operating System

- **作者 / 年份 / 来源**：B. Dieber, B. Breiling, S. Taurer, S. Kacianka, S. Rass, P. Schartner，2017，*Robotics and Autonomous Systems*，98: 192–203
- **DOI**：10.1016/j.robot.2017.09.017
- **研究问题**：ROS 1 生态存在哪些安全问题，SROS 等加固手段能做到什么程度。
- **技术方法**：系统性梳理 ROS 的攻击面（明文通信、无认证、无授权、节点可任意发布），并评估基于 TLS/ VPN/ SROS 的缓解方案。
- **核心结论**（领域共识 + 标题/来源级核实）：ROS 1 缺少内建认证与访问控制；加固方案多为外挂式，难以覆盖计算图内部。
- **局限性**：成文于 ROS 2 早期，不能直接代表 Jazzy 的实现状态；本文未在本轮获取全文，仅作背景性引用。
- **与 RosSystem 的关系**：提供"为什么需要 ROS 2 / DDS Security"的动机链；RosSystem 的威胁模型（未授权节点、伪造请求）与其一脉相承。
- **建议引用位置**：Introduction；Related Work 开篇。
- **核实级别**：Crossref 元数据；**全文未获取**，仅作背景引用（写作时不得引用其具体实验数字）。

### L04 · `white2019` — Network Reconnaissance and Vulnerability Excavation of Secure DDS Systems

- **作者 / 年份 / 来源**：R. White, G. Caiazza, C. Jiang, X. Ou, Z. Yang, A. Cortesi, H. Christensen，2019，IEEE EuroS&PW 2019，pp. 57–66
- **DOI**：10.1109/EuroSPW.2019.00013
- **研究问题**：启用 DDS Security 之后，攻击者是否仍能进行网络侦察与漏洞挖掘。
- **技术方法**：针对 secure DDS 系统的侦察方法与漏洞挖掘实验。
- **核心结论**（标题/摘要级）：**"secure DDS"并不等于"不可侦察"**；安全配置下仍存在可被利用的信息暴露面。
- **局限性**：面向 DDS 层侦察，不涉及应用层任务语义；具体工具与命中率需读全文才能引用。
- **与 RosSystem 的关系**：直接支撑 RosSystem 的威胁模型（M1 的图发现/侦察异常观测）与"不能把 Enforce 通过当作安全结论"的论证。
- **建议引用位置**：Threat Model；Discussion（为什么仍需 M1）。
- **核实级别**：Crossref 元数据 + 标题级；具体结论需全文确认后引用细节。

### L05 · `wang2024` — A Formal Analysis of Data Distribution Service Security

- **作者 / 年份 / 来源**：B. Wang, H. Li, J. Guan，2024，ACM AsiaCCS 2024，pp. 716–727
- **DOI**：10.1145/3634737.3656288
- **研究问题**：DDS Security 协议的安全目标是否真的可达？是否存在协议层攻击。
- **技术方法**：用 **ProVerif** 对 DDS Security 的安全目标与协议流建模，在不同场景下评估；以形式化结果指导攻击构造。
- **核心结论**（摘要明确支持）：自动化确认了此前人工发现的部分漏洞，并**新发现** permission file impersonation（权限文件冒充）、拒绝服务、降级、隐私泄露四类攻击；给出缓解建议。
- **局限性**：协议/规范层分析，不针对具体 ROS 2 部署；缓解措施是建议性的，不构成产品级修复。
- **与 RosSystem 的关系**：**关键论据**——DDS Security 的权限判定本身存在已知攻击面，因此"仅靠 DDS 层授权"不足以支撑任务执行准入；RosSystem 的 F0/Gateway 双层判定是对该风险的一种工程性补充（而非修复 DDS 规范）。
- **建议引用位置**：Related Work「DDS 参与者认证与资源授权」；Motivation；Limitations（说明本文不修复协议缺陷）。
- **核实级别**：Crossref 元数据 + 出版方摘要。

### L06 · `wagner2024` — DDS Security+: Enhancing the Data Distribution Service With TPM-based Remote Attestation

- **作者 / 年份 / 来源**：P. G. Wagner, P. Birnstill, J. Beyerer，2024，ARES 2024，pp. 1–11
- **DOI**：10.1145/3664476.3670442
- **研究问题**：DDS 已有参与者认证与访问控制，能否进一步用 **TPM 远程证明**验证对端**软件栈完整性**。
- **技术方法**：把 TPM 远程证明透明地嵌入 DDS 安全信道握手，将通信信道与"被证明的软件栈"密码学绑定；用 **Tamarin** 形式化验证；以 eProsima Fast DDS 分支实现并评估性能。
- **核心结论**（摘要支持）：DDS 的基本安全特性（参与者认证、访问控制）**不验证对端代码完整性**；该工作补上了这一层，并给出实现与开销评估。
- **局限性**：需要 TPM 硬件与部署支持；仍是**平台/参与者级**证明，不证明"这条请求属于该主体"。
- **与 RosSystem 的关系**：这是与 RosSystem C1 最接近的"身份增强"研究之一。差别在于：DDS Security+ 加强的是**参与者身份的可信根**（测度/证明），RosSystem 加强的是**该参与者发出的当前应用请求与内容的绑定**。二者可组合而非互斥。
- **建议引用位置**：Related Work「应用层身份与请求完整性」；Novelty Comparison（必须引用并说明差异）。
- **核实级别**：Crossref 元数据 + 出版方摘要。

### L07 · `lu2024` — 机器人操作系统 ROS 安全性研究综述

- **作者 / 年份 / 来源**：鲁敬敬, 秦云川, 刘志中, 唐卓, 张拥军, 李肯立，2024，软件学报，35(2): 1010–1027
- **DOI**：未注册 Crossref；CNKI 记录号 `RJXB202402018`
- **研究问题**：系统梳理 ROS 的安全特性、已知安全问题与近年安全方案。
- **技术方法**：综述；分析 ROS 安全特性与已知问题，对近年方案分类，并按**机密性、完整性、可用性**三个维度比较。
- **核心结论**（摘要支持）：ROS 安全研究已有大量工作，但"安全性目前还没有得到足够的重视"；现有方案可从 CIA 三性统一比较；文章给出研究展望。
- **局限性**：综述性文章，不提供新实验；以 ROS/ROS 2 生态为主，对"任务级准入"着墨需阅读全文确认。
- **与 RosSystem 的关系**：**国内研究现状的主要锚点**。用于说明国内已有系统性 ROS 安全梳理，而 RosSystem 定位为"跨层证据融合 + 可审计准入"的工程实证补充，不声称填补国内空白。
- **建议引用位置**：Related Work「国内研究现状」；Introduction 国内背景。
- **核实级别**：CNKI 与农业学术服务平台两处记录交叉核对（作者、2024 年第 2 期、页码 1010–1027、摘要）。**卷号 35 取自期刊连续卷号，CNKI 页面未直接印出**，已在 `SOURCE_VERIFICATION_REPORT.md` 标注。

---

## B. 入侵检测与模型可信性（M1 评估）

### L08 · `sommer2010` — Outside the Closed World: On Using Machine Learning for Network Intrusion Detection

- **作者 / 年份 / 来源**：R. Sommer, V. Paxson，2010，IEEE S&P 2010，pp. 305–316
- **DOI**：10.1109/SP.2010.25
- **研究问题**：把机器学习直接用于网络入侵检测，为什么在真实部署中常常失败。
- **核心结论**（领域共识 + 标题/来源级）：入侵检测本质是**开放世界**问题——训练分布不能覆盖真实流量；单纯追求算法指标会掩盖部署失效；需要关注**基率、语义鸿沟与特征稳定性**。
- **局限性**：2010 年的网络 IDS 语境，非机器人专用；本轮未获取全文。
- **与 RosSystem 的关系**：为 M1 的"高 F1 不等于可部署"提供最经典的方法论依据；与 RosSystem 的 `validation_gate_passed=false` 形成呼应。
- **建议引用位置**：M1 评估；Discussion。
- **核实级别**：Crossref 元数据；**全文未获取**，仅引用其核心论点，不引用具体数字。

### L09 · `axelsson2000` — The Base-Rate Fallacy and the Difficulty of Intrusion Detection

- **作者 / 年份 / 来源**：S. Axelsson，2000，*ACM TISSEC*，3(3): 186–205
- **DOI**：10.1145/357830.357849
- **研究问题**：为什么入侵检测的误报率必须极低才有实用价值。
- **核心结论**（标题/摘要级，领域标准结论）：在攻击先验极低的场景下，即使检测率很高，只要**误报率**不够低，告警的**后验可信度**仍然很低（基率谬误）。
- **局限性**：理论/概率论证，非机器人实证。
- **与 RosSystem 的关系**：直接支持"12 个正常窗口 0 误报不能推出低 FPR"以及"小样本下不能给生产级 FPR 声明"的论证。
- **建议引用位置**：M1 评估；Statistical Analysis；Limitations。
- **核实级别**：Crossref 元数据；结论为该文核心论点。

### L10 · `kaufman2012` — Leakage in Data Mining: Formulation, Detection, and Avoidance

- **作者 / 年份 / 来源**：S. Kaufman, S. Rosset, C. Perlich, O. Stitelman，2012，*ACM TKDD*，6(4): 1–21
- **DOI**：10.1145/2382577.2382579
- **研究问题**：如何形式化"数据泄漏"（训练时使用了预测时不可得的信息）并检测、避免。
- **核心结论**（摘要支持）：泄漏是"引入了不应合法可用于挖掘的目标信息"，被列为数据挖掘十大错误之一；论文给出形式化、检测方法与规避原则。
- **局限性**：通用数据挖掘方法学，不针对 ROS/时序窗口。
- **与 RosSystem 的关系**：M1 的 `duration_ms` 与标签强相关（窗口时长泄漏标签信息）正是该文所述泄漏/伪相关模式的实例；也是"会话级分组验证"必要性的依据。
- **建议引用位置**：M1 评估；Threats to Validity（内部有效性）。
- **核实级别**：Crossref 元数据 + 摘要。

### L11 · `geirhos2020` — Shortcut Learning in Deep Neural Networks

- **作者 / 年份 / 来源**：R. Geirhos, J.-H. Jacobsen, C. Michaelis, R. Zemel, W. Brendel, M. Bethge, F. A. Wichmann，2020，*Nature Machine Intelligence*，2(11): 665–673
- **DOI**：10.1038/s42256-020-00257-z
- **研究问题**：深度网络为何在分布外失败——模型倾向利用"捷径"特征。
- **核心结论**（摘要支持）：模型常依赖与标签相关但在目标分布中不成立的**捷径**线索；在基准上表现好，换分布即崩。
- **局限性**：以视觉任务为主，但机制可迁移。
- **与 RosSystem 的关系**：为"M1 高 F1 来自窗口时长而非真实通信行为"提供术语与理论框架（shortcut / spurious cue），比笼统说"过拟合"更准确。
- **建议引用位置**：M1 评估；Discussion。
- **核实级别**：Crossref 元数据 + 摘要。

### L12 · `chandra1996` — Unreliable Failure Detectors for Reliable Distributed Systems

- **作者 / 年份 / 来源**：T. D. Chandra, S. Toueg，1996，*Journal of the ACM*，43(2): 225–267
- **DOI**：10.1145/226643.226647
- **研究问题**：在异步分布式系统中，如何用**不可靠的失败检测器**（超时即怀疑）构建可靠协议。
- **核心结论**（领域标准结论）：在纯异步模型中无法区分"进程慢"与"进程死"；**超时只能产生怀疑（suspicion），不能产生事实**；可靠性需由失败检测器的性质（如 eventually strong）保证。
- **局限性**：理论模型，不含 ROS 2 实现细节。
- **与 RosSystem 的关系**：P09 的**核心理论依据**——Planner `RESULT_TIMEOUT` 是"怀疑下游未在期限内返回"，不是"下游未执行"，更不是"已取消"。
- **建议引用位置**：P09 讨论；Discussion「分布式执行语义」。
- **核实级别**：Crossref 元数据；结论为该文核心贡献。

### L13 · `saltzer1984` — End-to-End Arguments in System Design

- **作者 / 年份 / 来源**：J. H. Saltzer, D. P. Reed, D. D. Clark，1984，*ACM TOCS*，2(4): 277–288
- **DOI**：10.1145/357401.357402
- **研究问题**：功能应放在系统哪一层实现。
- **核心结论**（领域标准结论）：许多功能只能在**端点**完整实现；中间层提供的检查不能替代端到端的确认。
- **局限性**：设计原则，非实验研究。
- **与 RosSystem 的关系**：说明"Gateway 已 ALLOW"不等于"任务已执行"；Planner 的超时观测也不能替代端点（执行侧）的完成确认。为 RosSystem 的**审计事件链**提供设计理由。
- **建议引用位置**：P09；Discussion；Audit 设计。
- **核实级别**：Crossref 元数据；结论为该文核心论点。

### L14 · `schneider2000` — Enforceable Security Policies

- **作者 / 年份 / 来源**：F. B. Schneider，2000，*ACM TISSEC*，3(1): 30–50
- **DOI**：10.1145/353323.353382
- **研究问题**：哪些安全策略可以被**执行监控**（execution monitoring）强制执行。
- **核心结论**（领域标准结论）：一类策略可由**安全自动机**在执行过程中强制执行；超出该类的策略（如"信息不泄漏"）不能仅靠监控执行。执行监控必须**中介每一次操作**。
- **局限性**：理论框架，不涉及机器人任务语义。
- **与 RosSystem 的关系**：F0 与 Gateway 的定位应表述为**执行监控/准入中介**（policy enforcement），其能力边界受该理论约束——这既支持设计，也限制了"全面安全"的表述。
- **建议引用位置**：F0/Gateway 设计；Discussion。
- **核实级别**：Crossref 元数据；结论为该文核心贡献。

### L15 · `saltzer1975` — The Protection of Information in Computer Systems

- **作者 / 年份 / 来源**：J. H. Saltzer, M. D. Schroeder，1975，*Proceedings of the IEEE*，63(9): 1278–1308
- **DOI**：10.1109/PROC.1975.9939
- **研究问题**：保护机制的设计原则。
- **核心结论**（领域标准结论）：提出包括**最小权限、完全中介、失败安全默认（fail-safe defaults）**在内的设计原则。
- **局限性**：经典原则文献，非机器人实证。
- **与 RosSystem 的关系**：为"证据缺失时默认拒绝（fail-closed）""LAB 身份默认不被 F0 接受"提供原则性依据；也提醒 fail-closed 必须与可用性代价一起讨论。
- **建议引用位置**：F0/Gateway 设计；Discussion「fail-closed 的代价」。
- **核实级别**：Crossref 元数据；原则性结论。

### L16 · `bernstein2012` — High-speed high-security signatures (Ed25519)

- **作者 / 年份 / 来源**：D. J. Bernstein, N. Duif, T. Lange, P. Schwabe, B.-Y. Yang，2012，*Journal of Cryptographic Engineering*，2(2): 77–89
- **DOI**：10.1007/s13389-012-0027-1
- **研究问题**：如何构造高速、高安全、短签名的数字签名方案。
- **技术方法**：Ed25519（EdDSA over edwards25519）；给出实现与性能数据。
- **核心结论**（摘要支持）：公钥 32 字节、签名 64 字节；在通用 CPU 上可达很高签名/验签吞吐。
- **局限性**：算法与实现层，不涉及密钥管理、证书体系与撤销。
- **与 RosSystem 的关系**：RosSystem 的请求证明使用 Ed25519。**论文不得把"采用 Ed25519"写成密码学创新**；创新点只能落在"如何把 DDS 主体、请求摘要、新鲜度与双层核验集成起来"。
- **建议引用位置**：M2 技术方案（算法依据）；Novelty Comparison（明确"成熟机制"）。
- **核实级别**：Crossref 元数据 + 摘要；另有 RFC 8032 作为标准化依据（L39）。
