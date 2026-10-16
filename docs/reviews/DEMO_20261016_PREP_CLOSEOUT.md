# RosSystem 2026-10-16 阶段收尾报告（10 月 19 日演示候选准备）

- 仓库：`godzwp117/RosSystem`
- 本地工作区：`/home/zhangwei/project/RosSystem`（演示候选 worktree：`/home/zhangwei/project/RosSystem-demo-1019`）
- 执行日期：2026-10-16
- 契约：`PROPOSED_V1` / `1.0.0-proposed`（**未冻结**，本轮未改任何 Schema 语义）
- 运行环境：WSL2 / Ubuntu 24.04 容器 `rg_jazzy`（`ros:jazzy`）/ ROS 2 Jazzy / `rmw_fastrtps_cpp` / Domain 42（普通）、43（Enforce）

> 状态口径：`FIXED` 有测试证明的源码修复｜`VERIFIED` 本轮实际重新执行并通过｜
> `PARTIAL` 部分验证｜`NOT_RUN` 未执行｜`BLOCKED` 环境受限。
> **历史验收报告不得替代本轮执行结果**；本报告所有 PASS 均为本轮实跑。

---

## 1. 执行摘要

本轮完成了阶段收尾的全部**代码与离线**工作，并**恢复并复验了真实 ROS 2 / DDS-Security 环境**：
容器内 Gateway/NavigationSim A/B 演示 8/8 通过，SROS 2 Enforce S1–S6 对照 7/7 通过
（含原生 Fast DDS 拒绝与正向对照），验收器两个已知严谨性缺陷已修复并有反例测试。

| 项目 | 结果 | 状态 |
|---|---|---|
| Git 状态核对 | 全部 SHA 与任务书预期一致；工作区干净 | **VERIFIED** |
| PR #6 / #7 状态 | 两条 PR 均 **open**，**目标分支均为 `main`**（非任务书假设的 baseline） | **VERIFIED** |
| 演示候选分支 | `demo/2026-10-19-rc` = `92e884f` | **VERIFIED** |
| 验收器缺陷一（LIM-01 恒 PASS） | 已修复 + 反例测试（可证伪） | **FIXED + VERIFIED** |
| 验收器缺陷二（REAL-STATE 未校验退出码） | 已修复 + 反例测试 | **FIXED + VERIFIED** |
| ROS 2 Jazzy 环境 | 已恢复并验证（4 包构建、Action 类型正确） | **VERIFIED** |
| Gateway/NavigationSim A/B | 8 passed / 0 failed（修复前后各跑一次） | **VERIFIED** |
| DDS-Security Enforce S1–S6 | 7 passed / 7 total，域 43，含原生拒绝 | **VERIFIED** |
| M2 真实验收 | 45 PASS / 3 FAIL(不适用) / 门槛 True | **VERIFIED** |
| M3 真实验收 | 45 PASS / 3 FAIL(不适用) / 门槛 True | **VERIFIED** |
| 全仓单元测试 | **575 passed, 3 skipped** | **VERIFIED** |
| 10 月 17 日 M3 在线联调 | 链路已离线打通；在线提交未执行 | **READY (离线就绪)** |

**整体状态：`READY_FOR_M3_L3`** —— 详见 §12。

---

## 2. 固定 Git SHA 与工作分支

### 2.1 本轮核对的实际 SHA（`git ls-remote` + 本地 `rev-parse` 双向确认）

| 引用 | SHA | 与任务书预期 |
|---|---|---|
| `origin/baseline` | `a4c597161d254192b662ee7b8f4d17f76a89cc16` | ✅ 一致，**未被移动** |
| `origin/chore/member-deliveries` | `3ce820258c69b89e2ad9291e16c44dc7d2b99150` | ✅ 一致 |
| `origin/main` | `838f66f41821edf0421612a205d162ae8e9eb955` | — |
| `origin/fix/m2-m3-acceptance` | `2d0610eb0a9a304e74a625c530fa22cabf725251`（修复前 `13098b7a…`） | 本轮**前进 1 个提交** |
| `origin/demo/2026-10-19-rc` | `92e884fb42a7d68a239b9c33891e26c12b8749b8` | **本轮新建** |

### 2.2 分支职责（严格区分，未混用）

| 分支 | SHA | 角色 |
|---|---|---|
| `baseline` | `a4c5971` | 公共基线（本轮未推任何提交） |
| `chore/member-deliveries` | `3ce8202` | 三成员原始交付归档 |
| `fix/m2-m3-acceptance` | `2d0610e` | 后续整改成果（M2/M3 修复 + 验收器严谨性修复） |
| `demo/2026-10-19-rc` | `92e884f` | **演示集成候选开发起点**（合并了 fix 分支） |

`demo/2026-10-19-rc` 是**演示候选开发分支**，不是已验收通过的 RC1。

### 2.3 工作区状态

- 主工作区：`fix/m2-m3-acceptance`，工作区干净（仅 `user/` 交付归档，已由 `.git/info/exclude` 排除）。
- 独立 worktree：`/home/zhangwei/project/RosSystem-demo-1019` → `demo/2026-10-19-rc`。
- **未使用** `reset --hard` / `clean -fd` / 覆盖文件；未清除任何既有工作。

### 2.4 本轮新增的构建排除标记（非破坏性）

`user/COLCON_IGNORE`（新建，**未删除任何交付物**）。原因：`user/` 下存放三名成员交付归档，
其中成员一交付 ZIP 解出的 `RosSystem/src` 与本仓库 `src/` **同名包**
（`rg_demo_nodes` / `rg_gateway` / `rg_interfaces` / `rg_policy`），
导致 `colcon build` 报 `Duplicate package names not supported` 并中止（实测 exit 1）。
放置 colcon 官方忽略标记后构建通过。该文件不改变任何 ROS 包、安全策略或运行时行为。

---

## 3. PR #6 / #7 实际状态

**用 GitHub API 实测（`gh` CLI 未安装，改用 REST API + `refs/pull/*/head`），非推测：**

| 项 | PR #6 | PR #7 |
|---|---|---|
| 标题 | `Chore/member deliveries` | `Fix/m2 m3 acceptance` |
| 状态 | **open**（未合并） | **open**（未合并） |
| **base 分支** | **`main`**（`838f66f`） | **`main`**（`838f66f`） |
| head 分支 | `chore/member-deliveries` `3ce8202` | `fix/m2-m3-acceptance` `2d0610e` |
| commits | 44 | 51 |
| changed_files | 192 | 266 |
| ± | +59011 / −497 | +70573 / −497 |
| mergeable | true / clean | true / **unstable** |
| CI（`2d0610e`） | — | 4 项全部 **success**（`no-local-only-files`、`lightweight-gates`） |

### 3.1 关键发现：PR #6 与 PR #7 的依赖关系（不是"大范围重叠"而是**包含**）

实测 `git merge-base --is-ancestor origin/chore/member-deliveries origin/fix/m2-m3-acceptance` → **成立**。

即 **PR #7 完整包含 PR #6**（stacked PR）：
- PR #7 相比 PR #6 只多 **6 个提交**；
- 文件层面：PR #6 的 **192 个文件全部出现在 PR #7** 中，PR #7 另加自己的 36 个文件 + 审查归档 8 个 = 266。

**结论**：两条 PR **不能独立合并**。先合 PR #6 再合 PR #7 是唯一不会重复/冲突的顺序；
反之 PR #7 合并后 PR #6 会变成空 diff。

### 3.2 与任务书假设的差异（必须上报）

任务书建议"PR #6 以 `baseline` 为目标；PR #7 暂以 `chore/member-deliveries` 为目标"。
**实际两者目标都是 `main`**。这是**任务书假设与实际不符**，不是本轮造成的。

**未执行 PR 目标分支修改**：本环境只有 SSH 推送权限，无 GitHub 写 API 凭据；
任务书亦禁止在未获成员四授权时执行合并。因此只记录方案，**未谎称已调整**。

**建议的调整方案（需成员四确认后由有权限者执行）**：
1. `gh pr edit 6 --base baseline`（PR #6 → baseline）；
2. `gh pr edit 7 --base chore/member-deliveries`（PR #7 → PR #6 的分支，形成依赖审查）；
3. 待 PR #6 合入 `baseline` 后，将 PR #7 改为 `--base baseline`；
4. 每次改 base 后复核 diff / 冲突 / CI（本轮实测改 base 前后 mergeable 均为 true，风险低）。

---

## 4. 修改代码与原因

**唯一修改的源码文件**：`scripts/check_member_module.py`（+123 / −10）。

### 4.1 缺陷一：LIM-01 存在无条件 PASS（已修复）

**实际代码（修复前，第 1172–1175 行）**：

```python
r_t = invoke(command, envelope, timeout=0.001, max_bytes=max_bytes)
report.add('LIM-01', '极小超时下不会挂起（超时即阻断）',
           'PASS' if r_t['exceeded'] in ('TIMEOUT', None) else 'PASS',
           ...)
```

三元表达式**两个分支同为字面量 `'PASS'`**，恒为 PASS。

**实测证伪（本轮）**：把一个"超时后从未被终止"的结果喂给旧表达式：

```
OLD expression on a failed result -> PASS     <-- 无法失败
NEW judge_timeout on same failure -> ok=False status=timeout_not_contained
    超时后 returncode=None 不是被信号终止的负值；终止结果 terminate=None 未完成回收；
    elapsed=120.00s 远超上限 0.001s + 3.0s 余量，超时后进程未被及时终止
```

**修复**：新增 `judge_timeout(result, timeout)`，依据**可核验事实**区分三类结果：

| 判定 | 条件 | 含义 |
|---|---|---|
| `clean_completion` | `exceeded is None` 且 `elapsed <= timeout + 3.0s` | 超时前自行结束，未挂起 |
| `timeout_terminated` | `exceeded == 'TIMEOUT'`、`returncode < 0`（被信号杀死）、`terminate ∈ {terminated, already_gone, terminated+killed}`、`elapsed <= timeout + 3.0s` | 超时触发且进程组**真实终止并回收** |
| `failed` | 其余全部，含 `unreaped` / `kill_failed` / 非 TIMEOUT 的 exceeded / 运行时间超限 | **绝不记为 PASS** |

同时新增 `judge_exit_consistency()`：产出结构化输出却非零退出即不一致。
**注意**：该项**只在未判定为 `timeout_terminated` 时适用** —— 超时终止时负的 `returncode`
正是终止成功所要求的，不存在"成功退出"语义（此边界由测试固定）。

### 4.2 缺陷二：REAL-STATE 未要求成功退出（已修复）

**实测确认（修复前）**：真实场景通过条件为
`structured and schema_ok and ids_ok and traceability_ok and 状态匹配 and 分类匹配`，
**不含 `returncode == 0`**。因此"输出合法 JSON + 状态正确 + 以 1 退出"会被判 PASS。

**修复**：把 `returncode == 0` 纳入真实场景通过条件（`row['returncode_ok']`），
并写入 `REAL-STATE-*` 的 detail 与报告字段。

**保留安全语义（未破坏）**：`UNKNOWN` / `ERROR` / `BLOCK_RECOMMENDED` 仍是**合法安全阻断** ——
只要结构合法且 `rc == 0` 即通过，**不因"不是 ALLOW"而被判 Schema 失败**。
真实模块不是"输出结构化结果"的失败关闭（例如输入非法 -> `rc=2` 且无 stdout）不在此项判负。

**反例实测（本轮）**：构造"输出完全合法 JSON + 状态正确 + `exit(1)`"的模块：

```
REAL-STATE-UNKNOWN : actual_state=UNKNOWN (正确)  schema_ok=True  (合法)
                     returncode=1  returncode_ok=False  passed=False
                     -> [FAIL]；计数 39 PASS / 9 FAIL；门槛 False
```

### 4.3 未修改的内容（边界遵守）

- **未修改** Gateway 权威 TaskPolicy 准入语义（`config/task_policy.yaml` 无 diff）
- **未修改** DDS 最小权限规则（`security/policies/minimal_permissions.xml` 无 diff）
- **未修改** 任何公共 Schema 语义（4 个 Schema 文件无 diff）
- **未修改** `scripts/team_demo.py` 的执行边界
- **未把** DDS-Security 从 Enforce 降为 Permissive
- **未重构** M2/M3 算法，**未重训** M1

### 4.4 新增测试与 fixture

| 文件 | 内容 |
|---|---|
| `tests/unit/test_member_module_strictness.py` | **新增 345 行 / 27 测试**：`judge_timeout` 判定表（含穷举证明非恒真）、真实挂起子进程、真实快速子进程、故障注入使 LIM-01 真判 FAIL、`judge_exit_consistency` 规则、非零退出端到端反例、零退出正例对照、阻断状态仍通过 |
| `tests/fixtures/faulty_modules/quick_ok.py` | 新增 `clean_completion` 正例 fixture（原先测试靠 skip 掩盖缺失，已移除 skip） |

---

## 5. 本轮测试命令、环境、返回码与结果

### 5.1 运行环境（实测）

```
宿主    : Linux 6.18.54.1-microsoft-standard-WSL2 x86_64
容器    : rg_jazzy (ros:jazzy) / Ubuntu 24.04.5 LTS / ROS_DISTRO=jazzy
RMW     : rmw_fastrtps_cpp       Domain: 42（普通）/ 43（Enforce）
容器内  : ros2=/opt/ros/jazzy/bin/ros2  colcon=/usr/bin/colcon
          jsonschema 4.10.3（Draft 2020-12 可用）  PyYAML ok
宿主机  : Python 3.10.12（.research-venv: pytest 9.1.1, jsonschema 4.26.0）
          宿主系统 python3 仅 jsonschema 3.2.0（不足 —— 见 §11 风险 R-3）
```

### 5.2 命令与结果

| # | 命令 | 返回码 | 结果 |
|---|---|---|---|
| 1 | `bash scripts/container_up.sh` | 0 | 复用既有容器，配置核验通过（挂载/工作目录/镜像/RMW/Domain） |
| 2 | `bash scripts/check_deps.sh` | 0 | `jsonschema=4.10.3 draft2020-12=yes format-checker=active` |
| 3 | `bash scripts/build.sh` | 0 | 4 包构建成功（加 `user/COLCON_IGNORE` 后） |
| 4 | `ros2 pkg list \| grep ^rg_`（容器内） | 0 | `rg_demo_nodes` `rg_gateway` `rg_interfaces` `rg_policy` |
| 5 | `ros2 interface show rg_interfaces/action/PatrolNavigate` | 0 | 字段正确（request_id/task_id/target） |
| 6 | `bash scripts/run_demo.sh`（修复前） | 0 | **DEMO RESULT: PASS (8 passed, 0 failed)** |
| 7 | `bash scripts/run_demo.sh`（修复后复跑） | 0 | **DEMO RESULT: PASS (8 passed, 0 failed)** |
| 8 | `python3 tests/integration/sros2_check.py --run-id preflight20261016` | 0 | **SROS2 SUMMARY 7 passed / 7 total** |
| 9 | `check_member_module.py --module identity_trust … --real-fixture` | 0 | 45 PASS / 门槛 True |
| 10 | `check_member_module.py --module task_risk … --real-fixture` | 0 | 45 PASS / 门槛 True |
| 11 | `pytest tests/unit -q` | 0 | **575 passed, 3 skipped**（7:57） |
| 12 | `pytest tests/unit/test_member_module_strictness.py -q` | 0 | **27 passed**（无 skip） |
| 13 | 受影响的 limits/four_state/acceptance/contract/member3_real 回归 | 0 | **89 passed** |
| 14 | F0 链路（容器内，M3 EXTERNAL + M1/M2 MOCK，合法输入） | 0 | `READY_FOR_GATEWAY_SUBMISSION` |
| 15 | F0 链路（同上，越界目标） | 10 | `ADAPTER_BLOCK` / `ADAPTER_MODULE_STATUS_NOT_PROCEED` |

`3 skipped` 为仓库既有跳过项（**跳过不计入通过**）。修复前全仓基线为 548 passed（10-15 记录）；
本轮 +27 为新增严谨性测试。

---

## 6. 基础 A/B 演示记录（阶段四）

**执行**：`bash scripts/run_demo.sh`（内部委托 `scripts/demo_live.sh`），本轮**两次**执行（验收器修复前 / 修复后），均 PASS。

**场景 A（合法任务）**：`task_id=patrol_a_001`，`frame=map`，目标 `(1.5, 1.5)`

- Planner 向 `/rg/guarded_navigate` 提交；`PLANNER_RESULT.success=true`，`status_code=EXECUTED`
- Gateway 权威决策 `ALLOW` / `ALLOW_IN_POLICY`
- NavigationSim journal **新增 1 条 Goal**（`request_id=demo-a-0001`）
- 审计：`RosCommEvent` → `DecisionEvent(ALLOW)` → `ExecutionEvent(EXECUTED)` 同一 `event_id` 可关联

**场景 B（非法任务）**：同任务，目标 `(9.0, 9.0)` 越界

- Gateway 明确业务拒绝 `BLOCK` / `OUT_OF_REGION`
- NavigationSim **新增 0 条 Goal**；`demo-b-0002` **未出现在 journal**
- 日志存在 1 条可关联 `REJECTED` 行
- **无 ExecutionEvent**，未通过任何通道直达 `/rg/nav_execute`

**8 项断言全部 PASS**：

```
[PASS] NavigationSim received exactly 1 Goal (A only) -- journal lines=1
[PASS] the received Goal is the A-zone request_id -- request_ids=['demo-a-0001']
[PASS] B-zone request_id never reached the executor -- B request_id=demo-b-0002
[PASS] DecisionEvent sequence is ALLOW then BLOCK -- [('ALLOW','ALLOW_IN_POLICY'),('BLOCK','OUT_OF_REGION')]
[PASS] exactly 1 ExecutionEvent (only the forwarded A request) -- executions=['EXECUTED']
[PASS] BLOCK produced no ExecutionEvent for the B event_id -- no shared event_id
[PASS] exactly 1 correlatable REJECTED log line -- reject lines=1
[PASS] policy_version is recorded on every decision -- ['1.0','1.0']
```

**证据**：`artifacts/demo-2026-10-19/preflight-20261016/gateway-ab/`（修复前）与
`…/gateway-ab-postfix/`（修复后）；全部文件 SHA-256 见 `…/preflight-20261016/SHA256SUMS.txt`。

> **重要边界**：`run_demo.sh` 成功**不代表** DDS-Security Enforce 成功。两者已**分开验收**（见 §7）。

---

## 7. DDS-Security Enforce 验收记录（阶段五）

### 7.1 执行前安全检查（未盲目重生成 keystore）

`scripts/setup_sros2.sh` 在 `public/ca.cert.pem` 缺失时会执行 `rm -rf <keystore>` 并重建。
**实测确认**：`security/keystore/public/ca.cert.pem` **存在**，keystore 完整（28 个文件，
含 6 个 enclave 的 `cert.pem`/`key.pem`/`permissions.xml`/`permissions.p7s` + `governance.xml`），
因此走**复用路径**，**未触发任何删除或重建**。

### 7.2 生成配置核验

`python3 scripts/verify_sros2_permissions.py --keystore security/keystore --policy security/policies/minimal_permissions.xml --domain 43` → **PERMISSIONS VERIFY: PASS**

| Enclave | node | 授权 topic | domain |
|---|---|---|---|
| `/operator` | `operator_node` | 18 | [43] |
| `/planner` | `planner_node` | 25 | [43] |
| `/gateway` | `security_gateway` | 35 | [43] |
| `/navsim` | `navigation_sim` | 25 | [43] |
| `/unauthorized` | `rogue_client` | 17 | [43] |

**独立复核（本轮实跑）**：

- `governance.xml` 域 = **43** ✅
- **通配符授权：全部为 NONE**（无 `rt/*`、`rq/*Request`、`rr/*Reply`）✅
- 每个 enclave 的 `<default>` 均为 **DENY** ✅
- 业务 Action 授权（最小权限成立）：

| Enclave | `/rg/guarded_navigate` | `/rg/nav_execute` |
|---|---|---|
| `/planner` | **8** | **0** |
| `/gateway` | 8 | **8** |
| `/navsim` | 0 | 8 |
| `/unauthorized` | **0** | **0** |
| `/operator` | 0 | 0 |

即：`/planner` 只能发起 guarded Action、**不能**直达执行端；`/unauthorized` **两者皆无**。**未修改策略语义**。

### 7.3 真实权限对照实验

`tests/integration/sros2_check.py`（Enforce = Domain **43**，普通 = **42**，每角色独立 Enclave）
→ **SROS2 SUMMARY (7 passed / 7 total)**

| 场景 | 模式 | Enclave | 资源 | Goals | 结果 |
|---|---|---|---|---|---|
| S1 | disabled | — | — | 1 | PASS（普通模式对照） |
| S2 | enforce | `/planner` | `/rg/guarded_navigate` | 1 | PASS `ALLOW_IN_POLICY` |
| S5 | enforce | `/planner` | `/rg/guarded_navigate` | 0 | PASS `OUT_OF_REGION`（业务拒绝） |
| **S3C** | enforce | `/gateway` | `/rg/nav_execute` | 1 | PASS **正向对照成功** |
| **S3** | enforce | `/planner` | `/rg/nav_execute` | 0 | PASS `ACTION_CLIENT_CREATION_DENIED` |
| **S4** | enforce | `/unauthorized` | `/rg/nav_execute` | 0 | PASS `ACTION_CLIENT_CREATION_DENIED` |
| S6 | enforce | bad-keystore | `/rg/nav_execute` | 0 | PASS（**未静默回退**为无认证通信） |

**原生拒绝证据（本轮新生成，非历史归档）** —— 用 M2 的规范化解析器实测：

```
S3: rogue_planner.log      ansi=True  native_denial_records=2
    line 1: [SECURITY Error] rr/rg/nav_execute/_action/send_goalReply topic not found in allow rule
S4: rogue_unauthorized.log ansi=True  native_denial_records=2
    line 1: [SECURITY Error] rr/rg/nav_execute/_action/send_goalReply topic not found in allow rule
```

**结论**：拒绝证据是 **Fast DDS 原生 `not found in allow rule` 报错**，
**不是**客户端超时；且 S3C 在同一时间窗口提供正向对照，因此"拒绝来自 DDS 权限"成立。
**未通过关闭安全机制获取 PASS**；**未将 Enforce 降为 Permissive**。

### 7.4 未越界确认

- S3/S4 越权尝试的下游 Goal 数均为 **0**：**越界请求未创建下游 Goal**。
- Enforce 域 43 与普通域 42 隔离；执行前已确认容器内无其他运行实例（`ros2 node list` 为空、无 `rg_*` 进程）。

**证据**：`artifacts/demo-2026-10-19/preflight-20261016/sros2-enforce/`（18 文件 + `summary.json` + sha256 清单）。

---

## 8. M2/M3 离线回归结果（阶段六）

### 8.1 本轮重新执行（非引用历史）

| 模块 | 命令 | counts | 门槛 |
|---|---|---|---|
| M2 `identity_trust` | `check_member_module.py --config config/team_modules.member2.real.yaml --real-fixture config/acceptance/real_scenarios.member2.yaml` | 45 PASS / 3 FAIL / 1 NOT_RUN / 1 BLOCKED | **True** |
| M3 `task_risk` | 同上（member3 配置） | 45 PASS / 3 FAIL / 1 NOT_RUN / 1 BLOCKED | **True** |

四场景真实状态（`rc=0`、`schema_ok=True`、`traceability_ok=True`、`passed=True`）：

- **M2**：`s2-authorized`→`AUTHORIZED`；`s3c-positive-control`→`UNKNOWN`；
  `s3-native-denial`→`UNKNOWN`；`s4-native-denial`→`UNKNOWN`
- **M3**：`allow`→`ALLOW_RECOMMENDED`；`block`→`BLOCK_RECOMMENDED`；
  `unknown`→`UNKNOWN`；`error`→`ERROR`

`LIM-01` 判定均为 `timeout_terminated`（真判据生效）。

### 8.2 M2 专项确认（全部满足）

- ✅ S3/S4 的 **ANSI 日志可识别**（`ansi=True`，非历史归档，本轮新日志）
- ✅ **原生 DDS 拒绝证据保留**（`denial_topic=rr/rg/nav_execute/_action/send_goalReply`，`line=1`，正向对照 1 项）
- ✅ **历史 `/rg/nav_execute` 拒绝不迁移**为当前 `/rg/guarded_navigate` 请求的 `DENIED`
  （`current_request_binding=HISTORICAL_RESOURCE_MISMATCH`）
- ✅ **资源不匹配时结果为 `UNKNOWN`**
- ✅ **S2 的 `AUTHORIZED` 仅表示历史实验成功**（`historical_only=true`，从不填 `authenticated_identity`）
- ✅ `historical_only` **未消失**（`extensions.historical_only=true`，四场景均存在）

### 8.3 M3 专项确认（全部满足）

- ✅ 合法策略 → `ALLOW_RECOMMENDED`
- ✅ 越界条件 → `BLOCK_RECOMMENDED`
- ✅ 缺失策略 → `UNKNOWN`
- ✅ 损坏策略 → `ERROR`
- ✅ **F0 对后三类均失败关闭**（`REAL-ADP-{BLOCK,UNKNOWN,ERROR}` → `ADAPTER_BLOCK`，退出码 ≠ 0）
- ✅ **M3 模块未获得 Gateway 最终授权权力**：合法条件仅产出 `READY_FOR_GATEWAY_SUBMISSION`
  （`gateway_decision is None`、`navsim_goal_id is None`）

### 8.4 关于报告中的 `3 FAIL`（勿误读）

三项为 `STATE-BLOCK/UNKNOWN/ERROR` —— 把 Mock 场景开关套用到**不解析该开关的真实模块**。
它们**如实保留并显示 FAIL**，但标记 `gate=False`、`applicability=NOT_APPLICABLE_REAL_MODULE`，
门槛由 `REAL-STATE-*` 承担。**未删除检查项、未修改期望状态、未降低门槛**。

### 8.5 证据归档原则

- **未覆盖** `artifacts/acceptance/exports/`（`git status` 对该路径为空，历史记录零改动）。
- 本轮证据写入**新目录** `artifacts/demo-2026-10-19/preflight-20261016/`，**未**把旧日志复制冒充新结果。
- 历史 SROS 2 证据（`20261009T093144Z`）与本轮证据（`preflight20261016`）**时间戳与 SHA 均不同**，可区分。

---

## 9. 尚未完成的任务

| # | 事项 | 原因 |
|---|---|---|
| 1 | **在线模式实跑**（`team_demo.py --online` 真正提交到 `/rg/guarded_navigate`） | 属 10-17 任务；本轮仅离线打通链路并保留在线开关未启用 |
| 2 | PR #6 / #7 目标分支调整 | 无 GitHub 写 API 凭据；且未获成员四授权（方案见 §3.2） |
| 3 | PR 合并 | 任务书明确禁止未审查合并 |
| 4 | M1 真实模块接入（三模块全真实联合） | 超出本轮范围（本轮配置中 M1/M2 为显式 MOCK） |
| 5 | M2 对候选入口的正面结论 | 现有受控实验只覆盖 `/rg/nav_execute`；需**新增针对 `/rg/guarded_navigate` 的受控实验** |
| 6 | M3 实时监测 / 动态状态机 | 交付方自述 `runtime_monitor=NOT_READY`、`dynamic_state_model=NOT_INTEGRATED` |

---

## 10. 10 月 17 日联调启动条件

### 10.1 可实际启动的环境（实测）

**可以**。`rg_jazzy` 容器（`ros:jazzy`，Ubuntu 24.04.5，ROS 2 Jazzy，`rmw_fastrtps_cpp`）
已运行且配置核验通过；`/opt/ros/jazzy/setup.bash` 存在；4 个 ROS 2 包已构建并可在容器内
`source install/setup.bash` 后正常加载；`jsonschema 4.10.3` 满足 Draft 2020-12。

### 10.2 离线链路已打通（本轮实测，容器内）

```
M3(EXTERNAL) + M1/M2(MOCK)
   → ModuleInputEnvelope(docs/interfaces/examples/module_input_valid.json)
   → scripts/team_demo.py  (--online 未启用)
   → F0 decision = READY_FOR_GATEWAY_SUBMISSION   [合法输入, exit 0]
   → F0 decision = ADAPTER_BLOCK / ADAPTER_MODULE_STATUS_NOT_PROCEED  [越界输入, exit 10]

M3(EXTERNAL) + M1/M2(MOCK) 同配置下 Gateway/NavigationSim 独立复验：
   → Gateway ALLOW → NavigationSim +1 Goal   [场景 A, 8/8 断言 PASS]
   → Gateway BLOCK → NavigationSim +0 Goal   [场景 B]
```

### 10.3 次日可直接验证的内容

- **可立即执行**：`--online` 真实提交（`planner_command: [ros2, run, rg_demo_nodes, planner_node]`，
  已配置且存在于仓库），叠加本轮已验证的 Gateway/NavigationSim 与 Enforce 基底。
- **需准备/确认**：
  1. 运行前确认 Domain 42 无其他成员实例（本轮已验证为空闲，`ros2 node list` 空）。
  2. 若需在 **Enforce（43）** 下联调，须以对应 Enclave 启动各节点，并保留正向对照。
  3. 记录路径建议沿用 `logs/demo/` + 新 run-id 目录；**不要**覆盖 `tests/evidence/preflight20261016`。
  4. 明确 `READY_FOR_GATEWAY_SUBMISSION ≠ Gateway ALLOW`，`Gateway ALLOW ≠ NavigationSim 执行成功`。

### 10.4 关于该配置的边界（必须写清）

该链路是 **`M3(EXTERNAL) + M1/M2(显式 MOCK)`**，**不属于三模块全真实联合系统**。
未来若接入 **M2 历史证据解释器**，必须明确：其 `AUTHORIZED` **不构成当前请求已通过 DDS 认证的证明**。

---

## 11. 风险、阻断项及建议

| ID | 风险 / 阻断 | 影响 | 建议 |
|---|---|---|---|
| **R-1** | **PR #7 完整包含 PR #6**（stacked），两者 base 都是 `main` | 合并顺序错误会产生空 diff 或重复 | 按 §3.2 顺序：先 PR #6 → `baseline`，再 PR #7 → `chore/member-deliveries`，最后 PR #7 → `baseline` |
| **R-2** | PR #7 `mergeable_state = unstable` | CI 有 4 项 success，unstable 可能来自非必需检查 | 合并前复核 CI 全绿 |
| **R-3** | **宿主机系统 `python3` 仅 jsonschema 3.2.0**（真实模块需 ≥4） | 直接在宿主机跑 `scripts/team_demo.py` 会以 `ADAPTER_MODULE_EXIT_NONZERO` 失败（本轮已实测） | 在容器内运行 F0/联调（容器 `python3` 为 4.10.3），或在配置中显式使用带依赖的解释器 |
| **R-4** | `user/` 交付归档含同名 ROS 包 | 无 `COLCON_IGNORE` 时 `colcon build` 失败 | 已加标记；勿删除该标记，勿把归档移入 `src/` |
| **R-5** | 验收器 `STATE-*` 对真实模块仍显示 3 个 FAIL | 易被误读为模块缺陷 | 保留为"不适用"证据；评审时以 `REAL-STATE-*` 为门槛 |
| **R-6** | `event_id` 契约张力：`ID-03` 要求含完整 `request_id`，Schema 限 ≤128 字符 | `request_id` > 80 字符时两者无法同时成立 | 需成员四裁定（沿用 10-15 报告 R-1） |
| **R-7** | M2 对当前候选入口恒为 `UNKNOWN`（资源不匹配） | 不会给出正面授权结论（符合安全要求） | 如需正面结论，须新增针对 `/rg/guarded_navigate` 的受控实验 |
| **R-8** | 本轮未执行 `--online` | 尚无真实 Gateway 决策 + Goal 的**在线提交**证据 | 10-17 执行并留证 |

**无 C 类（BLOCKED）阻断**：未出现越界请求创建下游 Goal、DDS 权限意外宽松、
正向对照或原生拒绝证据不成立、容器/包/权限无法恢复、关键测试失败原因不明等情形。

---

## 12. 最终状态

# `READY_FOR_M3_L3`

| 完成判据（A 类） | 实测结果 |
|---|---|
| 演示候选分支清晰 | ✅ `demo/2026-10-19-rc` = `92e884fb42a7d68a239b9c33891e26c12b8749b8`（独立 worktree） |
| 必要代码整改完成 | ✅ LIM-01 + REAL-STATE 两处修复，均有反例测试（27 项） |
| ROS 2 Jazzy 环境可运行 | ✅ 容器复用核验通过、4 包构建、Action 类型正确 |
| 基础 A/B 演示通过 | ✅ 8 passed / 0 failed（修复后复跑一致） |
| DDS-Security Enforce 对照通过 | ✅ 7 passed / 7 total（域 43，含原生拒绝 + 正向对照） |
| 必需测试通过 | ✅ 全仓 **575 passed, 3 skipped** |
| 有完整日志和 SHA 记录 | ✅ `artifacts/demo-2026-10-19/preflight-20261016/` + sha256 清单 |

**此状态表示准备进入 10 月 17 日真实联调，不表示最终演示版已完成。**
距 10-19 正式可演示版本仍需：在线联调证据（真实 Gateway 决策 + NavigationSim Goal）、
PR #6/#7 合流、以及 R-6/R-7 的裁定。

---

## 附 A：记录未完成/受限事项时的诚实口径

- 本轮**未**执行在线提交，报告未将其写作通过。
- 本轮**未**修改 PR 目标分支，报告未声称已调整。
- 本轮**未**合并任何 PR。
- 本轮**未**使用历史验收报告替代本轮测试；所有 PASS 均可追溯到本轮 run-id
  （`preflight20261016` / `run_demo`）与 SHA-256。
- 本轮**未**修改 `artifacts/acceptance/exports/`。

## 附 B：证据索引

| 内容 | 路径 |
|---|---|
| 本轮证据根目录 | `artifacts/demo-2026-10-19/preflight-20261016/` |
| Gateway A/B（修复前 / 修复后） | `…/gateway-ab/`、`…/gateway-ab-postfix/` |
| SROS 2 Enforce S1–S6 | `…/sros2-enforce/`（18 文件，含 `summary.json`） |
| F0/M3 链路 | `…/f0-m3-chain/`（`f0_allow.json`、`f0_block.json`、adapter JSONL） |
| 验收器严谨性反例 | `…/verifier-strictness/`（非零退出模块 + 配置 + 报告） |
| 证据总清单 | `artifacts/demo-2026-10-19/preflight-20261016/SHA256SUMS.txt`（40 项，`sha256sum -c` 全通过；清单自身不自哈希） |
| 历史 SROS 2 证据（只读，未改动） | `artifacts/acceptance/exports/m2_sros2_enforce/logs/tests_evidence/20261009T093144Z/` |
| 本轮 SROS 2 原始证据（工作区） | `tests/evidence/preflight20261016/` |
