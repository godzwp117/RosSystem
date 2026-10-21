# RosSystem 参赛作品包 · 跨层安全决策可视化控制台

> **作品名称**：RosSystem —— 面向 ROS 2 机器人任务执行的多源可信证据融合与可审计分层安全准入系统
> **受测代码 SHA**：`2f3de257c9eac873093201292f6b2a9571da4f03`
> **正式提交分支**：`release/final-submission-closeout-2026-10-22` @ `c5556e4be7008029c5a2b2b7b5fb752aa4b12c62`
> **作品包版本**：1.0.0

本包把已完成工程与安全验收的 RosSystem 转化为**评委可实际运行**的参赛作品。

---

## 两种作品包

| 包 | 内容 | 用途 |
| --- | --- | --- |
| `RosSystem-creative-work-1.0.1.tar.gz`（约 42 KB） | 控制台 + 回放快照 + 文档 | **离线回放**，无需 Docker/ROS 2 |
| `RosSystem-CreativeWork-Full-1.0.1.tar.gz`（约 1.5 MB） | 上述 + `runtime/`（ROS 2 源码/脚本/配置/接口）+ `docker/` | **在线演示**，需 Docker + ROS 2 Jazzy |

完整包内的 `runtime/` 已包含 `scripts/final_system.sh`、`src/`、`modules/`、`config/`、
`docs/interfaces/`、`identity_trust/`、`security/policies`；
**不含 keystore、私钥或证书**（打包时强制扫描）。

## 立即运行（无需 ROS 2）

```bash
tar -xzf RosSystem-creative-work-1.0.0.tar.gz
cd <解包目录>
./run.sh              # 默认 http://127.0.0.1:8787/
# 浏览器打开后点击「离线回放」
```

离线回放**不需要** Docker、ROS 2 或外网，读取的是已归档的真实实验证据。

停止：`./stop.sh`

## 两种运行模式（界面顶部徽章会明确显示）

| 徽章 | 含义 |
| --- | --- |
| `ONLINE 就绪` | 检测到 docker 且工作空间已构建，可启动真实实验 |
| `REPLAY / 历史证据回放` | 只读展示已归档真实证据，**不代表本次重新执行** |
| `UNAVAILABLE` | 在线条件不足（缺 docker 或未构建），界面会给出具体原因 |
| `RUNNING` | 正在运行白名单实验 |
| `FAIL` | 实验以非零退出码结束，界面显示真实失败原因 |

**在线不可用时控制台不会自动降级后仍显示 ONLINE PASS。**

## 在线演示（需要 Docker + 已构建工作空间）

在完整仓库根目录先构建一次：

```bash
docker run --rm -v "$PWD:/ws" -w /ws ros:jazzy bash -lc \
  'source /opt/ros/jazzy/setup.bash && colcon build --symlink-install'
```

然后在控制台选择模式并点击「启动实验」：

- `controlled`：受控正向在线（M1/M2 MOCK + M3 EXTERNAL）→ 合法任务 ALLOW、越界任务 Gateway 独立 BLOCK
- `three-real-strict`：三真实 External → F0 STRICT 正确 `ADAPTER_BLOCK`
- `enforce`：正式 DDS Enforce（域绑定，独立实验）
- `acceptance`：全量验收

控制台只**调用**既有入口 `scripts/final_system.sh`，**不重新实现** F0 / Gateway / DDS 的任何安全判断。

## 包内容

```
dashboard/     本地控制台（Python 标准库，无第三方依赖）
replay/        从真实证据提取的只读回放快照
tests/         控制台自检
docs/          快速开始、演示脚本、架构、清单、限制
run.sh         启动控制台
stop.sh        停止控制台
package.sh     重新打包
verify_package.sh  校验作品包
```

## 安全声明（必须随作品一起说明）

- M1 生产级 IDS **未通过**验收，研究模型未导出；
- M2 生产身份签发者**未就绪**，历史 `AUTHORIZED` ≠ 当前请求身份；
- 真实 Action SendGoal 请求级身份**未证明**；无可信速率授权基线；
- **`THREE_REAL_LEVEL3_READY = BLOCKED`**；
- NavigationSim 为 `recorded_only` 存根，**不代表实体机器人完成导航**；
- DDS Enforce 与普通在线模式是**不同域、不同 run** 的独立实验。

详见 `docs/LIMITATIONS.md`。
