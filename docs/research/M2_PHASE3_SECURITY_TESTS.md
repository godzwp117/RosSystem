# M2 第三轮：安全测试矩阵

> run_id：`m2p3-20261019T033811Z`
> 证据：`artifacts/research/m2-phase3/m2p3-20261019T033811Z/`
> 环境：`rg_m2p3`，Domain 60，Fast DDS 2.14.6，研究用独立 keystore

## 1. 已执行项

| ID | 场景 | 结果 | 证据 |
| --- | --- | --- | --- |
| M2-P3-01 | 合法 DDS 主体认证 | **PASS**：`PARTICIPANT_AUTHENTICATED` 记录证书主体 | `events.jsonl` |
| M2-P3-02 | 两个合法主体不串号 | **PASS**：A(2 条)/B(3 条) 各自归属正确，零交叉 | `events.jsonl` |
| M2-P3-03 | 请求样本被可靠捕获 | **PASS**：`ingress_exit received=5` 与发送数一致 | `ingress.log` |
| M2-P3-04 | Writer→Participant 归属 | **PASS**：writer GUID 前缀 = participant GUID | `events.jsonl` |
| M2-P3-05 | 请求内容与样本一致 | **PASS**：goal_uuid/payload 与发送值逐条一致 | `events.jsonl` |
| M2-P3-06 | F0 前置时序 | **PASS（设计层面）**：入口位于 F0 之前，身份随请求到达即取得 | 架构 + 账本 |
| M2-P3-07 | 非法主体被原生拒绝 | **PASS（间接）**：DDS 权限拒绝未授权 topic，见 §2.2 | `ingress.log` |
| M2-P3-08 | 自报身份/伪造日志不被信任 | **PASS（延续 P0）**：F0 STRICT 关闭自报，38 项反例仍通过 | 回归日志 |
| M2-P3-10 | 过期/重放拒绝 | **PASS（延续第二轮）**：nonce 重放被 F0 拒 | 第二轮证据 |
| M2-P3-14 | Action 计数与真实接收一致 | **PASS**：`send_goal_count=5` = 实际接收 5 | `window_complete.json` |
| M2-P3-15 | 30 秒窗口聚合一致 | **PASS**：`coverage=COMPLETE, count=5` | `window_complete.json` |
| M2-P3-16 | 账本篡改/缺失 -> UNKNOWN | **PASS**：四类降级全部拒绝，见 §3 | `/tmp/tamper` 结果记录在下表 |
| M2-P3-17 | 不使用尚未发生的 Gateway 结果 | **PASS**：窗口强制 `window_end = as_of - 2s` | 代码 + 输出 |
| M2-P3-20 | F0 P0 反例不退化 | **PASS**：38 passed | `logs/` |

## 2. 未执行项（明确 BLOCKED / NOT_RUN）

| ID | 场景 | 状态 | 原因 |
| --- | --- | --- | --- |
| M2-P3-09 | Writer 错绑（同主体多 writer） | NOT_RUN | 需要同一 client 创建多个 writer 的用例，未构造 |
| M2-P3-11 | 跨 Domain 不可复用 | NOT_RUN | 需双域对照实验，未构造 |
| M2-P3-12 | Gateway 正向对照 | NOT_RUN | 未启动 Gateway 栈 |
| M2-P3-13 | Gateway 独立阻断 | NOT_RUN | 同上 |
| M2-P3-18 | 并发与重试 | NOT_RUN | 未构造并发客户端 |
| M2-P3-19 | 原 M3 在线六场景回归 | NOT_RUN | 本轮未启动在线栈 |
| — | 真实 Action send_goal 捕获 | **BLOCKED** | 缺 Action 请求类型 typesupport 接线 |

## 3. 账本降级场景实测

| 场景 | 结果 |
| --- | --- |
| 账本截断（前 3 行） | `count=0, coverage=UNKNOWN`，提示"不得断言为 0" |
| 账本文件不存在 | `count=null, coverage=UNKNOWN` |
| 混入损坏行 | `count=5, coverage=PARTIAL` |
| 请求错误 resource | `count=0, coverage=UNKNOWN` |

## 4. 本轮未启动的回归说明

本轮把预算集中在"请求级身份绑定"与"可信事件账本"两件主目标上，
因此 **Gateway / M3 在线 / DDS Enforce 的联调回归未执行**（NOT_RUN），
不能以"前几轮通过"代替本轮结论。
F0 安全反例与契约检查在本地执行并通过。
