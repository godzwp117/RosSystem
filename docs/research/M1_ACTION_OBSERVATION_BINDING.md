# M1 Action 级观测可行性调查（第三轮 P1）

> 结论先行：**`M1_ACTION_COUNT_BOUND` = BLOCKED**（未实现，只完成调查与设计）

## 1. 现状

`modules/member1_comm/collector/ros2_window.py` 的 `request_count`
是**订阅侧收到的消息数**，不是 Action 业务请求数。
第二轮已把它与训练窗口的定义对齐（30 s、同名字段），
但**语义上它仍是话题消息计数**，不是 `SendGoal` 次数。

## 2. 在 Action 上可以观察到什么

ROS 2 Action 由三组服务 + 两个话题组成：

| 事件 | 类型 | 能否在订阅侧观测 |
| --- | --- | --- |
| `send_goal` | 服务请求（Goal UUID 由客户端生成） | 只能在服务端观测 |
| `cancel_goal` | 服务请求 | 服务端 |
| `get_result` | 服务请求 | 服务端 |
| `feedback` | 话题 | 可订阅 |
| `status` | 话题 | 可订阅 |

因此**可信的 `SendGoal` 计数只能在 Action Server 侧（Gateway）取得**，
订阅侧拿不到"有多少次业务请求被提交"。

## 3. 时间顺序约束（决定能否作为特征）

M1 在 F0 中运行，位于 Planner **之前**。因此：

- 当前请求的 Gateway 决策（ALLOW/BLOCK）与执行结果
  **在 M1 判断时尚未发生**，绝对不能作为特征；
- 但"**过去窗口**内该资源上的 SendGoal 次数"在判断时已经存在，
  属于合法的历史行为特征。

即可以使用：`[t-W, t)` 区间内、由**受信任组件**（Gateway 或 Action server
侧边车）记录的 SendGoal 计数；不可以使用：`[t, t+Δ)` 内本请求的结果。

## 4. 需要的受信任组件（设计，未实现）

```
Gateway / Action Server 侧边车（受信任进程）
    │ 在收到 send_goal 时，用原子计数器写入历史窗口账本：
    │   {resource, window_start, window_end, send_goal_count}
    ▼
M1 采集器读该账本（只读、带 SHA 与时间戳），得到 request_count
```

必须满足：

1. 计数由**服务端**产生，业务 JSON 无法伪造；
2. 只读过去窗口，不能读取当前请求的处理结果；
3. 账本带写入时间与哈希，可审计；
4. M1 只能读，不能写（避免反向构造）。

## 5. 为什么本轮没有实现

实现该侧边车需要修改 Gateway 或新增 ROS 2 节点，
而任务书明确规定**不得修改 `src/rg_gateway/**`**，
且新增节点需要与最终集成协调启动顺序与权限。
因此本轮只完成调查与接口设计，**如实标记 BLOCKED**，
不以"话题消息数"冒充 Action 请求数。

## 6. 若将来实现，验收要求

- 存在可复现实验，显示账本计数与 Gateway 审计里的 `RosCommEvent` 数量一致；
- 时间窗口严格在判断时刻之前；
- 篡改账本会被 M1 拒绝（哈希/权限校验）；
- 与 M2 的 STRICT 身份要求不冲突。
