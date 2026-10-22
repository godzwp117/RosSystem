# 成员一通信风险模块（M1，已适配入主系统）

本目录是成员一交付 `modules/my_comm` 在主系统中的**正式位置**。
来源与逐文件哈希见 `docs/integration/member_module_handoff.yaml`；
适配说明见 `docs/integration/WORK_A_MODULE_ADAPTATION_REPORT.md`。

## 它是什么 / 不是什么

* **是**：一个用**真实离线训练产物**做数值推理的通信风险分类器，输入是
  49 维通信/主机特征向量，输出是公共契约 `CommRiskEvidence`（建议）。
* **不是**：当前 ROS 2 通信的实时 IDS。特征来源是 ROSPaCe 离线数据集
  （tshark 抓包字段 + `/proc` 主机指标），不是 Jazzy 运行时可直接采集的量。
  模型与在线可观测特征之间的映射**尚未建立**。
* **不是**：DDS 身份证明。`request_id`、`producer`、业务 JSON 自报身份都不构成认证。

## 交付模型（可复验）

| 项 | 值 |
| --- | --- |
| 模型文件 | `modules/member1_comm/model/comm_risk_model.json` |
| SHA-256 | `d45d272eea9dfef67b2b0066af0fd078270d559a4a4e350b7558d072c21c40df` |
| 格式 | `member1-numeric-v1`（纯数值 JSON，**不加载** pickle/joblib） |
| 算法 | ExtraTrees（48 棵，深度上限 12），阈值 0.75 |
| 验证门槛 | **FAIL**（`validation_gate_passed=false`）→ 正常预测默认保留 UNKNOWN |
| 测试集表现 | F1 0.1312 / Recall 0.0702 / Specificity 1.0（恒预测攻击基线 F1 0.8132） |
| 训练数据 | ROSPaCe_reduced（官方归档，尺寸 + MD5 校验通过；3024.7 万行审计，15 万采样） |
| 划分 | 按文件不相交：train 0-10 / validation 11-12 / test 13-14；会话独立性 **UNVERIFIED** |

模型的数值实现与 sklearn 训练对象在 20000 条 held-out 行上完全一致
（最大概率误差 3.3e-16，分类不一致 0）。完整报告见
`modules/member1_comm/model/train_report.json`，清单见
`modules/member1_comm/model/model_manifest.json`。

复现：

```bash
# 官方归档不在版本控制中（/data 已被 .gitignore 排除）
PY=/path/to/python3.10-with-numpy-sklearn        # 见 requirements.txt
$PY modules/member1_comm/train.py \
    --archive data/ROSPaCe_reduced/ROSPaCe_reduced.tar.gz \
    --samples data/member1_samples/reduced \
    --output training_runs/member1
sha256sum training_runs/member1/model.json       # 与上方 SHA-256 对照
```

## 调用协议

```bash
python3 modules/member1_comm/module.py \
    --model modules/member1_comm/model/comm_risk_model.json \
    --model-sha256 d45d272eea9dfef67b2b0066af0fd078270d559a4a4e350b7558d072c21c40df \
    --features modules/member1_comm/features.json \
    --observation-provenance UNKNOWN \
    < envelope.json
```

* stdin 恰好一个 `ModuleInputEnvelope`；stdout 恰好一个 `CommRiskEvidence`；诊断只写 stderr。
* 工作目录：仓库根。无需 ROS 2 运行时（纯 Python + jsonschema）。
* 退出码：`0` 正常产出（**状态可能是 UNKNOWN/SUSPICIOUS，不等于允许**）；
  `2` 输入非法；`3` 模型缺失；`4` 无法形成映射（拒绝伪造完整证据）。
* 超时 / 输出上限由适配层控制（默认 10s / 64 KiB）。

### 输入中的通信观测

```json
{
  "observations": [{
    "source": "/rg/guarded_navigate",
    "kind": "CONTROLLED_SECURITY_EXPERIMENT",
    "observed_at": "2026-10-13T12:00:03Z",
    "detail": {
      "rospace_comm": {
        "features": {"feature_names": ["<49 个有序特征名>"], "values": [0.0]}
      },
      "f0_runtime": {
        "communication": {"resource": "/rg/guarded_navigate", "resource_type": "Action", "operation": "GOAL_SEND"},
        "request_count": 12,
        "window": {"start": "2026-10-13T12:00:00Z", "end": "2026-10-13T12:00:05Z", "duration_ms": 5000}
      }
    }
  }]
}
```

约束：`feature_names` 必须与模型内嵌顺序**完全一致**；缺失列直接拒绝（不补零）；
显式 `null` 视为数据集缺失，用训练集中位数填补并在输出记录条数；
`source` 必须等于 `f0_runtime.communication.resource`；`observed_at` 必须落在窗口内；
`request_count` 是**业务请求数**，不是数据集包数。

### NORMAL 的三个必要条件

1. 模型 `validation_gate_passed=true`；
2. 受信任配置 `--observation-provenance` 声明了 `RUNTIME_LOG` 或
   `CONTROLLED_SECURITY_EXPERIMENT`；
3. 信封自报的 `observations[].kind` 与该声明一致。

三者缺一即 UNKNOWN。**业务 JSON 无法打开 1，也无法替代 2**。
本交付模型 1 为 false，所以生产语义下永远得不到 NORMAL —— 这是真实结论。

`--controlled-test` 只允许出现在受信任的受控测试配置中，输出会带
`CONTROLLED_TEST_ONLY` 与 `extensions.member1_comm.controlled_test=true`。

## 测试

```bash
python3 -m pytest modules/member1_comm/test_module.py modules/member1_comm/test_integration.py -q
python3 -m pytest tests/unit/test_member1_comm_real.py \
                  tests/unit/test_member1_adapter_integration.py \
                  tests/unit/test_member1_real_acceptance.py -q
```

* `test_module.py` / `test_integration.py`：成员交付的受控单元与 CLI 测试（44 项）。
* `tests/unit/test_member1_comm_real.py`：真实交付模型 + 真实 held-out 数据行 +
  失败关闭（缺失/坏哈希/越界路径/特征错配/来源伪造/观测窗口）。
* `tests/unit/test_member1_adapter_integration.py`：F0 适配层 External 调用链路。
* `tests/unit/test_member1_real_acceptance.py`：交付配置 + 验收 fixture 的整体回归。

## 未完成 / 阻断项

| 项 | 状态 | 说明 |
| --- | --- | --- |
| 实时通信特征采集 | **BLOCKED** | ROSPaCe 的 49 维特征（tshark 字段 + `/proc`）在 Jazzy 运行时没有等价采集器；映射未建立前不得宣称在线 IDS |
| 检测有效性 | **NOT_PROVEN** | 测试集 F1 0.131 低于恒预测攻击基线 0.813；验证门槛 FAIL |
| 会话级泛化 | **UNVERIFIED** | 只有 FILE_DISJOINT_SPLIT，不证明跨采集会话泛化 |
| 模型可信度 | **PARTIAL** | 模型随仓库交付并有 SHA-256；训练数据不入库，跨环境重训不保证字节一致 |
