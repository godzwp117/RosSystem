# M1 交付给最终集成的交接说明

> `RESEARCH_BASE_SHA` = `be47ccd6c1b19460b65abc0ea8004706383d01d4`
> 本分支：`research/m1-online-detection`
> 运行证据：`artifacts/research/m1/m1audit-20261018T160049Z/`

## 1. 本次交付的代码

| 文件 | 状态 | 作用 |
| --- | --- | --- |
| `scripts/m1_data_audit.py` | **新增** | 数据/标签/划分审计，产出可复现的 JSON+MD |
| `scripts/m1_train_windows.py` | **新增** | 窗口级多候选训练，会话分组交叉验证与诚实基线对比 |
| `scripts/m1_export_window_model.py` | **新增** | 导出纯数值模型 + 数值一致性校验（1e-9） |
| `modules/member1_comm/collector/ros2_window.py` | **新增** | 真实 ROS 2 订阅侧窗口特征采集与在线打分 |
| `modules/member1_comm/model/comm_risk_window_model.json` | **新增** | 新窗口模型（6 维 logistic，SHA-256 见 manifest） |

**未修改**：`module.py` 推理逻辑、`features.json`、49 维模型、
`scripts/team_demo.py`（F0）、任何 Gateway/策略/DDS 权限。

> 因此本次不需要重跑 F0 P0 反例矩阵——F0 代码未动。

## 2. 集成时需要做的三件事（尚未做，故意留给集成负责人）

1. **切换默认模型**：把 `config/team_modules.three-real.yaml` 中
   `comm_risk` 的 `--model` 指向 `comm_risk_window_model.json`，
   `--features` 指向新的 6 维清单，并更新 `--model-sha256`。
2. **接入在线特征**：由 `ros2_window.py` 产出的窗口特征替换当前
   `build_envelope` 里硬编码的 `f0_runtime.request_count = 12`。
   注意：这是**语义变更**，需评审 F0 的 `observation provenance` 逻辑。
3. **重跑全链路**：三真实联合 + M3 在线六场景 + DDS Enforce，
   确认 M1 从 `UNKNOWN` 变为可在真实条件下给出 `NORMAL` 的路径。

## 3. 接口约定（保持不变）

- 输入：`ModuleInputEnvelope`（`module_input.schema.json`）
- 输出：`CommRiskEvidence`（`comm_risk_evidence.schema.json`）
- 退出码：0 正常 / 2 输入非法 / 3 模型缺失 / 4 映射失败
- 证据来源：`--observation-provenance` 由**受信任配置**声明，
  业务 JSON 自报的 kind 只用于一致性比对

## 4. 当前剩余阻断（交给 M2 之后或后续轮次）

| 编号 | 阻断 | 归属 |
| --- | --- | --- |
| B1 | `request_count` 未绑定 Action 业务语义 | M1 后续 |
| B2 | 未在真实 ROS 2 攻击流量上验证检出力 | M1 后续（需隔离攻击实验） |
| B3 | 22 维逐包 RTPS 特征不可从订阅侧取得 | 需要抓包侧组件 |
| B4 | 默认模型未切换（`M1_ONLINE_PROCEED_READY=FAIL`） | 集成 |
| B5 | M2 生产身份来源仍 UNKNOWN | M2 专项 |

## 5. 复现命令

```bash
# 1) 数据审计
python3 scripts/m1_data_audit.py --rows-per-shard 20000 --out <out>/data_audit

# 2) 多候选训练（会话分组）
python3 scripts/m1_train_windows.py --out <out>/model

# 3) 导出部署模型 + 数值一致性校验
python3 scripts/m1_export_window_model.py \
    --out modules/member1_comm/model/comm_risk_window_model.json \
    --manifest-out <out>/model/model_manifest_window.json

# 4) 真实 ROS 2 采集（隔离域，容器 rg_m1 内）
ros2 topic pub --rate 50 /m1_probe/tick std_msgs/msg/String "{data: tick}"
python3 modules/member1_comm/collector/ros2_window.py \
    --topic /m1_probe/tick --type std_msgs/msg/String \
    --duration 6 --interval 1 --out <out>/window_50hz.json
```

## 6. 不得据此宣称

- ❌ 已具备有效的实时入侵检测
- ❌ 能检测未知攻击
- ❌ 生产误报率已达标
- ❌ 已在真实攻击流量上验证

## 7. 证据与哈希

见 `artifacts/research/m1/m1audit-20261018T160049Z/SHA256SUMS.txt`。
模型 SHA-256：`a91e166cee8b94d3c49b53322782147a696161d9d8eb8e597d5b97ff8065d1bb`。
