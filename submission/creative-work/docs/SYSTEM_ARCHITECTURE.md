# 系统架构

```text
     M1 通信风险 ──┐
     M2 身份可信 ──┼──> F0 可信证据核验（STRICT）
     M3 任务风险 ──┘            │
                                 │ READY / BLOCK
                                 v
                              Planner
                                 │ /rg/guarded_navigate
                                 v
                        SecurityGateway · TaskPolicy（权威）
                                 │ ALLOW / BLOCK
                                 │ ALLOW only
                                 v
                           NavigationSim（recorded_only）

DDS-Security：独立于 F0 的通信身份与资源权限控制（域绑定）
```

## 证据流

1. 三模块各自输出结构化证据，经 Schema 校验；
2. F0 核验证据齐备性与关联字段（run_id / request_id），不信任模块自报；
3. F0 `READY` 才提交 Planner；
4. Gateway 依 **TaskPolicy 独立判定**，与模块建议无关；
5. 仅 ALLOW 才下发 `/rg/nav_execute`；
6. NavigationSim 记录 Goal（`recorded_only`）；
7. 全过程写入 Gateway audit 与 NavSim journal，控制台**只读**展示。

## 控制台定位

控制台**不参与任何安全判断**：
- 不重写 F0、Gateway、DDS 逻辑；
- 只调用既有入口 `scripts/final_system.sh`；
- 只读取真实证据文件；
- 运行接口使用固定白名单，不接受任意命令。
