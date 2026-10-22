# 最终包单元测试证据审计（1.1.1-rc1）

> 审计基线：`40fded595afceced4205d2fae9756d6c90f95617`
> 最终包：`RosSystem-CreativeWork-Full-1.1.1-rc1.tar.gz`
> SHA-256：`d69737cf9dbd039a4a0b8a127eb15bb3db55b5514512c119befd46d5e0fe32d2`
> 本文件不修改安全核心、不改包 SHA，只做事实与证据审计。

## 1. 当前 Git 与包

| 项 | 值 |
| --- | --- |
| 分支 | `research/cross-layer-security-v1.1.0` |
| 候选包验收来源提交 | `40fded5` |
| 打包来源提交 | `ca32a6c…`（见包内 `BUILD_INFO.json`；`40fded5` 是之后的验收/文档提交） |
| 完整包 SHA-256 | `d69737cf…`（校验通过） |
| 离线包 SHA-256 | `2fa7892d…`（校验通过） |

## 2. 已记录测试结果（FINAL_PACKAGE_VALIDATION）

```text
passed   = 921
skipped  = 17
failed   = 0
duration = 603.8 s
scope    = SAME_HOST_FRESH_ENV（完整包解压后的新容器）
source   = paper/FINAL_PACKAGE_REPRODUCTION.md
```

该结果是**报告记录值**；原始完整 pytest stdout 不可恢复（见第 4 节）。

## 3. skipped 审计

历史结果记录 17 项 skipped。为了逐项核对，本轮在**新容器**中对同一最终包执行了
一次带 `-rs` 的审计运行，标记为 `NEW_REEXECUTION`；它不是 `rg_last2` 的原始日志。

```text
SKIP_AUDIT_NEW_RUN_NODEIDS = 17
SKIP_AUDIT_NEW_RUN_RESULT  = 921 passed / 17 skipped / 0 failed / 600.79 s（NEW_REEXECUTION，与历史 603.8 s 为不同运行）
SKIP_NODEIDS_RECOVERED     = 17/17（新重跑 + 源码条件）
SKIP_REASONS_RECOVERED     = 17/17（逐项写入 CSV）
```

逐项明细：`paper/FINAL_PACKAGE_SKIPPED_TESTS.csv`（17 行）。

> M2 参数化 nodeid 中的 `/ws/src/...` 是包内运行路径（由 `--collect-only` 确认），
> 不是仓库绝对路径；其余 nodeid 为包内测试函数标识。

| 来源模块 | 数量 | 原因 | 性质 |
| --- | --- | --- | --- |
| `test_on06_report_claims.py` | 15 | 包内无 `artifacts/demo-2026-10-19/...` 在线证据目录 | 旧 M3 在线报告声明检查未执行 |
| `test_m2_witness_guid_safety.py` | 2 | EntityId 序列化条件；无 `three-real-limited` 集成证据 | 源码级 GUID 安全分支/证据检查未执行 |

> 新审计运行在 **sourced** 环境下执行，`test_gateway_audit_safety.py` 的
> `rclpy` import 成功，因此它没有被 skip；这也是历史 17 项与未 sourced 的
> 局部探测（会多出 gateway module skip）之间的差异来源。

原因来源严格区分：

- `ORIGINAL_PYTEST_LOG`：本轮未使用（原始日志不存在）；
- `SOURCE_CODE_ANALYSIS`：从当前最终包源码的 skipif/fixture 条件核对；
- `UNKNOWN`：无法确认的项（如有，必须单独列出）。

## 4. 原始日志可用性

```text
ORIGINAL_FULL_PYTEST_LOG = NOT_RECOVERED
```

原因：完整输出被重定向到已删除容器 `rg_last2` 的 `/tmp/unit.log`；宿主只保留
`tail -3`。追溯过程与来源见 `UNIT_TEST_LOG_RECOVERY_STATUS.md`。

新审计运行日志：`paper/evidence/pytest_1_1_1_rc1_skip_audit_new_run.log`
（`NEW_REEXECUTION`，不是原始日志）。

- 文件大小：3,103 B
- SHA-256：`3498071b28d9f371b3b9027a5d0a58d690c7f786e1b2dd0ff0c153f03656baf3`
- 完整 stdout 与 17 条 `SKIPPED` 明细：**包含**
- 运行：`921 passed, 17 skipped in 600.79s`，`EXIT=0`
- 清单：`paper/evidence/pytest_1_1_1_rc1_log_manifest.json`

## 5. 安全覆盖影响审计

逐项判断见 CSV 的 `effect_on_coverage` 字段。总体分类：

| 类别 | 是否被 skipped 影响 | 依据 |
| --- | --- | --- |
| DDS Security / Enforce | **否** | 最终包 DDS 动态 7/7；DDS 负向 6/6；skip 项为 M3 在线报告声明，不是 DDS 场景 |
| M2 意图身份 | **否（核心链）** | 最终包 M2 动态 17/17；skip 项是 witness 源码级 GUID 安全分支/集成证据条件 |
| Gateway 独立授权 | **否（核心链）** | 最终包 Gateway 动态 14/14；本次 sourced 审计运行未 skip Gateway 模块（`rclpy` 可用） |
| F0 安全决策 | **否（核心链）** | P07/F0 13/13；三真实 L3 BLOCKED 有动态证据 |
| 三真实负向阻断 | **否** | L1/L2 PASS、L3 BLOCKED 为动态运行结果 |
| LEVEL C 成熟度 | **否** | skipped 不提高也不降低成熟度；仍受 M1/Action/生产条件限制 |
| 旧 Demo 在线证据声明 | **是（该模块未执行）** | `test_on06_report_claims.py` 依赖 `artifacts/demo-2026-10-19`，包内未携带 |

关键原则：**不能用其他动态实验的 PASS 把 skipped 改写成 PASS**。上表只说明
“该风险有独立的动态覆盖”，不改变这些测试“未执行”的事实。

## 6. 与其他动态实验的关系

- DDS 7/7、负向 6/6：独立最终包运行；
- M2 17/17、Gateway 14/14：独立最终包运行；
- P07 13/13：CONTROLLED_ISOLATION，M1/M2 为 MOCK；
- P09 10/10：同容器时钟，未发送取消；
- 三真实 L1/L2 PASS、L3 BLOCKED：未用 Mock 替换；
- 这些动态实验不能替代单测中 skipped 的旧 Demo 声明检查。

## 7. 结论状态（分层，不用单一 PASS 掩盖）

```text
FINAL_PACKAGE_TEST_RESULT_RECORDED = PASS
ORIGINAL_PYTEST_LOG_ARCHIVED       = NOT_RECOVERED
ALL_17_SKIP_REASONS_IDENTIFIED     = PASS（17/17 nodeid/reason；来源是新审计运行 + 源码条件，不是原始日志）
SECURITY_SKIP_IMPACT_AUDITED       = PASS（有独立动态覆盖，但不改写 skipped）
PAPER_FACTS_CONSISTENT             = PASS（见 check_paper_facts.py）
```

## 8. 对论文结论的影响

1. 可以写“最终包全量单测 921 passed / 17 skipped / 0 failed，603.8 s”；
2. 必须同时写“原始完整 pytest 日志未归档”；
3. 不得写“17 skipped 全部是无关项”——其中 15 项是 M3 在线报告声明检查确实未执行；
4. 不得写“921 次独立实验”；
5. 不得把 LEVEL C 写成生产级验收通过；
6. 建议在论文脚注中引用 `paper/FINAL_PACKAGE_REPRODUCTION.md` 与
   `paper/UNIT_TEST_LOG_RECOVERY_STATUS.md`。
