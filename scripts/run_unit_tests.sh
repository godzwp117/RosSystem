#!/usr/bin/env bash
# Unit tests for the ROS-free core (policy engine, loader, tracker, events,
# interface contract).
#
# Evidence: logs/unit_tests.log, plus the command / exit code / log path triple.
set -uo pipefail

RG_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${RG_SCRIPT_DIR}/lib.sh"

rg_evidenced \
  "unit tests (pytest)" \
  "${RG_LOG_DIR}/unit_tests.log" \
  "python3 -m pytest tests/unit -v -p no:cacheprovider"
status=$?

echo
if [ "${status}" -eq 0 ]; then
  echo "UNIT TEST RESULT: PASS"
else
  echo "UNIT TEST RESULT: FAIL (exit ${status}) -- see ${RG_LOG_DIR}/unit_tests.log"
fi
exit "${status}"
