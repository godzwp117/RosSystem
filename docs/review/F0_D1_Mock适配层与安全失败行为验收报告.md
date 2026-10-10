# F0 D1：Mock、安全适配层与安全失败行为验收报告

| 项 | 值 |
| --- | --- |
| 报告类型 | 阶段验收 + 独立复核记录 |
| 起始提交 | `1cf64e77c5c5382e5fba63b91d9898c7f9a898f0` |
| 契约状态 | `PROPOSED_V1`（未冻结） |
| 状态用词 | 仅 `PASS` / `FAIL` / `PARTIAL` / `BLOCKED` / `NOT_RUN` |
| 本轮范围 | D0 核查 + D1 三 Mock、适配层、替换配置、测试替身、协议与安全失败测试、独立复核 |

---

## 1. 交付物

```text
mock_modules/
├── README.md                   用法、协议、故障注入开关说明
├── _protocol.py                三个 Mock 共用的进程协议助手
├── comm_risk_mock.py           → CommRiskEvidence
├── identity_trust_mock.py      → IdentityTrustAssessment
└── task_risk_mock.py           → TaskRiskDecision

scripts/
└── team_demo.py                安全适配层（本轮核心交付）

config/
└── team_modules.example.yaml   逐模块可替换配置（受信任本地配置）

tests/fixtures/team_modules/
├── permissions_matrix.json     测试权限矩阵（夹具，非真实 SROS 2 策略）
├── region_rules.json           测试区域规则（夹具，非权威 TaskPolicy）
├── comm_risk_double.py         规则计算型替身
├── identity_trust_double.py    矩阵计算型替身
└── task_risk_double.py         几何计算型替身

tests/unit/
├── test_team_process_protocol.py   P-01 ~ P-15
└── test_team_adapter.py            S-01 ~ S-18 + 替换验收

tests/integration/d1_independent_review.py   独立复核（四类）
docs/review/F0_D0_契约与环境基线核查.md
docs/review/F0_D1_Mock适配层与安全失败行为验收报告.md
```

---

## 2. 接口调用方式

### 2.1 模块进程协议

```text
stdin  : 一个 ModuleInputEnvelope（JSON 对象）
stdout : 一个对应接口的输出（JSON 对象），不得混入调试文本
stderr : 诊断信息
退出码 : 0 正常执行（不代表结论为允许）；2 输入问题；3 内部错误
```

### 2.2 适配层

```bash
# 从 stdin
python3 scripts/team_demo.py --config config/team_modules.example.yaml < envelope.json

# 从文件
python3 scripts/team_demo.py --input envelope.json --log logs/team_adapter.jsonl
```

### 2.3 退出码（独立命名空间，与八个业务原因码无关）

| 退出码 | 含义 |
| --- | --- |
| `0` | `READY_FOR_GATEWAY_SUBMISSION` |
| `10` | `ADAPTER_BLOCK`（本地阻断） |
| `3` | 输入信封无效 |
| `4` | 配置无效 |
| `2` | 用法错误 |

### 2.4 结论语义（重要）

本层**只有**一个肯定结论：`READY_FOR_GATEWAY_SUBMISSION`。

它只表示**适配层的候选输入检查通过**，**不代表** Gateway 已允许，
**不代表**下游已执行。本轮**未实现**真实 Action 提交（留待 D2）。

适配层结果中 `decision` 的取值只有 `READY_FOR_GATEWAY_SUBMISSION` 与
`ADAPTER_BLOCK` 两种，不存在任何等价于 `Gateway ALLOW` 或 `EXECUTED` 的取值。

---

## 3. 唯一推进条件

三个模块必须**同时**处于下列状态，且全部结构校验与一致性校验通过：

| 接口 | 允许推进的状态 |
| --- | --- |
| `CommRiskEvidence` | `NORMAL` |
| `IdentityTrustAssessment` | `AUTHORIZED` |
| `TaskRiskDecision` | `ALLOW_RECOMMENDED` |

其他任何状态（含 `SUSPICIOUS` / `DENIED` / `BLOCK_RECOMMENDED` / `UNKNOWN` /
`ERROR`）一律产生本地阻断。

---

## 4. 适配层内部错误码

均以 `ADAPTER_` 前缀，**与 Gateway 的八个业务原因码无交集**（有自动测试断言）：

```text
ADAPTER_OK                            ADAPTER_MODULE_STDOUT_INVALID
ADAPTER_INPUT_INVALID                 ADAPTER_MODULE_STDOUT_ENCODING
ADAPTER_CONFIG_INVALID                ADAPTER_MODULE_STDOUT_TOO_LARGE
ADAPTER_MODULE_MISSING                ADAPTER_MODULE_SCHEMA_INVALID
ADAPTER_MODULE_SPAWN_FAILED           ADAPTER_MODULE_SCHEMA_VERSION
ADAPTER_MODULE_EXIT_NONZERO           ADAPTER_MODULE_STATUS_NOT_PROCEED
ADAPTER_MODULE_TIMEOUT                ADAPTER_CONSISTENCY_REQUEST_ID / RUN_ID /
ADAPTER_CLEANUP_FAILED                          TASK_ID / ACTION / EVENT_ID
```

---

## 5. 测试结果

| 测试集 | 命令 | 结果 |
| --- | --- | --- |
| P 组进程协议（20 项） | `pytest tests/unit/test_team_process_protocol.py` | **PASS** |
| S 组安全失败 + 替换（38 项） | `pytest tests/unit/test_team_adapter.py` | **PASS** |
| D1 新增合计（58 项） | 两者合并 | **PASS**（58 passed） |
| 全量单元测试 | `scripts/run_unit_tests.sh` | **PASS**（**266 passed** = 既有 208 + 新增 58） |
| 契约校验（不得削弱） | `validate_team_contracts.py --all` | **PASS**（exit 0） |
| ROS 2 四包构建 | `scripts/build.sh` | **PASS**（4 packages finished） |

### 5.1 P 组（进程调用协议）

| ID | 项目 | 结果 |
| --- | --- | --- |
| P-01/02 | 正常 stdin 对象 / stdout 恰好一个 JSON 对象；记录 PID 与 PGID | `PASS` |
| P-03 | stdout 混入调试文本 → 拒绝 | `PASS` |
| P-04 | stdout 两个 JSON 对象 → 拒绝 | `PASS` |
| P-05 | stdout 为空 / 非 JSON → 拒绝 | `PASS` |
| P-06 | 非零退出码 → 拒绝 | `PASS` |
| P-07 | 非法 UTF-8 → 拒绝 | `PASS` |
| P-08 | 输出 `NaN` / `Infinity` → 拒绝 | `PASS` |
| P-09 | 非法日期格式 → 拒绝 | `PASS` |
| P-10 | 输出超出大小上限 → 拒绝 | `PASS` |
| P-11 | 子进程超时 → 拒绝，进程组清理且子进程已回收 | `PASS` |
| P-12 | 参数含空格与 `$(...)` → 不发生 Shell 解释 | `PASS` |
| P-13 | 输入无法控制执行命令；配置未开启故障注入时模块拒绝执行 | `PASS` |
| P-14 | stderr 诊断日志不污染 stdout 解析 | `PASS` |
| P-15 | 重复 JSON 键 → 拒绝（含输入信封自身） | `PASS` |

### 5.2 S 组（安全失败关闭）

| ID | 项目 | 实际 reason_code | 结果 |
| --- | --- | --- | --- |
| S-01 | 三模块均推进 | `ADAPTER_OK`（exit 0） | `PASS` |
| S-02 | 通信 `SUSPICIOUS` | `..._STATUS_NOT_PROCEED` | `PASS` |
| S-03 | 身份 `DENIED` | `..._STATUS_NOT_PROCEED` | `PASS` |
| S-04 | 任务 `BLOCK_RECOMMENDED` | `..._STATUS_NOT_PROCEED` | `PASS` |
| S-05 | 任一 `UNKNOWN` | `..._STATUS_NOT_PROCEED` | `PASS` |
| S-06 | 任一 `ERROR` | `..._STATUS_NOT_PROCEED` | `PASS` |
| S-07 | Schema 版本不兼容 | `..._SCHEMA_VERSION` | `PASS` |
| S-08 | 缺少必填字段 | `..._SCHEMA_INVALID` | `PASS` |
| S-09 | `request_id` 不一致 | `ADAPTER_CONSISTENCY_REQUEST_ID` | `PASS` |
| S-10 | `run_id` 不一致 | `ADAPTER_CONSISTENCY_RUN_ID` | `PASS` |
| S-11 | 任务/候选操作/事件标识不一致 | `ADAPTER_CONSISTENCY_*` | `PASS` |
| S-12 | 模块超时 | `..._TIMEOUT` | `PASS` |
| S-13 | 模块崩溃 / 可执行文件缺失 | `..._EXIT_NONZERO` / `..._MISSING` | `PASS` |
| S-14 | 结构合法但状态不允许推进 | `..._STATUS_NOT_PROCEED`（且 `schema_ok=true`） | `PASS` |
| S-15 | 自报 `producer=gateway` 不能覆盖拒绝、不被当作凭据 | `..._STATUS_NOT_PROCEED` | `PASS` |
| S-16 | 输入选择执行端 → 输入校验阶段以退出码 3 拒绝，且**不调用任何模块** | `ADAPTER_INPUT_INVALID` | `PASS` |
| S-17 | 失败后再次正常调用不受污染 | `ADAPTER_OK` | `PASS` |
| S-18 | 首个模块失败 → 不启动后续模块 | 实际调用 `['comm_risk']` | `PASS` |

> S-14 是关键用例：它证明 **Schema 校验成功不等于可以推进**。
> 该用例中模块输出的 `schema_ok` 为 `true`，但状态不是推进状态，仍被阻断。

---

## 6. 独立复核结果

复核脚本：`tests/integration/d1_independent_review.py`
证据：`tests/evidence/d1_review/review_result.json`

| 复核领域 | 项数 | 结果 |
| --- | --- | --- |
| 复核一：进程调用协议（故障注入逐项触发） | 15 | 全部 `PASS` |
| 复核二：安全失败行为 | 17 | 全部 `PASS` |
| 复核三：真实替换能力 | 5 | 全部 `PASS` |
| 复核四：与原有安全边界一致 | 6 | 全部 `PASS` |
| **合计** | **43** | **OVERALL: PASS**（0 FAIL） |

关键复核证据：

| 证据 | 内容 |
| --- | --- |
| 超时清理 | `cleanup=terminated`，且该 PID 复查无存活进程（僵尸亦无） |
| 参数边界 | 参数中的 `$(touch <file>)` **未生成标记文件**，证明无 Shell 解释 |
| 基线对照 | 同类输入下 `S-01` 得到 exit 0，其余阻断用例得到 exit 10 |
| 替换证明 | 三个替身命令路径均含 `tests/fixtures/team_modules`，且不含 `mock_modules` |
| 替身真实性 | `count=100 / baseline=3` → `SUSPICIOUS`（Mock 无法产生该结果） |
| 边界一致 | `PatrolNavigate.action` / `reason_codes.py` / `gateway/` / `security/` Git 差异均为空 |

---

## 7. 三模块替换证据

### 7.1 替身与 Mock 是真正不同的实现

| 维度 | `mock_modules/*_mock.py` | `tests/fixtures/team_modules/*_double.py` |
| --- | --- | --- |
| 判定方式 | **场景选择**（输入说 `suspicious` 就输出 `SUSPICIOUS`） | **规则计算**（按数值/矩阵/几何真实算出） |
| 通信 | 读控制块的 `scenario` | 读 `detail.comm.request_count` / `baseline_count`，按阈值比较 |
| 身份 | 读控制块的 `scenario` | 读 `permissions_matrix.json` + (主体, 资源, 操作) 三元组 |
| 任务 | 读控制块的 `scenario` | 读 `region_rules.json` + 候选目标坐标，按几何包含判断 |
| `producer.name` | `comm_risk_mock` 等 | `comm_risk_double` 等 |
| 输入变化是否改变输出 | 仅当改变控制块 | **是**（实测同一替身在不同数值下给出不同状态） |

### 7.2 替换粒度

| 替换方式 | 结果 |
| --- | --- |
| 三个模块全部替换为替身 | `PASS`（exit 0） |
| 只替换 `comm_risk` | `PASS`，其余两个仍为 Mock |
| 只替换 `identity_trust` | `PASS`，其余两个仍为 Mock |
| 只替换 `task_risk` | `PASS`，其余两个仍为 Mock |

替换**只改配置中的 `mode` 与 `command` 两项**；未修改 `PatrolNavigate.action`、
未修改八个原因码、未修改 `src/rg_gateway/` 任何代码、未修改其他模块代码。
替换后 Schema 校验仍然生效（每个模块记录 `schema_ok: true`）。

---

## 8. 本轮发现并修复的缺陷

| # | 缺陷 | 类型 | 根因 | 修复 | 回归 |
| --- | --- | --- | --- | --- | --- |
| 1 | 模块失败时其调用记录（PID / 退出码 / 清理结果）从结果中丢失 | **产品缺陷** | 调用记录在 `invoke_module` 成功返回后才追加，异常路径未登记 | 改为在构造记录后立即登记，失败路径同样保留 | 3 项失败用例转 PASS |
| 2 | 重复 JSON 键被静默接受（取最后一个值） | **产品缺口**（继承自阶段 C 工具） | `json.loads` 默认行为，JSON Schema 无法发现 | 在共享校验工具中加入解析阶段拒绝，适配层复用 | 阶段 C 的 53 项与全量校验均无回归 |
| 3 | Mock 场景词表不统一导致 identity/task 拒绝执行 | **设计缺陷** | 三个接口状态词汇本就不同，却共用一套 `scenario` | 控制块改为按模块名分别指定 | 12 个场景全部产出正确状态 |
| 4 | 独立复核脚本三条配置写到同一文件 | **复核脚本缺陷**（非产品） | 循环变量 `name` 遮蔽了同名参数，`{name}.yaml` 恒为 `task_risk.yaml` | 循环变量改名，配置文件名显式区分 | 复核从 4 FAIL 转为 43 PASS |
| 5 | 排障中发现：未 source `install/` 时全量单测在收集阶段中断 | **使用陷阱**（非产品缺陷） | `rg_gateway` 只在已构建工作区可导入 | 记入 D0 报告与共享文档，避免误判为测试失败 | — |

> 缺陷 4 值得单独说明：**复核脚本自身的 bug 会伪装成产品失败**。
> 当时的 4 项 FAIL 中有 3 项是"配置未生效"造成的假失败。这正说明
> 独立复核必须先证明"注入手段真的生效"（例如 P-11 通过检查 `cleanup` 字段
> 发现了故障注入未生效），否则负例可能因为**错误的原因**而"通过"。

---

## 9. 与原有安全边界的一致性

| 检查项 | 结果 |
| --- | --- |
| `PatrolNavigate.action` 未改 | `PASS`（Git 差异为空） |
| 八个业务原因码未改 | `PASS`（Git 差异为空） |
| `src/rg_gateway/` 核心未改 | `PASS`（Git 差异为空） |
| `security/`（M2 DDS 权限）未放宽 | `PASS`（Git 差异为空） |
| 未引入 M3 状态机 | `PASS`（`task_state.py` / `state_store.py` / `SwitchTask.srv` 均不存在） |
| 所有候选输入只能指向 `/rg/guarded_navigate` | `PASS`（Schema `const` + 适配层纵深检查） |
| 未使用 `shell=True` | `PASS`（0 处） |
| 未按名称执行 `pkill` / `killall` | `PASS`（实际调用 0 处；只使用 `os.killpg` 终止本进程组） |
| 未停止任何 Docker 容器 | `PASS`（适配层不含 `docker stop` / `docker rm`） |
| MOCK 数据未记为真实 DDS 安全实验 | `PASS`（`producer.source=MOCK`、`evidence_refs[].kind=MOCK`；身份 Mock 不写 `authenticated_identity`，不声称访问控制日志） |

---

## 10. 进程管理验证

| 要求 | 实现 | 验证 |
| --- | --- | --- |
| 唯一调用记录 | 每次调用生成 `invocation_id` | 日志中每条记录均含该字段 |
| 记录 PID 与所属实例 | 记录 `pid` / `pgid` / `invocation_id` | `PASS` |
| 超时与异常的进程生命周期管理 | `start_new_session=True` 建独立进程组；超时 `SIGTERM` → `SIGKILL` | `PASS` |
| 只操作本次调用所属进程组 | `os.killpg(pgid, ...)` | `PASS` |
| 回收直接子进程 | 终止后始终 `proc.wait()`，并关闭管道 | `PASS`（无未回收） |
| 不按名称 pkill | 无 `pkill` / `killall` 调用 | `PASS` |
| 不以停止容器作为超时手段 | 适配层不含容器操作 | `PASS` |
| 存活检查排除僵尸 | 复核中按 `stat` 首字符判断，`Z` 视为已终止 | `PASS` |
| 清理失败仍保持阻断 | `cleanup` 含 `failed` / `unreaped` 时强制 `ADAPTER_BLOCK` | 已实现（本轮未触发） |
| 超时后无残留 | 复核后容器内非僵尸残留进程 **0** | `PASS` |
| 其他实例不受影响 | `rg_jazzy` 容器保持运行；未操作其他容器 | `PASS` |

---

## 11. 安全边界：哪些已验证、哪些仍需 D2/E

### 11.1 本轮已离线验证

- 三个模块可经统一进程协议被独立调用、校验与替换；
- 任何无效、异常、不可信或不满足推进条件的输出**都无法**被误判为可提交执行；
- 适配层不提交真实 Action，也不创建任何指向执行端的通道；
- 自报 `producer` 不构成凭据，不能覆盖模块给出的拒绝结论；
- 进程超时与崩溃后失败关闭且无进程残留。

### 11.2 仍需 D2/E 验证（本轮**未**执行）

| 项目 | 归属 | 状态 |
| --- | --- | --- |
| F0-T01 三 Mock 完成真实 ROS 2 Action | D2 | `NOT_RUN` |
| F0-T02 Mock 全允许 + 区域合法 → Gateway ALLOW，下游收到 Goal | D2 | `NOT_RUN` |
| F0-T03 Mock 全允许 + 区域越界 → Gateway BLOCK，下游无 Goal | D2 | `NOT_RUN` |
| F0-T14 两个隔离实例互不影响 | D2/E | `NOT_RUN` |
| F0-T15 全链路结束节点正常退出 | D2/E | `NOT_RUN` |
| M1/M2 完整安全回归 | E | `NOT_RUN` |
| 公共契约正式冻结 | E | `BLOCKED`（需团队确认） |

> 本轮的测试证据主要支撑 T04~T08 的**离线适配行为**、T09~T11 的**替换能力**
> 与 T12~T13 的**协议一致性**，**不能取代** E 阶段要求的正式端到端验收。

### 11.3 已声明但未验证的假设

| # | 假设 | 说明 |
| --- | --- | --- |
| 1 | 模块进程为本机受信任配置所指定 | 适配层不校验可执行文件的签名或属主；这是本轮的信任边界 |
| 2 | 适配层与模块共享同一文件系统与用户 | 单机单容器场景成立；跨主机不适用 |
| 3 | 超时值由人工设定，未做自适应 | 10 秒为默认值，慢模块需显式调大 |
| 4 | 输出大小上限为 64 KiB | 对当前输出足够；大证据需另设通道 |

---

## 12. 最终强制验收关口 G1

| 验收项 | 证明 | 结果 |
| --- | --- | --- |
| 四份既有 Schema 未被弱化 | `--all` 退出码 0；53 项契约测试通过 | `PASS` |
| 三 Mock 实际可运行 | 12 个场景进程输出全部通过 Schema 校验 | `PASS` |
| 统一 stdin/stdout 协议有效 | P-01~P-15 正负测试 | `PASS` |
| 支持独立模块替换 | 三种替身实际运行（全替换 + 逐个替换） | `PASS` |
| 非法 JSON 被拒绝 | `ADAPTER_MODULE_STDOUT_INVALID` | `PASS` |
| Schema 版本不兼容被拒绝 | `ADAPTER_MODULE_SCHEMA_VERSION` | `PASS` |
| `request_id` / `run_id` 不一致被拒绝 | `ADAPTER_CONSISTENCY_*` | `PASS` |
| `UNKNOWN` / `ERROR` 不推进执行 | `..._STATUS_NOT_PROCEED` | `PASS` |
| 模块超时与崩溃安全失败 | 退出码 10 + `cleanup=terminated` + 无残留 | `PASS` |
| 自报身份不提升安全权限 | 欺骗性样例无法覆盖拒绝 | `PASS` |
| 下游执行资源不可由输入选择 | 退出码 3 + `ADAPTER_INPUT_INVALID` + 不调用模块 | `PASS` |
| 原有 208 项单测无回归 | 本轮实测 266 passed | `PASS` |
| ROS 2 四包构建无回归 | 4 packages finished | `PASS` |
| Gateway / Action / 原因码未改 | Git 差异检查为空 | `PASS` |

### 结论

**`G1: PASS — READY_FOR_D2`**

所有 D1 必需门禁通过，独立复核 43/43 PASS。

**同时明确以下限制**（不得因 G1 通过而淡化）：

1. 本轮**未**提交任何真实 ROS 2 Action，`READY_FOR_GATEWAY_SUBMISSION`
   **不代表** Gateway 已允许或下游已执行；
2. F0-T01/T02/T03/T14/T15 与 M1/M2 完整回归**未执行**，属 D2/E；
3. 公共契约仍为 `PROPOSED_V1`，**未冻结**；
4. 模块可执行文件的信任边界依赖本地受控配置，未做签名校验。


---

## 附录：第二批工作包对 D1 的加固（G1-R，后续轮次追加）

本报告 §5~§10 记录的是 D1 首次验收结果。第二批工作包对 D1 做了三项**安全加固**，
三项均为**先经真实故障注入复现**的真实缺陷（不是理论风险）：

| 项 | 复现 | 修复 |
| --- | --- | --- |
| **H1 输出资源限额** | `communicate()` 先读完再检查长度，`max_stdout_bytes` 不约束运行期缓冲。同一 64 MiB 洪泛输入：修复前峰值 **139 MB**，修复后 **27 MB** | 新增 `read_bounded()`：selector 边读边计数，stdout 超限立即终止本进程组；stderr 继续排空但只保留前 N 字节 |
| **H2 审计失败仍推进** | `append_log()` 失败只写 stderr，此前得到的 READY 不受影响 | 审计写入成为**推进的前置条件**，失败降级为 `ADAPTER_AUDIT_WRITE_FAILED`；实测四种写入故障（含 `/dev/full` 的 ENOSPC）全部阻断 |
| **H3 配置弱校验** | 布尔 `timeout`（Python 中 `True == 1`）、`NaN`/`Infinity`、接口错配、字符串故障开关等均被静默接受 | 明确拒绝并报 `ADAPTER_CONFIG_INVALID`；实测 11 类非法配置全部被拒 |

### 新增原因码（D1 报告 §4 列表的补充）

```text
ADAPTER_AUDIT_WRITE_FAILED   适配层审计写入失败（不得推进）
ADAPTER_DEPENDENCY_MISSING   缺少 jsonschema>=4.0（Draft 2020-12 必需）
ADAPTER_INPUT_TOO_LARGE      输入信封超过上限
```

### 依赖供给缺陷（第二批发现并修复）

`jsonschema >= 4.0` 是契约校验的必需依赖，但 `ros:jazzy` 基础镜像不带它。
此前它只存在于长期使用的容器里（早先手工安装过一次），导致**全新成员容器根本无法
运行适配层**，且报错是无法定位的 `TypeError: 'NoneType' object is not callable`。

已修复：`validate_team_contracts.py` 新增 `require_jsonschema()`，`team_demo.py` 新增依赖
预检并返回 `ADAPTER_DEPENDENCY_MISSING` + 可执行安装命令；
`container_up.sh` 新增 `rg_ensure_validation_dep()`，在新建与复用两条路径上幂等保障该依赖。

### 加固后的回归

| 项目 | D1 首次验收 | 加固后 |
| --- | --- | --- |
| D1 专项测试 | 58 | **79**（+21 项 H1~H3 故障回归） |
| 全量单元测试 | 208 | **287** |
| D1 独立复核 | 43 | **59**（+16 项加固检查） |
| 契约校验 / 四包构建 | PASS | PASS（未削弱） |

**G1-R（加固验收）：PASS**。详见
[`F0_D2_真实Action联调与GAP05验收报告.md`](F0_D2_真实Action联调与GAP05验收报告.md) 第 1 节。
