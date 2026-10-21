#!/usr/bin/env bash
# int_online_downstream_check.sh -- 受限集成第 9 项：真实 ROS 2 下游在线核查
#
# 解决什么问题
# ------------
# 旧验收只检查 F0 返回 JSON 里的字段就宣称"Gateway 没收到请求"。
# 这不能区分四种情况：
#   1) 请求确实没到达；2) Gateway 根本没启动；3) 日志配置错；4) 审计写入失败。
#
# 本脚本在**同一次栈生命周期**里同时做：
#   NEG  三真实 External 严格配置 -> F0 应 ADAPTER_BLOCK，Planner 不启动；
#   POS  受控合法请求（M3 真实、M1/M2 mock）-> Gateway ALLOW 且 NavSim +1 Goal。
# POS 是**审计可用性的正向对照**：只有它成功了，NEG 的"0 到达"才有意义。
#
# 安全边界
# --------
# * 只启动本项目既有节点；不按名称 pkill；只回收本脚本启动的进程组。
# * 不修改 config/task_policy.yaml、DDS 权限、Gateway 规则。
# * NEG 使用正式三真实配置，不替换、不放宽。
#
# 注意（历史踩坑）
# ----------------
# * source ROS setup.bash 时必须临时关闭 nounset，否则环境脚本会因未定义变量崩溃；
# * 不要把复杂引号嵌进多层 bash -lc，变量会静默为空。
set -uo pipefail
set -m

RUN_ID="${1:?usage: int_online_downstream_check.sh <run_id> <out_dir>}"
OUT="${2:?usage: int_online_downstream_check.sh <run_id> <out_dir>}"
WS=/ws

AUDIT="${OUT}/gateway_audit.jsonl"
JOURNAL="${OUT}/navsim_goals.jsonl"
mkdir -p "${OUT}"
: > "${AUDIT}"
: > "${JOURNAL}"

PIDS=()
cleanup() {
  local pid
  for pid in "${PIDS[@]:-}"; do
    [ -n "${pid}" ] && { kill -TERM "-${pid}" 2>/dev/null || kill -TERM "${pid}" 2>/dev/null || true; }
  done
  sleep 2
  for pid in "${PIDS[@]:-}"; do
    [ -n "${pid}" ] && { kill -KILL "-${pid}" 2>/dev/null || true; }
  done
}
trap cleanup EXIT

start_node() {
  "$@" &
  PIDS+=("$!")
}

echo "########## 启动真实下游栈 ##########"
start_node ros2 run rg_demo_nodes operator_node --ros-args -p task_id:=patrol_a_001 > "${OUT}/operator.log" 2>&1
start_node ros2 run rg_demo_nodes navigation_sim --ros-args -p record_path:="${JOURNAL}" > "${OUT}/navsim.log" 2>&1
start_node ros2 run rg_gateway security_gateway \
  --ros-args -p policy_path:="${WS}/config/task_policy.yaml" \
             -p audit_log_path:="${AUDIT}" > "${OUT}/gateway.log" 2>&1

# 等 Action server 真正可用：只认 GATEWAY_READY 标记，不靠 sleep 猜。
wait_ready() {
  local path="$1" pattern="$2" name="$3" limit="${4:-40}"
  for _ in $(seq 1 "${limit}"); do
    if grep -q "${pattern}" "${path}" 2>/dev/null; then
      echo "  [READY] ${name}"
      return 0
    fi
    sleep 0.5
  done
  echo "  [NOT_READY] ${name}（{path} 未出现 ${pattern}）" >&2
  return 1
}
wait_ready "${OUT}/gateway.log" 'GATEWAY_READY' 'security_gateway' 40 || true
wait_ready "${OUT}/navsim.log" 'NAVSIM_READY' 'navigation_sim' 40 || true

counters() {
  grep -o 'GATEWAY_COUNTERS .*' "${OUT}/gateway.log" 2>/dev/null | tail -1
}

echo
echo "########## NEG：三真实 External 严格配置 ##########"
echo "  启动前 counters: $(counters)"
ADAPTER_ARGS=(python3 scripts/team_demo.py --online
              --config config/team_modules.three-real.yaml
              --planner-timeout 3)
NEG_OUT="${OUT}/neg_three_real_f0.json"
set +e
"${ADAPTER_ARGS[@]}" > "${NEG_OUT}" 2> "${OUT}/neg_three_real_f0.err"
NEG_RC=$?
set -e
NEG_AUDIT=$(wc -l < "${AUDIT}" 2>/dev/null || echo 0)
NEG_JOURNAL=$(wc -l < "${JOURNAL}" 2>/dev/null || echo 0)
sleep 1
echo "  adapter rc=${NEG_RC}"
python3 - "${NEG_OUT}" <<'PY' 2>/dev/null || true
import json, sys
try:
    d = json.load(open(sys.argv[1], encoding='utf-8'))
except Exception:
    print('  F0 输出无法解析'); raise SystemExit
print('  F0 decision:', d.get('decision'), d.get('reason_code'))
for m in d.get('modules') or []:
    print('    {0:<16} mode={1:<8} exit={2} status={3} schema_ok={4}'.format(
        m.get('module'), m.get('mode'), m.get('exit_code'), m.get('status'), m.get('schema_ok')))
online = d.get('online') or {}
print('  planner_started:', online.get('planner_started'),
      '| outcome:', online.get('outcome'))
PY
echo "  Gateway 审计行数: ${NEG_AUDIT} | NavSim journal 行数: ${NEG_JOURNAL}"
echo "  启动后 counters: $(counters)"

echo
echo "########## POS：受控合法请求（审计正向对照） ##########"
POS_IN="${OUT}/pos_envelope.json"
python3 - "${POS_IN}" <<'PY'
import json, sys
envelope = {
    'schema_version': '1.0.0-proposed',
    'run_id': 'downstream-pos-{0}'.format(sys.argv[1]),
    'request_id': 'pos-audit-control',
    'candidate_action': {
        'action_resource': '/rg/guarded_navigate',
        'operation': 'ACTION_SEND_GOAL',
        'task_id': 'patrol_a_001',
        'target': {'frame_id': 'map', 'x': 1.0, 'y': 1.0, 'z': 0.0},
    },
    'f0_control': {
        'comm_risk': {'scenario': 'normal'},
        'identity_trust': {'scenario': 'authorized'},
        'task_risk': {'scenario': 'allow'},
    },
}
json.dump(envelope, open(sys.argv[1], 'w', encoding='utf-8'), ensure_ascii=False)
PY
set +e
python3 scripts/team_demo.py --online \
    --config config/team_modules.member3.real.yaml \
    --input "${POS_IN}" \
    --planner-timeout 8 \
    > "${OUT}/pos_control_f0.json" 2> "${OUT}/pos_control_f0.err"
POS_RC=$?
set -e
sleep 2
echo "  adapter rc=${POS_RC}"
python3 - "${OUT}/pos_control_f0.json" <<'PY' 2>/dev/null || true
import json, sys
try:
    d = json.load(open(sys.argv[1], encoding='utf-8'))
except Exception:
    print('  F0 输出无法解析'); raise SystemExit
print('  F0 decision:', d.get('decision'), d.get('reason_code'))
online = d.get('online') or {}
print('  planner outcome:', online.get('outcome'))
PY
POS_AUDIT=$(wc -l < "${AUDIT}" 2>/dev/null || echo 0)
POS_JOURNAL=$(wc -l < "${JOURNAL}" 2>/dev/null || echo 0)
echo "  Gateway 审计行数: ${POS_AUDIT} | NavSim journal 行数: ${POS_JOURNAL}"
echo "  结束时 counters: $(counters)"

echo
echo "########## 结论数据 ##########"
python3 - "${OUT}" "${NEG_AUDIT}" "${NEG_JOURNAL}" "${POS_AUDIT}" "${POS_JOURNAL}" <<'PY'
import json, sys
out, neg_a, neg_j, pos_a, pos_j = sys.argv[1:6]
summary = {
    'contract': 'limited-online-downstream-check/1',
    'negative': {'adapter': 'config/team_modules.three-real.yaml',
                 'gateway_audit_rows_after_neg': int(neg_a),
                 'navsim_goal_rows_after_neg': int(neg_j)},
    'positive': {'adapter': 'config/team_modules.member3.real.yaml',
                 'gateway_audit_rows_after_pos': int(pos_a),
                 'navsim_goal_rows_after_pos': int(pos_j)},
    'interpretation': ('POS 证明审计与 journal 在本栈可写可读；'
                       '只有 POS 成立时，NEG 的 0 到达才可归因为"未提交"而非"网关没跑/日志坏了"。'),
}
json.dump(summary, open(out + '/downstream_summary.json', 'w', encoding='utf-8'),
          ensure_ascii=False, indent=2)
print(json.dumps(summary, ensure_ascii=False, indent=2))
PY
echo "DONE_DOWNSTREAM"
