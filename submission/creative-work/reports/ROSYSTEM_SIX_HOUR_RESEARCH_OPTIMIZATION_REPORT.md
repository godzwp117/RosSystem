# RosSystem 六小时科研强化、实验补全与论文证据冻结报告

> 基线：`research/cross-layer-security-v1.1.0` @ `488491f`
> 1.0.3 冻结：`creative-work-v1.0.3` → `5773fb4`
> 报告日期：2026-10-22
> 最终成熟度：**LEVEL C（保持不变）**
> 论文事实基线：`paper/PAPER_FACTS_BASELINE.md`（冻结，不覆盖）

---

## 1. 本轮执行摘要

本轮没有扩大功能面，而是按“先冻结论文事实、再补关键实验、最后交付”的顺序执行：

1. **阶段 0**：从既有证据生成不可变论文基线（MD/JSON/CSV + changelog）；
   立即发现并冻结 **P07 证据不匹配**勘误。
2. **阶段 1**：用真实 M3 External 隔离实验重做 **P07**（13/13），
   在 1.1.0 上重测 **P09 Planner 超时**（10/10）。
3. **阶段 2**：完成 M1 阻断原因审计；新增**可信意图窗口**证据（count=2、COMPLETE、
   两个认证发送者；缺失账本=UNKNOWN）；保持 `validation_gate_passed=false`。
4. **阶段 3**：完成 **Action send_goal typesupport 探测**（真实负结果：原始 reader
   破坏服务发现）；回归 F0/Gateway 边界（49 tests）；新增 **Web 1.1.0 归档研究证据**展示。
5. **阶段 4/5**：重跑 DDS 7/7 与 6/6、三真实 L1/L2/L3、全量单测；
   打包候选版本并做同宿主新目录复现；生成论文表格、图与最终报告。

## 2. 六小时内真实完成的工程修改

| 类别 | 内容 | 文件 |
| --- | --- | --- |
| 论文基线 | 事实基线、claim-evidence、erratum、changelog | `paper/PAPER_FACTS_BASELINE.*`, `paper/CLAIM_EVIDENCE_MATRIX.csv`, `paper/ERRATUM_P07.md` |
| P07 | 隔离配置 + 驱动 + 真实 M3 实验 | `config/team_modules.p07-isolation.yaml`, `tests/integration/p07_m3_block_isolation.py` |
| P09 | 超时驱动 + 真实 Gateway/NavSim 实验 | `tests/integration/p09_planner_timeout.py` |
| M1 | 可信窗口分析 + findings | `artifacts/research/v110/m1/`, `paper/M1_RESEARCH_FINDINGS.md` |
| M2 | Action typesupport 探测、可复现构建脚本、witness 可选 Action reader | `src/m2_witness/m2_ingress_witness.cpp`, `scripts/build_m2_ingress.sh`, `tests/integration/m2_action_capture_*` |
| Web | 只读 `/api/research` + 研究证据面板 + 测试 | `submission/creative-work/dashboard/*`, `dashboard/research_evidence.json` |
| 论文材料 | 事实表、CSV、统计、贡献、局限、6 图 | `paper/*` |

没有修改任何历史证据；没有删除测试；没有把 `validation_gate_passed` 改为 true。

## 3. 1.1.0 基线对比（只列真实事实）

| 项 | 1.1.0 基线 | 六小时轮次 | 说明 |
| --- | --- | --- | --- |
| 全量单测 | 920 passed / 4 skipped | **920 passed / 4 skipped（源码）/ 921 passed / 17 skipped（最终包，603.8 s）** | 两处环境分别重跑 |
| DDS Enforce | 7/7 | **7/7（重跑）** | 新 run `sixhour-dds-20261022T034500Z` |
| DDS 负向 | 6/6 | **6/6（重跑）** | 新 run `sixhour-ddsneg-20261022T034800Z` |
| M2 身份链 | 17/17 | 17/17（回归） | 意图主题；默认 witness 路径 |
| Gateway | 14/14 | 49 项 F0/Gateway 单测通过 | 不再重复启动 4 场景 |
| 组件重复 | 30/30 | 30/30（原始延迟样本重采） | 组件级 |
| 三真实 L1/L2 | PASS/PASS | **PASS/PASS** | 新 run `sixhour-three-20261022T035000Z` |
| 三真实 L3 | BLOCKED | **BLOCKED** | M1 UNKNOWN |
| P07 | PASS（证据不匹配） | **PASS（隔离，13/13）** | 原证据作废 |
| P09 | NOT_RUN | **PASS（10/10）** | 新实验 |
| Web 1.1.0 证据 | NOT_RUN | **PASS（归档展示）** | 截图 NOT_RUN |
| Action 级身份 | NOT_VERIFIED | **BLOCKED/NOT_VERIFIED** | 负结果 |
| 严格 acceptance | INCOMPLETE | **INCOMPLETE** | LEVEL3/P01/P02/第三方仍未完成 |

## 4. 新增实验与原始数据

### 4.1 P07 隔离实验

- run：`p07-20261022T024200Z`，13/13；
- 真实 M3 External + 只读 tight policy `[0,1]²`，目标 (2.0,2.0)；
- 实测：M3 `BLOCK_RECOMMENDED` / `OUT_OF_REGION`；F0
  `ADAPTER_BLOCK` / `ADAPTER_MODULE_STATUS_NOT_PROCEED`，detail 指向 `task_risk`；
  Planner `submitted=false`；Gateway/NavigationSim 未启动，0 Goal。
- 证据：`artifacts/research/v110/p07/p07-20261022T024200Z/`。

### 4.2 P09 超时重测

- run：`p09-20261022T030000Z`，10/10；
- Planner result timeout 1 s，实际 1.573 s 后退出 `RESULT_TIMEOUT`（exit 2）；
- Gateway 1 次到达、DecisionEvent `ALLOW_IN_POLICY`；
- NavigationSim Goal 1；ExecutionEvent `EXECUTED`，`finished_at=02:37:47.665Z`，
  晚于 Planner 退出；
- 没有发送 cancel；同一容器时钟。
- 证据：`artifacts/research/v110/p09/p09-20261022T030000Z/`。

### 4.3 M1 可信意图窗口

- 来源：M2 真实链账本 `v110m2lab-20261021T184500Z`；
- 窗口 `17:33:34–17:33:54Z`：`send_goal_count=2`、`coverage=COMPLETE`、
  `authenticated_senders=[/CN=\/planner, /CN=\/operator]`、unauthenticated=0；
- 缺失账本：`count=null`、`coverage=UNKNOWN`（不是 0）。
- 证据：`artifacts/research/v110/m1/trusted_window_from_m2.json`。

### 4.4 Action send_goal 探测（负结果）

- typesupport 存在：`rg_interfaces::action`，`PatrolNavigate_SendGoal_Request`，结构 176 B；
- 原始 `TopicDataType` reader 创建成功（`action_reader_ready`），但 Planner 变为
  `NO_ACTION_SERVER`；同一栈去掉该 reader 得到 `EXECUTED`（正向对照）。
- 结论：Action 级身份 **NOT_VERIFIED**；不得把意图主题 17/17 写成 Action 绑定。
- 证据：`artifacts/research/v110/m2-action-probe/summary.json`。

### 4.5 Web 研究证据

- `/api/research` 200、`/` 200、`/api/health` 200；页面含「1.1.0 研究证据」面板；
- `ARCHIVED_RESEARCH_EVIDENCE`、`online_evidence=false`；18 项 dashboard 测试通过；
- 无无头浏览器，截图 NOT_RUN。
- 证据：`artifacts/research/v110/web/`。

## 5. P01–P12 结果修正

| 场景 | 旧状态 | 新状态 | 依据 |
| --- | --- | --- | --- |
| P07 | PASS（错证据） | **PASS（隔离）** | 真实 M3 13/13；Gateway 证据不再充当 |
| P09 | NOT_RUN | **PASS** | 超时重测 10/10 |
| P01 | BLOCKED | BLOCKED | M1 无 NORMAL |
| P02 | NOT_VERIFIED | NOT_VERIFIED | 无真实 M1 SUSPICIOUS |
| 其他 | — | 不变 | 见 `p01_p12_matrix.json` |

更新后汇总：**PASS 10、BLOCKED 1、NOT_VERIFIED 1、NOT_RUN 0**。
（P07 的 PASS 是受控隔离，不是三真实。）

## 6. M1 最新研究结果

- 部署模型 `validation_gate_passed=false`；
- 候选 6 维模型未部署，`duration_ms` 与标签强相关；
- 真实正常 12 窗口/异常 1 会话；500 Hz 风暴未被检出；phase6
  `worst_session_fpr=1.0`、`endpoint-recon recall=0.0`；
- 新增可信意图窗口只解决“意图主题观测”，不解决 Action 级观测；
- **结论：blocker 是模型验证与可信观测双重不足**；LEVEL3 保持 BLOCKED。

## 7. M2 当前身份能力边界

- 意图主题：Ed25519 + 公钥指纹 + 请求摘要 + 原子 nonce，17/17；
- 默认 F0 拒绝 `AUTHENTICATED_LAB`；显式 opt-in 才接受；
- Action send_goal：类型探测成功但原始 reader 破坏服务发现，**未验证**；
- Gateway 证据经文件 side channel，不是 Action 协议字段；
- 实验室 CA，不是生产 CA/HSM。

## 8. DDS Enforce 回归

六小时轮次重跑：

- `sixhour-dds-20261022T034500Z`：**7/7**；
- `sixhour-ddsneg-20261022T034800Z`：**6/6**（N1/N2/N5/N4/N3/N0）；
- 证据归档：`artifacts/research/v110/sixhour/`；
- 结论仍限定为实验室 Enforce，不是生产部署。

## 9. Gateway 独立授权

本轮未重复完整 14 场景，而是回归 F0/Gateway 边界测试 49 项（通过），
并保留 1.1.0 的 14/14 归档证据。关键结论不变：

- G1 身份+策略 ALLOW → 1 Goal；
- G2/G3 身份拒绝 → 0 Goal；
- G4 身份 ALLOW + TaskPolicy `OUT_OF_REGION` → 0 Goal；
- F0 READY 不等于 Gateway ALLOW。

## 10. 三真实正向与负向

六小时轮次 `sixhour-three-20261022T035000Z`：

| 等级 | 结果 |
| --- | --- |
| LEVEL1 | PASS |
| LEVEL2 | PASS |
| LEVEL3 | **BLOCKED** |

阻断原因：M1 `UNKNOWN`；M2 当前身份 `UNKNOWN`；F0 `ADAPTER_BLOCK`。
没有 Mock 替换，没有历史 AUTHORIZATION 复用。P07/P09 的 PASS 不改变该结论。

## 11. 超时与执行语义

P09 证明：

```text
Planner RESULT_TIMEOUT  ≠  Gateway 未收到
                        ≠  Gateway BLOCK
                        ≠  未执行
                        ≠  已取消
```

本次执行在 Planner 退出后完成；没有发送取消，因此“取消确认/迟到取消”仍未验证。
时钟为同一容器墙钟，不声明跨主机严格因果。

## 12. Web 展示验证

- 新增只读端点与面板，展示 DDS 7/6、M2 17、Gateway 14、三真实 L1/L2/L3、
  M1 gate、P07/P09、acceptance；
- 固定 `ARCHIVED_RESEARCH_EVIDENCE`，不冒充在线；
- 18 项 dashboard 测试通过；HTTP 200/200/200；
- 截图 NOT_RUN（无浏览器）；保留了 HTML/JSON/日志与哈希。

## 13. 最终发布包复现

候选版本：**1.1.1-rc1**（不覆盖 1.1.0 包）。

### 13.1 最终候选包

| 项 | 值 |
| --- | --- |
| 完整包 | `RosSystem-CreativeWork-Full-1.1.1-rc1.tar.gz`（2,453,717 B） |
| 完整包 SHA-256 | `d69737cf9dbd039a4a0b8a127eb15bb3db55b5514512c119befd46d5e0fe32d2` |
| 离线包 | `RosSystem-creative-work-1.1.1-rc1.tar.gz`（110,269 B） |
| 离线包 SHA-256 | `2fa7892deee52c079a76b51064acf7357f7b4bd7d655b3ab04d5081efa00a2b9` |
| 构建时源码提交 | 见包内 `runtime/BUILD_INFO.json`；构建时 tracked worktree 干净 |
| 解压/密钥扫描 | 两包 sha256 OK；无 `.pem/.key/.p7s` |
| colcon（最终 sha） | 4/4，0 失败 |
| DDS Enforce（最终 sha） | **7/7 PASS** |
| 全量单测（最终 sha） | **921 passed / 17 skipped / 0 failed（603.8 s）** |
| 最终 sha 包上的负向/身份/网关/P07/P09/三真实/Web | DDS 负向 6/6、M2 17/17、Gateway 14/14、P07 13/13、P09 10/10、三真实 L1/L2 PASS、L3 BLOCKED、Web 18 passed |

**注意**：以上结果均在最终 sha 包上重跑。`tests/unit` 在包内跳过 17 项
（依赖仓库未归档的 demo 证据/外部条件），pytest 明确列出 skipped，未计为 PASS。

详细记录：`paper/FINAL_PACKAGE_REPRODUCTION.md`。

## 14. 性能、统计与重复性

- 组件 30/30 正向、3/3 负向；
- 原始延迟（30 样本）：issue p50 0.559 ms、verify p50 1.400 ms、
  Gateway p50 1.466 ms；p99 分别 0.783/1.699/1.736 ms；
- 这是组件级，不是端到端；未测 CPU/内存分布；
- Wilson 95% 下界：DDS 7/7=0.646，M2 17/17=0.816，Gateway 14/14=0.785，
  组件 30/30=0.886；
- 详细见 `paper/STATISTICAL_ANALYSIS.md`。

## 15. 安全边界未降低的证据

| 边界 | 证据 |
| --- | --- |
| F0 默认拒绝 LAB 身份 | `test_f0_lab_scope.py` |
| Gateway 身份门默认关闭、启用后无静默回退 | `test_gateway_identity_gate.py` |
| M1 gate 仍为 false | `comm_risk_model.json` |
| 三真实 LEVEL3 仍 BLOCKED | `sixhour/three-real/summary.json` |
| P07 不再用错证据 | `ERRATUM_P07.md` + 隔离实验 |
| DDS 负向仍 6/6 | `sixhour-ddsneg...` |
| 未删除旧测试 | 全量单测 920 passed / 4 skipped |

## 16. 仍未完成

1. M1 受信任 NORMAL（数据/模型/观测）；
2. Action `send_goal` 请求级身份；
3. P02 真实 M1 SUSPICIOUS；
4. 取消确认/迟到取消；
5. 第三方主机/CI 复现；
6. 生产 CA/HSM/撤销/轮换；
7. Web 截图与视觉回归；
8. 实体机器人验证。

## 17. 对论文结论的影响

- 可新增：P07 隔离（真实 M3）、P09 超时语义、M1 双重阻断解释、
  Action 负结果、Web 归档展示；
- 不得新增：Action 级身份成功、M1 生产 IDS、三真正向、生产级安全；
- 原 P07 PASS 必须按 erratum 更正；
- 统计描述必须带样本单位和 Wilson 区间。

## 18. 最终验收矩阵

```text
BASELINE_FACTS_FROZEN           = PASS
P07_EVIDENCE_CORRECTED          = PASS
P09_TIMEOUT_RETESTED            = PASS
M1_DATA_QUALITY_IMPROVED        = NOT_RUN
M1_VALIDATION_GATE              = FALSE
M2_ACTION_SEND_GOAL_BINDING     = NOT_VERIFIED
DDS_LAB_ENFORCE                 = PASS
DDS_LAB_NEGATIVE                = PASS
M2_IDENTITY_LAB                 = PASS
GATEWAY_DOUBLE_LAYER            = PASS
THREE_REAL_LEVEL1               = PASS
THREE_REAL_LEVEL2               = PASS
THREE_REAL_LEVEL3               = BLOCKED
CONTROLLED_REGRESSION           = PASS
WEB_RESEARCH_EVIDENCE           = PASS
LATEST_ARCHIVE_REPRODUCED       = PASS（SAME_HOST_FRESH_ENV）
THIRD_PARTY_HOST_REPRODUCED     = NOT_RUN
PAPER_TABLES_COMPLETE           = PASS
PAPER_FIGURES_COMPLETE          = PASS
FINAL_REPORT_COMPLETE           = PASS
SECURITY_BOUNDARY_PRESERVED     = PASS
FINAL_MATURITY                  = LEVEL_C
```

**结论：本轮没有把 LEVEL C 提升为 B/D/E。**
三真正向仍被 M1 阻断，Action 级身份仍为负结果，生产条件仍不具备。
