# 成员研究模块最小工程模板

从这里开始你的模块。**不要**重新设计一套模块框架 —— 仓库已有统一的
`ModuleInputEnvelope`、三份研究输出 Schema 和适配层 `scripts/team_demo.py`。

## 三步起步

```bash
# 1) 复制模板到你的模块目录
python3 scripts/init_member_module.py --module comm_risk --dest modules/my_comm

# 2) 实现你的真实算法（改 modules/my_comm/module.py 的 analyse()）

# 3) 验收
python3 scripts/check_member_module.py --module comm_risk \
  --config config/team_modules.local.yaml
```

## 协议

```text
输入：stdin  一个 ModuleInputEnvelope（JSON）
输出：stdout 一个研究输出（JSON）—— **只能有一个 JSON 对象**
诊断：stderr （绝不污染 stdout）
```

## 模块与输出映射

| 模块 | 输出 Schema | 允许推进 | 阻断 | 未知 | 错误 |
| --- | --- | --- | --- | --- | --- |
| `comm_risk` | `CommRiskEvidence` | `NORMAL` | `SUSPICIOUS` | `UNKNOWN` | `ERROR` |
| `identity_trust` | `IdentityTrustAssessment` | `AUTHORIZED` | `DENIED` | `UNKNOWN` | `ERROR` |
| `task_risk` | `TaskRiskDecision` | `ALLOW_RECOMMENDED` | `BLOCK_RECOMMENDED` | `UNKNOWN` | `ERROR` |

`UNKNOWN` 与 `ERROR` **一律不推进**，且**不等于正常**。

## 安全默认行为（务必理解）

模板**默认不产生任何真实判断**：

```bash
$ python3 module.py --module comm_risk < envelope.json
[module] 模板尚未接入真实算法。**不会**输出虚构的 NORMAL/AUTHORIZED/ALLOW_RECOMMENDED。
$ echo $?
3
```

这是**刻意**的：**宁可非零退出让适配层阻断，也不填虚构字段**。

仅在协议自测时才用 `--allow-placeholder`（输出语义诚实的 `UNKNOWN`）：

```bash
python3 module.py --module comm_risk --allow-placeholder < envelope.json
```

> `--allow-placeholder` 的输出**不是**算法成果，**不得**写进研究结论。

## 如何替换成你的真实算法

只改 `analyse()` 一个函数：

```python
def analyse(module, envelope, context):
    features = extract_features(envelope)      # 你自己的特征提取
    if features is None:
        return 'UNKNOWN', {'reason': 'FEATURES_ABSENT'}
    score = my_model.predict(features)          # 你自己的真实算法
    state = 'NORMAL' if score < THRESHOLD else 'SUSPICIOUS'
    return state, {
        'reason': '模型判定为通信流量异常',
        'evidence_kind': 'UNIT_TEST',           # 或 RUNTIME_LOG / CONTROLLED_SECURITY_EXPERIMENT
        'evidence_ref': 'modules/my_comm/model',
        'risk_level': 'HIGH',
        'basis': ['model_sha256=<你的模型哈希>'],
    }
```

返回值规则：

- 返回 `None` → 模板认为"尚未接入算法" → 退出码 **3**；
- 返回 `(state, detail)` → `state` 必须是上表该模块的四个合法状态之一，
  否则退出码 **4**；
- 抛异常 → 输出语义诚实的 `ERROR` 状态（结构合法、不推进），退出码 0。

### 必须遵守

- **不得**输出虚构的 `NORMAL` / `AUTHORIZED` / `ALLOW_RECOMMENDED`；
- **不得**伪造权限文件、DDS 日志或真实攻击观测；
- **不得**把 `producer.source = EXTERNAL` 解释为"已完成身份验证"
  （它只表示"这是一个真实外部模块"）；
- **不得**用硬编码标签、预设 allow 或直接返回 Mock 结果冒充研究成果；
- 只填**能真实产生**的字段；不确定就不填，**不编造默认值**。

### 绝对禁止

- `shell=True`；
- 从业务 JSON 读取待执行命令；
- 从不不可信输入选择 joblib 模型；
- 修改全局 DDS 权限；
- 绕过 Gateway；
- 直接向 `/rg/nav_execute` 发送任何内容。

## 文件说明

| 文件 | 说明 |
| --- | --- |
| `module.py` | 模块实现（改 `analyse()`） |
| `example_config.yaml` | 接入适配层的配置片段 |
| `test_module.py` | 协议与安全默认行为自测 |

## 下一步

1. 用 `scripts/check_member_module.py` 跑统一验收（协议层）；
2. 补充你自己的**真实算法测试**（真实输入、真实输出、证据来源）；
3. 按 `.github/PULL_REQUEST_TEMPLATE.md` 创建 **base = `baseline`** 的 PR。

> 通过协议层验收**不代表**算法有效；
> 通过算法测试**不代表**实现了实时监测；
> `READY_FOR_GATEWAY_SUBMISSION` **不等于** Gateway 已授权。
