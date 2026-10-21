# dist/ —— 参赛作品可执行包（已入库）

> 仓库 CI 门禁 `member-module-gates` 检查 5 默认禁止跟踪 `*.tar.gz`（防数据集与模型缓存入库）。
> 经赛事交付需要，**为该目录下的两个命名受控的作品包开放白名单**，
> 白名单之外的任何 `.tar.gz` 仍然会被 CI 拒绝。

## 实际交付文件

| 包 | 文件 | 大小 | SHA-256 |
| --- | --- | --- | --- |
| 离线回放包 | `RosSystem-creative-work-1.0.1.tar.gz` | 42 KB | `730dd5c28897646fe0f3e1246480838b0e9c6feb6ae1380c6328212f9e83e1d3` |
| **完整在线包** | `RosSystem-CreativeWork-Full-1.0.1.tar.gz` | 1.5 MB | `775fb0dca6609d7284e45eaa33df5623d8d84b8607cff6bb2b8b0c1af5dbdf47` |

两个包均通过 `verify_package.sh`：**13/13 PASS**（`PACKAGE_VERIFY=PASS`）。
各自的 `.sha256` 文件可直接用于 `sha256sum -c` 校验。

## 使用

```bash
# 离线回放（无需 Docker / ROS 2）
tar -xzf RosSystem-creative-work-1.0.1.tar.gz
cd RosSystem-creative-work-1.0.1
./run.sh                      # http://127.0.0.1:8787/  点击「离线回放」

# 完整在线（需要 Docker）
tar -xzf RosSystem-CreativeWork-Full-1.0.1.tar.gz
cd RosSystem-CreativeWork-Full
python3 dashboard/docker_runtime.py "$PWD"   # 先检查在线条件
./run.sh
```

## 重新构建

```bash
./package.sh 1.0.1        # 离线回放包
./package_full.sh 1.0.1   # 完整在线包
./verify_package.sh       # 解包→启动→请求接口→扫描密钥
```

> 压缩包含构建时间戳，重新构建后哈希会变化；应同时更新本文件与 `.sha256`。
> 验收以 `verify_package.sh` 的 13 项结果为准。
