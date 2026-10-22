# 成员二技术审查：DDS 身份与资源权限分析（`identity_trust`）

- 审查对象：`deliveries/member2-identity/`（7 个文件）
- 来源快照：`chore/member-deliveries` = `3ce820258c69b89e2ad9291e16c44dc7d2b99150`
- 来源基线：`a4c597161d254192b662ee7b8f4d17f76a89cc16`（成员二自述，见其 `docs/MEMBER2_IMPLEMENTATION.md`）
- 核心文件 SHA-256：
  - `identity_trust/assessor.py` = `b287822efc107b99723b22b290cc0e4d0456688951829ba6123bcd26d9609069`
  - `tests/unit/test_identity_trust_assessor.py` = `1c835290824460014dbe1855575cf7031348687b24465c2718b348fcb7bc3c78`
  - `scripts/member2_adapter_check.py` = `3ecedc4f0986ec4073512f15f4757e9835004f21d15b73d61da8473f777530d2`
  - `config/team_modules.member2.example.yaml` = `530c334e115beaa986ff753f49e73b24dfc92fe7af5e7a78ce42c9f6a1b2bef6`
  - 全部 78 个文件哈希见 `EVIDENCE_INDEX.json` 与本轮生成的 `/tmp/mr/delivery_hashes.txt`
- 本轮实际执行：单元测试复测、模块真实运行（S2/S3/S3C/S4 × 两处证据根）、`check_member_module.py` 验收、联合适配层联调

---

## 1. 结论摘要

| 项 | 结论 | 证据等级 |
| --- | --- | --- |
| 实现类型 | **离线受控实验的证据解释器**，不是在线 DDS 身份认证器 | E1_CODE + E2_STATIC |
| 是否读取真实 Permissions | 是。同时读取 **源策略 XML** 与 **生成的 DDS `permissions.xml`**，并要求两者一致 | E1_CODE |
| 是否使用真实 SROS 2 Enforce 运行结果 | 是。依赖一个被 pin 的历史 Enforce run（`summary.json` + 原始客户端日志） | E1_CODE + E5_RUNTIME（历史） |
| 能否区分配置允许与实际通信成功 | 能。要求 summary + 原始日志 `PLANNER_RESULT.success=true, status_code=EXECUTED` | E1_CODE |
| 能否区分配置拒绝与 DDS 实际拒绝 | **设计上要求原生拒绝文本，但当前实现对真实彩色日志失效** | E2_STATIC + E3_UNIT_TEST + 本轮复现 |
| 是否真实接入 F0 适配层 | 是。已在本轮联合运行中作为 `external` 模块被适配层调用 | E4_INTEGRATION_TEST |
| 能否支持当前请求实时认证 | **不能**。输出与当前请求无因果关系（见 §4） | E1_CODE + E2_STATIC |

**一句话**：这是一个工程质量很高、安全边界表述诚实的**离线证据解释器**；但它既不认证当前请求，其核心的“原生 DDS 拒绝识别”路径在真实日志上当前**不可用**（返回 `UNKNOWN` 而非 `DENIED`）。

---

## 2. 信任判断方法与证据来源

### 2.1 方法

`assessor.py` 采用**多重一致性交叉核对**，而非分类或评分：

1. 解析 `security/policies/minimal_permissions.xml`，定位 `enclave path=...`，检查 `services request="ALLOW"` 中是否含目标 service；
2. 解析 `security/keystore/enclaves/<role>/permissions.xml`（**DDS 生成结果**，不是源策略），要求：
   - 恰好一个 `<grant>`；
   - `default` 必须是 `DENY`（`assessor.py:132-134`）；
   - 必须有非空 `subject_name`；
   - 任意 topic 含 `*`/`?` 或命中宽权限白名单 `BROAD` 即报错（`assessor.py:31,152-153`）；
   - `<id>` 必须恰好等于 `{43}`（`assessor.py:156-157`）；
   - DDS service request 语义 = publish `rq/<svc>Request` **且** subscribe `rr/<svc>Reply`（`assessor.py:158-160`）；
3. 要求源策略判定与生成权限判定**一致**，否则 `UNKNOWN`（`assessor.py:221-222`）；
4. 要求配置结果与受控实验的预期结果一致（`assessor.py:223-224`）；
5. 要求 pinned 历史 run 的 `summary.json` 满足 `suite=sros2`、`secure_domain=43`、`failed=0`（`assessor.py:178-180`）；
6. 对 DENIED 类场景**强制要求原生拒绝文本** `[SECURITY Error] ... not found in allow rule`，并**要求同 run 的 S3C 正向对照成功**（`assessor.py:241-250`）。

### 2.2 证据来源分类

| 来源 | 路径 | 性质 |
| --- | --- | --- |
| 源策略 | `security/policies/minimal_permissions.xml` | 配置推导，**非**运行时授权 |
| 生成 DDS 权限 | `security/keystore/enclaves/<role>/permissions.xml` | 配置推导（DDS 实际加载的 ACL） |
| 受控实验摘要 | `<evidence-root>/<run>/summary.json` | `CONTROLLED_SECURITY_EXPERIMENT` |
| 客户端原始日志 | `<evidence-root>/<run>/<case>/*.log` | `RUNTIME_LOG`（含原生 Fast DDS 拒绝） |

模块在输出中如实标注：`evidence_refs[].kind` 分别为 `PERMISSION_FILE_ANALYSIS` / `CONTROLLED_SECURITY_EXPERIMENT` / `RUNTIME_LOG`；`identity_evidence.detail` 写明“历史受控实验；不证明当前请求的 DDS 身份认证”。**这一点符合任务书对该字段的语义要求。**

---

## 3. 授权 / 拒绝的实际判定

本轮在被追踪的证据根 `artifacts/acceptance/exports/m2_sros2_enforce/logs/tests_evidence`（run `20261009T093144Z`，suite=sros2，secure_domain=43，7/7 PASS）上实测：

| case | 设计应产生 | 本轮实测 | 判定 |
| --- | --- | --- | --- |
| S2 `/planner → /rg/guarded_navigate` | `AUTHORIZED` | **`AUTHORIZED`** | ✅ 正常 |
| S3C `/gateway → /rg/nav_execute` | `UNKNOWN`（资源与候选入口不同） | **`UNKNOWN`** | ✅ 符合设计 |
| S3 `/planner → /rg/nav_execute` | `DENIED` + `DDS_ACCESS_CONTROL` | **`UNKNOWN`** | ❌ **缺陷** |
| S4 `/unauthorized → /rg/nav_execute` | `DENIED` + `DDS_ACCESS_CONTROL` | **`UNKNOWN`** | ❌ **缺陷** |

### 3.1 缺陷根因（已定位并复现）

原生拒绝确实存在于日志中：

```
2026-10-12 04:14:07.551 [SECURITY Error] rr/rg/nav_execute/_action/send_goalReply
topic not found in allow rule. (./src/cpp/security/accesscontrol/Permissions.cpp:1246)
```

但真实日志带 **ANSI 颜色转义**，原始字节为：

```
... \x1b[31;1m[ \x1b[37;1mSECURITY \x1b[31;1m Error] \x1b[37mrr/rg/nav_execute...
```

而 `assessor.py:30` 的正则是：

```python
DENIAL_RE = re.compile(r'\[\s*SECURITY\s+Error\s*\].{0,600}?not found in allow rule', re.I)
```

`\[\s*SECURITY` 要求 `[` 之后紧跟可选空白再是 `SECURITY`；实际中间夹了 `\x1b[37;1m`，因此**不匹配**。实测：

- 对原始彩色日志：`DENIAL_RE.search(...)` → `None`
- 对剥离 ANSI 后的同一文本：匹配成功

`read_case_log()`（`assessor.py:202`）只做 `errors='replace'` 解码，**没有去除 ANSI**，因此 `examine()` 在 `assessor.py:243-244` 抛 `no native access-control denial in client log`，最终 `UNKNOWN`。

**影响**：模块自我定位中最有价值的一条能力——「区分配置拒绝与 DDS 实际拒绝」——在当前交付版本上**无法从真实产物中产生 `DENIED`**。注意它是**失败关闭**（`UNKNOWN`，不是 `AUTHORIZED`），因此**不构成放行绕过**，属于功能性/集成缺陷。

### 3.2 单元测试为何未发现

`tests/unit/test_identity_trust_assessor.py:38-39` 的拒绝日志 fixture 是**无颜色纯文本**：

```python
'[SECURITY Error] rr/rg/nav_execute/_action/send_goalReply topic not found in allow rule\n...'
```

因此 22 项单测全绿，但 **fixture 与真实产物不一致**。这是「测试 fixture 与真实逻辑不一致」的典型实例，不能据此认定该路径已通过验证。

---

## 4. 身份绑定的真实能力边界（关键局限）

`CASES`（`assessor.py:23-28`）把「enclave → node → 资源 → 期望状态」写死为常量表：

```python
'S2': ('/planner', 'planner_node', ENTRY, 'AUTHORIZED', 'planner.log'),
```

`examine()` 的返回值只由 `(case_id, experiment_run)` 决定；业务信封只贡献：
- `run_id` / `request_id`（原样回填）；
- 对 `candidate_action.action_resource == /rg/guarded_navigate` 与 `operation == NAVIGATE` 的强制校验（`assessor.py:66-68`）。

**因此对任意真实请求，只要 `--case S2` 且 run 有效，输出恒为 `AUTHORIZED`。** 模块**无法**区分真正的 `/planner` 与冒名者，也无法把 DDS 身份与当前 TCP/RTPS 参与者关联。

模块对此是**诚实的**：`subject.observed_name` 取自常量表而非信封；`extensions.historical_only = true`；不读取、不填充 `authenticated_identity`。**这符合任务书「严禁把业务 request_id / 自报身份当作 DDS 认证证明」的要求**，但也意味着它**不能**作为当前请求的准入依据。

> 需要注意的语义细节：`subject.declared_enclave` 字段名中带 `declared_`，但值来自受信任的常量表而非请求方自报，命名容易引起误读。建议改名或在文档中显式说明。

---

## 5. 与 F0 适配层的接口符合性

| 检查 | 结果 |
| --- | --- |
| 输出 Schema | 通过。`check_member_module.py` 报 `schema_ok=True`（4 个场景全部） |
| `run_id` / `request_id` 一致 | 通过（ID-01 / ID-02） |
| `event_id` 含 `request_id` | **FAIL（ID-03）**：`evt-identity-<uuid24>` 不含 `request_id` |
| 非法 JSON / 坏版本 / 缺字段 → 失败关闭 | 通过（ERR-01/03/04） |
| 适配层对畸形信封阻断 | 通过（ADP-01） |
| 超时 → 阻断 | 通过（LIM-01） |
| stdout 超限 | FAIL（LIM-02），但**对三个模块与 Mock 一致**，疑为验收脚本自身问题（见 `INTEGRATION_READINESS.md` §5） |

`event_id` 不含 `request_id` 会削弱审计链路中「模块事件 ↔ 业务请求」的关联能力，属 P2。

---

## 6. 安全审查

### 6.1 做得好的部分（E2_STATIC）

- **不接受超时作为拒绝证据**：`assessor.py:241-243` 显式注释 *"TIMEOUT alone is never a DDS denial"*；
- **拒绝宽权限**：`BROAD` 白名单 + `*`/`?` 检测，且注释声明 “No implicit wildcard: a malformed/wide-open policy must not be reported safe”；
- **必须有正向对照**：任何 DENIED 判定都要同 run S3C 成功作为对照（`assessor.py:245-249`）；
- **XML 安全**：拒绝 `<!DOCTYPE` / `<!ENTITY`（`assessor.py:91-92`），防 XXE / billion-laughs；2 MB 上限；拒绝符号链接；
- **路径安全**：`SAFE_NAME` 白名单校验 run ID，`resolve()` + `is_relative_to` 防穿越（`assessor.py:169-173,200`）；
- **严格 JSON**：重复键报错、非有限数报错（`assessor.py:42-54`）；
- **不读私钥**：只引用 `permissions.xml`，不加载 `key.pem`（与其文档一致，本轮核实其代码中无 `.pem` 读取）；
- **失败关闭**：任何异常 → `UNKNOWN`，且 `reason` 写明原因，同时写 stderr。

### 6.2 风险与缺陷

| 级别 | 问题 | 位置 |
| --- | --- | --- |
| **P1** | ANSI 彩色日志导致原生 DDS 拒绝不被识别，`DENIED` 永不产生 | `identity_trust/assessor.py:30` + `:202` |
| **P2** | `event_id` 不含 `request_id`，审计关联受限 | `identity_trust/assessor.py:280` |
| **P2** | 默认证据根 `tests/evidence` 被 `.gitignore` 忽略，新克隆环境不可用（见 §7） | `identity_trust/assessor.py:318` |
| **P2** | 依赖 `jsonschema>=4.0`，在 3.x 环境下**所有**输入都返回 rc=2 | `identity_trust/assessor.py:74-82` |
| **P3** | 输出状态与当前请求无因果关系，容易被误读为「实时认证通过」 | `identity_trust/assessor.py:23-28,251-253` |
| **P3** | 对日志的 `errors='replace'` 可能静默替换损坏字节，缺少对替换字符的显式拒绝 | `identity_trust/assessor.py:202` |

**未发现 P0**：不存在放行绕过、不存在把自报身份当认证、不存在 UNKNOWN/ERROR 被当作允许。

---

## 7. 可复现性与依赖

- **`security/keystore/` 与 `tests/evidence/` 均被 `.gitignore` 忽略**（实测 `git check-ignore`：`.gitignore:8:/tests/evidence/`；`security/keystore/` 亦在忽略列表）。因此：
  - 新克隆仓库**没有** `tests/evidence/<run>`，模块默认参数必然 `UNKNOWN`；
  - 新克隆仓库**没有** `enclaves/*/permissions.xml`，`permission_permits` 直接报 `missing or unsafe XML`；
  - 二者都需要先跑 `scripts/setup_sros2.sh` 重新生成。
- **被追踪的可用证据**在 `artifacts/acceptance/exports/m2_sros2_enforce/logs/tests_evidence/20261009T093144Z/`（7/7 PASS，domain 43），但**成员二的配置与文档都没有指向这里**，而是指向未追踪的 `tests/evidence`。这是一处应当修掉的「配置 ↔ 证据」错配。
- 具体运行命令（本轮实测可用）：

```bash
python3 identity_trust/assessor.py \
  --experiment-run 20261009T093144Z --case S2 \
  --evidence-root artifacts/acceptance/exports/m2_sros2_enforce/logs/tests_evidence \
  < docs/interfaces/examples/module_input_valid.json
```

---

## 8. 成果 A / 成果 B 的区分（任务书要求）

| | 成果 A：既有 SROS 2 / DDS-Security Enforce 安全基础实验 | 成果 B：成员二新增的 `IdentityTrustAssessment` 解释器 |
| --- | --- | --- |
| 归属 | 基线既有（`tests/integration/sros2_check.py`、`scripts/setup_sros2.sh`、`security/`） | 成员二交付 |
| 证据 | `tests/evidence/20261012T041401Z`（7/7 PASS）、`artifacts/acceptance/exports/m2_sros2_enforce/.../20261009T093144Z`（7/7 PASS），均为**历史运行记录** | 源码 + 22 项单测 + 本轮实跑 |
| 本轮是否复跑 | **否**（需启动 `rg_jazzy` 容器，按任务书不得干扰他人容器） | 是 |
| 证据等级 | **B**（源码 + 可核对的原始日志，本轮未独立复现） | 见 §9 |
| 能否证明成员二算法 | **不能**。成果 A 的 PASS 属于既有系统的安全基础能力，不能直接记到成果 B 名下 | — |

`security/policies/minimal_permissions.xml` 的最小权限设计经本轮人工核对**确实是最小权限**：`/planner` 只能向 `/rg/guarded_navigate` 发 `send_goal`，**不能**向 `/rg/nav_execute` 发；`/gateway` 才能操作 `/rg/nav_execute`；`/unauthorized`（`rogue_client`）两者皆无。这与 S2/S3/S4 的预期一致。

---

## 9. 证据等级评定

| 结论 | 等级 | 说明 |
| --- | --- | --- |
| `assessor.py` 是离线证据解释器，非在线认证器 | **A** | 源码 + 本轮实跑行为一致 |
| S2 → `AUTHORIZED` | **A** | 源码 + 被追踪的真实 SROS2 日志 + 本轮实跑复现 |
| S3C → `UNKNOWN`（防跨资源放行） | **A** | 同上 |
| S3/S4 → `UNKNOWN`（应为 `DENIED`） | **A** | 缺陷已定位并复现两处证据根 |
| 单测 22 passed | **A** | 本轮复测（`.research-venv`，0.12s） |
| 既有 SROS 2 Enforce 7/7 PASS | **B** | 原始日志与 summary 可核对，本轮未复跑 |
| `team_demo` 联合联调可用 | **A** | 本轮实测（见 `INTEGRATION_READINESS.md`） |
| 「支持当前请求实时认证」 | **N** | 无证据，且与源码结构矛盾 |

---

## 10. 最终评价

**研究贡献**：给出了一条可审计的「配置推导 ↔ 受控实验 ↔ 原生拒绝日志」三方交叉核验路径，并且把「不得把配置许可当作运行时授权」这一安全原则**落实到了代码与输出字段**（`historical_only`、`evidence_refs[].kind`、拒绝超时作为证据）。这套 fail-closed 的证据纪律是本模块最有价值的部分。

**局限**：
1. 不构成在线认证，无法对当前请求做身份判定；
2. 原生 DDS 拒绝识别在真实彩色日志上失效（P1）；
3. 证据链依赖两个未被版本控制的目录（`security/keystore/`、`tests/evidence/`），可复现性受环境重建能力制约。

**集成建议**：**修改后集成**。修复 P1（去 ANSI 或在正则中容忍转义序列）并把配置/文档的证据根改到被追踪的 `artifacts/acceptance/exports/m2_sros2_enforce/logs/tests_evidence`，可作为一个**证据解释型**模块接入；在文档与竞赛材料中必须始终限定为「历史受控实验证据解释」，**不得**表述为 DDS 身份认证或实时鉴权。

**验收门槛**：`MEMBER2_CODE_AUDIT` = **PARTIAL**（源码已审、缺陷已定位）；`MEMBER2_SECURITY_EVIDENCE` = **PARTIAL**（既有 Enforce 实验有 B 级证据，成员二解析器未能在真实日志上产出 DENIED）。
