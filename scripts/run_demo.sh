#!/usr/bin/env bash
# Human-readable live demo of the A/B paths, with assertions. Safe to run from
# the Ubuntu 22.04 host: it delegates into the ROS 2 Jazzy container.
#
# Evidence: logs/demo.log plus logs/demo/*.
set -uo pipefail

RG_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${RG_SCRIPT_DIR}/lib.sh"

rg_reap_stragglers

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
