# M2 / M3 问题修复与真实模块验收报告

- 仓库：`godzwp117/RosSystem`
- 公共基线：`baseline`，任务书给定 SHA `a4c597161d254192b662ee7b8f4d17f76a89cc16`
- 成员交付归档快照：`chore/member-deliveries` = `3ce820258c69b89e2ad9291e16c44dc7d2b99150`（本轮实际检出的 HEAD）
- 修复分支：`fix/m2-m3-acceptance`（基于归档快照，**未**修改 `baseline` / `main`）
- 修复提交：`86d383eaa66b878dfffc2287b2ed302bbce69301`
- 契约：`PROPOSED_V1` / `1.0.0-proposed`，**未冻结**（本报告不作冻结声明）

> 状态口径：`FIXED` = 源码已修且有测试证明；`VERIFIED` = 本轮实际重新执行并通过；
> `PARTIAL` = 部分验证；`NOT_RUN` = 尚未执行；`BLOCKED` = 受环境限制无法执行。

---

## 0. 结论摘要

| 项 | 结论 | 状态 |
|---|---|---|
| M2 DDS 拒绝日志无法匹配（ANSI 控制序列） | 已复现、已定位、已修复，含真实归档日志回归 | **FIXED + VERIFIED** |
| M2 历史证据与当前请求的资源绑定 | 已修复：历史判定不再跨资源搬运，实测 S3/S4 由误判转为可解释 | **FIXED + VERIFIED** |
| M2 是否已变成在线 DDS 身份认证器 | **否**。仍是离线证据解释器，本次修复的是**证据解释可靠性** | — |
| M3 真实模块四状态验收不兼容 | 已修复：`--real-fixture` 真实条件触发，四状态全部由真实条件产生 | **FIXED + VERIFIED** |
| M3 是否完成真实 ROS 2 联调 | **否**。本环境无 ROS 2 Jazzy，L3 保持 `BLOCKED` | **BLOCKED** |
| 是否达到进入下一阶段集成 | M2/M3 的**离线/L2 真实模块**层面：**达到**；L3 在线联调：**未达到** | **PARTIAL** |

**一句话**：两个模块的代码级缺陷都已修复并有真实证据回归；但"真实 ROS 2 在线联调"这一层本轮无法执行，
报告中不把它写成通过。

---

## 1. 工作方式与边界遵守

| 约束 | 遵守方式 |
|---|---|
| 不直接改 `baseline` / `main` | 新建 `fix/m2-m3-acceptance`；`baseline`/`main` 未被 checkout 修改 |
| 从固定快照提取 M2/M3 源码 | 从 `3ce8202` 的 `deliveries/` 按交付说明映射到仓库正常位置 |
| 不在 `deliveries/` 归档内运行 | 全部测试在仓库根目录运行（模块依赖根目录 `src/rg_policy`、Schema、适配层） |
| 不覆盖同名文件 | 落位前逐一检查目标为空；`scripts/check_member_module.py` 为**修改**而非替换 |
| 不改历史实验记录 | `artifacts/acceptance/exports/` 无任何改动（`git status` 为空） |
| 不改 M1 | 未触碰 `modules/rospace_comm`、`deliveries/member1-comm/` |
| 不改公共 Schema / Gateway / DDS 权限 | 4 个 Schema SHA-256 前后一致；`config/task_policy.yaml`、`security/policies/` 未改 |
| 不上传密钥 | 只引用 `permissions.xml`；未读取/提交 `security/keystore` 私钥 |

### 落位映射（交付包 → 仓库）

| 交付包位置 | 仓库位置 | 本分支相对交付是否有改动 |
|---|---|---|
| `member2-identity/identity_trust/assessor.py` | `identity_trust/assessor.py` | **已修改**（见 §2） |
| `member2-identity/identity_trust/__init__.py` | `identity_trust/__init__.py` | 未改 |
| `member2-identity/tests/unit/test_identity_trust_assessor.py` | `tests/unit/test_identity_trust_assessor.py` | **已修改**（期望语义纠偏，见 §2.5） |
| `member2-identity/scripts/member2_adapter_check.py` | `scripts/member2_adapter_check.py` | 未改 |
| `member3-taskrisk/modules/member3_taskrisk/module.py` | `modules/member3_taskrisk/module.py` | **字节一致**（无需改动） |
| `member3-taskrisk/modules/member3_taskrisk/risk_model.py` | `modules/member3_taskrisk/risk_model.py` | **字节一致**（无需改动） |
| `member3-taskrisk/tests/unit/test_member3_taskrisk.py` | `tests/unit/test_member3_taskrisk.py` | 字节一致 |
| `member3-taskrisk/config/team_modules.member3.yaml` | `config/team_modules.member3.yaml` | 未改 |
| `member3-taskrisk/docs/member3/` | `docs/member3/` | 未改 |

SHA-256 对照与逐文件 diff 存于 `artifacts/acceptance/m2_m3_fix/`：

- `diff.m2_assessor.patch`（交付版 → 修复版）
- `diff.m2_unit_tests.patch`
- `check_member_module.task_risk.report.json` / `check_member_module.identity_trust.report.json`

**重要结论**：M3 的算法源码（`module.py` / `risk_model.py`）**不需要任何修改**。M3 的问题 100% 在通用验收器一侧，
因此修复集中在 `scripts/check_member_module.py`，未以"改模块迁就测试"的方式解决。

---

## 2. 第一项任务：M2 DDS 日志解析修复

### 2.1 缺陷确认（先复现，再修改）

对**真实归档日志**直接跑交付版 `DENIAL_RE`：

```
logs/tests_evidence/20261009T093144Z/S3/rogue_planner.log      -> OLD DENIAL_RE match = False
logs/tests_evidence/20261009T093144Z/S4/rogue_unauthorized.log -> OLD DENIAL_RE match = False
```

字节级定位（`S3/rogue_planner.log` 第一行）：

```
b'\x1b[37;1m2026-10-09 09:31:57.547 \x1b[31;1m[\x1b[37;1mSECURITY\x1b[31;1m Error] \x1b[37mrr/rg/nav_execute/...'
```

控制序列确实**插进了 `SECURITY` 与 `Error` 之间**（`ESC[37;1mSECURITY ESC[31;1m Error]`）。

**决定性证据**：只删 ANSI、不改任何文字，旧正则立刻匹配成功 —— 说明 ANSI 是唯一阻断因素，
而不是日志本身缺少拒绝语义：

```
S3: after ANSI-strip only -> OLD DENIAL_RE match = True
    matched text = '[SECURITY Error] rr/rg/nav_execute/_action/send_goalReply topic not found in allow rule'
S4: after ANSI-strip only -> OLD DENIAL_RE match = True
```

交付版在真实证据上的实测输出（错误地丢掉了 S3/S4 的真实拒绝证据）：

| 场景 | 交付版 status | 失败原因 |
|---|---|---|
| S2 | `AUTHORIZED` | — |
| S3C | `UNKNOWN` | 资源与候选入口不同 |
| **S3** | **`UNKNOWN`** | `证据不足或不可核验，失败关闭：no native access-control denial in client log` |
| **S4** | **`UNKNOWN`** | 同上 |

**为何旧单元测试没发现**：`test_identity_trust_assessor.py` 的 fixture 使用**手工合成的无 ANSI**日志
（且没有 `Permissions.cpp` 原生源码位置）。测试与真实证据不同构，因此缺陷被完全掩盖。

### 2.2 修复实现（`identity_trust/assessor.py`）

**(1) 有界的 ANSI 规范化** —— 按正规文法删除，不做模糊/通配/跨行拼接：

```python
ANSI_CSI_RE      = re.compile('\x1b\\[[0-?]*[ -/]*[@-~]')     # CSI
ANSI_TWO_CHAR_RE = re.compile('\x1b[@-Z\\\\-_]')              # 双字符序列
ANSI_OSC_RE      = re.compile('\x1b\\][^\x07\x1b]*(?:\x07|\x1b\\\\)')  # OSC
RESIDUAL_CTRL_RE = re.compile('[\\x00-\\x08\\x0b\\x0c\\x0e-\\x1f\\x7f]')
```

`normalize_ansi()` 只在**内存**中规范化并返回统计（`csi`/`osc`/`two_char`/`residual_ctrl`）。
原始日志文件从不被改写。有测试断言"规范化结果 == 按正规文法删除转义序列的结果"，
以及"纯文本输入逐字不变"。

**(2) 行内原生拒绝签名 + 资源核对**：

```python
NATIVE_DENIAL_LINE_RE = re.compile(
    r'SECURITY[^A-Za-z0-9]{0,4}Error\s*\][^\n]{0,600}?not found in allow rule'
    r'[^\n]{0,300}?Permissions\.cpp:\d+', re.I)
TOPIC_IN_LINE_RE = re.compile(r'\b((?:rq|rr|rt)/[A-Za-z0-9_./-]+)')
```

`dds_denial_evidence(log, resource, observed)` 强制三项对应关系全部成立：

1. **拒绝场景**：`outcome` 必须属于原生拒绝类别（`ACTION_CLIENT_CREATION_DENIED` /
   `EXCEPTION` / `NODE_CREATION_FAILED`）；
2. **原生权限错误**：同一行内出现 `SECURITY … Error]` + `not found in allow rule` +
   `Permissions.cpp:<行号>`；
3. **拒绝资源**：行内抽出的 DDS 主题必须等于期望资源的
   `rq/<svc>Request` 或 `rr/<svc>Reply`。

任一项不成立即 `ValueError` → 失败关闭。

**(3) 明确排除误判**：`NON_DDS_OUTCOMES`（超时/服务端不可达/业务阻断）与
`BUSINESS_POLICY_MARKERS`（`OUT_OF_REGION` / `TASK_MISMATCH` / `DUPLICATE_REQUEST` /
`RATE_LIMIT` / `POLICY_MISSING`）一律拒绝判为 DDS 拒绝。

**(4) 移除跨行匹配能力**：旧 `.{0,600}?` 允许跨行拼接；新签名限定在**单行**内
（`[^\n]`），并有专门测试 `test_multi_line_reassembly_is_not_a_denial` 证明跨行拼接不再构成证据。

修复后实测（真实归档日志）：

| 场景 | 证据层 `examine()` | 拒绝资源 | 日志行 |
|---|---|---|---|
| S3 | `DENIED` | `rr/rg/nav_execute/_action/send_goalReply` | 1 |
| S4 | `DENIED` | `rr/rg/nav_execute/_action/send_goalReply` | 1 |

### 2.3 历史证据与当前请求的关联修复（任务书 §3.3）

**问题**：交付版只在 `status == 'AUTHORIZED'` 时做资源一致性检查：

```python
if status == 'AUTHORIZED' and detail['resource'] != envelope['candidate_action']['action_resource']:
```

`DENIED` 分支**没有**这个检查。于是对 S3/S4，只要日志能被解析出来，就会把
"执行端 `/rg/nav_execute` 被拒绝"直接写成"当前 guarded 请求被 DDS 拒绝"——
把一次历史拒绝**跨资源搬运**到当前请求上。

**修复**：对**两个方向**统一比较历史资源与当前候选资源：

```python
if detail['resource'] != current_resource:
    status = 'UNKNOWN'
    binding = 'HISTORICAL_RESOURCE_MISMATCH'
    reason = ('历史受控实验证据针对资源 {0}（{1}），与当前候选资源 {2} 不同；'
              '该历史判定不能解释当前请求，且当前请求缺少与已认证 DDS 主体的绑定')
else:
    binding = 'HISTORICAL_RESOURCE_MATCHES_CURRENT'
```

**历史事实仍然完整保留**（不清空、不改写）：

- `extensions.historical_experiment_status = 'DENIED'`
- `extensions.historical_experiment_resource = '/rg/nav_execute'`
- `extensions.historical_denial_topic = 'rr/rg/nav_execute/_action/send_goalReply'`
- `extensions.historical_denial_log_line = 1`
- `authorization.denial_detail` / `access_control_evidence.detail` 保留原生报错原文
- `evidence_refs` 仍引用 summary、原始客户端日志、源策略、生成权限、S3C 正向对照

**当前请求的结论与历史分离**：

- 顶层 `status`（= `authorization.result_status`）：`UNKNOWN`，不推进
- `extensions.current_request_binding = 'HISTORICAL_RESOURCE_MISMATCH'`
- `extensions.identity_binding_note` 明确说明 `request_id` / `declared_enclave` /
  业务 JSON 自报身份**都不是** DDS 已认证身份
- **从不填写** `subject.authenticated_identity`

`IdentityTrustAssessment` 仍符合原有 Schema（`additionalProperties: false` 未被突破；
所有新增字段都在 `extensions` 内，`denial_layer` 取值仍在既有枚举内）。
Schema 文件 SHA-256 未变。

### 2.4 兼容性修复：`event_id` 与 `request_id` 关联

**发现的真实接口不兼容**：验收器 `ID-03` 要求 `event_id` 含 `request_id`
（M3 与既有约定为 `m3-<request_id[:80]>-<uuid>`），而交付版 M2 为
`'evt-identity-' + uuid4().hex[:24]`，**不含** `request_id`。这使 M2 真实模块无法达到验收门槛。

按"最小兼容修复"处理（不改验收器的既有检查，也不改 Schema）：

```python
'event_id': 'evt-identity-{0}-{1}'.format(envelope['request_id'][:80], uuid.uuid4().hex[:24])
```

有测试断言：`event_id` 含 `request_id` 且长度 ≤ 128（Schema 上限），
覆盖 `request_id` 长度 80 / 81 / 100 / 128。契约张力记入 §6「遗留问题 R-1」。

### 2.5 对交付单元测试期望的纠偏（不是"改成通过"）

交付版 `test_03` 断言 `S3/S4 -> DENIED`，这正是**把历史拒绝当成当前请求结论**的错误语义。
修复后该断言必然失败（`UNKNOWN`）。处理方式：**重写断言以表达正确语义**，并扩大覆盖：

| 原断言 | 修复后断言 |
|---|---|
| `status == 'DENIED'` | `status == 'UNKNOWN'` + 历史 `DENIED` 事实保留 + `binding == HISTORICAL_RESOURCE_MISMATCH` |
| `denial_layer == 'DDS_ACCESS_CONTROL'` | `denial_layer == 'UNKNOWN'`（当前请求未被判定） |
| — | 新增 `test_03b`：证据层资源一致时确为 `DENIED`；S2 资源一致时 `AUTHORIZED` |

同时修复了 fixture 与真实证据**不同构**的问题：合成日志现在包含
`Permissions.cpp` 原生源码位置，且 S4 使用带 ANSI 的着色形态。

---

## 3. 第二项任务：M3 真实模块验收修复

### 3.1 缺陷确认

交付报告 `deliveries/member3-taskrisk/reports/generic_acceptance_report.json` 记录
`33 PASS / 3 FAIL / 1 NOT_RUN / 1 BLOCKED`，门槛 `False`。三个失败是
`STATE-BLOCK` / `STATE-UNKNOWN` / `STATE-ERROR`，实际状态均为 `ALLOW_RECOMMENDED`。

**本轮已精确复现**：用修复前的验收器 + 真实 M3 模块运行，得到**完全相同的计数**
（见 §5.2），证明复现环境与交付方一致，不是环境差异。

**根因**：`check_member_module.py` 通过 `detail.f0_mock.scenario` 注入场景，
而真实规则模块依据"候选 Action / Task ID / 坐标系 / 目标位置 / TaskPolicy / 可选审计历史"
计算建议，**不读取**该 Mock 开关。因此三种阻断状态在真实模块上不可触发。

### 3.2 修复实现（`scripts/check_member_module.py`）

新增**可选**真实场景模式 `--real-fixture <受信任本地文件>`，与既有 Mock 模式并存。

**(1) 场景与命令分离**：fixture 只能引用受信任配置中的**档案名**，命令本身永远在
`--config` 的 `real_command_profiles` 里：

```yaml
# config/team_modules.member3.real.yaml（受信任配置）
real_command_profiles:
  policy_valid:        {args: [--policy, config/task_policy.yaml]}
  policy_tight_region: {args: [--policy, config/scenarios/task_policy_tight_region.yaml]}
  policy_absent:       {args: [--policy, config/scenarios/task_policy_absent.yaml]}
  policy_corrupt:      {args: [--policy, config/scenarios/task_policy_corrupt.yaml]}
```

**(2) 业务输入不得携带本地执行控制字段**：`_reject_command_injection()` 递归拒绝
`command / executable / exec / argv / shell / cwd / workdir / policy / policy_path /
audit_log / env / environment / pythonpath / module_path / script`，并有
9 个参数化测试逐一验证。fixture 中的策略路径必须落在仓库内（`_bounded_repo_path`）。

**(3) 独立地面真值**：`policy_file_state()` **不依赖模块自报**，独立解析配置指向的策略文件：

- `.yaml` → `rg_policy.task_policy.parse_task_policy`（Gateway 权威解析器）
- `.xml` → XML 解析器且根为 `<policy>`（M2 读取的同一种文件）

返回 `VALID` / `ABSENT` / `CORRUPT`。模块输出必须与之自洽，否则判负。
这直接防住"模块自称读过某策略"的伪造：即使输出里编造策略路径，也过不了
`test_fake_policy_citation_cannot_buy_traceability`。

**(4) 四状态由真实条件触发**（`config/acceptance/real_scenarios.member3.yaml`）：

| 场景 | 真实触发条件 | 期望状态 | 实测 |
|---|---|---|---|
| `allow` | 目标 (2.0,2.0) 在权威策略 `[0,4]×[0,4]` 内 | `ALLOW_RECOMMENDED` | ✅ `ALLOW_RECOMMENDED` / `ALLOW_IN_POLICY` |
| `block` | 同一目标超出隔离策略 `[0,1]×[0,1]` | `BLOCK_RECOMMENDED` | ✅ `BLOCK_RECOMMENDED` / `OUT_OF_REGION` |
| `unknown` | 受信任配置指向**不存在**的策略文件 | `UNKNOWN` | ✅ `UNKNOWN` / `POLICY_MISSING` |
| `error` | 受信任配置指向**损坏**的策略文件（非法 YAML） | `ERROR` | ✅ `ERROR` / `POLICY_MISSING` |

缺失/损坏策略使用**隔离 fixture**：`config/scenarios/task_policy_absent.yaml`（故意不存在）
与 `config/scenarios/task_policy_corrupt.yaml`。**权威策略 `config/task_policy.yaml` 未被修改**
（有测试断言其内容仍为 `active: true` / `patrol_a_001` / `[0,4]×[0,4]`）。

**(5) 检查实际状态，而非场景标签**：每行必须同时满足
`structured && schema_ok && ids_ok && traceability_ok && actual_state == expected_state
&& actual_class == expected_class`。把 `expected_state` 改成与真实条件不符会被立即判负
（`test_mislabeled_expected_state_would_be_caught`）。

**(6) F0 处置**：对每个阻断场景，把该场景的真实命令写进**临时受信任配置**后调用
`scripts/team_demo.py`，要求 `decision == 'ADAPTER_BLOCK'` 且退出码 ≠ 0；
对合法场景要求 `decision == 'READY_FOR_GATEWAY_SUBMISSION'`，且
`gateway_decision is None`、`navsim_goal_id is None`（READY ≠ ALLOW ≠ 执行成功）。

**(7) Mock 模式向后兼容**：未给出 `--real-fixture` 时行为与修复前**完全一致**，
Mock 状态矩阵仍是**强制项**（`mandatory=True, gate=True`）。只有给出 `--real-fixture` 时，
对真实模块不适用的 Mock 场景行才被标记 `gate=False, applicability=NOT_APPLICABLE_REAL_MODULE`
—— **检查项、状态与原因都完整保留在报告中（仍显示 FAIL）**，只是不再计入门槛，
门槛由真实条件矩阵承担。这**不是**删除失败检查或降低门槛：
原有 12 项 Mock 检查、超时、stdout/stderr、请求 ID、Schema 与失败关闭检查全部保留，
并由 `test_original_fail_closed_checks_still_present` 断言。

**(8) 解释器统一（兼容性修复）**：交付配置写裸 `python3`，而真实模块需要
`jsonschema>=4`（Draft 2020-12）。若验收器自身跑在满足依赖的解释器里、却用 PATH 上另一个
`python3` 调模块，会产生"模块不可运行"的假失败。`resolve_interpreter()` 把命令首部的裸
python 别名映射到**当前验收进程的解释器**；只改解释器，不改参数与任何检查门槛。
报告同时记录 `module_command` 与 `module_command_as_configured` 便于复核。

### 3.3 M3 审计历史处理复核（只读审查，未改代码）

任务书要求复核的四点，M3 源码已满足，且现有测试覆盖：

| 要求 | 实现/证据 | 状态 |
|---|---|---|
| 历史快照不得成为 Gateway 并发状态的权威替代 | `metadata.pending_gateway_checks` 保留 `CONCURRENT_TRACKER_RECHECK`；`history_snapshot.clock_basis = 'wall-clock snapshot; not Gateway monotonic tracker'`；`admitted_in_window` 为近似值 | **VERIFIED**（源码 + 测试） |
| 历史不完整时失败关闭 | `HistoryUnavailable`（缺失/过期/撕裂行/配对不全/时间越界）→ `UNKNOWN`；`HistoryInvalid`（JSON 非法/重复/关联错位）→ `ERROR` | **VERIFIED**（`test_history_failure_conditions` 8 个分支） |
| 去重/速率建议不得冒充实时权威判定 | `pending_gateway_checks` 保留 `DUPLICATE_REQUEST` / `RATE_LIMIT` 由 Gateway 最终判定；`authority = 'ADVISORY_ONLY'` | **VERIFIED** |
| 不得为实验成功改变 Gateway 规则顺序 | 未改动 `src/rg_gateway/`、`src/rg_policy/policy_engine.py`、`config/task_policy.yaml` | **VERIFIED**（git diff 为空） |

---

## 4. 修改文件清单

### 4.1 修改（已存在于基线）

| 文件 | 改动 |
|---|---|
| `scripts/check_member_module.py` | +621 / −7：新增 `--real-fixture` 真实场景机制、`real_command_profiles` 解析、命令注入拒绝、独立策略状态判定、追溯校验、真实矩阵与 F0 处置、解释器统一；Mock 模式语义不变 |

### 4.2 新增（从交付快照落位）

| 文件 | 说明 |
|---|---|
| `identity_trust/assessor.py` | M2 主实现（**已修改**：ANSI 规范化、行内拒绝签名、资源核对、双向资源绑定、`event_id`） |
| `identity_trust/__init__.py` | M2 包初始化（未改） |
| `scripts/member2_adapter_check.py` | M2 离线适配联调脚本（未改） |
| `modules/member3_taskrisk/{module.py,risk_model.py,README.md,requirements.txt,example_config.yaml}` | M3 实现（**字节一致**，未改） |
| `config/team_modules.member3.yaml` | 交付的 M3 接入配置（未改） |
| `docs/member3/{IMPLEMENTATION_REPORT.md,PR_DRAFT.md}` | 交付文档（未改） |

### 4.3 新增（本轮为使验收可复现而新增）

| 文件 | 说明 |
|---|---|
| `config/team_modules.member3.real.yaml` | M3 真实场景受信任配置（含 4 个命令档案） |
| `config/team_modules.member2.real.yaml` | M2 真实场景受信任配置（含 4 个受控实验档案） |
| `config/acceptance/real_scenarios.member3.yaml` | M3 四状态真实场景 fixture |
| `config/acceptance/real_scenarios.member2.yaml` | M2 四场景真实证据 fixture |
| `config/scenarios/task_policy_tight_region.yaml` | 隔离测试策略（收窄区域 → 触发 `BLOCK_RECOMMENDED`） |
| `config/scenarios/task_policy_corrupt.yaml` | 隔离损坏策略（触发 `ERROR`）；**故意不可解析** |
| `config/scenarios/README.task_policy_absent.md` | 说明 `task_policy_absent.yaml` **故意不存在**（触发 `UNKNOWN`） |
| `tests/unit/test_identity_trust_assessor.py` | M2 单测（**已修改**：期望语义纠偏 + fixture 与真实证据同构） |
| `tests/unit/test_identity_trust_real_logs.py` | **新增** M2 真实归档日志回归（56 项） |
| `tests/unit/test_member3_taskrisk.py` | M3 交付单测（未改，95 项） |
| `tests/unit/test_member3_real_acceptance.py` | **新增** M3 真实验收回归 + 反假通过（41 项） |
| `artifacts/acceptance/m2_m3_fix/` | 本轮验收报告与交付↔修复 diff |

---

## 5. 可复现测试命令与实际结果

**运行环境**（本轮全部命令的实际环境）

```
OS            : Linux 6.18.54.1-microsoft-standard-WSL2 x86_64
Python        : 3.10.12  (/home/zhangwei/project/RosSystem/.research-venv/bin/python)
pytest        : 9.1.1
jsonschema    : 4.26.0
PyYAML        : 6.0.3
ROS 2         : 不存在（无 /opt/ros，ros2 不在 PATH）→ L3 BLOCKED
Git HEAD      : 3ce820258c69b89e2ad9291e16c44dc7d2b99150（baseline 快照）
```

> 注：本仓库 `.research-venv` 是指向 `tests/evidence/research-venv` 的符号链接，
> 已预装 `pytest` / `jsonschema>=4` / `PyYAML`。

### 5.1 命令清单与结果

| # | 命令 | 返回码 | 结果 |
|---|---|---|---|
| 1 | `./.research-venv/bin/python -m pytest tests/unit -q` | 0 | **548 passed, 3 skipped**（7:50）—— 最终代码状态下的全量复跑 |
| 2 | `./.research-venv/bin/python -m pytest tests/unit/test_identity_trust_assessor.py -q` | 0 | **23 passed** |
| 3 | `./.research-venv/bin/python -m pytest tests/unit/test_identity_trust_real_logs.py -q` | 0 | **56 passed** |
| 4 | `./.research-venv/bin/python -m pytest tests/unit/test_member3_taskrisk.py -q` | 0 | **95 passed** |
| 5 | `./.research-venv/bin/python -m pytest tests/unit/test_member3_real_acceptance.py -q` | 0 | **41 passed**（约 7 分钟，含坏模块/挂起反例） |
| 6 | `./.research-venv/bin/python -m pytest tests/unit/test_member_module_{contract,acceptance,limits,four_state}.py tests/unit/test_team_{adapter,contracts,process_protocol}.py -q` | 0 | **180 passed**（32s）—— 受影响 F0 适配层与公共契约测试 |
| 7 | `python3 scripts/check_member_module.py --module task_risk --config config/team_modules.member3.real.yaml --real-fixture config/acceptance/real_scenarios.member3.yaml` | **0** | **45 PASS / 3 FAIL / 1 NOT_RUN / 1 BLOCKED，门槛 True** |
| 8 | `python3 scripts/check_member_module.py --module identity_trust --config config/team_modules.member2.real.yaml --real-fixture config/acceptance/real_scenarios.member2.yaml` | **0** | **45 PASS / 3 FAIL / 1 NOT_RUN / 1 BLOCKED，门槛 True** |
| 9 | `python3 scripts/check_member_module.py --module {comm_risk,identity_trust,task_risk} --config config/team_modules.example.yaml` | 0 | 各 **34 PASS / 3 NOT_RUN / 1 BLOCKED，门槛 True**（Mock 回归不变） |
| 10 | 4 个公共 Schema 加载 + 自检 | 0 | 全部通过；SHA-256 与快照一致 |
| 11 | ROS 2 Jazzy + DDS-Security Enforce 集成 | — | **NOT_RUN / BLOCKED**（无 ROS 2 环境） |

全量 548 项中，本轮新增/修改贡献 120 项：
`test_identity_trust_real_logs.py` 56 项（新增）、`test_member3_real_acceptance.py` 41 项（新增）、
`test_identity_trust_assessor.py` 由 21 项增至 23 项。`3 skipped` 为仓库既有跳过项
（**跳过不计入通过**）。修复前的全仓基线为交付方记录的 `428 passed, 3 skipped`。

关于 #7/#8 的 `3 FAIL`：这三项是 `STATE-BLOCK/UNKNOWN/ERROR`，即把 Mock 场景开关
套用到不解析该开关的真实模块。它们**如实保留在报告中并显示 FAIL**，但被标记
`gate=False, applicability=NOT_APPLICABLE_REAL_MODULE`，门槛由 `REAL-STATE-*` 承担。
这是"如实记录不适用"而非"删除失败检查"。

### 5.2 修复前后行为对比

**(A) 通用验收器（M3）**

| | 修复前（交付版验收器） | 修复后（`--real-fixture`） |
|---|---|---|
| 执行命令 | `check_member_module.py --module task_risk --config config/team_modules.member3.yaml` | 同左 + `--real-fixture config/acceptance/real_scenarios.member3.yaml` |
| 计数 | **33 PASS / 3 FAIL / 1 NOT_RUN / 1 BLOCKED** | **45 PASS / 3 FAIL / 1 NOT_RUN / 1 BLOCKED** |
| 门槛 | `False` | **`True`** |
| `STATE-BLOCK` | FAIL（实际 `ALLOW_RECOMMENDED`） | `REAL-STATE-BLOCK` PASS（实际 `BLOCK_RECOMMENDED`） |
| `STATE-UNKNOWN` | FAIL（实际 `ALLOW_RECOMMENDED`） | `REAL-STATE-UNKNOWN` PASS（实际 `UNKNOWN`） |
| `STATE-ERROR` | FAIL（实际 `ALLOW_RECOMMENDED`） | `REAL-STATE-ERROR` PASS（实际 `ERROR`） |
| 触发方式 | Mock 开关（真实模块不读取） | 真实策略条件 |
| F0 阻断 | 已有（基于 Mock） | 已有（基于**真实**状态）+ READY 语义校验 |

> 修复前的 `33/3/1/1` 由本轮用 `HEAD~1:scripts/check_member_module.py` 在本机**实测复现**，
> 与交付报告计数逐项一致（报告存于 `/tmp/baseline_acc/m3-baseline/report.json`）。

**(B) M2 评估器（真实归档日志）**

| 场景 | 修复前 status | 修复后 status | 修复后历史事实 | 当前请求绑定 |
|---|---|---|---|---|
| S2 | `AUTHORIZED` | `AUTHORIZED` | `AUTHORIZED` | `HISTORICAL_RESOURCE_MATCHES_CURRENT` |
| S3C | `UNKNOWN`（资源不同） | `UNKNOWN` | `AUTHORIZED` | `HISTORICAL_RESOURCE_MISMATCH` |
| **S3** | `UNKNOWN`（**丢失**真实拒绝证据） | `UNKNOWN` | **`DENIED`** + 拒绝资源/行号保留 | `HISTORICAL_RESOURCE_MISMATCH` |
| **S4** | `UNKNOWN`（**丢失**真实拒绝证据） | `UNKNOWN` | **`DENIED`** + 拒绝资源/行号保留 | `HISTORICAL_RESOURCE_MISMATCH` |

关键差异：修复前 S3/S4 的原生 DDS 拒绝证据**被整体丢弃**（`access_control_evidence.kind = UNKNOWN`）；
修复后该证据被完整提取并保留，同时**正确地不搬用**到当前 guarded 请求上。

**(C) 交付版 vs 修复版在"仅删 ANSI"对照下的行为**

| | 修复前 | 修复后 |
|---|---|---|
| 含 ANSI 真实日志 | 不匹配（证据丢失） | 匹配（2 条原生拒绝记录） |
| 仅删 ANSI 的同一日志 | 匹配 | 匹配 |
| 跨行拼接 | **可**误拼（`.{0,600}?` 可跨行） | **不可**（`[^\n]`，单行限定） |
| 超时/不可达/业务阻断 | 仅靠 `outcome` 白名单 | `outcome` 黑名单 + 业务标记 + 资源核对 |
| 拒绝资源与期望不一致 | 不检查 | 显式失败关闭 |

---

## 6. 剩余未解决问题

| ID | 问题 | 影响 | 状态 |
|---|---|---|---|
| **R-1** | **契约张力**：`ID-03` 要求 `event_id` 含完整 `request_id`，而 `identity_trust_assessment` / `task_risk_decision` 的 Schema 把 `event_id` 限制为 ≤128 字符。当 `request_id` > 80 字符（当前 M2/M3 约定）时两者无法同时成立 | 超长 `request_id` 下 `ID-03` 会失败 | **未解决**（需成员四裁定：缩短随机后缀至 12 位可把上限提高到 102，但 103+ 仍无解） |
| **R-2** | 真实 ROS 2 Jazzy + DDS-Security Enforce 集成未执行 | 无 Gateway 决策与 NavigationSim Goal 证据 | **BLOCKED**（无 ROS 2 环境） |
| **R-3** | M2 仍是**离线证据解释器**：`AUTHORIZED` 只表示所引用历史实验中访问成功 | 不能推导当前请求已完成 DDS 认证 | **设计如此**，非缺陷 |
| **R-4** | M2 的 `--case` 仍由受信任配置固定；`/rg/guarded_navigate` 与 `/rg/nav_execute` 资源不匹配时**永远**得到 `UNKNOWN` | 对当前候选入口，M2 不会返回 `AUTHORIZED` | 符合安全要求；若将来希望 M2 对候选入口给出正面结论，需要针对候选入口的**新**受控实验 |
| **R-5** | M3 `runtime_monitor = NOT_READY`、`dynamic_state_model = NOT_INTEGRATED` | 无实时监测能力 | 交付方自述，本轮未改变 |
| **R-6** | M1 未集成（`config/team_modules.member3.real.yaml` 中 M1 为 MOCK） | 三模块全真实联合实验不存在 | 超出本任务范围（任务要求不改 M1） |
| **R-7** | 本轮未把修复推送远程、未创建 PR | 仅本地分支 | 见 §8 PR 草案 |

---

## 7. 是否达到进入下一阶段集成的条件

| 层面 | 条件 | 结论 |
|---|---|---|
| M2 证据解释可靠性 | 真实归档 S3/S4 原生拒绝可解析；资源/场景/错误三者对应；超时等不误判；无正向对照/权限矛盾/日志缺失损坏均失败关闭 | **达到** |
| M2 历史与当前解耦 | 历史拒绝不再跨资源搬运；历史事实保留；自报身份不构成认证 | **达到** |
| M3 真实四状态 | 四状态全部由真实条件触发；输出符合原有 Schema；F0 对三种阻断正确阻断；合法条件仅 `READY_FOR_GATEWAY_SUBMISSION` | **达到** |
| M3 审计历史安全性 | 快照不冒充并发权威；不完整即失败关闭；去重/限速不冒充实时判定；未改 Gateway 规则顺序 | **达到** |
| **L3 ROS 2 在线联调** | 需真实 Gateway 决策 + NavigationSim Goal | **未达到（BLOCKED）** |

**总体：`PARTIAL`。** 建议下一阶段先在具备 ROS 2 Jazzy + DDS-Security Enforce 的环境
执行 L3，再进入成员四的最终审查。M2/M3 的离线与 L2 真实模块层面已具备集成条件。

---

## 8. PR 审查说明（草案）

**分支**：`fix/m2-m3-acceptance` → 目标 `baseline`（或团队约定的集成分支）
**提交**：`86d383eaa66b878dfffc2287b2ed302bbce69301`（基于 `3ce8202`）

**审查者应重点确认的四件事**

1. **M2 是否真的没有变成在线认证器** —— 检查 `assessor.py` 未引入任何 ROS/DDS 调用，
   `subject.authenticated_identity` 从不填写，`identity_evidence.kind` 恒为
   `CONTROLLED_SECURITY_EXPERIMENT` 或 `UNKNOWN`。
2. **M2 的 S3/S4 语义变化是否可接受** —— 交付版把 S3/S4 记为 `DENIED`，本修复改为
   `UNKNOWN`（历史 `DENIED` 保留在 `extensions`）。这是**收紧**而非放松：
   交付版会把执行端的历史拒绝当成当前 guarded 请求的结论。
3. **验收器门槛是否被放松** —— 确认未给出 `--real-fixture` 时计数与语义与修复前**逐项一致**
   （`test_mock_mode_still_passes_without_real_fixture` /
   `test_mock_mode_states_are_mandatory_and_gating`）；确认 `gate=False` 的行**仍以 FAIL
   出现在报告中**且带 `applicability=NOT_APPLICABLE_REAL_MODULE`；确认
   `test_original_fail_closed_checks_still_present` 覆盖 ERR/ADP/LIM/PROTO/ID/SCH 各项。
4. **未改公共资产** —— 4 个 Schema SHA-256、`config/task_policy.yaml`、
   `security/policies/`、`src/rg_gateway/`、`src/rg_policy/`、`artifacts/acceptance/exports/`
   均无 diff。

**建议的审查顺序**

1. `artifacts/acceptance/m2_m3_fix/diff.m2_assessor.patch`（M2 全部改动）
2. `scripts/check_member_module.py` 的 `real_command_profiles` 解析与
   `_reject_command_injection` / `policy_file_state` / `verify_traceability`
3. `config/acceptance/real_scenarios.member{2,3}.yaml`（场景与真实触发条件）
4. `tests/unit/test_identity_trust_real_logs.py`（真实日志回归）
5. `tests/unit/test_member3_real_acceptance.py` 的 `BROKEN_MODULES` 段（反假通过）

**已知会看到的"红"**

- 真实 fixture 报告中的 `STATE-BLOCK/UNKNOWN/ERROR` 三项 FAIL（原因与 `gate=False` 说明见 §5.1）
- `LAYER-02 = NOT_RUN`、`LAYER-03 = BLOCKED`
- M3 交付文档 `docs/member3/IMPLEMENTATION_REPORT.md` 中"M3 需与成员四解决验收器兼容"
  的表述**已过时**——本轮已完成，该文档按"不改交付归档"原则未改动，建议在 PR 中说明。

---

## 9. 证据文件位置

| 证据 | 路径 |
|---|---|
| M3 真实条件验收报告 | `artifacts/acceptance/m2_m3_fix/check_member_module.task_risk.report.json` |
| M2 真实证据验收报告 | `artifacts/acceptance/m2_m3_fix/check_member_module.identity_trust.report.json` |
| M2 交付↔修复 diff | `artifacts/acceptance/m2_m3_fix/diff.m2_assessor.patch` |
| M2 单测 diff | `artifacts/acceptance/m2_m3_fix/diff.m2_unit_tests.patch` |
| M2 原始安全证据（只读） | `artifacts/acceptance/exports/m2_sros2_enforce/logs/tests_evidence/20261009T093144Z/` |
| M3 修复前基线报告 | 本轮实测复现，计数 `33/3/1/1`（与交付报告一致） |
| M3 交付原始报告 | `deliveries/member3-taskrisk/reports/generic_acceptance_report.json` |

---

## 附：本报告未声称的内容

为避免过度声明，明确列出**本轮没有**做到的事：

- 没有执行任何 ROS 2 / DDS-Security Enforce 在线实验（无 ROS 2 环境）
- 没有取得 Gateway 决策或 NavigationSim Goal 证据
- 没有让 M2 成为在线 DDS 身份认证器，也没有声称它现在是
- 没有证明 M3 对未知攻击的泛化能力
- 没有修改或复跑历史 S1–S6 实验，只是**读取**其归档日志作为证据
- 没有冻结 `PROPOSED_V1` 契约
- 没有推送远程、没有创建 PR（仅本地分支与提交）
