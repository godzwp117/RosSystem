# 成员 3 实现与验证记录

基线 SHA：`a4c597161d254192b662ee7b8f4d17f76a89cc16`。
开发分支：`feature/member3-taskrisk`；模块版本 `0.1.0`；契约 `PROPOSED_V1`。
验证日期：2026-10-13（北京时间）。

## 结论

成员 3 已有可独立运行的任务风险规则原型，覆盖静态任务语义、风险解释、可选历史快照建议、
四状态及真实适配层接入。当前交付状态 **PARTIAL**，不是全面安全保证，**尚不满足 baseline 合入门槛**。
两个其他研究模块在接入示例中仍为 Mock；DDS 身份与通信异常检测不属于本次成果。

| 检查 | 实际结果 | 边界 |
| --- | --- | --- |
| 新增成员 3 测试 | 95 passed | 含算法、四状态、Schema、进程错误、真实适配层调用；历史日志是 UNIT_TEST 合成证据 |
| 全仓单元回归 | 428 passed, 3 skipped | 3 个跳过项不是 PASS；没有 ROS 实时链路 |
| 仓库本地 CI 镜像 | PASS | 契约、样例、语法、模板、文件卫生；不是线上 CI 审批 |
| 受控策略场景 | 87/87 正确 | 81 组边界网格 + 6 个任务/坐标系/策略异常条件；不是未知攻击泛化指标 |
| 真条件四状态进程矩阵 | PASS | 合法动作、越界动作、缺失策略、损坏策略，不使用 Mock 场景开关 |
| 通用 check_member_module | FAIL：33 PASS / 3 FAIL / 1 NOT_RUN / 1 BLOCKED | 3 项失败源于它对真实模块仍注入 Mock 场景开关；合入门槛 False |
| L3 ROS 2 在线联调 | BLOCKED | 本环境没有 ros2 / Docker；仅验证新增在线脚本会明确退出 3 |
| 实时监测 | NOT_READY | 快照推理和逐请求规则不等于 Jazzy 在线入侵监测 |
| 动态任务状态机 | NOT_INTEGRATED | 不依赖 feature/m3-dynamic-policy |

## 新增文件

- modules/member3_taskrisk/module.py：严格 stdin/stdout 协议及真实算法 analyse 入口。
- modules/member3_taskrisk/risk_model.py：独立条款推理、边界距离、只读策略和可选日志快照。
- modules/member3_taskrisk/experiments.py：受控数据生成、离线参考比较、简化消融和真条件四状态。
- modules/member3_taskrisk/online_check.py：待实测的 ROS 2 双侧证据脚本。
- modules/member3_taskrisk/test_module.py、requirements.txt、example_config.yaml、README.md。
- config/team_modules.member3.yaml：只替换 task_risk 为 external 的接入示例。
- tests/unit/test_member3_taskrisk.py：成员 3 独立验证。
- docs/member3/IMPLEMENTATION_REPORT.md、PR_DRAFT.md：本次报告和待审查 PR 说明。

共享 Gateway、Action、八个原因码、全部 rg_policy 源码、四份公共 Schema、DDS 配置、
其他成员 Mock、通用验收器、原始 task_policy.yaml 及 CI 工作流均保持字节不变。

## 算法真实性与技术边界

算法不读取 f0_mock.scenario，不使用硬编码预设标签，不调用 policy_engine.evaluate 生成输出。
任务匹配、坐标系匹配、策略 active 及目标区域包含直接由候选 Action 和实际读取的 TaskPolicy 决定。
策略文件只读；重复 YAML 键会报错；输入重复 JSON 键、非有限数值、超长数据和非法资源失败关闭。

rule_basis 与 extensions.member3.violations 保留所有已判定违反的条款。
主要原因遵循策略有效性→请求标识→任务→坐标系→数值→区域的顺序，
不通过加权平均稀释硬约束。多项违规时，解释可多条，但主要原因仍来自既有词表。

边界距离是可解释风险特征，不能当作攻击概率或碰撞风险预测。
默认静态模式不假装知道去重与频率状态，而列入 pending_gateway_checks。
可选历史模式读取本地专用审计日志，按首次到达与已 ALLOW 计数建议；
不是精确复刻 Gateway 的 monotonic 并发状态，不能成为权威放行依据。
不会从输入自报身份/phase/epoch/digest 推断授权，不伪造 F0 没有的动态字段。

## 受控实验结果解释

87 个样例由项目真实策略生成，不属于 ROSPaCe 自带标签。
静态建议与 ROS-free policy_engine.evaluate 的可推进判定一致率为 1.0；
在该受控集合上，误报率和漏报率均为 0。两者覆盖相同明确静态条款，
因此这个结果只是实现正确性检查，**不能证明模型超越基线、未知攻击能力或论文创新优越性**。
几何规则单独使用时会漏掉任务、坐标系和策略有效性问题；简化消融仅用于说明条款覆盖贡献。

历史去重/速率只完成合成 UNIT_TEST；EXECUTION_TIMEOUT 仍为 Gateway 执行层待验证项。
online_check.py 已安排静态建议与实时 Gateway 去重/速率拒绝的对照，但本环境没有运行它，
所以当前没有本次新增模块的真实 Gateway DecisionEvent + NavigationSim Goal 双侧证据。

## 可复现命令

仓库根目录，使用仓库外虚拟环境：

```bash
python3 -m venv ../RosSystem-member3-venv
source ../RosSystem-member3-venv/bin/activate
python -m pip install -r modules/member3_taskrisk/requirements.txt
python -m pytest tests/unit/test_member3_taskrisk.py -q -p no:cacheprovider
python -m pytest tests/unit -q -p no:cacheprovider
scripts/run_ci_checks_locally.sh
python modules/member3_taskrisk/experiments.py --out-dir logs/member3/offline-run1
python scripts/check_member_module.py --module task_risk \
  --config config/team_modules.member3.yaml --run-id member3-generic-check
```

已存在的实验目录不覆盖，重跑请换 offline-run2 等新的目录。
运行记录位于 logs/member3/offline-run1/report.json 及
logs/member_acceptance/member3-generic-check/report.json，均不会提交到功能分支。
开发环境为 Python 3.12，依赖 jsonschema 4.26.0、PyYAML 6.0.3、pytest 9.1.1。
正式在线环境仍应采用团队约定的 Jazzy 容器；本地 Python 测试不替代容器验证。

## 必须由成员四审查的后续事项

1. 审查真实四状态矩阵，决定如何扩展通用验收器接受真实成员输入/配置，而不是 Mock 开关。
   不允许仅删除失败项或改期望值使门槛变绿；本实现未自行改验收器。
2. 在专用 ROS Domain、现有 DDS-Security Enforce 环境跑 online_check.py，保存七类场景真实双侧证据。
3. 明确 Gateway 会话日志完整性、重启边界、时钟与去重 TTL；历史快照建议不能直接授权。
4. 单独复现执行超时事件，并与准入 DecisionEvent 区分；不能把执行失败写成未创建 Goal。
5. 审批 PR 后再合入 baseline，契约维持 PROPOSED_V1，成员 3 无权代签冻结确认。

本次只在本地功能分支交付，未推送远程、未创建 PR、未修改受保护分支。
