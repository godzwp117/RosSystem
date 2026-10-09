# M3 审阅交接说明（供外部审阅者 / ChatGPT）

> 本文件是**交接材料**，不是自评报告。目的是让审阅者能够**独立复核**每一项结论，
> 而不是复述作者的说法。请优先相信代码与原始日志，而不是本文的措辞。

---

## 0. 先读这一段：如何避免被误导

1. **一切钉在 SHA 上。** 分支会移动，请只按下面给出的 commit SHA 读代码：
   - 审阅目标：`3a6d2df1fb74ae5508c207890d17e5a7a24376fd`
   - 基线（母提交）：`838f66f41821edf0421612a205d162ae8e9eb955`（= 标签 `m2-secure-v1.0`）
2. **本文件里的"结论"全部是待验证命题**，不是已证实事实。每条都附了复核方式。
3. **区分"代码已实现"与"已实测通过"**：仓库里两者都有，但含义不同。
   实测证据在 `evidence/m3` 分支，不在代码分支。
4. **注意已知限制**（第 6 节）。作者已主动声明若干安全假设与未做项；
   若审阅者发现更多，属于预期内。
5. 请特别怀疑以下三类说法，并去代码里证伪：
   - "在途一致性屏障有效"（并发场景最容易有洞）
   - "拒绝来自 DDS 层"（不能只凭客户端超时推断）
   - "脱敏后无敏感信息"（脱敏器与扫描器可能共享盲区）

---

## 1. 仓库与访问方式

| 项 | 值 |
| --- | --- |
| 仓库 | `https://github.com/godzwp117/RosSystem`（**public**，可直接读取） |
| 审阅分支 | `feature/m3-dynamic-policy` |
| 审阅 SHA | `3a6d2df1fb74ae5508c207890d17e5a7a24376fd` |
| 基线 SHA | `838f66f41821edf0421612a205d162ae8e9eb955` |
| 公开证据分支 | `evidence/m3` @ `7584bcc2b35772313a700e63bdde3344b444e6a6` |
| 规模 | 29 files changed, 5521 insertions(+), 145 deletions(-)，8 个提交 |

单文件直读（钉在 SHA，替换 `<path>`）：
```text
https://raw.githubusercontent.com/godzwp117/RosSystem/3a6d2df1fb74ae5508c207890d17e5a7a24376fd/<path>
```

本地复核（推荐，可跑测试）：
```bash
git clone -b feature/m3-dynamic-policy https://github.com/godzwp117/RosSystem.git
cd RosSystem && git checkout 3a6d2df1fb74ae5508c207890d17e5a7a24376fd
```

---

## 2. 系统背景（最少必要上下文）

ROS 2 Jazzy 机器人业务基座，四包：`rg_interfaces` / `rg_policy` / `rg_gateway` / `rg_demo_nodes`。

```text
Planner ──/rg/guarded_navigate──> Gateway ──/rg/nav_execute──> NavigationSim
                                     │
                                     └─ 第 2 层：TaskPolicy 任务级判定（区域/速率/重复）
        └─ 第 1 层：SROS 2 / DDS-Security（身份 + 资源授权，M2 引入）
```

演进阶段（每个阶段都有独立证据包）：

| 阶段 | 内容 | 标签 / 证据 |
| --- | --- | --- |
| P0 | Action 代理最小基座 | `p0-stable-v1.0` |
| M1 | 审计 fail-closed、构建保护、超时语义 | 同标签 |
| M2 | SROS 2 Enforce、6 个 enclave、最小权限 | `m2-secure-v1.0` |
| M3 | **本次审阅对象**：可信任务动态约束 + 证据自动脱敏发布 | `evidence/m3` |

**M3 的核心命题**：*同一个合法 Planner、同一个 Action、同一个 `task_id`、同一组坐标，
在不同的可信任务阶段获得不同的授权结果* —— 且必须在**同一个持续运行的 Gateway 实例内**完成，
不能靠改 YAML、改 Planner 代码或重启网关冒充。

---

## 3. 待验证的核心结论（每条附复核方式）

### C1. 差异化授权（最关键）

**命题**：坐标 `(8.0, 8.0)` 在阶段 `ZONE_A` 被 `BLOCK(OUT_OF_REGION)`，
切到 `ZONE_B` 后**同一请求**变为 `ALLOW(EXECUTED)`。

复核：
- 代码：`gateway._effective_policy()` 用当前快照投影策略；`_on_execute` 的判定段
- 证据：`evidence/m3` → `m3_dynamic_policy/security_results.json`（场景 `D1_D2_D3_D4_D5_D6_D7_D14`）
- 本地：`tests/integration/dynamic_policy_check.py` 的 D2 与 D4

**审阅重点**：D2 与 D4 是否真的是"同一身份/同 Action/同 task_id/同坐标"？
（若不是，结论退化为"换了请求"，不成立。）请核对两处 `run_planner` 调用参数。

### C2. 管理接口最小权限

**命题**：`/planner` 身份调用 `/rg/task_control/switch` 会被 **DDS 访问控制层**拒绝；
`/task_admin` 身份成功。

复核：
- 权限文件：`security/policies/minimal_permissions.xml`（注意：**故意不含 XML 注释**）
- 生成后复核：`scripts/verify_sros2_permissions.py`
- 证据：场景 `D8_D9_D15`，期望出现 `rq/rg/task_control/switchRequest not found in allow rule`

**审阅重点**：
- 是否存在"用节点名判断管理员身份"的代码？（应当**没有**）
- 请求里是否有 `role`/`admin` 之类可自报字段？（应当**没有**）
- D8 的失败是否发生在**创建 Service 端点**阶段？若发生在"节点根本建不起来"，
  则结论不精确（作者曾因此修正过一次）。

### C3. 在途一致性与"超时≠已停止"

**命题**：存在在途 Goal、或执行超时且取消未确认时，任务切换被拒绝。

复核：
- 代码：`_on_execute` 中 `with self._transition_lock:` 临界区、`admitted` 局部变量、
  `_release_in_flight(confirmed=...)`、`_unconfirmed_in_flight`
- 证据：场景 `D10_D11`

**审阅重点（高风险区）**：
- 在途计数是否可能泄漏（只增不减）或漏计（只减不增）？
- `finally` 分支是否覆盖所有返回路径？
- 并发下是否有共享可变状态被多个 `_on_execute` 同时改写？
  （作者**曾在此处出过真缺陷**：早期版本用节点级共享标志 `_admission_registered`，
  并发时互相覆盖 —— 请检查现在是否真的改为每请求局部变量。）
- `_unconfirmed_in_flight` 的清零机制（`unconfirmed_clear_token`）是否构成绕过路径？

### C4. 重放 / 过期 epoch / 并发切换

**命题**：重放 `transition_id` 被拒且 epoch 不变；过期 `expected_epoch` 被拒；
两个并发切换至多一个成功。

复核：场景 `D1_..._D14` 的 D6/D7/D14；`task_state.py` 的 `request_transition`。

### C5. 重启恢复与故障关闭

**命题**：重启后 epoch/阶段/digest 正确恢复且权限未回退；
状态文件损坏 → 进入 `RECOVERY_REQUIRED`，连合法 A 区请求也拒绝。

复核：场景 `D12_D13`；`state_store.py` 的 `load()`（重算 digest 比对）。

**审阅重点**：文件缺失 vs 文件损坏的处理差异是否合理？（作者选择：缺失→按可信配置
冷启动 epoch 0；损坏→失败关闭。）是否存在"删掉状态文件就能降级"的攻击路径？

### C6. 证据脱敏与发布门禁

**命题**：发布前自动脱敏 + 独立扫描，扫描不通过不推送；公开副本哈希按脱敏后内容重算。

复核：
- 代码：`redact_evidence.py`、`check_evidence_safety.py`、`publish_acceptance.py`
- 证据：`evidence/m3` 分支上 `m3_dynamic_policy/manifest.json` 的 `redaction` 块
- 测试：`redaction_check.py`（E1–E10）

**审阅重点**：
- 脱敏器与扫描器是否**真的**使用独立模式集？（若共享，则"扫描通过"是同义反复）
- 是否存在"被判定为二进制 → 原样复制"的静默绕过路径？
  （作者**曾有此缺陷**：64KB 采样截断多字节字符导致 JSON 被原样复制。）
- 发布器的推送前闸门校验的是 **staged diff** 还是 **结果树**？
  （作者**曾因此把 426 个源码文件推上证据分支** —— 请确认现在校验结果树。）

---

## 4. 实测结果（待审阅者核对，而非直接采信）

作者声称全量 **43/43 PASS**：

| 套件 | 场景数 | 结果 |
| --- | --- | --- |
| build + 单元测试 | 199 | PASS |
| A/B 业务场景 | 2 | PASS |
| 负例联调 | 12 | PASS |
| M1 可靠性 R1–R7 | 5 | PASS |
| M1 构建保护 R5,R6 | 2 | PASS |
| M2 SROS 2 S1–S6 | 7 | PASS |
| M3 动态 D1–D15 | 4 组 | PASS |
| 脱敏 E1–E10 | 7 组 | PASS |
| 启动生命周期 | 2 | PASS |

证据入口：
```text
https://github.com/godzwp117/RosSystem/tree/evidence/m3/artifacts/acceptance/published/m3_dynamic_policy
```
包内含 `manifest.json`（含 `status_matrix` 与 `redaction`）、`test_results.json`、
`security_results.json`、`file_hashes.json`、逐场景日志。

**请注意一处刻意保留的失败记录**：`tests/evidence/20261009T142018Z` 是
`start_system` 的 1/2 失败轮次（原因：`ros2 action list` 的 daemon 按 domain 缓存，
M3 用例跑在 domain 43 导致 domain 42 的可发现性断言假失败）。
该日志**保留在磁盘、未删除、未计入证据包**。审阅者若认为这属于"选择性排除"，请直接指出。

---

## 5. 安全模型与信任边界（请重点审查是否被夸大）

| 边界 | 是否成立 | 说明 |
| --- | --- | --- |
| Planner 无法绕过 Gateway 直连执行端 | **成立**（Enforce 下实测 D15） | 仅限本机单容器 + Fast DDS + domain 43 |
| 普通业务节点无法冒充管理员切换任务 | **成立**（D8 实测） | 身份来自 enclave，不来自节点名 |
| 对**本地特权进程**的隔离 | **不成立** | 持有 `/task_admin` 私钥的进程即可行使管理员权限；单容器共享 root |
| digest 防篡改 | **部分** | 只能检测意外变化/内容关联，**不是数字签名**，不能抵御有写权限者 |
| 状态文件与审计日志的原子性 | **不成立** | 两个文件两次写入，提交顺序固定"先状态后审计"，审计缺口需靠日志发现 |

**最需要审阅者警惕的**：不要把"本地单容器内实测通过"读成"具备生产级隔离"。

---

## 6. 作者已声明的未解决项

1. 未确认在途计数**不跨重启**保留（重启前未确认的下游可能仍在运行）
2. 性能对照（M2 静态 vs M3 动态 P50/P95、切换耗时）**NOT_RUN**
3. 跨主机 / 跨 RMW / 跨 DDS 实现**未验证**
4. 未启用证书吊销与轮换
5. `main` 上已有的 M1/M2 历史证据含主机路径 `${WORKSPACE}`（24 文件）——
   **按"不得改写历史标签"的约束刻意未清理**
6. 安全模式下未为 `ros2` CLI 分配运维身份，观测依赖文件证据
7. 状态文件与审计日志无跨文件原子性

---

## 7. 建议审阅者输出的内容

1. **结论分级**：对 C1–C6 每条给出 `成立 / 部分成立 / 不成立 / 无法判定`，并附代码或证据位置
2. **具体缺陷**：文件:行 + 触发条件 + 影响 + 建议修法（区分"必须修"与"可选改进"）
3. **是否夸大的判定**：第 5 节哪些行被高估
4. **下一步开发指令**：按优先级排序，每条含"目标 / 验收判据 / 涉及文件 / 风险"
5. **明确指出作者未覆盖但应当覆盖的攻击路径**

---

## 8. 复现环境（若要跑测试）

| 项 | 值 |
| --- | --- |
| 容器 | `rg_jazzy`（Ubuntu 24.04.5） |
| 镜像 | `ros:jazzy`，ID `sha256:066420e07f60aa18262f2479981def87ebcfcec42eefb0c0c57c4a46098348ca` |
| ROS / RMW | `jazzy` / `rmw_fastrtps_cpp` |
| 安全栈 | `sros2` 0.13.6，OpenSSL 3.0.13 |
| domain | 普通 42 / 安全 43（**刻意隔离**） |

```bash
scripts/setup_sros2.sh                       # 生成 keystore + 6 个 enclave，并独立复核权限
./scripts/run_all.sh                         # build + 单测 + A/B + 负例
docker exec rg_jazzy bash -lc 'cd /ws && source /opt/ros/jazzy/setup.bash && \
    source install/setup.bash && python3 tests/integration/sros2_check.py'      # S1–S6
docker exec rg_jazzy bash -lc 'cd /ws && source /opt/ros/jazzy/setup.bash && \
    source install/setup.bash && python3 tests/integration/dynamic_policy_check.py'  # D1–D15
python3 tests/integration/redaction_check.py # E1–E10
```

**警告：`security/keystore/` 含明文私钥，已被 `.gitignore` 排除，绝不可上传或提交。**
