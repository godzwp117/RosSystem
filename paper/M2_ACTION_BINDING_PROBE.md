# M2 Action `send_goal` 请求级身份：接口探测与阻断结论

> 轮次：六小时强化（2026-10-22）
> 结论：**NOT_VERIFIED / BLOCKED**；意图主题绑定不得改名为 Action 绑定。
> 证据：`artifacts/research/v110/m2-action-probe/`

## 1. 目标

把已有链路

```text
DDS writer GUID -> 证书主体 -> request_digest -> Ed25519 -> F0/Gateway
```

从预准入意图主题 `rt/m2/candidate_task` 推进到真实 Action 服务请求
`rq/rg/guarded_navigate/_action/send_goalRequest`。

## 2. 本轮实际完成的接口探测

1. 确认生成代码中存在 Action 请求类型的 Fast DDS typesupport 符号：

   ```text
   ROSIDL_TYPESUPPORT_INTERFACE__MESSAGE_SYMBOL_NAME(
     rosidl_typesupport_fastrtps_cpp, rg_interfaces, action,
     PatrolNavigate_SendGoal_Request)()
   ```

   实测：`namespace=rg_interfaces::action`，`name=PatrolNavigate_SendGoal_Request`，
   `sizeof(PatrolNavigate_SendGoal_Request)=176`。

2. 用生成的序列化/反序列化回调构造了一个原始 Fast DDS `TopicDataType`，
   并成功创建了 `rq/rg/guarded_navigate/_action/send_goalRequest` 的 DataReader；
   witness 日志出现 `{"event":"action_reader_ready",...}`。

3. 失败结果（两次独立顺序尝试）：

| 条件 | Planner 结果 |
| --- | --- |
| witness + `--action-capture` | **`NO_ACTION_SERVER`**（20 s 内未发现 Action Server） |
| 同一 witness、同一栈、去掉 `--action-capture` | **`RESULT` / `EXECUTED`**（正向对照） |

即：**手工构造的 `TopicDataType` 一旦加入同一 DDS domain，Action 服务发现被破坏。**
不是“服务没启动”：同样栈、同样证书、去掉该 reader 就成功。

## 3. 原因判断（已确认的事实 + 尚未确认的部分）

已确认：

- typesupport 符号和回调存在，结构体大小可得；
- 原始 reader 能创建，但会扰动 Action 服务匹配；
- 不能通过“看到请求到达”来证明身份，因为请求根本没有到达 Gateway。

高度可能（未通过 rmw 源码实验确认）：

- `rmw_fastrtps_cpp` 的 service request 使用 `RequestTypeSupport` + TypeObject；
- 本原型的 `TopicDataType` 没有注册匹配的 TypeObject / 完全一致的 plain/bounds 属性，
  导致同一 topic 上出现类型不一致，服务端 endpoint 被判为不兼容。

## 4. 结论与边界

- **`M2_ACTION_SEND_GOAL_BINDING = NOT_VERIFIED`**；
- 现有 `M2_IDENTITY_LAB=17/17` 仍只证明**意图主题**绑定；
- 不得在论文中写“Action send_goal 请求级身份已实现”；
- 本轮的负结果本身是可引用的工程发现：**原始 DDS 订阅不能随意替换 rmw 的
  service typesupport**，否则会破坏服务发现。

## 5. 下一步（未执行）

1. 使用 `rmw_fastrtps_cpp::RequestTypeSupport` 的**精确类型对象**，或给自定义
   `TopicDataType` 注册与 rmw 完全一致的 TypeObject/属性；
2. 或采用 Jazzy 可用的 service introspection 路径（若其能同时给出请求内容与
   client GID；仅 `ServiceEventInfo` 只有 `client_gid/sequence`，不足以绑定内容）；
3. 只有在“正/负向对照 + 内容篡改阻断 + 合法身份成功”全部成立后，才允许把
   Action 绑定标为 PASS。

## 6. 复现

```bash
# 编译（容器内）
bash scripts/build_m2_ingress.sh /tmp/m2_ingress_action
# 需要研究 keystore 与已构建工作空间
python3 tests/integration/m2_action_capture_probe2.py  # 带 --action-capture
python3 tests/integration/m2_action_capture_control.py # 对照，不带
```

两次运行在 `tests/evidence/m2-action-probe2/` 与
`tests/evidence/m2-action-probe-control/`；摘要与 typesupport 探针在
`artifacts/research/v110/m2-action-probe/`。
