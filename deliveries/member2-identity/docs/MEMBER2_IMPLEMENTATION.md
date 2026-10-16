# 成员二：DDS 身份与资源权限安全分析模块

基线：`godzwp117/RosSystem` / `baseline`，本次查阅分支 HEAD：`a4c597161d254192b662ee7b8f4d17f76a89cc16`。开发交付包仅新增文件，未修改 Schema、DDS 权限、Gateway、其他成员模块。契约仍为 `PROPOSED_V1` / `1.0.0-proposed`。

## 1. 安全边界

这是**离线受控实验的证据解释器**，不是在线 DDS 身份认证器。即使输出 `AUTHORIZED`，也只表示所引用的历史实验中访问成功；**不能推导当前业务请求已经完成 DDS 认证**，更不能代替 Gateway 授权。`request_id`、`producer`、`subject.declared_enclave`、`observations` 均不构成认证证明，因而模块永远不会根据它们填写 `authenticated_identity`。

所有 `--experiment-run`、`--case`、`--policy`、`--keystore` 和 `--evidence-root` 参数只能从受信任的本地命令配置提供，绝不从 stdin 读取选择要验证的日志路径。**没有受控真实运行、权限文件或核验不足，一律 `UNKNOWN`**。默认示例 `REPLACE_WITH_REAL_SROS2_RUN_ID` 是有意不生效的占位值。

实验模式 **ROS_DOMAIN_ID=43**，与普通开发域 **42** 不混用。不得把 `ROSPaCe` 的攻击分类标签当作 DDS 认证真值；不得改写源策略来制造正向结果。`security/keystore/` 属本地敏感目录，只引用 `permissions.xml`，不读取、展示或打包私钥。

## 2. 证据映射

| 对照 | DDS 来源/目标 | 必须同时成立的证据 | 模块结果 |
|---|---|---|---|
| S2 | `/planner` → `/rg/guarded_navigate` | XML 源策略允许、生成 DDS 权限允许；受控摘要 S2 PASS；`planner.log` 的 `PLANNER_RESULT.success=true, status_code=EXECUTED`；1 个 downstream goal | `AUTHORIZED`（历史受控实验） |
| S3C | `/gateway` → `/rg/nav_execute` | XML 源策略允许、生成 DDS 权限允许；S3C PASS；`rogue_gateway.log` 的 `ROGUE_RESULT` 成功；1 个 goal | `UNKNOWN`（当前信封候选资源固定为 `/rg/guarded_navigate`，不能用执行端的成功放行另一个资源）；`extensions.positive_control_verified=true` |
| S3 | `/planner` → `/rg/nav_execute` | 源策略和生成 DDS 权限均不允许；S3 PASS；原生 Fast DDS `SECURITY Error ... not found in allow rule`；0 个 goal；**同 run 的 S3C 真实成功** | `DENIED`、`DDS_ACCESS_CONTROL` |
| S4 | `/unauthorized` → `/rg/nav_execute` | 同上，且 S4 PASS、存在原生拒绝、S3C 正向对照成功 | `DENIED`、`DDS_ACCESS_CONTROL` |
| S5 | 业务策略拒绝 | `OUT_OF_REGION` 是业务拒绝，**不是** DDS 拒绝 | 本模块不按 DDS `DENIED` 解读 |
| S6 | Keystore 缺失 | 初始化失败不是资源 ACL 的正向授权 | 本模块不按 `AUTHORIZED` 解读 |

**不接收仅凭超时、自己宣称是 gateway、Mock 报文、仅配置正确或仅 `summary.json` 的 PASS 标签作为充分证明。**

当前实现使用 `security/policies/minimal_permissions.xml` + `security/keystore/enclaves/<role>/permissions.xml`。对后者确认 domain=43、拒绝宽权限通配，并核对 DDS `rq/...Request` 的 publish + `rr/...Reply` 的 subscribe；只读取权限文件，不加载密钥。权限源与生成结果不一致 → UNKNOWN。读取摘要后继续核对场景元数据及原始客户端日志，拒绝场景要求 S3C 正向对照。

## 3. 使用方式

```bash
# 在完整 RosSystem baseline 工作区中复制本交付 ZIP 的文件，保留原文件结构。
# 不直接改 baseline/main；新建个人分支：
git switch baseline && git pull --ff-only origin baseline
git switch -c feature/member2-identity

# 不需要 ROS 的单元测试
python3 -m pytest tests/unit/test_identity_trust_assessor.py -q

# 在真实 Jazzy + Fast DDS + SROS2 Enforce 安全容器内：
scripts/setup_sros2.sh
scripts/shell.sh 'cd /ws && source install/setup.bash && python3 tests/integration/sros2_check.py --run-id member2_real_01'

# 运行现有适配层的离线正反案例校验（并未发送 ROS Action）
python3 scripts/member2_adapter_check.py --experiment-run member2_real_01
```

如果 `scripts/shell.sh` 的容器环境没有 `source install/setup.bash`，先按仓库 README 构建/初始化。真实安全实验必须在已安装 ROS 2 Jazzy、Fast DDS、SROS 2 的环境内运行；**本交付的作者侧环境无法执行这些实验**。

### 单独调用示例

```bash
python3 identity_trust/assessor.py --experiment-run member2_real_01 --case S2 \
  < /tmp/member2_envelope.json > /tmp/member2_assessment.json
```

`/tmp/member2_envelope.json` 应满足 `docs/interfaces/schemas/module_input.schema.json`。stdin 只能包含一个 JSON 对象；stdout 只包含一个 Schema 兼容的 JSON 对象；诊断只写 stderr。无可核验证据时，退出码仍可能为 0，但 JSON 的 `status=UNKNOWN`；非法信封退出码为 2，适配层应阻断。

## 4. 已有系统和本交付的区别

系统历史报告记载 `tests/integration/sros2_check.py` 在项目既有机器上达到 7/7 PASS。**这不是本次重新执行的结果**。本交付实现新的 `IdentityTrustAssessment` 数据生产者、Fail-Closed 检查和离线适配联调脚本；并未替换现有的 SROS 2 对照实验脚本。

## 5. 结果与待办（严格区分）

| 交付/验收项 | 状态 | 依据与说明 |
|---|---|---|
| 本地来源策略 XML 解析 | PASS | pytest 离线单测 |
| 生成 DDS 权限解析与弱权限检查 | PASS | pytest 离线合成权限样例 |
| 正反对照映射逻辑 | PASS | pytest 合成历史实验 fixture；不等于 DDS 实测 |
| 失败关闭 / 超时不能作为 DDS 拒绝 | PASS | pytest |
| stdin/stdout 单 JSON 协议 | PASS | CLI 子进程测试 |
| 真实 ROS 2 Jazzy S1–S6 本轮复现 | NOT_READY | 需要用户容器和真实 keystore |
| 本轮真实原生日志 / S3C 对照存证 | NOT_READY | 需执行现有 `sros2_check.py` |
| `team_demo.py` 完整仓库集成联调 | NOT_READY | 需在完整 RosSystem baseline 工作区运行 |
| Git 提交/PR | BLOCKED | 当前 GitHub 连接只有读取权限；须本地提交、推送并建 PR（目标 baseline） |

M1 对应项目原有 `scripts/setup_sros2.sh` / `tests/integration/sros2_check.py`，本交付不伪造运行结果。M2–M3 已实现解析和映射逻辑；M4–M5 的真实实验/系统联调需目标环境实跑才可签验收。

## 6. 文件

- `identity_trust/assessor.py` —— 核心模块；标准库实现。
- `tests/unit/test_identity_trust_assessor.py` —— 22 项离线断言（含参数化用例；真实通过数量以复测输出为准）。
- `scripts/member2_adapter_check.py` —— 复用原 `team_demo.py` 的离线联调检查。
- `config/team_modules.member2.example.yaml` —— fail-closed 配置示例，**不是可直接生产启用的配置**。
- `docs/MEMBER2_IMPLEMENTATION.md` —— 本文档。

## 7. 正式 Git 流程

```bash
git status --short
git add identity_trust tests/unit/test_identity_trust_assessor.py scripts/member2_adapter_check.py config/team_modules.member2.example.yaml docs/MEMBER2_IMPLEMENTATION.md
git commit -m "feat(identity): add fail-closed DDS permission evidence assessor"
git rev-parse HEAD
git push -u origin feature/member2-identity
```

然后创建 PR，base=`baseline`，附上实际 commit SHA、实测结果与证据路径。**不能声称这一步已经完成**。
