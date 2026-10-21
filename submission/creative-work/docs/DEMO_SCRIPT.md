# 评委演示脚本（约 6 分钟）

## 0. 开场（20 秒）

> RosSystem 把 ROS 2 机器人任务执行的安全判断拆成**三层证据 + 一个权威网关**：
> 通信风险、身份可信、任务风险三路建议，由 F0 做可信证据核验，
> 最后由 SecurityGateway 依 TaskPolicy 做**唯一权威放行**。

## 1. 打开控制台（30 秒）

`./run.sh` → 浏览器 `127.0.0.1:8787`。
指出顶部徽章：若显示 `UNAVAILABLE`，说明在线条件不足并给出原因，
此时可点「离线回放」查看已归档真实证据 —— **不会自动降级后仍显示 ONLINE**。

## 2. 跨层架构（60 秒）

指架构图：三模块并列 → F0 汇聚 → Planner → Gateway → NavSim。
强调：模块只给**建议**，Gateway 才有**权限**；DDS-Security 在通信层独立执行。

## 3. 受控在线：一放一行（90 秒）

选 `controlled` → 启动实验 → 完成后装载证据：
- ON-01：F0 READY → Gateway **ALLOW** → NavSim **Goal 1**；
- ON-05：M3 建议允许、F0 也放行，但 Gateway 依 TaskPolicy **BLOCK**，**Goal 0**。

> 一句话：**模块建议不等于最终权限。**

## 4. 三真实严格（60 秒）

选 `three-real-strict` → 启动：
三模块全部 EXTERNAL、Schema 全合法，但 F0 **ADAPTER_BLOCK**。
> 这不是故障，是**证据不足时正确失败关闭**。

## 5. 审计案例：TIMEOUT 不等于 BLOCK（60 秒）

打开「Planner TIMEOUT 证据比较」：
同一场景在封版 run 是 `到达 0 / Goal 0`，在历史加固 run 是 `到达 1 / ALLOW / Goal 1`。
> 所以**不能**用 Planner 超时推断请求被阻断或取消，必须看每次运行的原始审计。

## 6. 收尾（30 秒）

说明能力边界：M1 模型未过验收、M2 生产签发者未就绪、
**`THREE_REAL_LEVEL3_READY = BLOCKED`**，NavigationSim 是 `recorded_only` 存根。

## 录屏建议

- 分辨率 1920×1080，浏览器全屏，隐藏书签栏；
- 先跑一次 `--check` 展示环境自检；
- 在线演示前确认无残留节点（界面会显示环境状态）；
- 全程不要剪掉出现 `UNAVAILABLE` 或 `FAIL` 的片段 —— 真实失败展示本身就是可信度。
