# 2026-10-19 演示能力矩阵

> 受测版本：`be47ccd6c1b19460b65abc0ea8004706383d01d4`
> 分支：`release/demo-2026-10-19-freeze`
> 彩排 run_id：`rehearsal-20261018T144247Z`
> 契约：`PROPOSED_V1` / `1.0.0-proposed`（**未冻结**）

本表回答一个问题：**19 日现场，哪些话可以说，哪些不能说。**

---

## 1. 场景矩阵

| # | 演示场景 | 运行环境 | 本轮实测 | 可宣称 | **不可宣称** |
| --- | --- | --- | --- | --- | --- |
| 1 | Gateway A/B 基础闭环 | 域 56，普通模式 | **PASS** | 合法任务经 Gateway `ALLOW` 并真实执行（+1 Goal）；越界任务 `BLOCK`（0 追加 Goal） | 不得说成"三模块共同判定"——该场景 M1/M2 是 **MOCK** |
| 2 | 真实 M3 在线六场景 | 域 56，普通模式 | **PASS（6/6，39 检查 0 失败）** | 真实 M3 规则引擎参与在线准入；M3 阻断/UNKNOWN/ERROR 均失败关闭；Gateway 可独立阻断 | 不得说成"三真实模块联合在线准入"——M1/M2 在该场景是 **MOCK** |
| 3 | 三真实成员模块联合调用 | 宿主，严格身份模式 | **LEVEL 1+2 PASS，LEVEL 3 BLOCKED** | 三个成员程序**真实**被调用、输出合法、F0 正确融合并**正确阻断** | 不得说成"三真实模块已能正向联合准入"；也不得把正确阻断说成"系统故障" |
| 4 | F0 身份防伪造（P0） | 宿主，严格模式 | **PASS（38 passed）** | F0 不信外部模块自报 `AUTHENTICATED`；伪造完整 `checks` 也无法放行 | 不得说成"M2 已具备真实 DDS 身份认证" |
| 5 | DDS-Security Enforce | **域 43**，enforce | **PASS（7/7）** | DDS 原生权限拒绝生效（Planner 直连执行端被拒、未授权主体被拒）；正向对照成功；不静默降级 | 不得说成"与场景 2/3 同一次运行"——**域不同、run 不同** |

> **场景 5 与场景 2/3 是两次独立实验。** 现场必须分别陈述，不得合并成
> "三真实模块在 Enforce 模式下同次完整正向执行"。

---

## 2. 三个能力层次（必须区分）

| 层次 | 内容 | 状态 |
| --- | --- | --- |
| **A. 已实际验证的在线安全闭环** | `M1 MOCK + M2 MOCK + M3 EXTERNAL`：F0 失败关闭、M3 真实规则、Planner→Gateway→NavigationSim、DDS Enforce | **可用**（受控演示） |
| **B. 已完成的三真实模块集成** | 三模块全部 `EXTERNAL`，真实进程调用 + Schema + 关联 + 正确阻断 | **可用**，但 **LEVEL 3 BLOCKED** |
| **C. 已修复的 F0 身份信任边界** | 默认 `STRICT`，F0 独立核验原始证据；`CONTROLLED_TEST_ONLY` 需显式声明 | **可用** |

**A 与 B 不能混为一谈**：A 是"能跑通的安全闭环"，B 是"真实模块接进来了，
但真实证据不足所以被正确拒绝"。

---

## 3. 三个成员模块的真实状态

| 模块 | 真实能力 | **限制（必须同时说）** |
| --- | --- | --- |
| **M1 `comm_risk`** | 已有 Linux `/proc` 主机级 24 维采集器；真实数值模型可加载并推理 | 模型 `validation_gate_passed=false`，生产语义下只能 `UNKNOWN`；**部分 ROS 2 / RTPS 特征仍缺失**；**尚未证明具备有效的 ROS 2 在线通信攻击检测能力** |
| **M2 `identity_trust`** | 已有签名核验、签发者信任判定、请求绑定、新鲜度、原子 nonce 防重放组件 | **当前没有经审核的生产 DDS 身份签发者**；`test_issuer.py` 是 `TEST_ONLY`，无认证效力；严格真实模式**不能宣称已完成当前请求身份认证** |
| **M3 `task_risk`** | 确定性可解释规则引擎，可在真实条件下给出 `ALLOW_RECOMMENDED` / `BLOCK_RECOMMENDED` | `ALLOW_RECOMMENDED` **不是** Gateway 准入；不得包装成神经网络或未知攻击预测 |

---

## 4. 安全分层的准确表述

```
DDS-Security（原生身份与权限，域 43 独立验证）
        ↓ 只放行授权主体与资源
研究模块 M1/M2/M3（只输出证据与建议）
        ↓
F0 适配层（Schema + 关联 + 证据来源校验 + 失败关闭）
        ↓ 仅在证据充分时提交
Planner → /rg/guarded_navigate
        ↓
SecurityGateway（权威 TaskPolicy）
        ↓ 仅 ALLOW
/rg/nav_execute → NavigationSim
```

关键不变式（现场可强调）：

- `READY_FOR_GATEWAY_SUBMISSION` ≠ Gateway `ALLOW`；
- Gateway `ALLOW` ≠ 导航执行成功；
- 研究模块结论**不能**取代 Gateway 权威准入；
- 模块输出符合 Schema ≠ 证据可信；
- Planner `TIMEOUT` ≠ Gateway `BLOCK` ≠ 未执行。

---

## 5. 禁止宣称清单

1. ❌ "三个真实研究模块已完成可信的在线联合准入。"
2. ❌ "系统已具备 ROS 2 实时入侵检测能力。"
3. ❌ "M1 已能有效检测通信异常。"（模型门槛未过）
4. ❌ "M2 能认定当前请求的 DDS 身份。"
5. ❌ "三真实模块在 Enforce 模式下完成了同次正向全链路。"
6. ❌ "DDS 动态权限已实现自动调整。"（仅静态最小权限）
7. ❌ "动态任务状态机已集成。"
8. ❌ 把 Mock / 测试替身 / 离线模型表述为真实在线算法能力。
9. ❌ 把本轮"正确阻断"表述为系统缺陷或失败。

---

## 6. 本轮实测数字（可引用）

| 项 | 结果 |
| --- | --- |
| 契约与 Schema 校验 | **PASS** |
| 全仓单元测试 | 见 `logs/unit_full.log`（本轮实际输出） |
| F0 P0 安全反例 | **38 passed，0 xfailed** |
| 三模块真实验收 | M1 `60 PASS` / M2 `58 PASS` / M3 `58 PASS`，三模块 `meets_pr_gate=True` |
| 三真实联合 | LEVEL 1 **PASS** / LEVEL 2 **PASS** / LEVEL 3 **BLOCKED** |
| M3 在线六场景 | **6/6，跨层复核 39 检查 0 失败** |
| DDS Enforce | **7/7**（域 43） |
| 演示入口 | `--scenario all` **12/12 PASS** |

> 3 条 `FAIL` 是"MOCK 场景开关对真实模块不适用"的非门槛记录
> （`mandatory=False`、`gate=False`），**保留可见**，不是真实失败。

---

## 7. ON-06 的正确讲法

Planner 超时**不代表**请求未被执行，也不代表被拒绝。是否到达 Gateway、
是否 `ALLOW`、是否产生 Goal，必须从**本次** `run_id` 的日志读取。

累计实测（同一代码结构、不同 run）：

| 观测 | Gateway 到达 | 决策 | 执行 | Goal |
| --- | --- | --- | --- | --- |
| 历史 RC2 | 1 | ALLOW | 1 | 1 |
| B1 阶段一 | 0 | — | 0 | 0 |
| B1 阶段二 | 1 | ALLOW | 1 | 1 |
| F0 closeout | 1 | ALLOW | 1 | 1 |
| **本次彩排** | **0** | — | **0** | **0** |

→ 下游结果**在 0 与 1 之间摆动**。现场如被问及，应回答："这正是我们坚持
'超时必须查审计'的原因，不能预设。"
