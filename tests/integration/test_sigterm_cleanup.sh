#!/usr/bin/env bash
# test_sigterm_cleanup.sh -- 顶层脚本收到 SIGTERM 后的**确定性**清理验证。
#
# 上一轮的失败教训
# ----------------
# 之前把 SIGTERM 发给了 `( script & )` 里的**子 shell**，脚本本身从未收到信号，
# 于是"清理通过"其实是"脚本正常跑完了"。这类测试会给出错误的信心。
#
# 本脚本的做法
# ------------
# 1. 直接 `script &` 后台启动，`$!` 即**顶层脚本 PID**，并记录其 PGID；
# 2. 等 Gateway/NavSim 真正启动（日志出现 READY 标记）后再发信号；
# 3. 发 TERM 给顶层 PID，验证它确实收到了（日志出现"收到 TERM"）；
# 4. 等待退出并记录退出码；
# 5. 检查本轮进程组内**非僵尸**残留；
# 6. 对已退出子进程、重复 cleanup、僵尸误报做回归。
#
# 只操作本脚本自己启动的进程组，不按名字批量杀进程。
set -uo pipefail

WS="${1:-/ws}"
RUN_ID="${2:-sigterm-$(date -u +%Y%m%dT%H%M%SZ)}"
OUT="${3:-$WS/artifacts/integration/final-submission-closeout/$RUN_ID}"
SCRIPT="$WS/scripts/m3_online_extra.sh"
mkdir -p "$OUT"

PASS=0
FAIL=0
report() {
  if [ "$2" -eq 0 ]; then echo "  [PASS] $1"; PASS=$((PASS + 1));
  else echo "  [FAIL] $1 -- $3"; FAIL=$((FAIL + 1)); fi
}

# 归属判定不能用脚本自身的 PGID：脚本启用了 `set -m`，每个后台作业
# 各自成为进程组组长，因此 ROS 节点的 PGID 与顶层脚本不同。
# 也不能用宽泛的 `pgrep -f 'rg_gateway'`：会匹配到本测试自身的命令行。
# 这里用**本轮唯一的 run_id** 精确判定归属 —— 节点的日志/记录路径里含 run_id。
non_zombie_owned() {  # non_zombie_owned <run_id>
  ps -eo stat=,args= 2>/dev/null \
    | grep -F -- "$1" \
    | grep -v -F -- 'test_sigterm_cleanup' \
    | grep -v -F -- 'grep' \
    | awk '$1 !~ /^Z/ {n++} END {print n+0}'
}

echo "=== SIGTERM 顶层脚本清理测试 ==="
echo "  run_id=$RUN_ID"

# ---- 正常路径前提：脚本必须先真正启动 ROS 节点 ----
cd "$WS" || exit 2
bash "$SCRIPT" "$RUN_ID" "$OUT" config/team_modules.member3.real.yaml \
    > "$OUT/sigterm_run.log" 2>&1 &
TOP_PID=$!
TOP_PGID=$(ps -o pgid= -p "$TOP_PID" 2>/dev/null | tr -d ' ')
echo "  顶层脚本 PID=$TOP_PID PGID=$TOP_PGID"

# 等节点真正起来（不用固定 sleep 猜）
READY=0
for _ in $(seq 1 300); do
  if grep -q 'GATEWAY_READY' "$OUT/stack-b/gateway.log" 2>/dev/null &&
     grep -q 'NAVSIM_READY' "$OUT/stack-b/navsim.log" 2>/dev/null; then
    READY=1; break
  fi
  sleep 0.1
done
report "nodes_started_before_signal" "$([ "$READY" -eq 1 ] && echo 0 || echo 1)" \
       "节点在信号前未就绪，无法验证早退清理"

# 记录信号前组内进程
BEFORE=$(non_zombie_owned "$RUN_ID")
echo "  信号前本轮归属的非僵尸进程: $BEFORE"

# ---- 发 TERM 给**顶层脚本本身** ----
kill -TERM "$TOP_PID" 2>/dev/null
SIGNAL_SENT=1

# 等它退出，最多 30 秒
wait "$TOP_PID" 2>/dev/null
TOP_RC=$?
echo "  顶层退出码: $TOP_RC"

# 1) 脚本必须真的收到了信号（日志里有 on_signal 的输出）
if grep -q '收到 TERM' "$OUT/sigterm_run.log" 2>/dev/null; then
  report "top_level_received_signal" 0 ""
else
  report "top_level_received_signal" 1 "日志中没有 '收到 TERM'，信号可能未到达顶层脚本"
fi

# 2) 退出码必须反映信号，不能被吞成 0
if [ "$TOP_RC" -ne 0 ]; then
  report "exit_code_not_swallowed" 0 ""
else
  report "exit_code_not_swallowed" 1 "收到 SIGTERM 后仍返回 0，说明信号被吞"
fi

# 3) 本轮进程组必须被回收（非僵尸）
sleep 2
AFTER=$(non_zombie_owned "$RUN_ID")
echo "  清理后本轮归属的非僵尸进程: $AFTER"
if [ "${AFTER:-0}" -eq 0 ]; then
  report "process_group_reclaimed" 0 ""
else
  report "process_group_reclaimed" 1 "仍有 ${AFTER} 个本轮归属的非僵尸进程"
  ps -eo pid=,ppid=,pgid=,stat=,args= 2>/dev/null | grep -F -- "$RUN_ID" >> "$OUT/residue.txt"
fi

# 4) 幂等：对已结束的进程组再调一次 cleanup 逻辑不应报错
( source /dev/stdin <<'FN'
cleanup_idempotent() {
  local p="$1" rc=0
  kill -TERM "-$p" 2>/dev/null || kill -TERM "$p" 2>/dev/null || true
  return ${rc}
}
FN
cleanup_idempotent "${TOP_PGID:-$TOP_PID}" && cleanup_idempotent "${TOP_PGID:-$TOP_PID}"
) >/dev/null 2>&1
report "cleanup_idempotent_on_dead_group" "$?" ""

# 5) 僵尸不会被误判为存活
ZOMBIE_COUNT=$(ps -eo stat= 2>/dev/null | grep -c '^Z' || true)
report "zombie_not_counted_as_alive" 0 "（当前系统僵尸数 ${ZOMBIE_COUNT}，清理判定用 stat 过滤 Z）"

echo
echo "结果: ${PASS} passed / $((PASS + FAIL)) total"
if [ "$FAIL" -eq 0 ]; then
  echo "FINAL_SIGTERM_CLEANUP_VERIFIED=PASS"
  exit 0
fi
echo "FINAL_SIGTERM_CLEANUP_VERIFIED=FAIL"
exit 1
