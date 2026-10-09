# RoboGuard 最小 ROS 2 业务基底（阶段一 / 二 / 三 落地）

依据《ROS 2 基底系统工程搭建与集成方案 v1.2》（阶段一、二、三）实现的一个**最小、
可运行、可验证**的 ROS 2 机器人业务基底。

核心链路（真实 ROS 2 Action，不是函数调用）：

```
operator_node ──/rg/task_info (std_msgs/String, 仅通告)──▶ (Planner 参考；Gateway 不订阅)
planner_node ──/rg/guarded_navigate (Action Goal)──▶ security_gateway
                                     Gateway: 只读加载 config/task_policy.yaml → 同步判定
                                       ├─ BLOCK: 直接拒绝, 不创建下游 Goal, 只写审计
                                       └─ ALLOW: 转发到 /rg/nav_execute
                                                        │
                                                  navigation_sim (仅记录坐标, 不做路径规划)
                                                        │
                          ExecutionEvent ◀──────────────┴──▶ Result 回传 planner
```

**完成判据（阶段三）**：A 区 ALLOW → 下游收到 **1** 条 Goal；B 区 BLOCK → 下游收到
**0** 条 Goal；两条链路均可由 `request_id` / `event_id` 追溯。**已实测通过**
（见下方「验证结果」）。

---

## 0. 环境前提（重要，先读）

| 项目 | 实测 | 说明 |
| --- | --- | --- |
| 宿主机 | **Ubuntu 22.04.5 LTS (WSL2)** | `ros2` / `colcon` **均未安装**，`/opt/ros` 不存在 |
| ROS 2 运行环境 | **Docker `ros:jazzy` 容器** | 容器内为真正的 Ubuntu 24.04.5 + ROS 2 Jazzy |

方案要求 Ubuntu 24.04 + Jazzy；Jazzy 的 deb 只发布给 noble(24.04)，**无法在 22.04 上
apt 安装**。经确认，ROS 2 全部放在 `ros:jazzy` 容器中，宿主机不改动，工作区
`/home/zhangwei/project/RosSystem` bind mount 到容器 `/ws`。

完整环境数值见 [`environment.md`](environment.md)；依赖见
[`requirements.md`](requirements.md)。**容器内不需要额外 apt 安装任何包。**

---

## 1. 目录树（交付物）

```
/home/zhangwei/project/RosSystem/          ← ROS 2 工作区根（容器内 /ws）
├── README.md                              本文档
├── environment.md                         阶段一环境核查实测记录
├── requirements.md / requirements.txt      依赖说明
├── ACCEPTANCE.md                          阶段五验收表（PASS/FAIL + 证据路径）
├── pytest.ini
├── .gitignore                             排除 build/install/log/logs/evidence 与密钥
│
├── config/
│   ├── task_policy.yaml                   ★权威任务策略（唯一授权来源，只读加载）
│   └── scenarios/                          负例场景策略夹具
│       ├── task_policy_task_b.yaml         不同 task_id  → TASK_MISMATCH
│       ├── task_policy_inactive.yaml       active: false → POLICY_MISSING
│       ├── task_policy_low_rate.yaml       max 2/min     → RATE_LIMIT
│       ├── task_policy_missing_field.yaml  缺字段        → POLICY_MISSING
│       └── task_policy_nonfinite_region.yaml  x_max=NaN → POLICY_MISSING
│
├── security/
│   └── README.md                          ★SROS 2 预留位（**未启用**，无任何密钥）
│
├── src/
│   ├── rg_interfaces/                     ament_cmake：Action 契约
│   │   ├── action/PatrolNavigate.action   ★冻结的 Action 定义
│   │   ├── CMakeLists.txt / package.xml
│   │   ├── rg_policy/                     ament_python：**不 import rclpy** 的纯逻辑核心
│   │   │   ├── reason_codes.py            冻结原因码/状态码词表
│   │   │   ├── task_policy.py             权威策略加载 + schema 校验 + mtime 热重载
│   │   │   ├── policy_engine.py           ★纯函数 evaluate(request, policy)
│   │   │   ├── request_tracker.py         重复 request_id / 频率上限（注入时钟）
│   │   │   ├── events.py                  RosComm/Decision/Execution 事件 + JSONL sink
│   │   │   └── futures.py                 带超时的 future 等待（共享）
│   │   ├── rg_gateway/                    ament_python
│   │   │   └── rg_gateway/security_gateway.py   ★准入控制网关
│   │   └── rg_demo_nodes/                 ament_python
│   │       ├── rg_demo_nodes/operator_node.py   /rg/task_info 发布者
│   │       ├── rg_demo_nodes/planner_node.py    /rg/guarded_navigate 客户端（唯一出口）
│   │       ├── rg_demo_nodes/navigation_sim.py  /rg/nav_execute 服务端（只记录坐标）
│   │       └── launch/{demo,stack}.launch.py
│
├── tests/
│   ├── unit/                              pytest 单元测试（140 项）
│   │   ├── conftest.py
│   │   ├── test_task_policy_loader.py
│   │   ├── test_policy_engine.py
│   │   ├── test_request_tracker.py
│   │   ├── test_events.py
│   │   └── test_interface_contract.py
│   ├── integration/scenario_runner.py     ★A/B + 负例联调断言器
│   └── evidence/<run-id>/                 运行时证据（gitignore）
│
├── scripts/
│   ├── lib.sh                             宿主/容器双模式公共函数
│   ├── container_up.sh                    创建/启动 ros:jazzy 容器（幂等）
│   ├── build.sh                           colcon build
│   ├── run_unit_tests.sh                  pytest
│   ├── run_demo.sh  + demo_live.sh        现场演示（含 /rg/task_info 实况）
│   ├── run_ab_scenarios.sh                A/B 联调（要求 11）
│   ├── run_negative_scenarios.sh          负例联调（要求 12）
│   ├── run_all.sh                         全量验证一键跑
│   └── shell.sh                           进入已 source 的交互 shell
│
├── logs/                                  脚本输出日志（gitignore）
└── docs/plan_v1.2.extracted.txt           方案原文抽取文本（便于逐条对照）
```

包数量：**4 个**（`rg_interfaces` / `rg_policy` / `rg_gateway` / `rg_demo_nodes`）。
拆出 `rg_policy` 的判断依据：安全相关逻辑必须能**脱离 ROS 图**被穷举测试，且必须
集中（接口集中、可测）。`rg_policy` 全程不 import `rclpy`，由单元测试强制保证。

---

## 2. 核心接口（冻结契约）

### 2.1 Action：`rg_interfaces/action/PatrolNavigate.action`

```
# Goal：业务请求，不依赖客户端自报身份
string request_id
string task_id
geometry_msgs/PoseStamped target
---
# Result：已接受并执行后的业务结果
bool success
string status_code
string detail
---
# Feedback：最小进度反馈
float32 progress
string phase
```

### 2.2 ROS 资源名（方案v1.2 §2.1，冻结）

| 资源 | 类型 | 角色 |
| --- | --- | --- |
| `/rg/task_info` | `std_msgs/msg/String` (JSON) | Publisher: `operator_node`；**仅通告，非授权来源** |
| `/rg/guarded_navigate` | Action `PatrolNavigate` | **Server**: `security_gateway`；**Client**: `planner_node` |
| `/rg/nav_execute` | Action `PatrolNavigate` | **Server**: `navigation_sim`；**Client**: `security_gateway` |

`planner_node` 的出口 Action 名是**模块常量**（`GUARDED_NAVIGATE_ACTION`），
不可通过参数改写 —— 单元测试 `test_planner_egress_is_not_configurable` 强制这一点。

### 2.3 权威策略 `config/task_policy.yaml`

```yaml
task_id: patrol_a_001
policy_version: "1.0"
active: true
coordinate_frame: map
allowed_region: {x_min: 0.0, x_max: 4.0, y_min: 0.0, y_max: 4.0}
max_requests_per_minute: 10
```

* 6 个字段**全部必填**，缺任一 → `PolicySchemaError` → 拒绝（**绝不静默默认**）。
* 数值必须**有限**（NaN/Inf 一律拒绝）；`x_min ≤ x_max`、`y_min ≤ y_max`、速率 > 0。
* 只用只读方式打开；按 `(mtime_ns, size)` 热重载，**策略消失即刻 fail closed**。
* `/rg/task_info` **不能**覆盖权威策略：Gateway 根本不订阅该 Topic，且 `operator_node`
  发布的摘要里**不含** `allowed_region`。

### 2.4 事件契约（方案v1.2 §2.3）

三条事件共用同一个 `event_id`，且都带 `request_id` / `task_id`，输出为 JSONL：

| 事件 | 字段 | 产生时机 |
| --- | --- | --- |
| `RosCommEvent` | `event_id, request_id, task_id, observed_via, resource, frame_id, x, y, z, target_finite, received_at` | Gateway 收到 Goal 后**立即** |
| `DecisionEvent` | `event_id, request_id, task_id, policy_version, decision, reason_code, detail, decision_at` | 同步判定完成 |
| `ExecutionEvent` | `event_id, request_id, task_id, downstream_goal_id, success, status_code, detail, finished_at` | 转发后拿到执行结果（或超时） |

* 事件字段**没有构造默认值**；"无值"必须显式传 `UNKNOWN` / `NONE` 标记。
* 非有限目标值**不被静默清洗**：写成 `"NaN"/"Infinity"/"-Infinity"` 字符串并置
  `target_finite: false`，保证 JSONL 仍是严格合法 JSON。
* 被拒绝的 Goal **不会**产生 `ExecutionEvent`（由断言强制）。

### 2.5 原因码（方案v1.2 §2.3 冻结 8 个）

`ALLOW_IN_POLICY`、`TASK_MISMATCH`、`INVALID_TARGET`、`OUT_OF_REGION`、
`POLICY_MISSING`、`DUPLICATE_REQUEST`、`RATE_LIMIT`、`EXECUTION_TIMEOUT`

执行阶段另有状态码（写入 `ExecutionEvent.status_code`）：
`EXECUTED`、`EXECUTION_FAILED`、`EXECUTION_TIMEOUT`、`DOWNSTREAM_REJECTED`。

> **唯一一处词表扩展（已显式标注）**：`AUDIT_UNAVAILABLE`。方案 §2.3 要求
> "审计服务失效不能绕过准入判断"，但 8 个冻结码没有一个能如实描述该原因；
> 用 `POLICY_MISSING`/`INVALID_TARGET` 顶替会污染审计。因此新增 1 个码，并**放在
> 单独的元组** `ACCEPTED_DECISION_REASON_CODES` 中，冻结的
> `DECISION_REASON_CODES` 保持 8 项不变（单元测试强制）。正常运行不会触发它。

### 2.6 判定顺序（首个失败规则生效，文档化）

1. 策略缺失 / `active: false` → `POLICY_MISSING`
2. `request_id` 为空 → `INVALID_TARGET`
3. `task_id` 为空或不等于策略 `task_id` → `TASK_MISMATCH`
4. `frame_id` 为空或不等于策略 `coordinate_frame` → `INVALID_TARGET`
5. `x/y/z` 非有限数 → `INVALID_TARGET`
6. 目标越出 `allowed_region`（闭区间）→ `OUT_OF_REGION`
7. 重复 `request_id`（收到即登记）→ `DUPLICATE_REQUEST`
8. 超出 `max_requests_per_minute`（滑动 60s）→ `RATE_LIMIT`
9. 否则 → `ALLOW_IN_POLICY`

`policy_engine.evaluate(request, policy)` 是**纯函数**（无时钟、无 IO、无状态），
重复/频率这两条与时间相关的规则由 `RequestTracker` 承担，Gateway 按上表顺序组合。

---

## 3. 全部构建与启动命令

所有命令都在**工作区根目录**执行；脚本会自动选择「容器模式」或「原生模式」。

### 3.1 一键（推荐）

```bash
cd /home/zhangwei/project/RosSystem
scripts/container_up.sh     # 幂等：docker pull ros:jazzy + 创建/启动 rg_jazzy
scripts/run_all.sh          # build → 单元测试 → A/B → 负例，并打印 PASS/FAIL 汇总
```

### 3.2 分步

```bash
scripts/build.sh                # colcon build，日志 logs/build.log
scripts/run_unit_tests.sh       # pytest tests/unit，日志 logs/unit_tests.log
scripts/run_ab_scenarios.sh     # A 区 / B 区，日志 logs/scenarios_ab.log
scripts/run_negative_scenarios.sh  # 12 个负例，日志 logs/scenarios_negative.log
scripts/run_demo.sh             # 现场演示 A/B + /rg/task_info，日志 logs/demo.log
scripts/shell.sh                # 进入已 source 的交互 shell
```

### 3.3 容器内手工执行（等价，用于排障）

```bash
docker exec -it rg_jazzy bash -lc '
  source /opt/ros/jazzy/setup.bash
  cd /ws && source install/setup.bash
  colcon build
  ros2 action list -t
'
```

### 3.4 用 launch 文件启动

```bash
# 容器内，已 source ROS + install/setup.bash，且 cwd 为工作区根
ros2 launch rg_demo_nodes stack.launch.py                 # operator + gateway + navsim
ros2 launch rg_demo_nodes demo.launch.py target_x:=1.5 target_y:=1.5   # 再加 planner（A 区）
ros2 launch rg_demo_nodes demo.launch.py target_x:=9.0 target_y:=9.0   # B 区 → BLOCK
```

> 这两条命令**已实测**（见 [`ACCEPTANCE.md`](ACCEPTANCE.md) T7）：
> `stack.launch.py` 三节点就绪、两个 Action 在线、`SIGINT` 干净退出且无残留；
> `demo.launch.py` 四节点走通 A 区闭环（`success=true` / `EXECUTED`，
> NavigationSim journal 恰好 1 行）。
> 注意：`policy_path` / `audit_log_path` / `navsim_record_path` 的默认值基于 **cwd**，
> 不在工作区根启动时请传绝对路径。

### 3.5 手工发一次请求

```bash
ros2 run rg_demo_nodes planner_node --ros-args \
  -p task_id:=patrol_a_001 -p request_id:=manual-1 -p frame_id:=map \
  -p target_x:=1.5 -p target_y:=1.5 -p expect_success:=1
```

`planner_node` 参数：`task_id`、`request_id`(空则自动 uuid)、`frame_id`、`target_x/y/z`、
`server_wait_timeout_sec`、`result_timeout_sec`、`expect_success`(`-1` 仅报告)。
退出码：`0` 符合预期、`1` 与预期不符、`2` 无 Result（服务器不可用/超时）、
`3` Goal 在 Action 层被拒（`GoalRejected`）。

`security_gateway` 参数：`upstream_action`、`downstream_action`、`policy_path`、
`audit_log_path`、`execution_timeout_sec`、`downstream_accept_timeout_sec`、
`server_ready_timeout_sec`、`duplicate_ttl_sec`、`rate_window_sec`、`audit_fsync`。

`navigation_sim` 参数：`record_path`、`simulate_delay_sec`、`simulate_failure`、
`simulate_reject`、`emit_feedback`（后四个是**测试钩子**，默认关闭）。

---

## 4. 验证结果（真实执行，不是观察终端文本）

证据目录：`tests/evidence/20261009T045753Z`（A/B）、`tests/evidence/20261009T045831Z`（负例）。
汇总文件：`summary.json` / `summary.md`（每个 scenario 一份 `scenario_result.json` +
`commands.json`，记录**命令、返回码、耗时、日志路径**）。

### 4.1 总览

| 阶段 | 命令 | 返回码 | 结果 | 日志 |
| --- | --- | --- | --- | --- |
| 构建 | `colcon build` | 0 | **PASS**（4 packages） | `logs/build.log` |
| 单元测试 | `pytest tests/unit` | 0 | **PASS**（140 passed） | `logs/unit_tests.log` |
| A/B 联调 | `scenario_runner.py --suite ab` | 0 | **PASS**（2/2） | `logs/scenarios_ab.log` |
| 负例联调 | `scenario_runner.py --suite negative` | 0 | **PASS**（12/12） | `logs/scenarios_negative.log` |
| 现场演示 | `scripts/run_demo.sh` | 0 | **PASS**（8 checks） | `logs/demo.log` |

### 4.2 A/B 断言（要求 11）

| 场景 | Gateway 判定 | **NavigationSim 收到 Goal 数** | planner Result | REJECTED 日志 | 结果 |
| --- | --- | --- | --- | --- | --- |
| `A_zone_allow`（1.5, 1.5） | `ALLOW` / `ALLOW_IN_POLICY` | **1** | `success=true`, `EXECUTED`, goal_status=SUCCEEDED | 0 | **PASS** |
| `B_zone_block_out_of_region`（9.0, 9.0） | `BLOCK` / `OUT_OF_REGION` | **0** | `success=false`, `OUT_OF_REGION`, goal_status=ABORTED | 1（含 request_id + event_id + `downstream_goal_created: false`） | **PASS** |

计数来自 `navsim_goals.jsonl` 的**行数**（`wc -l` 语义），不是终端文本；
B 场景中 `ExecutionEvent` 数为 **0**。

### 4.3 负例断言（要求 12）

| 场景 | 期望原因码 | NavSim Goal 数 | 结果 |
| --- | --- | --- | --- |
| `policy_file_missing`（策略文件不存在） | `POLICY_MISSING` | 0 | **PASS** |
| `policy_missing_required_field`（缺 `coordinate_frame`） | `POLICY_MISSING` | 0 | **PASS** |
| `policy_nonfinite_region`（`x_max: .nan`） | `POLICY_MISSING` | 0 | **PASS** |
| `policy_inactive`（`active: false`） | `POLICY_MISSING` | 0 | **PASS** |
| `task_id_mismatch_request_side`（请求侧 `patrol_b_042`） | `TASK_MISMATCH` | 0 | **PASS** |
| `task_id_mismatch_policy_side`（策略侧 `patrol_b_999`） | `TASK_MISMATCH` | 0 | **PASS** |
| `frame_id_invalid`（`camera_link` ≠ `map`） | `INVALID_TARGET` | 0 | **PASS** |
| `target_nan`（`target.x = NaN`） | `INVALID_TARGET` | 0 | **PASS** |
| `target_infinite`（`target.y = inf`） | `INVALID_TARGET` | 0 | **PASS** |
| `duplicate_request_id`（同一 id 发两次） | `ALLOW_IN_POLICY` → `DUPLICATE_REQUEST` | 1 | **PASS** |
| `rate_limit`（策略上限 2/min，发 3 条） | `ALLOW`×2 → `RATE_LIMIT` | 2 | **PASS** |
| `execution_timeout`（执行器卡 10s，网关超时 2s） | `ALLOW_IN_POLICY` + `EXECUTION_TIMEOUT` | 1 | **PASS** |

**每一个场景都会额外断言**（实测每场景 13~21 条，14 个场景合计 **215 条全部 PASS**）：
1. `NAVSIM_READY` / `GATEWAY_READY` 出现；
2. planner 退出码符合预期；
3. planner `Result.success` / `status_code` 符合预期；
4. `DecisionEvent` 原因码**序列**完全一致；
5. `ExecutionEvent` 数量一致；
6. `RosCommEvent 数 == DecisionEvent 数 == planner 运行次数`；
7. `event_id` 可追溯：每个 id 恰好 1 个 RosComm + 1 个 Decision + ≤1 个 Execution；
8. **BLOCK 的 `event_id` 绝不出现 `ExecutionEvent`**；
9. `REJECTED` 日志行数一致，且每行都含被拒的 `request_id` 与 `event_id`，并声明
   `downstream_goal_created: false`；
10. NavigationSim 实际收到的 `request_id` 集合 **等于** 被允许的集合（跨场景无串扰）。

### 4.4 现场演示实测输出（节选）

```
/rg/guarded_navigate [rg_interfaces/action/PatrolNavigate]
/rg/nav_execute [rg_interfaces/action/PatrolNavigate]

data: '{"task_id": "patrol_a_001", "policy_version": "1.0", "coordinate_frame": "map", ...

PLANNER_RESULT {... "success": true,  "status_code": "EXECUTED",
                "feedback_seen": {"progress": 0.5, "phase": "DOWNSTREAM:EXECUTING"}}
PLANNER_RESULT {... "success": false, "status_code": "OUT_OF_REGION",
                "goal_status": "STATUS_ABORTED"}

DEMO RESULT: PASS  (8 passed, 0 failed)
```

审计链（同一 `event_id`，A 请求）：

```json
{"event_type":"RosCommEvent","event_id":"de9af9b3…","request_id":"demo-a-0001", …}
{"event_type":"DecisionEvent","event_id":"de9af9b3…","decision":"ALLOW","reason_code":"ALLOW_IN_POLICY","policy_version":"1.0", …}
{"event_type":"ExecutionEvent","event_id":"de9af9b3…","downstream_goal_id":"e1d55593…","success":true,"status_code":"EXECUTED", …}
```

---

## 5. 关键工程决策与死锁分析（要求 8）

### 5.1 为什么同步回调里阻塞等待不会死锁

Gateway 的 `execute_callback` 是**同步函数**，内部会阻塞等待下游 Action 的
Goal 接受与最终 Result。这在 rclpy 7.1.12 (Jazzy) 下**只有**在特定组合里才安全，
本次逐一核对过源码：

| 事实 | 源码位置 |
| --- | --- |
| `MultiThreadedExecutor` 拥有自己的 `ThreadPoolExecutor(num_threads)` | `rclpy/executors.py:983` |
| 每个可等待回调都 `submit` 到该线程池执行 | `rclpy/executors.py:1002` |
| `await_or_execute` 对**同步**回调直接**内联调用**（不是 `run_in_executor`） | `rclpy/executors.py:108,115` |
| ActionServer 的 Goal 通过 `executor.create_task` 派发 | `rclpy/action/server.py:568` |
| `_execute_goal` 里 `await await_or_execute(execute_callback, …)` | `rclpy/action/server.py:360` |

结论：同步 `execute_callback` 跑在线程池的**工作线程**上，阻塞它只占用 1 个 worker。
因此本实现采用：

* `MultiThreadedExecutor(num_threads=4)`；
* Action **Server** 用 `ReentrantCallbackGroup`，Action **Client** 用**另一个**
  `ReentrantCallbackGroup`。

这样 `_on_execute` 阻塞等待 `send_goal_async` / `get_result_async` 时，其余 worker
仍能处理本节点的 ActionClient 响应。**单线程 executor 或共用互斥组会死锁** ——
`EXECUTOR_THREADS >= 2` 由单元测试强制（`test_gateway_action_names_and_defaults`）。

`planner_node` 是纯客户端：`MultiThreadedExecutor(2)` 在后台线程 spin，主线程阻塞
等待有界 future。

### 5.2 全部等待均有超时

`rg_policy/futures.py::wait_for_future` 是唯一的等待原语：`add_done_callback` +
`threading.Event.wait(timeout)`，超时抛 `WaitTimeout`，调用方一律**fail closed**：

* 下游 Goal 接受超时 → `EXECUTION_TIMEOUT`；
* 下游 Result 超时 → `EXECUTION_TIMEOUT` + 尽力 `cancel_goal_async`；
* `wait_for_server` 超时 → planner 退出码 2；Gateway 记录
  `downstream_server_available: false` 但**不**放行绕过。

### 5.3 无故障绕过

* 没有任何环境变量/参数可以跳过判定；
* 策略缺失/非法/未激活 → 拒绝；
* 审计写入失败 → `AUDIT_UNAVAILABLE`，**拒绝**（启动时审计不可写则直接退出码 2，
  拒绝在无审计的情况下运行）。

---

## 6. 已知限制（如实声明）

1. **SROS 2 / DDS-Security 完全未启用。** 没有 keystore、enclave、permissions 或
   任何密钥。因此：
   * 本系统**不提供密码学身份认证**；
   * 本系统**不提供不可绕过的 DDS 资源隔离**——同一 ROS domain 内的任意进程都可以
     直接给 `/rg/nav_execute` 发 Goal，绕过 Gateway；
   * "Gateway 是唯一入口"目前只是**拓扑事实 + 代码约束**，不是强制边界。
   * 详见 [`security/README.md`](security/README.md)（含 P1 阶段必须补的验证项）。
2. **`navigation_sim` 不做路径规划、不建图**，只记录坐标并返回结果。
3. **`request_id` 去重是内存态**：Gateway 重启后重复窗口清空；未做持久化。
4. **频率限制是单进程滑动窗口**（60s），未做分布式/多实例一致性。
5. **鉴权只看业务字段**：`task_id` / `frame_id` / 区域 / 频率。`frame_id == map`
   才是"可信坐标系"这一前提**未被 TF 校验**（方案 §2.2 提到的事实前提，本阶段未实现
   TF 转换或校验）。
6. **未做跨主机/跨容器 DDS 发现验证**：所有节点在同一个容器内（共享 netns/ipc），
   并设置 `ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST`。WSL2 下跨主机发现未测试。
7. **宿主机不是 Ubuntu 24.04**：Jazzy 跑在容器里。`RG_MODE=native` 路径已实现但
   **未在原生 24.04 上实测过**（本次环境不存在该机器）。
8. **未安装/未验证 Nav2 与 Gazebo**：`/rg/nav_execute` 目前指向 `navigation_sim`；
   未来替换为 Nav2 `/navigate_to_pose` 只需要 Adapter，不必改 Planner↔Gateway 契约，
   但**该适配本身未实现**。
9. **未做持久化审计与审计 Topic**：事件只写本地 JSONL（方案 §2.3 提到"以后可发布
   审计 Topic"），未实现转发。
10. **`AUDIT_UNAVAILABLE` 是词表扩展**（见 §2.5），已显式标注，正常运行不触发。
11. **`planner_node` 的"唯一出口"是代码常量**，不是运行时强制；能被修改源码者绕过。
12. **未做性能/压力测试**：并发多 Goal 的正确性只有单元测试级别（`RequestTracker`
    多线程用例），未做 Action 层并发压测。

---

## 7. 术语与边界对照（方案v1.2）

| 方案条目 | 落地位置 | 状态 |
| --- | --- | --- |
| §1.1 系统/框架/语言/构建/RMW 冻结 | `environment.md` | ✅ 实测 |
| §1.3 首个运行证明（talker/listener 级别） | 本实现直接给出四节点 Action 闭环 | ✅ 更强证明 |
| §2.1 四个节点与通信资源冻结 | `src/`，`ros2 action list -t` 实测 | ✅ |
| §2.2 Action / 策略契约冻结 | `PatrolNavigate.action`、`config/task_policy.yaml` | ✅ |
| §2.2 `/rg/task_info` 不得覆盖权威策略 | Gateway 不订阅；payload 不含区域 | ✅ |
| §2.3 同步准入 + 异步记录 | `security_gateway` + `EventWriter` | ✅ |
| §2.3 三种事件字段 | `rg_policy/events.py` + JSONL 实测 | ✅ |
| §2.3 原因码规范 | `rg_policy/reason_codes.py` | ✅（+1 个已标注扩展） |
| §3.1 最小闭环 | A/B 联调实测 | ✅ |
| §3.2 状态机（CREATED→…→SUCCEEDED/FAILED） | `_on_execute` / `_forward` / `_finish_failure` | ✅ |
| §3.3 接口与判定分离（纯函数） | `policy_engine.evaluate` + 纯函数测试 | ✅ |
| §3.3 执行端 Adapter 可替换 | `downstream_action` 为参数 | ✅ 预留 |
| §3.3 SROS 2 限制 Planner 只访问网关 | `security/README.md` 预留 | ⏳ **未实现** |
| §5.1 P0 各项 | 见 [`ACCEPTANCE.md`](ACCEPTANCE.md) | ✅ 见验收表 |
| §5.1.1 P1 SROS 2 / P2 Nav2·Gazebo | — | ⏳ **未实现**（不阻塞首次联调） |

---

## 8. 下一步（不属于本次交付）

1. **P1**：SROS 2 Enforce 模式 + 四个 enclave 的 permissions XML，并留下
   ①授权链仍可通的证据 ②Planner 直连 `/rg/nav_execute` 失败的 DDS 错误日志；
   只有这两条都实测通过，才能对外声称"底层资源访问不可绕过"。
2. **P2**：写 Nav2 Adapter 替换 `navigation_sim`，保持 `downstream_action` 参数即可切换。
3. 审计事件发布为 Topic，供外部 SOC/IDS 消费。
4. `request_id` 去重与频率限制持久化；多实例一致性。
5. `frame_id` 的 TF 可信性校验（而不是仅字符串相等）。
