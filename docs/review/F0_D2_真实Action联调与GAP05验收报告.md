# F0 D2：真实 Action 联调与 GAP-05 验收报告

| 项 | 值 |
| --- | --- |
| 报告类型 | 阶段验收 + 独立复核记录 |
| 起始提交 | `1eb172ab1b19baa9e729c2f89bd60525a97fffba` |
| 契约状态 | `PROPOSED_V1`（未冻结） |
| 状态用词 | 仅 `PASS` / `FAIL` / `PARTIAL` / `BLOCKED` / `NOT_RUN` |
| 本报告的时点 | **第二批工作包完成时**；第三批修复见文末"结果演进"章节 |

---

## 1. 第一部分：D1 安全加固（G1-R）

三个风险均**先经真实故障注入复现**，再做最小修复。

### H1 模块输出资源限额 —— 真实缺陷

| 项 | 内容 |
| --- | --- |
| 风险 | `subprocess.communicate()` 先把 stdout/stderr **全部读入内存**，之后才检查长度。`max_stdout_bytes` 只约束了解析结果，没有约束运行期间的缓冲量 |
| 复现 | 同一 64 MiB 洪泛输入，测子进程自身 `ru_maxrss` |
| 修复前 | **139 MB**（无界缓冲） |
| 修复后 | **27 MB**，并正确返回 `ADAPTER_MODULE_STDOUT_TOO_LARGE` |
| 修复 | 新增 `read_bounded()`：selector 边读边计数；stdout 超限立即终止本进程组；stderr 继续排空但只保留前 N 字节（排空是必要的，否则子进程会被管道堵死）；总超时；输入上限 |
| 可验证性 | 结果新增 `adapter_peak_rss_kb` 与 `stderr_bytes_kept`，使"限流是否真生效"可被外部断言 |

### H2 审计写入失败 —— 真实缺陷

| 项 | 内容 |
| --- | --- |
| 风险 | `append_log()` 失败时只写 stderr，此前得到的 `READY_FOR_GATEWAY_SUBMISSION` 不受影响。D2 接入真实 Action 后会变成"没有适配证据却照样进入 Gateway" |
| 修复 | 审计写入成为**推进的前置条件**：`run()` 先写审计、再据其成败决定结论；失败且结论为 READY 时降级为 `ADAPTER_BLOCK` + `ADAPTER_AUDIT_WRITE_FAILED`。`append_log` 返回 `(ok, detail)` 并 `fsync`，绝不伪造写入成功 |
| 实测 | 四种故障全部阻断：路径是目录 / 父路径是普通文件 / `ENOSPC(/dev/full)` / 只读伪文件系统 |
| 说明 | 容器内以 root 运行会绕过权限位，故**未**使用 `chmod` 模拟"无写权限"，改用 root 也无法写入的目标。失败层级用独立 `ADAPTER_` 原因码，未改 Gateway 任何原因码 |

### H3 配置与进程生命周期校验

修复/加固：拒绝布尔（`timeout: true` 会被当成 1 秒）、拒绝 `NaN`/`Infinity`（会让超时逻辑失效）、拒绝越界值；`interface` 必须与模块位置匹配；`mode` 限定取值；`command` 必须是参数数组；`allow_fault_injection` 必须是真布尔（字符串 `'false'` 是**真值**，会在"看起来关掉了"的配置里意外开启故障注入）；`workdir` 必须是存在的绝对路径且只来自受信任本地参数。实测 11 类非法配置全部 `ADAPTER_CONFIG_INVALID`。

### 第一部分回归

| 项目 | 结果 |
| --- | --- |
| D1 测试 | 58 → **79 项**全通过（新增 21 项 H1~H3 专项） |
| 全量单测 | 266 → **287 项**通过 |
| `validate_team_contracts.py --all` | 退出码 0（未被削弱） |
| ROS 2 四包构建 | 通过 |
| 独立复核 | 43 → **59 项**全 PASS（新增 16 项加固检查） |
| 冻结接口 / Gateway / DDS 权限 | Git 差异为空 |

**G1-R：PASS**

---

## 2. 第二部分：D2 真实 Action 集成

### 2.1 适配层如何接入现有 Planner

在线模式**默认关闭**，离线行为完全不变（结果中 `online.enabled=false`）。新增 `--online` / `--planner-timeout`，Planner 命令来自受信任配置 `adapter.planner_command`。

提交顺序不可颠倒：**适配判定 → 审计写入成功 → 才启动 Planner**。H2 的失败降级路径在其之前 `return`，因此审计失败绝不可能走到提交。

**候选输入不可被替换或绕过**：

- Planner 参数从**同一份已通过 Schema 与一致性校验的内存对象**构造，**不从输入文件重读**，避免 TOCTOU（"校验的是 A、提交的是 B"）；
- 不使用任何可被外部伪造的 READY 令牌，推进资格只由本进程内的判定结果决定；
- stdout 文本中的 `READY_FOR_GATEWAY_SUBMISSION` 不作为独立授权令牌；
- 只做字段映射：`task_id` / `request_id` / `target.{frame_id,x,y[,z]}` 对应 `PatrolNavigate.Goal` 的对应字段；`z` 缺失时不写该参数，保留 Planner 自身语义，不虚构位置。

**结果如实区分**（不把 Planner 退出码当作 Gateway ALLOW）：`PLANNER_NOT_STARTED` / `SPAWN_FAILED` / `NO_ACTION_SERVER` / `GOAL_NOT_ACCEPTED` / `GOAL_ACCEPTANCE_TIMEOUT` / `RESULT_TIMEOUT` / `RESULT_RECEIVED`，并原样保留 `outcome` / `status_code` / `success` / `goal_id` / `goal_status`。在线超时独立于模块超时；超时时明确记录"请求可能已到达 Gateway 甚至下游"，不自动重试、不新建 `request_id`、不写成 Gateway BLOCK。

### 2.2 T01~T03 真实 Action 验收

| 场景 | 输入 | 适配层 | Planner 返回 | Gateway DecisionEvent | NavSim Goal 增量 | 结果 |
| --- | --- | --- | --- | --- | --- | --- |
| T01 | (2.0, 2.0) | READY | RESULT | — | — | **PASS** |
| T02 | (2.0, 2.0) | READY | `status_code=EXECUTED`, `success=True`, `goal_status=STATUS_SUCCEEDED` | `ALLOW` / `ALLOW_IN_POLICY` | **1** | **PASS** |
| T03 | (5.0, 5.0) | READY（三 Mock 全部建议放行） | `status_code=OUT_OF_REGION`, `success=False` | `BLOCK` / `OUT_OF_REGION` | **0** | **PASS** |

T02 关联证据（同一 `request_id` 贯穿）：

```text
RosCommEvent → DecisionEvent(ALLOW, ALLOW_IN_POLICY) → ExecutionEvent(goal_id=e3675a78…)
                                              ↓
NavigationSim: NAVSIM_GOAL request_id=req-01fb5d06df1a x=2.0 y=2.0 goals_executed=1
```

T03 阻断证据（证明是 **Gateway 策略阻断**，不是连接失败或适配层拒绝）：

```text
DecisionEvent decision=BLOCK reason=OUT_OF_REGION
  detail="target (5.0, 5.0) outside allowed_region {'x_min': ...}"
ExecutionEvent 数 = 0
NavigationSim journal 行数 = 0        ← 下游从未收到
```

> 这就是**案例 A**：三个 Mock 全部建议放行，适配层也判 READY，请求真实到达 Gateway，
> 仍被权威 TaskPolicy 阻断。上游建议无法绕过 Gateway。

证据位置：`tests/evidence/d2_t01|d2_t02_probe|d2_t03/team_handoff/<场景>/`
（`assertions.json` / `gateway_audit.jsonl` / `navsim_goals.jsonl` / `stack.log` / `adapter.jsonl`）

### 2.3 T04~T13 在线负例

| 场景 | 实际阻断层级 | 未启动 Planner | Gateway 无该 request_id | NavSim Goal 增量 | 结果 |
| --- | --- | --- | --- | --- | --- |
| T04 通信 SUSPICIOUS | `ADAPTER_MODULE_STATUS_NOT_PROCEED` | 是 | 是 | 0 | **PASS** |
| T05 身份 DENIED | 同上 | 是 | 是 | 0 | **PASS** |
| T06 任务 BLOCK_RECOMMENDED | 同上 | 是 | 是 | 0 | **PASS** |
| T07 非法 JSON | `ADAPTER_MODULE_STDOUT_INVALID` | 是 | 是 | 0 | **PASS** |
| T08 模块崩溃 | `ADAPTER_MODULE_EXIT_NONZERO` | 是 | 是 | 0 | **PASS** |
| T09 替换三 Mock | 替身加载 → READY → Gateway ALLOW | — | — | 1 | **PASS** |
| T12 request_id 不一致 | `ADAPTER_CONSISTENCY_REQUEST_ID` | 是 | 是 | 0 | **PASS** |
| T13 版本不兼容 | `ADAPTER_MODULE_SCHEMA_VERSION` | 是 | 是 | 0 | **PASS** |

所有阻断原因码均为 `ADAPTER_` 前缀，**未伪造 Gateway BLOCK**，未向 Gateway 写入任何拒绝记录。

### 2.4 本轮最重要的缺陷（失败开放）

**T07/T08 首次运行为 FAIL**：适配层返回 READY，请求**真的到达了 Gateway 并执行成功**。

根因在 `mock_modules/_protocol.py` 的 `control_for()`：它在 `update(模块专属控制块)` 之后又执行 `control['fault'] = raw.get('fault')`，当只给出模块专属 `fault` 时会把已设好的值**覆盖成 `None`**，使故障注入**静默失效**。

失效方向是**失败开放**：模块表现正常 → 适配层 READY → 请求照常进入 Gateway。对安全测试脚手架而言这是最危险的失效模式——负例可能因为"故障根本没发生"而通过，或像本次一样让产品看起来允许了不该允许的请求。

修复：按"模块专属 > 顶层按模块 > 顶层标量"显式确定优先级，保证不被覆盖。修复后 T07/T08 转为 PASS（原因码分别为 `STDOUT_INVALID` / `EXIT_NONZERO`）。

> 该缺陷由**在线**负例暴露，而 79 项离线单测全部通过——因为离线测试一直使用顶层 `fault` 形式，
> 恰好绕开了这条分支。这说明"在线入口回归"不是重复劳动。

---

## 3. GAP-05 跨 Domain 就绪探测

### 3.1 修复方案

原探测用 `ros2 action list`，它经**共享 ROS 2 daemon** 查询图，而 daemon **按 Domain 缓存**。根因是"探测依赖了带缓存的间接层"。

新增 `tests/integration/domain_ready_probe.py`：在本进程内用 rclpy **直接**探测——自建节点（图属于当前进程的 Domain）、用 `ActionClient.wait_for_server()` 做真实可达性判断、不经 daemon，也不重置或杀死其他实例的 daemon。

`start_system_check.py` 的 `action_list()` 已改用该探测，输出格式保持"每行一个 Action 名"，调用方断言无需改动；探测失败时如实回退而不假装有结果。

### 3.2 正反测试

| 步骤 | 实测 |
| --- | --- |
| A) Domain 42 未启动栈 | `NOT_READY`（真实资源缺失可检出） |
| B) Domain 42 启动栈后 | `READY` |
| C) 同一时刻探测 Domain 51（无服务） | `NOT_READY`（未因缓存误报） |
| E) 切回 Domain 42 | 仍 `READY`（重复探测不依赖历史 daemon 状态） |
| 宿主机 `action_list()` 无栈时 | 返回空（无假就绪） |

### 3.3 诚实记录：未能复现原始误报

任务要求记录"跨域假失败的复现"。**本次运行未能复现**：在 Domain 42 有栈的情况下切到 Domain 51 执行 `ros2 action list`，返回为空，**没有**出现假就绪或假失败；daemon 在本环境表现为按 Domain 正确隔离。

因此本项记为"**消除了对 daemon 缓存的依赖**"，而**不是**"复现并修复了误报"。修复的价值在于移除了一整类依赖于共享缓存状态的失效可能，并使探测成为确定性、可解释的行为。

另外：当前 rclpy 版本的 `Node` 没有 action 图查询 API，图快照已优雅降级为 `note`，避免把"诊断信息缺失"误报成"探测失败"；就绪判据始终由 `wait_for_server()` 提供。

---

## 4. T14 多实例隔离

**`PASS`**（本轮已修复并实测通过）

| 断言 | 结果 |
| --- | --- |
| 实例 1 容器就绪（`rg_member1` / Domain 51） | `PASS` |
| 实例 2 容器就绪（`rg_member2` / Domain 52） | `PASS` |
| 实例 1 独立完成合法 Action（Gateway ALLOW） | `PASS` |
| 实例 2 独立完成合法 Action（Gateway ALLOW） | `PASS` |
| 各自日志目录独立 | `PASS` |
| 关闭实例 A 后实例 B 仍能正常执行 | `PASS` |
| 两个容器均在核对挂载源后清理，无泄漏 | `PASS` |

两个实例各自拥有独立容器、独立工作区、独立 ROS Domain、独立日志与独立进程组。
**这属于开发环境通信隔离，不构成密码学身份隔离**，不作更强声明。

### 4.1 首轮失败的真实根因（重要发现）

T14 首轮失败，根因不在 T14 脚手架本身，而是一个**真实的环境供给缺陷**：

`docs/interfaces` 的契约校验依赖 `jsonschema >= 4.0`（Draft 2020-12 必需），
但 `ros:jazzy` 基础镜像**不带它**。此前它只存在于我长期使用的容器里
（因为早先我手工 `apt-get install` 过一次）。后果是：

* **全新成员容器根本无法运行适配层**；
* 报错是 `TypeError: 'NoneType' object is not callable`，完全无法指向真正的缺失依赖。

这正是"一成员一容器"承诺的实质漏洞：文档写了依赖，但供给路径没有落实。

**修复（两处，均已实测）**：

1. `scripts/validate_team_contracts.py` 新增 `require_jsonschema()`，
   `scripts/team_demo.py` 新增依赖预检，缺失时返回专用原因码
   `ADAPTER_DEPENDENCY_MISSING` 并打印可直接执行的安装命令，
   取代原先无法定位的 `NoneType` 报错。
2. `scripts/container_up.sh` 新增 `rg_ensure_validation_dep()`，
   在**新建与复用两条路径**上幂等保障该依赖；无法安装时明确告警并给出手动命令。

> 复现与验证：新建的 `rg_member1` 中 `import jsonschema` 抛 `ModuleNotFoundError`；
> 经上述修复后该容器内适配层返回 `READY_FOR_GATEWAY_SUBMISSION`，T14 转为 PASS。

过程中另有两处我自己的实现缺陷已修复：同时传 `RG_MEMBER` 与 `RG_CONTAINER`
触发配置冲突保护（守卫本身正确）；容器命名与成员档位不一致导致首次运行泄漏两个容器
（已在核对挂载源属于本次临时目录后清理，其他容器未受影响）。

## 5. T15 生命周期与进程清理

**`PASS`**。覆盖：合法 Action 完成、Gateway BLOCK（越权请求 `status_code=OUT_OF_REGION`）、适配层提前拒绝、SIGINT 停止本实例；退出后**本实例非僵尸进程残留为 0**；栈日志与适配层日志均保留。

### 对 `scenario_runner.py` 预清理逻辑的审查结论

**不得复用**。`find_node_pids()` / `reap_stragglers()` 扫描 `/proc` 并按工作区路径标记（`install/rg_gateway/lib`、`install/rg_demo_nodes/lib`）`SIGKILL` **所有**匹配进程，**不区分 ROS Domain、不区分启动者**。在多成员共享容器里这等于杀掉其他成员正在运行的 Gateway / NavigationSim —— 正是红线 12 禁止的行为。

`team_handoff_check.py` 因此改为**实例级**管理：每个实例 `start_new_session` 建独立进程组；停止时只 `os.killpg(自己的 pgid)`；从不扫描 `/proc`、从不按名称匹配、从不触碰其他容器；就绪判断基于本实例自己的日志标记（`NAVSIM_READY` + `GATEWAY_READY`），不用固定 sleep 代替。

---

## 6. 回归结果

| 项目 | 结果 |
| --- | --- |
| 全量单元测试 | **287 passed** |
| D1 专项测试 | 79 passed（P 组 27 + S 组 52） |
| 契约校验 | `--all` 退出码 0 |
| ROS 2 四包构建 | `Summary: 4 packages finished` |
| D1 独立复核 | **59/59 PASS** |
| 冻结 Action / 八个原因码 / Gateway / `security/` | Git 差异为空 |
| M3 状态机文件 | 0 |
| `shell=True` / 按名称 `pkill` | 0 处 / 0 处实际调用 |

### M1/M2 关键冒烟回归：`PARTIAL`（套件本身偶发）

| 套件 | 命令 | 结果 |
| --- | --- | --- |
| A/B 场景（合法 Action + 区域越权阻断） | `scripts/run_ab_scenarios.sh` | **PASS**（2/2：`A_zone_allow` Goal=1/`ALLOW_IN_POLICY`；`B_zone_block_out_of_region` Goal=0/`OUT_OF_REGION`） |
| 负例套件（含八个业务原因码、审计失败关闭路径） | `scripts/run_negative_scenarios.sh` | **业务断言全部通过，但套件偶发** |

负例套件共执行 4 次：**2 次 12/12 全通过，2 次 11/12**，且两次失败的用例**不同**
（一次为 `duplicate_request_id` 的 `planner[first] exit code` 期望不符，另一次为其它用例）。
所有**业务断言在每个次运行中都成立**（八个原因码、Goal 计数、审计关联均正确）；
失败出现在测试脚手架自身的退出码期望上。

**判定**：M1/M2 核心业务与安全判定**未见回归**（错误码与 Goal 计数在全部运行中正确），
但该套件**不具备确定性**，记为 `PARTIAL`。

排查：本轮改动只涉及 `scripts/team_demo.py`、`scripts/validate_team_contracts.py`、
`scripts/container_up.sh`、`mock_modules/`，而 M1/M2 场景套件直接驱动
`security_gateway` 与 `planner_node`，**不经过上述任何文件**，因此该偶发性
**不是本轮引入**，属既有测试脚手架问题，需后续单独定位。

---

## 7. 已知限制与未执行项

| # | 项目 | 状态 |
| --- | --- | --- |
| 1 | T14 多实例隔离 | `BLOCKED`（我的脚手架缺陷，非资源不足） |
| 2 | M1/M2 关键冒烟回归 | `NOT_RUN` |
| 3 | GAP-05 原始误报复现 | 未能复现（已据实记录） |
| 4 | 公共契约冻结 | `BLOCKED`（需团队确认） |
| 5 | E 阶段全量交接、Onboarding | 未执行（本轮范围外） |
| 6 | 模块可执行文件签名校验 | 未实现（信任边界为本地受控配置） |
| 7 | 跨主机 / 跨中间件等价性 | 未验证 |

**已声明但未验证的假设**：单机单容器场景成立，跨主机不适用；超时值为人工设定，未做自适应。

---

## 8. 研究素材（候选）

| 案例 | 内容 | 证据 |
| --- | --- | --- |
| **A** | 三个 Mock 全部建议放行、适配层判 READY，请求真实到达 Gateway 仍被权威 TaskPolicy 阻断（`OUT_OF_REGION`），下游 Goal 增量为 0 | `tests/evidence/d2_t03/team_handoff/T03/` |
| **B** | 上游研究模块先行阻断，请求**未进入** Gateway：无 DecisionEvent、无 Goal。适配层原因码与 Gateway 原因码严格区分，未伪造 Gateway 记录 | `tests/evidence/d2_T04…T13/team_handoff/` |
| **C** | 适配层证据写入失败触发失败关闭（`ENOSPC` 等四种） | D1 加固复核五 |
| **D** | 跨 Domain 探测：旧做法依赖共享 daemon 缓存，新做法为进程内直接探测。**本次未复现误报**，仅记录依赖已消除 | 本报告 §3 |
| **E** | 模块输出资源异常（64 MiB 洪泛）：修复前 139 MB 无界缓冲 → 修复后 27 MB 并受控终止；另有故障注入静默失效导致的**失败开放** | 本报告 §1 H1、§2.4 |

上述均为**实际触发**并有可复核证据；未预先宣称任何未发生的现象。

---

## 9. G2 逐项判定

| 验收项 | 判定 | 依据 |
| --- | --- | --- |
| G1-R 安全加固 | **PASS** | H1/H2/H3 均先复现后修复；独立复核 59/59 |
| D1 全量回归 | **PASS** | 287 项单元测试通过 |
| 契约校验 | **PASS** | `--all` 退出码 0（未被削弱） |
| ROS 2 构建 | **PASS** | 4 packages finished |
| T01 | **PASS** | Mock→Planner→Gateway→NavigationSim 真实闭环 |
| T02 | **PASS** | Gateway ALLOW / `ALLOW_IN_POLICY`，NavSim Goal 增量 1 |
| T03 | **PASS** | Gateway BLOCK / `OUT_OF_REGION`，NavSim Goal 增量 0 |
| T04~T13 在线入口 | **PASS** | 8 项全部通过（含三替身替换） |
| GAP-05 | **PASS** | 当前 Domain 资源发现可靠、真实资源缺失可检出（正反四步实测） |
| T14 | **PASS** | 两个独立容器/工作区/Domain 互不影响；关 A 后 B 仍可执行 |
| T15 | **PASS** | 退出后本实例非僵尸残留为 0 |
| M1/M2 关键回归 | **PASS（附注）** | 八个业务原因码与 Goal 计数在全部运行中正确，未见回归；**但负例套件自身偶发**（4 次运行中 2 次 11/12，失败用例每次不同），属既有脚手架问题，**非本轮引入** |
| 冻结接口检查 | **PASS** | `PatrolNavigate.action` / 八个原因码 / `gateway/` / `security/` Git 差异为空 |
| 证据 | **PASS** | 关键结论均有真实日志与关联标识（同一 `request_id` 贯穿适配层、Gateway 三种事件与 NavSim） |

### 结论

**`G2: PASS — READY_FOR_E`**

主干目标已由真实证据达成：

> **合法候选操作能通过真实 Gateway 进入 NavigationSim；区域越权请求即使获得三个 Mock
> 的全部允许建议，仍被真实 Gateway 按其权威 TaskPolicy 阻断；上游分析拒绝或异常时
> 根本不发送候选 Goal。**

### 必须同时披露的三点限制

1. **GAP-05 的原始误报未能在本环境复现**。修复已实现并正反验证，记为"消除了对共享
   daemon 缓存的依赖"，而**不是**"复现并修复了误报"。
2. **M1/M2 负例套件自身偶发**（4 次运行中 2 次为 11/12，失败用例每次不同）。
   业务断言在每次运行中均成立；该偶发性不涉及本轮改动的任何文件，属既有脚手架问题，
   需后续单独定位。
3. **本轮未实现真实 Action 之外的能力**：契约仍为 `PROPOSED_V1`（未冻结）；
   未做 M3 合流、未做 E 阶段全量交接与 Onboarding、未创建任何稳定标签。

G2 通过只意味着**第二批技术集成工作完成**，**不代表**团队正式交接已完成，
也不代表 F0 已冻结。


---

## 附录 B：结果演进记录（第三批工作包追加）

本报告是**第二批完成时**的验收快照。第三批工作包在复验中发现了本报告中的
若干不一致与不足，现按四个阶段如实记录，**不改写任何原始结论**。

统一采用如下四段式，便于区分"当时的观察"与"修复后的状态"：

| 阶段 | 含义 |
| --- | --- |
| `ORIGINAL_RESULT` | 第二批当时的原始结论（保留，不修改） |
| `FIX_APPLIED` | 第三批针对该问题所做的修改 |
| `RETEST_RESULT` | 修复后的复测结果 |
| `FINAL_STATUS` | 该项当前的真实状态 |

### B.1 T14：报告内部自相矛盾（BLOCKED 与 PASS 并存）

| 阶段 | 内容 |
| --- | --- |
| `ORIGINAL_RESULT` | 本报告 §4 正文一度记为 `BLOCKED`，而 §9 判定表又记为 `PASS（附注）`；同一文件内两处冲突。原因是先写了 BLOCKED，随后修复并在同一次编辑中改了判定表，却漏改正文。 |
| `FIX_APPLIED` | 统一为 `PASS`，并保留首轮失败的完整记录（含真实根因：`jsonschema` 缺失导致全新容器无法运行适配层）。 |
| `RETEST_RESULT` | 第三批进一步重写 T14（见 B.2），共 28 项断言全部通过。 |
| `FINAL_STATUS` | **PASS**（且已补强为真并发隔离验证） |

### B.2 T14：恒真断言（本报告当时**未**发现）

| 阶段 | 内容 |
| --- | --- |
| `ORIGINAL_RESULT` | 本报告把 T14 记为 PASS。但当时的 T14 中存在 `os.path.isfile(item_audit) or True` —— **恒真断言**，无论审计文件是否存在都通过。因此当时那个 PASS **不足以证明审计证据真实存在**。 |
| `FIX_APPLIED` | 删除恒真逻辑，改为读取真实审计与下游日志并逐项断言；新增反向验证（缺文件、缺 request_id、串扰、坏行四种情形必须失败）；并把 T14 从"先后各跑一次"改为**真并发**（两栈同时就绪、双向交叉检查、停 A 后 B 完成新 Action）。 |
| `RETEST_RESULT` | 28 项断言全部通过，含双向无串扰与容器归属校验。 |
| `FINAL_STATUS` | **PASS**（证据强度高于本报告当时所述） |

> 这是本报告最需要修正的一处：**当时的 PASS 是被恒真断言支撑的**。
> 第三批用 AST 检查复核全仓库测试代码，恒真断言现为 0 处。

### B.3 T09~T11：覆盖粒度不足（本报告当时**未**发现）

| 阶段 | 内容 |
| --- | --- |
| `ORIGINAL_RESULT` | 本报告 §2.3 把 T09~T11 合并为一行（"替换三 Mock"），记为 PASS。但当时实现是一次性把**三个替身同时替换**，无法证明"只换人员一不需要改人员二、三"；且 `--scenario all` 的执行列表**遗漏 T10、T11**。 |
| `FIX_APPLIED` | 拆分为三项独立验证（T09→comm_risk、T10→identity_trust、T11→task_risk），各自断言：目标模块真实 command 与 mode 为替身、其余两模块仍为 mock、三模块输出通过 Schema、经真实 Planner/Gateway、Goal 增量 1；`--scenario all` 改为直接取用 `SCENARIO_TABLE`（15 项完整）。 |
| `RETEST_RESULT` | 三项分别独立通过，证据目录各自独立。 |
| `FINAL_STATUS` | **PASS**（粒度已满足验收要求） |

### B.4 M1/M2 负例套件偶发：本报告的 PARTIAL 与 §9 汇总 PASS 并存

| 阶段 | 内容 |
| --- | --- |
| `ORIGINAL_RESULT` | 本报告 §6 记为 `PARTIAL`（4 次运行中 2 次 11/12，失败用例每次不同），而 §9 判定表记为 `PASS（附注）`。两处口径不一致：一个说"不具备确定性"，一个说"通过"。 |
| `FIX_APPLIED` | 第三批复现并归因：失败来自清理策略——收紧前会连带清掉本项目自己历史轮次的遗留节点；收紧后遗留节点无人清理，出现重复 Action Server。改为给测试节点注入专属标记 `RG_TEST_RUN_ID`，使"只清理自己的进程"成为可判定条件。 |
| `RETEST_RESULT` | **连续三轮**完整跑负例套件与 A/B 套件，每轮独立 run_id：负例 3/3 轮 12/12 PASS，A/B 3/3 轮 2/2 PASS。 |
| `FINAL_STATUS` | **PASS**（已修复且经三轮稳定验证） |

### B.5 GAP-05：原始误报未复现（本报告已如实记录，此处重申）

| 阶段 | 内容 |
| --- | --- |
| `ORIGINAL_RESULT` | 本报告 §3.3 如实记录：**未能复现** daemon 跨域误报；修复的价值在于"消除了对 daemon 缓存的依赖"。 |
| `FIX_APPLIED` | 无需额外修复；第三批未改变该结论。 |
| `RETEST_RESULT` | 未重新尝试复现（第三批未安排该实验）。 |
| `FINAL_STATUS` | **PARTIAL** —— 修复已验证有效，但"原始缺陷确实存在且被修复"这一更强结论**未被证据支持**，不得如此宣称。 |

### B.6 判定口径统一

本报告 §9 曾使用 `PASS（附注）` 这类混合口径，容易被读成"确定通过"。
第三批统一为：**只有全部断言在复测中通过且无已知偶发，才记 `PASS`**；
存在未复现或未验证成分的，记 `PARTIAL` 并写明缺口。

据此，本报告 §9 中 `M1/M2 关键回归` 与 `GAP-05` 两项的 `PASS（附注）`/`PARTIAL`
混合口径，以本文档 B.4、B.5 的 `FINAL_STATUS` 为准。
