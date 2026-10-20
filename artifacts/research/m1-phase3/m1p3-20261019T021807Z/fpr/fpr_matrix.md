# 真实 ROS 2 正常/异常流量回归

- 容器：rg_m1p3（Domain 59）
- 窗口：30.0 s（与训练契约一致）
- 生成时间：2026-10-19T02:28:09Z

| 场景 | 标签 | 状态 | 窗口数 | 平均分 | 判定 |
| --- | --- | --- | --- | --- | --- |
| normal_2hz | normal | SCORED | 1 | 0.013662 | NORMAL |
| normal_10hz | normal | SCORED | 1 | 0.008623 | NORMAL |
| normal_50hz | normal | SCORED | 1 | 0.008032 | NORMAL |
| normal_100hz | normal | SCORED | 1 | 0.007096 | NORMAL |
| anomaly_storm_500hz | anomaly | SCORED | 1 | 0.006592 | NORMAL |

## 汇总

- 正常场景：4 个，有效判定 4，误报 0，UNKNOWN 0
- 异常场景：1 个，有效判定 1，检出 0

> 异常场景是"异常负载"，不等价于真实攻击；标签由实验条件决定，不是按模型输出反推。
