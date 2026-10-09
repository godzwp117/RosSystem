#!/usr/bin/env bash
# Full verification sweep: build -> unit tests -> A/B scenarios -> negative
# scenarios. Stops at the first failing stage and reports which one failed.
#
# Evidence: logs/*.log and tests/evidence/<run-id>/.
set -uo pipefail

RG_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${RG_SCRIPT_DIR}/lib.sh"

overall=0
declare -a names=() results=() logs=()

run_stage() {
  local name="$1"; shift
  local log="$1"; shift
  local status
  echo
  echo "############ STAGE: ${name} ############"
  if rg_evidenced "${name}" "${log}" "$*"; then
    status=0
  else
    status=$?
  fi
  names+=("${name}")
  logs+=("${log}")
  if [ "${status}" -eq 0 ]; then
    results+=("PASS")
  else
    results+=("FAIL (exit ${status})")
    overall=1
  fi
  return "${status}"
}

run_stage "colcon build"      "${RG_LOG_DIR}/build.log"              "colcon build --event-handlers console_direct+"
if [ "${overall}" -ne 0 ]; then
  echo
  echo "STOPPING: build failed; later stages would be meaningless."
else
  run_stage "unit tests"      "${RG_LOG_DIR}/unit_tests.log"         "python3 -m pytest tests/unit -v -p no:cacheprovider"
  run_stage "A/B scenarios"   "${RG_LOG_DIR}/scenarios_ab.log"       "python3 tests/integration/scenario_runner.py --suite ab"
  run_stage "negative cases"  "${RG_LOG_DIR}/scenarios_negative.log" "python3 tests/integration/scenario_runner.py --suite negative"
fi

echo
echo "==============================================================="
echo "VERIFICATION SUMMARY"
echo "==============================================================="
for index in "${!names[@]}"; do
  printf '  %-22s %-12s log: %s\n' "${names[$index]}" "${results[$index]}" "${logs[$index]}"
done
echo "==============================================================="
if [ "${overall}" -eq 0 ]; then
  echo "OVERALL: PASS"
else
  echo "OVERALL: FAIL"
fi
exit "${overall}"
