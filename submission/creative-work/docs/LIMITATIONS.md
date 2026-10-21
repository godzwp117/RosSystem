# 能力边界与限制（必须随作品披露）

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
