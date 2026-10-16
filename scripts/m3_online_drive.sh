#!/usr/bin/env bash
# m3_online_drive.sh -- M3 真实模块在线联调驱动器（在 Jazzy 容器内运行）
#
# 目的
# ----
# 在**同一**受控栈生命周期内依次执行需要存活栈的在线场景，使每个场景的
# Planner / Gateway / NavigationSim 证据都落在同一次运行里，可交叉复核。
#
# 安全边界
# --------
# * 只启动本项目既有节点（operator_node / navigation_sim / security_gateway）。
# * 不按名称 pkill，不清理他人容器，只终止本脚本自己启动的进程组。
# * 不修改 config/task_policy.yaml（Gateway 权威策略）与 DDS 权限。
# * 每个场景使用独立 request_id，便于逐条关联与查重。
# * 不重试超时请求，不为超时请求更换 request_id。
set -uo pipefail

# 开启作业控制：让每个后台作业各自成为进程组组长。
# 为什么必须这样做：`ros2 run` 会 fork 出真正的节点进程，其 PID 与后台作业
# 的 PID 不同。只 kill 作业 PID 会把节点留成孤儿（实测遗留 3 个）。开启 `set -m`
# 后可用 `kill -- -PGID` 终止**整个作业进程组**，节点与包装脚本一并回收。
set -m

RUN_ID="${1:?usage: m3_online_drive.sh <run_id>}"
OUT="${2:-/tmp/m3_online}"
WS=/ws
CFG="${3:-config/team_modules.member3.real.yaml}"

# 第一组场景写入独立子目录：否则第二组脚本会覆盖同一 run 的
# gateway_audit.jsonl / navsim_goals.jsonl，导致跨层证据丢失
# （本组与 m3_online_extra.sh 必须各写各的目录，之后合并）。
OUT="${OUT}/stack-a"
mkdir -p "${OUT}"
AUDIT="${OUT}/gateway_audit.jsonl"
JOURNAL="${OUT}/navsim_goals.jsonl"
: > "${AUDIT}"
: > "${JOURNAL}"

PIDS=()
cleanup() {
  local pid rc=0
  # 先 TERM 整个进程组（负 PID = 进程组），给节点优雅退出机会
  for pid in "${PIDS[@]:-}"; do
    if [ -n "${pid}" ]; then
      kill -TERM "-${pid}" 2>/dev/null || kill -TERM "${pid}" 2>/dev/null || true
    fi
  done
  sleep 2
  # 仍未退出的进程组用 KILL 收尾；只作用于本脚本启动的进程组
  for pid in "${PIDS[@]:-}"; do
    if [ -n "${pid}" ] && kill -0 "-${pid}" 2>/dev/null; then
      kill -KILL "-${pid}" 2>/dev/null || true
    fi
  done
  return ${rc}
}

verify_no_stray() {
  # 只**统计**本项目节点，不做按名称扫描终止（-- 终止只按 PID/PGID）
  local n
  n="$(ps -eo cmd | grep -E 'rg_gateway|rg_demo_nodes' | grep -v grep | wc -l)"
  echo "STRAY_RG_PROCS=${n}"
  [ "${n}" -eq 0 ]
}
trap cleanup EXIT

cd "${WS}" || exit 1
# ROS 的 setup.bash 会引用未定义变量，必须在关闭 `set -u` 的情况下 source，
# 否则 `set -u` 会让环境准备直接失败（这不是脚本缺陷，是 ROS 脚本的既有行为）。
set +u
# shellcheck disable=SC1091
source /opt/ros/jazzy/setup.bash
# shellcheck disable=SC1091
source install/setup.bash
set -u

echo "=== 环境 ==="
echo "ROS_DISTRO=${ROS_DISTRO} RMW=${RMW_IMPLEMENTATION} ROS_DOMAIN_ID=${ROS_DOMAIN_ID}"
echo "RUN_ID=${RUN_ID}"
echo "OUT=${OUT}"
echo "CONFIG=${CFG}"
python3 --version

echo
echo "=== 启动受控栈 ==="
ros2 run rg_demo_nodes operator_node --ros-args -p task_id:=patrol_a_001 \
  >"${OUT}/operator.log" 2>&1 &
PIDS+=($!)
ros2 run rg_demo_nodes navigation_sim --ros-args -p record_path:="${JOURNAL}" \
  >"${OUT}/navsim.log" 2>&1 &
PIDS+=($!)
ros2 run rg_gateway security_gateway --ros-args \
  -p policy_path:="${WS}/config/task_policy.yaml" -p audit_log_path:="${AUDIT}" \
  >"${OUT}/gateway.log" 2>&1 &
PIDS+=($!)

wait_marker() {
  local file="$1" marker="$2" tries="${3:-150}" i
  for (( i=0; i<tries; i++ )); do
    grep -q -- "${marker}" "${file}" 2>/dev/null && return 0
    sleep 0.2
  done
  return 1
}

READY=1
wait_marker "${OUT}/operator.log" OPERATOR_READY 150 || { echo "  FAIL operator"; READY=0; }
wait_marker "${OUT}/navsim.log" NAVSIM_READY 150 || { echo "  FAIL navsim"; READY=0; }
wait_marker "${OUT}/gateway.log" GATEWAY_READY 150 || { echo "  FAIL gateway"; READY=0; }
echo "READY=${READY}"
if [ "${READY}" -ne 1 ]; then echo "栈未就绪，中止"; exit 3; fi

echo
echo "=== Action 服务可用性 ==="
timeout 20 ros2 action list -t 2>/dev/null || true

IN=/tmp/m3_online_inputs
mkdir -p "${IN}"

# ---------------------------------------------------------------- 输入构造
python3 - "${IN}" <<'PY'
import json, os, sys
out = sys.argv[1]
base = json.load(open('docs/interfaces/examples/module_input_valid.json'))
run_id = os.environ.get('RUN_ID', 'm3online')
# 每个场景必须使用**唯一** request_id：复用同一 request_id 会让 Gateway 审计
# 与 NavigationSim journal 的条目相互混串，使跨层复核无法区分场景
# （本工具的 ORPHAN/串单检查正是为发现这类问题而存在）。
specs = {
    'on01': ('on01-legal-allow-' + run_id, 1.5, 1.5),
    'on02': ('on02-oor-block-' + run_id, 9.0, 9.0),
    'on05': ('on05-gateway-authority-' + run_id, 9.0, 9.0),
}
for name, (rid, x, y) in specs.items():
    d = dict(base)
    d['run_id'] = run_id
    d['request_id'] = rid
    d['candidate_action'] = dict(base['candidate_action'])
    d['candidate_action']['target'] = {'frame_id': 'map', 'x': x, 'y': y, 'z': 0.0}
    with open(os.path.join(out, name + '.json'), 'w', encoding='utf-8') as fh:
        json.dump(d, fh, ensure_ascii=False, indent=2)
print('inputs written to', out)
PY

# ON-05 专用 TEST_ONLY 策略：允许区域外扩到 0..10，使 M3 对 (9,9) 建议允许
cat > "${IN}/task_policy_TEST_ONLY_wide.yaml" <<'YAML'
# TEST_ONLY -- 仅供 ON-05 在线联调，不得用于生产或作为 Gateway 策略。
# 目的：让上游 M3 认为 (9,9) 合法，从而证明 Gateway 仍保留独立权威拒绝权。
task_id: patrol_a_001
policy_version: "1.0-TEST-ONLY-wide"
active: true
coordinate_frame: map
allowed_region: {x_min: 0.0, x_max: 10.0, y_min: 0.0, y_max: 10.0}
max_requests_per_minute: 10
YAML

python3 - "${CFG}" "${IN}/on05_config.yaml" "${IN}/task_policy_TEST_ONLY_wide.yaml" <<'PY'
import sys, yaml
src, dst, policy = sys.argv[1], sys.argv[2], sys.argv[3]
doc = yaml.safe_load(open(src, encoding='utf-8'))
cmd = list(doc['modules']['task_risk']['command'])
out, i = [], 0
while i < len(cmd):
    if cmd[i] == '--policy' and i + 1 < len(cmd):
        out += ['--policy', policy]
        i += 2
        continue
    out.append(cmd[i])
    i += 1
if '--policy' not in out:
    out += ['--policy', policy]
doc['modules']['task_risk']['command'] = out
doc.setdefault('adapter', {})['log_path'] = '/tmp/m3_online/adapter_on05.jsonl'
with open(dst, 'w', encoding='utf-8') as fh:
    yaml.safe_dump(doc, fh, allow_unicode=True)
print('ON-05 TEST_ONLY command ->', out)
PY

# ---------------------------------------------------------------- 场景运行
run_scenario() {
  local cid="$1" input="$2" note="$3" cfg_override="${4:-}"
  local use_cfg="${CFG}"
  [ -n "${cfg_override}" ] && use_cfg="${cfg_override}"
  echo
  echo "########## SCENARIO ${cid} :: ${note} ##########"
  echo "--- BEGIN_F0 ${cid} ---"
  timeout 300 python3 scripts/team_demo.py \
      --input "${input}" --config "${use_cfg}" --online \
      --log "${OUT}/adapter_${cid}.jsonl" \
      >"${OUT}/f0_${cid}.json" 2>"${OUT}/f0_${cid}.err"
  echo "F0_EXIT_${cid}=$?"
  echo "--- END_F0 ${cid} ---"
  python3 - "${OUT}" "${cid}" <<'PY'
import json, sys
out, cid = sys.argv[1], sys.argv[2]
try:
    d = json.load(open('%s/f0_%s.json' % (out, cid), encoding='utf-8'))
except Exception as exc:
    print('  (F0 stdout 非 JSON:', exc, ')')
    print('  stderr head:', open('%s/f0_%s.err' % (out, cid), encoding='utf-8',
                               errors='replace').read()[:300])
    raise SystemExit
print('  decision   :', d.get('decision'))
print('  reason_code:', d.get('reason_code'))
for m in (d.get('modules') or []):
    print('    module=%-15s mode=%-9s exit=%s status=%s schema_ok=%s' % (
        m.get('module'), m.get('mode'), m.get('exit_code'), m.get('status'),
        m.get('schema_ok')))
on = d.get('online') or {}
if on:
    print('  online     : enabled=%s outcome=%s planner_exit=%s' % (
        on.get('enabled'), on.get('outcome'), on.get('planner_exit_code')))
    pr = on.get('planner_result')
    if isinstance(pr, dict):
        print('    planner_result: status_code=%s success=%s goal_id=%s' % (
            pr.get('status_code'), pr.get('success'), pr.get('goal_id')))
    if on.get('detail'):
        print('    online_detail:', str(on.get('detail'))[:160])
PY
  echo "--- journal 行数: $(wc -l < "${JOURNAL}" 2>/dev/null || echo 0) ---"
}

# 权威清单：ON-01/02/05（在场景执行前写入）
python3 scripts/m3_online_write_manifest.py "${OUT}" "${RUN_ID}" "$(python3 -c "
import json, sys
print(json.dumps([
  {'cid':'ON01','request_id':'on01-legal-allow-'+sys.argv[1],'run_id':sys.argv[1],'expected':'ALLOW_AND_EXECUTE'},
  {'cid':'ON02','request_id':'on02-oor-block-'+sys.argv[1],'run_id':sys.argv[1],'expected':'M3_BLOCK_NO_SUBMIT'},
  {'cid':'ON05','request_id':'on05-gateway-authority-'+sys.argv[1],'run_id':sys.argv[1],'expected':'M3_ALLOW_GATEWAY_BLOCK'},
], ensure_ascii=False))
" "${RUN_ID}")"

export RUN_ID
run_scenario ON01 "${IN}/on01.json" "合法任务：M3 ALLOW_RECOMMENDED -> Gateway ALLOW -> NavigationSim +1 Goal"
run_scenario ON02 "${IN}/on02.json" "M3 越界阻断：BLOCK_RECOMMENDED -> ADAPTER_BLOCK -> 不提交"
run_scenario ON05 "${IN}/on05.json" "Gateway 独立权威：M3 建议允许但 Gateway 越界拒绝" "${IN}/on05_config.yaml"

echo
echo "=== 栈关闭 ==="
cleanup
trap - EXIT
sleep 1
verify_no_stray || echo "WARNING: 仍有本项目节点存活，需人工核对"
echo "=== 汇总 ==="
echo "gateway_audit.jsonl 行数: $(wc -l < "${AUDIT}" 2>/dev/null || echo 0)"
echo "navsim_goals.jsonl  行数: $(wc -l < "${JOURNAL}" 2>/dev/null || echo 0)"
echo "DONE ${RUN_ID}"
