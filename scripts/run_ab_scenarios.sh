#!/usr/bin/env bash
# A/B integration scenarios (task requirement 11):
#   A_zone_allow              -> Gateway ALLOW, NavigationSim receives 1 Goal
#   B_zone_block_out_of_region-> Gateway BLOCK, NavigationSim receives 0 Goals
#
# Assertions are count/log based and live in tests/integration/scenario_runner.py;
# evidence is written under tests/evidence/<run-id>/.
set -uo pipefail

RG_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${RG_SCRIPT_DIR}/lib.sh"

rg_evidenced \
  "A/B scenarios" \
  "${RG_LOG_DIR}/scenarios_ab.log" \
  "python3 tests/integration/scenario_runner.py --suite ab"
status=$?

echo
if [ "${status}" -eq 0 ]; then
  echo "A/B SCENARIO RESULT: PASS"
else
  echo "A/B SCENARIO RESULT: FAIL (exit ${status}) -- see ${RG_LOG_DIR}/scenarios_ab.log"
fi
exit "${status}"
