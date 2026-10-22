#!/usr/bin/env bash
# demo_20261019_release.sh -- 2026-10-19 演示的发布级统一入口。
#
# 为什么需要它
# ------------
# 演示要跑四类场景（M3 在线闭环、三真实模块联合调用、F0 身份防伪造、
# DDS-Security Enforce），它们各自已有成熟驱动脚本。缺的不是驱动，而是：
#   * 一个能**先确认版本与环境**再开演的门禁（演示最怕跑错分支/域冲突）；
#   * 一个统一的 run_id，把四类场景的证据串到同一个目录下；
#   * 一个不静默降级、失败能说清原因的外壳。
# 因此本脚本只做编排与门禁，不重复实现任何场景逻辑。
#
# 安全边界（刻意不做的事）
# ----------------------
#   * 不修改 Gateway 正式 TaskPolicy，不放宽 DDS 最小权限；
#   * 不在严格模式失败时自动切到 CONTROLLED_TEST_ONLY；
#   * 不按进程名杀节点（只终止本脚本自己启动的进程组）；
#   * 不清空历史日志、证据或密钥。
#
# 用法
# ----
#   scripts/demo_20261019_release.sh --check
#   scripts/demo_20261019_release.sh --scenario all --run-id demo-<ts>
#   scripts/demo_20261019_release.sh --scenario m3 --run-id demo-<ts>
#
# 场景：check | ab | m3 | three-real | f0 | dds | all
# 退出码：0=全部通过；1=有场景失败；2=用法错误；3=环境门禁未通过
set -uo pipefail

WS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$WS" || exit 3

CONTAINER="${RG_CONTAINER:-rg_demo}"
DOMAIN="${RG_DOMAIN_ID:-56}"
ENFORCE_DOMAIN="${RG_ENFORCE_DOMAIN:-43}"
OUT_ROOT="${WS}/artifacts/demo-2026-10-19"
SCENARIO=""
RUN_ID=""
ASSUME_YES=0

usage() {
  cat <<'USAGE'
用法: demo_20261019_release.sh [选项]

  --scenario <check|ab|m3|three-real|f0|dds|all>   要执行的演示场景（默认 check）
  --run-id <id>        本次演示的运行标识（默认按 UTC 时间生成）
  --container <name>   演示容器（默认 $RG_CONTAINER 或 rg_demo）
  --domain <id>        在线场景的 ROS_DOMAIN_ID（默认 56）
  --out-root <dir>     证据根目录（默认 artifacts/demo-2026-10-19）
  --yes                跳过交互确认
  -h | --help          显示本帮助

说明:
  * 先跑 --scenario check 确认版本、容器、Domain、依赖与残留进程；
  * 一次演示请使用**同一个 run_id**，证据会集中到
    <out-root>/release-freeze-<run_id>/ 下；
  * 本脚本不会修改 TaskPolicy、不会放宽 DDS 权限、不会静默降级到 Mock。
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --scenario) SCENARIO="${2:-}"; shift 2 ;;
    --run-id) RUN_ID="${2:-}"; shift 2 ;;
    --container) CONTAINER="${2:-}"; shift 2 ;;
    --domain) DOMAIN="${2:-}"; shift 2 ;;
    --out-root) OUT_ROOT="${2:-}"; shift 2 ;;
    --yes) ASSUME_YES=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "未知参数: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[ -z "$SCENARIO" ] && SCENARIO="check"
case "$SCENARIO" in
  check|ab|m3|three-real|f0|dds|all) ;;
  *) echo "ERROR: --scenario 取值非法: $SCENARIO" >&2; exit 2 ;;
esac

if [ -z "$RUN_ID" ]; then
  RUN_ID="freeze-$(date -u +%Y%m%dT%H%M%SZ)"
fi
EVIDENCE_DIR="${OUT_ROOT}/release-freeze-${RUN_ID}"
mkdir -p "$EVIDENCE_DIR"

RC_TOTAL=0
declare -a RESULTS=()

say()  { printf '%s\n' "$*"; }
hdr()  { printf '\n===== %s =====\n' "$*"; }
ok()   { RESULTS+=("PASS  $1"); say "  [PASS] $1"; }
bad()  { RESULTS+=("FAIL  $1"); say "  [FAIL] $1"; RC_TOTAL=1; }
skip() { RESULTS+=("NOTRUN $1"); say "  [NOT RUN] $1"; }

# ---------------------------------------------------------------- 版本门禁
git_sha()  { git -C "$WS" rev-parse HEAD 2>/dev/null || echo unknown; }
git_tree() { git -C "$WS" rev-parse 'HEAD^{tree}' 2>/dev/null || echo unknown; }

preflight_git() {
  local sha dirty
  sha="$(git_sha)"
  hdr "版本门禁"
  say "  工作区 : $WS"
  say "  分支   : $(git -C "$WS" rev-parse --abbrev-ref HEAD 2>/dev/null)"
  say "  SHA    : $sha"
  say "  tree   : $(git_tree)"
  dirty="$(git -C "$WS" status --porcelain 2>/dev/null | grep -vE '^\?\? (artifacts|logs)/' | grep -v '^\?\? user/' || true)"
  if [ -n "$dirty" ]; then
    say "  未提交改动:"
    printf '    %s\n' "$dirty" | head -10
    bad "工作区必须干净（演示版本必须可追溯）"
    return 1
  fi
  # 记录到证据目录
  {
    printf 'git_sha=%s\ngit_tree=%s\nbranch=%s\nworktree=%s\nrun_id=%s\n' \
      "$sha" "$(git_tree)" "$(git -C "$WS" rev-parse --abbrev-ref HEAD 2>/dev/null)" \
      "$WS" "$RUN_ID"
  } > "$EVIDENCE_DIR/git_version.txt"
  ok "工作区干净，SHA 已记录"
  return 0
}

preflight_container() {
  hdr "容器与 ROS 环境门禁"
  say "  容器   : $CONTAINER"
  if ! docker inspect "$CONTAINER" >/dev/null 2>&1; then
    bad "容器不存在：$CONTAINER（用 scripts/container_up.sh 或手动创建）"
    return 1
  fi
  if [ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER")" != "true" ]; then
    bad "容器未运行：$CONTAINER"
    return 1
  fi
  # 逐项探测而不是把嵌套命令塞进一个 bash -lc：嵌套引号会被内外两层
  # shell + docker exec 反复解释，实测会静默产生空输出，把"环境正常"
  # 误判成"ROS 环境不可用"。
  local distro rmw pkgs py js
  distro="$(docker exec "$CONTAINER" bash -lc \
    'source /opt/ros/jazzy/setup.bash >/dev/null 2>&1; printf %s "${ROS_DISTRO:-}"' 2>/dev/null)"
  rmw="$(docker exec "$CONTAINER" bash -lc \
    'source /opt/ros/jazzy/setup.bash >/dev/null 2>&1; printf %s "${RMW_IMPLEMENTATION:-}"' 2>/dev/null)"
  pkgs="$(docker exec "$CONTAINER" bash -lc \
    'source /opt/ros/jazzy/setup.bash >/dev/null 2>&1; cd /ws 2>/dev/null || exit 3; if [ -f install/setup.bash ]; then source install/setup.bash >/dev/null 2>&1; fi; ros2 pkg list 2>/dev/null | grep -cE "^rg_"' 2>/dev/null)"
  py="$(docker exec "$CONTAINER" bash -lc \
    'python3 -c "import sys;print(sys.version.split()[0])" 2>/dev/null' 2>/dev/null)"
  js="$(docker exec "$CONTAINER" bash -lc \
    'python3 -c "from importlib.metadata import version;print(version(chr(106)+chr(115)+chr(111)+chr(110)+chr(115)+chr(99)+chr(104)+chr(101)+chr(109)+chr(97)))" 2>/dev/null' 2>/dev/null)"
  [ -z "$distro" ] && distro="none"
  [ -z "$rmw" ] && rmw="none"
  [ -z "$py" ] && py="none"
  [ -z "$js" ] && js="none"

  say "    ROS_DISTRO : $distro"
  say "    RMW        : $rmw"
  say "    rg 包数    : ${pkgs:-0}"
  say "    python     : $py"
  say "    jsonschema : $js"
  if [ "$distro" = "none" ]; then
    bad "容器内 ROS 2 Jazzy 不可用"
    return 1
  fi
  if [ "${pkgs:-0}" -lt 4 ]; then
    bad "ROS 2 包未构建完整（期望 >=4，实际 ${pkgs:-0}）；先执行 colcon build"
    return 1
  fi
  if [ "$js" = "none" ]; then
    bad "容器内缺少 jsonschema>=4，三个模块会以退出码 2 失败关闭"
    return 1
  fi
  {
    printf 'ROS_DISTRO=%s\nRMW=%s\nrg_pkgs=%s\npython=%s\njsonschema=%s\n' \
      "$distro" "$rmw" "${pkgs:-0}" "$py" "$js"
  } > "$EVIDENCE_DIR/ros_env.txt"
  ok "ROS 2 Jazzy / ${rmw} / ${pkgs} 包可加载 / jsonschema ${js}"
  return 0
}

preflight_domain() {
  hdr "DDS Domain 冲突门禁"
  say "  在线场景 Domain : $DOMAIN"
  say "  Enforce  Domain : $ENFORCE_DOMAIN"
  say "  注意：两者必须是**两次独立实验**，不得拼接成同一次全链路"
  local nodes
  nodes="$(docker exec -e "ROS_DOMAIN_ID=${DOMAIN}" "$CONTAINER" bash -lc '
    set +u
    source /opt/ros/jazzy/setup.bash
    cd /ws 2>/dev/null || exit 0
    if [ -f install/setup.bash ]; then source install/setup.bash; fi
    timeout 8 ros2 node list 2>/dev/null | wc -l' 2>/dev/null || echo 0)"
  if [ "${nodes:-0}" -gt 0 ]; then
    bad "Domain ${DOMAIN} 上已存在 ${nodes} 个节点（可能有其他实例在使用）"
    return 1
  fi
  ok "Domain ${DOMAIN} 空闲"
  return 0
}

preflight_keystore() {
  hdr "安全材料门禁（只检查存在性，绝不打印内容）"
  local n
  n="$(docker exec "$CONTAINER" bash -lc 'find /ws/security/keystore -name permissions.xml 2>/dev/null | wc -l' 2>/dev/null || echo 0)"
  if [ "${n:-0}" -lt 1 ]; then
    bad "容器内看不到 keystore（DDS Enforce 场景将无法运行）"
    return 1
  fi
  ok "keystore 可用（${n} 个 permissions.xml，只读挂载）"
  return 0
}

preflight_policy() {
  hdr "正式策略门禁"
  if ! git -C "$WS" diff --quiet HEAD -- config/task_policy.yaml security/policies 2>/dev/null; then
    bad "config/task_policy.yaml 或 security/policies 存在未提交改动（禁止为演示放宽策略）"
    return 1
  fi
  ok "TaskPolicy 与 DDS 最小权限均未改动"
  return 0
}

# ---------------------------------------------------------------- 场景
run_ab() {
  hdr "演示一：Gateway A/B 基础闭环（受控：M1/M2 Mock）"
  local out="${EVIDENCE_DIR}/ab"
  mkdir -p "$out"
  if RG_CONTAINER="$CONTAINER" RG_DOMAIN_ID="$DOMAIN" \
     bash scripts/run_demo.sh > "$out/demo.log" 2>&1; then
    cp -a logs/demo/. "$out/" 2>/dev/null || true
    ok "A/B 闭环（ALLOW→+1 Goal；BLOCK→0 追加 Goal）"
  else
    tail -n 15 "$out/demo.log" | sed 's/^/    /'
    bad "A/B 闭环（见 $out/demo.log）"
  fi
}

m3_run_group() {  # $1=场景名 $2=命令
  local name="$1" cmd="$2" out="${EVIDENCE_DIR}/m3"
  mkdir -p "$out"
  # 关键：install/setup.bash 自身会在 `set -u` 下引用未定义变量（如 COLCON_TRACE），
  # 所以**所有** sourcing 都必须在 set +u 期间完成，之后再恢复 set -u。
  if docker exec -e "ROS_DOMAIN_ID=${DOMAIN}" "$CONTAINER" bash -lc "
        set +u
        source /opt/ros/jazzy/setup.bash
        cd /ws || exit 3
        if [ -f install/setup.bash ]; then source install/setup.bash; fi
        set -u
        $cmd" > "$out/${name}.log" 2>&1; then
    return 0
  fi
  return 1
}

run_m3() {
  hdr "演示二：真实 M3 在线闭环（域 ${DOMAIN}，普通模式）"
  local out="${EVIDENCE_DIR}/m3"
  mkdir -p "$out"
  local runa="${RUN_ID}-m3a" runb="${RUN_ID}-m3b"
  if m3_run_group drive "RUN_ID='$runa' bash scripts/m3_online_drive.sh '$runa' '/tmp/m3/$runa'"; then
    ok "M3 第一组 ON-01/02/05"
  else
    bad "M3 第一组（见 m3/drive.log）"; return
  fi
  if m3_run_group extra "bash scripts/m3_online_extra.sh '$runb' '/tmp/m3/$runb'"; then
    ok "M3 第二组 ON-03/04/06"
  else
    bad "M3 第二组（见 m3/extra.log）"; return
  fi
  docker exec "$CONTAINER" bash -lc "
    mkdir -p /ws/${EVIDENCE_DIR#${WS}/}/m3
    cp -a /tmp/m3/$runa/. /ws/${EVIDENCE_DIR#${WS}/}/m3/group-a/ 2>/dev/null || true
    cp -a /tmp/m3/$runb/. /ws/${EVIDENCE_DIR#${WS}/}/m3/group-b/ 2>/dev/null || true" >/dev/null 2>&1

  # 合并两组证据并独立复核
  local merged="${out}/merged"
  mkdir -p "$merged"
  cat "${out}/group-a/stack-a/gateway_audit.jsonl" \
      "${out}/group-b/stack-b/gateway_audit.jsonl" > "$merged/gateway_audit.jsonl" 2>/dev/null || true
  cat "${out}/group-a/stack-a/navsim_goals.jsonl" \
      "${out}/group-b/stack-b/navsim_goals.jsonl" > "$merged/navsim_goals.jsonl" 2>/dev/null || true
  local d
  for d in group-a/stack-a group-b/stack-b; do
    cp "${out}/${d}"/f0_ON*.json "${out}/${d}"/adapter_ON*.jsonl "$merged/" 2>/dev/null || true
  done
  PYTHONPATH=. python3 - "$merged" "$runb" <<'PY' 2>/dev/null || true
import json, sys, os
merged, run = sys.argv[1], sys.argv[2]
sc = []
for p in (os.path.join(merged, '..', 'group-a', 'stack-a', 'manifest.json'),
          os.path.join(merged, '..', 'group-b', 'stack-b', 'manifest.json')):
    try:
        sc += json.load(open(p, encoding='utf-8'))['scenarios']
    except Exception:
        pass
json.dump({'run_id': run, 'scenarios': sc},
          open(os.path.join(merged, 'manifest.json'), 'w'), ensure_ascii=False, indent=2)
# ON-06 只声明不变量：超时后的下游结果每次不同，不得预设
claims = {'scenarios': {
 'ON01': {'gateway_arrival': 1, 'gateway_decision': 'ALLOW',
          'gateway_reason_code': 'ALLOW_IN_POLICY', 'gateway_execution': 1,
          'navsim_goals': 1},
 'ON02': {'adapter_decision': 'ADAPTER_BLOCK', 'gateway_arrival': 0,
          'gateway_execution': 0, 'navsim_goals': 0},
 'ON03': {'adapter_decision': 'ADAPTER_BLOCK', 'gateway_arrival': 0,
          'gateway_execution': 0, 'navsim_goals': 0},
 'ON04': {'adapter_decision': 'ADAPTER_BLOCK', 'gateway_arrival': 0,
          'gateway_execution': 0, 'navsim_goals': 0},
 'ON05': {'gateway_arrival': 1, 'gateway_decision': 'BLOCK',
          'gateway_reason_code': 'OUT_OF_REGION', 'gateway_execution': 0,
          'navsim_goals': 0},
 'ON06': {'adapter_decision': 'READY_FOR_GATEWAY_SUBMISSION',
          'planner_outcome': 'PLANNER_RESULT_TIMEOUT'}}}
json.dump(claims, open(os.path.join(merged, 'report_claims.json'), 'w'),
          ensure_ascii=False, indent=2)
PY
  if ./.research-venv/bin/python scripts/verify_m3_online_evidence.py \
       --run-dir "$merged" --claims "$merged/report_claims.json" \
       --json-out "$merged/verification.json" --md-out "$merged/verification.md" \
       > "$merged/verifier.log" 2>&1; then
    ok "M3 跨层证据复核通过（见 m3/merged/verification.md）"
  else
    bad "M3 跨层证据复核失败（见 m3/merged/verifier.log）"
  fi
}

run_three_real() {
  hdr "演示三：三个真实成员模块联合调用（离线，严格身份模式）"
  local out="${EVIDENCE_DIR}/three-real"
  mkdir -p "$out"
  rm -f logs/three-real/identity_ledger.jsonl 2>/dev/null || true
  if ./.research-venv/bin/python scripts/run_three_real_online.py \
       --run-id "${RUN_ID}-three-real" --out-dir "$out" \
       > "$out/stdout.log" 2>&1; then
    local l1 l2 l3
    l1="$(./.research-venv/bin/python -c "import json;print(json.load(open('$out/summary.json'))['levels']['THREE_EXTERNAL_CALLED'])" 2>/dev/null)"
    l2="$(./.research-venv/bin/python -c "import json;print(json.load(open('$out/summary.json'))['levels']['THREE_EXTERNAL_VALIDATED'])" 2>/dev/null)"
    l3="$(./.research-venv/bin/python -c "import json;print(json.load(open('$out/summary.json'))['levels']['THREE_EXTERNAL_ONLINE_PROCEED'])" 2>/dev/null)"
    say "    THREE_EXTERNAL_CALLED          = $l1"
    say "    THREE_EXTERNAL_VALIDATED       = $l2"
    say "    THREE_EXTERNAL_ONLINE_PROCEED  = $l3"
    if [ "$l1" = "PASS" ] && [ "$l2" = "PASS" ]; then
      ok "三真实模块被真实调用并通过校验（LEVEL 3=$l3，属预期真实能力结论）"
    else
      bad "三真实模块调用/校验未达预期（$l1/$l2）"
    fi
  else
    tail -n 12 "$out/stdout.log" | sed 's/^/    /'
    bad "三真实联合运行（见 three-real/stdout.log）"
  fi
}

run_f0() {
  hdr "演示四：F0 身份防伪造（P0 强制安全反例）"
  local out="${EVIDENCE_DIR}/f0"
  mkdir -p "$out"
  if ./.research-venv/bin/python -m pytest \
       tests/unit/test_phase2_security_boundaries.py \
       tests/unit/test_f0_identity_trust_boundary.py -q \
       > "$out/p0_security.log" 2>&1; then
    ok "$(tail -n 1 "$out/p0_security.log" | tr -d '\n')"
  else
    tail -n 15 "$out/p0_security.log" | sed 's/^/    /'
    bad "F0 安全反例（见 f0/p0_security.log）"
  fi
}

run_dds() {
  hdr "演示五：DDS-Security Enforce（域 ${ENFORCE_DOMAIN}，与在线场景是两次实验）"
  local out="${EVIDENCE_DIR}/dds_enforce"
  mkdir -p "$out"
  if docker exec -e "ROS_DOMAIN_ID=${ENFORCE_DOMAIN}" "$CONTAINER" bash -lc "
        set +u
        source /opt/ros/jazzy/setup.bash
        cd /ws || exit 3
        if [ -f install/setup.bash ]; then source install/setup.bash; fi
        set -u
        python3 tests/integration/sros2_check.py --run-id '${RUN_ID}-enforce'" \
       > "$out/sros2_check.log" 2>&1; then
    docker exec "$CONTAINER" bash -lc "
      cp -a /ws/tests/evidence/'${RUN_ID}-enforce'/. /ws/${EVIDENCE_DIR#${WS}/}/dds_enforce/ 2>/dev/null || true" >/dev/null 2>&1
    ok "$(grep -m1 'SROS2 SUMMARY' "$out/sros2_check.log" | tr -d '\n')"
  else
    tail -n 15 "$out/sros2_check.log" | sed 's/^/    /'
    bad "DDS Enforce（见 dds_enforce/sros2_check.log）"
  fi
}

# ---------------------------------------------------------------- 主流程
say "RosSystem 2026-10-19 演示发布入口"
say "  run_id     : $RUN_ID"
say "  证据目录   : ${EVIDENCE_DIR}"
say "  场景       : $SCENARIO"

if [ "$SCENARIO" = "check" ]; then
  preflight_git && preflight_container && preflight_domain && \
    preflight_keystore && preflight_policy
else
  if ! { preflight_git && preflight_container && preflight_domain && \
         preflight_keystore && preflight_policy; }; then
    say ""
    say "环境门禁未通过，未开始演示。"
    printf '%s\n' "${RESULTS[@]}" > "$EVIDENCE_DIR/preflight_results.txt"
    exit 3
  fi
  if [ "$ASSUME_YES" -eq 0 ]; then
    say ""
    say "即将在容器 $CONTAINER 上执行演示场景：$SCENARIO"
    say "在线 Domain=$DOMAIN，Enforce Domain=$ENFORCE_DOMAIN（两次独立实验）"
    printf '继续？[y/N] '
    read -r answer
    case "$answer" in y|Y|yes|YES) ;; *) say "已取消。"; exit 0 ;; esac
  fi
  case "$SCENARIO" in
    ab) run_ab ;;
    m3) run_m3 ;;
    three-real) run_three_real ;;
    f0) run_f0 ;;
    dds) run_dds ;;
    all) run_ab; run_m3; run_three_real; run_f0; run_dds ;;
  esac
fi

hdr "结果汇总"
printf '  %s\n' "${RESULTS[@]}"
printf '%s\n' "${RESULTS[@]}" > "$EVIDENCE_DIR/scenario_results.txt"

{
  printf 'run_id=%s\nscenario=%s\ncontainer=%s\ndomain=%s\nenforce_domain=%s\n' \
    "$RUN_ID" "$SCENARIO" "$CONTAINER" "$DOMAIN" "$ENFORCE_DOMAIN"
  printf 'git_sha=%s\n' "$(git_sha)"
} > "$EVIDENCE_DIR/run_meta.txt"

say ""
if [ "$RC_TOTAL" -eq 0 ]; then
  say "全部场景通过。证据：${EVIDENCE_DIR}"
else
  say "存在失败场景，请查看 ${EVIDENCE_DIR} 下的日志。"
  say "回退方案见 docs/demo/DEMO_20261019_FAILURE_RECOVERY.md"
fi
exit "$RC_TOTAL"
