# RosSystem 1.1.0 论文事实基线（冻结快照）

> 本文件是论文写作的**稳定事实来源**。生成后不覆盖；后续新实验写入 `PAPER_FACTS_NEW_EXPERIMENTS.md`，修正写入独立 erratum / `PAPER_CHANGELOG.md`。

- 冻结时间（UTC）：`2026-10-22T02:34:45Z`
- 研究版本：`1.1.0`，分支 `research/cross-layer-security-v1.1.0`
- 研究分支 HEAD：`488491f5320a6b83ab199d6da2f21169645b0b24`
- 完整包源码提交：`d50604452603ea3dbd5cd7d067f6eef967fb48c1`
- 1.0.3 标签：`creative-work-v1.0.3` → 标签对象 `7b60b2890cc70925d9618d8f3c971035651c6789` → 提交 `5773fb486c8eabdf7c0dfa039b600faabacffe75`
- 完整包：`RosSystem-CreativeWork-Full-1.1.0.tar.gz`，SHA-256 `c47b7a5b6bc933d22cd3fd6cf023f360648f200f94e2b740f4a3e1d1244aa9e0`，2179249 B
- 离线包：`RosSystem-creative-work-1.1.0.tar.gz`，SHA-256 `45026b057643e80262a2ba82c05b3ab781e201d80e08be0c5323081f9a2a5057`，69628 B

## 实验环境（论文 Methods 可直接引用）

| 项 | 值 |
|---|---|
| 宿主 | Ubuntu 22.04.5 LTS WSL2 x86_64 |
| ROS 2 | jazzy |
| RMW | rmw_fastrtps_cpp |
| DDS | Fast DDS 2.14.x |
| 运行容器 | ros:jazzy derived (rosystem-jazzy:1.1.0 / rosystem-verify-1.0.3) |
| Python | 3.12.3 in container; 3.10.12 on host |

## 可以引用的结论（逐项带范围）

| ID | 结论 | 状态 | 范围 | 指标 | 论文允许表述 | 限制 |
|---|---|---|---|---|---|---|
| C01 | 全量单元回归通过 | **PASS** | 本仓库、本容器 | 920 passed, 4 skipped, 0 failed, 563 s | 论文可写“本版本全量单元测试 920 通过、4 跳过” | 非 ROS 集成测试全覆盖 |
| C02 | 原 13 项身份证据测试已实质修复 | **PASS** | 证据解释 + 权限 fixture | 56/56 | 可写“13 项失败根因是归档缺 permissions.xml，已用非秘密 fixture 修复” | 不是算法缺陷修复；历史归档仍缺权限文件 |
| C03 | DDS 实验室 Enforce 正向 7/7 | **PASS** | LAB, domain 43, Fast DDS | 7/7 | 可写“实验室 Enforce 下合法通信建立、非法通信被 DDS 拒绝” | 临时实验室 CA；非生产部署 |
| C04 | DDS 实验室负向 6/6（带同栈正向对照） | **PASS** | LAB, domain 43 | 6/6 | 可写“不同 CA、篡改 p7s、证书/目录错配、Enforce 关闭对照均按预期” | 不覆盖跨主机/跨 RMW/生产 CA |
| C05 | M2 当前请求身份链（意图主题）17/17 | **PASS** | LAB, domain 45, intent topic | 17/17; 2 个证书零串号 | 可写“DDS writer→证书主体→请求摘要→Ed25519→F0 在实验室内成立” | 绑定的是预准入意图主题，不是 Action send_goal；Gateway 尚未在此链中 |
| C06 | Gateway 独立身份 + TaskPolicy 双层授权 14/14 | **PASS** | LAB, domain 45 | 14/14；G1 1 Goal；G2/G3/G4 0 Goal | 可写“身份门与 TaskPolicy 是两道独立屏障” | 证据经文件 side channel；不是 Action 协议内字段 |
| C07 | 组件级重复实验 30/30 | **PASS** | 组件级，不是完整端到端 | 30/30 正向；3/3 负向；verify p50 1.416 ms p99 1.943 ms | 可写“组件级 30 次重复全部成功，延迟约 1.5 ms” | 不得写成 30 次完整 ROS 2 安全闭环 |
| C08 | 三真实模块调用与 Schema 校验 | **PASS** | 真实 M1/M2/M3 External | LEVEL1 PASS, LEVEL2 PASS | 可写“三个真实模块被实际调用并通过 Schema/关联校验” | 不等于正向准入 |
| C09 | 三真正向在线准入 | **BLOCKED** | 真实三模块 | LEVEL3 BLOCKED | 只能写“被 M1 UNKNOWN 阻断，未实现正向” | 必须同时给出阻断原因 |
| C10 | 严格 acceptance | **INCOMPLETE** | 公开科研复现 | exit 9；无 FAIL；6 项 NOT_RUN | 可写“INCOMPLETE，不是 PASS” | 不得省略 NOT_RUN 列表 |
| C11 | P07 M3 建议阻断 → F0 阻断 | **DISPUTED** | 原矩阵标为 PASS，但证据不匹配 | 原证据主要是 Gateway OUT_OF_REGION | 论文暂不得引用 P07 PASS；等待本轮隔离实验或改为 NOT_VERIFIED | 见 ERRATUM_P07.md |
| C12 | P09 Planner TIMEOUT 语义 | **NOT_RUN** | 1.1.0 未重跑 | — | 不得引用为 1.1.0 新证据 | 仅 1.0.3 历史证据 |
| C13 | 最新压缩包独立复现 | **PARTIAL** | 同宿主新目录/新容器 | 16e74e 包：colcon 4/4、DDS 7/7、121 测试；最终包 c47b7a5b 仅 SHA/121 测试复验 | 只能写“同宿主独立目录/容器复现”，不能写第三方主机复现 | 未在第三方主机/CI 复现；最终包未重跑 DDS |
| C14 | 当前成熟度 | **LEVEL_C** | DDS + 当前请求身份实验室验证 | LEVEL C | 可写 LEVEL C | 不满足 B/D/E |
| C15 | M1 validation gate | **FALSE** | M1 模型 | validation_gate_passed=false | 必须写“未通过，不得用于正向准入” | 原因见 M1 专项报告 |
| C16 | Action send_goal 请求级身份 | **NOT_VERIFIED** | 当前 Ed25519 链 | — | 不得写已实现 Action 级身份 | 只绑定意图主题 |
| C17 | 1.0.3 冻结版本未被修改 | **PASS** | Git 标签/提交 | tag 7b60b28→5773fb4 | 可写“1.0.3 未被覆盖” | 研究分支新增提交不影响旧标签 |

### 关键统计表

| 实验 | 通过/总数 | 统计口径 | 证据 |
|---|---|---|---|
| DDS Enforce 正向 | 7/7 | 7 个独立场景，同一次运行 | `artifacts/acceptance/exports/m2_sros2_enforce_v110/` |
| DDS 负向 | 6/6 | 6 个场景，均带同栈正向对照 | `artifacts/acceptance/exports/m2_sros2_enforce_v110_negative/` |
| M2 身份链 | 17/17 | 真实 DDS + 合成/真实观测混合，详见包内 summary | `artifacts/acceptance/exports/m2_lab_identity_v110/` |
| Gateway 双层 | 14/14 | 4 组场景（G1–G4），每组 3–4 个检查 | `artifacts/acceptance/exports/m2_gateway_identity_v110/` |
| 组件重复 | 30/30 + 3/3 | 30 次独立 trial；非完整端到端 | `artifacts/research/v110/repeats/v110rep-20261021T195500Z/` |
| 三真实 | L1 PASS / L2 PASS / L3 BLOCKED | 一次真实运行 | `artifacts/research/v110/three-real/summary.json` |
| 全量单测 | 920 passed / 4 skipped | 一次全量回归 | `acceptance_v110.json` |

> 置信区间与独立性说明见 `STATISTICAL_ANALYSIS.md`。禁止把组件级 30 次写成 30 次完整 ROS 2 闭环。

## 明确不能声明的结论

- 生产级身份认证 / 生产 CA / HSM / 撤销轮换
- Action send_goal 请求级身份绑定
- M1 生产级 IDS 或受信任 NORMAL
- 三真实正向 LEVEL3
- 第三方主机独立复现
- 30 次完整端到端重复
- P07 M3 阻断已被证明（原证据不匹配）
- P09 超时/取消已在 1.1.0 验证
- Web 控制台已展示 1.1.0 证据（尚未接入）

## 风险 / 未完成矩阵

| 项 | 状态 | 对论文的影响 |
|---|---|---|
| P07 M3 阻断证据 | **DISPUTED** | 不得引用原 P07 PASS；见 `ERRATUM_P07.md` |
| P09 超时/取消 | NOT_RUN | 只能引用 1.0.3 历史证据或写“未重测” |
| M1 验证门槛 | false | 三真正向不能写成已实现 |
| Action send_goal 身份 | NOT_VERIFIED | 只能写“意图主题绑定” |
| Web 1.1.0 证据 | NOT_RUN | 不能写“控制台已展示新证据” |
| 第三方主机复现 | NOT_RUN | 只能写“同宿主独立目录/容器” |
| 生产 CA/HSM/撤销 | 未验证 | 不能写生产级安全 |

## 证据快照哈希

| 文件 | SHA-256 |
|---|---|
| `artifacts/acceptance/exports/research_v110/acceptance_v110.json` | `629e74cd90aa6a5800f9acc612340757a36a2867864d4a39f8717747915700e6` |
| `artifacts/acceptance/exports/research_v110/p01_p12_matrix.json` | `ab3332eafe241e4b4d9055c10aee813d35959ec2dff4655cb879cf93f8fcbe37` |
| `artifacts/acceptance/exports/m2_sros2_enforce_v110/evidence_manifest.json` | `705e8e622f903d1ae9bf7375eb2c1dc176c0fbd8a0527922db14f2e5b5f9bac4` |
| `artifacts/acceptance/exports/m2_sros2_enforce_v110_negative/evidence_manifest.json` | `e26dfe75b6cefd901a088503fa9d1bc4a128513b8e705a5d076164929643a898` |
| `artifacts/acceptance/exports/m2_lab_identity_v110/evidence_manifest.json` | `b1eddf696c34170a967cd1ae1b33b4e05ec16eb1b3dec55ab95ad06ff13ca598` |
| `artifacts/acceptance/exports/m2_gateway_identity_v110/evidence_manifest.json` | `d16f732cb07f51d65660764ad10cc1d87e111586546258589ecfc81817aef86f` |
| `artifacts/acceptance/exports/package_v110_verification/package_verification.json` | `2828f8b6eb71c26500cb7fd0034030fcc602c3571de401f73fafc3c00f90079b` |
| `artifacts/research/v110/three-real/summary.json` | `adca96a0e4e20958cea0a3148b91d7af6171d9ce75030dce484818a3ca048ab6` |
| `artifacts/research/v110/repeats/v110rep-20261021T195500Z/summary.json` | `955b2193b2f973dafcdc6715b662311e895ed0fb22b9369dbb06b5917bd470e9` |
| `submission/creative-work/reports/ROSYSTEM_1_1_0_RESEARCH_AND_SECURITY_VALIDATION_REPORT.md` | `f0d1a873e1dd701aab3f06505d103bc7ebdfb709ca62d096e01c2ea95fe6f0eb` |

> 原始证据只读；不要在本轮修改这些归档文件。新实验写入新目录，并登记到 `PAPER_FACTS_NEW_EXPERIMENTS.md`。
