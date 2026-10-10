# F0 研究模块模拟实现（Mock）

本目录提供三个研究模块的**模拟实现**，用于在真实算法尚未开发时，
让适配层、进程协议与安全失败行为可以先行开发和验证。

> **这不是安全算法，不构成任何安全保证。**
> 所有输出的 `producer.source` 均为 `MOCK`，`evidence_refs[].kind` 均为 `MOCK`。
> 模拟实验的结果**不得**被当作 DDS 认证或真实安全实验结论。

## 模块

| 文件 | 输出接口 | 可选状态 |
| --- | --- | --- |
| `comm_risk_mock.py` | `CommRiskEvidence` | `NORMAL` / `SUSPICIOUS` / `UNKNOWN` / `ERROR` |
| `identity_trust_mock.py` | `IdentityTrustAssessment` | `AUTHORIZED` / `DENIED` / `UNKNOWN` / `ERROR` |
| `task_risk_mock.py` | `TaskRiskDecision` | `ALLOW_RECOMMENDED` / `BLOCK_RECOMMENDED` / `UNKNOWN` / `ERROR` |

## 进程协议

```text
stdin  : 一个 ModuleInputEnvelope（JSON 对象）
stdout : 一个对应接口的输出（JSON 对象），不得混入调试文本
stderr : 诊断信息
退出码 : 0 正常执行（不代表结论为允许）；2 输入问题；3 内部错误；其他非零表示异常
```

## 调用方式

```bash
python3 mock_modules/comm_risk_mock.py < envelope.json
```

## 测试用行为控制

在输入信封的 `observations[].detail.f0_mock` 中按模块名指定：

```json
{
  "f0_mock": {
    "scenario": { "comm_risk": "suspicious", "identity_trust": "denied", "task_risk": "block" },
    "fault":    { "comm_risk": "invalid_json" },
    "comm_risk": { "override": { "request_id": "req-OTHER" } }
  }
}
```

| 键 | 作用 |
| --- | --- |
| `scenario` | 选择状态。可写字符串（对所有模块）或按模块名分别指定 |
| `fault` | 协议层故障注入，**必须配合 `--allow-fault-injection`** |
| `override` / `drop` | 覆写或删除输出字段，用于构造不一致/缺字段等负例 |
| `<模块名>` | 该模块专属参数（如 `declared_enclave`、`task_phase`） |

### 故障注入必须显式开启

故障注入只用于让适配层的失败关闭行为可被真实测试。它**必须**由受信任的
本地配置通过 `--allow-fault-injection` 开启；未开启时若输入要求注入故障，
模块会拒绝执行并返回退出码 2 —— 因此故障注入不可能在生产/联调配置下被意外触发。

支持：`invalid_json`、`debug_text`、`two_objects`、`empty`、`exit_nonzero`、
`timeout`、`bad_encoding`、`oversize`、`nan`、`infinity`、`duplicate_key`、
`bad_timestamp`。

## 与测试替身的区别

`tests/fixtures/team_modules/` 下的替身是**规则计算型**实现（按输入数值、
权限矩阵、几何区域真实计算），而本目录的 Mock 是**场景选择型**实现。
两者用途不同：Mock 用于让链路可跑，替身用于证明"替换能力"是真的。

## 边界

- Mock 不实现任何调度、数据库或常驻服务；
- Mock 不接触 `/rg/nav_execute`，只描述候选操作；
- `identity_trust_mock.py` 绝不写入 `subject.authenticated_identity`，
  也绝不声称观察到访问控制日志；
- `task_risk_mock.py` 绝不填写 `policy_epoch` / `policy_digest`。
