# 受限三真实集成在线收尾（第 9、10 项补齐）

> 起点：`integration/three-real-limited-verification@fdc322338499594b06fd94134a2b458a0742b847`
> 本分支：`integration/three-real-limited-online-closure`
> run_id：`online-20261019T155522Z`
> 环境：容器 `rg_online`，ROS 2 Jazzy，rmw_fastrtps_cpp，Domain 64（在线）/42·43（正式 Enforce）
> 证据：`artifacts/integration/three-real-limited-online/online-20261019T155522Z/`

---

## 1. 本轮要解决什么

上一轮判 `LIMITED_INTEGRATION_CONDITIONAL`，原因是两项 `NOT_RUN`：

* 第 9 项：真实 Planner / SecurityGateway / NavigationSim 下游在线检查；
* 第 10 项：M3 在线 ON-01..ON-06 六场景。

并且旧证据存在**表述过宽**的问题：`scripts/int_limited_verification.py`
用受控 Mock 驱动 F0，却把部分结论写成"三真实模块联合"，
还用 `gateway_submission=null` 推断"Gateway 没收到"。本轮一并纠正。

## 2. 第 10 项：M3 在线六场景 —— NOT_RUN → **PASS**

在**同一次** run（`online-20261019T155522Z`）内分两组执行：

* `scripts/m3_online_drive.sh`：ON-01、ON-02、ON-05（stack-a）
* `scripts/m3_online_extra.sh`：ON-03、ON-04、ON-06（stack-b）

两组各写独立目录，事后按同一 `run_id` 合并到 `m3_online/merged/`，
再用 `scripts/verify_m3_online_evidence.py` 对**合并后的原始审计与 journal** 复核。

```
verdict: PASS    checks: 19    failures: 0
```

逐场景事实（来自审计与 journal，不是报告口径）：

| 场景 | F0 决策 | Planner | Gateway 到达 | Gateway 决策 | NavSim Goal |
| --- | --- | --- | --- | --- | --- |
| ON-01 | `READY_FOR_GATEWAY_SUBMISSION` | `RECEIVED` | 1 | `ALLOW` / `ALLOW_IN_POLICY` | **1** |
| ON-02 | `ADAPTER_BLOCK` | 未提交 | 0 | — | 0 |
| ON-03 | `ADAPTER_BLOCK` | 未提交 | 0 | — | 0 |
| ON-04 | `ADAPTER_BLOCK` | 未提交 | 0 | — | 0 |
| ON-05 | `READY_FOR_GATEWAY_SUBMISSION` | `RECEIVED` | 1 | **`BLOCK` / `OUT_OF_REGION`** | **0** |
| ON-06 | `READY_FOR_GATEWAY_SUBMISSION` | `TIMEOUT` | **0** | — | 0 |

### ON-06 的本轮实测后验状态（必须如实记录）

本轮观测：`PLANNER_RESULT_TIMEOUT`，**Gateway 到达 0、NavSim Goal 0**。
校验器对该场景的判定是"超时未记为 Gateway BLOCK"，即 TIMEOUT 与 BLOCK 被明确区分。
历史上曾出现过 TIMEOUT 但 Gateway 实际到达并 ALLOW 的情况；本轮**没有**出现该情况，
但由于两种结果都可能发生，报告不预设后验状态，只记录本轮观测。

## 3. 第 9 项：真实 ROS 2 下游 —— NOT_RUN → **PASS**

关键设计：**同一次栈生命周期内同时跑负例与正向对照**，
否则"审计 0 行"无法区分"没到达"与"网关没跑/日志坏了"。

运行目录 `downstream_v2/`：

| 环节 | 结果 |
| --- | --- |
| 栈就绪 | `GATEWAY_READY`（`policy_loaded=true`, `downstream_server_available=true`）、`NAVSIM_READY`、`OPERATOR_READY` |
| **NEG**：`config/team_modules.three-real.yaml`（三模块 EXTERNAL） | `ADAPTER_BLOCK` / `ADAPTER_MODULE_STATUS_NOT_PROCEED`，Planner `NOT_SUBMITTED_ADAPTER_BLOCK`，**Gateway 审计 0 行，journal 0 行** |
| **POS**：受控合法请求（M3 真实 + M1/M2 mock） | `READY_FOR_GATEWAY_SUBMISSION`，Planner `RECEIVED`，**Gateway 审计 3 行，journal 1 个 Goal** |

三条真实模块状态（NEG 内，全部 `mode=external`、`schema_ok=true`）：

| 模块 | 状态 | 含义 |
| --- | --- | --- |
| `comm_risk` | **UNKNOWN** | 真实 M1：无有效在线模型证据，扣留 NORMAL |
| `identity_trust` | **UNKNOWN** | 真实 M2：无生产可信当前身份 |
| `task_risk` | `ALLOW_RECOMMENDED` | 真实 M3 规则引擎正常运行 |

**POS 是审计可用性的前提**：它证明在同一栈内 Gateway 审计与 NavSim journal
确实可写可读。因此 NEG 的 0 到达才能归因为"未提交"，而不是"网关没跑"或"日志坏了"。
这正是上一轮缺失的环节。

### 3.1 场景对照表（第 9 项 D01–D06）

| 场景 | 证据来源 | 结果 |
| --- | --- | --- |
| D01 合法正向对照 | `m3_online/merged` ON-01 + `downstream_v2` POS | **PASS**（ALLOW → 1 Goal） |
| D02 Gateway 独立阻断 | ON-05 | **PASS**（M3 允许、F0 放行、Gateway `OUT_OF_REGION` BLOCK、0 Goal） |
| D03 M1 真实 UNKNOWN 阻断 | `downstream_v2` NEG | **PASS**（真实 comm_risk UNKNOWN → F0 BLOCK → 未提交） |
| D04 M2 无可信当前身份 | `downstream_v2` NEG | **PASS**（真实 identity_trust UNKNOWN → 未提交）；标记 `CONTROLLED_PRECONDITION_IDENTITY_NEGATIVE` |
| D05 三真实严格联合阻断 | `downstream_v2` NEG | **PASS**（三 external、schema 合法、同一 request_id、无 Mock） |
| D06 错误与未知状态 | ON-02/03/04 | **PASS**（全部 `ADAPTER_BLOCK`，0 到达、0 Goal） |

> D04 的限定：本轮 M2 的 UNKNOWN 由真实模块在正式配置下产生，
> 但它证明的是"没有可信当前身份时必须阻断"，**不是**"三真实完整正向联调"。

## 4. 第 11 项：正式 DDS Enforce —— 独立复验 **PASS**

第一轮用 Domain 66 运行失败，根因清晰：keystore 内各 enclave 的
permissions 只授权 `<domains><id>43</id></domains>`，换域即被原生拒绝。
这不是缺陷，是**最小权限按域绑定**在生效。

确认 `rg_demo` 已停止（`docker ps` 无该容器）后，在正式域（42 普通 / 43 Enforce）复验：

```
SROS2 SUMMARY (7 passed / 7 total)
  [PASS] S1  普通模式合法 A 区请求
  [PASS] S2  Enforce 合法 A 区：Planner→Gateway→NavigationSim 正常完成
  [PASS] S5  Enforce B 区越界：身份合法但 TaskPolicy 拒绝
  [PASS] S3C 正向对照：/gateway 身份直连执行接口应当成功
  [PASS] S3  Planner 身份直连执行接口应被拒绝
  [PASS] S4  无授权身份访问执行接口应被拒绝
  [PASS] S6  安全配置失效不得静默回退为无认证通信
```

**这是正式 SROS 2 权限的复验**，与研究 keystore 的 `rt/m2/candidate_task` 实验不是同一类证明；
两者在报告中分开陈述。

## 5. 回归

| 项 | 结果 |
| --- | --- |
| 公共契约 | **PASS** |
| F0 P0 身份安全反例 | **38 passed** |
| M2 GUID 越界回归 | **4 passed, 1 skipped** |
| 三真实在线检查 `three_real_online_check.py` | **11 passed** |
| 全仓单元测试（宿主） | **767 passed, 4 skipped, exit 0** |

### 4 个 skipped 的逐项原因（已审查，无安全测试被跳过）

| 测试 | 原因 |
| --- | --- |
| `test_gateway_audit_safety.py:10` | 宿主 venv 无 rclpy |
| `test_interface_contract.py:93` | 宿主无 `rg_interfaces` PYTHONPATH |
| `test_interface_contract.py:141` | 宿主无 `rg_gateway` PYTHONPATH |
| `test_m2_witness_guid_safety.py:50` | 该文件不序列化 EntityId（参数化分支跳过） |

在**容器内**（有 rclpy 与 install 环境）复跑前两类：
`28 passed, 1 failed`，唯一失败为 `test_no_key_material_is_committed`，
原因是容器内 `/ws` 的 git worktree 元数据指向宿主路径不可见 —— 属于运行环境差异，
宿主侧该测试通过。**没有关键安全测试被跳过。**

## 6. 旧脚本证据表述的纠正

`scripts/int_limited_verification.py` 已修改（不放宽任何期望值）：

1. 每个用例新增 `evidence_source`，受控用例一律标记 `ADAPTER_UNIT_ONLY`；
2. 第 8 项改名为"被阻断请求未进入 Planner（适配器层）"，
   并显式声明"不等价于 Gateway 审计中的 0 到达"；
3. 第 12 项标注 `scope_limit`：只证明 F0 重复判定稳定，
   **不**证明 Gateway 的 ALLOW/BLOCK 行为未变；
4. 汇总 `scope_note` 写明本文件不含真实下游/在线/Enforce，
   那些结论见本报告；
5. 旧用例全部保留，作为有价值的 F0 单元回归。

## 7. 结论

| 项 | 上一轮 | 本轮 |
| --- | --- | --- |
| 第 9 项 真实 ROS 2 下游 | NOT_RUN | **PASS** |
| 第 10 项 M3 在线六场景 | NOT_RUN | **PASS** |
| 第 11 项 正式 DDS Enforce | PASS（研究 keystore） | **PASS（正式权限 7/7）** |

**本结论仍不等于三真实模块 LEVEL 3 正向准入。**
M1 的检测有效性仍未证明（`duration_ms` 标签泄漏已撤回上一轮结论），
M2 的生产身份信任根仍未就绪（对称 HMAC、同 UID、Action typesupport 未接线）。
