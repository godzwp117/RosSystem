#!/usr/bin/env bash
# acceptance_semantics_check.sh -- 验收状态语义的集成回归（1.0.3）
#
# 逐条验证任务书 5.1–5.4 的聚合语义：输入是"各项目状态"，
# 输出必须是 ACCEPTANCE 状态 + 进程退出码，二者一致。
# 本脚本只验证状态机，不声称任何真实实验已执行。
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="${PYTHON:-python3}"
AG="$ROOT/scripts/acceptance_status.py"
PASS=0; FAIL=0

check() {  # check <name> <expected-line> <expected-code> <items...>
  local name="$1" want_line="$2" want_code="$3"; shift 3
  local out code
  out="$("$PY" "$AG" "$@" 2>/dev/null)"; code=$?
  if [ "$out" = "$want_line" ] && [ "$code" -eq "$want_code" ]; then
    echo "  [PASS] $name -> $out (exit $code)"; PASS=$((PASS+1))
  else
    echo "  [FAIL] $name -> got '$out' exit=$code ; want '$want_line' exit=$want_code"
    FAIL=$((FAIL+1))
  fi
}

echo "== 5.1 全部必需项 PASS =="
check "all-pass" "PASS 0 - -" 0 \
  HOST_TESTS=PASS THREE_REAL=PASS CONTROLLED=PASS M3_SIX=PASS ENFORCE=PASS

echo "== 5.2 存在 NOT_RUN（Enforce 缺凭据）=="
check "enforce-not-run" "INCOMPLETE 9 ENFORCE -" 9 \
  HOST_TESTS=PASS THREE_REAL=PASS CONTROLLED=PASS M3_SIX=PASS ENFORCE=NOT_RUN

echo "== 5.3 存在 FAIL =="
check "controlled-fail" "FAIL 1 - CONTROLLED" 1 \
  HOST_TESTS=PASS THREE_REAL=PASS CONTROLLED=FAIL M3_SIX=PASS ENFORCE=PASS

echo "== 5.4 FAIL 与 NOT_RUN 并存 =="
check "fail-and-not-run" "FAIL 1 ENFORCE THREE_REAL" 1 \
  HOST_TESTS=PASS THREE_REAL=FAIL CONTROLLED=PASS M3_SIX=PASS ENFORCE=NOT_RUN

echo "== 边界：未执行任何项不得 PASS =="
check "empty" "INCOMPLETE 9 - -" 9

echo
echo "结果: ${PASS} passed / $((PASS+FAIL)) total"
[ "$FAIL" -eq 0 ] && { echo "ACCEPTANCE_SEMANTICS=PASS"; exit 0; }
echo "ACCEPTANCE_SEMANTICS=FAIL"; exit 1
