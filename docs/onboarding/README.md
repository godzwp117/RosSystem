# RosSystem F0 新成员接入指南

> 面向**第一次接触本项目**的开发者。按本文顺序执行即可从零跑通，
> 不需要先做复杂排障。所有命令都在本仓库的实际代码上验证过。

| 项 | 值 |
| --- | --- |
| 适用工程 | RosSystem F0 协作基底 |
| 契约状态 | `PROPOSED_V1`（**尚未冻结**，字段仍可能调整） |
| 目标版本 | 见 `docs/team/PROJECT_DEVELOPMENT_STATUS.md` 记录的固定提交 SHA |

**本文只讲怎么做，不讲谁负责什么。**

---

## 0. 三十秒总览

```text
你在 Ubuntu 22.04 宿主上工作
  └─ ROS 2 Jazzy 跑在 Docker 容器里（Ubuntu 24.04），你的仓库挂载到容器内 /ws
       └─ 四个 ROS 2 包：rg_interfaces / rg_policy / rg_gateway / rg_demo_nodes
            └─ 三个研究模块（通信行为 / 身份授权 / 任务风险）目前是 Mock，
               通过 scripts/team_demo.py 这个适配层调用
                 └─ 适配层判定通过后，才由既有 Planner 提交到 /rg/guarded_navigate
                      └─ SecurityGateway 做权威判定 → /rg/nav_execute → NavigationSim
```

关键心智模型：**适配层的判定不是授权**。它只说"这份候选输入可以进入提交流程"。

---

## 1. 开发前提

| 需要 | 说明 |
| --- | --- |
| 宿主 | Ubuntu 22.04（当前环境为 WSL2） |
| Docker | 可在宿主执行 `docker`（**不在宿主安装 ROS 2**） |
| 磁盘 | 建议 ≥ 20 GB 可用（镜像 + 构建产物 + 证据） |
| Git | 能访问 `git@github.com:godzwp117/RosSystem.git`（SSH） |
| 网络 | 首次需拉取镜像并安装一个 Python 依赖 |

**为什么不在宿主装 ROS 2**：Jazzy 只打包给 Ubuntu 24.04，宿主的 22.04 装不了。
所以 ROS 环境放在容器里，仓库 bind mount 进去。

---

## 2. 获取固定代码版本

不要用分支名当版本号——分支会移动。取固定提交：

```bash
git clone git@github.com:godzwp117/RosSystem.git
cd RosSystem
git fetch --all --tags

# 用 docs/team/PROJECT_DEVELOPMENT_STATUS.md 里记录的 SHA
git checkout <F0_COMMIT_SHA>
git rev-parse HEAD          # 确认与记录一致
```

---

## 3. 建立独立工作区与成员容器

**一成员一工作区、一容器、一开发 Domain。** 成员档位（`scripts/member_env.sh`）：

| 档位 | 容器名 | 开发 Domain |
| --- | --- | --- |
| `RG_MEMBER=1` | `rg_member1` | 51 |
| `RG_MEMBER=2` | `rg_member2` | 52 |
| `RG_MEMBER=3` | `rg_member3` | 53 |
| `RG_MEMBER=4` | `rg_member4` | 54 |

```bash
# 在你自己的工作区里执行；只传 RG_MEMBER，不要同时传 RG_CONTAINER
RG_MEMBER=2 scripts/container_up.sh
```

预期输出包含：

```text
[container] ensuring python3-jsonschema (Draft 2020-12 validation)...
  [ok] ...
[container] ready. ROS inside the container:
  ROS_DISTRO: jazzy
  RMW:       rmw_fastrtps_cpp
  domain:    52
```

> **优先级与冲突规则**：显式的 `RG_CONTAINER` / `ROS_DOMAIN_ID` 优先于 `RG_MEMBER`；
> **两者同时给出且不一致时会直接报错**，不会猜测——避免"以为在自己的环境里"
> 却实际用了别人的容器或通信域。
>
> **容器创建时固化的环境变量不会因宿主后来修改而更新。**
> 需要不同 Domain 请新建容器，别指望已有容器跟着变。

---

## 4. 检查 ROS 2 Jazzy 与中间件

```bash
scripts/shell.sh 'echo $ROS_DISTRO; echo $RMW_IMPLEMENTATION; echo $ROS_DOMAIN_ID'
```

预期：`jazzy` / `rmw_fastrtps_cpp` / 你的 Domain。

`scripts/shell.sh` 的行为：有终端时进交互式 shell；无终端时可执行单条命令
（`scripts/shell.sh '<command>'`），不会因为"没有 TTY"而失败。

---

## 5. 安装并验证 JSON Schema 依赖

契约校验与适配层需要 `jsonschema >= 4.0`（Draft 2020-12），
**`ros:jazzy` 基础镜像不带它**。`container_up.sh` 会自动安装；这里单独验证：

```bash
scripts/check_deps.sh          # 期望输出 [deps] OK，退出码 0
```

它做的是**真实能力检查**，而不是"包在不在"：

1. `jsonschema` 可导入；
2. 真实具备 `Draft202012Validator`；
3. **严格 RFC 3339 检查器自检通过** —— 环境缺 `rfc3339-validator` 时
   `format` 关键字会**静默失效**，非法时间戳会通过校验。

失败时脚本会给出可直接复制的安装命令并返回退出码 5。
若确实无法安装，可设 `RG_SKIP_DEP_CHECK=1`，但此时**不得**声称环境已就绪。

---

## 6. 编译四个 ROS 2 包

```bash
scripts/build.sh               # 期望 BUILD RESULT: PASS
```

该脚本在检测到"有受管理实例正在运行"时会**拒绝构建**，而不是替你杀掉正在运行的系统。

---

## 7. 运行阶段 C 契约测试（可离线）

```bash
scripts/shell.sh 'python3 -m pytest tests/unit/test_team_contracts.py -q'   # 53 项
scripts/shell.sh 'python3 scripts/validate_team_contracts.py --all'          # CONTRACT VALIDATION: PASS
```

这两项**不需要 ROS 环境**，只依赖 `jsonschema`。

---

## 8. 运行三个 Mock

Mock 读 stdin 一个 JSON 对象，写 stdout 一个 JSON 对象，诊断信息走 stderr。

```bash
# 准备一个输入信封（最小可用示例）
cat > /tmp/env.json <<'EOF'
{
  "schema_version": "1.0.0-proposed",
  "run_id": "run-demo", "request_id": "req-demo",
  "created_at": "2026-10-10T12:00:00Z",
  "candidate_action": {
    "action_resource": "/rg/guarded_navigate", "operation": "NAVIGATE",
    "task_id": "patrol_a_001",
    "target": {"frame_id": "map", "x": 2.0, "y": 2.0, "z": 0.0}},
  "observations": [{"source": "/rg/guarded_navigate", "kind": "MOCK",
    "observed_at": "2026-10-10T12:00:00Z",
    "detail": {"f0_mock": {
      "comm_risk": {"scenario": "normal"},
      "identity_trust": {"scenario": "authorized"},
      "task_risk": {"scenario": "allow"}}}}],
  "evidence_refs": [{"ref": "demo", "kind": "MOCK"}]
}
EOF

scripts/shell.sh 'python3 mock_modules/comm_risk_mock.py < /tmp/env.json'
scripts/shell.sh 'python3 mock_modules/identity_trust_mock.py < /tmp/env.json'
scripts/shell.sh 'python3 mock_modules/task_risk_mock.py < /tmp/env.json'
```

每个 Mock 支持 4 个状态（见 `mock_modules/README.md`）。
所有输出都标记 `producer.source = MOCK` —— **模拟结论不构成任何安全保证**。

---

## 9. 修改单个模块的外部命令配置

编辑 `config/team_modules.example.yaml`，只改目标模块的 `mode` 与 `command`：

```yaml
modules:
  comm_risk:
    mode: external
    interface: comm_risk_evidence
    command: ["python3", "path/to/your_module.py"]
    timeout_sec: 10
    max_stdout_bytes: 65536
```

**命令只能来自这个受信任的本地配置**；业务输入无法影响命令行。
`command` 必须是参数数组，字符串形式会被拒绝（会被 Shell 解释）。

---

## 10. 用独立测试替身替换一个 Mock

仓库自带三个**规则计算型**替身（与场景选择型 Mock 本质不同）：

```bash
scripts/shell.sh 'python3 -m pytest tests/unit/test_team_adapter.py -q -k replacement'
```

手工替换示例（只换通信模块，其余保持 Mock）：

```yaml
  comm_risk:
    mode: double
    interface: comm_risk_evidence
    command: ["python3", "tests/fixtures/team_modules/comm_risk_double.py"]
```

替身会按输入里的 `observations[].detail.comm.request_count/baseline_count`
**真实计算**风险状态，而不是读场景开关。

---

## 11. 执行真实 `/rg/guarded_navigate` 请求

先起栈（Gateway + NavigationSim + Operator），再让适配层在线提交：

```bash
# 终端 A：起栈（用独立日志路径，避免与其他实例混淆）
scripts/shell.sh 'cd /ws && source install/setup.bash && \
  ros2 launch rg_demo_nodes stack.launch.py \
  audit_log_path:=/ws/logs/my_audit.jsonl \
  navsim_record_path:=/ws/logs/my_navsim.jsonl'

# 终端 B：在线提交（默认是离线模式，只有 --online 才启动 Planner）
scripts/shell.sh 'cd /ws && source install/setup.bash && \
  python3 scripts/team_demo.py --input /tmp/env.json \
  --config config/team_modules.example.yaml \
  --online --planner-timeout 45 --log logs/my_adapter.jsonl'
```

期望：`"decision": "READY_FOR_GATEWAY_SUBMISSION"`，且 `online.outcome` 为
`PLANNER_RESULT_RECEIVED`。

> `READY_FOR_GATEWAY_SUBMISSION` **不代表** Gateway 已允许，更不代表下游已执行。
> 真实判定必须看 Gateway 审计。

---

## 12. 观察 Gateway DecisionEvent

```bash
scripts/shell.sh 'cat /ws/logs/my_audit.jsonl' | python3 -c "
import json,sys
for line in sys.stdin:
    r=json.loads(line)
    print(r.get('event_type'), r.get('request_id'), r.get('decision'), r.get('reason_code'))
"
```

一次合法请求会产生三个事件（同一 `request_id`）：
`RosCommEvent` → `DecisionEvent` → `ExecutionEvent`。

---

## 13. 查看 NavigationSim Goal

```bash
scripts/shell.sh 'wc -l /ws/logs/my_navsim.jsonl'          # 合法请求应 +1
scripts/shell.sh 'grep NAVSIM_GOAL /ws/logs/stack.log | tail -2'
```

---

## 14. 执行安全负例

最值得亲手跑的两条：

```bash
# 越权目标 (5.0, 5.0) 超出允许区域 x,y∈[0,4]
sed 's/"x": 2.0, "y": 2.0/"x": 5.0, "y": 5.0/' /tmp/env.json > /tmp/env_bad.json
scripts/shell.sh 'cd /ws && python3 scripts/team_demo.py --input /tmp/env_bad.json --online'

# 上游阻断：身份模块输出 DENIED，适配层应本地阻断且**不启动 Planner**
sed 's/"scenario": "authorized"/"scenario": "denied"/' /tmp/env.json > /tmp/env_denied.json
scripts/shell.sh 'cd /ws && python3 scripts/team_demo.py --input /tmp/env_denied.json --online'
```

预期的**区别**很重要：

| 情况 | 适配层 | Gateway | 下游 Goal |
| --- | --- | --- | --- |
| 越权目标 | READY | **BLOCK · OUT_OF_REGION** | 0 |
| 身份 DENIED | **ADAPTER_BLOCK** | 无该 request_id 的记录 | 0 |

即：越权是 **Gateway 策略阻断**（请求确实到了 Gateway）；
上游拒绝是 **适配层本地阻断**（请求根本没进 Gateway）。
两者不得混为一谈。

---

## 15. 结束当前实例并检查清理

```bash
# 在你的终端 A 按 Ctrl+C，或用实例记录里的进程组
cat logs/start_system/current_instance.env 2>/dev/null    # 若用 start_system.sh 启动

# 检查残留（只统计非僵尸）
scripts/shell.sh 'ps -eo stat=,cmd= --no-headers | grep -E "rg_gateway/lib|rg_demo_nodes/lib" | grep -v grep | grep -v "^ *Z" | wc -l'
```

期望为 `0`。容器内 PID 1 是 `sleep infinity`，不回收孤儿进程，
所以历史僵尸会累积——**僵尸不算存活**，但也不能用"排除僵尸"来掩盖新的进程泄漏。

---

## 16. 查看失败日志

| 内容 | 位置 |
| --- | --- |
| 构建 / 运行日志 | `logs/` |
| 适配层调用记录（JSONL） | `logs/team_adapter.jsonl`（或 `--log` 指定） |
| 集成测试证据 | `tests/evidence/<run_id>/` |
| 契约校验 | `CONTRACT VALIDATION: PASS/FAIL` 与退出码 |

失败时优先看三个地方：适配层结果里的 `reason_code`、栈日志里的就绪标记
（`NAVSIM_READY` / `GATEWAY_READY`）、以及 Gateway 审计里该 `request_id` 的
`DecisionEvent`。

---

## 17. 提交代码与创建 Pull Request

```bash
git switch -c feature/<你的主题>
git add <files>
git commit -m "<type>(f0): <说明>"
git push -u origin feature/<你的主题>
```

然后在 GitHub 上开 PR，`base` 选 `main`。

**本项目约定**：

- 不合并 `main`，不创建稳定标签（由项目负责人决定）；
- 不改 `src/rg_interfaces/action/PatrolNavigate.action`（冻结契约）；
- 不改 `src/rg_policy/rg_policy/reason_codes.py` 中八个业务原因码的含义；
- 不改 Gateway 核心准入逻辑；
- 本地归档文件 `gitlog.md` **不得上传**（已在 `.gitignore` 中，且没有 pre-commit 守卫）。

---

## 附录 A：故障排查索引

| 症状 | 根因 | 处理 |
| --- | --- | --- |
| `ERROR: 容器 'xxx' 的既有配置与本次请求不一致，已拒绝复用` | 你用的容器名属于别人，或挂载的是另一个工作区 | 按提示改用 `RG_MEMBER=<你的档位>`；**不要**删除既有容器 |
| `ERROR: 配置冲突 —— RG_MEMBER 对应容器 X，但显式指定了 Y` | 同时给了 `RG_MEMBER` 与 `RG_CONTAINER` | 只留一个：优先用 `RG_MEMBER` |
| `ADAPTER_DEPENDENCY_MISSING` | 容器里没有 `jsonschema>=4.0` | `scripts/check_deps.sh`；或 `docker exec <c> apt-get install -y python3-jsonschema` |
| `ModuleNotFoundError: No module named 'rg_gateway'` | 手工跑 pytest 却没 source 工作区 | 用 `scripts/run_unit_tests.sh`，或先 `source install/setup.bash` |
| Planner 报 `NO_ACTION_SERVER` | 栈没起、Domain 不对、或服务端未就绪 | 确认 `GATEWAY_READY` 已出现；确认两侧 `ROS_DOMAIN_ID` 一致 |
| 就绪探测说"看不到 Action"，但服务确实在跑 | 旧做法经共享 daemon 查图，daemon 会缓存上一个 Domain 的图 | 用 `tests/integration/domain_ready_probe.py`（进程内直接探测，不经 daemon） |
| 适配层返回 `ADAPTER_BLOCK` | 看 `reason_code`：`..._STATUS_NOT_PROCEED` 是上游状态不允许推进；`ADAPTER_CONSISTENCY_*` 是关联不一致；`ADAPTER_AUDIT_WRITE_FAILED` 是审计写不进去 | 按具体原因码定位；审计失败时**不得**绕过 |
| Gateway `OUT_OF_REGION` | 目标超出 `config/task_policy.yaml` 的允许区域 | 这是**正确**的策略阻断；把目标改回区域内 |
| DDS-Security 拒绝 | 安全模式下身份/权限不匹配 | 需要正确 Enclave 与权限策略；**仅凭客户端超时不能证明是权限拒绝** |
| 进程退出后仍有残留 | 终止 `docker exec` 客户端不会结束容器内进程 | 按唯一标记或进程组清理；不要按名称 `pkill` |
| 无法 `git push` 或建 PR | 缺少仓库协作者权限 | 联系仓库所有者添加；本地可先保留提交 |

---

## 附录 B：安全边界（必须理解，不可误读）

1. **SecurityGateway 是最终应用层执行准入点。** 适配层的
   `READY_FOR_GATEWAY_SUBMISSION` 不是授权。
2. **DDS-Security 负责通信身份与资源访问控制**，与业务层准入是两个层面。
3. **Mock 的自报身份不构成认证。** `producer` 字段是自报信息；
   测试用的权限矩阵推导也不是 DDS 认证结果。
4. **Docker / ROS Domain 隔离不是强身份隔离。** 单机共享容器下，
   成员之间**不能**声称密码学身份隔离。
5. **F0 不包含 M3 动态任务状态机。** `task_phase` / `policy_epoch` /
   `policy_digest` 均为可选字段，不得用占位值冒充真实策略版本。
6. **没有验证过的安全性质不得宣称已验证。**
