# ACCEPTANCE.md — 阶段五验收记录

依据方案v1.2 §5.1 分级验收表 / §5.2 结果记录模板，逐项填入**实测**结果。
所有数值来自实际执行，原始输出见文末「证据索引」。

---

## 5.2 验收结果记录（模板已填）

```
检查日期        : 2026-10-09
主机/系统       : WSL2 上的 Ubuntu 22.04.5 LTS（宿主机，无 ROS）
                  + Docker 容器 rg_jazzy（Ubuntu 24.04.5 LTS，ROS 2 Jazzy）
ROS_DISTRO      : jazzy
RMW             : rmw_fastrtps_cpp (ros-jazzy-rmw-fastrtps-cpp 8.4.4-1noble.20260902.041916)
Git Commit      : 工作区不是 git 仓库（git rev-parse HEAD 失败）→ 版本冻结依据为
                  镜像 digest sha256:066420e07f60aa18262f2479981def87ebcfcec42eefb0c0c57c4a46098348ca
                  与 environment.md 中的 deb 包版本清单
构建结果        : PASS     (colcon build，4 packages，exit 0)
启动结果        : PASS     (operator_node / security_gateway / navigation_sim 全部
                           打印 *_READY；ros2 action list 实测两个 Action 均在线)
合法 A 区       : PASS     下游收到 Goal 数：1
越界 B 区       : PASS     下游收到 Goal 数：0
错误任务/错误坐标系: PASS  (TASK_MISMATCH ×2 场景、INVALID_TARGET ×3 场景)
事件链可追踪    : PASS     (event_id 三段齐全；BLOCK 无 ExecutionEvent)
日志路径        : logs/*.log、logs/demo/、tests/evidence/20261009T045753Z/、
                  tests/evidence/20261009T045831Z/
尚未实现/失败项 : SROS 2 Enforce（P1）、Nav2/Gazebo 适配（P2）、TF 可信性校验、
                  去重与限流持久化、审计 Topic 转发、Action 层并发压测
下一阶段接口冻结版本: PatrolNavigate.action v0.1.0 / TaskPolicy schema v1.0 /
                  event schema v1.0 / reason-code 词表（8 项 + 1 项已标注扩展）
```

---

## 5.1 分级验收表（P0 全部实测）

| # | 验收项目 | 判据 | 证据位置 | 结果 |
| --- | --- | --- | --- | --- |
| 1 | 环境可复现（P0） | 按 README 构建与启动；记录 ROS、RMW、依赖版本 | [`environment.md`](environment.md)、[`logs/environment_report.txt`](logs/environment_report.txt)、[`logs/ros2_doctor_report.txt`](logs/ros2_doctor_report.txt) | **PASS** |
| 2 | 真实 ROS 2 通信（P0） | Planner↔Gateway、Gateway↔NavigationSim 均通过 Action 通信 | [`logs/demo.log`](logs/demo.log)、`tests/evidence/20261009T045753Z/*/gateway.log`、`ros2 action list -t` 输出（README §4.4） | **PASS** |
| 3 | 正常闭环（P0） | A 区 Goal 允许；下游执行数量为 1；Result 与 request_id 对应 | `tests/evidence/20261009T045753Z/A_zone_allow/`（`navsim_goals.jsonl` 1 行、`audit.jsonl` 3 事件、`planner_1_allow.log`） | **PASS** |
| 4 | 阻断闭环（P0） | B 区 Goal 被拒；下游执行数量为 0；原因码正确 | `tests/evidence/20261009T045753Z/B_zone_block_out_of_region/`（`navsim_goals.jsonl` 0 行、`OUT_OF_REGION`、1 条 REJECTED） | **PASS** |
| 5 | 异常输入（P0） | 无策略、任务不匹配、frame 错误、NaN/Inf 均按预期失败 | `tests/evidence/20261009T045831Z/`（12 个 scenario 全部 PASS） | **PASS** |
| 6 | 接口稳定性（P0） | Action 文件、Topic 名、策略 Schema 与 README 一致 | `tests/unit/test_interface_contract.py`（14 项，其中含已生成接口比对） | **PASS** |
| 7 | 事件可追溯（P0） | Event→Decision→Execution 可关联；拒绝无执行事件 | 每个 scenario 的 `audit.jsonl` + `scenario_result.json` 中 `event_id traceability` 与 `BLOCKed event_ids never have an ExecutionEvent` 断言 | **PASS** |
| 8 | SROS 2 资源隔离（P1） | 启用 Enforce 后授权链可通、Planner 直连下游失败 | [`security/README.md`](security/README.md) | **未实现**（P1，不阻塞） |
| 9 | Nav2/Gazebo 适配（P2） | Adapter 替换 NavigationSim，接口不变 | `downstream_action` 参数已预留 | **未实现**（P2，不阻塞） |

> P0 是"基底系统首次走通"的必备项，**7/7 全部 PASS**。
> 按方案 §5.1.1，**只有真实完成 P1 的 DDS-Security 授权/拒绝对照，才能声称
> "底层资源访问不可绕过"**。本交付**不做该声称**：SROS 2 未启用，当前准入控制是
> 业务规则层的执行前准入门，基础 Action 代理本身不提供密码学身份认证。

---

## 逐项测试结果（命令 / 返回码 / 断言 / 日志）

### T1 构建

| 项 | 值 |
| --- | --- |
| 命令 | `colcon build --event-handlers console_direct+`（容器内，cwd `/ws`） |
| 返回码 | `0` |
| 结果 | **PASS** — `Summary: 4 packages finished`（`rg_interfaces`、`rg_policy`、`rg_gateway`、`rg_demo_nodes`） |
| 日志 | [`logs/build.log`](logs/build.log) |
| 备注 | 构建期间**无新增 apt/pip 安装**；镜像自带全部依赖 |

### T2 单元测试

| 项 | 值 |
| --- | --- |
| 命令 | `python3 -m pytest tests/unit -v -p no:cacheprovider` |
| 返回码 | `0` |
| 结果 | **PASS** — `140 passed` |
| 日志 | [`logs/unit_tests.log`](logs/unit_tests.log) |

覆盖面：

| 文件 | 项数 | 覆盖内容 |
| --- | --- | --- |
| `test_task_policy_loader.py` | 46 | 权威策略加载；6 个必填字段逐一缺失；region 4 个字段逐一缺失；字符串/布尔/数值类型错误；NaN/Inf 边界；`x_min>x_max`；速率 ≤0；额外字段不致命；`PolicyProvider` mtime 热重载与"删除即失败" |
| `test_policy_engine.py` | 46 | 区域内含边界；越区 6 组；任务不匹配 4 组；frame 非法 5 组；request_id 非法 3 组；x/y/z 各 3 种非有限值；非数值；策略缺失/未激活；**规则优先级 4 组**；纯函数可重复性与不可变性 |
| `test_request_tracker.py` | 10 | 重复 id、TTL 过期、速率上限、窗口滑动、策略上限每次生效、被拒请求不占额度、内存有界、快照/重置、8 线程并发一致性 |
| `test_events.py` | 24 | 三类事件字段完整性；非法 decision/reason/status 码；空 event_id；`UNKNOWN`/`NONE` 显式标记要求；坏输入仍可记录；非有限值忠实编码且 JSON 严格合法；JSONL 追加/flush/父目录/关闭后写入报错；`event_id` 归组追溯 |
| `test_interface_contract.py` | 14 | `.action` 三段字段与顺序；两个 `---`；已生成 Python 接口比对；三个冻结资源名出现在源码；Planner 出口不可配置；Gateway 常量与线程数 ≥2；原因码词表冻结（8 项）与扩展隔离；策略 schema 冻结；权威策略等于文档示例；**源码树中无密钥类文件**；rg_policy 不 import rclpy |
| **合计** | **140** | `140 passed`（实测） |

### T3 A/B 联调（要求 11）

| 项 | 值 |
| --- | --- |
| 命令 | `python3 tests/integration/scenario_runner.py --suite ab` |
| 返回码 | `0` |
| 结果 | **PASS** — `2 passed / 2 total` |
| 日志 | [`logs/scenarios_ab.log`](logs/scenarios_ab.log) |
| 证据 | `tests/evidence/20261009T045753Z/summary.json`、`summary.md` |

| 场景 | 关键断言 | 断言数 | 结果 |
| --- | --- | --- | --- |
| `A_zone_allow` | `navsim Goal count == 1`；planner `success=true`/`EXECUTED`；`ALLOW_IN_POLICY`；`ExecutionEvent == 1`；REJECTED 0；executor 收到的 request_id 集合 == 被允许集合 | 13 | **PASS** |
| `B_zone_block_out_of_region` | `navsim Goal count == 0`；planner `success=false`/`OUT_OF_REGION`；`ExecutionEvent == 0`；REJECTED 1 且含 request_id/event_id/`downstream_goal_created:false`；BLOCK 的 event_id 无 ExecutionEvent | 15 | **PASS** |

### T4 负例联调（要求 12）

| 项 | 值 |
| --- | --- |
| 命令 | `python3 tests/integration/scenario_runner.py --suite negative` |
| 返回码 | `0` |
| 结果 | **PASS** — `12 passed / 12 total` |
| 日志 | [`logs/scenarios_negative.log`](logs/scenarios_negative.log) |
| 证据 | `tests/evidence/20261009T045831Z/summary.json`、`summary.md` |

| 场景 | 期望原因码 | NavSim Goal 数 | 断言数 | 结果 |
| --- | --- | --- | --- | --- |
| `policy_file_missing` | `POLICY_MISSING` | 0 | 15 | **PASS** |
| `policy_missing_required_field` | `POLICY_MISSING` | 0 | 15 | **PASS** |
| `policy_nonfinite_region` | `POLICY_MISSING` | 0 | 15 | **PASS** |
| `policy_inactive` | `POLICY_MISSING` | 0 | 15 | **PASS** |
| `task_id_mismatch_request_side` | `TASK_MISMATCH` | 0 | 15 | **PASS** |
| `task_id_mismatch_policy_side` | `TASK_MISMATCH` | 0 | 15 | **PASS** |
| `frame_id_invalid` | `INVALID_TARGET` | 0 | 15 | **PASS** |
| `target_nan` | `INVALID_TARGET` | 0 | 15 | **PASS** |
| `target_infinite` | `INVALID_TARGET` | 0 | 15 | **PASS** |
| `duplicate_request_id` | `ALLOW_IN_POLICY`,`DUPLICATE_REQUEST` | 1 | 18 | **PASS** |
| `rate_limit` | `ALLOW_IN_POLICY`×2,`RATE_LIMIT` | 2 | 21 | **PASS** |
| `execution_timeout` | `ALLOW_IN_POLICY`（+ `EXECUTION_TIMEOUT`） | 1 | 13 | **PASS** |

### T5 现场演示

| 项 | 值 |
| --- | --- |
| 命令 | `scripts/run_demo.sh`（内部 `bash scripts/demo_live.sh`，容器内） |
| 返回码 | `0` |
| 结果 | **PASS** — `DEMO RESULT: PASS (8 passed, 0 failed)` |
| 日志 | [`logs/demo.log`](logs/demo.log)、`logs/demo/audit.jsonl`、`logs/demo/navsim_goals.jsonl` |
| 额外实测 | `ros2 action list -t` 显示两个 Action；`ros2 topic echo /rg/task_info --once` 取到真实 `std_msgs/String` JSON；planner 收到 Feedback（`progress=0.5, phase=DOWNSTREAM:EXECUTING`） |

### T6 全量一键

| 项 | 值 |
| --- | --- |
| 命令 | `scripts/run_all.sh` |
| 返回码 | `0` |
| 结果 | **PASS** — `OVERALL: PASS`（build / unit / ab / negative 四阶段全 PASS） |
| 控制台留存 | [`logs/final_sweep_console.log`](logs/final_sweep_console.log) |

### T7 launch 文件（README §3.4 所述命令实测）

| 项 | 值 |
| --- | --- |
| 命令 1 | `ros2 launch rg_demo_nodes stack.launch.py policy_path:=… audit_log_path:=… navsim_record_path:=…`（cwd `/ws`） |
| 结果 1 | **PASS** — 3 个进程启动（pid 5349/5350/5351）；`OPERATOR_READY` / `NAVSIM_READY` / `GATEWAY_READY` 全部出现；运行中 `ros2 action list -t` 显示两个 Action；`SIGINT` 干净退出（exit -2 = SIGINT，符合预期），**无残留进程** |
| 命令 2 | `ros2 launch rg_demo_nodes demo.launch.py … request_id:=launch-a-1 target_x:=1.5 target_y:=1.5 expect_success:=1` |
| 结果 2 | **PASS** — 4 节点闭环：`PLANNER_RESULT … "success": true, "status_code": "EXECUTED", "goal_status": "STATUS_SUCCEEDED"`；`navsim.jsonl` **1 行**；`audit.jsonl` 判定 `ALLOW_IN_POLICY`；`SIGINT` 后无残留进程 |

> 两条 launch 命令的证据输出留在容器内 `/tmp/launchdemo*/`（临时目录，未纳入交付）；
> 上表结论来自实际运行输出，非推断。

---

## 真实阻塞与未运行项（不虚构通过）

| 项目 | 状态 | 真实原因 |
| --- | --- | --- |
| 宿主原生 ROS 2 Jazzy | **未运行** | 宿主为 Ubuntu 22.04；Jazzy deb 仅发布 noble(24.04)，apt 无法安装。已改用 `ros:jazzy` 容器满足 distro 要求 |
| `RG_MODE=native` 路径 | **未实测** | 本次环境不存在原生 24.04 + Jazzy 机器；脚本逻辑已实现但无实测证据 |
| SROS 2 Enforce / enclave / permissions | **未实现** | 任务边界明确要求仅预留；KEYSTORE/permissions 均未生成，`security/` 只有说明文档 |
| Planner 直连 `/rg/nav_execute` 的 DDS 拒绝证据 | **不存在** | 依赖 SROS 2 Enforce；未启用即无法产生该证据，因此不声称资源隔离 |
| Nav2 / Gazebo | **未安装、未验证** | 任务边界禁止安装；`downstream_action` 参数已为替换预留 |
| `frame_id` 的 TF 可信性校验 | **未实现** | 本阶段仅做 `frame_id == policy.coordinate_frame` 字符串相等判定 |
| 跨主机/跨容器 DDS 发现 | **未验证** | 全部节点在单一容器内（共享 netns/ipc），并设置 `ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST`；WSL2 跨主机发现未测试 |
| Action 层并发压测 | **未做** | 仅 `RequestTracker` 有 8 线程单元测试；未做多 Goal 并发端到端压测 |
| `request_id` 去重 / 限流持久化 | **未实现** | 均为 Gateway 进程内存态；重启后窗口清空 |
| 审计事件转发为 Topic | **未实现** | 当前仅写本地 JSONL |

---

## 证据索引

| 证据 | 路径 |
| --- | --- |
| 构建日志 | [`logs/build.log`](logs/build.log) |
| 单元测试日志 | [`logs/unit_tests.log`](logs/unit_tests.log) |
| A/B 场景日志 | [`logs/scenarios_ab.log`](logs/scenarios_ab.log) |
| 负例场景日志 | [`logs/scenarios_negative.log`](logs/scenarios_negative.log) |
| 现场演示日志 | [`logs/demo.log`](logs/demo.log) |
| 环境核查原始输出 | [`logs/environment_report.txt`](logs/environment_report.txt) |
| `ros2 doctor --report` | [`logs/ros2_doctor_report.txt`](logs/ros2_doctor_report.txt) |
| A/B 结构化证据 | `tests/evidence/20261009T045753Z/`（`summary.json`、`summary.md`、每场景 `commands.json` + `scenario_result.json` + 各节点日志 + `audit.jsonl` + `navsim_goals.jsonl`） |
| 负例结构化证据 | `tests/evidence/20261009T045831Z/`（同上） |
| 现场演示审计链 | `logs/demo/audit.jsonl`、`logs/demo/navsim_goals.jsonl` |

> `commands.json` 逐条记录每个场景执行的**完整 argv、cwd、起止时间、耗时、返回码、
> 日志路径**，满足要求 12「每次运行保留命令、返回码、测试结果、日志位置」。
