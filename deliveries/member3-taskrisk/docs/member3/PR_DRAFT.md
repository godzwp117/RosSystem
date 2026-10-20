# PR 待审查草案（base: baseline）

建议标题：feat(taskrisk): add member 3 explainable task-policy advisory prototype

| 项 | 内容 |
| --- | --- |
| 成员编号 | 成员三 |
| 模块名称 | task_risk |
| 功能分支 | feature/member3-taskrisk |
| baseline 来源 SHA | a4c597161d254192b662ee7b8f4d17f76a89cc16 |
| 当前 HEAD SHA | 提交/推送时执行 git rev-parse HEAD，填实际完整值 |
| 使用 Schema | TaskRiskDecision / ModuleInputEnvelope，未改动 |
| 契约版本 | 1.0.0-proposed，状态 PROPOSED_V1 |
| 本 PR 类型 | 实验原型：真正由 TaskPolicy 与 Action 算出结果的确定性规则 |
| 安全证据来源 | 本地真实策略与自建受控样例；历史窗口为合成 UNIT_TEST，不冒充 ROS 日志 |
| 主要局限 | 缺 L3 真实双侧证据；不覆盖身份认证、在线入侵检测、动态状态机；历史快照非并发权威状态 |

新增独立模块、配置、95 项测试及受控实验脚本。保留所有共享安全核心和其他成员模块。
ALLOW_RECOMMENDED 只表示建议；UNKNOWN/ERROR/非零退出均失败关闭。

测试：成员 3 95 passed；全仓 428 passed, 3 skipped；本地 CI 镜像 PASS；
87 个受控静态场景正确；真条件四状态及适配层接入 PASS。
通用验收器 FAIL（33 PASS、3 FAIL、1 NOT_RUN、1 BLOCKED）：
STATE-BLOCK、STATE-UNKNOWN、STATE-ERROR 仍靠 Mock 开关构造；真实模块刻意忽略它。
L3 BLOCKED，实时监测 NOT_READY，整体 PARTIAL，**当前不请求批准合入**。

待成员四处理：接受真实条件矩阵的验收器设计评审及受控 Jazzy 双侧证据补测。
不能通过让真实模块读取 Mock 开关、削弱门槛、删除负例等办法解决。

安全检查事实：未修改 Gateway、Action、原因码、rg_policy、公共 Schema、DDS 配置，
未使用业务 JSON 选择命令或文件，未引入执行器直通入口，未上传密钥/原始数据/模型二进制。
审批人、审批结论、远程 SHA 与 PR 链接均由实际开发者填写，不能由本草案伪造。
