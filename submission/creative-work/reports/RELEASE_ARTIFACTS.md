# RosSystem 1.1.0 发布产物清单

> 本研究分支的发布产物。1.0.3 的标签、压缩包与历史证据未修改。

| 项 | 值 |
| --- | --- |
| 版本 | `1.1.0`（研究分支 `research/cross-layer-security-v1.1.0`） |
| 构建时源码提交 | `d50604452603ea3dbd5cd7d067f6eef967fb48c1` |
| 构建时工作树 | 干净（`source_tree_dirty_entries=0`） |
| 冻结基线 | `creative-work-v1.0.3`（标签对象 `7b60b28…` → 提交 `5773fb4…`） |
| 受测安全核心 | `2f3de257c9eac873093201292f6b2a9571da4f03` |

## 产物

| 产物 | 大小 | SHA-256 |
| --- | --- | --- |
| `RosSystem-creative-work-1.1.0.tar.gz`（离线回放） | 69,628 B | `45026b057643e80262a2ba82c05b3ab781e201d80e08be0c5323081f9a2a5057` |
| `RosSystem-CreativeWork-Full-1.1.0.tar.gz`（完整在线） | 2,179,249 B | `c47b7a5b6bc933d22cd3fd6cf023f360648f200f94e2b740f4a3e1d1244aa9e0` |
| `RosSystem-CreativeWork-Full-1.1.0.tar.gz.sha256` | — | 与上一行一致 |
| `RosSystem-CreativeWork-Full-1.1.0.manifest.txt` | — | 含 artifact_commit 与大小 |

## 已执行的包验证

1. `sha256sum -c`：离线包与完整包均 **OK**；
2. 解压后扫描 `.pem/.key/.p7s`：**无**；
3. 完整包 `reports/` 含 1.0.3 报告、1.0.3 证据索引、1.1.0 基线审计与 1.1.0 最终报告；
4. 完整包 `runtime/artifacts/acceptance/exports/` 含 1.0.3 归档与 4 个 1.1.0 证据归档；
5. 构建 `16e74e…` 的全新解压 + 全新容器 `rosystem-jazzy:1.1.0`：
   - `colcon build` 4/4；
   - 新实验室 CA + 权限复核 PASS；
   - DDS Enforce **7/7 PASS**；
   - 6 个关键测试文件 **121 passed**；
   - 三真实 LEVEL1/2 PASS，LEVEL3 BLOCKED。
6. 最终包 `82c2f0ff…`（仅文档/报告变化）复验：
   - `sha256sum -c` OK；
   - 解压后无 `.pem/.key/.p7s`；
   - `reports/` 与 `runtime/artifacts/...` 证据存在；
   - 同一 6 个关键测试文件 **121 passed**；
   - **未**在最终包上重跑 DDS 7/7；该结果属于构建 `16e74e…`，两者代码相同、仅文档不同。

> 该复现是**同一宿主上的独立目录/独立容器**复现，不是第三方主机复现。
> 构建产物不包含私钥或证书；keystore 只在实验容器内临时生成并清理。

## 复现命令

```bash
cd submission/creative-work
sha256sum -c dist/RosSystem-CreativeWork-Full-1.1.0.tar.gz.sha256
tar -xzf dist/RosSystem-CreativeWork-Full-1.1.0.tar.gz -C /tmp/verify
cd /tmp/verify/RosSystem-CreativeWork-Full
./docker/build-runtime.sh
docker run --rm -v "$PWD/runtime:/ws" -w /ws rosystem-jazzy:1.1.0 bash -lc \
  'source /opt/ros/jazzy/setup.bash && colcon build --symlink-install'
```

严格 acceptance 在本包内标记为 `NOT_SUPPORTED_IN_ARCHIVE`；整体状态见
`artifacts/acceptance/exports/research_v110/acceptance_v110.json`（INCOMPLETE）。
