# 占位文件：用于让「受信任配置指向不存在的策略文件」这一真实条件可复现。
#
# 通用验收器的 policy_absent 档案**故意**指向
#     config/scenarios/task_policy_absent.yaml
# 这个文件在仓库中**不存在**，因此真实规则模块读文件失败并失败关闭为
# UNKNOWN（FileNotFoundError -> POLICY_MISSING），而不是被默认为允许。
#
# 本 README 的存在是为了说明「文件故意缺失」，不会被模块读取。
# 不要创建 config/scenarios/task_policy_absent.yaml，否则 UNKNOWN 场景会失效。
