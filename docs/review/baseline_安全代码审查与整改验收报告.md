# baseline 安全代码审查与整改验收报告

| 项 | 值 |
| --- | --- |
| 审查基准 SHA | `b031d4ba63df8bb3ef304099184f6927867a4c51`（`origin/baseline`，已重新核实） |
| F0 来源 | `ebfe263530d10a746c172367f9d96d2f9dc5d7d4` |
| 整改分支 | `fix/baseline-audit-v3-docs`（从 baseline 创建，**未直接改共享 baseline**） |
| 审查日期 | 2026-10-12 |
| 审查范围 | `src/`、`scripts/`、`tests/`、`security/`、`config/`、`docs/`、`.github/`、`.gitignore` |

---

## 1. 审查结论摘要

**`CONFIRMED_FINDINGS: 1`（1 项已证实并已修复）**

| ID | 严重度 | 问题 | 状态 |
| --- | --- | --- | --- |
| **F-01** | **高** | `scripts/lib.sh` 的 `rg_reap_stragglers()` 按**进程名**执行 `pkill -9 -f`，可跨成员/跨实例误杀；并提供 `RG_REAP_FORCE=1` 绕过唯一守卫 | **已修复** |

其余 13 个审查维度**未发现需要修复的缺陷**。
未发现可用于提权的命令注入、绕过 Gateway 的路径或审计失败放行。

---

## 2. F-01 详细记录

### 2.1 问题位置

| 位置 | 内容 |
| --- | --- |
| `scripts/lib.sh:197-215` | `rg_reap_stragglers()` 定义；对 4 个节点名模式执行 `pkill -9 -f` |
| `scripts/lib.sh:198-203` | `RG_REAP_FORCE=1` 可绕过 `rg_require_no_running_instance` 守卫 |
| `scripts/run_demo.sh:12` | **唯一真实调用点**（无条件调用） |
| `scripts/start_system.sh:227` | 注释声称"build.sh 会调用 rg_reap_stragglers 清理同名节点进程"（**过期说明**） |

### 2.2 复现条件

1. 成员 A 在容器内启动自己的栈（节点进程 cmdline 含
   `install/rg_demo_nodes/lib/rg_demo_nodes/navigation_sim`）；
2. 成员 B 在同一容器内执行 `scripts/run_demo.sh`（README.md:237 与 ACCEPTANCE.md:133
   均把它列为官方演示命令）；
3. `run_demo.sh` 第 12 行调用 `rg_reap_stragglers`，其守卫
   `rg_require_no_running_instance` **只检查本工作区记录中的受管理实例**，
   检查不到成员 A 的栈；
4. 随后 `pkill -9 -f "rg_demo_nodes/lib/rg_demo_nodes/navigation_[s]im"`
   **按名称匹配**，成员 A 的 NavigationSim 被终止。
5. 若设置 `RG_REAP_FORCE=1`，连唯一守卫也被绕过。

### 2.3 影响范围

- **跨成员误杀**：同一容器内其他成员正在运行的节点。
- **跨实例误杀**：同一成员用不同 `ROS_DOMAIN_ID` 并行运行的多个实例
  （`pkill -f` 不区分 Domain）。
- **不可归因**：被终止方只会看到进程消失，无法从日志判断是谁清理的。
- 可达性**已确认**（非死代码）：`run_demo.sh` 是文档化的官方命令。

### 2.4 可达性核查（逐脚本）

| 脚本 | 是否调用 | 说明 |
| --- | --- | --- |
| `scripts/run_demo.sh` | **是** | 唯一真实调用点 |
| `scripts/build.sh` | 否 | 只调用 `rg_require_no_running_instance`（**只读检测**，发现实例即拒绝构建） |
| `scripts/run_all.sh` | 否 | — |
| `scripts/run_unit_tests.sh` | 否 | — |
| `scripts/start_system.sh` | 否 | 只做**检测**并在发现实例时拒绝启动，从不终止进程 |

**其他批量清理路径排查**：全仓库检索 `pkill` / `killall` / `kill -9`。
`scripts/demo_live.sh:37` 的 `kill -9 "-${pid}"` 操作的是**它自己记录的 `PIDS`**，
属所有权语义，**安全**。未发现其他按名批量清理路径。

### 2.5 修改说明（最小范围，未引入新机制）

| 文件 | 修改 |
| --- | --- |
| `scripts/run_demo.sh` | **删除**第 12 行的 `rg_reap_stragglers` 调用，并以注释说明理由 |
| `scripts/lib.sh` | **删除** `rg_reap_stragglers()` 整个函数（已无调用者），以注释保留删除原因与正确做法 |
| `scripts/start_system.sh` | 更正第 227 行的过期注释 |
| `tests/integration/reap_ownership_check.py` | **新增**所有权回归测试 |

**为什么删除而不是改造**：`run_demo.sh` 调用的 `demo_live.sh` 已经用
`PIDS+=($!)` 记录自己启动的每个节点，并通过 `trap cleanup EXIT`
按**进程组**（所有权明确）清理。原有清理既**冗余**又**只可能伤害他人**。
删除是最小且最安全的修复。

**未做的事**：

- **未**引入替代性的全局清理机制；
- **未**重新开放任何强制清理开关（`RG_REAP_FORCE` 仅作为历史说明留在注释中）；
- **未**按节点名推断任何进程所有权。

### 2.6 回归证据

`tests/integration/reap_ownership_check.py` —— **7/7 PASS**
（不采用"给判断函数传两个字符串"的伪验证，而是**真实启动进程**）：

| 用例 | 结果 |
| --- | --- |
| lib.sh 中可执行 `pkill` 行数 = 0 | PASS |
| `rg_reap_stragglers` 行首函数定义已移除 | PASS |
| `run_demo.sh` 不再调用按名清理 | PASS |
| `RG_REAP_FORCE` 仅存在于说明注释 | PASS |
| **本轮自己的进程可被清理**（own pid 已终止） | PASS |
| **其他实例的进程未被清理**（other pid 仍存活） | PASS |
| 两者 cmdline 含相同节点名模式而结果不同 → 依据是**所有权**而非进程名 | PASS |

---

## 3. 其余审查维度结论

| # | 维度 | 结论 | 证据 |
| --- | --- | --- | --- |
| 1 | Gateway 始终保留权威准入 | **未发现问题** | T03：三模块全放行 + 越界 → Gateway `OUT_OF_REGION`、Goal 0 |
| 2 | 上游 Action 绕过 Gateway 的路径 | **未发现** | 仓库无直接向 `/rg/nav_execute` 下发的生产路径；`d1_independent_review.py` 有对应检查 |
| 3 | DDS-Security Enforce 真实限制 | **未发现问题** | `sros2_check.py` S3/S4 拒绝来自 Fast DDS 原生报错，非客户端超时；S3C 有正向对照 |
| 4 | 策略缺失/无效时失败关闭 | **未发现问题** | `MISSING_POLICY` 场景 → `POLICY_MISSING`；T04–T08 全部阻断 |
| 5 | UNKNOWN/ERROR/无效输出阻断 | **未发现问题** | 适配层 `ADAPTER_MODULE_STATUS_NOT_PROCEED` 等路径；`UNKNOWN` 不得推进 |
| 6 | 输入 JSON 是否可控命令执行或身份 | **未发现** | `team_demo.py:559` 明确"只操作本进程组，绝不按名 pkill"；模块命令只来自受信任配置且 `shell=False` |
| 7 | 命令注入/进程组误清理/超时悬挂 | **发现 F-01** | 见 §2 |
| 8 | 实例/容器/Domain 隔离 | **未发现问题** | `member_env.sh` 一成员一容器一 Domain；冲突时报错而非猜测 |
| 9 | 审计失败是否放行 | **未发现问题** | 适配层审计写入是推进前置条件（`ADAPTER_AUDIT_WRITE_FAILED`） |
| 10 | 执行超时被误解为未执行 | **未发现问题** | 文档与代码均未把超时等同于"一定没执行" |
| 11 | `.gitignore` 防泄漏 | **本轮加固** | baseline 原有的 `.gitignore` 未覆盖 `/data/`、`/training_runs/`、`/models/`、`/.research-venv`；已在上一轮 baseline 发布时补齐 |
| 12 | Schema/Action/八原因码一致性 | **未发现问题** | 契约校验 `CONTRACT_OK`；本轮 diff 对这些路径为空 |
| 13 | 恒真断言 / SKIP 误记 PASS | **未发现问题**（本分支） | 本分支无 `tests/research/`（属研究分支）；AST 复核 F0 测试无恒真断言 |
| 14 | Onboarding 命令可运行 | **未发现问题** | `docs/onboarding/README.md` 的命令已在容器内实测 |

**没有为了报告显得充分而虚构安全漏洞。**

---

## 4. 回归结果（本轮实测）

| 项目 | 命令 | 结果 |
| --- | --- | --- |
| 契约校验 | `scripts/validate_team_contracts.py --all` | **CONTRACT_OK** |
| F0 Python 单元测试 | `scripts/run_unit_tests.sh` | **295 passed / UNIT TEST RESULT: PASS** |
| ROS 2 四包构建 | `scripts/build.sh` | **BUILD RESULT: PASS** |
| 新增所有权回归 | `tests/integration/reap_ownership_check.py` | **7/7 PASS** |
| 三个默认 Mock | 容器内直接运行 | 全部通过，均标 `source=MOCK` |
| T02 正常 Action | `team_handoff_check.py --scenario T02` | Gateway `ALLOW`/`ALLOW_IN_POLICY`，Goal **1** |
| T03 越界 Action | `--scenario T03` | Gateway `BLOCK`/`OUT_OF_REGION`，Goal **0** |
| T04 失败关闭 | `--scenario T04` | PASS |
| T09 模块替换 | `--scenario T09` | PASS |
| SROS 2 Enforce | `sros2_check.py` | **7/7 PASS** |
| F0-T01~T15 | 完整执行 | **15/15 PASS**（在 baseline 上实测） |
| 脚本语法 | `bash -n` | 三个改动脚本均 OK |

> 说明：`tests/research/` 属研究分支内容，本分支不存在，**不是本轮回归项**。

---

## 5. 未修改的共享边界（已核验）

| 项 | 状态 |
| --- | --- |
| `PatrolNavigate.action` | 未修改 |
| 八个冻结业务原因码 | 未修改 |
| `/rg/guarded_navigate` | 未修改 |
| `/rg/nav_execute` 仅供 Gateway 下游 | 边界保持 |
| 四份 JSON Schema | 未修改 |
| 统一 `ModuleInputEnvelope` | 未修改 |
| 三个模块状态语义 | 未修改 |
| `PROPOSED_V1` / `1.0.0-proposed` | **未擅自改为 FROZEN** |
| DDS 权限配置 | 未修改 |
| `main` 分支 | 未触碰 |

---

## 6. 尚存风险

1. **SROS 2 Enforce 与默认开发模式并存**：Enforce 是安全实验模式（Domain 43），
   默认开发是 Domain 42。**报告中不得混为一谈**，成员二需特别注意。
2. **Keystore 为本地敏感资产**：`security/keystore/` 权限 700 且已在 `.gitignore` 中，
   但仍依赖使用者不误用 `git add -f`。
3. **CI 只做卫生检查**，不执行完整 ROS 2 构建；上面的 PASS 均为**本机实测**，
   不是 CI 保证的。
4. **`start_system.sh` 的进程扫描兜底**（`ctr_node_pids`）用于**检测**其他实例，
   行为是**拒绝启动**而非终止进程，属安全设计；但若未来有人把它改成清理逻辑，
   会重新引入 F-01 类风险。**建议在代码评审中关注这一点。**
5. **本轮未做**：SROS 2 之外的其他 DDS-Security 插件行为核验、
   跨主机场景、长时间运行下的资源泄漏观测。
