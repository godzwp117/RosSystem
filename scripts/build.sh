#!/usr/bin/env bash
# colcon build for the RoboGuard minimal base.
#
# Evidence: logs/build.log, plus the command / exit code / log path triple.
set -uo pipefail

RG_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${RG_SCRIPT_DIR}/lib.sh"

rg_reap_stragglers

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
