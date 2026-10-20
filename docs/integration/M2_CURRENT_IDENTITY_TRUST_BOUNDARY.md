# M2 当前身份：信任边界与核验语义（第二阶段 P0-1）

| 项 | 值 |
| --- | --- |
| 结论 | **未取得当前请求已认证 DDS 身份的可信证明**；生产路径恒为 `UNKNOWN` |
| 核验器 | `identity_trust/current_identity.py`（contract `current-identity-attestation/2`） |
| 测试签发器 | `identity_trust/test_issuer.py`（**TEST_ONLY**，只能产出 `AUTHENTICATED_TEST_ONLY`） |
| 受信任签发者清单 | **仓库不交付**（`config/` 下不存在任何 `*issuer*` 文件，测试断言此点） |
| 证据 | `docs/integration/evidence/PHASE2_EVIDENCE.json` → `m2_verification_matrix` |

---

## 1. 一句话结论

**HMAC 签名有效 ≠ DDS 身份已认证。** 签名只证明"持有密钥的人写了这些字段"。
因此核验器把"字节完整性"与"身份来源可信"拆成两件独立的事，并且只有当签发者
被一份**受信任清单**标记为 `VERIFIED_IDENTITY_SOURCE` 时才可能返回
`AUTHENTICATED`。本仓库不交付这样的清单，也不存在能签发它的组件。

## 2. 逐项回答审查清单（P0-1 的 10 个问题）

| # | 问题 | 核查结论 | 处置 |
| --- | --- | --- | --- |
| 1 | 签名由谁产生？ | 生产环境**没有**签发者；`test_issuer.py` 只是测试夹具 | 明确标注 TEST_ONLY，并拒绝非 `test-only:` 前缀 |
| 2 | 签发者是否实际获得经核验的 DDS 主体身份？ | **否**。ROS 2 Jazzy/rclpy 不向订阅端暴露样本发布者身份 | 契约要求 `issuer.identity_source`，但该字段本身只是声明；真正开关是受信任清单 |
| 3 | 密钥是否可能被业务调用方或普通模块获取？ | 密钥路径只能来自受信任配置；但**同机同用户**的其它进程仍可读（除非权限收紧） | 密钥必须 `0600`，否则拒绝；不做"进程隔离"的虚假承诺 |
| 4 | 签发者与接收者是否有权限隔离？ | 有（不同进程、不同密钥文件），但**同一 uid** 下不是强制隔离 | 记录为残余风险 R-1 |
| 5 | 业务 JSON 能否选择证据路径/密钥/身份？ | **否**。三者只来自进程参数；`envelope` 只用于比对 | 测试 `test_self_reported_identity_in_envelope_never_authenticates` |
| 6 | 同一证据能否跨请求/资源/操作/安全域复用？ | 不能：证据绑定 `request_id` + 资源 + 操作 + **请求摘要**（含 task_id 与目标点） | `checks.request_binding`；三项不匹配用例 |
| 7 | nonce 账本是否有并发竞争？ | **原来有**（先查后写）。现已改为 `flock(LOCK_EX)` 内"重读-判重-追加-fsync" | 8 进程并发测试：恰好 1 个 RESERVED |
| 8 | 账本损坏/不可写时是否失败关闭？ | **原来会静默失去防重放**（ledger=None 仍放行）。现在 AUTHENTICATED 必须 RESERVED | 缺账本 / 账本损坏 / 账本是目录 / 账本是符号链接 四类用例 |
| 9 | 符号链接、TOCTOU、权限、属主、路径替换？ | 原实现有 `getsize` 后 `open` 的 TOCTOU 与符号链接风险 | 改为 `O_NOFOLLOW` + `fstat` + 从 fd 读取；密钥/清单要求 0600 |
| 10 | 有效 HMAC 能否为"自报身份"签名？ | **能**，这就是原设计最大的问题 | 见第 3 节：把签发者信任独立出来 |

## 3. 判定模型（`checks` 五元组）

```json
{
  "status": "UNKNOWN | DENIED | AUTHENTICATED_TEST_ONLY | AUTHENTICATED",
  "evidence_kind": "NONE | SIGNED_ATTESTATION",
  "historical_only": false,
  "checks": {
    "signature":       "VALID | INVALID | NOT_PRESENT",
    "issuer":          "VERIFIED_IDENTITY_SOURCE | TEST_ONLY | NOT_LISTED | NOT_DECLARED | ERROR | NOT_EVALUATED",
    "request_binding": "MATCH | MISMATCH | NOT_CHECKED",
    "freshness":       "OK | STALE | FROM_FUTURE | INVALID | NOT_CHECKED",
    "replay":          "RESERVED | REPLAYED | LEDGER_UNAVAILABLE | LEDGER_ERROR | NONCE_INVALID | NOT_RESERVED"
  },
  "verifier": {"contract": "current-identity-attestation/2", "version": "2.0.0"}
}
```

判定顺序（有意如此）：**签名 → 字段 → 请求绑定 → 新鲜度 → 签发者信任 → 原子预留**。

* 绑定先于信任：证据属于别的请求时，无论签发者多可信都必须先拒绝；
* 信任先于预留：不可信签发者不得消耗账本条目（避免被用来刷日志/放大写入）。

只有五元组全部为 `VALID / VERIFIED_IDENTITY_SOURCE / MATCH / OK / RESERVED` 且
`evidence_kind == "SIGNED_ATTESTATION"`、`historical_only == false` 且状态为
`AUTHENTICATED`，`f0_accepts()` 才返回 `True`。

## 4. 实测矩阵（`CONTROLLED_TEST` 签发者）

| 用例 | 结果 | f0_accepts |
| --- | --- | --- |
| 无证据 | UNKNOWN（NOT_EVALUATED） | False |
| 签名有效、签发者不在清单 | **UNKNOWN**（NOT_LISTED） | False |
| 签名有效、签发者 TEST_ONLY | AUTHENTICATED_TEST_ONLY | False |
| 签名有效、签发者 VERIFIED + 账本 | AUTHENTICATED | True |
| 同一证据第二次使用 | UNKNOWN（RESERVED→REPLAYED） | False |
| 未配置账本 | UNKNOWN（LEDGER_UNAVAILABLE） | False |
| 账本路径是目录 | UNKNOWN（LEDGER_ERROR） | False |
| 密钥 0644 | UNKNOWN（权限过宽，拒绝读取） | False |

原始数据：`docs/integration/evidence/PHASE2_EVIDENCE.json`。

## 5. 为什么"受信任清单"不是自欺欺人

清单是**受信任本地配置**的一部分，它的存在本身是一次安全评审决策：只有"确实
掌握真实身份来源"的组件才应被写入。核验器能做的到此为止——它不能凭空判断
一个签发者是否真的看到了 DDS 认证事件。因此：

* 仓库**不提供**清单，生产路径恒为 UNKNOWN；
* 任何"我写个清单就能认证"的做法都是运维决策，不是本模块的能力；
* 未来真实来源出现时，只需新增清单（代码不改），并补一条独立实验证据。

## 6. 仍未解决的阻断（不得写成通过）

| 编号 | 阻断项 | 影响 |
| --- | --- | --- |
| R-1 | 密钥与核验器同 uid 运行，无强制进程隔离 | 同机同用户进程可读取密钥文件；需 OS 级隔离（不同 uid / 容器 / TPM）才能真正抬高门槛 |
| R-2 | 无真实签发者 | 当前身份恒 UNKNOWN；`ONLINE_PROCEED_READY` 保持 FAIL |
| R-3 | 依赖文件系统权限表达信任 | 若账本/密钥目录被替换（同 uid），防护失效；需只追加存储或外部服务 |
| R-4 | 无"安全域"绑定 | 证据未绑定 DDS domain/partition；跨域复用只能靠 `resource` 与 `request_digest` 间接限制 |

## 7. B1 需要配合的一件事（P0-2）

F0 目前只比较 `extensions.current_request_identity.status` 字符串。实测反例：
一个只写 `"status": "AUTHENTICATED"` 的模块即可让适配层给出
`READY_FOR_GATEWAY_SUBMISSION / ADAPTER_OK`（见证据 JSON 的
`f0_identity_trust_gap`）。

要求的改法（一行即可复用本模块的判定）：

```python
from identity_trust.current_identity import f0_accepts
current = (outputs['identity_trust'].get('extensions') or {}).get(
    'current_request_identity')
if not f0_accepts(current):
    raise AdapterBlock(REASON_CURRENT_IDENTITY_UNBOUND, ...)
```

本工作**没有**修改 `scripts/team_demo.py`（按分工由 B1 主导）。仓库里有两个
`xfail` 用例记录了该缺口：`tests/unit/test_phase2_security_boundaries.py`
中的 `test_f0_rejects_bare_status_self_report` 与
`test_f0_rejects_mock_fixture_identity`。B1 修复后把它们改成普通断言即可。
