#!/usr/bin/env bash
# final_system.sh -- RosSystem 最终交付统一执行入口（2026-10-22）
#
# 设计原则
# --------
# 1. **不重写业务逻辑**：本脚本只编排既有组件（F0 / Planner / Gateway /
#    NavigationSim / M3 六场景驱动 / 正式 Enforce 测试），不复制它们的判定。
# 2. **不掩盖失败**：任何关键步骤失败都以非零退出，不用 `|| true` 吞掉。
# 3. **不降级安全**：不关闭 DDS-Security，不改 TaskPolicy，不改 F0 严格模式。
# 4. **可审计**：每个模式都写 run_id、代码 SHA、命令、退出码到证据目录。
#
# 用法
# ----
#   scripts/final_system.sh --check                    # 环境与版本自检
#   scripts/final_system.sh --mode controlled          # 受控正向在线闭环
#   scripts/final_system.sh --mode three-real-strict   # 三真实严格准入
#   scripts/final_system.sh --mode enforce             # 正式 DDS Enforce
#   scripts/final_system.sh --mode acceptance          # 全量验收
#
# 通用选项：
#   --run-id <id>        指定 run_id（默认自动生成）
#   --out-dir <dir>      证据根目录（默认 artifacts/integration/final-deliverable-2026-10-22）
#   --domain <n>         在线模式使用的 ROS_DOMAIN_ID（默认 74）
#   --help
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

MODE=""
RUN_ID=""
OUT_ROOT="artifacts/integration/final-deliverable-2026-10-22"
ONLINE_DOMAIN="${FINAL_ONLINE_DOMAIN:-74}"
CONTAINER="${FINAL_CONTAINER:-}"

usage() {
  sed -n '2,26p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  exit 0
}

while [ $# -gt 0 ]; do
  case "$1" in
    --check) MODE="check" ;;
    --mode) MODE="${2:-}"; shift ;;
    --run-id) RUN_ID="${2:-}"; shift ;;
    --out-dir) OUT_ROOT="${2:-}"; shift ;;
    --domain) ONLINE_DOMAIN="${2:-}"; shift ;;
    --help|-h) usage ;;
    *) echo "ERROR: 未知参数 $1" >&2; exit 2 ;;
  esac
  shift
done

case "$MODE" in
  check|controlled|three-real-strict|enforce|acceptance) ;;
  "") echo "ERROR: 必须指定 --check 或 --mode <controlled|three-real-strict|enforce|acceptance>" >&2; exit 2 ;;
  *) echo "ERROR: 未知模式 '$MODE'" >&2; exit 2 ;;
esac

if [ -z "$RUN_ID" ]; then
  RUN_ID="final-$(date -u +%Y%m%dT%H%M%SZ)"
fi
EVIDENCE="$OUT_ROOT/$RUN_ID"
mkdir -p "$EVIDENCE"

CODE_SHA="$(git rev-parse HEAD 2>/dev/null || echo UNKNOWN)"
CODE_SHA_SOURCE="git"
TREE="$(git rev-parse HEAD^{tree} 2>/dev/null || echo UNKNOWN)"
# 发布压缩包不含 .git：此时从打包清单读取真实来源提交，而不是伪造 Git 工作树。
# artifact_commit 是生成该包的源码提交；baseline_core_sha 是安全判定所依据的历史受测核心。
BASELINE_CORE_SHA=""
PACKAGE_VERSION=""
PACKAGE_ARTIFACT_COMMIT=""
PACKAGE_SOURCE=""
if [ "$CODE_SHA" = "UNKNOWN" ] && [ -f "BUILD_INFO.json" ]; then
  CODE_SHA="$(python3 -c 'import json;print(json.load(open("BUILD_INFO.json"))["artifact_commit"])' 2>/dev/null || echo UNKNOWN)"
  CODE_SHA_SOURCE="BUILD_INFO.json"
  PACKAGE_SOURCE="BUILD_INFO.json"
  PACKAGE_ARTIFACT_COMMIT="$CODE_SHA"
  BASELINE_CORE_SHA="$(python3 -c 'import json;print(json.load(open("BUILD_INFO.json")).get("baseline_core_sha",""))' 2>/dev/null || echo '')"
  PACKAGE_VERSION="$(python3 -c 'import json;print(json.load(open("BUILD_INFO.json")).get("version",""))' 2>/dev/null || echo '')"
fi
DIFFTY="$(git status --porcelain 2>/dev/null | wc -l)"
[ -n "${DIFFTY:-}" ] || DIFFTY=0

log() { echo "[$(date -u +%H:%M:%SZ)] $*"; }

record() {  # record <name> <exit-code> <command...>
  local name="$1" rc="$2"; shift 2
  {
    echo "=== $name ==="
    echo "command: $*"
    echo "exit_code: $rc"
    echo "at: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "code_sha: $CODE_SHA"
    echo "run_id: $RUN_ID"
  } >> "$EVIDENCE/commands.log"
}

# ---------------------------------------------------------------- 运行元数据
# 控制台依赖 tested_commit.json 展示 run_id / 受测版本；旧实现从不写该文件，
# 于是页面只能显示「—」「未记录」。这里记录可核对的来源，不伪造 Git 信息。
write_run_metadata() {  # write_run_metadata <status>
  local status="${1:-RUNNING}"
  python3 - "$EVIDENCE" "$RUN_ID" "$MODE" "$CODE_SHA" "$CODE_SHA_SOURCE" \
           "$BASELINE_CORE_SHA" "$PACKAGE_VERSION" "$PACKAGE_ARTIFACT_COMMIT" \
           "$status" <<'PYMETA'
import json, os, sys, datetime
(ev, run_id, mode, sha, sha_src, baseline, version,
 artifact_commit, status) = sys.argv[1:10]
repo = os.path.dirname(os.path.dirname(os.path.abspath(ev)))
doc = {
    'run_id': run_id,
    'mode': mode,
    'generated_at': datetime.datetime.now(datetime.timezone.utc)
                    .strftime('%Y-%m-%dT%H:%M:%SZ'),
    'tested_code_sha': sha,
    'sha_source': sha_src,
    'baseline_core_sha': baseline or None,
    'package_version': version or None,
    'artifact_commit': artifact_commit or (sha if sha_src == 'git' else None),
    'evidence_source': os.path.relpath(ev, repo),
    'result': status,
    'note': ('tested_code_sha 为本次实际执行代码的提交；baseline_core_sha 为历史受测核心，'
             '两者含义不同，不得互相替代。'),
}
with open(os.path.join(ev, 'tested_commit.json'), 'w', encoding='utf-8') as fh:
    json.dump(doc, fh, ensure_ascii=False, indent=2)
PYMETA
}

update_run_result() {  # update_run_result <PASS|FAIL|NOT_RUN>
  local status="$1"
  local path="$EVIDENCE/tested_commit.json"
  [ -f "$path" ] || return 0
  python3 - "$path" "$status" <<'PYRES'
import json, sys
path, status = sys.argv[1], sys.argv[2]
doc = json.load(open(path, encoding='utf-8'))
doc['result'] = status
json.dump(doc, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
PYRES
}

# ---------------------------------------------------------------- 环境自检
check_env() {
  local fail=0
  log "环境自检 (run_id=$RUN_ID)"

  local ros="absent"
  if [ -n "${ROS_DISTRO:-}" ]; then ros="$ROS_DISTRO"; fi
  if [ "$ros" = "absent" ] && [ -f /opt/ros/jazzy/setup.bash ]; then ros="jazzy(未source)"; fi
  echo "  ROS: $ros"

  local py; py="$(python3 -c 'import sys;print(".".join(map(str,sys.version_info[:3])))' 2>/dev/null || echo absent)"
  echo "  Python: $py"

  local js; js="$(python3 -c 'import jsonschema;print(jsonschema.__version__)' 2>/dev/null || echo absent)"
  echo "  jsonschema: $js"
  [ "$js" = "absent" ] && { echo "  [FAIL] jsonschema 缺失" >&2; fail=1; }

  echo "  colcon: $(command -v colcon >/dev/null 2>&1 && echo present || echo absent)"

  echo "  代码 SHA: $CODE_SHA"
  echo "  未提交改动: $DIFFTY"
  [ "$DIFFTY" -ne 0 ] && echo "  [WARN] 工作树有未提交改动；正式验收应在干净工作树上执行" >&2

  for f in config/team_modules.three-real.yaml config/team_modules.member3.real.yaml \
           config/task_policy.yaml scripts/team_demo.py scripts/m3_online_drive.sh \
           scripts/m3_online_extra.sh scripts/verify_m3_online_evidence.py; do
    if [ -f "$f" ]; then echo "  [ok] $f"; else echo "  [FAIL] 缺少 $f" >&2; fail=1; fi
  done

  if [ -n "$CONTAINER" ]; then
    echo "  容器: $CONTAINER"
    docker inspect "$CONTAINER" >/dev/null 2>&1 || { echo "  [FAIL] 容器 $CONTAINER 不存在" >&2; fail=1; }
  fi

  # 正式验收的**强制**预检：这些条件不满足就直接 PREFLIGHT_FAIL。
  # 与 --check 的诊断模式不同：诊断允许 WARN，正式验收不允许。
  if [ "${STRICT_PREFLIGHT:-0}" = "1" ]; then
    local sha; sha="$(git rev-parse HEAD 2>/dev/null || echo '')"
    if ! printf '%s' "$sha" | grep -qE '^[0-9a-f]{40}$'; then
      echo "  [PREFLIGHT_FAIL] 无法取得完整 40 位 SHA" >&2; fail=1
    fi
    if [ "$DIFFTY" -ne 0 ]; then
      echo "  [PREFLIGHT_FAIL] 正式验收要求工作树干净，当前 $DIFFTY 项未提交" >&2; fail=1
    fi
    if [ -z "${ROS_DISTRO:-}" ]; then
      echo "  [PREFLIGHT_FAIL] ROS 2 环境未 source（ROS_DISTRO 为空）" >&2; fail=1
    fi
    if ! command -v colcon >/dev/null 2>&1; then
      echo "  [PREFLIGHT_FAIL] colcon 不可用" >&2; fail=1
    fi
    for pkg in rg_interfaces rg_demo_nodes rg_gateway; do
      if ! ros2 pkg prefix "$pkg" >/dev/null 2>&1; then
        echo "  [PREFLIGHT_FAIL] 找不到已构建的 ROS 2 包 $pkg" >&2; fail=1
      fi
    done
    if ! python3 -c 'import jsonschema' >/dev/null 2>&1; then
      echo "  [PREFLIGHT_FAIL] python3 缺少 jsonschema" >&2; fail=1
    fi
    # 只识别**明确的 ROS 节点进程**，避免 `pgrep -f 'rg_gateway|rg_demo_nodes'`
    # 匹配到调用者自身的命令行（本脚本、测试脚本、grep 参数里都可能含这些词）。
    # 做法：匹配可执行名/解释器脚本路径，并对本进程组做排除。
    local stray
    stray=$(ps -eo pid=,pgid=,args= 2>/dev/null \
      | awk -v self="$$" '$2 != self && ($0 ~ /[\/]rg_gateway( |$)/ || $0 ~ /security_gateway( |$)/ || $0 ~ /navigation_sim( |$)/ || $0 ~ /operator_node( |$)/) {n++} END {print n+0}')
    if [ "${stray:-0}" -gt 0 ]; then
      echo "  [PREFLIGHT_FAIL] 检测到 ${stray} 个残留 ROS 节点进程，可能干扰验收" >&2; fail=1
    fi
  fi

  record "check_env" "$fail" "final_system.sh --check"
  if [ "$fail" -eq 0 ]; then
    log "自检通过"
    echo "CHECK_RESULT=PASS" | tee "$EVIDENCE/check.txt"
  else
    log "自检失败" >&2
    echo "CHECK_RESULT=FAIL" | tee "$EVIDENCE/check.txt"
  fi
  return "$fail"
}

# ---------------------------------------------------------------- 代码级验收（宿主）
run_host_tests() {
  local rc=0
  log "契约检查"
  python3 scripts/validate_team_contracts.py --all > "$EVIDENCE/contracts.log" 2>&1
  rc=$?; record "contracts" "$rc" "validate_team_contracts.py --all"
  [ "$rc" -ne 0 ] && { echo "  [FAIL] 契约" >&2; return 1; }
  echo "  [PASS] 契约"

  log "F0 P0 安全反例"
  python3 -m pytest tests/unit/test_phase2_security_boundaries.py \
      tests/unit/test_f0_identity_trust_boundary.py -q \
      > "$EVIDENCE/f0_p0.log" 2>&1
  rc=$?; record "f0_p0" "$rc" "pytest phase2 + f0_identity_trust_boundary"
  [ "$rc" -ne 0 ] && { echo "  [FAIL] F0 P0" >&2; tail -5 "$EVIDENCE/f0_p0.log" >&2; return 1; }
  echo "  [PASS] F0 P0: $(tail -1 "$EVIDENCE/f0_p0.log")"

  log "全仓单元测试"
  python3 -m pytest tests/unit -q > "$EVIDENCE/unit_tests.log" 2>&1
  rc=$?; record "unit_tests" "$rc" "pytest tests/unit"
  [ "$rc" -ne 0 ] && { echo "  [FAIL] 全仓单测" >&2; tail -5 "$EVIDENCE/unit_tests.log" >&2; return 1; }
  echo "  [PASS] 全仓单测: $(tail -1 "$EVIDENCE/unit_tests.log")"
  return 0
}

# ---------------------------------------------------------------- 三真实严格
# 退出码语义（run_three_real_online.py 0.2 起）：
#   0 = 三个真实模块均成功调用、契约有效，且 F0 以**预期原因**阻断
#   1 = 预期未达成（例如被错误放行）
#   2 = LEVEL1/LEVEL2 不成立（模块未跑通/契约无效）——不得当作安全阻断
run_three_real() {
  log "三真实 External 严格准入"
  python3 scripts/run_three_real_online.py \
      --run-id "three-${RUN_ID}" --out-dir "$EVIDENCE/three_real" \
      --config config/team_modules.three-real.yaml --expect-block \
      > "$EVIDENCE/three_real.log" 2>&1
  local rc=$?
  record "three_real" "$rc" "run_three_real_online.py --expect-block"
  # 无论成败都打印分层结果：判定必须能追溯到 LEVEL1/2/3 的真实取值。
  python3 - "$EVIDENCE/three_real/summary.json" <<'PY' || true
import json, sys
try:
    d = json.load(open(sys.argv[1], encoding='utf-8'))
except (OSError, ValueError):
    print('  [ERROR] 三真实摘要缺失：本次调用没有产生 summary.json')
    raise SystemExit(0)
lv = d.get('levels') or {}
print('  LEVEL1 模块真实调用 :', lv.get('THREE_EXTERNAL_CALLED'))
print('  LEVEL2 证据契约有效 :', lv.get('THREE_EXTERNAL_VALIDATED'))
print('  LEVEL3 联合准入     :', lv.get('THREE_EXTERNAL_ONLINE_PROCEED'))
f0 = d.get('f0') or {}
print('  F0:', f0.get('decision'), f0.get('reason_code'))
for b in (d.get('blockers') or [])[:8]:
    print('    blocker:', b)
PY
  if [ "$rc" -ne 0 ]; then
    if [ "$rc" -eq 2 ]; then
      echo "  [FAIL] 三真实严格：模块未跑通或契约无效，不能判定为安全阻断（exit=2）" >&2
    else
      echo "  [FAIL] 三真实严格：预期阻断未达成（exit=$rc）" >&2
    fi
    return 1
  fi
  echo "  [PASS] 三真实 External 调用、证据契约与预期阻断均已核对"
  return 0
}

# ---------------------------------------------------------------- 受控在线
run_controlled() {
  log "受控正向在线闭环（M1/M2 MOCK + M3 EXTERNAL），Domain $ONLINE_DOMAIN"
  local ev="$EVIDENCE/controlled_online"
  mkdir -p "$ev"
  ROS_DOMAIN_ID="$ONLINE_DOMAIN" bash scripts/m3_online_drive.sh \
      "${RUN_ID}-controlled" "$ev" config/team_modules.member3.real.yaml \
      > "$ev/drive.log" 2>&1
  local rc=$?
  record "controlled_online" "$rc" "m3_online_drive.sh (domain $ONLINE_DOMAIN)"
  [ "$rc" -ne 0 ] && { echo "  [FAIL] 受控在线" >&2; tail -10 "$ev/drive.log" >&2; return 1; }

  # 行数断言不足以证明每个 request 的决策正确（两个都 BLOCK 加一条无关 Goal
  # 也能过），改用 request_id 级严格验证器逐场景核对不变量。
  python3 scripts/verify_final_controlled_online.py \
      --run-dir "$ev/stack-a" \
      --json-out "$ev/controlled_verification.json" \
      --md-out "$ev/controlled_verification.md" \
      > "$ev/verifier.log" 2>&1
  local rc_v=$?
  record "controlled_verifier" "$rc_v" "verify_final_controlled_online.py"
  cat "$ev/verifier.log"
  if [ "$rc_v" -ne 0 ]; then
    echo "  [FAIL] request_id 级受控在线验收未通过" >&2
    return 1
  fi
  echo "  [PASS] 受控在线 request_id 级严格验收"
}

# ---------------------------------------------------------------- M3 六场景
run_m3_six() {
  log "M3 在线六场景（Domain $ONLINE_DOMAIN）"
  local ev="$EVIDENCE/m3_online"
  mkdir -p "$ev"
  ROS_DOMAIN_ID="$ONLINE_DOMAIN" bash scripts/m3_online_drive.sh \
      "${RUN_ID}-six" "$ev" config/team_modules.member3.real.yaml \
      > "$ev/drive.log" 2>&1
  local rc_a=$?
  ROS_DOMAIN_ID="$ONLINE_DOMAIN" bash scripts/m3_online_extra.sh \
      "${RUN_ID}-six" "$ev" config/team_modules.member3.real.yaml \
      > "$ev/extra.log" 2>&1
  local rc_b=$?
  record "m3_online_drive" "$rc_a" "m3_online_drive.sh"
  record "m3_online_extra" "$rc_b" "m3_online_extra.sh"
  if [ "$rc_a" -ne 0 ] || [ "$rc_b" -ne 0 ]; then
    echo "  [FAIL] 六场景驱动失败 (drive=$rc_a extra=$rc_b)" >&2
    tail -6 "$ev/extra.log" >&2
    return 1
  fi
  # 合并两组证据后由独立验证器复核
  mkdir -p "$ev/merged"
  cat "$ev/stack-a/gateway_audit.jsonl" "$ev/stack-b/gateway_audit.jsonl" > "$ev/merged/gateway_audit.jsonl" 2>/dev/null
  cat "$ev/stack-a/navsim_goals.jsonl" "$ev/stack-b/navsim_goals.jsonl" > "$ev/merged/navsim_goals.jsonl" 2>/dev/null
  cp "$ev"/stack-a/f0_ON* "$ev"/stack-a/adapter_ON* "$ev/merged/" 2>/dev/null
  cp "$ev"/stack-b/f0_ON* "$ev"/stack-b/adapter_ON* "$ev/merged/" 2>/dev/null
  python3 - "$ev" <<'PY'
import json, os, sys
ev = sys.argv[1]
rows = []
for stack in ('stack-a', 'stack-b'):
    path = os.path.join(ev, stack, 'manifest.json')
    if os.path.exists(path):
        rows.extend(json.load(open(path, encoding='utf-8'))['scenarios'])
json.dump({'scenarios': rows}, open(os.path.join(ev, 'merged', 'manifest.json'), 'w'),
          ensure_ascii=False, indent=2)
PY
  # 由**原始日志**生成 claims（不是从报告文案反填），再交由验证器比对
  python3 - "$ev/merged" <<'PYCLAIMS'
import json, os, sys
merged = sys.argv[1]

def load(name):
    path = os.path.join(merged, name)
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding='utf-8') as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    pass
    return rows

audit = load('gateway_audit.jsonl')
journal = load('navsim_goals.jsonl')
manifest = json.load(open(os.path.join(merged, 'manifest.json'), encoding='utf-8'))
claims = {}
for entry in manifest.get('scenarios') or []:
    cid = entry.get('cid')
    rid = entry.get('request_id')
    if not cid or not rid:
        continue
    decisions = [r for r in audit if r.get('request_id') == rid
                 and r.get('event_type') == 'DecisionEvent']
    goals = [g for g in journal if g.get('request_id') == rid]
    row = {
        'gateway_arrival': len([r for r in audit if r.get('request_id') == rid
                                and r.get('event_type') == 'RosCommEvent']),
        'navsim_goals': len(goals),
    }
    if decisions:
        row['gateway_decision'] = decisions[0].get('decision')
        if decisions[0].get('reason_code'):
            row['gateway_reason_code'] = decisions[0].get('reason_code')
    if goals:
        row['gateway_execution'] = 1
    claims[cid] = row
json.dump({'scenarios': claims}, open(os.path.join(merged, 'claims.json'), 'w'),
          ensure_ascii=False, indent=2)
print('claims 已从原始日志生成:', ', '.join(sorted(claims)))
PYCLAIMS

  python3 scripts/verify_m3_online_evidence.py --run-dir "$ev/merged" \
      --claims "$ev/merged/claims.json" \
      --json-out "$ev/merged/verification.json" --md-out "$ev/merged/verification.md" \
      > "$ev/verify.log" 2>&1
  local rc_v=$?
  record "m3_verify" "$rc_v" "verify_m3_online_evidence.py"
  python3 - "$ev/merged/verification.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1], encoding='utf-8'))
print('  verdict=%s checks=%s failures=%s' % (d.get('verdict'), d.get('checks'), d.get('failures')))
PY
  [ "$rc_v" -ne 0 ] && { echo "  [FAIL] 六场景证据复核未通过" >&2; return 1; }
  echo "  [PASS] M3 六场景"
  return 0
}

# ---------------------------------------------------------------- DDS Enforce
run_enforce() {
  log "正式 DDS Enforce（S1/S2/S3/S3C/S4/S5/S6）"
  local ev="$EVIDENCE/dds_enforce"
  mkdir -p "$ev"
  # 凭据门禁：公开包**刻意不含** keystore/私钥。缺凭据时本项为 NOT_RUN，
  # 既不是 PASS 也不是 FAIL，更不得拿历史 7/7 充当本次结果。
  if [ ! -d security/keystore ]; then
    echo "DDS_ENFORCE=NOT_RUN reason=缺少授权的 security/keystore 与私钥（公开包不含凭据）" \
      | tee "$ev/NOT_RUN.txt"
    record "dds_enforce" 9 "preflight: security/keystore 缺失"
    return 9
  fi
  if [ ! -f tests/integration/sros2_check.py ]; then
    echo "DDS_ENFORCE=NOT_RUN reason=缺少 tests/integration/sros2_check.py" \
      | tee "$ev/NOT_RUN.txt"
    record "dds_enforce" 9 "preflight: sros2_check.py 缺失"
    return 9
  fi
  # 正式权限按 Domain 绑定，必须在其设计的域上运行
  python3 tests/integration/sros2_check.py --run-id "enforce-${RUN_ID}" \
      > "$ev/sros2_check.log" 2>&1
  local rc=$?
  record "dds_enforce" "$rc" "sros2_check.py"
  grep -E "SROS2 SUMMARY" -A1 "$ev/sros2_check.log" | head -2
  [ "$rc" -ne 0 ] && { echo "  [FAIL] DDS Enforce" >&2; tail -10 "$ev/sros2_check.log" >&2; return 1; }
  echo "  [PASS] 正式 DDS Enforce"
  return 0
}

# ---------------------------------------------------------------- 主流程
# 退出码约定：
#   0 = 全部结果 PASS
#   1 = 存在 FAIL
#   3 = 环境自检失败
#   4 = 单模式实验失败
#   8 = 严格预检失败（acceptance）
#   9 = 条件不满足，NOT_RUN（例如缺少 DDS 凭据）
RESULTS=""
mark() { RESULTS="${RESULTS}$1=$2\n"; }

finish() {  # finish <exit-code> <metadata-status>
  local code="$1" status="$2"
  printf "$RESULTS" | tee "$EVIDENCE/summary.txt"
  printf "$RESULTS" >> "$EVIDENCE/commands.log"
  update_run_result "$status"
  exit "$code"
}

write_run_metadata RUNNING

case "$MODE" in
  check)
    check_env; rc=$?
    update_run_result "$([ "$rc" -eq 0 ] && echo PASS || echo FAIL)"
    exit "$rc"
    ;;
  controlled)
    check_env || { update_run_result FAIL; exit 3; }
    run_controlled || { mark CONTROLLED FAIL; finish 4 FAIL; }
    mark CONTROLLED PASS
    ;;
  three-real-strict)
    check_env || { update_run_result FAIL; exit 3; }
    run_three_real || { mark THREE_REAL FAIL; finish 4 FAIL; }
    mark THREE_REAL PASS
    ;;
  enforce)
    run_enforce; rc=$?
    if [ "$rc" -eq 9 ]; then
      mark ENFORCE NOT_RUN
      finish 9 NOT_RUN
    elif [ "$rc" -ne 0 ]; then
      mark ENFORCE FAIL
      finish 4 FAIL
    fi
    mark ENFORCE PASS
    ;;
  acceptance)
    rc_all=0
    # 预检是**硬门槛**：失败立即终止，不启动任何 ROS 栈、不跑三真实、
    # 不进 DDS Enforce。旧实现用 `|| rc_all=1` 继续往下跑，
    # 会让"预检失败"被后续的栈启动失败掩盖，甚至误报出在线 PASS。
    if ! STRICT_PREFLIGHT=1 check_env; then
      mark PREFLIGHT FAIL
      mark ACCEPTANCE FAIL
      printf "$RESULTS" | tee "$EVIDENCE/summary.txt"
      printf "$RESULTS" >> "$EVIDENCE/commands.log"
      echo "PREFLIGHT_FAIL" | tee -a "$EVIDENCE/summary.txt"
      echo "ERROR: 预检失败，验收已终止（未启动任何后续测试）" >&2
      update_run_result FAIL
      exit 8
    fi
    run_host_tests || rc_all=1
    run_three_real || rc_all=1
    run_controlled || rc_all=1
    run_m3_six || rc_all=1
    # NOT_RUN（缺凭据）不算 PASS，但也不冒充 FAIL：单独记录后继续。
    run_enforce; rc_e=$?
    if [ "$rc_e" -eq 9 ]; then mark ENFORCE NOT_RUN; elif [ "$rc_e" -ne 0 ]; then mark ENFORCE FAIL; rc_all=1; else mark ENFORCE PASS; fi
    mark ACCEPTANCE "$([ "$rc_all" -eq 0 ] && echo PASS || echo FAIL)"
    if [ "$rc_all" -eq 0 ]; then
      log "验收通过"
      finish 0 PASS
    else
      log "验收存在失败项" >&2
      finish 1 FAIL
    fi
    ;;
esac

# 单模式统一收尾：只有每一行结果都是 PASS 才返回 0。
RC_FAILED=0
while IFS= read -r _line; do
  [ -z "$_line" ] && continue
  case "$_line" in
    *=PASS) : ;;
    *) RC_FAILED=1 ;;
  esac
done < <(printf "$RESULTS")
if [ "$RC_FAILED" -eq 0 ]; then
  finish 0 PASS
else
  finish 1 FAIL
fi
