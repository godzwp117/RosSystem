# F0 公共接口（`PROPOSED_V1`）

本目录定义三个研究模块的公共数据接口，以及三个模块共用的统一输入信封。

**当前状态：`PROPOSED_V1`（提案阶段，尚未冻结）**
**契约版本：`1.0.0-proposed`**

> 技术实现与独立校验已完成；**尚未经过相关开发者的业务确认**，因此不标记为已冻结版本。
> 版本管理、变更规则与八条强制安全边界见 [`CONTRACT_VERSION.md`](CONTRACT_VERSION.md)。

---

## 1. 目录结构

```text
docs/interfaces/
├── README.md                  本文件：接口总览、协议与验证方式
├── CONTRACT_VERSION.md        版本管理、变更规则、八条安全边界、待确认事项
├── schemas/
│   ├── module_input.schema.json                 统一输入信封
│   ├── comm_risk_evidence.schema.json           通信行为分析输出
│   ├── identity_trust_assessment.schema.json    身份与授权分析输出
│   └── task_risk_decision.schema.json           任务风险建议输出
└── examples/
    ├── module_input_valid.json
    ├── comm_normal.json / comm_suspicious.json / comm_unknown.json
    ├── identity_authorized.json / identity_denied.json / identity_error.json
    ├── task_allow_recommended.json / task_block_recommended.json / task_unknown.json
    └── invalid/
        ├── manifest.json        非法样例清单（声明各自针对哪个 Schema、因何失败）
        └── 13 个故意非法样例
```

---

## 2. 三个接口的定位

| 接口 | 回答的问题 | 典型输出状态 | **不是什么** |
| --- | --- | --- | --- |
| `CommRiskEvidence` | 某通信资源在观察窗口内的行为是否异常？ | `NORMAL` / `SUSPICIOUS` / `UNKNOWN` / `ERROR` | **不是**身份认证结果 |
| `IdentityTrustAssessment` | 某主体对某资源的访问是否获得授权？ | `AUTHORIZED` / `DENIED` / `UNKNOWN` / `ERROR` | **不是** DDS 身份认证证明，**不是**最终授权 |
| `TaskRiskDecision` | 某候选操作是否符合当前任务约束？ | `ALLOW_RECOMMENDED` / `BLOCK_RECOMMENDED` / `UNKNOWN` / `ERROR` | **不是** Gateway 的最终授权结果 |

三者都是**研究模块的输出**，最终业务操作仍必须经过 `/rg/guarded_navigate` 由安全网关判定。

---

## 3. 数据流

```text
             ┌──────────────────────┐
             │ ModuleInputEnvelope  │  ← 适配层构造（stdin 单对象）
             └──────────┬───────────┘
                        │ 同一 run_id / request_id
        ┌───────────────┼───────────────┐
        ▼               ▼               ▼
 CommRiskEvidence  IdentityTrust   TaskRiskDecision
        │               │               │
        └───────────────┼───────────────┘
                        ▼
                   统一适配层
                        │  一致性校验 + 版本校验 + 失败关闭
                        ▼
              现有 Planner（复用，不改动）
                        ▼
            /rg/guarded_navigate（固定入口）
                        ▼
               SecurityGateway（权威判定）
                        ▼
                /rg/nav_execute → NavigationSim
```

**适配层的职责边界**（本轮只定义契约，尚未实现）：

- 校验三个输出是否符合各自 Schema；
- 校验三者的 `request_id` / `run_id` / `task_id` 是否一致；
- 任一模块超时、崩溃、输出非法 JSON 或返回 `UNKNOWN`/`ERROR` 时**不得放行**；
- 形成**可解析的本地拒绝记录**，并**不得**把适配层阻断伪装成访问控制拒绝或 Gateway 策略阻断。

---

## 4. 统一输入信封

`ModuleInputEnvelope` 至少包含：

| 字段 | 说明 |
| --- | --- |
| `schema_version` | 契约版本 |
| `run_id` | 运行实例标识 |
| `request_id` | 业务关联标识（**不代表身份**） |
| `created_at` | 信封创建时间（RFC 3339，带时区） |
| `candidate_action` | 候选操作：资源、操作类型、任务 ID、目标位姿 |
| `task_context` | 可选：任务阶段与可信策略引用 |
| `observations` | 观察数据，**每条声明来源与可信级别** |
| `evidence_refs` | 证据引用（模拟数据必须标注 `kind=MOCK`） |

**两处由 Schema 强制的安全约束**：

1. `candidate_action.action_resource` 固定为 `/rg/guarded_navigate`（`const`），
   上游**无法**把候选操作指向执行端；
2. 信封中**不存在** `is_admin` / `authenticated` / `role` 等自报授权开关；
   出现此类字段会被严格校验拒绝。

---

## 5. 验证方式

### 5.1 依赖

校验使用 **JSON Schema Draft 2020-12**，需要 `jsonschema >= 4.0`：

```bash
# 在具备 ROS 2 的容器内
apt-get install -y python3-jsonschema     # 本环境实测版本 4.10.3
```

> **注意（实测发现）**：`jsonschema` 的 `format` 关键字**默认不生效**。
> 本环境实测 `Draft202012Validator.FORMAT_CHECKER` 中**没有** `date-time` 检查器
> （需 `rfc3339-validator`，本环境既无 pip 也无对应 Debian 包）。
> 因此仅声明 `"format": "date-time"` 时，非法时间戳会**静默通过**。
> `scripts/validate_team_contracts.py` 注册了基于标准库的严格检查器，
> 并用自检（`self_check_format_checker`）证明它确实在拦截非法值。

### 5.2 运行校验

```bash
# 全部 Schema + 全部样例（有效 + 非法）
python3 scripts/validate_team_contracts.py --all

# 单个文件
python3 scripts/validate_team_contracts.py \
    --doc docs/interfaces/examples/comm_normal.json \
    --schema comm_risk_evidence
```

### 5.3 运行单元测试

```bash
python3 -m pytest tests/unit/test_team_contracts.py -q
```

覆盖：Schema 自身合法性、公共定义一致性（防漂移）、有效样例通过、
13 个非法样例按预期类别被拒、格式检查器真实生效、非有限数值在解析阶段被拒、
`request_id` 语义与一致性、`UNKNOWN`/`ERROR` 不被当作允许、
上游无法指向执行端、`MOCK` 不冒充已认证身份、可选 M3 字段缺失仍通过。

---

## 6. 常见使用方式

### 6.1 新增一个合法输出

1. 阅读对应 Schema 的 `required` 与 `properties`；
2. 参考 `examples/` 下同类样例；
3. 用 `--doc` 校验通过后再接入。

### 6.2 标注证据来源

`evidence_refs[].kind` 必须如实反映来源：

| `kind` | 含义 | 可用作真实安全结论 |
| --- | --- | --- |
| `MOCK` | 模拟数据 | **否** |
| `RUNTIME_LOG` | 运行日志观察 | 可，需注明范围 |
| `PERMISSION_FILE_ANALYSIS` | 由权限配置推导 | 仅代表理论授权 |
| `CONTROLLED_SECURITY_EXPERIMENT` | 受控安全实验 | 可，需注明实验条件 |
| `UNIT_TEST` | 单元测试断言 | 仅证明代码行为 |
| `UNKNOWN` | 无法归类 | **否** |

### 6.3 需要扩展字段时

不要直接往顶层加字段（会被严格校验拒绝）。
在 `extensions` 对象内扩展，并同步更新本目录文档与测试。

---

## 7. 相关文档

| 文档 | 内容 |
| --- | --- |
| [`CONTRACT_VERSION.md`](CONTRACT_VERSION.md) | 版本管理、变更规则、八条强制安全边界、待确认事项 |
| [`../review/F0_C阶段接口建设验收报告.md`](../review/F0_C阶段接口建设验收报告.md) | 本阶段验收记录 |
| [`../team/PROJECT_DEVELOPMENT_STATUS.md`](../team/PROJECT_DEVELOPMENT_STATUS.md) | 团队开发共享状态 |
