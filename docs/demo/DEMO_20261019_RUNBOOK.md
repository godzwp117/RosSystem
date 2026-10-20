# 2026-10-19 演示 Runbook（现场操作手册）

> 受测版本：`be47ccd6c1b19460b65abc0ea8004706383d01d4`（`release/demo-2026-10-19-freeze`）
> 回退版本：`demo-2026-10-19-rc2-verified` = `33cb4f93d5e5fd268878fe83fc040c655d632a70`
> 彩排结论：**DEMO_FREEZE_PASS**（`--scenario all` 12/12）

---

## 0. 三十秒速览

```bash
cd /home/zhangwei/project/RosSystem-worktrees/demo-freeze

# 1) 门禁（不动任何东西，只检查）
./scripts/demo_20261019_release.sh --scenario check

# 2) 全场景彩排/演示（一次生成同一 run_id 的证据）
./scripts/demo_20261019_release.sh --scenario all --run-id demo-20261019

# 3) 单场景（时间紧时用）
./scripts/demo_20261019_release.sh --scenario m3 --run-id demo-20261019-m3
```

证据落在 `artifacts/demo-2026-10-19/release-freeze-<run_id>/`。

---

## 1. 固定参数（现场不要改）

| 项 | 值 |
| --- | --- |
| 工作树 | `/home/zhangwei/project/RosSystem-worktrees/demo-freeze` |
| 分支 | `release/demo-2026-10-19-freeze` |
| 受测 SHA | `be47ccd6c1b19460b65abc0ea8004706383d01d4` |
| 演示容器 | `rg_demo`（`ros:jazzy`，独立挂载本工作树） |
| ROS | Jazzy，`rmw_fastrtps_cpp` |
| 在线 Domain | **56**（普通模式，未启用 DDS-Security） |
| Enforce Domain | **43**（Enforce） |
| 容器内 jsonschema | 4.10.3 |
| Host venv | `.research-venv/bin/python`（Python 3.10.12，jsonschema 4.26.0） |
| keystore | 只读挂载 `/home/zhangwei/project/RosSystem/security/keystore` |

> **在线（56）与 Enforce（43）是两次独立实验。** 讲解时必须分开说。

---

## 2. 演示前 10 分钟检查清单

按顺序执行，任一步失败见 `DEMO_20261019_FAILURE_RECOVERY.md`。

```bash
cd /home/zhangwei/project/RosSystem-worktrees/demo-freeze

# 2.1 版本正确、工作区干净
git rev-parse HEAD
git status --short                     # 除 artifacts/ logs/ 外应为空

# 2.2 容器在跑
docker ps --format '{{.Names}}\t{{.Status}}' | grep rg_demo

# 2.3 门禁一次性检查（版本/环境/域/keystore/策略）
./scripts/demo_20261019_release.sh --scenario check
```

期望输出包含五行 `[PASS]`：
工作区干净、ROS 2 Jazzy + 4 包、Domain 56 空闲、keystore 可用、TaskPolicy 未改动。

### 2.1 如果容器不在

```bash
docker run -d --name rg_demo --hostname rg_demo \
  -v /home/zhangwei/project/RosSystem-worktrees/demo-freeze:/ws \
  -v /home/zhangwei/project/RosSystem/security/keystore:/ws/security/keystore:ro \
  -w /ws -e ROS_DOMAIN_ID=56 -e RMW_IMPLEMENTATION=rmw_fastrtps_cpp \
  ros:jazzy sleep infinity

docker exec rg_demo bash -lc 'apt-get update -qq && apt-get install -y -qq python3-jsonschema python3-yaml'
docker exec rg_demo bash -lc 'source /opt/ros/jazzy/setup.bash && cd /ws && \
  colcon build --symlink-install --packages-select rg_interfaces rg_policy rg_gateway rg_demo_nodes'
```

---

## 3. 场景 1：Gateway A/B 基础闭环（约 15 秒）

```bash
./scripts/demo_20261019_release.sh --scenario ab --run-id demo-20261019-ab
```

**看点**：A 区合法请求 → `ALLOW` → NavigationSim **+1 Goal**；B 区越界 → `BLOCK`
→ **0 追加 Goal**。

**口径**：该场景 `M1/M2` 为 **MOCK**，只演示 F0→Gateway→NavigationSim 的
权威准入与执行链。

证据：`release-freeze-demo-20261019-ab/ab/{audit.jsonl,navsim_goals.jsonl,demo.log}`

---

## 4. 场景 2：真实 M3 在线六场景（约 90 秒）

```bash
./scripts/demo_20261019_release.sh --scenario m3 --run-id demo-20261019-m3
```

脚本会：跑第一组（ON-01/02/05）→ 第二组（ON-03/04/06）→ 合并证据 →
运行独立跨层复核器。

**六个场景的口径**：

| 场景 | 展示什么 | 说什么 |
| --- | --- | --- |
| ON-01 | 合法任务 `ALLOW` + 执行 | 真实 M3 允许 → Gateway 允许 → 真实执行 |
| ON-02 | M3 越界阻断 | M3 提阻断建议，F0 不提交下游 |
| ON-03 | 策略缺失 → `UNKNOWN` | 证据不足即失败关闭 |
| ON-04 | 策略损坏 → `ERROR` | 模块自身失败也失败关闭 |
| ON-05 | **M3 允许但 Gateway 拒绝** | **Gateway 保留独立权威** |
| ON-06 | Planner 超时 | 超时后是否执行**必须查审计**，不可预设 |

**ON-06 现场讲法**：先不说结论，直接看本轮日志：
```bash
grep on06 <证据目录>/m3/merged/navsim_goals.jsonl | wc -l
grep on06 <证据目录>/m3/merged/gateway_audit.jsonl | wc -l
```
不同 run 的次数会不同（历史出现过 0 和 1），这正是不该预设的理由。

证据：`release-freeze-demo-20261019-m3/m3/merged/{verification.md,gateway_audit.jsonl,navsim_goals.jsonl}`

---

## 5. 场景 3：三个真实模块联合调用（约 10 秒，离线）

```bash
./scripts/demo_20261019_release.sh --scenario three-real --run-id demo-20261019-tr
```

期望输出：

```
THREE_EXTERNAL_CALLED          = PASS
THREE_EXTERNAL_VALIDATED       = PASS
THREE_EXTERNAL_ONLINE_PROCEED  = BLOCKED
```

三个模块的真实结论（本轮实测）：
```
comm_risk      UNKNOWN                 （模型门槛未过）
identity_trust AUTHORIZED（历史）       current_request_identity = UNKNOWN
task_risk      ALLOW_RECOMMENDED
F0: ADAPTER_BLOCK / ADAPTER_MODULE_STATUS_NOT_PROCEED
```

**口径**：这是**正确阻断**，不是故障。它证明"无真实可信当前证据时系统拒绝放行"。

证据：`release-freeze-demo-20261019-tr/three-real/summary.json`

---

## 6. 场景 4：F0 身份防伪造（约 5 秒）

```bash
./scripts/demo_20261019_release.sh --scenario f0 --run-id demo-20261019-f0
```

期望：`38 passed`。

**看点**（对应 `tests/unit/test_f0_identity_trust_boundary.py`）：

- 裸 `AUTHENTICATED` → BLOCK
- **伪造完整 `checks` 六字段 → BLOCK**
- 历史 `AUTHORIZED` → 不能冒充当前身份
- `TEST_ONLY` 签发者 → 严格模式拒绝
- 缺凭据 / 坏签名 / 签发者未列 / 摘要错配 / 过期 / 重放 / 权限过宽 → 全部 BLOCK

**口径**：F0 不信自报 ≠ M2 已有真实 DDS 身份认证能力。

---

## 7. 场景 5：DDS-Security Enforce（约 60 秒，域 43）

```bash
./scripts/demo_20261019_release.sh --scenario dds --run-id demo-20261019-dds
```

期望：`SROS2 SUMMARY (7 passed / 7 total)`。

**看点**：

| 场景 | 展示什么 |
| --- | --- |
| S1 | 普通模式 A 区请求（域 42，未启用安全） |
| S2 | Enforce 合法请求：Planner→Gateway→NavigationSim 正常完成 |
| S3 | **`/planner` 身份直连 `/rg/nav_execute` 被 DDS 原生拒绝** |
| S3C | **正向对照：`/gateway` 身份直连执行端成功** |
| S4 | 无授权主体访问执行端被原生拒绝 |
| S5 | Enforce 下 B 区越界：身份合法但 TaskPolicy 拒绝 |
| S6 | 安全配置失效**不静默降级** |

**口径**：本次 Enforce 与场景 2/3 **不是同一次运行**，域也不同。

原生拒绝证据：`release-freeze-demo-20261019-dds/dds_enforce/S3/rogue_planner.log`
（含 `not found in allow rule` 等 Fast DDS 原生信息），**不是**靠客户端超时推断。

---

## 8. 时间不够时的最小演示集

如果现场只有 5 分钟：

1. `--scenario check`（30 秒，证明版本与环境可信）
2. `--scenario m3`（90 秒，含 ON-05 Gateway 独立阻断）
3. `--scenario f0`（5 秒，安全反例）

DDS 用**已有证据**讲解：
```bash
less artifacts/demo-2026-10-19/release-freeze-rehearsal-20261018T144247Z/dds_enforce/S3/rogue_planner.log
```

---

## 9. 演示后

```bash
# 9.1 证据完整性
cd artifacts/demo-2026-10-19/release-freeze-<run_id>
sha256sum -c SHA256SUMS.txt | tail -3

# 9.2 确认没有遗留节点
docker exec rg_demo bash -lc 'source /opt/ros/jazzy/setup.bash; timeout 8 ros2 node list | wc -l'
# 期望 0

# 9.3 确认没有密钥入库
git -C /home/zhangwei/project/RosSystem-worktrees/demo-freeze status --short | grep -iE '\.pem|\.key|keystore' || echo "无密钥文件"
```

---

## 10. 回退到 RC2（演示候选无法运行时）

见 `DEMO_20261019_FAILURE_RECOVERY.md` 第 10 节。核心命令：

```bash
git -C /home/zhangwei/project/RosSystem worktree list           # 找到 RC2 工作树
cd /home/zhangwei/project/RosSystem                             # 主工作区即 RC2
git rev-parse HEAD                                              # 应为 33cb4f9...
bash scripts/run_demo.sh
```

**回退不改变 RC2 标签，也不移动任何已发布引用。**
