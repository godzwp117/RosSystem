# 勘误 E-001：P07 的“M3 阻断 → F0 阻断”证据不匹配

> 状态：**已复核并更正**（隔离实验 13/13，run `p07-20261022T024200Z`）
> 影响：论文中任何引用“P07 PASS”或“M3 建议阻断已被验证”的句子

## 1. 原声明

`artifacts/acceptance/exports/research_v110/p01_p12_matrix.json` 将 P07
（目标：`M3 建议阻断 → F0 BLOCK`）标为 **PASS**。

## 2. 原始证据

该条目的 `evidence` 指向：

- `artifacts/research/v110/three-real/summary.json`
- `artifacts/acceptance/exports/m2_sros2_enforce_v110`

其中三真实运行的 M3 实际输出是 **`ALLOW_RECOMMENDED`**；
`m2_sros2_enforce_v110` 的 S5 是 **Gateway TaskPolicy 的 `OUT_OF_REGION` 阻断**，
不是 M3 模块输出 `BLOCK_RECOMMENDED`。

## 3. 发现的问题

“Gateway TaskPolicy 阻断”与“M3 建议阻断导致 F0 阻断”是两个不同的机制：

- 前者是执行层的权威策略；
- 后者是建议模块的状态，经 F0 的模块状态门产生阻断。

原矩阵用前者支撑后者，属于**证据不匹配**，不能作为 P07 PASS 的依据。

## 4. 修正方案

本轮新增隔离实验 `P07-M3-BLOCK-ISOLATION`：

- **真实 M3 External 模块**，使用只读测试策略
  `config/scenarios/task_policy_tight_region.yaml`；
- 候选目标 (2.0, 2.0) 在主策略 [0,4]² 内、在测试策略 [0,1]² 外，
  由真实规则推出 `BLOCK_RECOMMENDED` / `OUT_OF_REGION`；
- M1/M2 使用 **MOCK 控制**（仅用于隔离 M3，不冒充三真实），并在配置中显式声明
  `CONTROLLED_TEST_ONLY`；
- 运行 F0 适配层，核验：
  1. M3 输出 `BLOCK_RECOMMENDED`；
  2. F0 `ADAPTER_BLOCK` 且原因指向 M3 模块状态；
  3. Planner 未被提交；
  4. Gateway 未收到请求（该隔离实验不启动 Gateway；记录这一点，不伪造 Gateway 事件）；
  5. 下游 Goal = 0。

只有以上全部成立，P07 才可改为 **PASS（受控隔离）**，并必须标注这不是三真实正向。

## 5. 对论文写作的影响

- 在复核完成前：**不得**引用 P07 PASS；
- 可安全引用的是独立的 Gateway S5 `OUT_OF_REGION` 阻断结论；
- 若隔离实验失败：P07 应改为 `NOT_VERIFIED`，并保留上述独立结论。


---

## 6. 复核结果（2026-10-22）

隔离实验 `p07-20261022T024200Z` 13/13 通过：

- 真实 M3 External 输出 `BLOCK_RECOMMENDED`，`OUT_OF_REGION`；
- F0 `ADAPTER_BLOCK`，reason `ADAPTER_MODULE_STATUS_NOT_PROCEED`，detail 明确指向 `task_risk`；
- Planner `submitted=false`；
- Gateway/NavigationSim 未启动，0 收到/0 Goal 由“未提交”推出，未伪造运行事件。

因此 P07 可标为 **PASS（CONTROLLED_ISOLATION）**；原 Gateway `OUT_OF_REGION`
证据仍作为独立结论保留。该结果**不是**三真实正向，也不改变 LEVEL 3 = BLOCKED。
