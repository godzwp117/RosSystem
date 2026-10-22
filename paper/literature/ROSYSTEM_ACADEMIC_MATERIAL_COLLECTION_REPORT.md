# RosSystem 学术资料收集与研究素材库建设报告

> 执行日期：2026-10-22（UTC）
> 基线：`99ea7cd94fc25320900ba3d268b075dd4d1e3ac3`（`research/cross-layer-security-v1.1.0`）
> 资料库提交：`28e6cf95da128e013ccf62b1e08f72e3fa5f1d50`
> 最终候选包：`1.1.1-rc1`，SHA-256 `d69737cf9dbd039a4a0b8a127eb15bb3db55b5514512c119befd46d5e0fe32d2`（本轮复核一致）
> 交付目录：`paper/literature/`

---

## 0. 基线确认与路径更正

### 0.1 真实 HEAD 与资料适用性

| 检查项 | 实际结果 |
|---|---|
| 当前工作区 HEAD | `33cb4f93d5e5fd268878fe83fc040c655d632a70`，分支 `demo/2026-10-19-rc2` |
| 任务书所指论文资料提交 | `99ea7cd94fc25320900ba3d268b075dd4d1e3ac3`（`research/cross-layer-security-v1.1.0` 的 tip） |
| 该分支在 `99ea7cd` 之后是否有新提交 | **无**（`git log 99ea7cd..research/cross-layer-security-v1.1.0` 为空） |
| 论文事实文件是否存在 | 在 `99ea7cd` 存在；**在当前 demo 工作区不存在** |

**结论**：任务书所列 `paper/PAPER_FACTS_FINAL.md` 等文件的**相对路径正确**，但在
`paper/` 目录所在的**研究分支**上；当前 demo 分支没有 `paper/` 目录。因此本轮以
`99ea7cd` 为唯一事实基线，并在其之上新建 `paper/literature-v1.1.1` 分支，
只新增 `paper/literature/`，未改动任何既有文件。

### 0.2 已读内部资料（真实路径）

| 资料 | 路径 | 状态 |
|---|---|---|
| 论文事实表（最终） | `paper/PAPER_FACTS_FINAL.md` | 已读，全文 |
| 创新点 | `paper/PAPER_CONTRIBUTIONS.md` | 已读，全文 |
| 局限与威胁 | `paper/PAPER_LIMITATIONS_AND_THREATS.md` | 已读，全文 |
| 统计 | `paper/STATISTICAL_ANALYSIS.md` | 已读，全文 |
| 实验结果 | `paper/EXPERIMENT_RESULTS.csv` | 已读（20 行） |
| 主张-证据矩阵 | `paper/CLAIM_EVIDENCE_MATRIX.csv` | 已读（19 行） |
| 最终包复现 | `paper/FINAL_PACKAGE_REPRODUCTION.md` | 已读，全文 |
| 单测证据审计 | `paper/FINAL_UNIT_TEST_EVIDENCE_AUDIT.md` | 已读，全文 |
| M1 结论 | `paper/M1_RESEARCH_FINDINGS.md` | 已读，全文 |
| M2 Action 探测 | `paper/M2_ACTION_BINDING_PROBE.md` | 已读，全文 |
| 六小时研究报告 | `submission/creative-work/reports/ROSYSTEM_SIX_HOUR_RESEARCH_OPTIMIZATION_REPORT.md` | 已读（前 120 行 + 关键结论） |
| 1.1.0 验证报告 | `submission/creative-work/reports/ROSYSTEM_1_1_0_RESEARCH_AND_SECURITY_VALIDATION_REPORT.md` | 存在（经 CLAIM_EVIDENCE_MATRIX 引用核对，未逐行通读） |
| 图 1–6 | `paper/figures/fig1..fig6.svg` | 已提取标题与关键标注 |

### 0.3 冻结事实未被改动

- 未修改 `paper/` 下任何既有文件（`git status` 仅显示新增 `paper/literature/`）；
- 未修改 `security/`、`src/`、`config/`、`tests/`；
- 未修改 `submission/creative-work/dist/`，压缩包 SHA-256 复核一致；
- 未修改历史实验数据与 `PAPER_FACTS_*`。

---

## A. 检索概况

### A.1 渠道与可用性

| 渠道 | 用途 | 结果 |
|---|---|---|
| Crossref REST API | DOI/作者/年份/卷期/页码 | ✅ 主力（39 项） |
| Semantic Scholar | 出版方摘要、arXiv 关联 | ✅ 24 项摘要 |
| 出版方/规范页面 | OMG、ROS 2 Design、Fast DDS、NIST、RFC、中文期刊 | ✅ 9 项页面级核实 |
| OpenAlex | 主题发现、中文 ISSN | ⚠️ 配额耗尽（429） |
| DBLP | 会议题录交叉核对 | ❌ 反爬拦截 |
| CNKI / 万方 / 维普 | 中文全文 | ⚠️ 仅题录+摘要，全文需订阅 |
| Google Scholar / IEEE Xplore / ACM DL / SpringerLink / ScienceDirect | 全文 | ⚠️ 未做站内检索，正文多在付费墙后 |

### A.2 检索规模

- 第一轮：9 组主题 × 中英文关键词，Crossref 批量检索（约 60 次查询）；
- 第二轮：48 个候选标题精确核对；
- 第三轮：10 个关键 DOI 精确解析 + 7 个缺口标题补检 + 6 组中文期刊检索；
- 第四轮：12 个"相似系统"缺口检索；
- 第五轮：摘要抓取 44 项。

### A.3 实际可用成果

```text
核心文献（A）        16
补充研究（B）        16
官方规范/文档        8
方法学与标准         8
------------------------
合计                 48（40 项有 DOI，37 项同行评审）
中文文献             2
```

未采用：低质中文期刊条目（D 级）、无法核实的 RSJ 报告、非同行评审预印本。

---

## B. 最值得引用的 10 篇（推荐优先使用）

| # | 文献 | 编号 | 用途 |
|---|---|---|---|
| 1 | Mayoral-Vilches 等，SROS2: Usable Cyber Security Tools for ROS 2（IROS 2022） | [2] | 说明 DDS 层安全工具链是**既有基础设施**，本文复用而非重造 |
| 2 | White 等，Procedurally Provisioned Access Control（IROS 2018） | [1] | 支撑"策略供给针对参与者/资源"的判断 |
| 3 | Wang 等，A Formal Analysis of DDS Security（AsiaCCS 2024） | [5] | 证明 DDS 层授权存在协议级攻击面 → 需要第二道判定 |
| 4 | Wagner 等，DDS Security+（ARES 2024） | [6] | 与本文最接近的"身份增强"工作，用于界定"平台可信 vs 请求可信" |
| 5 | 鲁敬敬 等，机器人操作系统 ROS 安全性研究综述（软件学报 2024） | [7] | 国内研究现状的主要锚点 |
| 6 | Sommer & Paxson，Outside the Closed World（S&P 2010） | [8] | 说明 ML IDS 指标不能外推为部署能力 |
| 7 | Axelsson，The Base-Rate Fallacy（TISSEC 2000） | [9] | 解释为何 12 个正常窗口不足以声明低误报率 |
| 8 | Chandra & Toueg，Unreliable Failure Detectors（JACM 1996） | [12] | P09"超时≠取消≠失败"的理论依据 |
| 9 | ROS 2 Actions 设计文档（2020-05） | [34] | Goal 生命周期与取消语义的权威定义 |
| 10 | OMG DDS Security 1.2 + ROS 2 Enclaves 设计文档 | [32][35] | "参与者身份 ≠ 请求身份"的规范依据 |

> 另：`geirhos2020` [11] 用于解释 M1 的 `duration_ms` 捷径效应，若论文有 M1 专节，建议进入前 10。

---

## C. 国内外研究现状（摘要）

按六条脉络组织（详见 `RELATED_WORK_RESEARCH.md`）：

1. **ROS 2 基础通信安全**——SROS 2/DDS Security 已成熟 [1][2][17][18]；国内有系统综述 [7]。
2. **DDS 参与者认证与资源授权**——规范完备 [32][35][37]，但形式化分析发现协议级攻击 [5]，且不验证代码完整性 [6]。
3. **应用层身份与请求完整性**——零信任/ABAC 提供架构 [40][41][24]，远程证明提供平台可信 [6]；**请求级绑定在 ROS 2 上的公开实现，在本轮检索范围内未发现**（有边界）。
4. **多源证据与分层决策**——风险自适应 [23]、信任修正 [25]、执行监控 [14][28] 均有研究；RosSystem 的贡献在于"建议 vs 判定"分离的双层实现。
5. **任务执行阶段独立控制**——策略框架存在 [24][28]，但"密码学请求绑定 + 双层准入 + 正负对照"的组合未见公开工作。
6. **可审计与可复现**——方法学成熟 [42][43][45][46][47]；RosSystem 的实践是把证据路径、允许措辞、勘误与负结果一并归档。

**写作纪律**：所有缺口判断均加"在本轮检索范围内"限定；不使用"国内外首次""填补空白"。

---

## D. RosSystem 的研究定位

### D.1 与已有工作相同之处

- 身份根：X.509 参与者证书（与 SROS 2 相同）；
- 算法：Ed25519（标准算法，非创新）；
- 原则：fail-closed、完全中介、PDP/PEP 分离（既有原则）；
- 策略：Gateway 复用未修改的 TaskPolicy。

### D.2 有证据支持的不同之处

| 贡献 | 内容 | 证据 | 边界 |
|---|---|---|---|
| C1 | DDS 主体 → 请求摘要的可审计桥接 | M2 17/17，双证书零串号 | **意图主题，非 Action** |
| C2 | 请求证明 + nonce + 新鲜度 + 失败关闭 | 篡改/重放/过期/错主体/错目标均拒绝 | 算法非创新 |
| C3 | F0 与 Gateway 双层独立判定 | 14/14（G1–G4） | 文件 side channel |
| C4 | 可复现安全实验与证据治理 | DDS 7/7、6/6；勘误；负结果保留 | 实验室条件 |

### D.3 明确不成立的部分

- Action `send_goal` 请求级身份：**NOT_VERIFIED**（原始 reader 破坏服务发现，同栈对照 `EXECUTED`）；
- M1 可信 NORMAL：`validation_gate_passed=false`；
- 三真正向 LEVEL 3：**BLOCKED**；
- 生产级安全：临时 CA、无 HSM/撤销/轮换、未第三方复现；
- 成熟度：**LEVEL C**。

---

## E. 论文各章节素材（索引）

| 章节 | 主要素材 | 文件 |
|---|---|---|
| 绪论 | ROS 2 背景 [17][18]、ROS 1 安全缺陷 [3]、DDS 攻击面 [4][5]、物理后果 [19] | `PAPER_WRITING_MATERIALS.md` §1 |
| 相关研究 | 六条脉络、九维对比表 | `RELATED_WORK_RESEARCH.md`；`NOVELTY_COMPARISON.md` §3 |
| 系统架构 | 四层架构、F0/Gateway 独立性、执行监控边界 [14] | `PAPER_WRITING_MATERIALS.md` §3；`fig1`、`fig2` |
| 技术方案 | 摘要字段、nonce、Ed25519 [16][39]、side channel 限制 | `PAPER_WRITING_MATERIALS.md` §4 |
| 实验方法 | 场景矩阵、统计口径、Wilson [42][43] | `PAPER_WRITING_MATERIALS.md` §5；`STATISTICAL_ANALYSIS.md` |
| 实验结果 | DDS 7/7、6/6；M2 17/17；Gateway 14/14；P07 13/13；P09 10/10；L3 BLOCKED | `PAPER_WRITING_MATERIALS.md` §6；`fig4`、`fig5`、`fig6` |
| 讨论 | 超时语义 [12][13][34]、建议 vs 判定、fail-closed 代价 | `PAPER_WRITING_MATERIALS.md` §7 |
| 局限 | 小样本 [43]、多重比较 [45]、泄漏 [10][11][26] | `PAPER_LIMITATIONS_AND_THREATS.md`；`PAPER_WRITING_MATERIALS.md` §8 |
| 结论 | 五段式结构 + 禁止表述 | `PAPER_WRITING_MATERIALS.md` §9 |

---

## F. 参考文献成果

| 文件 | 内容 | 规模 |
|---|---|---|
| `references.bib` | 规范 BibTeX | 48 条 |
| `references_ieee.md` | IEEE 格式 | 48 条 |
| `references_gbt7714.md` | GB/T 7714—2015 格式 | 48 条 |
| `LITERATURE_DATABASE.csv` | 19 字段总索引 | 48 行 |
| `CLAIM_REFERENCE_EVIDENCE_MATRIX.csv` | 21 条主张映射 | 21 行 |

一致性：三种格式由**同一份 canonical metadata** 生成，编号/作者/年份/页码一致；
无重复 DOI、无重复标题；8 项无 DOI 的文献（规范/设计文档/中文期刊）均记录核查方式。

---

## G. 尚缺的素材（必须承认的空白）

1. **Action 级请求绑定的先例**：检索范围内未找到公开实现；本项目自身为负结果。
   若要主张"首次"，需先排除无法访问的 SROS2+OIDC 工作。
2. **生产 PKI/HSM/凭据轮换的深度文献**：仅到规范层面（DDS Security 1.2），
   缺少证书生命周期、CRL/OCSP 在机器人部署中的实证研究。
3. **多层准入的端到端成本模型**：无外部基准；本项目只有组件级延迟（verify p50 1.40 ms），
   且未做"开启安全前后"的对照。
4. **证据融合理论**：Dempster–Shafer、主观逻辑等未系统收集，F0 的融合语义目前是工程实现，
   没有形式化依据。
5. **中文任务级授权文献**：CNKI 全文不可得，无法确认国内是否有同类工作。
6. **M1 部署期误报的独立基准**：无 Jazzy 运行时的公开 IDS 部署数据；ROSPaCe/ROSIDS23 均为离线数据集。
7. **"ROS 2 应用层 API 不暴露发布者身份"的文献支撑**：目前只有架构层间接支撑
   （[35] 参与者单身份 + DDS SampleIdentity），该判断主要是**本项目实现观察**，
   论文应写成工程发现而非文献结论。
8. **SROS2+OIDC（RSJ）**：HTTP 403，无法核实，已列入 `SOURCE_VERIFICATION_REPORT.md` §5。

---

## H. Git 交付

### H.1 分支与提交

| 项 | 值 |
|---|---|
| 基线提交 | `99ea7cd94fc25320900ba3d268b075dd4d1e3ac3` |
| 交付分支 | `paper/literature-v1.1.1`（从基线新建） |
| 资料库提交 | `28e6cf95da128e013ccf62b1e08f72e3fa5f1d50` |
| 工作树 | `/home/zhangwei/project/RosSystem/.worktrees/lit-research` |

### H.2 文件清单（仅新增 `paper/literature/`）

```text
paper/literature/CORE_LITERATURE.md
paper/literature/LITERATURE_DATABASE.csv
paper/literature/RELATED_WORK_RESEARCH.md
paper/literature/NOVELTY_COMPARISON.md
paper/literature/CLAIM_REFERENCE_EVIDENCE_MATRIX.csv
paper/literature/PAPER_WRITING_MATERIALS.md
paper/literature/TECHNICAL_TERMINOLOGY.md
paper/literature/references.bib
paper/literature/references_ieee.md
paper/literature/references_gbt7714.md
paper/literature/SOURCE_VERIFICATION_REPORT.md
paper/literature/ROSYSTEM_ACADEMIC_MATERIAL_COLLECTION_REPORT.md
```

### H.3 未改动声明

- `security/`、`src/`、`config/`、`tests/`：**0 处修改**；
- `paper/` 既有文件：**0 处修改**；
- `submission/creative-work/dist/`：**0 处修改**，SHA-256 复核一致；
- 历史实验数据与最终压缩包：未触碰。

---

## 验收矩阵

```text
GITHUB_BASELINE_CONFIRMED      = YES   （HEAD 33cb4f9；论文基线 99ea7cd 仍为分支 tip，无后续提交）
CORE_PAPERS_VERIFIED           = 16    （A 级，见 CORE_LITERATURE.md）
SUPPLEMENTARY_PAPERS_VERIFIED  = 16    （B 级，见 LITERATURE_DATABASE.csv）
OFFICIAL_SPECS_VERIFIED        = 8     （OMG×2、ROS 2 Design×3、Fast DDS、Jazzy、RFC 8032）
DOI_VERIFICATION               = 40/40 resolved（39 Crossref + 1 出版方注册）；8 项无 DOI 已记录理由
BIBTEX_DATABASE                = PASS  （48 条，references.bib）
RELATED_WORK_RESEARCH          = PASS  （六条脉络，含国内文献与缺口限定）
NOVELTY_COMPARISON             = PASS  （含无法核实近似工作的如实披露）
CLAIM_REFERENCE_MATRIX         = PASS  （21 条主张 → 文献 → 项目证据路径）
PAPER_WRITING_MATERIALS        = PASS  （九章 + 实验素材索引 + 图表清单）
TECHNICAL_TERMINOLOGY          = PASS  （13 个核心术语 + 12 个补充术语）
SOURCE_VERIFICATION            = PASS  （含访问限制与 5 类待核查/排除条目）
PROJECT_FACTS_UNCHANGED        = YES   （paper/ 既有文件 0 修改）
SECURITY_CODE_UNCHANGED        = YES   （src/security/config/tests 0 修改）
FINAL_PACKAGE_UNCHANGED        = YES   （SHA-256 d69737cf… 复核一致）
```

### 未达到"全部 PASS"的项（如实记录）

| 项 | 实际状态 | 原因 |
|---|---|---|
| 全文阅读覆盖 | **部分** | IEEE/ACM/Elsevier 正文付费墙；多数为摘要级核实 |
| 中文文献数量 | **2 篇** | CNKI 全文不可得，Crossref 中文检索多为低质期刊 |
| OpenAlex 主题发现 | **受限** | 免费共享配额耗尽（429） |
| DBLP 交叉核对 | **未完成** | 反爬拦截 |
| 近似工作核实 | **1 项失败** | SROS2+OIDC（RSJ）返回 403 |
| 近三年（2025–2026）核心文献 | **偏少** | 最新工作多需订阅；已纳入 2026 年 ACM CSUR 综述与 2025 年 JSA 框架 |

---

## 使用建议（给论文作者）

1. **先读** `NOVELTY_COMPARISON.md` §6（可以写/不可以写），再动笔；
2. 引用编号按正文首次出现顺序重排（当前编号是资料库内部编号）；
3. 任何来自文献的具体数字，在引用前核对全文（本轮多为摘要级）；
4. 把 `CLAIM_REFERENCE_EVIDENCE_MATRIX.csv` 当作写作时的"claim 检查表"，
   每写一条结论先确认对应的 `allowed_conclusion`；
5. 投稿前用 `TECHNICAL_TERMINOLOGY.md` §15 的自查清单过一遍术语。
