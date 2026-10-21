# RosSystem 最终三成员工程交付报告（2026-10-22）

> ⚠️ **历史版本提示**：本报告对应受测代码 `0563fe7cc8aab6901bb7a91d6ece3b9cdd960a04`，是**旧固定 SHA 的历史交付记录**，其中的 M3 19 checks 等数字不代表当前封版结果。
> 当前封版请见：`docs/integration/FINAL_SUBMISSION_CLOSEOUT_2026_10_22.md`（受测 `2f3de257c9eac873093201292f6b2a9571da4f03`）。



> 分支：`integration/final-deliverable-2026-10-22`
> 起点：`f258ac1ed59e316c4989279a7968dad3fe4460c8`
> **受测代码 SHA（FINAL_TESTED_CODE_SHA）：`0563fe7cc8aab6901bb7a91d6ece3b9cdd960a04`**
> 证据：`artifacts/integration/final-deliverable-2026-10-22/final-20261020T160207Z-v3/`
> 容器 `rg_final`（ros:jazzy），在线 Domain 74，正式 Enforce 域 42/43

---

## 1. 最终评级

| 等级 | 结论 |
| --- | --- |
| **`FINAL_CONTROLLED_SYSTEM_PASS`** | **通过**（受控系统交付完整验收） |
| `FINAL_THREE_EXTERNAL_INTEGRATION_READY` | **通过**（三真实调用与严格失败关闭） |
| `FINAL_DDS_ENFORCE_READY` | **通过**（正式权限 7/7） |
| **`THREE_REAL_LEVEL3_READY`** | **BLOCKED**（M1 模型无效 + M2 无生产签发者 + 无速率授权基线） |

受控系统交付通过 **不等于** 三真实正向准入。二者必须分开陈述。

## 2. 代码来源

| 模块 | 来源 |
| --- | --- |
| M1 CommRisk | `research/m1-phase6-evaluation-observation`（经 `45e67a2` 继承） |
| M2 IdentityTrust | `research/m2-action-origin-binding`（`a1d6996`，经集成合并继承） |
| M3 TaskRisk | `modules/member3_taskrisk/`（与冻结演示一致） |
| F0 | `scripts/team_demo.py`（含 `4e83f919` P0 修复） |
| Gateway / NavSim | `src/rg_gateway/`、`src/rg_demo_nodes/`（未改） |
| DDS 权限 | `security/policies/minimal_permissions.xml`（未改） |

## 3. 本轮修复的两个脚本缺陷

### 3.1 STACK_READY 假阳性（P0）

旧 `m3_online_extra.sh` 的就绪循环超时后仍打印 `STACK_READY=1` 并继续执行
ON-03/04/06，导致**启动失败被后续场景失败掩盖**，日志却声称已就绪。

现改为：跟踪 READY 标志；超时打印 node 日志尾部、清理、**exit 6**；
并额外要求 Gateway 日志出现 `"policy_loaded": true`，否则 **exit 7**
（在默认策略上跑验收会让 ALLOW/BLOCK 失去意义）。

### 3.2 进程清理（延续上一轮并本轮验证）

`trap EXIT/INT/TERM` + 幂等 cleanup（TERM 进程组 → KILL → wait）+
`check_stray`（只统计本轮存活**非僵尸**进程）+ 残留即非零退出。
本轮验收中 six-scenario 组跑完后 `STACK_READY=1`、无残留。

## 4. 统一执行入口

`scripts/final_system.sh`，五个入口：`--check` / `--mode controlled` /
`--mode three-real-strict` / `--mode enforce` / `--mode acceptance`。

**只编排既有组件，不复制其判定**；不关闭安全、不改 TaskPolicy、不改 F0 严格模式。

## 5. 受控正向在线模式（实测）

M1/M2 MOCK + M3 EXTERNAL，Domain 74：

- 合法任务：F0 READY → Planner 提交 → Gateway **ALLOW** → NavSim **Goal 1**；
- 越界任务：M3 建议允许、F0 放行，**Gateway 依 TaskPolicy 独立 BLOCK**，Goal **0**；
- Gateway 审计 5 行，NavSim journal 1 行。

## 6. 三真实 STRICT 模式（实测）

全部 `mode=external`、`schema_ok=true`：

| 模块 | 状态 |
| --- | --- |
| `comm_risk` | `UNKNOWN` |
| `identity_trust` | `AUTHORIZED`（历史解释） |
| `task_risk` | `ALLOW_RECOMMENDED` |

F0 → `ADAPTER_BLOCK` / `ADAPTER_MODULE_STATUS_NOT_PROCEED`，Planner 未提交。
**这是正确失败关闭，不是故障。**

## 7. M3 在线六场景（实测）

独立验证器复核：**19 checks / 0 failures / PASS**。

ON-01 ALLOW→Goal 1；ON-02/03/04 未提交、Goal 0；
ON-05 Gateway `OUT_OF_REGION` BLOCK、Goal 0；
ON-06 Planner TIMEOUT，其后验状态以本轮原始审计为准（校验器拒绝把超时记为 BLOCK）。

## 8. 正式 DDS Enforce（实测）

S1 普通模式、S2 合法链、S3 Planner 直连被拒、S3C Gateway 正向对照、
S4 未授权被拒、S5 TaskPolicy 越界、S6 不静默降级 —— **7/7 PASS**。
与在线模式**不同域、不同 run**，不得合并陈述。

## 9. 技术限制（必须随交付一起说明）

1. **M1 检测有效性未通过**：合法 1000 Hz 被全线误报（FPR 1.0），
   端点侦察融合后召回 0，纯查询侦察与短命端点在当前传感器下不可观测；
2. **M2 无生产签发者**：对称 HMAC、同 UID、无审批/撤销；
   真实 Action `send_goal` 未捕获（仅 CandidateProto 入口）；
3. **无可信速率授权基线**：`task_policy.yaml` 与 DDS 权限均无速率定义，
   因此"合法高负载"与"洪泛"在观测上不可区分；
4. **三真实 LEVEL 3 未通过**；
5. 正式 Enforce 与普通在线模式是**独立实验**。

## 10. 证据与复验

```bash
cd artifacts/integration/final-deliverable-2026-10-22/final-20261020T160207Z-v3
sha256sum -c SHA256SUMS.txt
```

一键复验：`scripts/final_system.sh --mode acceptance --domain <空闲域>`

## 11. 后续工作

1. 由受信任策略提供速率授权基线（M1 误报的根因）；
2. M2 Action `send_goal` typesupport 接线 + 非对称签发 + 独立 UID；
3. M1 端点增长率等更敏感图特征，或分通道保守融合；
4. 三真实 LEVEL 3 需在上述全部完成后重新评估，不得靠调门槛达成。
