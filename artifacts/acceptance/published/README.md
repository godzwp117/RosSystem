# published/ — 可公开发布的脱敏验收证据

本目录由 `scripts/publish_acceptance.py` 自动生成并推送到证据分支。

* 每个 `<run_id>/` 是一次验收运行的**脱敏公开副本**；
* `<run_id>.tar.gz` 为同内容的归档，`.sha256` 为其校验值；
* `file_hashes.json` 登记的是**脱敏后**文件的 SHA-256；
* 原始（未脱敏）证据包仅保存在受控本地环境的
  `artifacts/acceptance/exports/<run_id>/`，可通过
  `manifest.redaction.source_package_sha256` 在本地比对；
* 脱敏映射表**不随包发布**，无法据此还原真实主机身份。

校验方式：

```bash
python3 scripts/verify_acceptance.py artifacts/acceptance/published/<run_id>
python3 scripts/check_evidence_safety.py --path artifacts/acceptance/published/<run_id>
```
