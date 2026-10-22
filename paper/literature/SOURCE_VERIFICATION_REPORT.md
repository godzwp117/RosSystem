# 来源核查报告（Source Verification Report）

> 核查执行日期：2026-10-22（UTC）
> 核查人：RosSystem 学术文献检索轮次
> 基线提交：`99ea7cd94fc25320900ba3d268b075dd4d1e3ac3`（分支 `research/cross-layer-security-v1.1.0`）
> 本报告只记录**实际做过**的核查，不把"计划核查"写成"已核查"。

---

## 1. 总量与构成

```text
TOTAL_ITEMS                 = 48
WITH_DOI                    = 40
PEER_REVIEWED               = 37
NO_DOI_DOCUMENTED           = 8
DUPLICATE_DOI               = 0
DUPLICATE_TITLE             = 0
YEAR_RANGE                  = 1927–2026
ACCESS_DATE                 = 2026-10-22
```

| 类别 | 数量 | 说明 |
|---|---|---|
| 核心文献（A 级） | 16 | 直接支撑研究背景、技术方案、研究差距或实验讨论 |
| 补充研究（B 级） | 16 | 可与 RosSystem 做明确对比 |
| 官方规范/技术文档 | 8 | OMG、ROS 2 Design、Fast DDS、ROS 2 Jazzy、RFC |
| 方法学与标准 | 8 | NIST、统计方法、可复现性 |
| **合计** | **48** | 略高于建议区间 25–40，理由见 §8 |

语言分布：英文 46、中文 2（`lu2024` 软件学报、`zhuge2022` 计算机工程与应用）。

分级分布：A 级 32（含官方与方法学）、B 级 16、C 级 0（未入正式库）、D 级 0（已剔除）。

---

## 2. 核查渠道与结果

| 渠道 | 用途 | 实际结果 |
|---|---|---|
| **Crossref REST API** | DOI 解析、作者/年份/卷期/页码权威元数据 | ✅ 主力渠道；39 项经 `/works/{doi}` 或检索确认 |
| **Semantic Scholar Graph API** | 出版方摘要、arXiv 标识、开放获取状态 | ✅ 24 项取到摘要；部分条目无摘要 |
| **OpenAlex API** | 主题发现、中文期刊 ISSN 过滤 | ⚠️ 免费共享配额耗尽（HTTP 429），仅前段可用 |
| **DBLP API** | 会议/期刊题录与 DOI 交叉核对 | ❌ 被反爬页面拦截（"Making sure you're not a bot"） |
| **出版方/规范页面** | OMG、ROS 2 Design、Fast DDS、NIST、RFC Editor | ✅ OMG DDS Security 1.2、ROS 2 enclave/actions/DDS-security 设计文档、Fast DDS 2.14、NIST、RFC 均直达 |
| **CNKI** | 中文题录与摘要 | ⚠️ 题录/摘要可读，**全文需订阅**；DOI 未在 Crossref 注册 |
| **中文期刊官网** | 中文文献二次核对 | ✅ `cea.ceaj.org` 可读全文摘要与引用格式 |
| **Google Scholar / IEEE Xplore / ACM DL / SpringerLink / ScienceDirect** | 全文检索 | ⚠️ 仅通过 DOI/摘要与出版方页面间接访问；**未做站内全文检索**，多数正文在付费墙后 |

> 说明：本轮**没有**使用"模型记忆"生成任何题录。所有条目均来自上述接口或页面，
> 并保留可复现的查询脚本（见 §9）。

---

## 3. 逐项核查方法

### 3.1 DOI 条目（40 项）

1. 用 Crossref `/works/{doi}` 取回权威记录；
2. 校验标题、作者顺序、年份、容器标题、卷期、页码；
3. 对 12 项重点文献，再用 Semantic Scholar 取出版方摘要，确认"摘要明确支持"的表述；
4. 人工复核生成后的 BibTeX/IEEE/GB-T 三种格式是否一致。

**发现并修正的真实错误**（可作为核查有效性的证据）：

| 项 | 初始假设 | Crossref 实际 | 处理 |
|---|---|---|---|
| Sha 的 Simplex 论文 | DOI 10.1109/MS.2001.935422 | 404 | 放弃该条，改引 `schneider2000` 与 `nist800207` |
| Casini ECRTS 2019 | DOI 10.4230/LIPIcs.ECRTS.2019.4 | Crossref 无记录（LIPIcs 不在 Crossref） | 未收录；改用已核实 `jiang2022` |
| ROSIDS23 卷号 | 以为是 vol. 50 | 实为 **vol. 51** | 已按 Crossref 修正 |
| Bartocci 页码 | 以为是 3–34 | 实为 **1–33** | 已于生成前剔除该条（未使用） |
| DDS Security 版本 | 原以为 1.1 为最新 | OMG 页面显示 **1.2（formal/25-03-06，2026-02）** | 正式条目改用 1.2，并在正文说明 1.1 的历史地位 |
| NIST 800-92 容器名 | 空 | 无 container-title | 手工补 "NIST Special Publication 800-92" 并标注 |

### 3.2 无 DOI 条目（8 项）——为什么可以保留

| 条目 | 类型 | 核查方式 | 说明 |
|---|---|---|---|
| `lu2024` | 中文期刊 | CNKI 记录 + 农业学术服务平台记录双源核对（作者、期号、页码、摘要一致） | 软件学报 DOI 由 CNKI 体系注册，未进 Crossref；**卷号 35 取自期刊连续卷号，页面未直接印出**，已标注 |
| `zhuge2022` | 中文期刊 | 期刊官网页面（含 DOI 10.3778/j.issn.1002-8331.2206-0025、卷期页、摘要） | 有 DOI 但 Crossref 未收录，故 metadata 来源标为 publisher-page |
| `ddssec12` | 规范 | OMG 官方页面（版本、formal 编号、采纳日期、历史版本） | 标准文献通常无 Crossref DOI |
| `dds14` | 规范 | OMG 官方页面（formal/15-04-10） | 同上 |
| `ros2actions` | 设计文档 | design.ros2.org 页面（作者、Date Written/Last Modified） | 非同行评审，已标注 |
| `ros2enclaves` | 设计文档 | 同上（2020-05 撰写，2020-07 修订） | 同上 |
| `ros2ddssec` | 设计文档 | 同上（Last Modified 2020-07） | 同上 |
| `fastdds214` | 厂商文档 | Fast DDS 2.14.0 文档页（插件清单、三层次、Tagging 未实现） | 同上 |
| `ros2jazzy` | 官方文档 | URL 返回 HTTP 200；仅作版本锚点 | 语义以设计文档为准 |

> 注：上表 9 行，其中 `zhuge2022` 实际有 DOI，故"无 DOI"为 8 项。

### 3.3 官方文档的版本与访问日期

| 文档 | 版本 | 访问日期 |
|---|---|---|
| OMG DDS Security | 1.2（formal/25-03-06，2026-02 采纳） | 2026-10-22 |
| OMG DDS | 1.4（formal/15-04-10） | 2026-10-22 |
| ROS 2 Actions 设计文档 | 2019-03 撰写 / 2020-05 修订 | 2026-10-22 |
| ROS 2 Security Enclaves 设计文档 | 2020-05 撰写 / 2020-07 修订 | 2026-10-22 |
| ROS 2 DDS-Security 集成设计文档 | Last Modified 2020-07 | 2026-10-22 |
| Fast DDS | 2.14.0 | 2026-10-22 |
| ROS 2 Jazzy 文档 | Jazzy | 2026-10-22 |
| RFC 8032 | 2017 | 2026-10-22 |

### 3.4 DOI 解析复核（独立于 Crossref 的第二道检查）

对 40 个 DOI 逐一请求 `https://doi.org/{doi}` 并读取重定向目标（不跟随到出版方页面，
以避免反爬误判）：

```text
DOI_REDIRECT_CHECK = 40/40（全部返回 301/302 并指向出版方）
```

映射结果（按重定向主机统计，合计 40）：IEEE Xplore 14、ACM DL 10、Elsevier 3、
NIST 3、Nature 2、Springer 1、Science 1、Wiley 1、Oxford University Press 1、
Taylor & Francis 1、Project Euclid 1、RFC Editor 1、计算机工程与应用 1。

> 说明：直接跟随重定向时，IEEE 返回 202、ACM/Wiley 返回 403，这是**出版方反爬**，
> 不是 DOI 不存在。判定 DOI 是否注册应看 `doi.org` 的重定向，而不是落地页状态码。

---

## 4. 访问限制（必须如实记录）

1. **IEEE Xplore / ACM DL / SpringerLink / ScienceDirect 正文**：本轮未获得机构订阅，
   多数文献只读到**摘要**，未读全文。凡引用其具体实验数字的地方，均在
   `CORE_LITERATURE.md` 标注"全文未获取"。
2. **CNKI 全文**：仅题录与摘要可读；无法确认中文综述对"任务级授权"的具体论述细节。
3. **RSJ 会议报告（SROS2 + OIDC）**：PDF 返回 **HTTP 403**，作者、年份、方法、结论均无法核实
   → 进入 §5 待核查清单，**不进入正式参考文献**。
4. **OpenAlex**：免费共享配额耗尽（HTTP 429），中文期刊 ISSN 过滤未能完成。
5. **DBLP**：反爬页面拦截，未能用 DBLP 交叉核对会议页码。
6. **Google Scholar**：未直接抓取（无稳定接口），仅通过 Crossref/OpenAlex/S2 间接覆盖。
7. **万方 / 维普**：未获得可用检索入口，未使用。

---

## 5. 待核查清单（不进入正式参考文献）

| 条目 | 来源线索 | 状态 | 处理建议 |
|---|---|---|---|
| SROS2 with OIDC（サービスロボットに対する命令の信頼性を担保する技術） | RSJ 大会资料 `4I2-06.pdf` | **403，无法核实** | 作者应通过图书馆/会议论文集获取；若确为请求级命令认证，须重新评估新颖性表述 |
| Runtime Authorization and Evidence Logging for LLM-Driven Physical AI Systems | Zenodo 2026 预印本 | 非同行评审，未核实 | 仅作趋势参考，不引用 |
| 跨层安全风险评估（电力 CPS） | Reliability Engineering & System Safety 2025 | 元数据可核实，但领域不同 | 如需引用须先读全文，避免跨域类比 |
| Dempster–Shafer 多源证据融合系列 | 检索命中多篇 | 未逐篇核实 | 若论文要强化"证据融合"理论，应补 2–3 篇并读全文 |
| 中文"ROS 安全"类大量低质期刊条目 | Crossref 中文检索命中 | 来源可疑（非核心期刊、疑似掠夺性） | **D 级，禁止引用** |

---

## 6. 真实性抽查（负面结果）

Crossref 中文关键词检索（`机器人操作系统 安全`、`ROS2 安全 认证`、`工业机器人 网络安全` 等）
返回的多数条目来自与主题无关的期刊（如《电子通信与计算机科学》《工程与管理科学》），
作者与机构信息不完整、被引为 0。此类条目一律**不收录**，仅在本报告登记，
以免"检索到很多中文文献"的假象。

---

## 7. 引用一致性检查

- 48 个 citation key 与 `references.bib` 一一对应；
- IEEE 与 GB/T 7714 两种格式由同一份 `final_metadata_numbered.json` 生成，
  编号、作者、年份、页码完全一致；
- `LITERATURE_DATABASE.csv` 与 `CLAIM_REFERENCE_EVIDENCE_MATRIX.csv` 中的 key
  均能在 `.bib` 中找到（脚本校验 `unknown refs = ∅`）；
- 无重复 DOI、无重复标题；
- 未使用任何"仅存在于模型记忆"的条目。

---

## 8. 数量超出建议区间的理由

建议区间为核心 10–15、补充 8–12、官方 5–8、方法 3–5（合计 25–40）。实际为 16/16/8/8（48）。

理由：

1. 六个研究脉络每条至少需要 2–3 个锚点，否则综述会退化为单篇支撑；
2. 方法学部分必须同时覆盖区间估计、拒识、多重比较、可复现性与审计日志，缺一不可；
3. 每一项都在至少一份交付物中被实际引用（见 §7 校验），不存在"凑数条目"。

**若期刊限制参考文献数量，建议按以下顺序压缩到 40 项**（B 级优先）：
`bode2023`、`jiang2022`、`josang2017`、`lanotte2020`、`albatati2026`、`salimi2025`、
`nist80092`、`chow1970`。压缩时须同步删除对应论断或改用 A 级文献支撑。

---

## 9. 可复现的检索过程

检索脚本与原始返回保存在本次工作树（未提交，属过程性材料）：

```text
.litwork/sweep.py          # 第一轮：9 组主题 × 中英文 Crossref 检索
.litwork/verify.py         # 第二轮：48 个候选标题的精确核对
.litwork/verify2.py        # 第三轮：DOI 精确解析 + 中文期刊检索
.litwork/round4.py         # OpenAlex 中文 ISSN 检索（配额耗尽）
.litwork/round5.py         # 缺口检索 + 摘要抓取
.litwork/abstracts.py      # Semantic Scholar 摘要
.litwork/build_meta.py     # 权威元数据固化（唯一事实源）
.litwork/gen_refs.py       # 生成 BibTeX / IEEE / GB-T
.litwork/gen_db.py         # 生成 LITERATURE_DATABASE.csv
.litwork/gen_matrix.py     # 生成 CLAIM_REFERENCE_EVIDENCE_MATRIX.csv
.litwork/round1..6_*.json  # 原始返回
```

> 过程性材料不进入仓库提交，但脚本可在需要时重跑以复核任意条目。

---

## 10. 结论

```text
DOI_VERIFICATION            = 40/40 resolved (39 Crossref + 1 publisher-registered)
DOI_REDIRECT_CHECK          = 40/40 redirect at doi.org to the expected publisher
METADATA_MATCH              = PASS（题名/作者/年份/来源逐项比对）
DUPLICATE_CHECK             = PASS（0 重复）
UNVERIFIABLE_EXCLUDED       = 5 类（见 §5）
FULL_TEXT_READ              = 部分（多数仅摘要）
HONEST_LIMITATION_RECORDED = YES
```
