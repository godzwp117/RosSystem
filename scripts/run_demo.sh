#!/usr/bin/env bash
# Human-readable live demo of the A/B paths, with assertions. Safe to run from
# the Ubuntu 22.04 host: it delegates into the ROS 2 Jazzy container.
#
# Evidence: logs/demo.log plus logs/demo/*.
set -uo pipefail

RG_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${RG_SCRIPT_DIR}/lib.sh"

# 注意：**不再**在此处做"按进程名清理遗留节点"。
# 原因（本轮安全审查确认）：
#   * 被调用的 rg_reap_stragglers() 内部是 `pkill -9 -f <节点名模式>`，
#     按**进程名**而非所有权匹配，无法区分"本实例的遗留节点"与
#     "同一容器内其他成员/其他运行实例正在使用的节点"；
#   * 它还有一个 RG_REAP_FORCE=1 开关可以绕过唯一的实例守卫；
#   * 本脚本调用的 demo_live.sh 已经用 PIDS+=($!) 记录自己启动的进程，
#     并通过 `trap cleanup EXIT` 只终止这些进程组（所有权明确）。
# 因此该清理既冗余又只可能伤害他人，已移除。
# 若确实需要清理遗留节点，请用 scripts/start_system.sh 的诊断输出人工确认归属，
# 或为运行实例引入显式的所有权登记机制。

rg_evidenced \
  "live demo (operator + A/B requests)" \
  "${RG_LOG_DIR}/demo.log" \
  "bash scripts/demo_live.sh"
status=$?

echo
if [ "${status}" -eq 0 ]; then
  echo "DEMO RESULT: PASS"
  echo "  audit JSONL    : ${RG_WS_HOST}/logs/demo/audit.jsonl"
  echo "  navsim journal : ${RG_WS_HOST}/logs/demo/navsim_goals.jsonl"
else
  echo "DEMO RESULT: FAIL (exit ${status}) -- see ${RG_LOG_DIR}/demo.log"
fi
exit "${status}"
