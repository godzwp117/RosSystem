# dist/ —— 参赛作品可执行包（已入库）

> 仓库 CI 门禁 `member-module-gates` 默认禁止跟踪 `*.tar.gz`（防数据集与模型缓存入库）。
> 经赛事交付需要，**为该目录下两类命名受控的作品包开放白名单**：
> `RosSystem-creative-work-<x.y.z>.tar.gz` 与 `RosSystem-CreativeWork-Full-<x.y.z>.tar.gz`。
> 白名单之外的任何 `.tar.gz` 仍然会被 CI 拒绝。

## 当前交付版本：1.0.2

| 包 | 文件 | 大小 | SHA-256 |
| --- | --- | --- | --- |
| 离线回放包 | `RosSystem-creative-work-1.0.2.tar.gz` | 32481 B | `58e3cc57687dcc369b7b70515feb8394e35668f4050320ae0f9c5c1610e277e1` |
| **完整在线包** | `RosSystem-CreativeWork-Full-1.0.2.tar.gz` | 1758537 B | `4aa7f6235835258659800caf34ca27d477452a5cf8190ff93d7f929c97211584` |

1.0.2 相对 1.0.1 的修复（依据独立复现报告 D-01..D-15）：

- 修复 `docs/interfaces` 被拍平成 `runtime/interfaces` 的打包缺陷；
- 补齐受控在线必需的 `mock_modules/`、三真实 M1 观测 fixture 与 `tests/`；
- 修复 `final_system.sh` 退出码恒为 1 的判定缺陷，并写入 `tested_commit.json` 运行元数据；
- 三真实严格模式不再把"模块崩溃/契约失败"当成成功阻断（分层 LEVEL1/2/3 判定）；
- 控制台 ONLINE 探测改为复用 `docker_runtime.probe()`，实验在 Jazzy 镜像内执行；
- 控制台可读取本次新产生的 `dashboard-runs` 证据，并区分 ONLINE / REPLAY / ARCHIVED；
- DDS Enforce 缺凭据时明确标记 `NOT_RUN`，不再以历史 7/7 冒充本次结果。

## 历史版本（保留，不覆盖）

| 包 | 文件 | 大小 | SHA-256 |
| --- | --- | --- | --- |
| 离线回放包 | `RosSystem-creative-work-1.0.1.tar.gz` | 42279 B | `730dd5c28897646fe0f3e1246480838b0e9c6feb6ae1380c6328212f9e83e1d3` |
| 完整在线包 | `RosSystem-CreativeWork-Full-1.0.1.tar.gz` | 1544992 B | `775fb0dca6609d7284e45eaa33df5623d8d84b8607cff6bb2b8b0c1af5dbdf47` |

> 1.0.1 保留用于追溯，**不建议再用于演示**：完整包缺少 `runtime/docs/interfaces`
> 与 `mock_modules`，受控在线实验无法运行。

## 使用

```bash
# 离线回放（无需 Docker / ROS 2）
mkdir -p replay && tar -xzf RosSystem-creative-work-1.0.2.tar.gz -C replay
(cd replay && ./run.sh)            # http://127.0.0.1:8787/  点击「离线回放」

# 完整在线（需要 Docker + 可拉取 ros:jazzy）
mkdir -p full && tar -xzf RosSystem-CreativeWork-Full-1.0.2.tar.gz -C full
cd full/RosSystem-CreativeWork-Full
docker build -t rosystem-jazzy:1.0.2 docker/
docker run --rm -v "$PWD/runtime:/ws" -w /ws rosystem-jazzy:1.0.2 \
  bash -lc "source /opt/ros/jazzy/setup.bash && colcon build --symlink-install"
export ROS_IMAGE=rosystem-jazzy:1.0.2 ROS_ONLINE_DOMAIN=77
./run.sh
```

## 校验

```bash
sha256sum -c RosSystem-CreativeWork-Full-1.0.2.tar.gz.sha256
sha256sum -c RosSystem-creative-work-1.0.2.tar.gz.sha256
```

## 重新构建

```bash
./package.sh 1.0.2        # 离线回放包
./package_full.sh 1.0.2   # 完整在线包（内含 29 项完整性门禁）
./verify_package.sh       # 解包→启动→请求接口→扫描密钥
```

> 压缩包含构建时间戳，重新构建后哈希会变化；应同时更新本文件与 `.sha256`。
