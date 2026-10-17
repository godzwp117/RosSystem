# 2026-10-19 演示候选版本选定说明

> 本文确定**唯一**用于 2026-10-19 演示验收的候选版本。
> 其余分支（`fix/m2-m3-acceptance`、`integration/m3-online-evidence-20261016`、
> 旧 `demo/2026-10-19-rc`）**不再**被指定为正式演示版本。

---

## 1. 最终候选分支名

```
demo/2026-10-19-rc2
```

---

## 2. 完整 40 字符 Git SHA

| 角色 | 值 | 说明 |
| --- | --- | --- |
| **最终复验所测定的代码状态** | **`f6574acbf51062a96a918ac3096e7aecf83371c6`** | 不可变事实：`scripts/final_verify_demo.py` 在此提交上执行，工作区干净 |
| **rc2 分支 Tip（含证据与报告）** | 用标签解析（见下） | 会随文档修订前进，**故不在此写死** |
| 标签 `demo-2026-10-19-rc2-verified` | 指向 rc2 Tip | 权威引用；不可变 |

> **为什么不在正文写死 Tip SHA**：本文件位于该分支上，每次修订都会改变 Tip。
> 因此正文只固定**受测 SHA**（不可变事实），分支版本一律通过标签解析：
>
> ```bash
> git fetch origin --tags
> git rev-parse demo-2026-10-19-rc2-verified^{commit}   # => rc2 Tip
> ```

**源码等价性证明**（可独立复跑）：

```bash
git fetch origin --tags
TAG=$(git rev-parse demo-2026-10-19-rc2-verified^{commit})
git diff --stat f6574acbf51062a96a918ac3096e7aecf83371c6 "$TAG" \
    -- scripts src config security tests modules identity_trust docs/interfaces
# 输出为空 => 受测状态与标签目标的源码、契约、策略完全一致；
# 两者差异仅存在于 docs/reviews/** 与 artifacts/**（文档与证据）。
```

> 之所以存在两个 SHA：复验必须在**工作区干净**时执行（`GIT-02` 强制），
> 而证据只能在复验**之后**提交。因此"受测 SHA"必然早于"含证据的 Tip"。
> 标签指向 Tip 以便评审者 checkout 后同时拿到代码与证据，
> 但其**受测代码状态**由上面的等价性证明锚定到 `f6574ac`。

---

## 3. 父提交与继承来源

```
baseline a4c5971（公共稳定基线，未改动）
  └── chore/member-deliveries 3ce8202       [PR #6]  三成员交付归档
        └── fix/m2-m3-acceptance 19f6a25     [PR #7]  M2/M3 整改
              └── integration/m3-online-evidence-20261016  （本轮前 SHA 36b2f98）
                    └── demo/2026-10-19-rc2               （本候选）
```

**实测继承关系**（`git merge-base --is-ancestor`）：

| 断言 | 结果 |
| --- | --- |
| `baseline` → `fix` | ✅ 祖先 |
| `fix` → `integration` | ✅ 祖先 |
| `integration` → `demo/2026-10-19-rc2` | ✅ 祖先 |

本候选的父提交即 `integration/m3-online-evidence-20261016` 的 HEAD
（含 ON-06 勘误提交 `ec4258a`）。

---

## 4. 相对 baseline 的主要变更

| 类别 | 内容 |
| --- | --- |
| 成员交付归档 | `deliveries/member{1,2,3}-*`（三成员原始交付、实验报告、证据） |
| M2 实现 | `identity_trust/assessor.py`（离线 DDS 证据解释器）+ 单元测试 |
| M3 实现 | `modules/member3_taskrisk/{module,risk_model}.py`（确定性规则引擎）+ 测试 |
| 公共契约 | `docs/interfaces/schemas/`、`CONTRACT_VERSION.md`（**未改语义**） |
| 验收器加固 | `scripts/check_member_module.py`：LIM-01 可证伪、REAL-STATE 退出码、ADP-01 输入拒绝、ID-03/05 契约对齐 |
| 在线联调工具 | `scripts/m3_online_drive.sh`、`m3_online_extra.sh`、`verify_m3_online_evidence.py` |
| 验收证据 | `artifacts/acceptance/m2_m3_fix/`、`artifacts/demo-2026-10-19/**` |
| 审查文档 | `docs/reviews/**`（含 ON-06 勘误、状态快照、声明口径） |

---

## 5. 相对旧演示候选（`demo/2026-10-19-rc` = `df5a0f0`）的新增内容

**关键事实：旧演示候选相对 `fix/m2-m3-acceptance` 的**文件内容差异为零**。**
（`git diff origin/fix/m2-m3-acceptance origin/demo/2026-10-19-rc` 输出为空；
其 8 个额外提交全部是 merge 提交。）

因此旧候选**不含**任何 M3 在线集成成果。本候选相对旧候选新增：

| 新增内容 | 文件 |
| --- | --- |
| 在线联调驱动器（两组场景） | `scripts/m3_online_drive.sh`、`scripts/m3_online_extra.sh` |
| 跨层证据独立复核工具 | `scripts/verify_m3_online_evidence.py`（含 claims 对账） |
| ADP-01 / ID-03 修复与反例 | `scripts/check_member_module.py`、`tests/unit/test_adp01_input_rejection.py`、`test_event_id_contract_boundaries.py` |
| 在线证据反例测试 | `tests/unit/test_m3_online_evidence_counterexamples.py` |
| **ON-06 勘误与复发防护** | `docs/reviews/ON06_EVIDENCE_CORRECTION.md`、`tests/unit/test_on06_report_claims.py`、`report_claims.json` |
| 真实在线证据包 | `artifacts/demo-2026-10-19/m3-online-m3online-20261016T134406Z/`（66 文件，含 SHA256SUMS） |
| 本轮最终复验证据 | `artifacts/demo-2026-10-19/final-review-<run_id>/` |
| 状态与声明文档 | `SYSTEM_STATUS_20261016_CURRENT.md`、`COMPETITION_CLAIMS_20261016_CURRENT.md` |

**结论：旧候选必须被本候选取代，不得沿用旧 SHA 宣称在线集成已完成。**

---

## 6. 包含的真实模块

| 模块 | 类型 | 说明 |
| --- | --- | --- |
| **M3 `task_risk`** | **真实（EXTERNAL）** | 确定性可解释规则引擎，`TASK_CONSTRAINT_RULES_V1` |
| Gateway / F0 适配层 | 真实 | `scripts/team_demo.py` + `src/rg_gateway` + `src/rg_policy` |

---

## 7. 仍为 Mock 的模块

| 模块 | 状态 |
| --- | --- |
| **M1 `comm_risk`** | **显式 MOCK**（`mock_modules/comm_risk_mock.py`） |
| **M2 `identity_trust`** | **显式 MOCK**（`mock_modules/identity_trust_mock.py`） |

**必须明确：本候选的真实在线组合是 `M1 MOCK + M2 MOCK + M3 EXTERNAL`。**
**不得**宣称三模块全真实联合防护。

M1 之所以保持 Mock：其交付缺可加载的数值 JSON 模型，且性能门槛 FAIL
（F1 0.1312 / 0.6346，均低于恒预测攻击基线 0.8132 / 0.8719）。
M2 之所以保持 Mock：它是历史 DDS 证据解释器，对当前候选入口
`/rg/guarded_navigate` 恒为 `UNKNOWN`，若启用会持续阻断推进。

---

## 8. DDS 运行模式

| 层次 | 模式 | 域 |
| --- | --- | --- |
| M3 在线联调（L3） | **普通模式（未启用 DDS-Security）** | **42** |
| DDS-Security Enforce 回归（L4） | **Enforce** | **43** |

**两者是分别独立的运行，不是同一次 Enforce 在线全链路实验。**
对外只能声明"普通模式下真实 M3 在线集成 + 独立 Enforce 安全对照"。

---

## 9. 实际验证过的安全能力

| 能力 | 证据 |
| --- | --- |
| Gateway 权威准入（合法任务 ALLOW + 执行 + 1 Goal） | ON-01 |
| M3 越界阻断且不提交 Gateway（Goal 0） | ON-02 |
| UNKNOWN / ERROR 失败关闭（不提交、Goal 0） | ON-03 / ON-04 |
| **Gateway 独立于 M3 建议的阻断权**（M3 允许但 Gateway BLOCK，Goal 0） | ON-05 |
| **客户端超时 ≠ Gateway BLOCK ≠ 未执行** | ON-06（勘误后） |
| DDS Enforce 最小权限 + 原生拒绝 + 正向对照 + 不静默回退 | S1–S6（域 43） |
| 适配层输入拒绝可证伪（不靠崩溃假通过） | ADP-00 / ADP-N01..N10 |
| 证据篡改可检出（含声明对账） | 证据反例 + ON-06 复发防护 |

---

## 10. 尚未实现的研究能力

| 能力 | 状态 |
| --- | --- |
| 三模块全真实联合在线运行 | `NOT_READY`（M1 缺模型；M2 对候选入口恒 UNKNOWN） |
| ROS 2 实时入侵检测（在线特征采集） | `NOT_READY` |
| M1 有效通信异常检测 | `NOT_READY`（性能门槛 FAIL，F1 低于平凡基线） |
| DDS 动态权限调整 | `NOT_READY`（仅静态最小权限） |
| 动态任务状态机 | `NOT_INTEGRATED` |
| 同一次运行内的 Enforce 在线全链路 | `NOT_RUN`（L3 普通模式 + L4 独立 Enforce） |

---

## 11. 当前是否已执行最终验收

**是。** 最终复验在同一 SHA 上按 L0–L4 顺序执行，
结果见 `docs/reviews/DEMO_20261019_FINAL_VERIFICATION.md`
与证据目录 `artifacts/demo-2026-10-19/final-review-<run_id>/`。

---

## 12. 推荐的版本冻结方式

### 12.1 候选固定（已完成）

代码收敛后记录唯一 SHA，并**只**用该 SHA 执行最终复验。
在复验完成前，不得使用 `verified` / `release` 字样。

### 12.2 正式冻结（复验达标后执行）

为**通过复验的那个 SHA** 创建不可变注解标签：

```
demo-2026-10-19-rc2-verified
```

创建方式（在已推送到远程的前提下）：

```bash
git fetch origin --tags
RC2=$(git rev-parse origin/demo/2026-10-19-rc2)
git tag -a demo-2026-10-19-rc2-verified "$RC2" \
  -m "2026-10-19 演示候选（已通过最终复验）"
git push origin demo-2026-10-19-rc2-verified
```

实际采用的标签消息中同时记录了受测 SHA 与 Tip SHA，以及源码等价性证明命令。

**规则**：

- 只有复验达到验收要求才允许打 `verified` 标签；
- 标签一旦创建**不再移动**（必要时新建 `rc3`）；
- **2026-10-16 旧预检标签 `demo-2026-10-19-rc-preflight-20261016` 保持不变**，
  仍指向 `df5a0f0`，作为历史快照。

---

## 13. 旧演示候选与各分支的处置

| 引用 | 处置 |
| --- | --- |
| `demo/2026-10-19-rc`（`df5a0f0`） | **保留为历史候选**，不再作为正式演示版本；不删除、不强推 |
| 标签 `demo-2026-10-19-rc-preflight-20261016` | **保持不变**（仍指 `df5a0f0`） |
| `fix/m2-m3-acceptance`（`19f6a25`） | 保留为整改成果分支；其内容已被 rc2 包含 |
| `integration/m3-online-evidence-20261016` | 保留为在线集成开发分支；其内容已被 rc2 包含 |
| `demo/2026-10-19-rc2` | **唯一正式演示候选** |

**唯一性声明**：自本文档起，`demo/2026-10-19-rc2`（及其 `verified` 标签）
是**唯一**被指定用于 2026-10-19 演示验收的版本。
其余分支仅作为历史或开发过程记录，**不得**同时被标注为正式演示版本。
