# dist/ —— 作品包构建产物

> **本目录不跟踪 `*.tar.gz` 构建产物**（仓库 CI 门禁 `member-module-gates` 检查 5
> 明确禁止跟踪 `\.tar\.gz$`，用于防止数据集与模型缓存入库）。
> 我们不修改该门禁，而是让作品包**可复现构建**并记录哈希。

## 构建与校验（一条命令）

```bash
cd submission/creative-work
./package.sh 1.0.0     # 生成 dist/RosSystem-creative-work-1.0.0.tar.gz
./verify_package.sh    # 解包、真实启动、请求接口、检查不含密钥 → 13 项
```

## 本轮实际构建记录

| 项 | 值 |
| --- | --- |
| 文件名 | `RosSystem-creative-work-1.0.0.tar.gz` |
| 大小 | 约 32 KB |
| SHA-256 | `11ed2f77449439cd4e27b4d9c4ed641d3e706ab3521231d0f4fd5caf16199dc7` |
| 校验结果 | **13/13 PASS**（`PACKAGE_VERIFY=PASS`） |
| 构建时间 | 2026-10-21（UTC） |

```
11ed2f77449439cd4e27b4d9c4ed641d3e706ab3521231d0f4fd5caf16199dc7  RosSystem-creative-work-1.0.0.tar.gz
```

> 由于压缩包内容含构建时间戳，重跑 `package.sh` 得到的哈希可能不同；
> 校验应以 `verify_package.sh` 的 13 项结果为准，而不是比对某一次的历史哈希。
