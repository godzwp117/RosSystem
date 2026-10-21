# 三模块研究成果对照

- 快照：`chore/member-deliveries` = `3ce820258c69b89e2ad9291e16c44dc7d2b99150`
- 公共基线：`a4c597161d254192b662ee7b8f4d17f76a89cc16`
- 契约：`PROPOSED_V1` / `1.0.0-proposed`
- 证据等级：`A` 源码+原始日志+本轮独立复现｜`B` 源码+可核对运行记录，本轮未复现｜`C` 代码+单测/合成实验，无真实系统运行证据｜`D` 仅声明｜`N` 无证据

> **编号警告**：本仓库中 `m1_stable` / `m2_sros2_enforce` / `m3_dynamic_policy` 是**系统工程验收阶段名称**，与「成员一/二/三」**不是同一编号体系**。二者不可混用。

---

## 1. 系统级研究成果对照表

| 字段 | M1 通信风险 | M2 身份权限 | M3 任务风险 |
| --- | --- | --- | --- |
| **module** | `comm_risk` | `identity_trust` | `task_risk` |
| **implementation_type** | ML（离线监督分类器） | 证据解释（规则化交叉核验） | 规则（确定性约束引擎） |
| **algorithm** | `member1-numeric-v1`：LogisticRegression / ExtraTrees 二选一（验证集选择），纯 Python 数值推理；两数据集均选中 `extra_trees`，阈值 0.75 | 三方一致性核验 + 原生 DDS 日志取证；无学习成分 | `TASK_CONSTRAINT_RULES_V1`；静态条款 + 可选 journal 快照推断 |
| **input_source** | ROSPaCe_reduced / ROSPaCe_reduced_noperiodicity 官方归档（MD5 校验）→ 49 维特征 `.npz` 分片 | 源策略 XML + 生成的 DDS `permissions.xml` + pinned SROS2 Enforce run 的 `summary.json` 与客户端日志 | 本地 `config/task_policy.yaml` + `ModuleInputEnvelope` + 可选 Gateway journal |
| **output_schema** | `CommRiskEvidence` | `IdentityTrustAssessment` | `TaskRiskDecision` |
| **L1_status** | **PASS**（36 单测复测通过；四状态协议、Schema、失败关闭在联合运行中正确） | **PARTIAL**（22 单测通过；`event_id` 不含 `request_id`；默认证据根不可用） | **PASS**（95 单测复测通过；通用验收 33 PASS，3 项 FAIL 系 harness 不兼容） |
| **L2_status** | **FAIL / 未证明**：两数据集 `validation_gate=FAIL`，F1 均**低于恒预测攻击基线** | **PARTIAL**：既有 Enforce 实验证据等级 B；解析器在真实彩色日志上无法产出 `DENIED` | **PARTIAL**：受控静态 87/87，但比较器同源、场景合成；历史推断仅单测 |
| **L3_status** | **NOT_READY**（受控数值 fixture 下的 ROS 联调通过，但用的是 `CONTROLLED_NUMERIC_FIXTURE_NOT_TRAINED_MODEL`） | **NOT_READY**（既有 7/7 Enforce 为历史记录，本轮未复跑） | **BLOCKED**（无 ROS 运行时） |
| **metrics（有效）** | 见 §2；关键：`reduced` F1 0.1312 / Recall 0.0702 / BAcc 0.5351；`noperiodicity` F1 0.6346 / Recall 0.4648 / BAcc 0.7324；**两者恒预测攻击 F1 = 0.8132 / 0.8719** | 无分类指标。可核对的是 S2/S3/S3C/S4 的判定布尔值与 goal 计数 | 受控 87/87；`static_verdict_agreement=1.0`；`FPR=FNR=0.0`（合成）；几何消融 FN 13.16% |
| **limitations** | ① 测试集只覆盖 6 类攻击中的 1 类；② F1 低于恒预测基线；③ 模型产物未交付；④ 无在线特征采集；⑤ 会话独立性 `UNVERIFIED` | ① 不认证当前请求，输出与请求无因果；② 彩色日志导致 `DENIED` 不可达；③ 证据依赖两个未版本控制目录 | ① 静态条款与 Gateway 同源；② 无动态状态机；③ `EXECUTION_TIMEOUT` 未覆盖；④ 场景为合成 |
| **evidence_level** | 算法实现 **A**；**离线指标 A（本轮两份数据集完整独立复现，混淆矩阵与 F1 逐位一致）**；在线能力 **N** | 实现 **A**；既有 Enforce 实验 **B**；实时认证 **N** | 实现 **A**；受控实验 **B**；历史推断 **C**；在线 **N** |
| **code_reference** | `deliveries/member1-comm/modules/my_comm/`（15 文件）+ `artifacts/member1/`（35 证据文件） | `deliveries/member2-identity/identity_trust/assessor.py` 等 7 文件 | `deliveries/member3-taskrisk/modules/member3_taskrisk/` 等 17 文件 |
| **integration_recommendation** | **暂不集成**为安全模块（性能门 FAIL）；可集成其**证据与防泄漏机制**（见 §4） | **修改后集成**（修 P1 + 改证据根），且只能定位为历史证据解释 | **部分立即集成**（静态条款建议器）；历史推断修改后集成 |

---

## 2. M1 指标复核（本轮逐字段核对报告 JSON，非重新训练）

| 指标 | `reduced` | `noperiodicity` |
| --- | --- | --- |
| 审计行数 / 分片 | 30,247,050 / 15 | 20,851,051 / 10 |
| 抽样 / 测试行数 | 150,000 / 20,000 | 100,000 / 20,000 |
| 划分 | train 0–10，val 11–12，test 13–14 | train 0–5，val 6–7，test 8–9 |
| **测试集类别** | **仅 `metasploit SYN flood` (13703) + `observe` (6297)** | **仅 `metasploit SYN flood` (15457) + `observe` (4543)** |
| 其余 5 类攻击 | **`NOT_EVALUATED`（count=0）** | **`NOT_EVALUATED`（count=0）** |
| F1 | 0.1312 | 0.6346 |
| Recall | 0.0702 | 0.4648 |
| Precision / FPR | 1.0 / 0.0 | 1.0 / 0.0 |
| Balanced Accuracy | 0.5351 | 0.7324 |
| PR-AUC（average precision） | 0.7442 | 0.9234 |
| **恒预测攻击 F1** | **0.8132** | **0.8719** |
| **模型 F1 − 恒预测 F1** | **−0.682** | **−0.237** |
| `validation_gate_passed` | **False** | **False** |
| 部署推理↔sklearn 一致性 | PASS（max err 3.3e-16，0 mismatch） | PASS（max err 2.8e-16，0 mismatch） |

**必须同时呈现的三点**：

1. 模型的 F1 **低于**「全部判为攻击」的平凡基线。**只报 F1 会得出误导性结论**；
2. 模型在 Balanced Accuracy 上略高于 0.5（0.5351 / 0.7324），即**优于随机**，但召回率 7.0% / 46.5% 不足以支撑实用检测；
3. 测试集**只含 1 类攻击**，因此「每攻击类别检测效果」对 5/6 类**无法评估**。测试分片取 `files[-2:]`（按分片序号的末两片），而 ROSPaCe 的末两片恰好只含 metasploit SYN flood。这是**评估设计缺陷**（测试覆盖偏置），不是标签泄漏。

---

## 3. 三模块方法学对比

| 维度 | M1 | M2 | M3 |
| --- | --- | --- | --- |
| 是否有学习成分 | **有**（监督学习） | 无 | 无 |
| 是否有模型产物 | 应有，但**未交付** | 不适用 | 不适用 |
| 判定是否依赖当前请求 | **是**（读输入特征向量） | **否**（只依赖 `--case` 与 pinned run） | **是**（读 task_id / target / 策略） |
| 是否有状态 | 无 | 无（纯快照） | 可选（journal 快照，非实时） |
| 是否可被输入伪造放行 | 否（需模型+阈值+证据种类） | 否 | 否 |
| 失败关闭默认 | 是（UNKNOWN/ERROR） | 是（UNKNOWN） | 是（UNKNOWN/ERROR） |
| 输出可解释性 | 低（单一概率 + 无攻击子类） | 中（给出 denial_layer 与日志片段） | **高**（逐条 reason + policy_field + 边界距离） |

---

## 4. 各模块可独立复用的工程资产（与算法性能无关）

即使 M1 的模型未达性能门，以下机制**独立于模型性能**且质量很高，建议沉淀为团队公共资产：

| 资产 | 位置 | 价值 |
| --- | --- | --- |
| **纯 JSON 数值模型 + SHA-256 强制校验** | `my_comm/module.py:54-109` | 彻底规避 `pickle`/`joblib` 反序列化不可信模型的风险 |
| **标签/时间/分组泄漏特征名黑名单** | `my_comm/module.py:20,68-69` | 在加载与推理两处拦截 `attack`/`label`/`timestamp`/`session_id`/`group_id` |
| **部署实现 ↔ 训练框架一致性断言** | `my_comm/train.py:108-116` | 在留出集上强制断言，防止「训练有效、部署走样」 |
| **恒预测基线对照** | `my_comm/train.py:97,144` | 强制报告 `test_always_attack` / `test_always_normal` |
| **YAML 重复键拒绝** | `member3_taskrisk/risk_model.py:35-50` | 防策略歧义 |
| **XML 实体/DOCTYPE 拒绝** | `member2-identity/identity_trust/assessor.py:91-92` | 防 XXE / billion-laughs |
| **历史证据 fail-closed 读取纪律** | `member3_taskrisk/risk_model.py:101-185` | 可复用的 journal 完整性校验模式 |

---

## 5. 跨模块一致性

| 维度 | 状态 |
| --- | --- |
| `schema_version` | **一致**：三者均输出 `1.0.0-proposed` |
| `run_id` / `request_id` 回填 | 一致（M2 的 `event_id` 例外，见其审查 §5） |
| 状态枚举 | 各自符合自身 Schema；三者的「可推进值」唯一（`NORMAL` / `AUTHORIZED` / `ALLOW_RECOMMENDED`） |
| Python 版本 | 均声明 Python 3；M1 训练在 **Windows**（日志中为 `C:\Users\YOGA\...`），M2/M3 在 Linux/容器 |
| 关键依赖 | M1 需 numpy+sklearn；M2 仅标准库（+ `jsonschema>=4` 可选）；M3 需 PyYAML + `jsonschema>=4` |
| **共同硬依赖** | **三者都要 `jsonschema>=4.0`**（M1/M3 直接用 `validate_team_contracts`；M2 在完整仓库中会尝试） |
| 数据来源 | 互不重叠：M1 用 ROSPaCe 离线归档；M2 用 SROS2 实验产物；M3 用本地 TaskPolicy |
| 实时性 | 三者**均无**实时能力 |
| 默认失败策略 | **一致：一律不推进** |

**结论**：三者在**协议层高度兼容**（同一信封、同一契约版本、同一失败哲学），在**能力层互不依赖**，因此可以逐个替换、逐个回退。

---

## 6. L1 / L2 / L3 状态总表

| | L1 协议 | L2 真实算法 | L3 ROS 2 集成 |
| --- | --- | --- | --- |
| **M1** | **PASS**（36 单测 + 联合运行 + 四状态） | **FAIL**（性能门 FAIL，F1 低于平凡基线；测试仅覆盖 1/6 攻击类） | **NOT_READY**（受控 fixture 联调 PASS，真实检测器未接入） |
| **M2** | **PARTIAL**（22 单测 + 联合运行；`event_id` 关联缺失） | **PARTIAL**（既有 Enforce 实验 B 级；解析器 `DENIED` 路径失效） | **NOT_READY**（历史 7/7 未复跑） |
| **M3** | **PASS**（95 单测 + 通用验收 33 PASS） | **PARTIAL**（受控静态充分，真实流量无证据） | **BLOCKED**（无 ROS 运行时） |

**三者 L1 通过都不代表 L2 通过，L2 也不代表 L3。** 本轮**没有任何一个模块达到 L3**。
