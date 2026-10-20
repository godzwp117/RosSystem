# M1 生产交接说明（工作 C）

> 基准：`86a8910bf4560dfe455bec09bc503600c30bf670`
> 分支：`research/m1-trusted-action-retraining`

## 1. 本轮交付

| 文件 | 状态 | 作用 |
| --- | --- | --- |
| `scripts/m1_session_collector.py` | 新增 | 单会话多资源窗口观测器（固定 30 s、不重叠、特征仅来自真实观测） |
| `scripts/m1_collect_sessions.py` | 新增 | 场景编排：正常高频/突发/重启 + 定性异常 |
| `scripts/m1_leakage_audit.py` | 新增 | 强制泄漏审计 + 会话级留一评估 |
| `docs/research/M1_TRUSTED_DATA_COLLECTION_SPEC.md` | 新增 | 采集与标签规范（先于数据写定） |
| 4 篇研究报告 | 新增 | 来源、审计、评估、Action 对接 |

**未修改**：`modules/member1_comm/**`、`config/team_modules.three-real.yaml`、
F0、Gateway、DDS 权限、M2 签发代码。

## 2. 给集成的明确建议

**不要启用任何 M1 模型。** 当前既没有通过门槛的新模型，
旧模型也已被证明依赖 `duration_ms` 泄漏。

生产配置应保持：M1 在有可信在线证据前返回 **UNKNOWN**，
F0 因此失败关闭。这正是当前系统应有的行为。

## 3. 下一轮的精确阻断条件

| 阻断 | 具体条件 | 归属 |
| --- | --- | --- |
| B1 | 窗口需支持时间驱动，才能看到 graph-only 攻击 | M1 |
| B2 | 每类攻击 ≥5 个独立会话、正常 ≥20 个会话 | M1（需采集时长） |
| B3 | 真实 `action_send_goal_received_count` | M2（typesupport 接线） |
| B4 | 正式 Enforce 下的 M1 在线推理基准 | M1 + 集成 |

## 4. 复现

```bash
python3 scripts/m1_collect_sessions.py --out <dir>/sessions --duration 65
python3 scripts/m1_leakage_audit.py --sessions <dir>/sessions --out <dir>/leakage_audit.json
```
