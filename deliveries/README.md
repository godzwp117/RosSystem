# 成员交付物归档（deliveries/）

本目录统一存放三位成员的研发交付物，**原样保留各自的结构**，便于追溯与复现。
不是可运行代码的默认入口 —— 各成员的模块若要接入适配层，需按其自带说明配置。

| 目录 | 成员 | 模块身份 | 来源基线 | 交付状态 |
| --- | --- | --- | --- | --- |
| `member1-comm/` | 成员一 | `comm_risk` | `a4c597161d254192b662ee7b8f4d17f76a89cc16` | `PARTIAL_EXPERIMENTAL_PROTOTYPE` |
| `member2-identity/` | 成员二 | `identity_trust` | 见其 `docs/MEMBER2_IMPLEMENTATION.md` | 见其交付说明 |
| `member3-taskrisk/` | 成员三 | `task_risk` | `a4c597161d254192b662ee7b8f4d17f76a89cc16` | `packaging_change_only: true` |

---

## member1-comm

成员一的通信异常分析原型。**只归档其真正新增的部分**，未复制整份仓库副本
（其交付包内含完整仓库快照，其中 480 个文件与本仓库仅行尾差异、347 个
`artifacts/acceptance/` 文件已存在于本仓库，均已在归档时剔除）。

```text
modules/my_comm/          成员一的模块（module.py / train.py / metrics.py / features.json ...）
artifacts/member1/        运行证据（35 个）：
  local_evidence/           四状态 adapter 输入输出与校验记录
  ros_controlled_protocol/  ROS 受控协议实验（audit.jsonl / navsim_goals.jsonl）
  secure_system_smoke/      安全链路冒烟
  offline_experiments/      reduced / noperiodicity 离线训练报告
.github/workflows/member1-comm.yml   成员一自带的 CI（只读权限，path 过滤，仅 L1/单元）
REVISION.txt              来源与状态声明
RosSystem-member1-changes.patch      其变更补丁
```

其 `REVISION.txt` 自述（**原样引用，未改写**）：

```text
local_research_delivery=COMPLETE
acceptance_status=PARTIAL_EXPERIMENTAL_PROTOTYPE
L2_offline_experiment=PASS
model_performance_gate=FAIL
L3_live_protocol=PASS_WITH_CONTROLLED_FIXTURES
L3_effective_detector=NOT_READY
RUNTIME_MONITOR=NOT_READY
Jazzy_tests=203_PASSED
```

> **`model_performance_gate=FAIL` 与 `L3_effective_detector=NOT_READY` 是成员一自己
> 如实声明的**，本归档不改写、不美化。该原型**不构成**已可用的在线检测器。
>
> 其交付包另含一项对本仓库 `.gitignore` 的安全改进
> （忽略 `/config/team_modules*.local.yaml`，因生成的受信任命令会写入本地解释器
> 与模型路径），**已单独应用到仓库根 `.gitignore`**。

## member2-identity

成员二的 DDS 身份与资源权限评估实现。

```text
identity_trust/assessor.py            实现
tests/unit/test_identity_trust_assessor.py
scripts/member2_adapter_check.py      适配层自检
docs/MEMBER2_IMPLEMENTATION.md        实现说明
docs/MEMBER2_UNIT_TEST_RESULT.txt     单测结果
config/team_modules.member2.example.yaml
```

## member3-taskrisk

成员三的任务风险模块（`v0.1.0`）。

```text
START_HERE.md             入口说明
MANIFEST.json             文件清单（含每个文件的 sha256 与大小）
modules/member3_taskrisk/ module.py / risk_model.py / experiments.py / online_check.py
tests/unit/test_member3_taskrisk.py
docs/member3/             IMPLEMENTATION_REPORT.md / PR_DRAFT.md
config/team_modules.member3.yaml
reports/                  offline_report.json / generic_acceptance_report.json
member3.patch             其变更补丁
```

其 `MANIFEST.json` 声明 `packaging_change_only: true`，即该交付**只做打包**，
不含对公共接口的改动。可用 `sha256` 逐文件校验完整性。

---

## 未做与不应做的事

- 本归档**未**把成员模块接入默认配置。基线默认模块配置仍是明确标记
  `MOCK` 的实现 —— **不得**直接把未经验证的检测器设为默认安全模块。
- 成员模块的**审核状态不变**：`L1_PROTOCOL` 通过**不代表** `L2_REAL_ALGORITHM`
  通过，更不代表实现了 `L3` 实时监测。
- **不得**把本目录中的 Mock 或实验原型结果表述为真实在线检测能力。
- 公共接口仍为 `PROPOSED_V1`，未因本次归档而变更。

## 后续若要接入某个模块

1. 阅读该成员目录下的 README / IMPLEMENTATION_REPORT；
2. 按其 `example_config.yaml` 在自己的 `config/team_modules.local.yaml` 中配置；
3. 用 `python3 scripts/check_member_module.py --module <身份> --config <你的配置>` 验收；
4. 走 `feature/member*-*` 分支 → PR（`base = baseline`）→ 独立审查 → 合入。
