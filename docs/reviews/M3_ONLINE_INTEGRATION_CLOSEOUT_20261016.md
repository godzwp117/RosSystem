# M3 在线联调收尾报告（2026-10-16）

> 契约：`PROPOSED_V1` / `1.0.0-proposed`（**未冻结**）
> 基准：`origin/baseline` = `a4c597161d254192b662ee7b8f4d17f76a89cc16`（未改动）
> 演示候选：`origin/demo/2026-10-19-rc` = `df5a0f0d3a12286b3dc3861fb104987cf10d21d3`
> 本轮工作分支：`integration/m3-online-evidence-20261016`

---

## 1. 本轮真实执行情况

| 阶段 | 内容 | 结果 |
| --- | --- | --- |
| A | PR #6/#7/#8 继承关系与 diff 核对 | **完成**（实测） |
| A | PR base 整改 | **`BLOCKED_PERMISSION`**（无 GitHub 写凭据，见 §2） |
| B | 修复 `ADP-01` 假通过风险 + 反例 | **完成**（10 项反例 + 正向对照） |
| C | 修复 `event_id` 契约冲突 + 边界测试 | **完成**（37 项边界测试） |
| D | **M3 真实在线联调（ON-01..ON-06）** | **完成**（6/6 场景，独立复核 19/19 PASS） |
| E | 跨层证据复核工具 + 5 类篡改反例 | **完成** |
| F/G | 系统状态与竞赛声明文档 | **完成**（新增，不覆盖历史） |
| H | 回归测试与 Git 交付 | **完成**（见 §11） |

**整体状态：`READY_FOR_M3_L3`** —— M3 真实模块已在 ROS 2 Jazzy 受控环境中完成
可复核的在线安全执行链，Gateway 权威准入未被取代。

---

## 2. PR #6 / #7 / #8 最新状态

### 2.1 实测数据（GitHub REST API）

| PR | state | base | head | files | commits | ± | mergeable |
| --- | --- | --- | --- | --- | --- | --- | --- |
| #6 | open | **main** | `chore/member-deliveries@3ce8202` | 192 | 44 | +59011/−497 | true/clean |
| #7 | open | **main** | `fix/m2-m3-acceptance@19f6a25` | 272 | 59 | +71168/−497 | true/clean |
| #8 | open | **main** | `demo/2026-10-19-rc@df5a0f0` | 272 | 67 | +71168/−497 | true/clean |

### 2.2 继承关系（`git merge-base --is-ancestor` 实测）

```
baseline a4c5971
  └── chore/member-deliveries 3ce8202   [PR #6]   ✅ 是祖先
        └── fix/m2-m3-acceptance 19f6a25 [PR #7]   ✅ 是祖先
              └── demo/2026-10-19-rc df5a0f0 [PR #8] ✅ 是祖先
```

**三条 PR 构成严格的堆叠链**：`#7` 继承 `#6`，`#8` 继承 `#7`。

**最终文件内容差异**：

| 比较 | 结果 |
| --- | --- |
| `baseline...chore/member-deliveries` | 79 文件 / +38338（成员交付归档） |
| `chore/member-deliveries...fix/m2-m3-acceptance` | 81 文件 / +12169 −12（M2/M3 修复 + 校验器加固 + 证据） |
| **`fix/m2-m3-acceptance...demo/2026-10-19-rc`** | **空（零文件差异）** |
| `git diff origin/fix/m2-m3-acceptance origin/demo/2026-10-19-rc` | **空** |

即 **#8 的 8 个额外提交全部是 merge 提交**，不产生任何独立内容；
其 `files=272 / ±71168` 与 #7 完全相同，佐证该结论。

### 2.3 PR 目标分支整改：`PR_RETARGET: BLOCKED_PERMISSION`

三条 PR 的 base **均为 `main`**，而团队政策要求研究模块 PR 指向 `baseline`
（仓库已有自动守卫：`tests/unit/test_member_module_contract.py::test_no_research_module_targets_main_in_docs`）。

**未能整改的原因（实测证据）**：

```
$ gh --version                      -> gh 未安装
$ env | grep -E 'GH_TOKEN|GITHUB_TOKEN|GH_PAT'  -> 均未设置
$ git config --get-all credential.helper         -> 无
$ curl -X PATCH .../pulls/6 -d '{"base":"baseline"}'
  HTTP 401 {"message":"Requires authentication"}
```

本环境只有 SSH 推送权限（`ssh -T git@github.com` 认证成功），**没有** GitHub 写 API 凭据。
**未尝试使用任何凭据，也未只改文档就宣称 PR 已修复。**

**需有权限者执行的页面操作步骤**：

1. 打开 https://github.com/godzwp117/RosSystem/pull/6 → 标题下方 `base: main` → 改为 **`baseline`** → 确认。
2. 打开 https://github.com/godzwp117/RosSystem/pull/7 → 其 base 当前为 `main`（**不是** `baseline`）→ 改为 **`chore/member-deliveries`**
   （使其只审查相对成员交付归档的新变化）。
3. `#8` 因**与 #7 文件差异为零**，建议在 PR 描述中说明该事实后**关闭**，
   或改为指向 `fix/m2-m3-acceptance` 以体现"无独立内容"；**不要**为制造非空 PR 而修改无关文件。
4. 待 #6 经审查合入 `baseline` 后，再把 #7 的 base 改为 `baseline`，并**重新核对 diff / CI / 审查**。
5. 若决定不将原始归档全量合入 `baseline`，应从 `baseline` 新建集成分支，
   **选择性**纳入已审查的 M2/M3 运行代码与测试，而不是强行合并整个 #7。

> 注意：`git merge-base --is-ancestor` 只证明**包含关系**，**不能替代安全审查**。

---

## 3. 两个验收缺陷的修复前后对比

### 3.1 ADP-01：输入拒绝的假通过风险

**修复前**（`scripts/check_member_module.py`）：

```python
blocked = ('ADAPTER_BLOCK' in proc.stdout
           or 'ADAPTER_INPUT_INVALID' in proc.stdout
           or proc.returncode != 0)
```

`proc.returncode != 0` 使**任意**非零退出都被算作「输入校验成功阻断」。
适配器因 Python 异常、依赖缺失、配置错误而崩溃时，也会被记为「输入拒绝 PASS」。

**直接证伪**（已固化为测试 `test_old_logic_would_have_accepted_a_crashing_adapter`）：

```
旧表达式对 {'returncode': 1, 'stdout': 'Traceback ...'} -> True（记为 PASS）
新判定对同一输入                                          -> False（FAIL）
```

**修复后**：`judge_clean_input_rejection()` 要求**同时**成立

| # | 条件 | 依据 |
| --- | --- | --- |
| 1 | stdout 是可解析 JSON | 无法解析即不构成"明确拒绝" |
| 2 | 顶层 `decision == ADAPTER_BLOCK` | 适配层协议 |
| 3 | `reason_code == ADAPTER_INPUT_INVALID` | 与真实输入拒绝路径对应 |
| 4 | `returncode == 3`（`EXIT_INPUT_INVALID`） | 适配层退出码协议 |
| 5 | 没有任何模块被调用 | **调用标记**测试替身证明拒绝发生在模块调用之前 |
| 6 | 未启动 Planner | 结构化输出 + 无 planner 标记 |

常量直接取自 `team_demo` 模块（`_td_checks`），避免硬编码漂移。

### 3.2 ID-03：`event_id` 与 `request_id` 的契约冲突

**修复前**：要求 `event_id` **包含完整 `request_id`**。
而三份 Schema 把 `event_id` 限为 **1..128 字符**，二者在 `request_id > 80` 时：

```
前缀 + request_id(128) + 分隔符 + 随机部分  >  128
```

**数学上无法同时成立**。M2/M3 曾截取 `request_id[:80]` 以兼容验收器，因而又违反"必须包含"。

**契约依据**（`docs/interfaces/CONTRACT_VERSION.md` §7 与 Schema 描述）：

| 字段 | 定义 |
| --- | --- |
| `run_id` | 运行实例关联 |
| `request_id` | **业务请求关联**（跨层串联） |
| `event_id` | **本次输出事件唯一标识**，用于审计追溯与去重 |

**修复后**（不改 Schema）：

| 检查 | 规则 |
| --- | --- |
| `ID-03` | `event_id` 为非空字符串且长度 ≤ 128（**不要求**包含 `request_id`） |
| `ID-03B` | 关联由**显式** `request_id` 字段一致性承担 |
| `ID-05` | 全 run 内 `event_id` 非空、≤128、**不重复**（含重复台账） |

---

## 4. 本轮新增的负面测试

### 4.1 ADP-01 系列（`tests/unit/test_adp01_input_rejection.py`，16 项）

| 编号 | 输入/故障 | 期望 | 实测 |
| --- | --- | --- | --- |
| ADP-00 | 合法输入 | 必须推进**且**真的调用模块 | PASS |
| ADP-N01 | 缺少 `observations` | 明确输入拒绝 | PASS（rc=3, `ADAPTER_INPUT_INVALID`, 0 模块调用） |
| ADP-N02 | 非法 `schema_version` | 明确输入拒绝 | PASS |
| ADP-N03 | 缺少 `candidate_action` | 明确输入拒绝 | PASS |
| ADP-N04 | 非法 JSON | 明确输入拒绝 | PASS |
| ADP-N05 | 适配器内部异常（模块脚本崩溃） | **不得**记为输入拒绝 | PASS |
| ADP-N06 | 依赖缺失（解释器不存在） | **不得**记为输入拒绝 | PASS |
| ADP-N07 | 配置文件不存在 | **不得**记为输入拒绝 | PASS |
| ADP-N08 | 非零退出且输出非 JSON | 必须 FAIL | PASS |
| ADP-N09 | `ADAPTER_BLOCK` 但原因码不符 | 必须 FAIL | PASS |
| ADP-N10 | 输入拒绝却调用了模块 | 必须 FAIL | PASS |

另含 3 项针对判定函数本身的逐条件破坏测试（任一条件缺失即判负），
以及 1 项证明旧表达式会误判的测试。

### 4.2 `event_id` 边界（`tests/unit/test_event_id_contract_boundaries.py`，37 项）

- `request_id` 长度 **1 / 64 / 80 / 81 / 100 / 127 / 128**，分别在 M2 与 M3 上验证
  `event_id` 非空、≤128、且输出通过**未修改的**公共 Schema。
- 空 `event_id`、超长、非字符串、重复、`request_id`/`run_id` 不一致、
  特殊字符 `request_id`、跨层关联不依赖 `event_id` 包含关系。

### 4.3 在线证据反例（`tests/unit/test_m3_online_evidence_counterexamples.py`，14 项）

| 反例 | 期望 | 实测 |
| --- | --- | --- |
| 篡改 Gateway `reason_code` | 必须失败 | FAIL（`ILLEGAL_GATEWAY_REASON_CODE`） |
| 把 ALLOW 改为 BLOCK 但保留 Goal | 必须失败 | FAIL（`BLOCK_BUT_GOAL_EXISTS`） |
| 移除对应 NavigationSim Goal | 必须失败 | FAIL（`ACTION_RESULT_GOAL_CONSISTENT`） |
| 修改某层 `request_id` | 必须失败 | FAIL（`REQUEST_ID_MISMATCH`） |
| 在 BLOCK 请求中插入伪造 Goal | 必须失败 | FAIL |
| 缺失 DecisionEvent | 必须失败 | FAIL（`ARRIVAL_WITHOUT_DECISION`） |
| 重复 DecisionEvent | 必须失败 | FAIL（`DUPLICATE_DECISION`） |
| 时间倒序（decision 早于 arrival） | 必须失败 | FAIL（`TIME_ORDER_VIOLATION`） |
| 阻断却启动 Planner | 必须失败 | FAIL（`BLOCK_NO_PLANNER`） |
| 缺少权威清单 | 必须失败关闭 | FAIL（`MANIFEST_MISSING`） |
| 只改 F0 的 `request_id` | 必须失败 | FAIL（`F0_REQUEST_ID_MISMATCH`） |

**注**：反例测试在编写过程中**发现了我自己复核工具的两个真实缺陷**（缺 `manifest.json`
导致期望值自证循环；`arrival` 无 `decision` 未被检出），已修复并重新验证。

---

## 5. M3 在线联调各场景结果

- `run_id`：`m3online-20261016T134406Z`
- Domain：**42**，RMW：`rmw_fastrtps_cpp`，容器：`rg_jazzy`
- 配置：`comm_risk=MOCK`、`identity_trust=MOCK`、`task_risk=EXTERNAL`
- 适配层：`--online` **真实启用**

| 场景 | M3 状态 | 适配层决策 | Planner | Gateway 决策 | Execution | Goal |
| --- | --- | --- | --- | --- | --- | --- |
| **ON-01** 合法任务 (1.5,1.5) | `ALLOW_RECOMMENDED` | `READY_FOR_GATEWAY_SUBMISSION` | `PLANNER_RESULT_RECEIVED`，`EXECUTED` | **ALLOW** / `ALLOW_IN_POLICY` | 1 | **1** |
| **ON-02** 越界 (9,9) | `BLOCK_RECOMMENDED` | `ADAPTER_BLOCK` | **未启动** | 未到达 | 0 | **0** |
| **ON-03** 策略缺失 | `UNKNOWN` | `ADAPTER_BLOCK` | **未启动** | 未到达 | 0 | **0** |
| **ON-04** 策略损坏 | `ERROR` | `ADAPTER_BLOCK` | **未启动** | 未到达 | 0 | **0** |
| **ON-05** Gateway 独立权威 | `ALLOW_RECOMMENDED` | `READY_FOR_GATEWAY_SUBMISSION` | 已提交 | **BLOCK** / `OUT_OF_REGION` | 0 | **0** |
| **ON-06** Planner 超时 | `ALLOW_RECOMMENDED` | `READY_FOR_GATEWAY_SUBMISSION` | `PLANNER_RESULT_TIMEOUT` | 无决策 | 0 | 0 |

### 5.1 ON-05 的关键意义

ON-05 使用 **TEST_ONLY** 外扩策略（允许区域 0..10，仅供本次实验，文件内显式标注
`TEST_ONLY`、`policy_version: "1.0-TEST-ONLY-wide"`），使 M3 **自行推导**出
`ALLOW_RECOMMENDED`；适配层也确实放行提交给 Gateway。
而 Gateway 加载的仍是**未修改的** `config/task_policy.yaml`（允许区域 [0,4]²），
因此返回 `BLOCK` / `OUT_OF_REGION`，**下游 Goal 为 0**。

**该场景证明：上游研究模块的建议不能取代 Gateway 的权威准入判定。**

> 未修改、未放宽、未覆盖 Gateway 的正式策略文件；`config/task_policy.yaml` 在本轮 `git diff` 中为 **0 改动**。

### 5.2 ON-06 的超时语义

- 超时**未**被记为 Gateway BLOCK（`online.outcome = PLANNER_RESULT_TIMEOUT`）。
- **未**自动重试，**未**更换 `request_id` 重新发送。
- 适配层如实提示"该请求可能已经到达 Gateway，甚至已到达下游执行端"，
  要求依据 Gateway 审计与 NavigationSim journal 核对。

---

## 6. request_id 跨层关联表

| 场景 | request_id | run_id |
| --- | --- | --- |
| ON-01 | `on01-legal-allow-m3online-20261016T134406Z` | `m3online-20261016T134406Z` |
| ON-02 | `on02-oor-block-m3online-20261016T134406Z` | 同上 |
| ON-03 | `on03-m3online-20261016T134406Z` | 同上 |
| ON-04 | `on04-m3online-20261016T134406Z` | 同上 |
| ON-05 | `on05-gateway-authority-m3online-20261016T134406Z` | 同上 |
| ON-06 | `on06-m3online-20261016T134406Z` | 同上 |

**关联方式**：显式 `run_id`/`request_id` 字段贯穿 M3 输出 → 适配层记录 → Planner 结果
→ Gateway `RosCommEvent`/`DecisionEvent` → `ExecutionEvent` → NavigationSim Goal。

**`event_id` 不要求跨层相同**：各层各自生成自己的事件标识（契约 §7）。
Gateway 的事件标识由其自身审计字段承担。

**每个场景使用唯一 `request_id`**：这是本轮的一个重要教训——
第一版驱动器让 ON-01/03/04/06 复用同一 `request_id`，导致审计与 journal 条目**相互混串**，
复核工具随即报出串单类 FAIL。修正后复核通过。**该问题由工具发现，不是人工察觉。**

---

## 7. Gateway DecisionEvent

取自 `gateway_audit.jsonl`（8 行）：

| request_id | 事件序列 |
| --- | --- |
| `on01-legal-allow-…` | `RosCommEvent` → `DecisionEvent(ALLOW/ALLOW_IN_POLICY)` → `ExecutionEvent(EXECUTED)` |
| `on05-gateway-authority-…` | `RosCommEvent` → `DecisionEvent(BLOCK/OUT_OF_REGION)` |
| ON-02/03/04 | **无任何事件**（适配层阻断，未提交给 Gateway） |
| ON-06 | **无事件**（Planner 超时，未完成提交） |

`RosCommEvent` 与 `DecisionEvent` 的 `event_id` 成对一致，可按 `request_id` 串联。

---

## 8. Action Result

| 场景 | Planner outcome | status_code | success | Goal ID |
| --- | --- | --- | --- | --- |
| ON-01 | `PLANNER_RESULT_RECEIVED` | `EXECUTED` | `true` | `e9e8…`（本轮另一次运行示例） |
| ON-05 | `PLANNER_RESULT_RECEIVED` | **`OUT_OF_REGION`** | **`false`** | 已受理但业务拒绝 |
| ON-02/03/04 | —（未启动） | — | — | — |
| ON-06 | `PLANNER_RESULT_TIMEOUT` | — | — | — |

**注意区分**：`Gateway BLOCK`（审计决策）与 `Action Result = OUT_OF_REGION`（客户端观察到
的业务拒绝）是两个不同层次的证据，本报告分别记录。ON-05 中二者一致指向越界拒绝。

---

## 9. NavigationSim Goal 数量

| 场景 | journal 行数（该 request_id） |
| --- | --- |
| ON-01 | **1** |
| ON-05 | **0**（Gateway BLOCK，未产生下游 Goal） |
| ON-02 | **0** |
| ON-03 | **0** |
| ON-04 | **0** |
| ON-06 | **0** |

全 run 共 **2** 条 Goal（分别属于 ON-01 与另一次 ON-06 的受理；ON-06 的 Planner 超时
发生在受理之后，故其 Goal 记录存在但无 ExecutionEvent）。
**没有任何被阻断的 request_id 产生 Goal。**

---

## 10. DDS-Security 回归

| 项 | 结果 |
| --- | --- |
| 命令 | `python3 tests/integration/sros2_check.py --run-id m3online-regression` |
| 返回码 | **0** |
| 结果 | **SROS2 SUMMARY (7 passed / 7 total)** |
| S1 | 普通模式 A 区请求（域 42，未启用安全）PASS |
| S2 | Enforce 模式合法请求：Planner→Gateway→NavigationSim PASS |
| S5 | Enforce 模式 B 区越界：身份合法但 TaskPolicy 拒绝 PASS |
| **S3C** | **正向对照：`/gateway` 直连执行接口成功 PASS** |
| **S3** | **Enforce 模式：`/planner` 直连执行接口被拒绝 PASS** |
| **S4** | **无授权身份访问执行接口被拒绝 PASS** |
| S6 | 安全配置失效**不静默回退** PASS |

**未回退**。安全能力与 10-16 预检一致；keystore 复用（未重建），
`security/policies/minimal_permissions.xml` 与 `config/task_policy.yaml` **零改动**。

---

## 11. 运行环境

| 项 | 值 |
| --- | --- |
| 宿主 | WSL2 / Linux 6.18.54.1-microsoft-standard-WSL2 x86_64 |
| 容器 | `rg_jazzy`（`ros:jazzy`）/ Ubuntu 24.04.5 LTS |
| ROS | Jazzy，`ROS_DISTRO=jazzy`，`RMW_IMPLEMENTATION=rmw_fastrtps_cpp` |
| Domain | **42**（在线联调）/ **43**（Enforce 实验） |
| 容器内 Python | 3.12.3，`jsonschema` 4.10.3 |
| 宿主 Python | 3.10.12（`.research-venv`：pytest 9.1.1，jsonschema 4.26.0） |
| 构建 | 4 个 ROS 2 包（`rg_interfaces`/`rg_policy`/`rg_gateway`/`rg_demo_nodes`）已构建并可加载 |
| 其他实例 | 执行前实测无其他 ROS 节点（`ros2 node list` 为空） |

---

## 12. Git 版本与 SHA

| 引用 | SHA |
| --- | --- |
| `origin/baseline` | `a4c597161d254192b662ee7b8f4d17f76a89cc16` |
| `origin/main` | `838f66f41821edf0421612a205d162ae8e9eb955` |
| `origin/chore/member-deliveries` | `3ce820258c69b89e2ad9291e16c44dc7d2b99150` |
| `origin/fix/m2-m3-acceptance` | `19f6a256e71db7270de88e5b76b9ac2d87668cc6` |
| `origin/demo/2026-10-19-rc` | `df5a0f0d3a12286b3dc3861fb104987cf10d21d3` |
| 标签 `demo-2026-10-19-rc-preflight-20261016` | `df5a0f0d3a12286b3dc3861fb104987cf10d21d3`（**未移动**） |
| 本轮分支 `integration/m3-online-evidence-20261016` | 起点 `19f6a25`；提交见下表 |

**本轮提交拆分**：

| 提交 | 内容 |
| --- | --- |
| `fix(verifier)` | ADP-01 加固 + ID-03 契约对齐 + 两项测试套件 |
| `test(online)` | 在线证据反例测试 |
| `feat(online)` | 在线驱动器 + 逐层复核工具 + 辅助脚本 |
| `evidence(online)` | 在线联调证据包 |
| `docs(status)` | 系统状态 + 竞赛声明 + 本报告 |

---

## 13. 原始证据路径与 SHA-256

| 内容 | 路径 |
| --- | --- |
| 证据根目录 | `artifacts/demo-2026-10-19/m3-online-m3online-20261016T134406Z/` |
| SHA-256 清单 | 同上 `SHA256SUMS.txt`（自哈希已排除，可 `sha256sum -c` 校验） |
| 权威清单 | 同上 `merged/manifest.json` |
| 逐场景 F0 结果 | 同上 `merged/f0_ON0*.json` |
| 适配层记录 | 同上 `merged/adapter_ON0*.jsonl` |
| Gateway 审计 | 同上 `merged/gateway_audit.jsonl`（8 行） |
| NavigationSim journal | 同上 `merged/navsim_goals.jsonl`（2 行） |
| 独立复核输出 | 同上 `merged/verification.json`、`merged/verification.md` |
| 分组原始日志 | 同上 `stack-a/`、`stack-b/` |
| DDS 安全回归 | 同上 `dds-security-regression/` |
| 工作区（gitignored）副本 | `logs/m3_online/m3online-20261016T134406Z/` |
| 历史预检证据（**未改动**） | `artifacts/demo-2026-10-19/preflight-20261016/` |
| 历史 SROS 2 证据（**未改动**） | `artifacts/acceptance/exports/m2_sros2_enforce/logs/tests_evidence/20261009T093144Z/` |

**未包含任何私钥、keystore 或凭据**（已实测：证据目录内 `.pem/.key/.p7s` 文件数为 0）。

---

## 14. 当前真实可运行的系统组合

**`M1 MOCK + M2 MOCK + M3 EXTERNAL`**（ROS 2 Jazzy，域 42）：

```
ModuleInputEnvelope
  → team_demo --online
  → READY_FOR_GATEWAY_SUBMISSION
  → Planner（真实 ROS 2 Action Client）
  → /rg/guarded_navigate
  → SecurityGateway（权威 TaskPolicy）
  → ALLOW only
  → /rg/nav_execute
  → NavigationSim（+1 Goal）
```

**必须明确**：该组合中 **M1 与 M2 是显式 Mock**，**不是**三模块全真实联合系统。

---

## 15. 未完成事项及其影响

| 事项 | 状态 | 影响 |
| --- | --- | --- |
| PR base 整改（#6/#7/#8 的 base 为 `main` 而非 `baseline`） | **`BLOCKED_PERMISSION`** | 违反团队政策；有误合入 `main` 的风险；需有权限者操作 |
| 三模块全真实联合 | `NOT_READY` | M1 缺可加载的数值 JSON 模型（仅有 joblib，而模块明确拒绝 joblib）；M2 对当前候选入口恒 `UNKNOWN` |
| M1 检测有效性 | `NOT_READY` | 两数据集 F1 均低于恒预测攻击基线，门槛 FAIL；仅覆盖 1 类攻击 |
| M2 参与在线链路 | `NOT_RUN` | 需先为 `/rg/guarded_navigate` 补充受控安全实验，否则其恒 `UNKNOWN` 会持续阻断 |
| ROS 2 实时入侵检测 | `NOT_READY` | 无在线特征采集代码 |
| DDS 动态权限调整 | `NOT_READY` | 仅静态最小权限 |
| `feature/m3-dynamic-policy` | `NOT_RUN` | 本轮未审查其算法；与 baseline 互不包含 |

---

## 16. 下一阶段建议

1. **优先**：由有 GitHub 写权限者完成 §2.3 的 PR base 整改与 #8 处置。
2. **优先**：为 M1 用交付版 `train.py` 重训并导出数值 JSON 模型（含 SHA256），
   使其可参与真实推理；**不要**把 joblib 塞给当前实现。
3. 把本分支（`integration/m3-online-evidence-20261016`）作为**独立证据 PR** 提交审查，
   **不**直接合入 `baseline`。
4. 若需 M2 参与在线链路，先为 `/rg/guarded_navigate` 补充受控实验，
   或由团队确认其恒 `UNKNOWN` 为预期行为。
5. 竞赛材料按 `docs/reviews/COMPETITION_CLAIMS_20261016_CURRENT.md` 的口径撰写，
   **不得**升级为"三模块全真实联合防御"。

---

## 附：供 ChatGPT 接续研发的最新系统上下文

> 本节可**直接复制**到新的 ChatGPT 会话，不依赖历史聊天记录。

### 项目与版本

- **项目**：面向具身智能机器人的 ROS 2 通信可信分析与动态最小权限防护系统。
  定位：系统安全为基础，应用安全为核心，具身智能机器人为应用场景。
- **日期**：2026-10-16。
- **baseline**：`a4c597161d254192b662ee7b8f4d17f76a89cc16`（未改动）。
- **契约**：`PROPOSED_V1` / `1.0.0-proposed`（**未冻结**）。
- **演示候选**：`demo/2026-10-19-rc` = `df5a0f0d3a12286b3dc3861fb104987cf10d21d3`。
- **本轮分支**：`integration/m3-online-evidence-20261016`（起点 `19f6a25`）。

### 系统架构（四层安全控制）

1. **DDS-Security**（SROS 2 / Fast DDS）：Enclave 独立身份 + `permissions.xml` 最小权限，域 43。
2. **三个研究分析模块**：M1 `comm_risk`、M2 `identity_trust`、M3 `task_risk`，只输出建议。
3. **F0 适配层**：`scripts/team_demo.py`，输入/输出 Schema 校验 + 三模块状态门槛，只有阻断权。
4. **SecurityGateway**：权威 TaskPolicy 准入；ALLOW 才允许 `/rg/nav_execute` → NavigationSim。

关键不等式：`READY_FOR_GATEWAY_SUBMISSION ≠ Gateway ALLOW`；
`Gateway ALLOW ≠ NavigationSim 执行成功`；`DDS 允许 ≠ Gateway 允许`。

### 四名成员真实状态

| 成员 | 实际算法 | 状态 |
| --- | --- | --- |
| M1 | ROSPaCe 49 特征 + LogisticRegression/ExtraTrees 监督二分类，导出纯数值 JSON 模型（拒绝 pickle/joblib） | 代码完整、44 项自带测试通过；**缺 JSON 模型**故无法真实推理；**性能门槛 FAIL**（F1 0.1312/0.6346 低于恒预测攻击 0.8132/0.8719，漏报 93%/53.5%，仅 1 类攻击） |
| M2 | 离线受控实验证据解释器（源策略 XML + 生成 permissions.xml + 归档 Enforce 日志三方交叉核验） | 23 项测试 + 真实验收 45 PASS；**不是**在线身份认证器；对当前候选入口恒 `UNKNOWN` |
| M3 | 确定性可解释规则引擎 `TASK_CONSTRAINT_RULES_V1`（任务 ID/坐标系/目标区域/可选审计历史） | 95 项测试 + 真实验收 45 PASS；**本轮已完成 ROS 2 在线联调** |
| M4 | F0 框架与集成（4 个 ROS 2 包、公共契约、适配层、Gateway、DDS 安全配置） | 全量单元测试通过；Gateway A/B 与 DDS Enforce 均实测通过 |

### 已验证的安全边界（本轮 `VERIFIED_THIS_RUN`）

- Gateway 权威准入：ON-01 合法任务 `ALLOW` + Action `EXECUTED` + NavigationSim **+1 Goal**。
- 越权阻断：ON-02 M3 `BLOCK_RECOMMENDED` → `ADAPTER_BLOCK`，Planner 未启动，Goal **0**。
- 失败关闭：ON-03 `UNKNOWN` / ON-04 `ERROR` 均阻断，Goal **0**。
- **Gateway 独立权威**：ON-05 M3 建议允许且适配层放行，Gateway 仍 `BLOCK/OUT_OF_REGION`，Goal **0**。
- 超时语义：ON-06 `PLANNER_RESULT_TIMEOUT`，未记为 BLOCK，未重试。
- DDS Enforce：域 43 S1–S6 **7/7 PASS**，含原生拒绝与正向对照。
- 跨层可复核：独立工具 19 项检查 **0 失败**，含 5 类篡改反例测试。

### 在线联调是否完成

**M3 的在线联调已完成**（`M1 MOCK + M2 MOCK + M3 EXTERNAL`，域 42）。
**三模块全真实联合未完成**，因为 M1 缺模型、M2 对候选入口恒 `UNKNOWN`。

### 仍然不具备的能力

- ROS 2 实时入侵检测（无在线特征采集）
- 有效的通信异常检测（M1 性能低于平凡基线）
- DDS 动态权限调整（仅静态最小权限）
- 动态任务状态机（独立分支未集成）
- M2 对当前请求的实时 DDS 身份认证（设计上不承担）

### 最重要的三个剩余问题

1. **PR #6/#7/#8 的 base 均为 `main`（应指向 `baseline`）**，违反团队政策且本环境无写权限；
   须先改为 `baseline`（#6）、`chore/member-deliveries`（#7），#8 无独立内容应说明后关闭。
2. **M1 缺可加载的数值 JSON 模型**，阻断三模块全真实联合；
   需用交付版 `train.py` 重训导出（数据仍在 `data/ROSPaCe_reduced/`，25G）。
3. **M2 对 `/rg/guarded_navigate` 恒 `UNKNOWN`**（安全收紧，非缺陷），
   使全真实联合无法达到 READY；需为其补充针对候选入口的受控实验，或确认该行为为预期。

### ChatGPT 后续分析必须遵守的约束

- 契约 `PROPOSED_V1` **未冻结**；不得擅自冻结或改 Schema 语义。
- 冻结的 `PatrolNavigate` Action 与**八个** `DECISION_REASON_CODES` 不得更改。
- `config/task_policy.yaml` 是 Gateway **唯一**任务约束权威，不得为让模块通过而修改。
- 不得放宽 DDS 最小权限、不得把 Enforce 降为 Permissive、不得绕过 Gateway。
- 研究模块输出只是**建议**；`UNKNOWN`/`ERROR` 默认不得推进。
- `event_id` 是唯一事件标识，**不承担**完整 `request_id` 的编码责任；
  跨层关联以显式 `run_id`/`request_id` 为准。
- 不得把 Mock / 测试替身 / 离线模型表述为真实在线算法能力。
- 引用版本用**标签或完整 SHA**，不要用浮动分支名。
