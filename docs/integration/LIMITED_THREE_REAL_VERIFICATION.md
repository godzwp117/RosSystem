# 受限三真实联合集成验证

> 集成分支：`integration/three-real-limited-verification`
> 共同基准：`be47ccd6c1b19460b65abc0ea8004706383d01d4`
> M1 来源：`research/m1-window-alignment@d5f03af47df6aac90157d5e86817732fb2c8e691`
> M2 来源：`research/m2-action-origin-binding@a1d699674204543afc8b15c88bd6df8c7da794de`
> run_id：`int-20261019T143527Z`
> 证据：`artifacts/integration/three-real-limited/int-20261019T143527Z/`

---

## 0. 结论先行

**`LIMITED_INTEGRATION_CONDITIONAL`**

理由：三真实调用、Schema、严格失败关闭、M2 惰性、DDS Enforce 正反例
都已在本分支上**真实运行并通过**；但 ROS 2 下游实机、M3 受控在线六场景
两项**未在本轮启动**（NOT_RUN），因此不满足无条件通过的条件。

**本结论不是 LEVEL 3 通过。** 三真实模块仍无法给出正向在线准入：
M1 的检测有效性在第三轮已被证伪（`duration_ms` 标签泄漏），
M2 的生产身份信任根仍未就绪。本轮只证明"新代码可以在完整系统中共存且不破坏安全边界"。

## 1. 合流方式

从 `be47ccd` 派生，按固定 SHA 依次合流两条研究分支：

```
be47ccd (common base)
  ├── merge d5f03af (M1 window-alignment)       --no-ff
  └── merge a1d6996 (M2 action-origin-binding)  --no-ff
        └── b0bf9cf fix(m2): EntityId 越界读取修复
```

两次合流**无冲突**。M1 只改动 `modules/member1_comm/**` 与 `scripts/m1_*.py`；
M2 只新增 `src/m2_witness/**`、`scripts/m2_*.py`、`tests/integration/m2_*`；
两者与 F0（`scripts/team_demo.py`）、Gateway、策略、DDS 权限均无交集。

## 2. 已发现并修复的缺陷：Writer GUID 越界读取

集成审查指出 M2 的 Writer GUID 序列化存在越界读取，**该指摘成立**。

Fast DDS 的实际布局：

```
GuidPrefix_t::size == 12
EntityId_t::size   == 4      <-- 只有 4 字节
```

而原实现用 `for (i = 0; i < 12; ++i) ... guid.entityId.value[i]`，
读到 `value[4..11]`，**越界 8 字节**，属未定义行为。

### 为什么之前的测试没抓到

**AddressSanitizer 抓不到**：对象内越界不跨越分配块边界，ASan 不报。
实测用 `-fsanitize=address` 跑完整入口/客户端流程，ASan 只报了
**124 字节内存泄漏**，没有任何越界报告。这说明"跑过 ASan"不能作为该类缺陷的保证。

### 修复与验证

修复提交 `b0bf9cf`：两处见证组件均改用 `rtps::EntityId_t::size` 与
`rtps::GuidPrefix_t::size`。

可观测差异（真实运行证据）：

| 版本 | writer_guid 的 entity 段 | 长度 |
| --- | --- | --- |
| 修复前 | `000001030000000001000000` | 24 hex = **12 字节（越界产物）** |
| 修复后 | `00000103` | 8 hex = **4 字节（正确布局）** |

回归测试 `tests/unit/test_m2_witness_guid_safety.py`：

1. **静态约束**：禁止 `i < 12` 遍历 `entityId.value`，强制使用 size 常量
   （已确认该断言在修复前源码上会失败）；
2. **证据约束**：所有记录的 `writer_guid` 的 entity 段必须是 8 个十六进制字符、
   prefix 必须有 11 个点。

### 该缺陷对结论的影响

即使已修复，**M2 研究组件仍不得作为生产身份信任根**：
签发仍是对称 HMAC、与 F0 同 UID、无审批流程、Action send_goal 捕获未接线。
本轮把它保持在"研究组件、非信任根"的状态。

## 3. 逐项验收结果

| # | 验收项 | 结果 | 证据 |
| --- | --- | --- | --- |
| 1 | 公共契约 + 全仓单元测试 | **PASS** | 契约 PASS；全仓 767 passed / 4 skipped（exit 0） |
| 2 | F0 P0 身份安全反例 | **PASS** | 38 passed |
| 3 | 三真实 External 调用与 Schema | **PASS** | 75 passed / 5 skipped（`test_joint_three_modules` 等） |
| 4 | M1 无效在线模型 -> UNKNOWN | **PASS** | `ADAPTER_MODULE_STATUS_NOT_PROCEED` |
| 5 | M2 无生产可信身份 -> 阻断 | **PASS** | `ADAPTER_MODULE_STATUS_NOT_PROCEED` |
| 6 | M3 规则引擎真实运行 | **PASS** | allow -> READY；block -> ADAPTER_BLOCK |
| 7 | F0 严格模式正确 ADAPTER_BLOCK | **PASS** | `ADAPTER_CURRENT_IDENTITY_UNBOUND` |
| 8 | 被阻断请求不进入 Planner | **PASS** | 4 个阻断用例，下游泄漏 0 |
| 9 | ROS 2 下游实机核查 | **NOT_RUN** | 未启动 Gateway/NavigationSim 栈 |
| 10 | M3 受控在线六场景 | **NOT_RUN** | 同上 |
| 11 | DDS Enforce 独立正反例 | **PASS** | 负例被原生拒绝；正例收到 1 条事件、0 安全错误 |
| 12 | M2 组件不改变 Gateway 决策 | **PASS** | 重复判定一致；F0 未导入任何 M2 脚本 |

### 3.1 失败关闭的具体证据（item 4/5/6/7/8）

| 用例 | 期望 | 实测 |
| --- | --- | --- |
| 受控基线（三模块正常） | READY | `READY_FOR_GATEWAY_SUBMISSION` / `ADAPTER_OK` |
| M1 UNKNOWN | 阻断 | `ADAPTER_BLOCK` / `ADAPTER_MODULE_STATUS_NOT_PROCEED` |
| M2 身份 UNKNOWN | 阻断 | `ADAPTER_BLOCK` / `ADAPTER_MODULE_STATUS_NOT_PROCEED` |
| M3 block | 阻断 | `ADAPTER_BLOCK` / `ADAPTER_MODULE_STATUS_NOT_PROCEED` |
| STRICT 无凭据 | 阻断 | `ADAPTER_BLOCK` / `ADAPTER_CURRENT_IDENTITY_UNBOUND` |
| 阻断后下游 | 0 泄漏 | 4 个阻断用例，`gateway_submission`/`submitted_to_gateway` 均为空 |

### 3.2 DDS Enforce（item 11）

| 方向 | 资源 | 结果 |
| --- | --- | --- |
| 负例 | `/rg/candidate_task`（不在 allow rule） | Fast DDS 原生拒绝：`topic not found in allow rule`，`create_datareader failed` |
| 正例 | `rt/m2/candidate_task`（在 allow rule） | Reader 创建成功，收到 1 条事件，0 条 SECURITY 错误 |

### 3.3 首轮全仓测试的 13 个失败（已定位并修复）

首次在本工作树跑全仓时 `test_identity_trust_real_logs.py` 有 13 个失败，
原因不是代码缺陷，而是**本地缺少 `security/keystore` fixture**
（该目录 gitignored，需本地存在）。补齐其允许位置后重跑：**56 passed**，
全仓变为 **767 passed / 4 skipped / exit 0**。
两次日志都保留在 `logs/unit_suite_first_run_failures.log` 与
`logs/unit_suite_second_run.log`，便于核对不是"跑过一次就算过"。

## 4. 未执行项（明确 NOT_RUN，不继承历史结论）

| # | 项 | 原因 |
| --- | --- | --- |
| 9 | ROS 2 下游实机（Gateway 审计、NavigationSim Goal） | 需启动完整 Gateway + NavigationSim 栈；本轮未启动 |
| 10 | M3 受控在线六场景 | 同上 |

这两项是"有条件通过"的直接原因。**不得**用前几轮（RC2/冻结演示）的结果替代本轮结论。

## 5. 不得据此宣称

- ❌ 三真实模块 LEVEL 3 通过
- ❌ M1 具备在线检测有效性（第三轮已证伪：`duration_ms` 泄漏，去特征后折 1 F1 0.32/0.57 低于基线 0.666）
- ❌ M2 可作为生产身份信任根（对称 HMAC、同 UID、无审批、Action 捕获未接线）
- ❌ DDS Enforce 已覆盖正式策略（本轮用独立研究 keystore 与 `rt/*` 命名空间）

## 6. 复现命令

```bash
# 契约 + 全仓
python3 scripts/validate_team_contracts.py --all
pytest tests/unit -q

# 受限验证用例
python3 scripts/int_limited_verification.py \
    --evidence artifacts/integration/three-real-limited/<run_id>

# M2 组件编译（容器内）
g++ -std=c++17 -O2 -I/opt/ros/jazzy/include -I/opt/ros/jazzy/include/fastrtps \
    -I/opt/ros/jazzy/include/fastcdr -DHAVE_SECURITY=1 \
    src/m2_witness/m2_ingress_witness.cpp -o /tmp/ingress \
    -L/opt/ros/jazzy/lib -lfastrtps -lfastcdr -lpthread

# GUID 安全回归
pytest tests/unit/test_m2_witness_guid_safety.py -q
```
