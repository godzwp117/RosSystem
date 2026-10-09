#!/usr/bin/env bash
# Negative / fail-closed scenarios (task requirement 12):
#   missing policy file, malformed policy, non-finite policy region, inactive
#   policy, task_id mismatch (request side and policy side), invalid frame_id,
#   NaN target, infinite target, duplicate request_id, rate limit, execution timeout.
#
# Every scenario must end in a rejection (or, for the duplicate/rate/timeout
# cases, in the documented downstream count with zero leaked Goals).
set -uo pipefail

RG_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${RG_SCRIPT_DIR}/lib.sh"

rg_evidenced \
  "negative scenarios" \
  "${RG_LOG_DIR}/scenarios_negative.log" \
  "python3 tests/integration/scenario_runner.py --suite negative"
status=$?

echo
if [ "${status}" -eq 0 ]; then
  echo "NEGATIVE SCENARIO RESULT: PASS"
else
  echo "NEGATIVE SCENARIO RESULT: FAIL (exit ${status}) -- see ${RG_LOG_DIR}/scenarios_negative.log"
fi
exit "${status}"
