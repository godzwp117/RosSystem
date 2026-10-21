# RosSystem 1.1.0 基线与能力差距审查（阶段一，实测）

> 分支：`research/cross-layer-security-v1.1.0`
> 基线：`creative-work-v1.0.3` = `5773fb486c8eabdf7c0dfa039b600faabacffe75`
> 状态：**能力差距审查已完成；本轮未实施 M1/M2/DDS 实质性增强**（原因见 §5）

---

## 1. 基线核验（实测）

| 项 | 值 | 核验方式 |
| --- | --- | --- |
| 冻结标签 | `creative-work-v1.0.3` | `git rev-parse` → `5773fb4…` ✅ |
| 报告提交 | `5773fb486c8eabdf7c0dfa039b600faabacffe75` | 存在 ✅ |
| 修复提交 | `bcbec1bfc6b0ac26db447975b41fcda762934ec9` | 存在 ✅ |
| 发布提交 | `332732e341db7b0f6e815863a7f6d62dc21a823d` | 存在 ✅ |
| 原始归档 | `e69325d8094e1d2bc309772650ae85a241751b31` | 存在 ✅ |
| 受测安全核心 | `2f3de257c9eac873093201292f6b2a9571da4f03` | 存在 ✅ |
| 历史标签 | `v1.0.2-creative-work` | 存在 ✅ |

## 2. 环境实测

| 项 | 值 |
| --- | --- |
| OS | Linux（宿主） |
| 宿主 ROS 2 | **未安装**（`/opt/ros/jazzy` 不存在） |
| ROS 2 运行方式 | Docker `ros:jazzy`，工作区挂载 `/ws` |
| Python（系统） | 3.12，`cryptography 3.4.8` ✅ |
| Python（研究 venv） | **无 `cryptography`**，无 Ed25519 |
| RMW | `rmw_fastrtps_cpp` |

> **关键约束**：非对称签名方案若要落地，需在 venv 中补齐 `cryptography`，
> 或改用系统解释器。这是实现 M2 前必须解决的依赖前提。

## 3. 13 项身份测试失败：根因定位（实测，非推断）

```
$ pytest tests/unit/test_identity_trust_real_logs.py -q
13 failed, 43 passed
```

**已排除的因素**：

| 假设 | 实测结论 |
| --- | --- |
| 测试顺序污染 | ❌ 否。单独运行同样失败 |
| 归档证据目录缺失 | ❌ 否。`artifacts/acceptance/exports/m2_sros2_enforce/logs/tests_evidence/20261009T093144Z` **存在**，含 S1/S2/S3/S3C/S4/S5/S6 + `summary.json` |

**已确认的事实**：

1. 归档目录中 **不存在任何 `permissions.xml`**（`find -name permissions.xml` 无结果）。
   13 项失败中至少 `test_permission_file_contradicting_runtime_fails_closed`、
   `test_missing_positive_control_fails_closed` 直接依赖该文件。
2. `S3C` 目录**只有 `rogue_gateway.log`**，没有配套的权限文件或结果 JSON。
   测试报错原文：
   > `STATE-S3C-POSITIVE-CONTROL 真实条件 s3c-positive-control（归档 S3C 日志 ROGUE_RESULT success=true，资源 = /rg/nav_execute）-> UNKNOWN`
   即：日志证据被读到了，但**缺少权限文件，评估器无法把它提升为 AUTHORIZED**，
   于是保持 `UNKNOWN`。这**符合失败关闭原则**，不是评估器 bug。
3. `S3` 的 `rogue_planner.log` 含真实 Fast DDS 拒绝记录：
   > `rr/rg/nav_execute/_action/send_goalReply topic not found in allow rule.`

**结论**：13 项失败的根因是**归档证据不完整**（缺 `permissions.xml` 与 S3C 配套材料），
而不是算法缺陷。要真正修复，必须**用实验室 CA 重新生成完整证据**，
不能靠跳过测试、放宽断言或把 FAIL 改成 NOT_RUN。

这与任务书 §6.4 的判断一致，且**不能通过修改测试修复**。

## 4. 能力差距矩阵（逐项，基于源码实测）

| 能力 | 1.0.3 已验证 | 目标 | 阻断因素 |
| --- | --- | --- | --- |
| M1 通信风险 | External 调用 + 严格负向 | 可信观测 + 风险分类 | 无可信观测链；模型未过验证门槛 |
| M2 身份可信 | 历史证据解释 + 失败关闭 | 当前请求可验证身份 | **无请求级签名**；无实验室 CA |
| M3 任务风险 | External 建议输出 | 完整正负场景 | 基本具备 |
| F0 联合准入 | 严格阻断 | 三真实正向 + 负向 | 依赖 M1/M2 正向证据 |
| Planner | 受控已验证 | 重试/超时/取消语义 | 未实现取消协议 |
| Gateway | 独立 TaskPolicy 已验证 | 与请求身份关联 | 无请求身份输入 |
| DDS Security | 历史 7/7；1.0.3 NOT_RUN | 可独立复现 Enforce | **归档缺 permissions.xml**；无实验室 CA 生成流程 |
| NavigationSim | Goal recorded_only | 生命周期审计 | 未实现 Action 状态机 |
| Web 控制台 | 在线 + 证据展示 | 科研级可视化 | 基本具备 |
| 独立复现 | 受控在线已通过 | 三真实正向可复现 | 依赖上述 P0 |

## 5. 本轮实际完成与未完成（如实）

### 已完成

- ✅ 基线核验：6 个关键 SHA 全部存在且可解析
- ✅ 分支 `research/cross-layer-security-v1.1.0` 从冻结标签派生，**未触碰 1.0.3 标签与历史包**
- ✅ 环境实测：宿主无 ROS 2；venv 缺 `cryptography`
- ✅ **13 项身份测试失败根因定位**：归档缺 `permissions.xml` 与 S3C 配套材料，
  非算法缺陷；排除顺序污染与目录缺失两种假设
- ✅ 能力差距矩阵（基于源码与实测）

### 未完成（必须如实标注）

| 项目 | 状态 | 原因 |
| --- | --- | --- |
| DDS 实验室 CA 与 Enforce 重建 | **NOT_RUN** | 需在容器内生成 CA/Enclave/权限并重跑 S1–S6；本轮预算不足 |
| M2 当前请求身份绑定（非对称签名） | **NOT_STARTED** | 需先补 `cryptography` 依赖并设计接口扩展 |
| M1 可信观测链与数据集 | **NOT_STARTED** | 需新增观测代理与数据集划分 |
| 三真实正向 LEVEL 3 | **BLOCKED** | 依赖 M1 正向证据 + M2 请求身份 |
| P01–P12 场景矩阵 | **NOT_RUN** | 依赖上述能力 |
| 30 次重复实验与统计 | **NOT_RUN** | 依赖上述能力 |
| 科研报告（18 章） | **NOT_STARTED** | 无可报告的实验结果 |

## 6. 不得作出的声明

- ❌ 不得声明 M1 具备生产级检测能力
- ❌ 不得声明 M2 已实现当前请求身份认证
- ❌ 不得声明三真实正向 LEVEL 3 已达成
- ❌ 不得把 13 项失败描述为"已修复"
- ❌ 不得把本审查文档描述为科研验证报告

## 7. 若继续推进的下一步（按优先级）

1. **补齐 venv 的 `cryptography`**（前置依赖，否则 M2 无法实现）
2. **实验室 CA 生成 + S1–S6 重建**：产出含 `permissions.xml` 的完整证据，
   同时修复 13 项身份测试（这是 P0 #1 与 #2，且互相依赖）
3. **M2 请求级签名**：`request_id + subject + resource + target_digest + exp + nonce`
   的规范化序列化 + Ed25519 签名 + nonce 账本
4. **M1 观测链**：从 Gateway audit / DDS 日志构造可信观测，保持 UNKNOWN 语义
5. **F0 接入 M2 请求身份**，再尝试三真实正向
6. 最后才是 P01–P12、重复实验、科研报告

> 顺序不能颠倒：没有实验室 CA 就没有完整证据；没有请求身份就没有正向准入；
> 没有正向准入就没有可统计的对照实验。
