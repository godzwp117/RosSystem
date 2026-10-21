#!/usr/bin/env bash
# test_preflight_failfast.sh -- 预检必须是硬门槛的**反例**测试。
#
# 每个案例都要同时证明三件事：
#   1. 退出码非零；
#   2. 输出给出正确的失败原因（PREFLIGHT_FAIL + 具体条件）；
#   3. **后续验收命令没有执行**（没有生成 controlled_online / m3_online /
#      dds_enforce 等证据目录）。
#
# 只证明"退出非零"是不够的：旧实现同样会返回非零（因为后续步骤都失败），
# 但它**跑了**那些步骤，正是本轮要修的问题。
#
# 所有故障注入都通过**环境操纵**完成（PATH 影子、环境变量、临时目录），
# 不破坏宿主 ROS 安装，也不杀任何真实 ROS 进程。
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT="$REPO/scripts/final_system.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

PASS=0
FAIL=0

report() {  # report <name> <ok> <detail>
  if [ "$2" -eq 0 ]; then
    echo "  [PASS] $1"
    PASS=$((PASS + 1))
  else
    echo "  [FAIL] $1 -- $3"
    FAIL=$((FAIL + 1))
  fi
}

# 断言：预检失败时不得产生任何在线证据目录
assert_no_downstream() {  # assert_no_downstream <outdir>
  local out="$1"
  local offending
  offending=$(find "$out" -maxdepth 3 -type d \
      \( -name controlled_online -o -name m3_online -o -name dds_enforce \
         -o -name three_real -o -name unit_tests \) 2>/dev/null | head -3)
  [ -z "$offending" ]
}

run_case() {  # run_case <name> <expect-substring> <env-prefix...>
  local name="$1" expect="$2"; shift 2
  local out="$TMP/out-$name"
  mkdir -p "$out"
  local log="$TMP/log-$name.txt"

  ( cd "$REPO" && env "$@" bash "$SCRIPT" --mode acceptance \
      --run-id "pf-$name" --out-dir "$out" ) > "$log" 2>&1
  local rc=$?

  local ok=0 detail=""
  [ "$rc" -eq 0 ] && { ok=1; detail="期望非零退出，实际为 0"; }
  if ! grep -q 'PREFLIGHT_FAIL' "$log" 2>/dev/null; then
    ok=1; detail="$detail；输出缺少 PREFLIGHT_FAIL"
  fi
  if ! grep -q "$expect" "$log" 2>/dev/null; then
    ok=1; detail="$detail；输出缺少原因 '$expect'"
  fi
  if ! assert_no_downstream "$out"; then
    ok=1; detail="$detail；预检失败后仍生成了后续验收证据目录"
  fi
  if grep -q 'ACCEPTANCE=PASS' "$log" 2>/dev/null; then
    ok=1; detail="$detail；出现了伪造的 ACCEPTANCE=PASS"
  fi

  report "$name" "$ok" "$detail"
}

echo "=== 预检硬门槛反例测试 ==="

# 1) 未 source ROS：清空 ROS_DISTRO / AMENT_PREFIX_PATH
run_case "no-ros" "ROS 2 环境未 source" ROS_DISTRO= AMENT_PREFIX_PATH= CMAKE_PREFIX_PATH=

# 2) 缺少 colcon：PATH 里放一个不含 colcon 的最小目录
SAFE_BIN="$TMP/bin"
mkdir -p "$SAFE_BIN"
for tool in bash git python3 awk ps find grep sed date mkdir wc sort xargs; do
  src="$(command -v "$tool" 2>/dev/null)" && ln -sf "$src" "$SAFE_BIN/$tool" 2>/dev/null
done
run_case "no-colcon" "colcon 不可用" PATH="$SAFE_BIN"

# 3) jsonschema 缺失：用影子 python3 让 import 失败
NOJSON_BIN="$TMP/bin-nojson"
mkdir -p "$NOJSON_BIN"
cat > "$NOJSON_BIN/python3" <<'STUB'
#!/usr/bin/env bash
if [ "${1:-}" = "-c" ] && printf '%s' "${2:-}" | grep -q 'import jsonschema'; then
  echo "ModuleNotFoundError: No module named 'jsonschema'" >&2
  exit 1
fi
exec /usr/bin/env -u PATH python3 "$@" 2>/dev/null || exec python3.real "$@"
STUB
chmod +x "$NOJSON_BIN/python3"
run_case "no-jsonschema" "jsonschema" PATH="$NOJSON_BIN:$PATH"

# 4) 工作树不干净：在仓库里放一个临时未跟踪文件
DIRTY="$REPO/.preflight-dirty-marker"
: > "$DIRTY"
run_case "dirty-tree" "工作树干净"
rm -f "$DIRTY"

# 5) SHA 无法解析：从无 .git 的目录运行
NOGIT="$TMP/nogit"
mkdir -p "$NOGIT/scripts"
cp "$SCRIPT" "$NOGIT/scripts/final_system.sh"
mkdir -p "$NOGIT/config"
for f in team_modules.three-real.yaml team_modules.member3.real.yaml task_policy.yaml; do
  cp "$REPO/config/$f" "$NOGIT/config/" 2>/dev/null
done
( cd "$NOGIT" && bash scripts/final_system.sh --mode acceptance \
    --run-id "pf-nogit" --out-dir "$TMP/out-nogit" ) > "$TMP/log-nogit.txt" 2>&1
rc=$?
ok=0; detail=""
[ "$rc" -eq 0 ] && { ok=1; detail="期望非零退出"; }
grep -q 'PREFLIGHT_FAIL' "$TMP/log-nogit.txt" 2>/dev/null || { ok=1; detail="$detail；缺 PREFLIGHT_FAIL"; }
grep -qE '40 位 SHA|SHA' "$TMP/log-nogit.txt" 2>/dev/null || { ok=1; detail="$detail；缺 SHA 原因"; }
assert_no_downstream "$TMP/out-nogit" || { ok=1; detail="$detail；产生了后续证据"; }
report "no-git-sha" "$ok" "$detail"

# 6) 运行冲突：启动一个**不会被误杀**的替身进程（名为 navigation_sim 的 sleep）
CONFLICT_BIN="$TMP/conflict"
mkdir -p "$CONFLICT_BIN"
cp /bin/sleep "$CONFLICT_BIN/navigation_sim" 2>/dev/null || ln -sf /bin/sleep "$CONFLICT_BIN/navigation_sim"
"$CONFLICT_BIN/navigation_sim" 30 &
CONFLICT_PID=$!
sleep 0.3
run_case "runtime-conflict" "残留 ROS 节点" PATH="$CONFLICT_BIN:$PATH"
# 只杀我们自己的替身
kill "$CONFLICT_PID" 2>/dev/null
wait "$CONFLICT_PID" 2>/dev/null

# 7) ROS 2 包未构建：影子 ros2 让 pkg prefix 失败
NOROS2_BIN="$TMP/bin-noros2"
mkdir -p "$NOROS2_BIN"
cat > "$NOROS2_BIN/ros2" <<'STUB'
#!/usr/bin/env bash
if [ "${1:-}" = "pkg" ]; then exit 1; fi
exit 1
STUB
chmod +x "$NOROS2_BIN/ros2"
run_case "packages-unbuilt" "找不到已构建的 ROS 2 包" PATH="$NOROS2_BIN:$PATH"

echo
echo "结果: ${PASS} passed / $((PASS + FAIL)) total"
if [ "$FAIL" -eq 0 ]; then
  echo "FINAL_STRICT_PREFLIGHT_FAIL_FAST=PASS"
  exit 0
fi
echo "FINAL_STRICT_PREFLIGHT_FAIL_FAST=FAIL"
exit 1
