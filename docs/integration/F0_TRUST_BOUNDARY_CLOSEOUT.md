# F0 身份信任边界关闭报告（P0）

> 契约：`PROPOSED_V1` / `1.0.0-proposed`（未冻结）
> 修复提交（`VERIFIED_CODE_SHA`）：`4e83f9190596d71f5b887c613d3f509578a9c497`
> 基线：`integration/three-real-online` @ `e18598d78cbdadd3f2166f0dfcc33293eac0d3c5`
> 验证证据：`artifacts/integration/f0-trust-closeout/f0close-20261018T082739Z/`

---

## 1. 原漏洞

### 1.1 现象

修复前，F0（`scripts/team_demo.py`）对"当前请求身份"的判定只有两个条件：

```python
current.get('status') == 'AUTHENTICATED'
and current.get('historical_only') is not True
```

`current` 来自 `outputs['identity_trust']['extensions']['current_request_identity']`，
而 `outputs` 是**外部进程写出的 JSON**。因此任何模块——只要它能输出合法
`IdentityTrustAssessment`——都可以自行写一个 `AUTHENTICATED` 并获得
`READY_FOR_GATEWAY_SUBMISSION`，而它：

- 不持有任何签名密钥；
- 不在任何受信任签发者清单里；
- 没有账本记录，也没有任何 DDS 身份证据。

### 1.2 最小复现（修复前实测）

构造一个模块，把它能控制的字段全部填成"通过"：

```json
"extensions": {"current_request_identity": {
  "status": "AUTHENTICATED",
  "evidence_kind": "SIGNED_ATTESTATION",
  "binding": "CURRENT_REQUEST_BOUND_TO_AUTHENTICATED_DDS_SUBJECT",
  "historical_only": false,
  "checks": {"signature": "VALID", "issuer": "VERIFIED_IDENTITY_SOURCE",
             "request_binding": "MATCH", "freshness": "OK",
             "replay": "RESERVED"}}}
```

**修复前实测结果**：

| 项 | 值 |
| --- | --- |
| F0 返回码 | **0** |
| decision | **`READY_FOR_GATEWAY_SUBMISSION`** |
| reason_code | `ADAPTER_OK` |
| detail | "三个模块状态均为推进状态且全部校验通过" |

即一个只会 `print` 的脚本可以让 F0 放行，且**没有任何一项真实核验发生过**。

### 1.3 为什么"调用 f0_accepts(current)"不算修复

`identity_trust/current_identity.py:f0_accepts()` 检查的是**同一个字典**里的字段：

```python
current.get('checks', {}).get('signature') == 'VALID'
current.get('checks', {}).get('issuer') == 'VERIFIED_IDENTITY_SOURCE'
...
```

这仍然是"读外部进程写出的结论"。伪造者可以把这六个字段一起写出来。
**证据完整性、来源可信、当前身份绑定可信**这三件事，没有任何一件能通过
"读取被验证对象自己写的通过标记"来建立。

修复的关键不是"检查更多字段"，而是**换一个核验主体**：由 F0 自己去核验原始证据。

---

## 2. 修复架构

### 2.1 谁核验、拿什么核验

| 问题（任务书 §6.1） | 本修复的回答 |
| --- | --- |
| F0 能信任的身份验证组件是哪一个 | `identity_trust/current_identity.py:verify()`，由 **F0 进程自己调用**；它是代码，不是外部进程的报告 |
| F0 如何取得原始身份证据 | 从**受信任本地配置** `identity_attestation.witness_path` 读取原始证据字节；**不**从信封、**不**从模块输出 |
| 签发者信任如何配置 | `identity_attestation.issuers_path` 指向受信任签发者清单（`trusted-identity-issuers/1`）；只有 `VERIFIED_IDENTITY_SOURCE` 才可能得到 `AUTHENTICATED` |
| 签名密钥由谁持有 | F0 侧 `identity_attestation.key_path`（权限必须 0600）；模块进程无法读取或影响 |
| 当前请求内容由谁提供并核对 | F0 用**自己收到的信封**计算 `request_digest()`，与证据中的 `request_digest`、`request_id`、`resource`、`operation` 比对 |
| 如何禁止业务 JSON 自选密钥/凭据/签发者 | 所有路径只来自受信任配置文件；F0 代码里没有任何从信封或模块输出取路径的分支；路径必须是**绝对路径** |
| nonce 由谁最终消费 | **F0**（唯一权威消费路径）。M2 若与 F0 指向同一 witness，视为配置冲突直接拒绝 |
| 如何防止重复消费导致合法请求被判重放 | 见 §2.3 |
| 如何防止测试签发者进入正式运行 | 受信任清单里 `TEST_ONLY` 的签发者只能得到 `AUTHENTICATED_TEST_ONLY`，F0 要求恰好 `AUTHENTICATED`；`test_issuer.py` 本身拒绝 `--trust verified` |
| 如何证明签发者能观察 DDS 认证身份 | **当前无法证明，也未被证明**。这是尚未完成的生产能力，见 §5 |

### 2.2 实现要点

`scripts/team_demo.py` 新增：

- `_load_identity_attestation(config)`：解析并校验受信任配置块；
- `verify_identity_attestation(config, envelope)`：加载原始证据 → 调用
  `ci.verify()` → 返回可安全记录的结论（绝不含密钥或签名原文）；
- 判定改为**分模式**：严格模式用上述核验结果，受控模式走旧的模块自报路径。

严格模式下，`extensions.current_request_identity` **不再参与推进判定**。
模块自报的内容只在输出里留下痕迹供事后比对，无法改变结论。

### 2.3 nonce 只能有一个权威消费路径

`verify()` 内部会对证据的 nonce 做**原子预留**（`flock` 临界区内重读→判重→追加→fsync）。
若 M2 与 F0 各自核验同一份凭据，第二次必然被判为"重放"，
合法请求会被误杀；若两者用不同账本，防重放语义又会互相污染。

本修复的处理：

1. **F0 是正式凭据的唯一权威消费者。**
2. F0 在配置校验阶段就检查：若 `identity_trust` 模块命令里的
   `--identity-witness` 与 `identity_attestation.witness_path` 指向同一文件，
   **直接判配置非法**（`ADAPTER_IDENTITY_ATTESTATION_CONFIG_INVALID`），
   而不是等到运行时才发现重放。
3. M2 仍可保留自己的 witness 用于**分析**，但那是另一份材料/另一个账本，
   且**不构成** F0 的推进依据。
4. 没有任何"关闭重放检查"的开关。

### 2.4 两种模式

| 模式 | 由谁决定 | 身份依据 | 输出标注 | 用途 |
| --- | --- | --- | --- | --- |
| `STRICT`（**默认**，不写配置块即为严格） | 受信任本地配置 | F0 自行核验原始证据 | `verified_by=F0_LOCAL_VERIFIER` | 真实运行 |
| `CONTROLLED_TEST_ONLY` | 受信任本地配置，且必须给 `controlled_reason` | 模块自报 | `verified_by=MODULE_SELF_REPORT` + `caveat` + detail 注明"受控身份模式" | RC2 受控演示、单元测试 |

相关原因码：

| 原因码 | 含义 |
| --- | --- |
| `ADAPTER_CURRENT_IDENTITY_UNBOUND` | 拿不到可信的当前身份绑定（严格模式无材料/文件缺失/核验组件不可用）。**语义与修复前一致**，精确子原因见 `identity_attestation.detail_code` |
| `ADAPTER_IDENTITY_ATTESTATION_UNVERIFIED` | `detail_code`：严格模式缺少可核验材料 |
| `ADAPTER_IDENTITY_ATTESTATION_REJECTED` | 证据存在但核验失败（签名/签发者/绑定/新鲜度/重放/权限） |
| `ADAPTER_IDENTITY_ATTESTATION_CONFIG_INVALID` | 身份核验配置本身非法（相对路径、缺密钥、与 M2 争抢凭据、未知模式、受控模式缺理由） |

---

## 3. 修复后的反例（全部强制测试）

文件：`tests/unit/test_f0_identity_trust_boundary.py`（**27 项**）
+ `tests/unit/test_phase2_security_boundaries.py`（原 2 项 xfail 已转为强制断言）

| 情形 | 严格模式结果 | 原因码 |
| --- | --- | --- |
| 只伪造 `AUTHENTICATED` | BLOCK | `CURRENT_IDENTITY_UNBOUND`（detail: `ATTESTATION_UNVERIFIED`） |
| **伪造完整 `checks` 六字段** | **BLOCK** | 同上 |
| 伪造 checks + 真实证据签名被破坏 | BLOCK | `ATTESTATION_REJECTED` |
| 顶层历史 `AUTHORIZED` | BLOCK | 同上 |
| `historical_only=true` | BLOCK | 同上（受控模式下也仍被旧规则阻断） |
| Mock 身份模块 | BLOCK | 同上 |
| TEST_ONLY 签发者 | BLOCK | `ATTESTATION_REJECTED`（status=`AUTHENTICATED_TEST_ONLY`） |
| 自报"可信 DDS Enclave" | BLOCK | 同上 |
| 无原始凭据 | BLOCK | 同上 |
| 证据文件缺失 | BLOCK | 同上 |
| 只给 witness 不给密钥 | BLOCK | `CONFIG_INVALID` |
| 相对路径 | BLOCK | `CONFIG_INVALID` |
| 签名错误 | BLOCK | `ATTESTATION_REJECTED` |
| 签发者不在受信任清单 | BLOCK | `ATTESTATION_REJECTED`（`WITNESS_ISSUER_UNTRUSTED`） |
| 请求内容摘要错配 | BLOCK | `ATTESTATION_REJECTED`（`request_binding=MISMATCH`） |
| 资源/操作错配 | BLOCK | `ATTESTATION_REJECTED` |
| 凭据过期 | BLOCK | `ATTESTATION_REJECTED`（`freshness=STALE`） |
| nonce 重放 | BLOCK | `ATTESTATION_REJECTED`（`replay=REPLAYED`） |
| 账本不可用 | BLOCK | `ATTESTATION_REJECTED`（`replay=LEDGER_UNAVAILABLE`） |
| 账本损坏 | BLOCK | `ATTESTATION_REJECTED` |
| 密钥文件权限过宽（0644） | BLOCK | `ATTESTATION_REJECTED` |
| 签发者清单权限过宽（0644） | BLOCK | `ATTESTATION_REJECTED` |
| M2 与 F0 共用同一 witness | BLOCK | `CONFIG_INVALID` |
| 受控模式但无 `controlled_reason` | BLOCK | `CONFIG_INVALID` |
| 未知模式字符串 | BLOCK | `CONFIG_INVALID` |

**所有阻断都发生在 F0 层**，不依赖 Gateway 事后补救。

### 3.1 正向路径（受控构造）

用**人工构造的合成受信任签发者清单**（`trust: VERIFIED_IDENTITY_SOURCE`）
+ 真实 HMAC 证据，可得到 `READY_FOR_GATEWAY_SUBMISSION`，
`identity_attestation.verified_by = F0_LOCAL_VERIFIER`，`checks` 六项全部为
真实核验结果（`signature=VALID`、`issuer=VERIFIED_IDENTITY_SOURCE`、
`request_binding=MATCH`、`freshness=OK`、`replay=RESERVED`）。

这证明**核验代码正确**，但**不**证明生产身份能力：该签发者是测试构造，
系统中并不存在经审核的生产签发者。

---

## 4. RC2 受控演示兼容性

RC2 的六个在线场景使用 `config/team_modules.member3.real.yaml`
（`identity_trust` 为 MOCK）。严格模式会拒绝这种自报，因此该配置被
**显式**标注为受控模式：

```yaml
identity_attestation:
  mode: CONTROLLED_TEST_ONLY
  controlled_reason: "RC2 受控演示：identity_trust 为 MOCK，身份结论来自模块自报，不构成真实 DDS 身份认证"
```

同样处理：`team_modules.example.yaml`、`member1.real.yaml`、`member3.yaml`、
以及验收器探针配置（`check_member_module._write_probe_config`）与
测试辅助 `write_config`（默认受控，**需要安全边界的用例必须显式传 STRICT**）。

保持**严格**（不写该块）的配置：`team_modules.three-real.yaml`、
`team_modules.all-real.yaml`、`team_modules.all-real.controlled-test.yaml`、
`team_modules.member2.real.yaml`。

### 4.1 兼容性要求逐条对照

| 要求 | 落实 |
| --- | --- |
| 严格真实模式默认不接受 Mock 身份 | ✅ 不写配置块即为 `STRICT` |
| 正式运行不得自动降级 | ✅ 代码中没有任何降级分支；模式只来自配置 |
| 受控模式必须显式启用并标识限制 | ✅ 必须给 `controlled_reason`，输出带 `verified_by=MODULE_SELF_REPORT` 与 `caveat` |
| 模式只能来自受信任配置 | ✅ 路径/模式均不从信封读取 |
| 受控模式 READY 不得声称真实认证 | ✅ detail 写明"受控身份模式"，`verified=false` |
| 不允许任意配置轻易变成无身份检查 | ✅ 必须显式写 `mode` + 非空理由；未知模式报错而非忽略 |
| Gateway 与 DDS 权限始终有效 | ✅ 未改动，Enforce 复验 7/7 |

---

## 5. 仍然缺少的生产能力

**当前不存在真正可信的生产 DDS 身份签发者。**

- `identity_trust/test_issuer.py` 只能签发 `TEST_ONLY` 证据，不能声称已验证来源；
- ROS 2 Jazzy / rclpy 不向订阅端暴露"该样本发布者已完成 DDS 认证的主体身份"；
  DDS-Security 的认证发生在参与者建链阶段，不随消息传递；
- 因此严格真实在线模式下，M2 只能给出 `current_request_identity = UNKNOWN`，
  F0 正确阻断。

**这不构成本轮修复的失败。** 本轮目标是"不让伪造声明放行"，该目标已达成；
"让 M2 具备可信当前身份"是长期目标，仍被真实技术条件阻断。

---

## 6. 新的信任假设（必须明示）

修复引入了以下显式信任假设，它们**不是**自动成立的，需要运维保证：

| # | 信任假设 | 若不成立 |
| --- | --- | --- |
| A1 | 受信任配置文件（含 `identity_attestation`）不被攻击者修改 | 攻击者可指向自己构造的证据与密钥，从而"合法地"伪造身份 |
| A2 | 签发者确实具备观察 DDS 认证身份的能力，且其密钥受保护 | 签名与清单只能证明"谁说的"，不能证明"它有资格说" |
| A3 | 账本文件所在目录对 F0 可写且不被替换 | 账本被替换/回滚会削弱防重放 |
| A4 | `identity_trust` 包代码未被篡改 | 核验逻辑本身被替换则一切失效 |

其中 **A2 是当前最关键的未证明项**：系统没有机制验证签发者的资质，
只有"它出现在受信任清单里"这一人工审批事实。

---

## 7. 修复带来的影响

| 方面 | 影响 |
| --- | --- |
| 安全 | 外部模块无法仅凭自报字段获得 READY；所有身份材料来自 F0 的受信任边界 |
| 兼容 | RC2 六场景通过显式受控模式保持可用；`ADAPTER_CURRENT_IDENTITY_UNBOUND` 语义不变 |
| 运维 | 严格模式需要配置 witness/key/issuers/ledger 四件材料；缺失即阻断（失败关闭） |
| 可观测 | 输出新增 `identity_attestation`，含模式、核验者、状态、六项 checks、签发者信任等级 |
| 性能 | 每次判定增加一次 HMAC 校验与一次账本 flock 追加，实测可忽略 |

---

## 8. 结论

- **P0 漏洞已关闭**：伪造 `AUTHENTICATED`、伪造完整 `checks`、Mock 身份、
  TEST_ONLY 签发者、自报 Enclave、历史授权、签名/绑定/新鲜度/重放/权限异常
  —— 全部在 F0 层阻断，共 25 类情形 + 2 项原 xfail 转为强制断言。
- **原两项 xfail 已成为真正的 PASS，且 0 项 xfailed 残留。**
- **RC2 受控演示能力保留**，但被明确标注为"非真实身份认证"。
- **生产身份能力仍然缺失**，严格真实模式继续阻断，`THREE_EXTERNAL_ONLINE_PROCEED=BLOCKED`。
