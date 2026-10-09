# M3 审阅包（上传用）

本目录是交给外部审阅者（ChatGPT 等）的材料包。

## 文件清单

| 文件 | 用途 |
| --- | --- |
| `00_dossier.md` | **主文件**：待验证命题 C1–C6、复核方式、安全模型、已知限制、建议输出格式 |
| `01_m3.patch` | 完整 diff（`git diff main...3a6d2df`，288K） |
| `02_commits.txt` | 8 个阶段提交 |
| `03_changelog.md` | 含缺陷记录与 I25–I32 未解决事项 |
| `04_evidence_index.md` | 结论 → 证据包对照表 |
| `key_files/` | 9 个核心源文件快照 |

## 上传前做过的处理（诚实声明）

1. **宿主路径已脱敏**：`00_dossier.md`、`01_m3.patch`、`03_changelog.md` 中的
   真实宿主用户名路径已替换为 `${WORKSPACE}`。**仅替换了文档/注释文本，代码 hunk 未改动。**
   若需逐字节精确的 diff，请自行执行：

   ```bash
   git diff 838f66f 3a6d2df
   ```

2. **`key_files/` 与仓库逐字节一致**：9 个文件均以 SHA-256 与
   `git show 3a6d2df:<path>` 比对通过（9/9 一致），未被任何脱敏改动。

3. **文档子集通过敏感信息扫描**（`scripts/check_evidence_safety.py` → `PASS`）。

## 关于安全扫描器的一个已知局限（附带价值）

`check_evidence_safety.py` 是**面向日志**设计的。把它直接指向**源代码**会产生误报，例如：

- `self._clear_token_param = self.declare_parameter(...)` 被 `credential_assignment` 规则命中；
- 源码里的 PEM 正则 `-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----` 被 `private_key_material` 命中。

这不是缺陷披露，而是**工具适用边界**：源码快照的完整性用哈希比对（上文第 2 条）保证，
不用面向日志的扫描器。审阅者若认为该工具应支持"代码模式"，这本身是一条可采纳的改进建议。

## 复现环境

见 `00_dossier.md` 第 8 节。

> **警告**：`security/keystore/` 含明文私钥，已被 `.gitignore` 排除，**绝不可上传或提交**。
