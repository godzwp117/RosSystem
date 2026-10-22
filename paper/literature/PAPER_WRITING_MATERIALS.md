# 论文写作素材库（按章节组织）

> 核实日期：2026-10-22
> 依据：`paper/` 冻结事实、`paper/literature/` 已核实文献、`artifacts/` 已跟踪证据。
> **来源标签**（全文通用）：
> - `PROJECT_EVIDENCE`：本项目实验/代码/归档证据，可用 `git ls-files` 定位；
> - `ACADEMIC_LITERATURE`：同行评审文献（编号见 `references_ieee.md`）；
> - `OFFICIAL_TECHNICAL_DOCUMENTATION`：规范/官方文档（带版本与访问日期）；
> - `RESEARCHER_INTERPRETATION`：作者基于以上材料的推理，**不是**外部文献或实验直接结论。
>
> 使用规则：`ACADEMIC_LITERATURE` 不能替代本项目的实验结论；`PROJECT_EVIDENCE` 也不能证明
> 外部文献成立。每段素材后标注建议来源类型，改写时保留标签。

---

## 0. 实验素材索引（PROJECT_EVIDENCE）

### 0.1 环境

| 项 | 值 | 证据 |
|---|---|---|
| ROS 发行版 | ROS 2 Jazzy | `environment.md`；`docs/review/三成员代码审查与系统研发状态交接报告_20261014.md` |
| RMW | `rmw_fastrtps_cpp` | 同上 |
| DDS 实现 | Fast DDS 2.14 | `paper/PAPER_LIMITATIONS_AND_THREATS.md` §2.2 |
| 容器 | `ros:jazzy` 派生镜像 `rosystem-jazzy:1.1.0` | `paper/FINAL_PACKAGE_REPRODUCTION.md` |
| DDS 域 | 42（普通）、43（Enforce）、45（M2/Gateway 实验） | `paper/CLAIM_EVIDENCE_MATRIX.csv` C03/C05 |
| CA 性质 | `TEST_ONLY_LAB` 临时实验室 CA | `paper/PAPER_FACTS_FINAL.md` §E |
| 宿主范围 | 同宿主、同派生镜像 | `paper/PAPER_FACTS_FINAL.md` §D |

### 0.2 证据路径（全部为已跟踪文件）

| 能力 | 结果 | 证据路径 | 关键限定 |
|---|---|---|---|
| DDS Enforce 正向 | 7/7 | `artifacts/research/v110/sixhour/sixhour-dds-20261022T034500Z/summary.json` | 域 43，临时 CA |
| DDS 负向（带同栈对照） | 6/6 | `artifacts/research/v110/sixhour/sixhour-ddsneg-20261022T034800Z/summary.json` | 同 CA |
| M2 意图主题身份链 | 17/17 | `artifacts/acceptance/exports/m2_lab_identity_v110`；`tests/evidence/m2lab-round2-20261022T031500Z/` | **意图主题，非 Action** |
| Gateway 双层 | 14/14（G1–G4） | `artifacts/acceptance/exports/m2_gateway_identity_v110` | 文件 side channel |
| P07 M3 阻断 | 13/13 | `artifacts/research/v110/p07/p07-20261022T024200Z/` | `CONTROLLED_ISOLATION`；M1/M2 为 MOCK |
| P09 Planner 超时 | 10/10 | `artifacts/research/v110/p09/p09-20261022T030000Z/` | 同容器时钟；未发 cancel |
| 三真实 L1/L2/L3 | PASS/PASS/**BLOCKED** | `artifacts/research/v110/sixhour/three-real/summary.json` | L3 因 M1 UNKNOWN |
| M1 可信窗口 | count=2、COMPLETE | `artifacts/research/v110/m1/trusted_window_from_m2.json`；缺失对照 `trusted_window_missing.json` | 缺失时为 UNKNOWN，不是 0 |
| Action 探测 | NO_ACTION_SERVER | `artifacts/research/v110/m2-action-probe/summary.json` | 负结果 |
| 组件重复 | 30/30 + 3/3 | `artifacts/research/v110/repeats/v110rep-20261021T195500Z` | 组件级 |
| Web 研究证据 | 200/200/200；18 tests | `artifacts/research/v110/web/summary.json` | 归档只读；截图 NOT_RUN |
| F0/Gateway 边界回归 | 49 tests | `artifacts/research/v110/f0_gateway_reverify.log` | STRICT/LAB |
| 最终包单测 | 921 passed / 17 skipped / 0 failed / 603.8 s | `paper/FINAL_PACKAGE_REPRODUCTION.md`；`paper/FINAL_UNIT_TEST_EVIDENCE_AUDIT.md` | 原始日志 `NOT_RECOVERED` |
| 最终包 SHA-256 | `d69737cf9dbd039a4a0b8a127eb15bb3db55b5514512c119befd46d5e0fe32d2` | `submission/creative-work/dist/RosSystem-CreativeWork-Full-1.1.1-rc1.tar.gz`（本轮 `sha256sum` 复核一致） | 打包源自 `ca32a6c…`，验收文档提交 `40fded5` |

### 0.3 关键代码位置

| 机制 | 文件 |
|---|---|
| DDS 侧观测（writer GUID → 证书主体） | `src/m2_witness/m2_ingress_witness.cpp` |
| 当前请求证明（摘要、nonce、新鲜度） | `identity_trust/current_identity.py` |
| Gateway 独立身份门 | `src/rg_gateway/rg_gateway/identity_gate.py` |
| Gateway 安全决策 | `src/rg_gateway/rg_gateway/security_gateway.py` |
| F0 联合准入 | `scripts/team_demo.py` |
| 实验室 CA/权限生成 | `scripts/setup_sros2.sh` |
| 非秘密证据归档 | `scripts/archive_dds_evidence.py` |
| P07 隔离配置 | `config/team_modules.p07-isolation.yaml` |
| P07 / P09 驱动 | `tests/integration/p07_m3_block_isolation.py`、`tests/integration/p09_planner_timeout.py` |
| 身份门/LAB 范围测试 | `tests/unit/test_gateway_identity_gate.py`、`tests/unit/test_f0_lab_scope.py` |

---

## 1. 绪论（Introduction）

### 1.1 可用素材

- **背景**：ROS 2 已成为机器人主流中间件，以 DDS 承载通信 [17][18]（`ACADEMIC_LITERATURE`）；DDS Security 提供参与者认证、访问控制与加密 [32][37]（`OFFICIAL_TECHNICAL_DOCUMENTATION`）。
- **问题动机**：ROS 1 时代缺乏认证与授权 [3]；即使启用 DDS Security，仍存在侦察与协议层攻击面 [4][5]（`ACADEMIC_LITERATURE`）。
- **物理后果**：工业机器人控制器可被网络攻击影响物理过程 [19]（`ACADEMIC_LITERATURE`）。
- **本项目观察（不可由文献替代）**：在本项目的实现中，DDS 层能证明"哪个参与者"，但应用层仍需回答"这条请求是谁发的、内容是否被改、是否新鲜、是否该执行"（`PROJECT_EVIDENCE`：`src/m2_witness/m2_ingress_witness.cpp`、`paper/PAPER_CONTRIBUTIONS.md` C1）。

### 1.2 建议论证顺序

```text
ROS 2 主流化 → 通信安全下沉到 DDS → DDS 安全边界（参与者/资源）
→ 任务执行阶段仍需独立判定 → 本项目提出问题与范围限定
```

### 1.3 必须在绪论就限定的范围

- 只研究**任务执行准入**，不研究物理安全控制；
- 实验为**实验室条件**（临时 CA、单宿主、Fast DDS 2.14、Jazzy）；
- Action 级身份**未验证**，本文明确以意图主题为界（`RESEARCHER_INTERPRETATION` + `PROJECT_EVIDENCE`）。

---

## 2. 相关研究（Related Work）

直接取材 `paper/literature/RELATED_WORK_RESEARCH.md` 的六条脉络。写作要求：

- 按**技术脉络**而非年份/国别组织；
- 每条脉络给出"代表工作 + 实际限制"，再落到本项目的位置；
- 国内研究用 [7]（ROS 安全综述）与 [30]（零信任综述）锚定，不堆砌；
- 高度相似但无法核实的工作（SROS2+OIDC）按 `NOVELTY_COMPARISON.md` §5 的方式披露。

可用对照表：`NOVELTY_COMPARISON.md` §3 的九维对比表（建议改写为论文 Table）。

---

## 3. 系统架构（System Architecture）

### 3.1 分层与来源

| 层 | 机制 | 来源类型 | 引用 |
|---|---|---|---|
| L1 通信/资源 | SROS 2 + DDS Security（证书、governance、permissions、加密） | 既有 | [1][2][32][35][37] |
| L2 请求证据 | writer GUID → 证书主体 → request_digest → Ed25519 | 本项目 | [16][39] + `PROJECT_EVIDENCE` |
| L3 建议性风险 | M1 通信风险、M3 任务风险 | 本项目 | [8][9] 方法学 |
| L4 判定 | F0 联合准入 + Gateway 独立身份门 + TaskPolicy | 本项目 | [14][40][41] |

### 3.2 关键架构论点

- **F0 READY ≠ Gateway ALLOW**（`PROJECT_EVIDENCE`：G1 ALLOW/1 Goal；G2/G3 BLOCK/0；G4 身份 ALLOW 但 TaskPolicy `OUT_OF_REGION`/0）。
- F0 使用受信任材料**自行核验**，不读取模块自报（`PROJECT_EVIDENCE`：`scripts/team_demo.py`）。
- Gateway **重建**摘要字段，用自己的公钥/清单/nonce 账本再核验，再交给**未修改**的 TaskPolicy（`PROJECT_EVIDENCE`：`src/rg_gateway/rg_gateway/identity_gate.py`）。
- 能力边界：属于执行监控类机制，受可执行策略类约束 [14]（`ACADEMIC_LITERATURE`）。

### 3.3 图表

- `paper/figures/fig1_architecture.svg`（跨层架构，M1 gate=false、M2 Ed25519/LAB、M3 任务风险）
- `paper/figures/fig2_identity_chain.svg`（真实请求身份链，标题已注明"意图主题；Action 级未验证"）
- `paper/figures/fig5_block_matrix.svg`（阻断案例矩阵）

---

## 4. 技术方案（Method）

### 4.1 请求绑定

| 要素 | 本项目实现 | 外部依据 |
|---|---|---|
| 签名算法 | Ed25519 | [16][39] |
| 摘要覆盖字段 | `request_id / resource / operation / task_id / target.frame_id,x,y,z` | `PROJECT_EVIDENCE`：`identity_trust/current_identity.py` |
| 信任锚 | 公钥 DER SHA-256 固定在受信任清单 | [32][35] 的思路延伸 |
| 新鲜度 | 时间窗 + 单调 nonce | 密码学常识 + `PROJECT_EVIDENCE` |
| 防重放 | `flock` + 重读-判重-追加-fsync 原子账本 | `PROJECT_EVIDENCE` |
| 作用域隔离 | `AUTHENTICATED_LAB` 与 `AUTHENTICATED` 严格分离，F0 默认拒绝 LAB | `PROJECT_EVIDENCE` |

> 写作提醒：以上除 Ed25519 外均为**工程集成**，不构成密码学创新。见 `NOVELTY_COMPARISON.md` §2。

### 4.2 双层准入

- F0：联合 M1/M2/M3 证据，输出 READY/BLOCK 并记录 detail 归因；
- Gateway：身份门（G1–G4）→ TaskPolicy → DecisionEvent；
- 审计分离：`GatewayIdentityCheck` 与 `DecisionEvent` 分表/分事件。

### 4.3 证据传递的现实约束

- 当前用**文件 side channel**（按 `request_id` 命名的 JSON），不是 Action 协议内字段；
- 文件系统在 TCB 内，故论文必须把它写成**实验室可行的过渡机制**，不是安全边界。

---

## 5. 实验方法（Experimental Method）

### 5.1 场景矩阵

| 场景 | 目的 | 证据 |
|---|---|---|
| P07 | 真实 M3 建议 → F0 阻断 | `artifacts/research/v110/p07/...` |
| P09 | Planner 超时后的执行语义 | `artifacts/research/v110/p09/...` |
| 三真实 L1–L3 | 真实模块调用与正向准入 | `artifacts/research/v110/sixhour/three-real/summary.json` |
| DDS 正向/负向 | 通信安全正负对照 | `.../sixhour-dds*`、`.../sixhour-ddsneg*` |
| 组件重复 | 稳定性与延迟 | `.../repeats/v110rep-20261021T195500Z` |
| Action 探测 | 请求级身份可行性 | `.../m2-action-probe/summary.json` |

### 5.2 统计口径（必须写清）

- 样本单位：场景 / 检查项 / trial（见 `paper/STATISTICAL_ANALYSIS.md` §1）；
- 干预项：17 skipped 不计入分子分母；
- 区间：Wilson 95%，并说明下界（7/7 → 0.646）[42][43]；
- 多重比较：未校正，作为局限 [45]；
- 负结果不剔除（Action reader、500 Hz 未检出）。

---

## 6. 实验结果（Results）

### 6.1 可直接报告的数值（附限定）

| 结果 | 数值 | 允许表述 | 禁止表述 |
|---|---|---|---|
| DDS Enforce | 7/7 | 实验室 Enforce 下合法通信建立、非法被拒 | 生产级 DDS 安全 |
| DDS 负向 | 6/6 | 不同 CA、篡改 p7s、错配、Enforce-off 对照符合预期 | 覆盖所有攻击 |
| M2 身份链 | 17/17 | 意图主题上 writer→subject→content 绑定成立 | Action 级身份已实现 |
| Gateway | 14/14 | 身份门与 TaskPolicy 是两道独立屏障 | 单层即可保证安全 |
| P07 | 13/13 | 真实 M3 在隔离配置下阻断并在 F0 生效 | 三真实链闭环 |
| P09 | 10/10 | 超时 ≠ 取消 ≠ 未执行 | 已实现取消协议 |
| 组件延迟 | verify p50 1.40 ms | 组件级开销 | 端到端延迟 |
| 最终包单测 | 921/17/0 | 单元检查项通过 | 921 次独立实验 |

### 6.2 图表

- `paper/figures/fig4_latency.svg`（组件延迟，标题已注明非端到端）
- `paper/figures/fig5_block_matrix.svg`（阻断矩阵）
- `paper/figures/fig6_maturity.svg`（LEVEL C 与缺口）
- `paper/figures/fig3_comparison.svg`（1.0.3 vs 1.1.0 状态，标注"不是性能提升曲线"）

---

## 7. 讨论（Discussion）

### 7.1 可用的三个讨论支点

1. **超时的语义**：分布式系统中超时只能产生怀疑 [12]，端到端确认不可由中间层替代 [13]，取消需被接受 [34]；P09 的 `EXECUTED` 晚于 Planner 退出即为例证（`PROJECT_EVIDENCE`）。
2. **建议 vs 判定**：P07 的勘误本身说明"把策略阻断当成建议阻断"会导致错误结论（`PROJECT_EVIDENCE`：`paper/ERRATUM_P07.md`）。
3. **fail-closed 的代价**：证据缺失时拒绝 [15]，但会造成可用性损失；当前未量化（`RESEARCHER_INTERPRETATION`）。

### 7.2 与既有工作的关系

- 与 SROS 2：复用而非替代 [1][2]；
- 与 DDS Security+：平台可信 vs 请求可信，维度互补 [6]；
- 与形式化分析：本文不修复协议缺陷，只增加第二道判定 [5]；
- 与零信任/ABAC：提供 ROS 2 中的密码学请求绑定实现 [40][41][24]。

---

## 8. 局限性（Limitations）

直接改写 `paper/PAPER_LIMITATIONS_AND_THREATS.md`，并补三条文献定位：

- 小样本区间宽 [42][43]；
- 未做多重比较校正 [45]；
- 分组/泄漏风险与 `duration_ms` 伪相关 [10][11][26]。

**必须保留的原话级事实**：
- `M2_ACTION_SEND_GOAL_BINDING = NOT_VERIFIED`；
- `THREE_REAL_LEVEL3 = BLOCKED`；
- `M1 validation_gate_passed = false`；
- `DDS_CA_SCOPE = TEST_ONLY_LAB`；
- `ORIGINAL_FULL_PYTEST_LOG = NOT_RECOVERED`；
- `FINAL_MATURITY = LEVEL_C`。

---

## 9. 结论（Conclusion）

建议结构：

1. 问题：DDS 层身份不等于应用层请求身份，任务执行需要独立准入；
2. 做法：在实验室条件下把 DDS 主体、请求摘要、Ed25519 证明、F0 与 Gateway 双层判定串成可审计链；
3. 结果：意图主题 17/17、Gateway 14/14、P07 13/13、P09 10/10、DDS 7/7 与 6/6；
4. 边界：Action 级未验证、M1 未过门槛、LEVEL C、未第三方复现；
5. 展望：Action typesupport/service introspection、生产 PKI/HSM、独立正常会话数据集。

**结论段禁止**出现"实现了 Action 级身份""达到生产级""零误报""国内外首次"。

---

## 10. 图表与技术素材清单

| 编号 | 文件/来源 | 类型 | 备注 |
|---|---|---|---|
| Fig.1 | `paper/figures/fig1_architecture.svg` | 项目自绘 | 可再生成（`paper/make_figures.py`） |
| Fig.2 | `paper/figures/fig2_identity_chain.svg` | 项目自绘 | 已注明 Action 未验证 |
| Fig.3 | `paper/figures/fig3_comparison.svg` | 项目自绘 | 非性能曲线 |
| Fig.4 | `paper/figures/fig4_latency.svg` | 项目自绘 | 组件级 |
| Fig.5 | `paper/figures/fig5_block_matrix.svg` | 项目自绘 | 阻断矩阵 |
| Fig.6 | `paper/figures/fig6_maturity.svg` | 项目自绘 | LEVEL C |
| 表 1 | `PAPER_FACTS_FINAL.md` §A–C | 项目数据 | 实验事实表 |
| 表 2 | `STATISTICAL_ANALYSIS.md` §2 | 项目数据 | Wilson 区间 |
| 表 3 | `NOVELTY_COMPARISON.md` §3 | 本资料库 | 与既有研究对比 |
| 表 4 | `LITERATURE_DATABASE.csv` | 本资料库 | 文献总表（附录可用） |

**版权提醒**：外部论文中的图**不得直接复制**。若需引用其技术事实，
请按"重绘 + 标注来源"处理，并在图注写明"redrawn after [编号]"。

---

## 11. 可改写句式（原创，供作者润色）

> 以下为素材句式，不是外部论文原文，作者应据实改写并核对数字。

- 背景句：「ROS 2 以 DDS 作为默认通信中间件，其安全能力主要由中间件层提供 [17][32]。」
- 缺口句：「然而，中间件层认证的对象是通信参与者，而非某一次应用请求 [35]。」
- 方法句：「本文在不修改 DDS 实现的前提下，于应用层引入请求摘要与 Ed25519 证明，并由两个组件独立核验。」
- 结果句：「在临时实验室 CA 与固定域条件下，意图主题上的身份链通过 17/17 项检查（Wilson 95% 下界 0.816）。」
- 局限句：「上述结果不构成 Action `send_goal` 级身份认证，后者的接口探测在本轮以负结果告终。」
- 讨论句：「因此，超时应被理解为失败怀疑而非执行结论 [12]，执行状态需由审计事件还原 [13]。」
