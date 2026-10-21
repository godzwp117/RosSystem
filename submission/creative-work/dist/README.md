# dist/ —— 参赛作品可执行包（已入库）

> 仓库 CI 门禁 `member-module-gates` 默认禁止跟踪 `*.tar.gz`。本目录的
> `RosSystem-creative-work-<x.y.z>.tar.gz` 与 `RosSystem-CreativeWork-Full-<x.y.z>.tar.gz`
> 属白名单；其余压缩包仍会被拒绝。

## 当前交付版本：1.1.0（研究分支）

| 包 | 文件 | 大小 | SHA-256 |
| --- | --- | --- | --- |
| 离线回放包 | `RosSystem-creative-work-1.1.0.tar.gz` | 69628 B | `45026b057643e80262a2ba82c05b3ab781e201d80e08be0c5323081f9a2a5057` |
| **完整在线包** | `RosSystem-CreativeWork-Full-1.1.0.tar.gz` | 2179249 B | `c47b7a5b6bc933d22cd3fd6cf023f360648f200f94e2b740f4a3e1d1244aa9e0` |

构建来源：`artifact_commit=d50604452603ea3dbd5cd7d067f6eef967fb48c1`，
构建时工作树干净（`source_tree_dirty_entries=0`）。1.0.3 标签与旧包保持不变。

### 1.1.0 变更

- DDS 实验室 Enforce 重新验证：新 CA、domain 43、7/7 正向 + 6/6 负向；
- M2 当前请求身份：真实 DDS writer→证书主体→请求摘要 + Ed25519（LAB scope）；
- Gateway 双层授权：独立身份再核验 + TaskPolicy（G1–G4 14/14）；
- 13 项身份单测实质性修复（56/56），全量单测 920 passed / 4 skipped；
- 三真实 LEVEL1/2 PASS，LEVEL3 **仍 BLOCKED**（M1 门槛未通过）；
- 完整包包含 1.0.3 归档、1.1.0 证据、报告与不依赖 `.git` 的哈希清单。

详细结论见 `reports/ROSYSTEM_1_1_0_RESEARCH_AND_SECURITY_VALIDATION_REPORT.md`，
边界见 `docs/LIMITATIONS.md`。**1.1.0 不是生产版。**

---

## 1.0.3（冻结版本，保留）

| 包 | 文件 | 大小 | SHA-256 |
| --- | --- | --- | --- |
| 离线回放包 | `RosSystem-creative-work-1.0.3.tar.gz` | 33202 B | `36f8954caa80b4e44bf157ee9776f7edaf80fb0347f0cdd5db7adae092a2d7bb` |
| **完整在线包** | `RosSystem-CreativeWork-Full-1.0.3.tar.gz` | 1765195 B | `42e0d21d098297806812f13dd6e75a87cded950dcd4ae3021e1b59ce2aa01022` |

构建来源：`artifact_commit=bcbec1bfc6b0ac26db447975b41fcda762934ec9`，
构建时工作树干净（`source_tree_dirty_entries=0`）。

### 1.0.3 变更（仅验收语义与状态显示，不改安全核心）

1.0.2 存在**验收语义缺陷**：`--mode acceptance` 用单一 rc 汇总，
DDS Enforce 因缺凭据返回 `NOT_RUN` 时不置位失败标志，于是出现

    ENFORCE=NOT_RUN
    ACCEPTANCE=PASS
    exit_code=0

1.0.3 修复为统一状态机（`scripts/acceptance_status.py`）：

| 必需项情况 | 整体结果 | 退出码 |
| --- | --- | --- |
| 全部实际执行并 PASS | PASS | 0 |
| 至少一个 FAIL | FAIL | 1 |
| 无 FAIL 但至少一个 NOT_RUN | **INCOMPLETE** | **9** |
| 预检失败 | PREFLIGHT_FAIL | 8 |
| 未执行任何项 | INCOMPLETE | 9 |

FAIL 与 NOT_RUN 并存时结果为 FAIL，但 NOT_RUN 项完整保留在
`summary.txt` 的 `NOT_RUN_ITEMS` 里。控制台把 exit 9 显示为
`INCOMPLETE`（既不是 DONE 也不是 FAIL），并修复了"停止早于容器创建"
时残留 Created 容器的问题（`docker rm -f` + 退出后重试确认）。

配套回归：`tests/unit/test_acceptance_status.py`（14 例）、
`tests/unit/test_run_controller_status.py`（4 例）、
`tests/integration/acceptance_semantics_check.sh`（5 例）、
`tests/integration/acceptance_wiring_check.sh`（6 例）。

> `ACCEPTANCE=INCOMPLETE` 表示"没有失败，但并非全部执行"，**不是** PASS。
> 公开包缺 SROS 2 凭据时 DDS Enforce 只能是 NOT_RUN。

## 历史版本（保留，不覆盖）

| 版本 | 离线包 SHA-256 | 完整包 SHA-256 |
| --- | --- | --- |
| 1.0.2 | `58e3cc57687dcc369b7b70515feb8394e35668f4050320ae0f9c5c1610e277e1` | `4aa7f6235835258659800caf34ca27d477452a5cf8190ff93d7f929c97211584` |
| 1.0.1 | `730dd5c28897646fe0f3e1246480838b0e9c6feb6ae1380c6328212f9e83e1d3` | `775fb0dca6609d7284e45eaa33df5623d8d84b8607cff6bb2b8b0c1af5dbdf47` |

> 1.0.1 缺少 `runtime/docs/interfaces` 与 `mock_modules`；1.0.2 修复了打包
> 与三真实假阳性，但 acceptance 语义有缺陷。两者均不建议再用于演示。

## 使用

```bash
# 离线回放（无需 Docker / ROS 2）
mkdir -p replay && tar -xzf RosSystem-creative-work-1.0.3.tar.gz -C replay
(cd replay && ./run.sh)            # http://127.0.0.1:8787/ 点击「离线回放」

# 完整在线（需要 Docker + 可拉取 ros:jazzy）
mkdir -p full && tar -xzf RosSystem-CreativeWork-Full-1.0.3.tar.gz -C full
cd full/RosSystem-CreativeWork-Full
docker build -t rosystem-jazzy:1.0.3 docker/
docker run --rm -v "$PWD/runtime:/ws" -w /ws rosystem-jazzy:1.0.3 \
  bash -lc "source /opt/ros/jazzy/setup.bash && colcon build --symlink-install"
export ROS_IMAGE=rosystem-jazzy:1.0.3 ROS_ONLINE_DOMAIN=77
./run.sh
```

## 验收范围说明

- **公开发布包验收**：受控在线、三真实负向、Web 在线、回放、边界与清理。
  DDS Enforce 与正式身份认证因无私钥 → `NOT_RUN`，整体 acceptance → `INCOMPLETE`。
- **完整安全验收**：需要授权的 SROS 2 keystore 与真实测试条件，
  只能在内部环境执行；其结果不得与公开包结论混用。

## 校验

```bash
sha256sum -c RosSystem-CreativeWork-Full-1.0.3.tar.gz.sha256
sha256sum -c RosSystem-creative-work-1.0.3.tar.gz.sha256
```

## 重新构建

```bash
./package.sh 1.0.3        # 离线回放包
./package_full.sh 1.0.3   # 完整在线包（内含 29 项完整性门禁）
./verify_package.sh       # 解包→启动→请求接口→扫描密钥
```

> 压缩包含构建时间戳，重新构建后哈希会变化；应同时更新本文件与 `.sha256`。
