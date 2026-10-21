# M1 第三轮交接说明

> `RESEARCH_BASE_SHA` = `246bd8bd6b6829a73052235c0a4840b71ff53de5`
> 本轮分支：`research/m1-window-alignment`
> 证据：`artifacts/research/m1-phase3/m1p3-20261019T021807Z/`

## 1. 本轮交付

| 文件 | 状态 | 作用 |
| --- | --- | --- |
| `scripts/m1_window_attribution.py` | 新增 | 逐特征 logit 归因，定位分布偏移到具体特征 |
| `scripts/m1_normal_traffic_fpr.py` | 新增 | 真实 ROS 2 正常/异常流量回归编排 |
| `modules/member1_comm/collector/ros2_window.py` | **修改** | 新增窗口契约校验；契约不符时拒绝给结论 |

**未修改**：`scripts/team_demo.py`（F0）、`config/team_modules.three-real.yaml`、
Gateway、策略、DDS 权限、`user/**`。因此不影响已冻结演示版本。

## 2. 三条最重要的结论

1. **50 Hz 误报的根因是窗口契约不一致**，不是模型缺陷：
   1 s 窗口让 `duration_ms` 偏离训练分布 30 倍，单特征贡献 +169.35。
   对齐到 30 s 后同一模型给出 0.0076（NORMAL）。
2. **第二轮的高 F1 不可信**：`duration_ms` 在训练集里几乎等于标签
   （三类落在互不重叠的窄带，权重 −10.60）。
   去掉它后，未见攻击类别那一折只有 0.32/0.57，低于基线 0.666。
   本轮**撤回**第二轮的有效性结论。
3. **模型不具备高频负载异常的判别力**：500 Hz 风暴得分 0.0066，比 2 Hz 正常流量还低。

## 3. 交给最终集成的建议

**不要**把 `comm_risk_window_model.json` 设为正式部署模型。

理由：
- 其判别力主要来自 `duration_ms` 伪相关；
- 真实正常流量误报虽为 0/4，但每个场景只有 1 个窗口，且模型是"靠时长匹配"通过；
- 真实攻击检出未验证（0/1，且场景语义错配）。

建议后续顺序：

1. 先实现 §Action 观测账本（需要 Gateway 侧边车，跨团队）；
2. 用**本轮可复现的采集器**重新采集一套真实 ROS 2 正常/异常数据集，
   固定窗口契约（30 s），并保证每类 ≥ 数十个会话；
3. 在新数据集上重训，**显式禁止**任何与标签共线的特征
   （时长、资源名、segment id 等），并在报告中给出该约束的消融；
4. 只有在真实正常/攻击流量上同时满足 FPR 与召回门槛后，才提交集成。

## 4. 复现命令

```bash
# 归因
python3 scripts/m1_window_attribution.py \
    --model modules/member1_comm/model/comm_risk_window_model.json \
    --windows-json <采集输出>.json --out attribution.json

# 正常/异常回归（容器 rg_m1p3，Domain 59）
python3 scripts/m1_normal_traffic_fpr.py --container rg_m1p3 --domain 59 \
    --evidence artifacts/research/m1-phase3/<run_id>/fpr
```

## 5. 不得据此宣称

- ❌ 已具备有效在线通信攻击检测
- ❌ 第二轮 0.9919 F1 可作为泛化证据（本轮已撤回）
- ❌ 正常流量零误报 ⇒ 检测有效
- ❌ 话题消息数等于 Action 业务请求数
