# 作品包清单

| 文件 | 作用 |
| --- | --- |
| `run.sh` | 启动控制台（默认 127.0.0.1:8787） |
| `stop.sh` | 停止控制台（只匹配本作品进程） |
| `package.sh` | 重新打包（自动拒绝含密钥材料） |
| `verify_package.sh` | 解包→启动→请求接口→安全检查 |
| `dashboard/server.py` | HTTP 服务（标准库，无第三方依赖） |
| `dashboard/evidence_loader.py` | 只读装载真实证据 |
| `dashboard/run_controller.py` | 白名单运行控制器 |
| `dashboard/static/*` | 控制台前端（无 CDN 依赖） |
| `replay/replay_manifest.json` | 从真实证据提取的只读回放快照 |
| `docs/*` | 快速开始、演示脚本、架构、清单、限制 |
| `tests/*` | 控制台自检 |

## 打包安全

- 打包脚本在生成前扫描 `*.pem` / `*.key` / `*.p7s` / `id_rsa*`，命中即**拒绝打包**；
- 作品包**不包含** keystore、私钥、签发秘密或大型原始证据；
- 原始完整证据仍在仓库 `artifacts/integration/` 下，通过 SHA-256 校验。
