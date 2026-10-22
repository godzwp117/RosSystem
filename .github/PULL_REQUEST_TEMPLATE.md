<!--
PR 目标分支必须是 baseline。研究模块不得直接提交到 main。
请在提交前逐项填写；不适用的项写「不适用」并说明。
-->

## 开发内容

| 项 | 内容 |
| --- | --- |
| 成员编号 | 成员一 / 成员二 / 成员三 / 成员四 |
| 模块名称 | `comm_risk` / `identity_trust` / `task_risk` / 框架 |
| 功能分支 | `feature/member?-???` |
| **baseline 来源 SHA** | `<你 git switch baseline 后 rev-parse HEAD 得到的完整 SHA>` |
| 当前 HEAD SHA | `<git rev-parse HEAD>` |
| 改动文件清单 | |

---

## 算法真实性（**必填，不得含糊**）

| 项 | 内容 |
| --- | --- |
| 本 PR 属于哪一类 | ☐ 真正研究算法　☐ Mock　☐ 测试替身　☐ 实验原型 |
| 数据或安全证据来源 | |
| 是否存在离线与在线能力差异 | |
| 当前局限 | |

> 若选 Mock 或测试替身：**不得**在任何文档、报告或答辩中把它表述为真实算法结果。
> 若选实验原型：请写明**尚未证明**的部分。

---

## 接口

| 项 | 内容 |
| --- | --- |
| 使用的 Schema | `CommRiskEvidence` / `IdentityTrustAssessment` / `TaskRiskDecision` |
| Schema 版本 | `1.0.0-proposed` |
| 正常（允许推进）状态 | |
| 阻断状态 | |
| UNKNOWN 处理 | |
| ERROR 处理 | |
| 是否请求修改公共接口 | ☐ 否　☐ 是（**是则必须单列说明并等待契约评审**） |

---

## 测试

- [ ] 本模块验收脚本：`python3 scripts/check_member_module.py --module <X> --config <cfg>`
- [ ] 契约校验：`python3 scripts/validate_team_contracts.py --all`
- [ ] 单元测试：`<命令>`
- [ ] 必要集成测试：`<命令>`
- [ ] 真实证据路径：`<日志/证据目录>`

三层测试请分别标注结果（**过 L1 不代表过 L2**）：

| 层次 | 结果 |
| --- | --- |
| L1 协议层（受控 fixtures） | PASS / FAIL / NOT_RUN |
| L2 真实算法（真实输入输出与证据来源） | PASS / FAIL / NOT_RUN |
| L3 ROS 2 在线联调（Gateway 审计 + NavigationSim Goal） | PASS / FAIL / BLOCKED / NOT_RUN |

---

## 安全边界（**逐项确认**）

- [ ] 未修改 `src/rg_gateway/` 核心准入逻辑
- [ ] 未修改冻结的 `PatrolNavigate.action`
- [ ] 未修改八个冻结业务原因码
- [ ] 未修改四份公共 JSON Schema
- [ ] 未削弱 DDS-Security 配置
- [ ] 未新增命令执行入口（无 `shell=True`、不从业务 JSON 读命令）
- [ ] 未从不不可信输入选择模型文件
- [ ] 未绕过 Gateway / 未直接控制 `/rg/nav_execute`
- [ ] 未引入 M3 动态状态机为默认依赖
- [ ] 不涉及密钥、大文件或模型二进制
- [ ] 契约状态仍为 `PROPOSED_V1`（未擅自改为 FROZEN）

---

## 审核

- [ ] 满足合入门槛（baseline 来源正确 / diff 范围合理 / 契约校验通过 /
      模块验收通过 / 必需单测通过 / 风险与 UNKNOWN 与 ERROR 失败关闭 /
      无机密材料 / 无大型原始数据 / 不改冻结安全边界 / 真实算法如实标记）
- [ ] 不存在已知未解释的关键回归

| 项 | 内容 |
| --- | --- |
| 当前未解决问题 | |
| 负责审查人员 | |
| 是否批准合入 baseline | ☐ 批准　☐ 需修改　☐ 拒绝 |

> **远程 SHA 与本地 HEAD 必须一致。** 不得 force push `baseline`，不得修改 `main`。
