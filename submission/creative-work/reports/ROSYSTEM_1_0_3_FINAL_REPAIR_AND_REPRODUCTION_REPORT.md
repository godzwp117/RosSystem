# RosSystem 1.0.3 最终修正、独立复现与正式冻结报告

- 报告文件：submission/creative-work/reports/ROSYSTEM_1_0_3_FINAL_REPAIR_AND_REPRODUCTION_REPORT.md
- 角色：首席 ROS 2 集成工程师 / 软件质量审计工程师 / 发布工程师 / 独立验收负责人
- 实际执行时间：2026-10-21 23:59 – 2026-10-22 00:20 (+08:00)
- 工程工作区：/home/zhangwei/project/RosSystem_test/repair/repo
- 独立验收区：/home/zhangwei/project/RosSystem_test/verify_1.0.3
- 依据：ROSYSTEM_REPAIR_AND_REPRODUCTION_REPORT.md（1.0.2）、本轮任务书

---

## 第一章 执行摘要

### 1.1 修正目标

1.0.2 的严格 acceptance 存在一个语义缺陷：DDS Enforce 因缺少合法凭据返回
`NOT_RUN` 时，没有任何失败标志被置位，于是可能出现

    ENFORCE=NOT_RUN
    ACCEPTANCE=PASS
    exit_code=0

即"没有执行的项目"被算成了"通过的项目"。本轮的唯一功能性目标就是消除这种可能，
并建立统一、可机读、可回归的状态判定体系。

### 1.2 实际完成情况

| 工作 | 状态 |
|---|---|
| 建立 1.0.3 分支 | 完成（release/creative-work-v1.0.3-final，基于 b1eb082） |
| 修复 acceptance 汇总语义 | 完成（新增 scripts/acceptance_status.py，统一状态机） |
| 统一退出码 | 完成（0 PASS / 1 FAIL / 9 INCOMPLETE 或 NOT_RUN / 8 PREFLIGHT_FAIL） |
| 结果输出统一 | 完成（summary.txt 增加 NOT_RUN_ITEMS；tested_commit.json 记录真实结果） |
| 控制台状态显示 | 完成（exit 9 → INCOMPLETE，不再是 DONE/FAIL） |
| 顺带修复容器残留 | 完成（停止早于容器创建时不再残留 Created 容器） |
| 状态语义回归测试 | 完成（单元 18 例 + CLI 5 例 + 编排接线 6 例） |
| 生成 1.0.3 发布包 | 完成（完整包 + 离线包 + sha256 + manifest） |
| 从压缩包独立复现 | 完成（全流程，见第七至十二章） |
| 正式报告 | 本文件 |

### 1.3 最终发布状态

- 修复提交：bcbec1bfc6b0ac26db447975b41fcda762934ec9
- 发布提交：332732e341db7b0f6e815863a7f6d62dc21a823d
- 完整包：RosSystem-CreativeWork-Full-1.0.3.tar.gz，1765195 B，
  SHA-256 42e0d21d098297806812f13dd6e75a87cded950dcd4ae3021e1b59ce2aa01022
- 离线包：RosSystem-creative-work-1.0.3.tar.gz，33202 B，
  SHA-256 36f8954caa80b4e44bf157ee9776f7edaf80fb0347f0cdd5db7adae092a2d7bb

### 1.4 是否满足第三方独立复现条件

**满足。** 仅使用 1.0.3 完整压缩包、其 .sha256、包内 Dockerfile 与 README，
在一个全新的空目录中完成了：校验 → 解压 → 镜像构建 → 全新 colcon 构建 →
自检 → 受控在线（40/0）→ 三真实负向 → Enforce 条件判定 → 验收语义回归 →
控制台在线运行与新证据展示 → 回放 → 边界 → 清理。全过程未使用开发工作树的
build/install、未复制任何缺失文件、未复用旧容器。

### 1.5 尚未完成的验收项目

- DDS Enforce：NOT_RUN（公开包不含 SROS 2 私钥/keystore）——不是 PASS。
- 三真实 LEVEL 3 正向准入：BLOCKED（M1 UNKNOWN、M2 无授权凭据）。
- 严格 acceptance（发布包内）：PREFLIGHT_FAIL（无 .git 的 40 位 SHA）。
- 严格 acceptance（源仓库内）：整体 FAIL，原因是 13 个身份类单测实际执行后断言失败
  （缺少 permissions.xml），另有更早的 49 例已通过补齐检出范围消除。

---

## 第二章 版本与来源

| 名称 | SHA | 含义 |
|---|---|---|
| 作品包原始归档 | e69325d8094e1d2bc309772650ae85a241751b31 | 1.0.1/1.0.2 的打包基线 |
| 历史受测安全核心 | 2f3de257c9eac873093201292f6b2a9571da4f03 | 历史证据所对应的核心；**不是**本次代码 |
| 1.0.2 修复基线 | b1eb082dcb02a28dc97805ddd9ea912871ff16a8 | 本轮分支起点 |
| **1.0.3 修复提交** | **bcbec1bfc6b0ac26db447975b41fcda762934ec9** | 11 文件，+575/−24 |
| **1.0.3 发布提交** | **332732e341db7b0f6e815863a7f6d62dc21a823d** | 追加 1.0.3 两包与校验 |
| **最终冻结 Tag** | creative-work-v1.0.3 | 指向包含本报告的提交（见第十六章） |

- 分支：release/creative-work-v1.0.3-final（未改动 main 与封版提交）
- 打包内 BUILD_INFO.json：artifact_commit=bcbec1b…，baseline_core_sha=2f3de257…，
  archive_baseline_sha=e69325d…，source_tree_dirty_entries=0
- 压缩包 SHA-256 与 Git SHA 是两类不同标识：前者标识文件字节，
  后者标识源码提交，报告中不混用。

### 2.1 实际测试环境

| 项 | 实际值 |
|---|---|
| OS | Ubuntu 22.04.5 LTS（WSL2） |
| Docker | 29.7.2 |
| 宿主 ROS 2 / colcon | 未安装（所有 ROS 执行在容器内） |
| 容器镜像 | rosystem-verify-1.0.3，digest sha256:ad4e6d2703b72c6fe09470e191edd569f6470077ddedde7ae41c8e7fc356fa75 |
| 容器内 ROS / Python / colcon / jsonschema | Jazzy / 3.12.3 / 有 / 4.10.3 |
| RMW | rmw_fastrtps_cpp |
| ROS_DOMAIN_ID | 144（CLI 实验）/ 145（控制台） |
| 浏览器 | Playwright 1.49.1 + Chromium 131 |

---

## 第三章 问题根因与修复

### 3.1 根因

1.0.2 的 acceptance 分支用一个整数 rc_all 汇总：

    run_host_tests || rc_all=1
    run_three_real || rc_all=1
    run_controlled || rc_all=1
    run_m3_six     || rc_all=1
    run_enforce; rc_e=$?
    if rc_e == 9 -> mark ENFORCE NOT_RUN        # 不置位 rc_all
    mark ACCEPTANCE "$([ rc_all -eq 0 ] && echo PASS || echo FAIL)"

当唯一的异常是"Enforce 没跑"时，rc_all 仍为 0，于是 ACCEPTANCE=PASS 且 exit 0。
状态字符串（NOT_RUN）、进程返回码（0）与实验语义（未执行）被混为一谈。

### 3.2 修改前 / 修改后

| 场景 | 1.0.2 行为 | 1.0.3 行为 |
|---|---|---|
| 全部执行且通过 | PASS / 0 | PASS / 0 |
| 仅 Enforce NOT_RUN | **PASS / 0（错误）** | **INCOMPLETE / 9** |
| 某必需项 FAIL | FAIL / 1 | FAIL / 1 |
| FAIL + NOT_RUN | FAIL / 1 | FAIL / 1，且 NOT_RUN_ITEMS 保留 |
| 预检失败 | PREFLIGHT_FAIL / 8 | PREFLIGHT_FAIL / 8 |
| 一项都未执行 | 可能 PASS | INCOMPLETE / 9 |

### 3.3 实现方式

- 新增 scripts/acceptance_status.py：纯函数 aggregate() + CLI，成为唯一事实来源。
  任一 FAIL → FAIL；否则任一 NOT_RUN → INCOMPLETE；否则非空全 PASS → PASS；
  空集合 → INCOMPLETE。
- final_system.sh：五类必需项（HOST_TESTS / THREE_REAL / CONTROLLED / M3_SIX /
  ENFORCE）各自 record_item，整体结论由聚合器输出，shell 不再推断。
- summary.txt 增加 `NOT_RUN_ITEMS=…`；tested_commit.json 的 result 记录
  PASS / FAIL / INCOMPLETE / NOT_RUN / PREFLIGHT_FAIL。

---

## 第四章 修改文件审计

| 文件 | 修改原因 | 实现 | 对安全边界的影响 |
|---|---|---|---|
| scripts/acceptance_status.py（新增） | 汇总语义无单一来源 | 纯函数聚合 + CLI + 校验 | 无（只读状态，不做安全判断） |
| scripts/final_system.sh | NOT_RUN 被计入 PASS | 逐项 record_item + 调用聚合器 + NOT_RUN_ITEMS | 无（编排层，不改任何实验判定） |
| dashboard/run_controller.py | exit 9 无法区分；停止时残留容器 | INCOMPLETE 映射；rm -f + 退出后重试确认 | 无（仅进程/容器生命周期） |
| dashboard/static/app.js | INCOMPLETE 无显示分支 | 新增 INCOMPLETE 徽标与提示 | 无（纯展示） |
| package.sh / package_full.sh | 版本默认值 | 1.0.2 → 1.0.3 | 无 |
| tests/unit/test_acceptance_status.py（新增） | 5.1–5.4 回归 | 14 例 | 无 |
| tests/unit/test_run_controller_status.py（新增） | exit 码映射回归 | 4 例 | 无 |
| tests/integration/acceptance_semantics_check.sh（新增） | CLI 级回归 | 5 例 | 无 |
| tests/integration/acceptance_wiring_check.sh（新增） | 编排接线回归 | 6 例（stub 实验体） | 无 |
| tests/integration/_make_acceptance_stub.py（新增） | 生成 stub 变体 | 仅替换函数体 | 无 |
| submission/creative-work/dist/README.md | 1.0.3 说明与哈希 | 文档 | 无 |

关键 diff：repair/artifacts/fix_1.0.3.diff（由 git diff b1eb082..bcbec1b 生成）。
未修改：F0（team_demo.py）、TaskPolicy、M1/M2/M3 算法、DDS 权限、Action 接口、
NavigationSim（见第十四章逐文件核对）。

---

## 第五章 验收状态语义

### 5.1 定义

| 状态 | 含义 | 适用层级 |
|---|---|---|
| PASS | 该项实际执行，且满足对应通过条件 | 单项 / 整体 |
| FAIL | 该项实际执行后失败，或出现契约违反/实验异常 | 单项 / 整体 |
| NOT_RUN | 该项因缺少合法凭据、必要环境或其他前置条件而未执行 | **仅单项** |
| INCOMPLETE | 无 FAIL，但至少一个必需项 NOT_RUN（或未执行任何项） | **仅整体** |
| PREFLIGHT_FAIL | 严格预检失败，后续项目未执行 | 整体 |
| BLOCKED | 单项安全结论：按设计拒绝推进（如 LEVEL3） | 单项（三真实分层） |
| NOT_SUPPORTED | 该环境/包形态不支持该验收（如发布包内无 .git） | 整体条件 |

### 5.2 状态转换矩阵（整体）

| HOST_TESTS | THREE_REAL | CONTROLLED | M3_SIX | ENFORCE | 整体 | 退出码 |
|---|---|---|---|---|---|---|
| PASS | PASS | PASS | PASS | PASS | PASS | 0 |
| PASS | PASS | PASS | PASS | NOT_RUN | INCOMPLETE | 9 |
| PASS | PASS | FAIL | PASS | PASS | FAIL | 1 |
| PASS | FAIL | PASS | PASS | NOT_RUN | FAIL | 1 |
| NOT_RUN | PASS | PASS | PASS | PASS | INCOMPLETE | 9 |
| （空集） | — | — | — | — | INCOMPLETE | 9 |
| 预检失败 | — | — | — | — | PREFLIGHT_FAIL | 8 |

规则：FAIL 优先级最高；NOT_RUN 次之（→INCOMPLETE）；只有全部 PASS 才是 PASS。

---

## 第六章 状态语义回归测试

### 6.1 单元测试（tests/unit/test_acceptance_status.py，14 例）

| 用例 | 输入 | 预期 | 实际 |
|---|---|---|---|
| all_pass_is_pass | 5 项全 PASS | PASS / 0 | 通过 |
| enforce_not_run_is_incomplete_not_pass | ENFORCE=NOT_RUN，其余 PASS | INCOMPLETE / 9 | 通过 |
| not_run_never_returns_zero | 逐项置 NOT_RUN（5 次） | 均 INCOMPLETE / 9 | 通过 |
| any_fail_is_fail | CONTROLLED=FAIL | FAIL / 1 | 通过 |
| fail_and_not_run_is_fail_and_keeps_not_run | THREE_REAL=FAIL + ENFORCE=NOT_RUN | FAIL / 1，且 not_run=['ENFORCE'] | 通过 |
| empty_is_not_pass | 空集合 | INCOMPLETE / 9 | 通过 |
| unknown_status_rejected | X=MAYBE | ValueError | 通过 |
| duplicate_item_rejected | X=PASS,X=FAIL | ValueError | 通过 |
| malformed_item_rejected | NOEQUALS | ValueError | 通过 |
| cli_line_and_exit_incomplete | CLI 5 项 | "INCOMPLETE 9 ENFORCE -" / 9 | 通过 |
| cli_exit_pass / cli_exit_fail | CLI | 0 / 1 | 通过 |
| cli_json_mode | --json | acceptance=INCOMPLETE | 通过 |
| cli_bad_status_exit_2 | X=NOPE | 2 | 通过 |

合计 **14 passed**（容器内 pytest，日志 reports/evidence-1.0.3/logs/04_semantics.log）。

### 6.2 控制台退出码映射（tests/unit/test_run_controller_status.py，4 例）

| exit | 预期状态 | 实际 |
|---|---|---|
| 0 | DONE | 通过 |
| 9 | INCOMPLETE（不是 DONE） | 通过 |
| 1 | FAIL | 通过 |
| 4 | FAIL | 通过 |

合计 **4 passed**。

### 6.3 CLI 级语义（tests/integration/acceptance_semantics_check.sh，5 例）

| 用例 | 预期 | 实际 |
|---|---|---|
| all-pass | PASS 0 | 通过 |
| enforce-not-run | INCOMPLETE 9 ENFORCE | 通过 |
| controlled-fail | FAIL 1 | 通过 |
| fail-and-not-run | FAIL 1 ENFORCE THREE_REAL | 通过 |
| empty | INCOMPLETE 9 | 通过 |

**5 passed / 5**，ACCEPTANCE_SEMANTICS=PASS。

### 6.4 编排接线（tests/integration/acceptance_wiring_check.sh，6 例）

做法：复制 final_system.sh，**只**把五个实验函数体替换为固定返回值
（check_env 也固定返回 0），验收块一行不改。声明：本测试验证编排逻辑，
不代表任何真实实验已执行。

| 用例 | 注入 | 预期 | 实际 |
|---|---|---|---|
| all_pass | 全 0 | ACCEPTANCE=PASS / 0 | 通过 |
| enforce_notrun | ENFORCE=9，其余 0 | ACCEPTANCE=INCOMPLETE / 9 | 通过 |
| controlled_fail | CONTROLLED=1 | ACCEPTANCE=FAIL / 1 | 通过 |
| fail_and_notrun | THREE_REAL=1, ENFORCE=9 | ACCEPTANCE=FAIL / 1 且保留 NOT_RUN_ITEMS=ENFORCE | 通过 |
| three_notrun | THREE_REAL=9, ENFORCE=9 | ACCEPTANCE=INCOMPLETE / 9 | 通过 |

**6 passed / 6**，ACCEPTANCE_WIRING=PASS。

### 6.5 预检失败（5.5，真实执行）

在发布包内执行 `--mode acceptance`：无 .git → PREFLIGHT_FAIL / exit 8，
且该 run 目录只有 summary.txt / check.txt / tested_commit.json / commands.log
四个文件，**没有** controlled_online、three_real、m3_online 等实验目录，
证明未启动受控在线与三真实（证据：evidence-1.0.3/acceptance/）。

---

## 第七章 Docker 与 ROS 2 部署

| 项 | 结果 |
|---|---|
| 镜像构建 | exit 0；digest sha256:ad4e6d2703b72c6fe09470e191edd569f6470077ddedde7ae41c8e7fc356fa75 |
| 构建目录 | 解压包内 docker/（包自带 Dockerfile） |
| 全新 colcon | 解压包内不存在 runtime/build、runtime/install |
| 构建结果 | 4 packages finished [4.70s]，exit 0 |
| 包前缀 | rg_interfaces / rg_demo_nodes / rg_gateway / rg_policy 均解析到 /ws/install/… |

日志：evidence-1.0.3/logs/02_build.log。

---

## 第八章 受控在线复现

run_id：v103-controlled，Domain 144，验证器 **40 checks / 0 failures**，进程退出码 **0**。

| 场景 | request_id | F0 | Planner | Gateway 到达 | Decision | Goal |
|---|---|---|---|---|---|---|
| ON-01 | on01-legal-allow-v103-controlled-controlled | READY_FOR_GATEWAY_SUBMISSION | PLANNER_RESULT_RECEIVED | 1 | ALLOW / ALLOW_IN_POLICY | 1 |
| ON-02 | on02-oor-block-v103-controlled-controlled | ADAPTER_BLOCK | NOT_SUBMITTED_ADAPTER_BLOCK | 0 | 无 | 0 |
| ON-05 | on05-gateway-authority-v103-controlled-controlled | READY_FOR_GATEWAY_SUBMISSION | PLANNER_RESULT_RECEIVED | 1 | BLOCK / OUT_OF_REGION | 0 |

跨层一致性（原始 JSONL）：

- ON-01：RosCommEvent(target 1.5,1.5) → DecisionEvent(ALLOW, ALLOW_IN_POLICY,
  inside allowed_region [0,4]x[0,4]) → ExecutionEvent(downstream_goal_id
  703baca938e34ea8b8e0f03312500bbb, success=true, EXECUTED)
- NavSim：goal_id 703baca938e34ea8b8e0f03312500bbb、同一 request_id、
  recorded_only=true、path_planning=false
- ON-05：RosCommEvent(target 9.0,9.0) → DecisionEvent(BLOCK, OUT_OF_REGION)；
  **无 ExecutionEvent、无 NavSim goal**
- ON-02：适配层阻断，Gateway 到达 0

证据：evidence-1.0.3/controlled/（controlled_verification.json、gateway_audit.jsonl、
navsim_goals.jsonl、tested_commit.json）。

---
## 第九章 三真实负向实验

run_id：v103-threereal，配置 config/team_modules.three-real.yaml（禁止 Mock）。

| 等级 | 结果 | 依据 |
|---|---|---|
| LEVEL1 真实模块调用 | **PASS** | 三模块均 mode=external、rc=0、schema_ok=true |
| LEVEL2 证据契约有效 | **PASS** | run_id / request_id / event_id / evidence_refs / 关联字段一致 |
| LEVEL3 联合准入 | **BLOCKED** | F0 = ADAPTER_BLOCK / ADAPTER_MODULE_STATUS_NOT_PROCEED |

模块真实状态：

| 模块 | mode | rc | schema_ok | status |
|---|---|---|---|---|
| comm_risk | external | 0 | true | UNKNOWN |
| identity_trust | external | 0 | true | UNKNOWN |
| task_risk | external | 0 | true | ALLOW_RECOMMENDED |

negative_expectation：

    expect_block         : true
    expected_reason_code : ADAPTER_MODULE_STATUS_NOT_PROCEED
    observed_reason_code : ADAPTER_MODULE_STATUS_NOT_PROCEED
    levels               : level1=PASS, level2=PASS, level3=BLOCKED
    verdict              : EXPECTED_BLOCK

真实返回码：run_three_real_online.py 退出 0；外层编排 THREE_REAL=PASS，exit 0。

**必须强调**：这里的 PASS 是"负向用例按预期被阻断"，**不是**三真实正向准入通过。
LEVEL3 仍为 BLOCKED，正向准入能力未获得。

---

## 第十章 DDS Enforce 与身份测试边界

### 10.1 DDS Enforce：NOT_RUN

- 执行：`--mode enforce`，退出码 **9**
- 输出：`DDS_ENFORCE=NOT_RUN reason=缺少授权的 security/keystore 与私钥（公开包不含凭据）`
- 判定依据：run_enforce 的前置门禁检测到 security/keystore 不存在，
  **在启动 sros2_check.py 之前**就返回 9 —— 因此这是"未执行"，而不是"执行后失败"。
- 未把历史 7/7 当作本次结果；页面与报告均标注为独立历史实验。

### 10.2 身份类单元测试：FAIL（不是 NOT_RUN）

在源仓库（补齐 artifacts/acceptance/exports 后）重跑
tests/unit/test_identity_trust_real_logs.py：

   13 failed, 43 passed

失败原因全部指向 `security/keystore/enclaves/<ns>/permissions.xml` 缺失。

**分类判定**：这些测试函数**确实被执行了**，只是断言失败 → 按任务书 4.1
必须记 **FAIL**，不得因为出现 keystore 字样就改判 NOT_RUN。
与之相对，DDS Enforce 有显式前置门禁、根本没启动 → NOT_RUN。二者不可混用。

### 10.3 两种验收范围

| 范围 | 内容 | 本轮结果 |
|---|---|---|
| 公开发布包验收 | 受控在线、三真实负向、Web、回放、边界、清理 | 全部 PASS |
| 完整安全验收 | 正式 SROS 2 凭据下的 DDS Security、真实身份认证 | NOT_RUN / FAIL（缺凭据） |

两种范围分别陈述，不共用一个未加说明的 PASS。

---

## 第十一章 Web 控制台复现

| 检查项 | 实际结果 |
|---|---|
| ONLINE READY | true；probe 显示 docker_daemon / image_present / container_ros_jazzy_ok / runtime_workspace_root 全部就绪 |
| 启动方式 | 浏览器点击「启动实验」，在 ROS 2 Jazzy 容器内执行（Python 3.12.3，宿主为 3.10.12） |
| INCOMPLETE 显示 | 选择 enforce → exit 9 → 徽标 **INCOMPLETE**，日志 "⚠ 实验不完整（exit 9）…"，API status=INCOMPLETE |
| 受控在线 | exit 0 → 徽标 DONE，页面显示 run_id 与 SHA |
| 新证据 | 自动装载 run_kind=ONLINE_EVIDENCE，徽标 "ONLINE / 本次在线执行" |
| 历史回放 | REPLAY_SNAPSHOT → 徽标 "REPLAY / 历史证据回放"，并显示 DDS Enforce 7/7 历史数值 |
| 失败信息 | FAIL 分支保留真实错误文本；INCOMPLETE 单独提示 |
| JS 错误 | 0 |

浏览器实测记录：evidence-1.0.3/logs/06_browser.json
（含 enforce 的 INCOMPLETE 与 controlled 的 DONE 两段完整状态）。

---

## 第十二章 故障注入与安全检查

### 12.1 三真实 / 受控故障注入（本轮真实执行，5 例）

| 注入 | 预期 | 实际 | 编排退出码 |
|---|---|---|---|
| F1 删除 module_input.schema.json | 必须 FAIL | LEVEL1 FAIL、L2 BLOCKED、ADAPTER_INTERNAL_ERROR | 4 |
| F2 删除 mock_modules/comm_risk_mock.py | 受控必须 FAIL | 38 checks / 15 failures | 4 |
| F3 模块输出非 JSON（rc=0） | LEVEL2 必须 FAIL | L1 PASS、L2 FAIL、MODULE_STDOUT_INVALID | 4 |
| F4 模块 rc=3 崩溃 | LEVEL1 必须 FAIL | L1 FAIL、MODULE_EXIT_NONZERO | 4 |
| F5 强制 STRICT 身份（阻断原因不符预期） | 必须 UNEXPECTED_BLOCK_REASON | L1/L2 PASS，F0 以 IDENTITY_ATTESTATION_CONFIG_INVALID 阻断，内部 exit 1 | 4 |

结论：五种异常均未被评为"三真实负向 PASS"，假阳性防护有效。
日志：evidence-1.0.3/logs/08_fault_injection.log（随仓库报告目录提交）。

### 12.2 边界与安全

| 用例 | 结果 |
|---|---|
| 证据路径 ../../../etc/passwd | 403 |
| 绝对路径 /etc/passwd | 403 |
| 非法 run_id "../x" | 400 拒绝 |
| 未知模式 "rm -rf /" | 400 拒绝 |
| 3 路并发启动 | 仅 1 个被接受 |
| 停止后容器残留 | **0**（修复了 Created 残留竞态） |
| 在线条件不满足（1.0.2 已验，1.0.3 复核 health） | online_possible 由 probe 决定 |

### 12.3 清理

停止控制台后：8787/8794 无监听、无 dashboard 进程、无 rosystem-* 容器；
原项目 7 个 rg_* 容器全程未被触碰。

---

## 第十三章 发布压缩包核验

| 项 | 完整包 | 离线包 |
|---|---|---|
| 文件名 | RosSystem-CreativeWork-Full-1.0.3.tar.gz | RosSystem-creative-work-1.0.3.tar.gz |
| 大小 | 1765195 B | 33202 B |
| SHA-256 | 42e0d21d098297806812f13dd6e75a87cded950dcd4ae3021e1b59ce2aa01022 | 36f8954caa80b4e44bf157ee9776f7edaf80fb0347f0cdd5db7adae092a2d7bb |
| sha256sum -c | OK | OK |
| 路径穿越 / 绝对路径 | 无 | 无 |
| 符号链接 | 无 | 无 |
| 完整性门禁 | 29 项打包门禁通过；第三方逐项复核 13/13 PRESENT | 内置 11 项门禁；verify_package.sh 13/13 PASS |
| 密钥材料 | 0 | 0 |
| 版本元数据 | BUILD_INFO: version=1.0.3, artifact_commit=bcbec1b…, dirty=0 | — |
| Git 来源 | bcbec1bfc6b0ac26db447975b41fcda762934ec9 | 同左 |

注意：压缩包 SHA-256 是文件字节标识；artifact_commit 是源码提交标识；两者不同，
报告中分别给出，不互相替代。报告与证据在本包构建**之后**提交，
因此发布提交（332732e）晚于 artifact_commit（bcbec1b）。

---

## 第十四章 安全边界一致性

逐文件 `git diff --quiet b1eb082..HEAD -- <file>` 的结果：

| 文件 | 是否改动 |
|---|---|
| scripts/team_demo.py（F0 判定核心） | UNCHANGED |
| config/task_policy.yaml（Gateway 策略） | UNCHANGED |
| identity_trust/assessor.py（M2） | UNCHANGED |
| modules/member1_comm/module.py（M1） | UNCHANGED |
| modules/member3_taskrisk/module.py（M3） | UNCHANGED |
| security/policies/minimal_permissions.xml（DDS 权限） | UNCHANGED |

动作/消息接口（rg_interfaces）与 NavigationSim（rg_demo_nodes）同样未改动。

相对 1.0.2 的全部改动文件（排除压缩包本身）共 15 个，均在任务书 6.1 允许范围内：
acceptance 汇总、退出码、运行元数据、Web 状态显示、回归测试、版本与打包脚本。

---

## 第十五章 遗留问题与能力限制

1. **DDS Enforce**：NOT_RUN。公开包不含 SROS 2 私钥/keystore，正式 Enforce
   只能在授权环境执行；本报告未以历史 7/7 冒充本次结果。
2. **身份类单元测试**：源仓库 13 例 FAIL（实际执行后断言失败，根因是缺
   permissions.xml）。未改判 NOT_RUN、未删除、未放宽断言。
3. **三真实 LEVEL3 正向准入**：BLOCKED。M1 在缺少可信观测状态时给 UNKNOWN，
   M2 缺授权凭据失败关闭。负向通过 ≠ 正向准入通过。
4. **M1 生产级 IDS**：未通过验收（研究模型可用，但不构成生产级检测能力）。
5. **M2 生产身份签发者**：未就绪；受控模式仍为 CONTROLLED_TEST_ONLY，
   F0 记录 verified=false。
6. **Action SendGoal 请求级身份**：未证明。
7. **NavigationSim**：recorded_only，path_planning=false，不代表实体机器人导航。
8. **严格 acceptance（发布包）**：PREFLIGHT_FAIL（无 .git 40 位 SHA），
   属于包形态限制，设计如此。
9. **严格 acceptance（源仓库）**：整体 FAIL，原因是第 2 条的身份类测试；
   其余环节（契约、F0 P0、三真实、受控、M3 六场景）在 1.0.2 轮次已验证通过。
10. **单实例假设**：同一安装目录并行启动两个控制台会互相覆盖 PID 文件。

---

## 第十六章 最终验收矩阵与结论

### 16.1 发布包验收矩阵（1.0.3，独立复现）

| 项目 | 结果 | 证据 |
|---|---|---|
| 发布包 SHA-256 | **PASS** | logs/01_package.log |
| 安全解压 | **PASS**（无穿越、无符号链接） | 同上 |
| 打包完整性 | **PASS**（13/13 + 29 项门禁） | 同上 |
| Docker 构建 | **PASS**（exit 0，digest ad4e6d27…） | logs/02_build.log |
| Fresh colcon 构建 | **PASS**（4 包，4.70s） | 同上 |
| 受控在线 | **PASS**（40/0，exit 0） | logs/03_runs.log |
| ON-01 ALLOW/Goal1 | **PASS** | controlled/ |
| ON-02 F0 BLOCK/Goal0 | **PASS** | controlled/ |
| ON-05 Gateway BLOCK/Goal0 | **PASS** | controlled/ |
| 三真实负向验证 | **PASS**（EXPECTED_BLOCK） | three_real/ |
| 假阳性防护 | **PASS**（5 类注入全部 FAIL） | logs/08_fault_injection.log |
| ONLINE READY | **PASS** | logs/05_dashboard_up.log |
| Web 在线执行 | **PASS**（exit 0 → DONE） | logs/06_browser.json |
| 新证据展示 | **PASS**（ONLINE_EVIDENCE + 真实 run_id/SHA） | 同上 |
| **acceptance 状态语义** | **PASS**（实现正确：18 单元 + 5 CLI + 6 接线） | logs/04_semantics.log |
| DDS Enforce | **NOT_RUN**（缺凭据） | acceptance/NOT_RUN.txt |
| 安全边界保持 | **PASS**（6 个核心文件 UNCHANGED） | 第十四章 |
| 进程清理 | **PASS**（0 残留） | logs/07_boundary.log |

### 16.2 两个必须分开的结论

- **acceptance 判定实现是否正确**：**PASS**。状态机与退出码经 29 个用例验证，
  ENFORCE=NOT_RUN 不再产生 ACCEPTANCE=PASS / exit 0。
- **acceptance 实际完成了多少**：**INCOMPLETE**。公开发布包内 DDS Enforce 为
  NOT_RUN；源仓库内还有 13 个身份类测试 FAIL。二者都不等于"全部通过"。

### 16.3 最终结论

**RELEASE_FROZEN_WITH_LIMITATIONS**

依据：
- 交付物完成了**公开发布包验收范围内**的全部规定验证（上表 PASS 项），
  版本固定、报告与证据齐全、可被第三方仅凭压缩包复现受控在线系统；
- 但仍存在**已披露的非阻断限制**：DDS Enforce NOT_RUN、13 个身份类测试 FAIL、
  LEVEL3 BLOCKED、NavigationSim 为 recorded_only、发布包内 acceptance 只能
  PREFLIGHT_FAIL。这些限制均有原始证据，且未通过放宽校验或伪造结果掩盖。

未选择 RELEASE_FROZEN_VERIFIED 的原因：严格 acceptance 仍有未执行项（NOT_RUN）
与失败项（FAIL），"规定验证全部完成"不成立；按任务书标准，不得以主观判断替代。

---

## 附录 A 交付物索引

| 类别 | 路径 |
|---|---|
| 分支 | release/creative-work-v1.0.3-final |
| 修复提交 | bcbec1bfc6b0ac26db447975b41fcda762934ec9 |
| 发布提交 | 332732e341db7b0f6e815863a7f6d62dc21a823d |
| 冻结 Tag | creative-work-v1.0.3 |
| 完整包 | submission/creative-work/dist/RosSystem-CreativeWork-Full-1.0.3.tar.gz |
| 离线包 | submission/creative-work/dist/RosSystem-creative-work-1.0.3.tar.gz |
| 校验文件 | 同目录 .sha256 与 .manifest.txt |
| 报告 | submission/creative-work/reports/ROSYSTEM_1_0_3_FINAL_REPAIR_AND_REPRODUCTION_REPORT.md |
| 证据包 | submission/creative-work/reports/evidence-1.0.3/（112 KB，19 个文件） |
| 完整 diff | 由 git diff b1eb082..bcbec1b 生成 |

## 附录 B 证据包内容

    evidence-1.0.3/
      logs/01_package.log          包校验、解压、完整性、密钥扫描
      logs/02_build.log            镜像构建 + 全新 colcon
      logs/03_runs.log             check / controlled / three-real
      logs/04_semantics.log        Enforce NOT_RUN、acceptance PREFLIGHT_FAIL、语义回归
      logs/05_dashboard_up.log     ONLINE READY 与 probe 明细
      logs/06_browser.json         浏览器：INCOMPLETE / DONE / 新证据
      logs/07_boundary.log         路径、run_id、并发、清理
      logs/08_fault_injection.log  5 类故障注入（本报告第十三章）
      controlled/                  验证器 JSON、Gateway JSONL、NavSim JSONL、tested_commit
      three_real/                  summary.json、f0.json
      acceptance/                  summary.txt、NOT_RUN.txt、check.txt
      package/                     manifest 与两个 .sha256
