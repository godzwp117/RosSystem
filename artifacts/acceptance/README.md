# 验收证据体系（artifacts/acceptance）

本目录定义 RosSystem 的**标准化验收证据**格式、生成方式与校验规则。
所有结论必须能回溯到真实执行，禁止用"代码已编写""理论上可行"替代运行验证。

## 目录结构

```text
artifacts/acceptance/
├── README.md                       本文件：格式、生成方式、验收规则
├── schema/
│   └── acceptance.schema.json      冻结的数据契约（JSON Schema 2020-12）
└── exports/                        每次运行生成的证据包（不纳入版本控制）
    ├── <run_id>/
    │   ├── manifest.json           核心契约：阶段、状态、版本、环境、汇总
    │   ├── environment.json        宿主/容器/ROS/RMW/镜像版本
    │   ├── test_results.json       业务场景结果（含 A/B、12 项负例）
    │   ├── security_results.json   M2 安全对照实验结果（仅 M2 阶段）
    │   ├── file_hashes.json        包内每个文件的 SHA-256 与脱敏排除清单
    │   └── logs/                   本次运行相关的日志与测试证据副本
    └── <run_id>.tar.gz(.sha256)    可移植归档包与其 SHA-256 sidecar
```

## 生成方式

```bash
# 一个命令导出（P0 修改前快照）
python3 scripts/export_acceptance.py --phase P0 --status PASS --run-id p0_before_m1 \
    --note "M1 修改前的原始状态快照"

# M2 安全对照实验
python3 scripts/export_acceptance.py --phase M2 --status PASS \
    --security-mode enforce --security-results /tmp/m2_security.json \
    --status-matrix /tmp/status_matrix.json
```

常用参数：

| 参数 | 说明 |
| --- | --- |
| `--phase` | `P0` / `M1` / `M2`（必填） |
| `--status` | `PASS` / `FAIL` / `PARTIAL` / `BLOCKED`（必填） |
| `--run-id` | 证据包目录名；缺省为 `<phase小写>_<UTC时间戳>`；已存在则**拒绝覆盖** |
| `--security-mode` | `disabled`（默认）或 `enforce` |
| `--scenario-summary` | `scenario_runner` 的 `summary.json`，可重复；缺省自动收集 `tests/evidence/*/summary.json` |
| `--security-results` | M2 安全对照实验结果 JSON |
| `--include` | 额外纳入的日志文件或目录，可重复 |
| `--status-matrix` | 最终状态矩阵 JSON（写入 manifest） |
| `--no-archive` | 不生成 tar.gz |

导出行为约定：

* **只读**：不修改 `logs/`、`tests/evidence/` 中的任何原始文件，只做复制。
* **数据真实**：commit SHA 取自 `git rev-parse HEAD`；镜像 ID/RepoDigest 取自
  `docker inspect`。镜像无可用 RepoDigest 时 `docker_image_digest` 写 `null`，
  同时保留真实 `docker_image_id`，**不编造 digest**。
* **脱敏**：`security/keystore/`、`build/`、`install/`、`.git/` 及各类密钥后缀
  （`.pem/.key/.p12/.pfx/.csr/.srl/.der`）一律排除；正文命中私钥/证书/口令模式的文件
  也会被排除。排除项记录在 `file_hashes.json` 的 `excluded` 字段中。
* **哈希自洽**：`file_hashes.json` 不含自身哈希（无法自哈希）；归档包创建后包内文件不再
  变化，其 SHA-256 写在与包同级的 `<run_id>.tar.gz.sha256` sidecar 中。

## 校验方式

```bash
python3 scripts/verify_acceptance.py artifacts/acceptance/exports/<run_id>
python3 scripts/verify_acceptance.py artifacts/acceptance/exports/<run_id>.tar.gz
```

校验项：

1. JSON 是否符合 Schema；
2. 必填字段是否完整；
3. 每个文件的 SHA-256 是否与 `file_hashes.json` 一致；包内是否有多余未登记文件；
4. 场景引用的 `log_path` / `evidence_files` 是否真实存在；
5. 判定 PASS 的场景是否有真实执行证据（命令、返回码、存在的证据文件、无 FAIL 断言），
   以及**阶段 PASS 与 `test_summary` 是否自洽**（`failed`/`not_run` 必须为 0，
   否则默认判为错误，可用 `--allow-not-run` 降级为警告）；
6. 证据包内是否含敏感密钥文件或密钥正文；
7. 归档包 SHA-256 是否与 sidecar 一致。

退出码：`0` 校验通过，`1` 校验失败，`2` 用法/路径错误。

## 数据契约（schema_version 1.0）

`manifest.json` 必填字段（不得任意更名，只允许向后兼容地扩展）：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `schema_version` | string | 固定 `"1.0"` |
| `run_id` | string | 唯一运行标识，同时是目录名 |
| `timestamp_utc` | string | ISO8601 UTC，以 `Z` 结尾 |
| `phase` | enum | `P0` / `M1` / `M2` |
| `status` | enum | `PASS` / `FAIL` / `PARTIAL` / `BLOCKED` |
| `source.repository` | string | 例如 `godzwp117/RosSystem` |
| `source.commit_sha` | string | 40 位十六进制 |
| `source.git_dirty` | boolean | 生成时工作区是否有未提交改动 |
| `environment.host_os` | string | 宿主系统 |
| `environment.container_name` | string | 例如 `rg_jazzy` |
| `environment.ros_distro` | string | 例如 `jazzy` |
| `environment.rmw_implementation` | string | 例如 `rmw_fastrtps_cpp` |
| `environment.docker_image_id` | string | 镜像 ID |
| `environment.docker_image_digest` | string \| null | RepoDigest，无则 `null` |
| `security_mode` | enum | `disabled` / `enforce` |
| `test_summary` | object | `passed` / `failed` / `not_run`（+可选 `blocked`/`total`） |

场景记录（`test_results.json` 与 `security_results.json` 的元素）必填字段：

`scenario_id`、`scenario_name`、`expected_result`、`actual_result`、`status`、
`command`、`exit_code`、`duration_ms`、`log_path`、`evidence_files`、`reason_code`。

`status` 取值 `PASS` / `FAIL` / `NOT_RUN` / `PARTIAL` / `BLOCKED`。
**未执行的场景必须显式记录为 `NOT_RUN`，不得默认按通过处理。**

安全场景额外字段：`security_mode`、`source_role`、`source_enclave`、
`requested_resource`、`downstream_goal_count`、`rejection_layer`
（`dds_security` / `action_server_unreachable` / `business_task_policy` / `not_applicable`）。
`rejection_layer` 用于区分 DDS 层拒绝、Action Server 不可达与业务 TaskPolicy 阻断 ——
**仅客户端超时不足以证明 DDS 权限规则生效**。

### Schema 子集

`scripts/verify_acceptance.py` 内置的校验器只实现本仓 schema 用到的关键字：
`$ref`（仅本地 `#/$defs/...`）、`type`（含类型数组）、`required`、`properties`、
`additionalProperties`（`false` 或子 schema）、`items`、`enum`、`pattern`、
`minLength`、`minimum`。因此 `acceptance.schema.json` 被**刻意限制在该子集内**，
以保证"Schema 可校验"这一点是真实成立的，而不是依赖未安装的第三方库。
如需扩展 schema，请同步扩展校验器并更新本节。

## 验收规则

* 只有**全部 P0 必需测试通过**时才允许把 `status` 记为 `PASS` 并冻结 `p0-stable-v1.0`。
* 存在未执行项时，阶段状态应记 `PARTIAL`；环境/依赖缺失导致无法执行时记 `BLOCKED`，
  并在 `notes` 中写明技术原因与实际影响。
* 不得删除或改写历史证据包；每次运行生成新的 `run_id` 目录。
* `exports/` 不纳入 Git；`schema/`、生成工具与本文档纳入 Git。
