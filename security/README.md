# security/ — SROS 2 安全配置

本目录承载 M2 引入的 DDS-Security（SROS 2）配置。**这里只放策略与说明，不放密钥**：
密钥材料由脚本生成到 `security/keystore/`，该目录已被 `.gitignore` 排除，禁止入库或上传。

## 目录

```text
security/
├── README.md                       本文件
├── policies/
│   ├── README.md                   策略设计与 sros2 工具链注意事项
│   └── minimal_permissions.xml     SROS 2 最小权限策略源文件（纳入版本控制）
└── keystore/                       运行时密钥库（.gitignore 排除，不得入库）
    ├── public/                     CA 证书
    ├── private/                    CA 私钥
    └── enclaves/                   每个角色的证书、私钥、permissions.xml、governance
```

## 状态：M2 已启用并实测生效

| 项目 | 状态 |
| --- | --- |
| 安全身份（Enclave） | 4 个业务角色各 1 个独立身份 + 1 个受控"无授权"测试身份 |
| 最小权限 | 已按真实 ROS 图生成并**独立复核**（`scripts/verify_sros2_permissions.py`） |
| 强制模式 | `ROS_SECURITY_ENABLE=true` + `ROS_SECURITY_STRATEGY=Enforce`，逐进程指定 enclave |
| 授权链 | Enforce 下 Planner → Gateway → NavigationSim 正常完成（场景 S2） |
| 越权直连 | Planner 身份直连 `/rg/nav_execute` 被 DDS 访问控制拒绝（场景 S3） |
| 无授权身份 | 无法完成执行调用（场景 S4） |
| 配置失效 | 不静默回退为无认证通信（场景 S6） |

> 结论的适用范围：以上均为**本机单容器、`rmw_fastrtps_cpp`、domain 43** 的实测结果
> （见 `tests/evidence/<run>/summary.json` 与 `artifacts/acceptance/exports/m2_sros2_enforce/`）。
> 跨主机、跨 RMW、跨 DDS 实现的等价性**未验证**。

## 运行方式

```bash
scripts/setup_sros2.sh                     # 生成/更新 keystore 与 enclave（幂等，含权限复核）
docker exec rg_jazzy bash -lc 'cd /ws && source /opt/ros/jazzy/setup.bash && \
    source install/setup.bash && python3 tests/integration/sros2_check.py'
```

普通模式不受影响，仍是容器默认 domain 42，由 `scripts/start_system.sh` 启动。

## 每个角色需要设置的环境变量

安全模式不是"设一个全局开关"，而是**逐进程**指定身份：

```text
ROS_SECURITY_ENABLE=true
ROS_SECURITY_STRATEGY=Enforce
ROS_SECURITY_KEYSTORE=/ws/security/keystore
ROS_SECURITY_ENCLAVE_OVERRIDE=/<role>      # operator | planner | gateway | navsim
ROS_DOMAIN_ID=43                           # 与普通模式 42 隔离
```

**禁止所有角色共用一个全局 enclave**：那样等于所有节点共享同一套权限，
隔离粒度会退化为"全有或全无"。

## 已知限制与风险（如实记录）

1. **sros2 工具链会静默回退**：`ros2 security generate_artifacts` 在策略非法（例如含 XML
   注释）时会先写出**默认全开**的 `permissions.xml` 再报错。只检查命令返回值或文件是否
   存在会把"全开"误当"最小权限"。本项目用 `scripts/verify_sros2_permissions.py` 独立复核
   来堵这个口子（详见 `policies/README.md`）。
2. **私钥以明文落盘**：`security/keystore/private/*.key.pem` 是未加密的 PEM，
   权限已收紧到 `700`/`go-rwx`，但任何能读该目录的进程都能冒充对应身份。
   生产环境应配合文件系统加密或硬件密钥存储。
3. **未启用证书吊销/轮换**：CA 与身份证书有效期 10 年，无 CRL 流程。
4. **未做跨主机/跨 RMW 验证**：结论仅覆盖本机单容器 + Fast DDS。
5. **未覆盖 ros2 CLI 的运维通道**：安全模式下未为 `ros2 topic/action` 等 CLI 分配身份，
   因此运维观测依赖文件证据（JSONL 日志）而非图查询。
6. **本目录的 README 与策略纳入版本控制，keystore 不纳入**：这是刻意的，
   `.gitignore` 中有对应规则并由单元测试
   （`test_no_key_material_is_committed`）持续校验。
