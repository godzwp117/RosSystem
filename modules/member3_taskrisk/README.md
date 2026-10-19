# 成员 3：任务感知风险建议模块

开发基线：`a4c597161d254192b662ee7b8f4d17f76a89cc16`，分支 `baseline`。
模块实现版本：`0.1.0`；公共契约保持 `PROPOSED_V1 / 1.0.0-proposed`。

这是**独立规则算法实验原型**，不是场景开关 Mock，也不是已获认证的授权模块。
算法读取本地真实 TaskPolicy 和候选 Action，识别合法通信主体也可能提出的任务越权。
它只产生建议；执行必须经过 `/rg/guarded_navigate`，SecurityGateway 是最终权威准入点。

## 已实现与未实现

| 内容 | 范围 |
| --- | --- |
| 任务、坐标系、区域、策略有效性检查 | 独立确定性规则，不调用 Gateway evaluate 来冒充新算法 |
| 风险因子 | active、task_matches、frame_matches、target_finite、region_inside、边界有符号距离 |
| 可解释性 | 所有违反条款及原因；主要原因按基线静态判定优先级排列 |
| 四状态 | 真实合法输入→ALLOW_RECOMMENDED；真实违规→BLOCK_RECOMMENDED；缺策略→UNKNOWN；坏策略→ERROR |
| 重复与频率 | 可选只读整会话审计快照，仅在来源及启动时间由本地配置明确指定时启用 |
| 尚未实现 | DDS 身份验证、在线入侵检测、动态任务状态机、物理机器人验证 |
| 执行超时 | 属 Gateway 执行阶段；不能在执行前捏造 EXECUTION_TIMEOUT 结论 |

边界距离为 `min(x-x_min, x_max-x, y-y_min, y_max-y)`，单位米。负数表示越界，
非负表示处于闭区间内。距离不超过 0.25 米时提示 LOW，但不会改变准入建议。
该阈值是可配置工程提示，不是经学习得到的攻击概率，不代表碰撞安全。
基线是二维区域，因此 z 仅检查数值合法性，不新增高度约束。

## 安装及独立运行

从仓库根目录运行。需要 Python 3.10 以上，算法不依赖 ROS 或训练模型。

```bash
python3 -m venv ../RosSystem-member3-venv
source ../RosSystem-member3-venv/bin/activate
python -m pip install -r modules/member3_taskrisk/requirements.txt
python modules/member3_taskrisk/module.py < docs/interfaces/examples/module_input_valid.json
python modules/member3_taskrisk/test_module.py
python modules/member3_taskrisk/experiments.py --out-dir logs/member3/offline-run1
```

stdin 只接受一个合法 ModuleInputEnvelope；stdout 只输出一个 TaskRiskDecision；诊断写 stderr。
非有限数值、重复 JSON 键、畸形信封或非法入口返回退出码 2，不伪造必填字段。
状态 UNKNOWN/ERROR 的合法 JSON 返回退出码 0，但适配层仍必须阻断。

`policy_ref` 仅填写真实读取的 policy_version。不会从业务输入复制 phase/epoch/digest。
`extensions.member3.policy_content_sha256` 是本地文件实际字节摘要，不是权威 policy_digest。
配置文件证据标为 UNKNOWN，并注明它是本地配置来源；不把它错标为 DDS 权限文件。
实验样例明确是项目自建受控数据，不是 ROSPaCe Action 标签。

## 适配层接入

`config/team_modules.member3.yaml` 只把成员 3 换为 external，成员 1/2 保留 Mock。
若两位成员已有真实实现，只合并本目录 example_config.yaml 的 task_risk 段。
不要整体覆盖团队已有本地配置。

```bash
source ../RosSystem-member3-venv/bin/activate
python scripts/team_demo.py \
  --input docs/interfaces/examples/module_input_valid.json \
  --config config/team_modules.member3.yaml
```

正常结果是 READY_FOR_GATEWAY_SUBMISSION，**不等于 Gateway ALLOW**，更不等于机器人已执行。
实验脚本会生成合法、越界、缺策略、坏策略的真实输入输出和适配层记录，保存在 logs/ 下，不入库。

## 通用验收器的已知不兼容

必须如实运行：

```bash
python scripts/check_member_module.py --module task_risk \
  --config config/team_modules.member3.yaml --run-id member3-generic-check
```

当前基线验收器对所有四状态使用同一合法目标和同一策略，只改变
`observations[].detail.f0_mock.scenario`。真实模块必须忽略这个 Mock 开关，因此
STATE-BLOCK、STATE-UNKNOWN、STATE-ERROR 会报告 FAIL，不能声称达到 PR 合入门槛。
某些 ADP-* 项仍会通过，是其他两个 Mock 被同时切换后的阻断，不能据此证明成员 3 四状态。
本交付未修改或削弱共享验收器。真实四状态验证在新增单测及 experiments.py 中进行，
需要成员四审查是否把通用验收器扩展为接受成员提供的真实输入/配置矩阵。
在审查与在线证据完成前，本模块整体合入状态为 PARTIAL。

## 可选历史快照推理

默认不启用历史分析；ALLOW_RECOMMENDED 会明确列出仍待 Gateway 检查的去重、频率及执行事项。
不要把静态允许建议解读为“已经排除所有历史风险”。

历史模式要求由成员四提供**单一 Gateway 当前会话、启动时为空、未截断的专用审计日志**，
并明确会话开始时间。路径及时间只能来自受信任本地配置/命令行，不能取自业务 JSON。

```bash
python modules/member3_taskrisk/module.py --policy config/task_policy.yaml \
  --audit-log tests/evidence/your-session/gateway_audit.jsonl \
  --audit-kind RUNTIME_LOG --audit-session-start 2026-10-13T00:00:00Z \
  < your-envelope.json
```

此命令中的开始时间必须替换为该 Gateway 的真实启动时间，不能照抄常量。
日志必须有完整 RosCommEvent/DecisionEvent 对，必须仍在本地配置的 30 秒新鲜度窗口内。
程序只读文件；不会把建议加入 Gateway 的已准入次数，也不会修改共享策略。
重复窗口沿用首次到达时间，不因重复包刷新；速率只统计已经 ALLOW 的历史到达。
日志缺失、陈旧、截断或缺关联对时 UNKNOWN；内容畸形或重复 event_id 时 ERROR。

限制：日志 mtime 不能证明节点活跃或日志完整；路径本身不能证明 DDS 身份。
wall-clock 快照不等价于 Gateway 的 monotonic 并发 tracker；进程重启、时钟跳变、
跟踪表容量裁剪和同时到达会导致不一致。history 模式仍是研究建议，不能替代最终准入。
单位测试中的合成事件一律标 UNIT_TEST，不会当成实际 Gateway 日志。

## ROS 2 在线验收（当前未运行）

新增 online_check.py 只在已构建、已 source、现有 DDS-Security Enforce 环境运行。
它复用基线按实例拥有的进程组清理，不按名称杀进程，不停其他成员容器。
必须选一个团队为你保留的独立 ROS Domain；不会为了跑通测试关闭 DDS 安全。

```bash
# 在成员 3 的团队 Jazzy 容器内运行，使用团队已有权限与 keystore
cd /ws
source install/setup.bash
# 使用容器现有的 jsonschema/PyYAML 或已准备的成员独立环境，不改 DDS 配置
python3 modules/member3_taskrisk/online_check.py --domain 63
```

域 63 只是示例，执行前必须确认它属于你的隔离测试环境。
脚本验证正常、区域越界、任务不匹配、坐标系错误、无效策略、重复请求和频率限制。
上游阻断的真实请求不应产生 Gateway 记录；为对照会另发**不同 request_id** 的影子控制请求，
仍走既有 Planner→Gateway，而非执行端。报告分开记录两种阻断层级。
重复及频率案例可展示静态建议允许但实时 Gateway 拒绝的不一致，并保存双侧真实证据。
在线脚本目前仅完成语法和无 ROS 环境阻断检查，不能宣称 L3 已通过；整体实时监测仍 NOT_READY。

## 开发与提交

新增文件限于本成员目录、独立配置、成员测试及 docs/member3，未改任何共享安全核心。
无需 joblib、原始流量、图像数据或密钥。仅 feature 分支走 PR，base 必须是 baseline。
完整测试命令、当前状态与待成员四确认项见 docs/member3/IMPLEMENTATION_REPORT.md。

环境提醒：baseline 的一个旧单测会遍历源码树内的证书扩展名，未排除 `.research-venv`，
因而可能把 pip 自带的公开 CA 证书误报为密钥。请把开发虚拟环境放在仓库外，
如上述同级目录；本交付不删证书、不修改该单测，也不削弱凭据审查。
