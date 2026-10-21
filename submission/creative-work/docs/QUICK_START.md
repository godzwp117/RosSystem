# 快速开始

## 1. 只看法则（评委 60 秒路径）

```bash
tar -xzf RosSystem-creative-work-1.0.0.tar.gz && cd RosSystem-creative-work-1.0.0
./run.sh
```
浏览器打开 `http://127.0.0.1:8787/` → 点击 **离线回放** → 依次查看：
运行状态 → 跨层架构 → M3 六场景矩阵 → Planner TIMEOUT 证据比较 → 能力边界。

## 2. 在线演示（需要 Docker + 已构建）

在完整仓库根目录构建一次工作空间后：

```bash
./run.sh
```
界面显示 `ONLINE 就绪` → 选择 `controlled` → **启动实验** → 等日志出现完成 →
**装载证据** 查看 ON-01（ALLOW + Goal 1）与 ON-05（BLOCK + Goal 0）。

## 3. 停止与清理

```bash
./stop.sh
```
只停止本作品控制台（按 PID 文件与精确路径匹配），不影响其他 ROS 进程。

## 4. 重新打包与校验

```bash
./package.sh 1.0.0
./verify_package.sh
```
`verify_package.sh` 会解包、真实启动、请求页面与接口，并检查包内不含密钥材料。
