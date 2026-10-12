# baseline 团队协作工程化最终验收报告

| 项 | 值 |
| --- | --- |
| 起始 baseline SHA | `7f82db2cd20f9aa23a0b709dd4a5afafdd9077f9` |
| 起始工作分支 SHA | `3990a03b559e4e19db70bb3a4c57afc746d7eac6`（6 个提交，未丢失） |
| 本轮追加提交 | `63203ee` →（amend）`996059051087233444dfbbb4bf8aa4676c9bc341` |
| **最终工作分支 SHA** | **`996059051087233444dfbbb4bf8aa4676c9bc341`** |
| `baseline` SHA | `7f82db2cd20f9aa23a0b709dd4a5afafdd9077f9`（**未改动**） |
| `main` SHA | `838f66f41821edf0421612a205d162ae8e9eb955`（**未改动**） |
| 分支名 | `chore/baseline-team-workflow` |
| PR URL | **未创建**（见 §D） |
| 合并方式 | **未合并**（见 §D） |

---

## A. 版本

工作分支共 **7 个提交**（6 个原有 + 1 个本轮补丁）：

```text
e62b978 docs: align README and onboarding with baseline
13df951 docs: finalize baseline collaboration workflow
6628db2 feat: add minimal member module template
65afc45 test: add unified member module acceptance
a530bb4 ci: enforce member PR security and test gates
3990a03 docs: record manual procedure for closing historical PRs
9960590 test(baseline): close three acceptance gaps found in review   ← 本轮
```

> 本轮按任务书要求**在现有分支追加小型补丁**，未从 baseline 重建工程，
> 也未重置丢失任何提交。

---

## B. 三项缺陷

### FIX-01 — CI Schema 示例校验必须真实执行 → **PASS**

| 项 | 内容 |
| --- | --- |
| 修复前问题 | CI 用 `sample.name.startswith(stem.split('.')[0])` 做**文件名前缀匹配**。样例真实名称是 `comm_normal.json` / `module_input_valid.json`，Schema 名是 `comm_risk_evidence.schema.json` / `module_input.schema.json` —— **前缀根本不匹配**，样例可能一个都没被校验，CI 却显示 PASS |
| 修复文件 | `.github/workflows/member-module-gates.yml`、新增 `scripts/check_schema_coverage.py` |
| 修复方式 | CI 改为**复用** `scripts/validate_team_contracts.py`（内部已有显式 `valid_map` 与非法样例 `manifest.json`），并补上校验器自身没有的**覆盖断言** |
| 测试用例 | `tests/unit/test_schema_coverage.py`（7 项） |
| 命令 | `python3 scripts/validate_team_contracts.py --all --quiet` + `python3 scripts/check_schema_coverage.py` |
| 返回码 | **0** |
| 实测输出 | `comm_risk_evidence: checked 3, passed 3` / `identity_trust_assessment: checked 3, passed 3` / `module_input: checked 1, passed 1` / `task_risk_decision: checked 3, passed 3`；`invalid_cases: checked 13, expected_rejections 13, actual_rejections 13`；`SCHEMA_EXAMPLE_COVERAGE: PASS` |
| 负向验证 | ① 清空样例目录 → 非零退出 ② 移走必需合法样例 → 非零退出 ③ 合法样例改成字段类型错误 → 非零退出 ④ 非法样例换成合法内容 → 非零退出 ⑤ CI 不再使用前缀匹配 ⑥ 正式 Schema 未被修改 |
| **结论** | **PASS** —— 即使样例覆盖为零也不可能错误显示通过 |

**过程中发现并修复自身一个健壮性缺陷**：样例目录缺失时 `validate_all()` 抛异常，脚本只崩不报（CI 只看到 traceback、看不到覆盖缺口）。已改为干净的 `SCHEMA_EXAMPLE_COVERAGE: FAIL` 输出。

### FIX-02 — 统一验收工具必须在读取过程中限制输出 → **PASS**

| 项 | 内容 |
| --- | --- |
| 修复前问题 | `invoke()` 用 `subprocess.run(capture_output=True)`，会先把 stdout/stderr **全部读入内存**再检查 `max_stdout_bytes`。持续输出的模块可在检查生效前把验收器内存吃光 —— 上限形同虚设 |
| 修复文件 | `scripts/check_member_module.py` |
| 修复方式 | **复用**适配层 `team_demo.py` 已有的 `read_bounded()` 与 `terminate_process_group()`，**不另写一套**语义不同的超时/限流/清理实现。`invoke()` 改用 `Popen(start_new_session=True)` + selector 边读边计数；stdout 超限立即终止本次进程组；stderr 继续排空但只保留上限字节；单调时钟计时；超时走受控终止（SIGTERM → SIGKILL） |
| 新增 fixtures | `tests/fixtures/faulty_modules/` 五个**真实故障子进程**：洪泛 stdout / 洪泛 stderr / 挂起 / 派生子进程 / 多字节 UTF-8 |
| 测试用例 | `tests/unit/test_member_module_limits.py`（LIM-01~08，11 项） |
| 返回码 | **0**（11 passed） |
| 关键证据 | LIM-02：超限时 `exceeded=STDOUT_TOO_LARGE` 且保留量 ≤ 上限、**耗时 < 30s**（立即终止而非等超时）；LIM-04：stderr 保留量受限且 stdout 仍能取到合法 JSON；LIM-05：超时 `exceeded=TIMEOUT` 且不判成功；LIM-06：**派生的子进程被一并清理**（验证整个进程组）；LIM-07：**其他实例进程未被误杀**；LIM-08：UTF-8 按字节而非字符计数 |
| **结论** | **PASS** —— 验收工具与真实适配器共用同一套资源限制语义 |

**过程中修正一处测试断言**：僵尸进程的 `/proc/<pid>` 仍然存在，原断言把"目录项消失"当作终止判据会误报。已改为检查进程状态（`state='Z'` 或目录消失均视为已终止）。连续两次运行结果一致。

### FIX-03 — 真实验证三模块四状态与失败关闭 → **PASS**

| 项 | 内容 |
| --- | --- |
| 修复前问题 | `STATE-03` 直接写入 PASS，只靠静态状态列表判断，不能证明模块真实产生了对应输出，也不能证明合法风险状态被正确识别 |
| 修复文件 | `scripts/check_member_module.py` |
| 修复方式 | 引入 `STATE_MATRIX`，三模块 × 四状态 = **12 个组合逐一真实运行**：实际调用模块 → 真实产出 JSON → 通过对应 Schema → `run_id`/`request_id` 一致 → `classify()` 分为 `PROCEED` / `LEGAL_BLOCK`。并验证三种阻断状态经 `team_demo.py` 均返回 `ADAPTER_BLOCK` |
| 测试用例 | `tests/unit/test_member_module_four_state.py`（7 项，含参数化） |
| 返回码 | **0**（三模块均 exit 0） |
| 实测状态矩阵 | `comm_risk`: NORMAL(PROCEED) / SUSPICIOUS / UNKNOWN / ERROR<br>`identity_trust`: AUTHORIZED(PROCEED) / DENIED / UNKNOWN / ERROR<br>`task_risk`: ALLOW_RECOMMENDED(PROCEED) / BLOCK_RECOMMENDED / UNKNOWN / ERROR |
| 适配层阻断 | `ADP-SUSPICIOUS` / `ADP-DENIED` / `ADP-BLOCK` / `ADP-UNKNOWN` / `ADP-ERROR` 全部 **PASS** |
| 分层标注 | L1_PROTOCOL = PASS；**L2_REAL_ALGORITHM = NOT_READY**；**L3_ROS2_RUNTIME = BLOCKED** |
| **结论** | **PASS** —— 12 种状态均有实际运行证据，且适配层失败关闭可靠 |

**关键区分已落地**：`SUSPICIOUS` / `DENIED` / `BLOCK_RECOMMENDED` **结构合法**（Schema 通过），归类为 `LEGAL_BLOCK` 而**不是** Schema 错误。

> **L1 通过不自动把 L2/L3 标为 PASS** —— 有专门测试断言这一点。

---

## C. 测试

| 测试 | 命令 | 返回码 | 结果 | 本轮实际执行 |
| --- | --- | --- | --- | --- |
| Python 单元测试 | `scripts/run_unit_tests.sh` | 0 | **350 passed / UNIT TEST RESULT: PASS** | 是 |
| 契约（四份 Schema + 样例） | `scripts/validate_team_contracts.py --all` | 0 | `CONTRACT_OK` | 是 |
| Schema 覆盖 | `scripts/check_schema_coverage.py` | 0 | `SCHEMA_EXAMPLE_COVERAGE: PASS` | 是 |
| 模板自测 | `templates/member_module/test_module.py` | 0 | `TEMPLATE SELF-TEST: PASS`（9/9） | 是 |
| 模块验收（三模块） | `scripts/check_member_module.py --module <X>` | 0 | 三模块各 27 PASS | 是 |
| 十二状态 | 同上 `STATE-*` 项 | 0 | 12/12 PASS + 9 项适配层阻断 PASS | 是 |
| stdout/stderr 限流 | `pytest tests/unit/test_member_module_limits.py` | 0 | 11 passed（真实故障子进程） | 是 |
| 子进程组清理与隔离 | 同上 LIM-06 / LIM-07 | 0 | PASS | 是 |
| ROS 2 四包构建 | `scripts/build.sh` | 0 | `BUILD RESULT: PASS` | 是 |
| 进程所有权回归 | `tests/integration/reap_ownership_check.py` | 0 | 7/7 PASS | 是 |
| GitHub CI（`member-module-gates`） | — | — | **未运行**（见 §D） | **否** |
| GitHub CI（`repo-hygiene`） | — | — | **未运行**（见 §D） | **否** |
| F0-T01～T15 | — | — | **NOT_RUN** | **否** |
| SROS 2 Enforce | — | — | **NOT_RUN** | **否** |

> 单元测试数由 **320 → 350**（+30）。历史报告中的 295/320 均为**当时**的实测值，
> 不作为本轮结论。

**冻结安全边界检查**（`git diff origin/baseline...HEAD`）：

```text
src/rg_interfaces/action/PatrolNavigate.action
src/rg_policy/rg_policy/reason_codes.py
src/rg_gateway/
docs/interfaces/schemas/
security/policies/
config/task_policy.yaml
→ 差异为空
```

---

## D. PR 审查 → **BLOCKED**

### 无法创建 PR

| 检查项 | 结果 |
| --- | --- |
| `gh` CLI | **不可用** |
| `hub` | **不可用** |
| `GITHUB_TOKEN` / `GH_TOKEN` | **未设置** |
| `~/.config/gh` | 不存在 |
| git credential helper | 未配置 |
| 远程协议 | `git@github.com:...`（**SSH**，可推送但无法调用 REST API） |
| GitHub REST API 探测 | 匿名可读（200），**写操作需要 token** |

**结论**：本环境缺少 GitHub 凭证，无法执行 `gh pr create` / `gh pr comment` /
`gh pr close`，也无法读取 Checks 或分支保护规则。

**这不是操作失败，而是权限缺失。** 用户虽已授权"推送 GitHub 的所有权限"，
但环境内不存在可用凭证。

### 待人工执行

1. 打开 https://github.com/godzwp117/RosSystem/compare/baseline...chore/baseline-team-workflow
2. 标题：`chore(baseline): finalize team module gates and collaboration workflow`
3. 按 `.github/PULL_REQUEST_TEMPLATE.md` 填写
4. **base 必须是 `baseline`**（不是 `main`）
5. 等待 `member-module-gates` 与 `repo-hygiene` 两个 workflow **实际成功**
6. 取得**至少一名非提交者**的正式 `APPROVED`
7. 核对 PR HEAD SHA == `996059051087233444dfbbb4bf8aa4676c9bc341`
8. 正常合并

### 不得做的事

不得因为无法创建 PR 就**直接强推 `baseline`** 绕过审查 —— 本轮**未**这样做。

---

## E. 历史 PR → **BLOCKED**

| PR | 源分支 | 目标分支 | 最终状态 |
| --- | --- | --- | --- |
| #1 | `feature/m3-dynamic-policy` | `main` | **未关闭**（权限不足） |
| #2 | `feature/framework-f0` | `main` | **未关闭**（权限不足） |
| #3 | `baseline` | `main` | **未关闭**（权限不足） |

三项均**未合并**、来源分支**全部保留**。

操作步骤与可直接粘贴的关闭说明见
[历史PR关闭操作说明](历史PR关闭操作说明.md)。

---

## F. 分支保护 → **MANUAL_ACTION_REQUIRED**

无法读取或修改 GitHub 分支保护规则（同上凭证原因）。**未声称已启用。**

### 待人工配置（`baseline`）

- [ ] Require a pull request before merging（至少 **1** 名审批人）
- [ ] Require status checks to pass
- [ ] 禁止强制推送
- [ ] 禁止删除分支
- [ ] 如可用：审查新提交后旧批准失效
- [ ] 如可用：要求 PR 分支与最新 baseline 保持可合并

> **重要**：配置 Required Checks 前，必须先让 PR 真实跑过一次，
> 从 GitHub UI 读取**准确的 job check 名称**，而不是按 workflow 文件名猜测。
> 不能要求一个从未成功运行过的检查。

---

## G. 最终门槛

| 门槛 | 状态 |
| --- | --- |
| `FIX_SCHEMA_EXAMPLE_COVERAGE` | **PASS** |
| `FIX_BOUNDED_SUBPROCESS` | **PASS** |
| `FIX_FOUR_STATE_VERIFICATION` | **PASS** |
| `CONTRACT_REGRESSION` | **PASS** |
| `F0_REGRESSION` | **PARTIAL**（单测/契约/构建/所有权 PASS；F0-T01~T15 与 SROS 2 Enforce **NOT_RUN**） |
| `REVIEW_PR_CREATED` | **BLOCKED**（无 GitHub 凭证） |
| `INDEPENDENT_REVIEW` | **BLOCKED**（无 GitHub 凭证） |
| `GITHUB_CI` | **BLOCKED**（无 GitHub 凭证） |
| `BASELINE_MERGE` | **BLOCKED**（无 GitHub 凭证；**未绕过审查直推**） |
| `OLD_PRS_CLOSED` | **BLOCKED**（无 GitHub 凭证） |
| `BRANCH_PROTECTION` | **MANUAL_ACTION_REQUIRED** |
| `BASELINE_FINAL_RELEASE` | **NOT_READY** |

**最终发布 PASS 的强制条件未全部满足** —— 三个修复已通过，但真实 CI、
独立审查与正常合入均因权限缺失无法完成。**未宣称全部仓库治理项目已完成。**

---

## H. 绝对约束遵守情况

| 约束 | 遵守 |
| --- | --- |
| 不修改 `main` | ✅ `main` SHA 未变 |
| 不 force push `baseline` | ✅ `baseline` SHA 未变，本轮未推送 baseline |
| 不删除既有功能分支 | ✅ 全部保留 |
| 不跳过独立代码审查 | ✅ **未**为了合并而绕过 |
| 不伪造 APPROVED | ✅ 未生成任何伪造批准 |
| 不把本地测试冒充 GitHub CI | ✅ 明确标注 CI 为 BLOCKED |
| 不把 Mock 结果冒充真实算法 | ✅ L2 = `NOT_READY` |
| 不修改冻结 Action / 八原因码 | ✅ diff 为空 |
| 不削弱 DDS-Security | ✅ `security/policies/` diff 为空 |
| 不让 UNKNOWN/ERROR 推动执行 | ✅ 9 项适配层阻断全部验证 |
| 不清理其他成员进程或容器 | ✅ LIM-07 专门验证 |
| 不提交数据/模型/密钥/个人日志 | ✅ 0 个 |
| 不无依据扩大架构修改 | ✅ 仅追加一个补丁提交 |
| 不擅自把 `PROPOSED_V1` 改 FROZEN | ✅ 未改 |
| 不宣称在线入侵检测 | ✅ L3 = `BLOCKED` |

---

## I. 一句话结论

**三个验收缺口已全部修复并有真实运行证据（FIX-01/02/03 均 PASS，
单元测试 350 passed）；但 PR 审查、GitHub CI、合入 baseline、关闭历史 PR
与分支保护五项目标均因本环境缺少 GitHub 写权限而 BLOCKED ——
已提供准确的人工操作清单，且未以任何方式绕过审查流程。**
