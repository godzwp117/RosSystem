# 2026-10-19 演示故障处理手册

> 适用版本：`be47ccd6c1b19460b65abc0ea8004706383d01d4`
> 原则：**任何恢复手段都不得关闭安全机制、放宽权限或伪造结果。**

---

## 0. 通用诊断顺序

演示出问题时，按这个顺序看，不要跳步：

```bash
cd /home/zhangwei/project/RosSystem-worktrees/demo-freeze

./scripts/demo_20261019_release.sh --scenario check    # 门禁会直接指出哪一层坏了
docker ps --format '{{.Names}}\t{{.Status}}' | grep rg_demo
docker exec rg_demo bash -lc 'source /opt/ros/jazzy/setup.bash; timeout 8 ros2 node list'
```

门禁会给出准确原因码，比逐个猜快得多。

---

## 1. ROS 节点启动失败

**现象**：`ros2 node list` 为空；日志出现 `Process exited with failure 1`。

**排查**：

```bash
docker exec rg_demo bash -lc '
  source /opt/ros/jazzy/setup.bash
  cd /ws && source install/setup.bash
  ros2 pkg list | grep rg_          # 期望 4 个
  ros2 run rg_demo_nodes navigation_sim --ros-args -p record_path:=/tmp/probe.jsonl &
  sleep 3; ros2 node list; kill %1'
```

**常见原因与处置**：

| 原因 | 识别 | 处置 |
| --- | --- | --- |
| 未构建 | `ros2 pkg list` 无 `rg_*` | `colcon build --symlink-install --packages-select rg_interfaces rg_policy rg_gateway rg_demo_nodes` |
| 未 source | 命令找不到 | 先 `source /opt/ros/jazzy/setup.bash` 再 `source install/setup.bash` |
| `set -u` 下 source 报 `COLCON_TRACE: unbound variable` | 启动即退出 | 在 `set +u` 期间完成所有 sourcing（发布脚本已修正此点） |

**禁止**：用 `pkill -f` 按进程名清理"可能残留"的节点——会误杀同容器内其他实例。
只用 `kill -INT -<PGID>` 终止自己启动的进程组。

---

## 2. Domain 冲突

**现象**：门禁报 `Domain 56 上已存在 N 个节点`；或 GateWay 收到不属于本次的请求。

**排查**：

```bash
docker exec -e ROS_DOMAIN_ID=56 rg_demo bash -lc '
  source /opt/ros/jazzy/setup.bash; cd /ws && source install/setup.bash
  timeout 8 ros2 node list'
```

**处置**（按优先级）：

1. **换一个空闲 Domain 演示**（最安全）：
   ```bash
   ./scripts/demo_20261019_release.sh --scenario all --domain 57 --run-id demo-20261019-b
   ```
2. 如果是自己上一次演示残留，检查并显式终止对应进程组；
3. **不要**为了抢 Domain 去改别人的容器或端口。

**禁止**：为了让门禁通过而改门禁或忽略告警。

---

## 3. Action server 不可达

**现象**：F0 输出 `online.outcome = PLANNER_NO_ACTION_SERVER`；日志 `Wait for action server ... timeout`。

**含义**：Gateway 或 Planner 没起来，或不在同一 Domain。

**处置**：

```bash
docker exec -e ROS_DOMAIN_ID=56 rg_demo bash -lc '
  source /opt/ros/jazzy/setup.bash; cd /ws && source install/setup.bash
  timeout 8 ros2 action list | grep guarded_navigate'
```

- 无输出 → Gateway 未启动：重跑对应场景脚本（它会自行拉起栈）；
- 有输出但仍失败 → 检查 `logs/demo/gateway.log`。

---

## 4. Python 环境错误

**现象**：模块退出码 `2`，stderr `INPUT_INVALID: ImportError`；或门禁报 `jsonschema none`。

**根因**：系统 `python3` 的 `jsonschema` 是 3.x，无法构造 Draft 2020-12 校验器。
模块会**正确**失败关闭，但看起来像"模块坏了"。

**处置**：

```bash
# 容器内
docker exec rg_demo bash -lc 'apt-get update -qq && apt-get install -y -qq python3-jsonschema python3-yaml'
docker exec rg_demo bash -lc 'python3 -c "from importlib.metadata import version;print(version(\"jsonschema\"))"'
# 期望 >= 4

# 宿主（跑三真实/F0 测试）
./.research-venv/bin/python -c "from importlib.metadata import version;print(version('jsonschema'))"
```

**禁止**：把未执行的测试记为 PASS 来"绕过依赖问题"。

---

## 5. Gateway 未就绪

**现象**：`GATEWAY_READY` 标记迟迟不出现；审计文件为空。

**处置**：

```bash
docker exec rg_demo bash -lc 'tail -n 30 /ws/logs/demo/gateway.log'
```

| 日志特征 | 原因 | 处置 |
| --- | --- | --- |
| `policy ... not found` | 策略路径错 | 确认 `config/task_policy.yaml` 存在且未被移动 |
| `address already in use` | 上一实例未退 | 终止自己的进程组后重跑 |
| `SECURITY ERROR: directory ... does not exist` | Enforce 下 keystore 缺 enclave | 见第 6 节 |

---

## 6. DDS Enforce 拒绝异常

**现象**：S1–S6 有失败；日志出现 `SECURITY ERROR` 或本应成功的场景被拒。

**区分两种情况**：

1. **报错 `directory '.../enclaves/<role>' does not exist`**
   → keystore 未挂进容器。
   ```bash
   docker inspect rg_demo --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{"\n"}}{{end}}' | grep keystore
   ```
   修复：用第 2.1 节命令重建容器（只读挂载 keystore）。

2. **S3/S4 本应被拒却成功**
   → **这是安全问题，不是演示故障。**
   - 立刻停止使用该环境做安全结论；
   - 检查 `security/policies/minimal_permissions.xml` 是否被改动：
     ```bash
     git -C /home/zhangwei/project/RosSystem-worktrees/demo-freeze diff --stat HEAD -- security/policies
     ```
   - 若被改动，恢复后重跑。

**禁止**：把 Enforce 降级为 Permissive、或给 Planner 加执行端权限来"让演示通过"。

---

## 7. Planner TIMEOUT

**现象**：F0 输出 `online.outcome = PLANNER_RESULT_TIMEOUT`。

**这不是错误，是真实观测。** 正确处置是**查审计**，不是重试刷结果：

```bash
EV=artifacts/demo-2026-10-19/release-freeze-<run_id>
RID=$(grep -o '"request_id": *"[^"]*on06[^"]*"' $EV/m3/merged/f0_ON06.json | head -1 | cut -d'"' -f4)
grep "$RID" $EV/m3/merged/gateway_audit.jsonl | wc -l   # 到达事件数
grep "$RID" $EV/m3/merged/navsim_goals.jsonl  | wc -l   # Goal 数
```

**讲解口径**：超时后下游结果**在 0 与 1 之间摆动**（历史四次实测：1/0/1/1，本轮 0）。
所以"是否执行"必须逐次从审计读取，**不能预设，也不能把超时记为 BLOCK**。

---

## 8. 模块 UNKNOWN

**现象**：`comm_risk` 状态 `UNKNOWN`；`identity_trust.current_request_identity = UNKNOWN`。

**这不是故障，是当前真实能力结论**：

| 模块 | 原因 | 是否可现场修复 |
| --- | --- | --- |
| M1 `UNKNOWN` | 模型 `validation_gate_passed=false` | **否**（需重训达标） |
| M2 当前身份 `UNKNOWN` | 无可信生产 DDS 身份签发者 | **否**（需中间件层机制） |

**讲法**：这正是 F0 失败关闭在起作用——"没有可信当前证据就不放行"。

**禁止**：
- 用 `--controlled-test` 让 M1 输出 NORMAL 并当作真实结论展示；
- 把 TEST_ONLY 签发者加入受信任清单；
- 用自报 enclave 代替 DDS 认证。

（`CONTROLLED_TEST_ONLY` 模式本身是合法工具，但**必须标注**其
`verified_by=MODULE_SELF_REPORT`、不构成真实身份认证。）

---

## 9. 日志目录冲突

**现象**：`logs/demo` 被占用；或证据目录已存在同名 `run_id`。

**处置**：

- 演示脚本默认按 UTC 时间生成 `run_id`，正常不会撞；
- 手工指定时用唯一 id：`--run-id demo-$(date -u +%H%M%S)`；
- 历史证据目录**不要删除**，换新 `run_id` 即可。

**禁止**：`rm -rf artifacts/` 或清空 `logs/` —— 会销毁历史证据。

---

## 10. 演示候选无法运行 → 回退 RC2

**触发条件**：`release/demo-2026-10-19-freeze` 环境无法在 5 分钟内修好。

**回退目标**：`demo-2026-10-19-rc2-verified` = `33cb4f93d5e5fd268878fe83fc040c655d632a70`
（主工作区 `/home/zhangwei/project/RosSystem` 当前即此版本）

### 10.1 回退步骤

```bash
cd /home/zhangwei/project/RosSystem

# 确认版本
git rev-parse HEAD
# 期望 33cb4f93d5e5fd268878fe83fc040c655d632a70

# 确认工作区干净
git status --short

# RC2 的演示入口（用主工作区的容器 rg_jazzy）
bash scripts/run_demo.sh
```

### 10.2 RC2 能演示什么

| 能力 | RC2 | 本候选 |
| --- | --- | --- |
| Gateway A/B 闭环 | ✅ | ✅ |
| M3 在线六场景 | ✅（历史证据） | ✅（本轮证据） |
| F0 身份防伪造（P0 修复） | ❌ **无** | ✅ |
| 三真实模块联合调用 | ❌ **无** | ✅（LEVEL 3 BLOCKED） |
| DDS Enforce 7/7 | ✅ | ✅ |

**关键差别**：RC2 **没有** F0 安全修复，也**没有**三真实模块集成。
若回退到 RC2，**不得**再宣称"F0 已能拒绝伪造身份"或"三真实模块已接入"。

### 10.3 回退的纪律

- **不移动** `demo-2026-10-19-rc2-verified` 标签；
- **不删除**本候选的证据目录；
- 回退后在讲解中**明确说明**当前运行的是 RC2，能力范围按上表。

---

## 11. 一页速查表

| 症状 | 最可能原因 | 一行处置 |
| --- | --- | --- |
| 门禁 `工作区不干净` | 有未提交改动 | `git status` 确认后提交或还原 |
| 门禁 `容器未运行` | 容器停了 | `docker start rg_demo` |
| 门禁 `包数 < 4` | 未构建 | `colcon build`（见 §2.1） |
| 门禁 `jsonschema none` | 依赖缺失 | `apt-get install python3-jsonschema` |
| 门禁 `Domain 上已有节点` | 冲突 | 换 `--domain 57` |
| 门禁 `keystore 不可用` | 未挂载 | 重建容器（§2.1） |
| 门禁 `策略有改动` | 被误改 | `git checkout -- config/task_policy.yaml security/policies` |
| `PLANNER_NO_ACTION_SERVER` | Gateway/Planner 未起 | 查 `ros2 action list` |
| `INPUT_INVALID: ImportError` | jsonschema 3.x | 装 4.x（§4） |
| `PLANNER_RESULT_TIMEOUT` | 真实超时 | **查审计，别重试**（§7） |
| 模块 `UNKNOWN` | 真实能力限制 | 如实讲解（§8） |
| S3/S4 未被拒 | **安全异常** | 停止演示并排查（§6） |
