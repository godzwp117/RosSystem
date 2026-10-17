# 工作 A 第二阶段：真实模块可信化、安全缺口修复与 B1 交接

| 项 | 值 |
| --- | --- |
| 本轮基准 SHA | `f51bab800d7bb3fe325d7e096bb15438178f5122`（第一阶段已推送） |
| 分支 | `integration/member-module-adaptation` |
| 工作树 | `/home/zhangwei/project/RosSystem/.worktrees/work-a`（复用，未重建） |
| 本轮新提交 | 见第 11 节（功能提交 + SHA 记录提交） |
| 总结论 | M2 信任边界已收紧并实测；M1 取得**真实** /proc 观测但**不具备**在线检测；M3 零改动、回归通过；F0 的身份自报缺口**仍存在**，已定位、已给反例、交由 B1 修 |

---

## 1. 本轮基准与范围

已重新核验（执行前）：

```text
git rev-parse HEAD                                   = f51bab8…（work-a）
git rev-parse origin/integration/member-module-adaptation = f51bab8…
demo-2026-10-19-rc2-verified^{commit}                = 33cb4f9…
主工作区 git status                                   = 干净
B1 分支 integration/three-real-online                 = 1808834（已 merge 本工作分支，尚未改 team_demo.py）
user/                                                = 未改动（609 文件，只读）
```

本轮**没有**重复第一阶段工作（成员源码迁移、M1 原有模型训练、M2 历史证据解释器重构、
M3 适配）。改动集中在：M2 核验器与信任边界、M1 真实采集与子集模型、安全反例与交接。

## 2. 已核实的安全风险

| 编号 | 风险 | 严重度 | 证据 | 状态 |
| --- | --- | --- | --- | --- |
| P0-1-A | **签名有效被当成身份已认证**：`remote_identity.authenticated` 只是签发者写的一个布尔值，核验器不区分签发者是谁 | 高 | 代码审查 + 改写前后对比 | **已修**（签发者信任独立判定） |
| P0-1-B | **防重放是可选项**：未配置账本仍返回 AUTHENTICATED；账本损坏会静默降级 | 高 | 证据 JSON 的 `no ledger configured` / `ledger path is a directory` 用例（修复前会 AUTHENTICATED） | **已修**（AUTHENTICATED 必须 RESERVED） |
| P0-1-C | **判重存在 TOCTOU**：`seen_nonce` 与 `append` 分离，并发实例可同时接受同一 nonce | 高 | 8 进程并发测试（修复前可重复接受） | **已修**（flock 临界区重读-判重-追加） |
| P0-1-D | **账本读取/追加非原子**、损坏后静默失去防护 | 中 | 同上 | **已修** |
| P0-1-E | **文件安全**：`getsize` 后 `open` 的 TOCTOU、符号链接、密钥可被 0644 读取 | 中 | 新增加固用例 | **已修**（`O_NOFOLLOW`+`fstat`+fd 读取+0600 强制） |
| P0-1-F | **证据未绑定请求内容**：只绑 `request_id`，同一 id 下不同目标点可复用同一证据 | 中 | `test_attestation_must_bind_the_exact_target` | **已修**（`request_digest` 含 task_id 与目标点） |
| P0-2 | **F0 信任裸状态字符串**：一个只写 `"status":"AUTHENTICATED"` 的模块即可让适配层给出 `READY_FOR_GATEWAY_SUBMISSION / ADAPTER_OK` | **高** | 证据 JSON `f0_identity_trust_gap`（真实执行） | **未修**（`scripts/team_demo.py` 归 B1；已给一行改法与 2 个 xfail 反例） |
| P0-3 | Mock/TEST_ONLY 与真实证据在 F0 眼里无差别 | 中 | `test_f0_rejects_mock_fixture_identity`（xfail） | 部分缓解（M2 侧标注 `MOCK_FIXTURE`/`AUTHENTICATED_TEST_ONLY`；F0 侧同上交 B1） |
| P1-A | M1 无实时特征采集 | 高 | 可行性矩阵 + 环境探针 | 部分完成（24 维真实可采；其余经验证不可得） |
| P1-B | M1 模型未过门槛 | 高 | 测试 F1 0.1312 / 0.0891 vs 基线 0.8132 | 未变（如实保留） |

## 3. 修改的源码

| 文件 | 类型 | 说明 |
| --- | --- | --- |
| `identity_trust/current_identity.py` | **重写** | contract v2：签发者信任、请求摘要绑定、五元组 checks、原子账本、fd 安全读取、`f0_accepts()` 谓词 |
| `identity_trust/assessor.py` | 修改 | 接入新核验器与 `--identity-issuers`；历史复用改用原子 `reserve_assessment`；账本故障不再静默 |
| `identity_trust/test_issuer.py` | **新增** | 受控测试签发器（TEST_ONLY）：拒绝 verified、强制 `test-only:` 前缀 |
| `modules/member1_comm/collector/proc_runtime.py` | **新增** | 真实 `/proc` 采集（24 维）、窗口毫秒自洽、缺失项如实标注 |
| `modules/member1_comm/collector/emit_observation.py` | **新增** | 采集 CLI；无 `request_count` 时明确 `mapping_blocked` |
| `modules/member1_comm/export_runtime_subset_samples.py` | **新增** | 按列投影既有审计采样（不重采样） |
| `modules/member1_comm/export_feasibility_matrix.py` | **新增** | 生成 49 行可采集性矩阵（含环境探针） |
| `modules/member1_comm/features_runtime_subset.json` | 新增 | 24 维子集特征清单 |
| `modules/member1_comm/model/comm_risk_model_runtime_subset.json` | 新增 | 24 维子集模型（1.4 MB，纯数值 JSON） |
| `modules/member1_comm/model/model_manifest_runtime_subset.json` | 新增 | 子集模型身份清单（SHA-256/门槛/对比） |
| `modules/member1_comm/model/train_report_runtime_subset.json` | 新增 | 子集训练/验证/测试报告 |
| `tests/unit/test_identity_current_binding.py` | **重写** | 26 项：信任边界、绑定、账本、并发、文件安全、assessor 集成 |
| `tests/unit/test_phase2_security_boundaries.py` | **新增** | 9 项通过 + 2 项 xfail（F0 缺口反例） |
| `tests/unit/test_member1_runtime_observation.py` | **新增** | 7 项：真实采集、失败关闭、子集模型、矩阵一致性 |
| `docs/integration/evidence/PHASE2_EVIDENCE.json` | 新增 | 真实运行证据包（M1 采集、M1 两种结果、M2 八用例矩阵、F0 缺口） |
| `docs/integration/{M1_RUNTIME_FEATURE_FEASIBILITY.md,M2_CURRENT_IDENTITY_TRUST_BOUNDARY.md}` | 新增 | 两份专题说明 |
| `docs/integration/m1_feature_feasibility.json` | 新增 | 49 行机器可读矩阵 |

未改动：`scripts/team_demo.py`（B1 主导）、`modules/member3_taskrisk/**`（零改动）、
`security/policies/minimal_permissions.xml`、`config/task_policy.yaml`、`user/**`。

## 4. M1 特征可采集性与真实采集证据

详见 `docs/integration/M1_RUNTIME_FEATURE_FEASIBILITY.md`。摘要：

| 分类 | 数量 | 证据 |
| --- | --- | --- |
| 真实可采（已实现） | 24 | `/proc/{net/dev,vmstat,meminfo,diskstats,net/tcp,net/tcp6}` 实测读数 |
| 本机缺失 | 1 | `pgalloc_dma` 不在本机 `/proc/vmstat` |
| 需 pcap+tshark 解剖 | 22 | 本机无 `tshark`（`tcpdump` 存在但不足以给出解剖语义） |
| 需 ROS 2 图内省 | 2 | 本机无 ROS 2（无 `/opt/ros`、无 `ros2`） |

真实采集证据（`REAL_RUNTIME`）：窗口 804 ms / 5 次采样，窗口内 `pgpgin +3348`、
`pgfault +7950`、`Disk_Read +6696`，`measurement_sha256` 可复核。

## 5. M1 模型有效性结果

| 模型 | 特征 | 阈值 | 测试 F1 | Recall | 恒预测攻击基线 F1 | 门槛 |
| --- | --- | --- | --- | --- | --- | --- |
| 原模型 | 49 | 0.75 | 0.1312 | 0.0702 | 0.8132 | **FAIL** |
| 运行时子集 | 24 | 0.90 | **0.0891** | 0.0466 | 0.8132 | **FAIL** |

子集模型在验证分片 F1=0.978、测试分片 F1=0.089 —— 再次证明"文件分片独立 ≠ 采集
会话独立"。没有任何一个模型达到门槛，`validation_gate_passed` 保持 `false`。

## 6. M2 证据签发来源是否真实可信

**否。** 生产环境不存在签发端；本仓库只交付：

* 证据契约（`contract_description()`）；
* 核验器（含签发者信任判定）；
* 受控测试签发器（TEST_ONLY，产物最多 `AUTHENTICATED_TEST_ONLY`）。

受信任签发者清单在仓库中**不存在**（测试断言 `config/` 下无 `*issuer*` 文件），
所以真实路径恒为 `UNKNOWN`。`ONLINE_PROCEED_READY` 保持 **FAIL**。

## 7. M2 核验器加固结果

八用例实测（`CONTROLLED_TEST` 签发者）：

```text
no witness                     -> UNKNOWN  (NOT_EVALUATED)        f0_accepts=False
signed, issuer not listed      -> UNKNOWN  (NOT_LISTED)           f0_accepts=False
signed, TEST_ONLY issuer       -> AUTHENTICATED_TEST_ONLY         f0_accepts=False
signed, VERIFIED issuer+ledger -> AUTHENTICATED                   f0_accepts=True
same witness replayed          -> UNKNOWN  (REPLAYED)             f0_accepts=False
no ledger configured           -> UNKNOWN  (LEDGER_UNAVAILABLE)   f0_accepts=False
ledger path is a directory     -> UNKNOWN  (LEDGER_ERROR)         f0_accepts=False
world-readable key             -> UNKNOWN  (权限过宽，拒绝读取)     f0_accepts=False
```

并发：8 个独立进程同时核验同一证据 → 恰好 1 个 `RESERVED`、7 个 `REPLAYED`。

## 8. F0 安全接口需要 B1 配合的修改

1. **必须改**：把身份位置的判定从"比较 `status` 字符串"换成调用
   `identity_trust.current_identity.f0_accepts(current)`。当前反例已实测可绕过
   （`READY_FOR_GATEWAY_SUBMISSION / ADAPTER_OK`）。
2. **建议改**：审计里同时记录 `checks` 五元组，使"这次 READY 靠什么成立"可复核。
3. **建议改**：拒绝 `evidence_kind == "MOCK_FIXTURE"` 的对象进入真实模式
   （Mock 演示可保留在 `mode: mock` 的配置里）。
4. **不需要改**：`REQUIRED_CURRENT_IDENTITY` 的存在本身是对的，问题只在判定方式。

对应 xfail 用例：
`tests/unit/test_phase2_security_boundaries.py::test_f0_rejects_bare_status_self_report`、
`::test_f0_rejects_mock_fixture_identity`。B1 修好后改成普通断言。

## 9. M3 回归结果

M3 **代码零改动**（`module.py`/`risk_model.py` 与第一阶段 SHA-256 一致）。
本轮仅做回归：

* `tests/unit/test_member3_taskrisk.py`、`test_member3_real_acceptance.py`：通过；
* `tests/unit/test_joint_three_modules.py`：5 项通过（三模块真实调用、event_id 关联、
  进程/资源隔离、交付配置）；
* `check_member_module --module task_risk`：`meets_pr_gate=True`，
  `NOT_RUN`(L2) / `BLOCKED`(L3) 标注不变。

## 10. 模块级测试结果

```text
tests/unit/test_identity_current_binding.py            27 passed
tests/unit/test_phase2_security_boundaries.py           9 passed, 2 xfailed
tests/unit/test_member1_runtime_observation.py          7 passed
tests/unit/test_member1_comm_real.py                   21 passed
tests/unit/test_member1_adapter_integration.py          6 passed
tests/unit/test_member1_real_acceptance.py              2 passed
tests/unit/test_identity_trust_assessor.py + real_logs  56 passed
tests/unit/test_joint_three_modules.py                  5 passed

全仓：734 passed, 3 skipped, 2 xfailed in 532.64s (0:08:52)
（其中 2 项 xfailed 是 P0-2 的已知缺口反例，不是失败）
```

`xfailed` 两项是**已知 F0 缺口**（P0-2）的可执行反例，不是失败：
它们断言"F0 应当阻断"，而当前 F0 会放行，故按预期失败。

### 附：任务要求的 12 项重点测试对照

| # | 要求 | 用例 | 结果 |
| --- | --- | --- | --- |
| 1 | 伪造 M2 当前身份 AUTHENTICATED | `test_phase2_security_boundaries.py::test_f0_rejects_bare_status_self_report`（xfail，实测 F0 放行）；`test_identity_current_binding.py::test_m2_output_always_carries_verification_metadata` | **缺口已复现**（B1 修） |
| 2 | 历史 AUTHORIZED 复用于全新请求 | `test_identity_current_binding.py::test_same_historical_evidence_for_a_brand_new_request_stays_unbound` | PASS |
| 3 | HMAC 有效但签发来源不可信 | `test_identity_current_binding.py::test_signature_without_trusted_issuer_is_not_authentication` | PASS |
| 4 | 凭据与请求/资源/操作不匹配 | `::test_attestation_must_bind_request_resource_operation`（3 参数）、`::test_attestation_must_bind_the_exact_target` | PASS |
| 5 | nonce 并发重放 | `::test_concurrent_same_nonce_is_accepted_at_most_once`（8 独立进程，恰好 1 个 RESERVED） | PASS |
| 6 | 账本损坏/不可写/路径被替换 | `::test_corrupt_ledger_never_authenticates`、`::test_unwritable_ledger_never_authenticates`、`::test_symlinked_ledger_is_refused` | PASS |
| 7 | 受控测试身份被正式模式误用 | `test_phase2_security_boundaries.py::test_test_only_issuer_is_never_accepted_by_f0`... （见下） | PASS / 缺口已复现 |
| 8 | M1 虚假 RUNTIME_LOG 来源 | `test_member1_comm_real.py::test_self_reported_runtime_kind_cannot_earn_normal`、`::test_normal_allowed_requires_all_three_conditions` | PASS |
| 9 | M1 缺少实时特征 | `test_member1_runtime_observation.py::test_49_feature_model_rejects_the_runtime_subset`、`::test_module_fails_closed_without_request_count` | PASS |
| 10 | M1 门槛失败但返回 NORMAL | `::test_runtime_subset_model_consumes_real_features`（断言永不 NORMAL）、`test_member1_comm_real.py::test_controlled_test_flag_is_the_only_way_to_normal` | PASS |
| 11 | 三真实模块 Schema 正确但推进条件不足 | `test_joint_three_modules.py::test_f0_invokes_all_three_then_blocks_on_status` | PASS |
| 12 | M3 与原有安全约束不退化 | `test_member3_taskrisk.py`、`test_member3_real_acceptance.py`、`test_joint_three_modules.py` | PASS |

第 7 项的两侧结果要分开看：
* **M2 侧已守住**：`test_identity_current_binding.py::test_test_only_issuer_is_never_accepted_by_f0`
  证明 TEST_ONLY 签发者只能得到 `AUTHENTICATED_TEST_ONLY`，`f0_accepts()` 为 False；
  配置侧由 `test_phase2_security_boundaries.py::test_controlled_test_flag_only_in_marked_places`
  与 `::test_joint_real_config_uses_no_mock_modules` 约束。
* **F0 侧仍是缺口**：`::test_f0_rejects_mock_fixture_identity`（xfail）证明只要把 Mock
  配进真实模式，F0 会放行 `MOCK_FIXTURE`。这一条归 P0-2，责任人 B1。

## 11. 新提交 SHA

```text
c6f6755e3c5b21febf23d3f8a0f5ce57e5957715
```

（SHA 记录本身在随后一条仅改本文件的提交里。）

## 12. 尚未解决的阻断项

| 编号 | 阻断 | 影响 | 解除条件 |
| --- | --- | --- | --- |
| A-1 | 无 ROS 2 运行时（本机） | 无法做实时观测/在线联调 | 在 Jazzy 容器内运行（B1 的环境） |
| A-2 | 无业务请求计数 | M1 无法形成完整映射（退出码 4） | ROS 2 Action 计数接入 |
| A-3 | 22 维逐包特征 + 2 维图特征不可得 | 49 维模型无法在线使用 | 部署 tshark 或改采集方案 + ROS 图内省 |
| A-4 | 两个模型都未过门槛 | 生产语义下不给 NORMAL | 重新设计特征/算法并在独立会话复现 |
| A-5 | 证据语义等价性 UNVERIFIED | 不能声称"同一特征" | 需要数据集作者的采样口径或对照实验 |
| A-6 | 无真实身份签发者 | 当前身份恒 UNKNOWN | 中间件层身份绑定或受审计的见证服务 |
| A-7 | F0 信任裸状态字符串 | 身份自报可绕过（P0-2） | B1 改用 `f0_accepts()` |
| A-8 | 密钥与核验器同 uid | 同机同用户可读密钥 | OS 级隔离/容器/TPM |

## 13. 逐模块结论（四项状态）

| 模块 | CALLABLE_REAL | SCHEMA_VALID | EVIDENCE_VALID | ONLINE_PROCEED_READY |
| --- | --- | --- | --- | --- |
| M1 `comm_risk` | PASS | PASS | PASS（限"真实 /proc 子集 + 离线模型"范围内） | **FAIL** |
| M2 `identity_trust` | PASS | PASS | PASS（限"历史证据 + 签名核验"范围内） | **FAIL** |
| M3 `task_risk` | PASS | PASS | PASS | PASS |

## 14. 最终问答

1. **M1 是否已获得真正的 ROS 2 当前通信观测？**
   **否。** 本环境没有 ROS 2。已获得的是**真实 Linux `/proc` 观测**（24 维，窗口级、
   主机级），不是 ROS 2 通信观测。
2. **现有 M1 模型是否适用于这些观测？**
   49 维模型**不适用**（22 维逐包 + 2 维图特征不可得，1 维本机缺失）。为此另训了
   24 维子集模型；两者都未通过门槛。
3. **M1 模型性能是否已满足准入门槛？**
   **否。** 49 维 F1 0.1312；24 维 F1 0.0891；恒预测攻击基线 0.8132。
4. **M2 HMAC 核验的信任边界是什么？**
   签名只证明"持有密钥者的字节完整性"；身份可信**只能**来自受信任签发者清单，
   而仓库不交付任何清单、也没有能签发它的组件。因此真实路径恒 UNKNOWN。
5. **M2 是否真正获得当前请求已认证 DDS 身份的可信证明？**
   **否。** 且已证明现有 API 无法提供，未虚构。
6. **F0 的身份自报绕过风险是否已排除？**
   **否。** 已实测复现（`ADAPTER_OK`），已给一行改法与 2 个可执行反例，责任人 B1。
7. **受控测试输入是否能够误入正式系统？**
   配置层面已加断言约束（`--controlled-test` 只出现在受控配置/受控档案；
   三真实配置无 mock 入口；M2 的 TEST_ONLY 产物状态是
   `AUTHENTICATED_TEST_ONLY`，F0 的 `AUTHENTICATED` 匹配不上）。
   **但** F0 仍不区分 `MOCK_FIXTURE`，所以只要有人把 Mock 配进真实模式，
   仍会被放行——这一条仍归 P0-2/A-7。
8. **M3 已验证能力是否保持？**
   **是。** 零改动，回归全通过。
9. **B1 可以直接合入哪些提交？**
   见第 11 节的功能提交（已推送分支）；合并前请先确认 A-7 的改法是否同期落地。
10. **三模块严格真实在线推进还有哪些阻断？**
    A-1（无 ROS 2 运行时）、A-2（无请求计数）、A-3（24 维不可得）、A-4（模型门槛）、
    A-6（无身份签发者）、A-7（F0 自报绕过）。
