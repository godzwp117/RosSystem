# 论文局限性与有效性威胁

## 1. 结论范围

1. **M1 模型未通过验证**：部署模型 `validation_gate_passed=false`；
   6 维候选依赖 `duration_ms`，未部署；真实正常窗口 12 个、异常会话 1 个，
   无法给出可信 FPR/FNR。
2. **三真正向未实现**：LEVEL1/2 PASS，LEVEL3 BLOCKED；阻断原因是 M1 UNKNOWN，
   不是“通过但未记录”。
3. **当前身份绑定只到意图主题**：`rt/m2/candidate_task`，不是
   `rq/rg/guarded_navigate/_action/send_goalRequest`。Action 级实验为负结果。
4. **Gateway 证据 side channel**：按 `request_id` 命名的 JSON 文件，不是 Action
   协议内签名字段；文件系统在 TCB 内。
5. **实验 CA ≠ 生产 CA**：临时 CA、文件私钥、无 HSM、无 CRL/轮换、无独立 UID。
6. **样本量**：DDS 7/7、负向 6/6、M2 17/17、Gateway 14/14 都是小样本；Wilson
   下界 0.61–0.89，不能外推为高可靠概率。
7. **实验主机**：同一宿主、同一容器/同派生镜像；未做第三方主机/CI 复现。
8. **仿真执行**：NavigationSim 为 recorded_only 存根，不是实体机器人导航；
   P09 的 `EXECUTED` 只表示存根记录目标。
9. **组件延迟不是端到端延迟**：30 次在单进程/单主机测，未覆盖 DDS 发现和 Action
   调度。
10. **Web 证据是归档展示**：`ARCHIVED_RESEARCH_EVIDENCE`，不是在线实时；
    无浏览器截图为 NOT_RUN。

## 2. 有效性威胁（Threats to Validity）

### 2.1 内部有效性

- **标签来源**：M1 训练标签来自 ROSPaCe 实验条件，不是人工逐样本标注；
- **duration_ms 伪相关**：窗口时长与标签强相关，高 F1 可能来自窗口长度；
- **非独立检查项**：17/17、14/14 是检查项计数，不是 17/14 个独立实验；
- **P09 时钟**：同容器墙钟；未做跨主机时钟同步，因此不声明严格全局因果；
- **P07 隔离**：M1/M2 为 MOCK，只隔离 M3；“M3 阻断生效”不等于三真实链。

### 2.2 外部有效性

- 单一 DDS 实现（Fast DDS 2.14）、单一 RMW、单一 ROS 发行版；
- 单一容器/主机；未验证跨主机发现、NAT、不同内核；
- 只覆盖 Action 导航任务与固定 TaskPolicy，不能外推到其他任务；
- 未覆盖真实攻击流量（nmap/recon）与生产网络噪声。

### 2.3 构念有效性

- “身份已认证”在本论文中严格指“DDS 证书主体 + 当前请求摘要签名”；
  不等于“用户身份”或“业务授权”；
- “Gateway ALLOW”指 TaskPolicy + 身份门均通过，不等于下游物理执行成功；
- “PASS”是实验判定，不是安全证明。

### 2.4 结论有效性

- 负结果（Action 原始 reader 破坏服务发现）是工程性观察，未定位到 rmw 源码级
  根因；
- 未做统计功效分析；小样本区间宽；
- 未做多重比较校正（多个场景/指标）。

## 3. 复现性威胁

- 实验室 keystore 私钥在实验后清理；复现必须重新生成 CA（`setup_sros2.sh`）；
- `/tmp` 二进制、容器名、run_id 与时间戳影响路径；论文引用的是归档证据；
- 最终包复现是**同宿主**，不是第三方；
- Web 截图缺失（无浏览器），只有 HTTP/HTML/JSON 证据。

## 4. 论文中必须避免的表述

| 禁止 | 原因 |
| --- | --- |
| “实现了 Action send_goal 请求级身份” | 仅意图主题；Action 探测失败 |
| “M1 已具备生产级检测能力” | gate=false；数据不足 |
| “三真正向闭环已完成” | LEVEL3 BLOCKED |
| “DDS Enforce 达到生产级” | 临时 CA，无生产运维 |
| “30 次端到端重复” | 组件级重复 |
| “第三方独立复现” | 同宿主新目录/容器 |
| “Web 实时展示研究证据” | 归档只读；在线证据另计 |
| “零误报/零漏报” | 样本量不足，且 500 Hz 未检出 |

## 5. 建议的论文写法

- 把 C1–C4 写成“实验室可行性 + 可复现证据链”，不要写成生产部署；
- 把 P07 纠错、13 项测试根因、Action 负结果放入 Threats/Experience；
- 明确区分 `AUTHENTICATED` 与 `AUTHENTICATED_LAB`；
- 给出每个数字的 n、范围、证据路径和 Wilson 区间；
- 在 Discussion 中说明：M1 的 blocker 是“模型 + 观测”双重不足，而非单纯算力/时间。
