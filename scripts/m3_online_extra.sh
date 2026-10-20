#!/usr/bin/env bash
# m3_online_extra.sh -- ON-03 / ON-04 / ON-06 在线场景驱动器
#
# 为什么单独成脚本：这三个场景需要**不同的受信任配置**（ON-03 缺策略、
# ON-04 损坏策略）或**不同的 planner 超时**（ON-06），无法与 ON-01/02/05
# 共用同一份配置。
#
# 每个场景使用**唯一** request_id：复用同一 request_id 会让 Gateway 审计与
# NavigationSim journal 的条目互相混串，使跨层复核无法区分场景
# （scripts/verify_m3_online_evidence.py 的串单检查正是为发现这类问题而存在）。
set -uo pipefail
set -m

RUN_ID="$1"
OUT="$2"
WS=/ws
cd "$WS" || exit 1
set +u
# shellcheck disable=SC1091
source /opt/ros/jazzy/setup.bash
# shellcheck disable=SC1091
source install/setup.bash
set -u

# 第二组场景写入独立子目录（见 m3_online_drive.sh 的同名说明）。
OUT="$OUT/stack-b"
mkdir -p "$OUT"
AUDIT="$OUT/gateway_audit.jsonl"
JOURNAL="$OUT/navsim_goals.jsonl"
: > "$AUDIT"
: > "$JOURNAL"

PIDS=()
trap cleanup EXIT
trap 'on_signal INT' INT
trap 'on_signal TERM' TERM
cleanup() {
  # 幂等：重复调用不能报错，也不能杀死别人的进程。
  # 只作用于本脚本记录过的进程组。
  local p rc=0
  for p in "${PIDS[@]:-}"; do
    [ -n "$p" ] && { kill -TERM "-$p" 2>/dev/null || kill -TERM "$p" 2>/dev/null || true; }
  done
  sleep 2
  for p in "${PIDS[@]:-}"; do
    if [ -n "$p" ] && kill -0 "-$p" 2>/dev/null; then
      kill -KILL "-$p" 2>/dev/null || true
      rc=1
    fi
  done
  wait 2>/dev/null || true
  return ${rc}
}

check_stray() {
  # 只统计**仍存活且非僵尸**的进程组。
  # 为什么不用 `kill -0 -$p`：进程组在成员被回收前会短暂存在，
  # 且组内可能只剩僵尸（Z），直接判存活会产生误报。
  # 也不用 `pgrep -f pattern`：它会匹配到调用者自身的命令行。
  local n=0 p live
  for p in "${PIDS[@]:-}"; do
    [ -z "$p" ] && continue
    live=$(ps -o stat= -g "$p" 2>/dev/null | grep -vc '^Z' || true)
    if [ "${live:-0}" -gt 0 ]; then
      n=$((n + 1))
    fi
  done
  echo "STRAY_GROUPS=${n}"
  [ "${n}" -eq 0 ]
}

on_signal() {
  echo "收到 $1，执行清理"
  cleanup || true
  trap - EXIT
  exit 130
}
trap cleanup EXIT

ros2 run rg_demo_nodes navigation_sim --ros-args -p record_path:="$JOURNAL" \
  >"$OUT/navsim.log" 2>&1 &
PIDS+=($!)
ros2 run rg_gateway security_gateway --ros-args \
  -p policy_path:="$WS/config/task_policy.yaml" -p audit_log_path:="$AUDIT" \
  >"$OUT/gateway.log" 2>&1 &
PIDS+=($!)

for _ in $(seq 1 150); do
  if grep -q NAVSIM_READY "$OUT/navsim.log" 2>/dev/null &&
     grep -q GATEWAY_READY "$OUT/gateway.log" 2>/dev/null; then
    break
  fi
  sleep 0.2
done
echo "STACK_READY=1"

IN=/tmp/m3_online_inputs
mkdir -p "$IN"

python3 scripts/m3_online_prepare_inputs.py "$IN" "$RUN_ID" "$WS" || exit 4

run_one() {
  local cid="$1" cfg="$2" to="${3:-300}"
  echo
  echo "########## SCENARIO ${cid} ##########"
  timeout 300 python3 scripts/team_demo.py --input "$IN/$cid.json" \
    --config "$cfg" --online --planner-timeout "$to" \
    --log "$OUT/adapter_${cid}.jsonl" \
    >"$OUT/f0_${cid}.json" 2>"$OUT/f0_${cid}.err"
  echo "F0_EXIT_${cid}=$?"
  python3 scripts/m3_online_report_f0.py "$OUT" "$cid"
  echo "  journal 行数: $(wc -l < "$JOURNAL")"
}

# 权威清单：ON-03/04/06（在场景执行前写入）
python3 scripts/m3_online_write_manifest.py "$OUT" "$RUN_ID" "$(python3 -c "
import json, sys
r = sys.argv[1]
print(json.dumps([
  {'cid':'ON03','request_id':'on03-'+r,'run_id':r,'expected':'UNKNOWN_BLOCK'},
  {'cid':'ON04','request_id':'on04-'+r,'run_id':r,'expected':'ERROR_BLOCK'},
  {'cid':'ON06','request_id':'on06-'+r,'run_id':r,'expected':'TIMEOUT_NOT_BLOCK'},
], ensure_ascii=False))
" "$RUN_ID")"

run_one ON03 "$IN/ON03_config.yaml"
run_one ON04 "$IN/ON04_config.yaml"
run_one ON06 "$IN/ON06_config.yaml" 0.5

echo
echo "=== 关闭 ==="
cleanup
trap - EXIT
trap - INT
trap - TERM
sleep 1
if check_stray; then
  echo "audit 行数: $(wc -l < "$AUDIT")  journal 行数: $(wc -l < "$JOURNAL")"
  echo "DONE_EXTRA"
  exit 0
else
  echo "ERROR: 本轮仍有残留进程组；清理未完全成功" >&2
  echo "audit 行数: $(wc -l < "$AUDIT")  journal 行数: $(wc -l < "$JOURNAL")"
  exit 1
fi
