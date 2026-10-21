# 最终同版本复验报告（P1）

> **唯一受测代码版本（`VERIFIED_CODE_SHA`）**：`4e83f9190596d71f5b887c613d3f509578a9c497`
> 分支：`fix/f0-trust-boundary-closeout`
> Git tree：`525b8b6ed82a2d3036acffe3a5fda83fe0ce79b7`
> 证据目录：`artifacts/integration/f0-trust-closeout/f0close-20261018T082739Z/`
> 契约：`PROPOSED_V1` / `1.0.0-proposed`（未冻结）

**所有下列测试都在同一个 `VERIFIED_CODE_SHA` 上执行，测试时工作树干净**
（`tested_commit.json` 记录 `worktree_clean_excluding_new_evidence=true`）。
之后只新增了文档与证据文件，**未修改任何源码、测试或运行配置**。

---

## 1. 受测版本与环境

| 项 | 值 |
| --- | --- |
| `VERIFIED_CODE_SHA` | `4e83f9190596d71f5b887c613d3f509578a9c497` |
| 运行时的 `git HEAD` | 同上（一致） |
| Git tree | `525b8b6ed82a2d3036acffe3a5fda83fe0ce79b7` |
| 分支 | `fix/f0-trust-boundary-closeout` |
| 基线（修复前） | `integration/three-real-online` @ `e18598d78cbdadd3f2166f0dfcc33293eac0d3c5` |
| RC2 回退标签 | `demo-2026-10-19-rc2-verified` = `33cb4f93d5e5fd268878fe83fc040c655d632a70`（**未移动**） |
| 宿主 | WSL2 Linux x86_64 |
| 宿主解释器 | `<work-f0>/.research-venv/bin/python`（Python 3.10.12，jsonschema 4.26.0） |
| ROS 2 容器 | `rg_f0`（`ros:jazzy`，独立挂载本工作树，**ROS_DOMAIN_ID=55**） |
| ROS_DISTRO / RMW | `jazzy` / `rmw_fastrtps_cpp` |
| 在线域 / 安全模式 | **55 / 普通模式（未启用 DDS-Security）** |
| Enforce 域 / 安全模式 | **43 / enforce** |
| 三真实模块模式 | `comm_risk=external`、`identity_trust=external`、`task_risk=external` |
| 身份信任模式（三真实配置） | **`STRICT`**（默认，失败关闭） |
| 身份信任模式（RC2 演示配置） | `CONTROLLED_TEST_ONLY`（显式） |

> 说明：宿主默认 `python3` 的 jsonschema 版本不足以构造 Draft 2020-12 校验器，
> 因此所有 Python 测试使用上述 venv 解释器；容器内为
> `python3-jsonschema 4.10.3`。未因缺依赖把任何测试记为 PASS。

---

## 2. 各阶段实际命令与结果

| # | 阶段 | 命令 | 返回码 | 结果 | 证据 |
| --- | --- | --- | --- | --- | --- |
| 9.1 | 公共契约 | `python3 scripts/validate_team_contracts.py --all` | 0 | **PASS** | `logs/contracts.log` |
| 9.2 | P0 安全反例 | `pytest tests/unit/test_phase2_security_boundaries.py tests/unit/test_f0_identity_trust_boundary.py -q` | 0 | **PASS（38 passed, 0 xfailed）** | `logs/p0_security.log` |
| 9.3 | 身份与真实模块回归 | `pytest tests/unit/test_identity_current_binding.py tests/unit/test_member1_comm_real.py tests/unit/test_member1_runtime_observation.py tests/unit/test_joint_three_modules.py -q` | 0 | **PASS（60 passed）** | `logs/identity_and_real.log` |
| 9.4 | 三真实联合回归 | `pytest tests/integration/three_real_online_check.py -q` | 0 | **PASS（11 passed）** | `logs/three_real_check.log` |
| 9.5 | 全仓单元测试 | `pytest tests/unit -q` | 0 | **PASS（763 passed, 3 skipped, 0 xfailed）** | `logs/unit_full.log` |
| 10 | 模块级真实验收 | `check_member_module.py --module <m> --config <real> --real-fixture <real>` | 0 | **PASS**（三模块 `meets_pr_gate=True`） | `logs/acceptance_*.log`、`acceptance/<m>/` |
| 11 | 三真实联合运行 | `run_three_real_online.py --config config/team_modules.three-real.yaml` | 0 | LEVEL 1/2 **PASS**，LEVEL 3 **BLOCKED** | `three_real/summary.json` |
| 12 | 真实 M3 在线 | `m3_online_drive.sh` + `m3_online_extra.sh` + `verify_m3_online_evidence.py`（域 55，新 run_id） | 0 | **PASS（6/6，39 检查 0 失败）** | `m3_online/merged/verification.json` |
| 13 | DDS Enforce | `sros2_check.py --run-id f0close-enforce`（域 43） | 0 | **PASS（7/7）** | `dds_enforce/summary.json` |

汇总：**8 PASS / 1 BLOCKED / 0 NOT_RUN / 0 FAIL**（BLOCKED 为 LEVEL 3，属预期真实能力结论）。

---

## 3. 模块级真实验收明细

| 模块 | PASS | FAIL | NOT_RUN | BLOCKED | `meets_pr_gate` |
| --- | --- | --- | --- | --- | --- |
| M1 `comm_risk` | 60 | 3 | 1 | 1 | **True** |
| M2 `identity_trust` | 58 | 3 | 1 | 1 | **True** |
| M3 `task_risk` | 58 | 3 | 1 | 1 | **True** |

**3 条 FAIL 每条都保留可见，未删除、未改写成 PASS。** 它们都是
`STATE-BLOCK` / `STATE-UNKNOWN` / `STATE-ERROR`，即"MOCK 场景开关对不解析该开关的
真实模块不适用"（`mandatory=False`、`gate=False`、
`applicability=NOT_APPLICABLE_REAL_MODULE`）。门槛由 `REAL-STATE-*` 承担。

**必须同时保留的能力限制**：

- **M1**：原 49 维模型与 24 维运行时子集模型的 `validation_gate_passed` **均为 false**；
  已有 `/proc` 主机级采集器但**部分 ROS 2/RTPS 特征仍缺失**；
  **尚未证明具备有效的 ROS 2 在线通信攻击检测能力**。
- **M2**：已有签名核验/签发者判定/绑定/新鲜度/防重放组件，但
  **当前无可信的生产 DDS 身份签发者**；`test_issuer.py` 为 TEST_ONLY，无认证效力。
- **M3**：真实确定性规则引擎，可在线给出 `ALLOW_RECOMMENDED`（该值不是 Gateway 准入）。

`meets_pr_gate=True` **不代表**模型或身份研究目标已完成。

---

## 4. 三真实模块联合运行（LEVEL 结果）

| 等级 | 结果 | 依据 |
| --- | --- | --- |
| `THREE_EXTERNAL_CALLED` | **PASS** | 三个真实进程均执行，`rc=0`，`producer.source=EXTERNAL`，命令不含 `mock_modules` |
| `THREE_EXTERNAL_VALIDATED` | **PASS** | 公共 Schema、`run_id`/`request_id`/`event_id`（唯一、≤128）、任务与资源一致性、严格 JSON 全部通过 |
| `THREE_EXTERNAL_ONLINE_PROCEED` | **BLOCKED** | M1 `UNKNOWN`（门槛未过）、M2 `current_request_identity=UNKNOWN`（无可信当前身份） |

实际模块输出（本轮实测）：

```
comm_risk       UNKNOWN              rc=0  schema_ok=True
identity_trust  AUTHORIZED (historical)  rc=0  schema_ok=True
                current_request_identity = UNKNOWN
task_risk       ALLOW_RECOMMENDED    rc=0  schema_ok=True

F0: ADAPTER_BLOCK / ADAPTER_MODULE_STATUS_NOT_PROCEED
```

### 4.1 附加验证：即使 M1/M3 可推进，伪造身份仍不能 READY

这是 P0 修复的关键验证，见 `tests/unit/test_f0_identity_trust_boundary.py`：

- 用**真实 M1 的受控测试开关**让 M1 给出 `NORMAL`（输出带 `CONTROLLED_TEST_ONLY` 依据）、
  真实 M3 给出 `ALLOW_RECOMMENDED`、真实 M2 给出历史 `AUTHORIZED`，
  三者表面都可推进；同时身份模块伪造 `AUTHENTICATED`+完整 `checks`；
- 结果：F0 **仍然阻断**，`reason_code=ADAPTER_CURRENT_IDENTITY_UNBOUND`
  （`detail_code=ADAPTER_IDENTITY_ATTESTATION_UNVERIFIED`）。

### 4.2 下游声明的范围限定

第 11 阶段是**离线**运行（`run_three_real_online.py` 不启动 ROS 2 下游）。
因此本轮对它的结论只声明为：

- F0 决策为 `ADAPTER_BLOCK`，**未提交 Planner**（来自 F0 自身审计记录）；
- **未**独立观察 Gateway 审计或 NavigationSim journal。

真正的 Gateway/Goal 观察来自第 12 阶段（在线、域 55），见下节。
两者不得混写成"三真实模块经 Gateway 执行"。

---

## 5. 真实 M3 在线回归（ON-01 … ON-06）

域 **55**（普通模式），`run_id = f0close-20261018T082739Z-m3`。
按 `request_id` 关联 Gateway `RosCommEvent` / `DecisionEvent` / `ExecutionEvent`
与 NavigationSim journal。

| 场景 | M3 状态 | 适配层 | Planner | Gateway 到达 | Gateway 决策 | 执行 | Goal |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ON-01 | `ALLOW_RECOMMENDED` | `READY` | `RECEIVED` | 1 | **ALLOW**/`ALLOW_IN_POLICY` | 1 | **1** |
| ON-02 | `BLOCK_RECOMMENDED` | `ADAPTER_BLOCK` | 未启动 | **0** | — | 0 | **0** |
| ON-03 | `UNKNOWN` | `ADAPTER_BLOCK` | 未启动 | **0** | — | 0 | **0** |
| ON-04 | `ERROR` | `ADAPTER_BLOCK` | 未启动 | **0** | — | 0 | **0** |
| ON-05 | `ALLOW_RECOMMENDED` | `READY` | `RECEIVED` | 1 | **BLOCK**/`OUT_OF_REGION` | 0 | **0** |
| ON-06 | `ALLOW_RECOMMENDED` | `READY` | **`PLANNER_RESULT_TIMEOUT`** | **1** | **ALLOW**/`ALLOW_IN_POLICY` | **1** | **1** |

独立复核器：**39 项检查，0 失败**，`claims_checked=true`。

### 5.1 ON-06 不得预设任何下游结果

累计实测（不同 run、同一份代码结构）：

| # | 运行 | Gateway 到达 | 决策 | 执行 | Goal |
| --- | --- | --- | --- | --- | --- |
| 1 | 2026-10-16（RC2，域 42） | **1** | ALLOW | 1 | 1 |
| 2 | B1 阶段一（域 54） | **0** | — | 0 | 0 |
| 3 | B1 阶段二（域 54） | **1** | ALLOW | 1 | 1 |
| 4 | **本轮（域 55）** | **1** | ALLOW | 1 | 1 |

同一份代码、同样的 0.5s 超时窗口，下游结果在 **0 与 1 之间摆动**。
因此本轮 claims 对 ON-06 **只声明不变量**（适配层放行 + Planner 超时），
到达/决策/执行/Goal 全部逐次从本轮日志读取，**未引用旧 run 的证据**。

---

## 6. DDS-Security Enforce 复验

`tests/integration/sros2_check.py --run-id f0close-enforce`，域 **43**：

| 场景 | 结果 |
| --- | --- |
| S1 普通模式合法 A 区请求（域 42，未启用安全） | PASS |
| S2 Enforce 合法请求：Planner→Gateway→NavigationSim | PASS |
| S5 Enforce B 区越界：身份合法但 TaskPolicy 拒绝 | PASS |
| **S3C 正向对照：`/gateway` 直连执行接口成功** | PASS |
| **S3 Enforce：`/planner` 直连 `/rg/nav_execute` 被原生 DDS 拒绝** | PASS |
| **S4 无授权主体访问执行接口被原生 DDS 拒绝** | PASS |
| S6 安全配置失效**不静默回退** | PASS |

**7/7 PASS**。原生拒绝证据保存在 `dds_enforce/S3/rogue_planner.log`、
`dds_enforce/S4/rogue_unauthorized.log`（含 `not found in allow rule` 等 Fast DDS
原生信息），**不是**仅凭客户端 TIMEOUT 推断权限拒绝。

`config/task_policy.yaml` 与 `security/policies/` 在本轮 `git diff` 中 **0 改动**；
keystore 以只读方式挂载，未重建、未覆盖。

### 6.1 与在线实验的关系

**在线（域 55，普通模式）与 Enforce（域 43）是两次独立实验。**
不得宣称"三真实模块在 Enforce 模式下同次完整正向执行"。

---

## 7. 是否全部在同一 SHA 上执行

**是。** 所有 9 个阶段都在 `4e83f9190596d71f5b887c613d3f509578a9c497` 上执行，
测试时工作树干净（除新增证据目录外无改动）。未把多个 SHA 上的成功结果拼接。

复验期间**未发现需要修改源码或安全配置的失败**，因此没有触发"重新固定 SHA 并重跑"
的分支。

---

## 8. 未解决项与 NOT_RUN

| # | 项 | 状态 | 说明 |
| --- | --- | --- | --- |
| 1 | 三真实模块正向联合准入 | **BLOCKED** | M1 模型门槛未过；M2 无可信生产身份签发者 |
| 2 | 三真实 + Enforce 同次运行 | **NOT_RUN** | F0 的 Planner 启动无安全上下文接线；属架构改动，超出本轮范围 |
| 3 | M1 有效在线检测 | **NOT_READY** | 门槛 FAIL + 部分 ROS 2/RTPS 特征缺失 |
| 4 | M2 生产身份签发者 | **NOT_READY** | ROS 2 不暴露发布者主体身份 |
| 5 | PR #6/#7/#8 base 仍为 `main`（应指向 `baseline`） | **BLOCKED_PERMISSION** | 本环境无 GitHub 写凭据 |

**无未解释的安全关键失败。**

---

## 9. 最终验收等级

# `CLOSEOUT_PASS`

依据（逐条对应任务书 §18 的 `CLOSEOUT_PASS` 条件）：

| 条件 | 状态 |
| --- | --- |
| F0 身份自报漏洞无法在严格模式放行 | ✅ 25 类情形全部 BLOCK（含最小复现） |
| 完整 `checks` 伪造无法放行 | ✅ 专测用例 PASS（阻断） |
| 两项原 xfail 转为真正 PASS | ✅ 38 passed，**0 xfailed** |
| 原有系统能力没有回归 | ✅ 763 passed / 0 xfailed；M3 六场景 6/6；Enforce 7/7 |
| 全部要求的测试在同一固定 SHA 上通过 | ✅ `4e83f91`，工作树干净 |
| 证据完整 | ✅ 98 文件，`SHA256SUMS` 97/97 校验通过，**0 密钥文件** |

**同时必须继续写明**：

```
THREE_EXTERNAL_ONLINE_PROCEED = BLOCKED
```

本轮完成的是"F0 不再因伪造身份声明而错误放行"；
**没有**完成"三真实模块可信正向联合准入"，后者仍被真实技术条件阻断。

---

## 10. 是否具备创建 RC3 的条件

**本报告不建议创建 `rc3` 标签。** 理由：

1. RC3 应代表"演示候选"，而演示的核心诉求（真实 M3 在线闭环）**已由 RC2 覆盖**；
2. 本轮产物是**安全修复 + 更严格的失败关闭**，其价值在于"不放行不该放行的请求"，
   而三真实正向链路仍 BLOCKED；
3. 若创建新标签，必须一并说明其与 RC2 的能力差异，否则会造成"能力提升"的误读；
4. 任务书明确"在新版本验收完成之前，继续保留 RC2 为唯一已验证的受控演示回退版本"。

**建议**：保留 RC2 为演示回退版本；本分支作为安全整改分支等待独立审查，
待 M1/M2 具备可信当前证据后再评估 `rc3`。

---

## 11. 证据索引

| 内容 | 路径 |
| --- | --- |
| 证据根 | `artifacts/integration/f0-trust-closeout/f0close-20261018T082739Z/` |
| 受测版本 | `tested_commit.json` |
| 环境 | `environment.json` |
| 全部结果（逐项返回码/日志/计数） | `test_results.json` |
| 安全回归矩阵 | `security_regression.json` |
| 三真实联合 | `three_real/` |
| M3 在线 | `m3_online/`（含 `merged/verification.json`） |
| DDS Enforce | `dds_enforce/` |
| 报告声明 | `report_claims.json` |
| 复核输出 | `verification.json` / `verification.md` |
| 校验清单 | `SHA256SUMS.txt`（97 项） |
| 原始命令日志 | `logs/` |
| P0 说明 | `docs/integration/F0_TRUST_BOUNDARY_CLOSEOUT.md` |
