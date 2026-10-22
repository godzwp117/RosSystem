#!/usr/bin/env bash
# acceptance_wiring_check.sh -- 验收编排接线回归（1.0.3）
#
# 目的：证明 final_system.sh 的 acceptance 分支确实按
#        "各项目状态 -> ACCEPTANCE -> 退出码" 接线，而不是只看某个 rc 变量。
#
# 做法：复制 final_system.sh，**只**把五个实验函数体替换成固定返回值
#       （check_env 也固定返回 0），验收块本身一行不改。
# 声明：本测试证明的是编排逻辑，**不**代表任何真实实验已执行；
#       真实实验结论以独立复现章节的原始日志为准。
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
PASS=0; FAIL=0

run_case() {  # run_case <name> <want_status> <want_code> <host> <three> <ctrl> <m3> <enf>
  local name="$1" want_status="$2" want_code="$3"
  local host="$4" three="$5" ctrl="$6" m3="$7" enf="$8"
  local dir="$WORK/$name"
  mkdir -p "$dir/scripts"
  cp "$ROOT/scripts/acceptance_status.py" "$dir/scripts/"
  python3 "$ROOT/tests/integration/_make_acceptance_stub.py" \
      "$ROOT/scripts/final_system.sh" "$dir/scripts/final_system.sh" \
      "run_host_tests=$host" "run_three_real=$three" "run_controlled=$ctrl" \
      "run_m3_six=$m3" "run_enforce=$enf"
  ( cd "$dir" && bash scripts/final_system.sh --mode acceptance \
      --run-id "wiring-$name" --out-dir "artifacts/wiring" >"$dir/run.log" 2>&1 )
  local code=$?
  local summary=""
  local sfile="$dir/artifacts/wiring/wiring-$name/summary.txt"
  [ -f "$sfile" ] && summary="$(tr -d '\r' < "$sfile" | tr '\n' ' ')"
  if [ "$code" -eq "$want_code" ] && \
     printf '%s' "$summary" | grep -q "ACCEPTANCE=$want_status"; then
    echo "  [PASS] $name -> ACCEPTANCE=$want_status exit=$code"
    PASS=$((PASS+1))
  else
    echo "  [FAIL] $name -> exit=$code summary=[$summary] (want $want_status/$want_code)"
    FAIL=$((FAIL+1))
  fi
}

echo "== 5.1 全部 PASS =="
run_case all_pass PASS 0 0 0 0 0 0

echo "== 5.2 仅 Enforce 为 NOT_RUN（必须 INCOMPLETE / exit 9）=="
run_case enforce_notrun INCOMPLETE 9 0 0 0 0 9

echo "== 5.3 存在 FAIL =="
run_case controlled_fail FAIL 1 0 0 1 0 0

echo "== 5.4 FAIL 与 NOT_RUN 并存（应为 FAIL，且保留 NOT_RUN）=="
run_case fail_and_notrun FAIL 1 0 1 0 0 9
if grep -q "NOT_RUN_ITEMS=ENFORCE" \
   "$WORK/fail_and_notrun/artifacts/wiring/wiring-fail_and_notrun/summary.txt" 2>/dev/null; then
  echo "  [PASS] fail_and_notrun 保留了 NOT_RUN_ITEMS=ENFORCE"; PASS=$((PASS+1))
else
  echo "  [FAIL] fail_and_notrun 未保留 NOT_RUN 记录"; FAIL=$((FAIL+1))
fi

echo "== 5.2b 三真实 NOT_RUN 同样不得 PASS =="
run_case three_notrun INCOMPLETE 9 0 9 0 0 9

echo
echo "结果: ${PASS} passed / $((PASS+FAIL)) total"
[ "$FAIL" -eq 0 ] && { echo "ACCEPTANCE_WIRING=PASS"; exit 0; }
echo "ACCEPTANCE_WIRING=FAIL"; exit 1
