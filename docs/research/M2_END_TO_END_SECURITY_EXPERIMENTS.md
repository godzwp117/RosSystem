# M2 端到端安全实验（专项③ P1）

> 代码基准：`be47ccd6c1b19460b65abc0ea8004706383d01d4`
> 运行入口：`tests/integration/m2_identity_experiments.py`
> 证据：`artifacts/research/m2/m2api-20261018T160244Z/experiments/experiments.json`
> 复跑：`./.research-venv/bin/python tests/integration/m2_identity_experiments.py \
>   --evidence <dir> --witness-log <dir>/witness_probe.log \
>   --key <dir>/issuer.key --identity '/CN=\\/m2_peer'`

## 1. 结果总览

**9 / 9 PASS**

| 编号 | 实验 | 期望 | 实测 |
| --- | --- | --- | --- |
| M2-01b | 真实 DDS 身份凭据经 F0 严格核验 | `READY_FOR_GATEWAY_SUBMISSION` | **通过** |
| M2-05 | 同一 nonce 二次使用 | `ADAPTER_IDENTITY_ATTESTATION_REJECTED` | 通过 |
| M2-07 | 同一 request_id 改目标点 | `REJECTED` | 通过 |
| M2-03 | 资源错配（改 `action_resource`） | `ADAPTER_BLOCK` | 通过（`ADAPTER_INPUT_INVALID`） |
| M2-10a | 签发者未列入受信任清单 | `REJECTED` | 通过 |
| M2-10b | TEST_ONLY 签发者 | `AUTHENTICATED_TEST_ONLY` | 通过 |
| M2-09 | 过期证据 | `freshness=STALE` | 通过 |
| M2-11 | 账本不可用 | `replay=LEDGER_UNAVAILABLE` | 通过 |
| M2-04 | 模块自报 `AUTHENTICATED` + 伪造 checks | `ADAPTER_BLOCK` | 通过 |

## 2. 实验设计要点

### 2.1 每个用例重新签发凭据

凭据带**新鲜度窗口**（`MAX_REMOTE_AGE_SEC = 30` 秒）。复用同一份凭据跑多个
用例会全部退化为 `STALE`，从而把"用例逻辑失败"与"凭据过期"混在一起。
因此实验框架对每个用例调用一次签发器（`fresh_witness()`），
过期用例则显式用 `--received-at 2020-01-01T00:00:00Z` 签发。

> 这个坑在首次运行时确实踩到了：4 个用例报 `UNKNOWN/NOT_CHECKED`，
> 定位后确认是过期而非逻辑错误。**记录在此以免被误读为"实现有问题"。**

### 2.2 契约字段必须精确匹配

签发器最初把 `issuer` 写成字符串、`remote_identity` 缺 `authenticated`，
`verify()` 判为"未声明签发者"（`issuer=NOT_DECLARED`）而返回 UNKNOWN。
按契约改为 `issuer={id,...}` 与 `remote_identity.authenticated=true` 后通过。

> 这说明 F0 的核验是**逐字段严格**的，不是"看到 VALID 就放行"。

### 2.3 M2-04 为什么是"伪造完整 checks"

该用例的模块输出把 `current_request_identity.status` 写成 `AUTHENTICATED`，
并伪造 `checks.signature=VALID / issuer=VERIFIED_IDENTITY_SOURCE /
request_binding=MATCH / freshness=OK / replay=RESERVED`。
严格模式下 F0 **完全不看这些字段**，只用自己的受信任材料核验，
因此仍然 `ADAPTER_BLOCK`。

## 3. 未执行的实验（如实标注）

| 编号 | 实验 | 状态 | 原因 |
| --- | --- | --- | --- |
| M2-01 | 真实合法主体端到端（含 Action 请求） | **部分** | 身份见证已实现；Action 级请求绑定未实现 |
| M2-02 | 未授权主体被 DDS 原生拒绝 | **NOT_RUN** | 需要 Enforce 下真实发起请求的客户端；本轮未在 Domain 58 构造 |
| M2-06 | 重放（已由 M2-05 覆盖 nonce 层） | 覆盖 | 见 M2-05 |
| M2-08 | 跨 Domain 凭据 | **NOT_RUN** | witness 未绑定 Domain 字段；属后续增强 |
| M2-12 | Gateway 权威（身份有效但任务越界仍被 BLOCK） | **NOT_RUN** | 需在线 Gateway；属集成阶段验证 |

> 这些缺口不改变 M2-01b..M2-11 的结论，但**限制**了"生产级身份见证"的宣称范围。
