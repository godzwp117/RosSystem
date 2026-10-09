# SROS 2 最小权限策略（M2）

本目录存放 M2 的授权策略源文件。**只放策略，不放密钥**：密钥材料由
`scripts/setup_sros2.sh` 生成到 `security/keystore/`，该目录已被 `.gitignore` 排除。

## 文件

| 文件 | 说明 |
| --- | --- |
| `minimal_permissions.xml` | SROS 2 policy（version 0.2.0），五个 enclave 的最小权限定义 |

## 为什么策略文件里一行注释都没有

这是实测得到的硬约束，不是风格选择：

> sros2 0.13.6（ROS 2 Jazzy）的 `ros2 security generate_artifacts` **只要策略文件中存在
> 任何 XML 注释**，就会以
> `failed to validate namespace: error not set`
> 失败；**更危险的是它在此之前已经写好了各 enclave 的 `key.pem` 与 `permissions.xml`，
> 而内容来自内置默认策略 —— 即 `rt/*`、`rq/*Request`、`rr/*Reply`，整个 domain 全部放开。**

也就是说：只看"命令跑完了 / 文件生成了 / 进程起得来"会把**全开**误判成**最小权限**。
因此本项目做了两件事：

1. `scripts/setup_sros2.sh` 在生成前**拒绝**含注释的策略（快速失败），
   生成后调用 `scripts/verify_sros2_permissions.py` **独立复核**生成结果，
   出现宽松回退特征即判失败；
2. 全部说明文字放在本文件，策略 XML 保持零注释。

## Enclave 与最小权限

Enclave 才是身份边界：每个角色一个独立 enclave、独立证书与私钥，**不使用全局 enclave**。

| Enclave | 运行节点 | 业务资源授权 | 明确不含 |
| --- | --- | --- | --- |
| `/operator` | `operator_node` | 仅发布 `/rg/task_info` | 任何 Action 资源 |
| `/planner` | `planner_node` | `/rg/guarded_navigate/_action/*`（客户端方向） | **`/rg/nav_execute` 全部资源** |
| `/gateway` | `security_gateway` | `/rg/guarded_navigate`（服务端）+ `/rg/nav_execute`（客户端） | 其他业务资源 |
| `/navsim` | `navigation_sim` | `/rg/nav_execute/_action/*`（服务端） | 其他业务资源 |
| `/unauthorized` | （受控测试身份） | 无任何业务资源 | 全部业务 Action |

每个节点另外获得 `rosout`、`parameter_events` 发布权限与节点私有参数服务（`~/...`），
这是 rclpy 节点正常运行的公共最小集。

## 资源名是怎么来的（不是凭记忆写 Action 名）

先用 `ros2 security generate_policy` 对**真实 ROS 图**采集，得到 Jazzy 下 Action 的实际展开：

* services：`<action>/_action/{send_goal,cancel_goal,get_result}`
  —— 服务端 `reply="ALLOW"`，客户端 `request="ALLOW"`
* topics：`<action>/_action/{status,feedback}`
  —— 服务端 `publish="ALLOW"`，客户端 `subscribe="ALLOW"`

一个容易踩的坑：**节点自身私有参数服务（`~/describe_parameters` 等）必须放在 `reply` 一侧**
（该节点是这些服务的服务端）。若误放进 `request`，节点在创建参数服务时就会被 DDS 拒绝，
表现为 `rclpy` 抛 `RCLError: failed to create service`，节点根本起不来。

## 权限映射的方向（排障时最常看错的地方）

sros2 把 ROS 名称映射为 DDS 名称：`rt/`（topic）、`rq/`（service 请求）、`rr/`（service 应答）。

| 策略写法 | 含义 | 生成的 DDS 权限 |
| --- | --- | --- |
| `<topics publish="ALLOW">` | 该节点**发布**该 topic | publish `rt/<topic>` |
| `<topics subscribe="ALLOW">` | 该节点**订阅**该 topic | subscribe `rt/<topic>` |
| `<services reply="ALLOW">` | 该节点是**服务端** | subscribe `rq/<svc>Request` + publish `rr/<svc>Reply` |
| `<services request="ALLOW">` | 该节点是**客户端** | publish `rq/<svc>Request` + subscribe `rr/<svc>Reply` |

## 重新生成

```bash
scripts/setup_sros2.sh              # 安全 domain 默认 43（RG_SECURE_DOMAIN_ID 可覆盖）
```

安全模式使用 **domain 43**，与普通模式的 **42** 隔离，避免共用 ROS daemon 缓存或发现结果。
