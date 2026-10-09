#!/usr/bin/env bash
# colcon build for the RoboGuard minimal base.
#
# 行为约定（任务 B3）：
#   * 构建前**检查系统状态**；若发现正在运行的受管理实例，明确报错并拒绝构建，
#     而不是去清理正在运行的节点。
#   * 不使用无差别 pkill ros2 / docker stop 等操作。
#   * colcon build 能力本身保持不变。
#
# Evidence: logs/build.log, plus the command / exit code / log path triple.
set -uo pipefail

RG_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${RG_SCRIPT_DIR}/lib.sh"

echo "---------------------------------------------------------------"
echo "[run] 构建前运行状态检查"

# 运行中实例保护：拒绝在系统运行时构建，避免打断用户正在使用的实例
if ! rg_require_no_running_instance; then
  echo "[refused] 构建被拒绝：系统正在运行（exit 4）"
  echo "          如需构建，请先停止运行中的实例。"
  echo "---------------------------------------------------------------"
  echo "BUILD RESULT: REFUSED (exit 4) -- 系统运行中，未执行 colcon build"
  exit 4
fi
echo "[  ok ] 未发现运行中的受管理实例，可以安全构建"
echo "---------------------------------------------------------------"

rg_evidenced \
  "colcon build" \
  "${RG_LOG_DIR}/build.log" \
  "colcon build --event-handlers console_direct+"
status=$?

echo
if [ "${status}" -eq 0 ]; then
  echo "BUILD RESULT: PASS"
  rg_ros 'colcon list'
else
  echo "BUILD RESULT: FAIL (exit ${status}) -- see ${RG_LOG_DIR}/build.log"
fi
exit "${status}"
