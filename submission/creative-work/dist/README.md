# dist/ —— 作品包（构建产物不入库）

仓库 CI 门禁 `member-module-gates` 检查 5 禁止跟踪 `*.tar.gz`（防数据集/模型缓存入库）。
我们**不修改该门禁**，因此压缩包由脚本生成、哈希与验收结果记录在此。

## 本轮实际构建（2026-10-21 UTC）

| 包 | 文件 | 大小 | SHA-256 |
| --- | --- | --- | --- |
| 离线回放包 | `RosSystem-creative-work-1.0.1.tar.gz` | 42 KB | `730dd5c28897646fe0f3e1246480838b0e9c6feb6ae1380c6328212f9e83e1d3` |
| **完整在线包** | `RosSystem-CreativeWork-Full-1.0.1.tar.gz` | 1.5 MB | `775fb0dca6609d7284e45eaa33df5623d8d84b8607cff6bb2b8b0c1af5dbdf47` |

两个包均通过 `verify_package.sh`：**13/13 PASS**（`PACKAGE_VERIFY=PASS`）。

## 重新构建

```bash
./package.sh 1.0.1        # 离线回放包
./package_full.sh 1.0.1   # 完整在线包（含 runtime/ 与 docker/）
./verify_package.sh       # 解包→启动→请求页面与回放接口→扫描密钥
```

> 压缩包含构建时间戳，重跑后哈希会变化；应以 `verify_package.sh` 的 13 项结果为准。
