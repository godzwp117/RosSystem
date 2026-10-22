# 论文事实表（最终，六小时轮次）

> 基线：`PAPER_FACTS_BASELINE.md`（冻结于 HEAD `488491f`）
> 增量：`PAPER_FACTS_NEW_EXPERIMENTS.md`
> 本表按**证据强度**分类，不按“是否希望论文好看”分类。

> **最终版本归属（2026-10-22 文档收尾）**
>
> ```text
> FINAL_CANDIDATE                 = 1.1.1-rc1
> FINAL_ACCEPTANCE_SOURCE_COMMIT  = 40fded595afceced4205d2fae9756d6c90f95617
> FINAL_FULL_SHA256               = d69737cf9dbd039a4a0b8a127eb15bb3db55b5514512c119befd46d5e0fe32d2
> FINAL_UNIT_TESTS                = 921 passed / 17 skipped / 0 failed / 603.8 s
> FINAL_UNIT_SCOPE                = SAME_HOST_FRESH_ENV（完整包解压后的全量单测）
> ```
>
> `40fded5` 是**候选包验收来源提交**；本文件若在更晚的文档提交中更新，不得把
> 该文档提交冒称为打包源码提交。`921/17` 来自
> `FINAL_PACKAGE_REPRODUCTION.md` 记录的最终包运行；原始完整 pytest 日志
> **未归档**（见 `UNIT_TEST_LOG_RECOVERY_STATUS.md`）。历史 1.1.0 的
> `920/4` 是 `HISTORICAL_BASELINE`，与最终包结果分开记录。

## A. 已动态验证（本轮实际运行）

| 结论 | 数值 | 证据 | 范围 |
| --- | --- | --- | --- |
| DDS 实验室 Enforce | 7/7 | `artifacts/research/v110/sixhour/sixhour-dds-20261022T034500Z/summary.json` | domain 43，临时 CA |
| DDS 负向 | 6/6 | `artifacts/research/v110/sixhour/sixhour-ddsneg-20261022T034800Z/summary.json` | 每项带同栈对照 |
| 三真实 LEVEL1 | PASS | `artifacts/research/v110/sixhour/three-real/summary.json` | 真实 M1/M2/M3 |
| 三真实 LEVEL2 | PASS | 同上 | Schema/关联 |
| 三真实 LEVEL3 | **BLOCKED** | 同上 | M1 UNKNOWN |
| P07 M3 阻断隔离 | 13/13 | `artifacts/research/v110/p07/p07-20261022T024200Z/` | 真实 M3，M1/M2 MOCK |
| P09 Planner 超时 | 10/10 | `artifacts/research/v110/p09/p09-20261022T030000Z/` | 同容器时钟 |
| Web 研究证据 | 200/200/200，18 tests | `artifacts/research/v110/web/` | 归档只读，截图 NOT_RUN |
| F0/Gateway 边界回归 | 49 tests | `artifacts/research/v110/f0_gateway_reverify.log` | STRICT/LAB |
| M2 身份链回归 | 17/17 | `tests/evidence/m2lab-round2-20261022T031500Z/` | 意图主题 |

## B. 已静态验证（代码/配置/契约）

| 结论 | 依据 |
| --- | --- |
| 部署 M1 模型 `validation_gate_passed=false` | `modules/member1_comm/model/comm_risk_model.json` |
| 6 维候选模型依赖 `duration_ms`，未部署 | `comm_risk_window_model.json` + `M1_WINDOW_SHIFT_ROOT_CAUSE.md` |
| LAB 身份默认不被 F0 接受 | `team_demo.py` + `test_f0_lab_scope.py` |
| Gateway 身份门默认关闭且无静默回退 | `security_gateway.py` + `test_gateway_identity_gate.py` |
| P07 隔离配置显式 `CONTROLLED_TEST_ONLY` | `config/team_modules.p07-isolation.yaml` |

## C. 历史基线（HISTORICAL_BASELINE，复用，不冒充最终包）

| 结论 | 数值 | 证据 |
| --- | --- | --- |
| 全量单元回归（1.1.0 基线） | 920 passed / 4 skipped | `acceptance_v110.json` |
| 全量单元回归（六小时重跑） | **920 passed / 4 skipped / 0 failed（591.5 s）** | 本轮容器日志 |
| 原 13 项身份测试 | 56/56 | `test_identity_trust_real_logs.py` |
| M2 意图身份 | 17/17 | `m2_lab_identity_v110` |
| Gateway 双层 | 14/14 | `m2_gateway_identity_v110` |
| 组件重复 | 30/30 + 3/3 | `v110rep-20261021T195500Z` |


## C2. 最终包验证（FINAL_PACKAGE_VALIDATION）

| 结论 | 数值 | 证据 | 口径 |
| --- | --- | --- | --- |
| 最终包全量单测 | **921 passed / 17 skipped / 0 failed / 603.8 s** | `FINAL_PACKAGE_REPRODUCTION.md`；原始日志未归档 | 完整包解压后的新容器；17 skipped 不计入 passed |
| 最终包 DDS Enforce | 7/7 | `artifacts/research/v110/final-package/last-dds-20261022T051500Z/summary.json` | domain 43，TEST_ONLY_LAB |
| 最终包 DDS 负向 | 6/6 | `artifacts/research/v110/final-package/last-ddsneg-20261022T051700Z/summary.json` | 同栈对照 |
| 最终包 M2 意图身份 | 17/17 | `artifacts/research/v110/final-package/last-m2-20261022T052000Z/` | 意图主题，不是 Action |
| 最终包 Gateway | 14/14 | `artifacts/research/v110/final-package/last-gw-20261022T052300Z/` | 文件 side channel |
| 最终包 P07 | 13/13 | `artifacts/research/v110/final-package/last-p07-20261022T052500Z/` | CONTROLLED_ISOLATION |
| 最终包 P09 | 10/10 | `artifacts/research/v110/final-package/last-p09-20261022T052700Z/` | 同容器时钟 |
| 最终包三真实 | L1 PASS / L2 PASS / **L3 BLOCKED** | `artifacts/research/v110/final-package/three-real/summary.json` | M1 UNKNOWN |
| 最终包 Web | 18 passed；HTTP 200 | `artifacts/research/v110/web/summary.json` | ARCHIVED_RESEARCH_EVIDENCE |

> 最终包的 921 项是**单元测试检查项**，不是 921 次独立系统实验；17 个 skipped
> 不进入成功率的分子或分母。17 项 nodeid/reason 由一次 `NEW_REEXECUTION`
> （600.79 s，同一最终包）逐项核对；它不替代历史 603.8 s 的结果。

## D. 仅同宿主复现

- 新压缩包 → 新目录/新容器 → colcon 4/4 → DDS 7/7 → 全量单测 921/17；
- 这是 `SAME_HOST_FRESH_ENV_VERIFIED`，**不是** `THIRD_PARTY_HOST_VERIFIED`。

## E. 实验室验证

- DDS Enforce、M2 意图身份、Gateway 双层均为临时实验室 CA（`TEST_ONLY_LAB`）；
- 不证明生产 CA/HSM/撤销/轮换。

## F. 尚未验证

| 项 | 状态 | 原因 |
| --- | --- | --- |
| M1 受信任 NORMAL | BLOCKED | 数据/模型/观测三者均不足 |
| Action `send_goal` 身份 | NOT_VERIFIED | 原始 DDS reader 破坏服务发现 |
| 三真正向 LEVEL3 | BLOCKED | 依赖 M1 NORMAL |
| P02 真实 M1 SUSPICIOUS | NOT_VERIFIED | 无真实触发样本 |
| 第三方主机复现 | NOT_RUN | 无第二台主机/CI |
| 生产部署 | NOT_RUN | 无生产信任根/运维 |
| 取消确认/迟到取消 | 未验证 | P09 只验证 Planner 超时，不发取消 |

## G. 明确失败 / 负结果

1. 手工 `TopicDataType` 订阅 Action 请求导致 Planner `NO_ACTION_SERVER`（同栈对照 `EXECUTED`）；
2. 500 Hz 消息风暴未被现有 M1 模型检出；
3. 原 P07 用 Gateway `OUT_OF_REGION` 充当 M3 阻断证据，已判定不成立；
4. 仅 12 个正常窗口/1 个异常会话，无法支撑误报率/召回声明。

## H. 论文可用的一句话总结

> 在临时实验室 CA 与固定域条件下，RosSystem 能证明 DDS 访问控制、真实 DDS
> 主体到请求摘要的 Ed25519 绑定（意图主题）以及 F0/Gateway 双层独立阻断；
> 但 M1 受信任 NORMAL 与 Action 级身份仍未实现，因此三真正向与生产级结论
> 均不成立。

## I. 最终状态矩阵（供论文/答辩直接引用）

```text
FINAL_CANDIDATE                  = 1.1.1-rc1
FINAL_ACCEPTANCE_SOURCE_COMMIT   = 40fded595afceced4205d2fae9756d6c90f95617
FINAL_UNIT_TESTS                 = 921 passed / 17 skipped / 0 failed / 603.8 s
ORIGINAL_FULL_PYTEST_LOG         = NOT_RECOVERED
THREE_REAL_LEVEL3                = BLOCKED
M2_ACTION_SEND_GOAL_BINDING      = NOT_VERIFIED
THIRD_PARTY_HOST_REPRODUCED      = NOT_RUN
P07_SCOPE                        = CONTROLLED_ISOLATION
WEB_RESEARCH_EVIDENCE            = ARCHIVED_RESEARCH_EVIDENCE
DDS_CA_SCOPE                     = TEST_ONLY_LAB
FINAL_MATURITY                   = LEVEL_C
```

`LEVEL_C` 不是生产级安全验收通过；`921 passed` 不是 921 次独立系统实验。
