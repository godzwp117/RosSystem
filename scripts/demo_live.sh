#!/usr/bin/env bash
# Live demo of the minimal closed loop. MUST be executed inside a sourced ROS 2
# Jazzy environment (scripts/run_demo.sh arranges that).
#
# Shows, in one run:
#   * /rg/task_info actually being published by operator_node
#   * A-zone request -> Gateway ALLOW -> NavigationSim receives exactly 1 Goal
#   * B-zone request -> Gateway BLOCK -> NavigationSim receives 0 further Goals
#   * the audit trail (RosCommEvent / DecisionEvent / ExecutionEvent) and the
#     correlatable REJECTED log line
#
# Exit code 0 only when every count/log assertion holds.
set -uo pipefail
set -m   # job control ON: each background job gets its own process group, so
         # "kill -INT -$PID" reaches both the `ros2 run` wrapper and the node.

WS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$WS" || exit 3

DEMO_DIR="${WS}/logs/demo"
rm -rf "$DEMO_DIR"
mkdir -p "$DEMO_DIR"

POLICY="${WS}/config/task_policy.yaml"
AUDIT="${DEMO_DIR}/audit.jsonl"
JOURNAL="${DEMO_DIR}/navsim_goals.jsonl"
A_REQUEST_ID="demo-a-0001"
B_REQUEST_ID="demo-b-0002"

PIDS=()
cleanup() {
  local pid
  for pid in ${PIDS[@]+"${PIDS[@]}"}; do kill -INT "-${pid}" 2>/dev/null || true; done
  sleep 2
  for pid in ${PIDS[@]+"${PIDS[@]}"}; do kill -TERM "-${pid}" 2>/dev/null || true; done
  sleep 1
  for pid in ${PIDS[@]+"${PIDS[@]}"}; do kill -9 "-${pid}" 2>/dev/null || true; done
  wait 2>/dev/null || true
}
trap cleanup EXIT

wait_for_marker() {
  local file="$1" marker="$2" timeout="${3:-30}"
  local iterations=$(( timeout * 5 )) index
  for (( index=0; index<iterations; index++ )); do
    if grep -q -- "$marker" "$file" 2>/dev/null; then return 0; fi
    sleep 0.2
  done
  return 1
}

echo "###############################################################"
echo "# RoboGuard minimal base -- live demo"
echo "#   ROS_DISTRO=${ROS_DISTRO:-<unset>}  RMW=${RMW_IMPLEMENTATION:-<unset>}"
echo "#   workspace=${WS}"
echo "#   policy   =${POLICY}"
echo "###############################################################"

echo
echo "== 1. bring-up =="
ros2 run rg_demo_nodes operator_node --ros-args -p task_id:=patrol_a_001 \
  >"${DEMO_DIR}/operator.log" 2>&1 &
PIDS+=($!)
ros2 run rg_demo_nodes navigation_sim --ros-args -p record_path:="${JOURNAL}" \
  >"${DEMO_DIR}/navsim.log" 2>&1 &
PIDS+=($!)
ros2 run rg_gateway security_gateway --ros-args \
  -p policy_path:="${POLICY}" -p audit_log_path:="${AUDIT}" \
  >"${DEMO_DIR}/gateway.log" 2>&1 &
PIDS+=($!)

READY=1
wait_for_marker "${DEMO_DIR}/operator.log" "OPERATOR_READY" 30 || { echo "  FAIL: operator not ready"; READY=0; }
wait_for_marker "${DEMO_DIR}/navsim.log" "NAVSIM_READY" 30 || { echo "  FAIL: navigation_sim not ready"; READY=0; }
wait_for_marker "${DEMO_DIR}/gateway.log" "GATEWAY_READY" 30 || { echo "  FAIL: security_gateway not ready"; READY=0; }
[ "${READY}" -eq 1 ] && echo "  OK: operator_node, navigation_sim, security_gateway up"

echo
echo "== 2. ros2 action list =="
timeout 20 ros2 action list -t || true

echo
echo "== 3. /rg/task_info sample (operator_node -> planner, advisory only) =="
TASK_INFO_SAMPLE="${DEMO_DIR}/task_info_sample.txt"
if timeout 45 ros2 topic echo /rg/task_info --once \
     >"${TASK_INFO_SAMPLE}" 2>"${DEMO_DIR}/task_info_echo.err"; then
  cat "${TASK_INFO_SAMPLE}"
  echo "  OK: /rg/task_info is live (std_msgs/msg/String, advisory payload)"
else
  echo "  WARN: no /rg/task_info sample within 45 s (see ${DEMO_DIR}/task_info_echo.err)"
  sed -n '1,5p' "${DEMO_DIR}/task_info_echo.err" 2>/dev/null || true
  echo "  NOTE: this does not affect admission control -- the Gateway never subscribes to"
  echo "        /rg/task_info; it always loads config/task_policy.yaml directly."
fi

echo
echo "== 4. A zone: task_id=patrol_a_001 frame=map target=(1.5, 1.5) -- expect ALLOW =="
timeout 60 ros2 run rg_demo_nodes planner_node --ros-args \
  -p task_id:=patrol_a_001 -p request_id:="${A_REQUEST_ID}" -p frame_id:=map \
  -p target_x:=1.5 -p target_y:=1.5 -p expect_success:=1 \
  2>&1 | tee "${DEMO_DIR}/planner_a.log"
A_EXIT=${PIPESTATUS[0]}
echo "  planner exit code (A) = ${A_EXIT}"

echo
echo "== 5. B zone: target=(9.0, 9.0) is outside allowed_region -- expect BLOCK =="
timeout 60 ros2 run rg_demo_nodes planner_node --ros-args \
  -p task_id:=patrol_a_001 -p request_id:="${B_REQUEST_ID}" -p frame_id:=map \
  -p target_x:=9.0 -p target_y:=9.0 -p expect_success:=0 \
  2>&1 | tee "${DEMO_DIR}/planner_b.log"
B_EXIT=${PIPESTATUS[0]}
echo "  planner exit code (B) = ${B_EXIT}"

sleep 1

echo
echo "== 6. audit trail =="
cat "${AUDIT}" 2>/dev/null || echo "  (no audit records)"

echo
echo "== 7. assertions (count / log based) =="
python3 - "${JOURNAL}" "${AUDIT}" "${DEMO_DIR}/gateway.log" \
          "${A_REQUEST_ID}" "${B_REQUEST_ID}" <<'PY'
import json
import sys

journal_path, audit_path, gateway_log, a_id, b_id = sys.argv[1:6]


def read_jsonl(path):
    records = []
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            for line in handle:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
    except FileNotFoundError:
        pass
    return records


journal = read_jsonl(journal_path)
audit = read_jsonl(audit_path)
with open(gateway_log, 'r', encoding='utf-8', errors='replace') as handle:
    gateway_text = handle.read()

decisions = [r for r in audit if r.get('event_type') == 'DecisionEvent']
executions = [r for r in audit if r.get('event_type') == 'ExecutionEvent']
rejects = [line for line in gateway_text.splitlines() if 'REJECTED ' in line]

checks = []


def check(name, condition, detail):
    checks.append((name, bool(condition), detail))


check('NavigationSim received exactly 1 Goal (A only)',
      len(journal) == 1, 'journal lines={0}'.format(len(journal)))
check('the received Goal is the A-zone request_id',
      [r.get('request_id') for r in journal] == [a_id],
      'request_ids={0}'.format([r.get('request_id') for r in journal]))
check('B-zone request_id never reached the executor',
      b_id not in {r.get('request_id') for r in journal},
      'B request_id={0}'.format(b_id))
check('DecisionEvent sequence is ALLOW then BLOCK',
      [(r.get('decision'), r.get('reason_code')) for r in decisions]
      == [('ALLOW', 'ALLOW_IN_POLICY'), ('BLOCK', 'OUT_OF_REGION')],
      '{0}'.format([(r.get('decision'), r.get('reason_code')) for r in decisions]))
check('exactly 1 ExecutionEvent (only the forwarded A request)',
      len(executions) == 1 and executions[0].get('status_code') == 'EXECUTED',
      'executions={0}'.format([r.get('status_code') for r in executions]))
check('BLOCK produced no ExecutionEvent for the B event_id',
      not ({r.get('event_id') for r in decisions if r.get('decision') == 'BLOCK'}
           & {r.get('event_id') for r in executions}),
      'no shared event_id')
check('exactly 1 correlatable REJECTED log line',
      len(rejects) == 1 and b_id in rejects[0],
      'reject lines={0}'.format(len(rejects)))
check('policy_version is recorded on every decision',
      all(r.get('policy_version') for r in decisions),
      '{0}'.format([r.get('policy_version') for r in decisions]))

failed = 0
for name, passed, detail in checks:
    print('  [{0}] {1} -- {2}'.format('PASS' if passed else 'FAIL', name, detail))
    if not passed:
        failed += 1

print()
print('DEMO RESULT: {0}  ({1} passed, {2} failed)'.format(
    'PASS' if failed == 0 else 'FAIL', len(checks) - failed, failed))
sys.exit(0 if failed == 0 else 1)
PY
ASSERT_EXIT=$?

echo
echo "evidence:"
echo "  audit JSONL     : ${AUDIT}"
echo "  navsim journal  : ${JOURNAL}"
echo "  gateway log     : ${DEMO_DIR}/gateway.log"
echo "  navsim log      : ${DEMO_DIR}/navsim.log"
echo "  operator log    : ${DEMO_DIR}/operator.log"
echo "  planner logs    : ${DEMO_DIR}/planner_a.log, ${DEMO_DIR}/planner_b.log"
echo "  planner exits   : A=${A_EXIT} B=${B_EXIT}"

if [ "${A_EXIT}" -ne 0 ] || [ "${B_EXIT}" -ne 0 ] || [ "${ASSERT_EXIT}" -ne 0 ]; then
  echo "LIVE DEMO RESULT: FAIL"
  exit 1
fi
echo "LIVE DEMO RESULT: PASS"
exit 0
