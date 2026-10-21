# 能力边界与限制（必须随作品披露）

## 1.1.0 更新（2026-10-21，研究分支）

| 项 | 1.1.0 状态 |
| --- | --- |
| DDS 实验室 Enforce | **重新验证**：新实验室 CA，domain 43，7/7 正向 + 6/6 负向 |
| 当前请求身份 | **实验室范围**：真实 DDS writer→证书主体→请求摘要 + Ed25519；`AUTHENTICATED_LAB`，默认 F0 不接受 |
| Gateway 授权 | **双层**：独立身份再核验 + 未修改的 TaskPolicy；G1–G4 14/14 |
| 13 项身份单测 | **已实质修复**：补齐非秘密 permissions fixture，56/56 |
| M1 生产级 IDS | **仍未通过**：`validation_gate_passed=false`，三真实 LEVEL3 继续 BLOCKED |
| Action send_goal 请求级身份 | **未证明**：本轮绑定的是预准入意图主题，不是 Action 服务请求 |
| 生产身份/密钥生命周期 | **未就绪**：临时 CA、文件私钥、无 HSM/吊销/轮换 |
| 生产部署 | **未验证**：新包已做同宿主独立目录/容器复现，第三方主机未做 |

### 1.1.0 必须避免的误读

- `AUTHENTICATED_LAB` **不是**生产身份认证；
- 意图主题的身份绑定 **不等于** Action `send_goal` 的发送者身份；
- Gateway 身份门只增加阻断，**不能**让 TaskPolicy 拒绝的请求通过；
- DDS 7/7 是**实验室**结果，不是生产部署验证；
- 三真实 LEVEL3 仍然 `BLOCKED`，没有通过替换 Mock 或复用历史授权得到正向。


## 1.0.3 基线（保留原文，不移除历史限制）

| 项 | 状态 |
| --- | --- |
| 受控正向在线闭环（M1/M2 MOCK + M3 EXTERNAL） | ✅ 已验证 |
| Gateway 独立 TaskPolicy 阻断 | ✅ 已验证 |
| 三真实 External 调用与 Schema | ✅ 已验证 |
| 三真实严格模式正确阻断 | ✅ 已验证 |
| 正式 DDS-Security Enforce | ✅ 7/7（独立实验，域绑定） |
| **M1 生产级 IDS** | ❌ **未通过**（合法高负载误报、观测盲区） |
| **M2 生产身份签发者** | ❌ **未就绪**（对称 HMAC、同 UID、无审批） |
| **真实 Action SendGoal 请求级身份** | ❌ **未证明** |
| **可信速率授权基线** | ❌ **不存在**（TaskPolicy 与 DDS 权限均无速率定义） |
| **`THREE_REAL_LEVEL3_READY`** | ❌ **BLOCKED** |

## 必须避免的误读

- NavigationSim 记录 Goal ≠ 实体机器人完成路径规划与导航；
- M3 `ALLOW_RECOMMENDED` ≠ Gateway `ALLOW`（建议不等于权限）；
- M2 历史 `AUTHORIZED` ≠ 当前请求的生产身份；
- F0 `READY` ≠ Gateway `ALLOW`；
- Planner `TIMEOUT` ≠ Gateway `BLOCK` ≠ 请求取消 ≠ 未执行；
- DDS Enforce 与普通在线模式**不是同一次实验**。

## TIMEOUT 证据比较（本作品的一个审计案例）

| run | Planner | Gateway 到达 | 决策 | Goal |
| --- | --- | --- | --- | --- |
| `closeout-20261021T023020Z`（封版） | TIMEOUT | 0 | 无 | 0 |
| `harden-20261020T171740Z`（历史加固） | TIMEOUT | 1 | ALLOW | 1 |

两次真实运行给出不同结果。现有日志**没有可严格比较的 Planner 超时与 Goal 时间戳**，
因此**不宣称** Goal 发生在超时之后，只陈述两者在同一请求上同时成立。
