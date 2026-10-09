#!/usr/bin/env bash
# run_acceptance_and_publish.sh -- 受控的"测试 → 证据 → 脱敏 → 校验 → 发布"一条龙（Task A4）。
#
# 设计要点
# --------
# * 只有**显式执行正式验收**才会触发发布；临时调试请用 --no-publish 或直接跑各测试脚本。
# * 发布前一定要通过：证据包校验（Schema/哈希/证据引用）+ 脱敏 + 安全扫描。
# * 任一环节失败都返回非零，并且**绝不删除本地验收结果**，而是给出重试命令。
# * 不修改当前工作分支，不 force push，不动任何基线标签。
#
# 用法：
#   scripts/run_acceptance_and_publish.sh --suite base
#   scripts/run_acceptance_and_publish.sh --suite sros2 --phase M2 --security-mode enforce
#   scripts/run_acceptance_and_publish.sh --suite dynamic --phase M3 --security-mode enforce
#   scripts/run_acceptance_and_publish.sh --suite redaction --no-publish
set -uo pipefail

RG_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RG_WS="$(cd "${RG_SCRIPT_DIR}/.." && pwd)"
cd "${RG_WS}"

SUITE=""
PHASE=""
SECURITY_MODE="disabled"
RUN_ID=""
PUBLISH=1
REMOTE="origin"
BRANCH="evidence/m3"
CONTAINER="${RG_CONTAINER:-rg_jazzy}"

usage() {
  sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  exit 2
}

while [ $# -gt 0 ]; do
  case "$1" in
    --suite) SUITE="${2:-}"; shift 2 ;;
    --phase) PHASE="${2:-}"; shift 2 ;;
    --security-mode) SECURITY_MODE="${2:-}"; shift 2 ;;
    --run-id) RUN_ID="${2:-}"; shift 2 ;;
    --remote) REMOTE="${2:-}"; shift 2 ;;
    --branch) BRANCH="${2:-}"; shift 2 ;;
    --no-publish) PUBLISH=0; shift ;;
    -h|--help) usage ;;
    *) echo "ERROR: 未知参数 $1" >&2; usage ;;
  esac
done

[ -n "${SUITE}" ] || { echo "ERROR: 必须指定 --suite" >&2; usage; }
[ -n "${PHASE}" ] || PHASE="$(echo "${SUITE}" | tr '[:lower:]' '[:upper:]')"

# 每个套件对应的真实执行命令（必须是真的跑测试，不能是空壳）
case "${SUITE}" in
  base)        CMD=(./scripts/run_all.sh) ;;
  start_system) CMD=(python3 tests/integration/start_system_check.py) ;;
  build_guard) CMD=(python3 tests/integration/build_guard_check.py) ;;
  redaction)   CMD=(python3 tests/integration/redaction_check.py) ;;
  reliability) CMD=(docker exec "${CONTAINER}" bash -lc
                   'cd /ws && source /opt/ros/jazzy/setup.bash && source install/setup.bash && python3 tests/integration/reliability_check.py') ;;
  sros2)       CMD=(docker exec "${CONTAINER}" bash -lc
                   'cd /ws && source /opt/ros/jazzy/setup.bash && source install/setup.bash && python3 tests/integration/sros2_check.py') ;;
  dynamic)     CMD=(docker exec "${CONTAINER}" bash -lc
                   'cd /ws && source /opt/ros/jazzy/setup.bash && source install/setup.bash && python3 tests/integration/dynamic_policy_check.py') ;;
  *) echo "ERROR: 未知套件 ${SUITE}（可选 base|start_system|build_guard|redaction|reliability|sros2|dynamic）" >&2; exit 2 ;;
esac

[ -n "${RUN_ID}" ] || RUN_ID="${PHASE,,}_$(date -u +%Y%m%dT%H%M%SZ)"

echo "=============================================================="
echo " 受控验收流程"
echo "   套件     : ${SUITE}"
echo "   阶段     : ${PHASE}"
echo "   安全模式 : ${SECURITY_MODE}"
echo "   run_id   : ${RUN_ID}"
echo "   发布     : $([ "${PUBLISH}" -eq 1 ] && echo "是 -> ${REMOTE}/${BRANCH}" || echo "否（--no-publish）")"
echo "=============================================================="

BEFORE_LIST="$(mktemp)"
AFTER_LIST="$(mktemp)"
ls -1 tests/evidence 2>/dev/null | sort > "${BEFORE_LIST}" || true

echo "[1/6] 真实执行测试套件 ..."
if ! "${CMD[@]}" 2>&1 | tee "logs/acceptance_${SUITE}_${RUN_ID}.log" | tail -25; then
  echo "ERROR: 测试套件失败 —— 不导出、不发布。原始日志保留在 logs/acceptance_${SUITE}_${RUN_ID}.log" >&2
  echo "       重试命令: scripts/run_acceptance_and_publish.sh --suite ${SUITE} --run-id ${RUN_ID}" >&2
  rm -f "${BEFORE_LIST}" "${AFTER_LIST}"
  exit 1
fi

echo "[2/6] 收集本次运行产生的证据目录 ..."
ls -1 tests/evidence 2>/dev/null | sort > "${AFTER_LIST}" || true
NEW_DIRS="$(comm -13 "${BEFORE_LIST}" "${AFTER_LIST}" || true)"
rm -f "${BEFORE_LIST}" "${AFTER_LIST}"
if [ -z "${NEW_DIRS}" ]; then
  echo "WARN: 本次运行没有产生新的 tests/evidence 目录，无法形成结构化证据。" >&2
  echo "      不发布（避免用旧证据冒充本次结果）。" >&2
  exit 1
fi
echo "${NEW_DIRS}" | sed 's/^/        + tests\/evidence\//'

echo "[3/6] 导出验收证据包 ..."
EXPORT_ARGS=(--phase "${PHASE}" --status PASS --run-id "${RUN_ID}"
             --security-mode "${SECURITY_MODE}" --outdir artifacts/acceptance/exports)
for dir in ${NEW_DIRS}; do
  summary="tests/evidence/${dir}/summary.json"
  [ -f "${summary}" ] || continue
  suite_name="$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('suite') or '')" "${summary}" 2>/dev/null || true)"
  if [ "${suite_name}" = "sros2" ] || [ "${suite_name}" = "dynamic" ]; then
    EXPORT_ARGS+=(--security-summary "${summary}")
  else
    EXPORT_ARGS+=(--scenario-summary "${summary}")
  fi
done
[ -f "logs/acceptance_${SUITE}_${RUN_ID}.log" ] && EXPORT_ARGS+=(--include "logs/acceptance_${SUITE}_${RUN_ID}.log")

if ! python3 scripts/export_acceptance.py "${EXPORT_ARGS[@]}"; then
  echo "ERROR: 证据导出失败 —— 不发布。测试结果仍保留在 tests/evidence/。" >&2
  exit 1
fi

echo "[4/6] 校验证据包 ..."
if ! python3 scripts/verify_acceptance.py "artifacts/acceptance/exports/${RUN_ID}"; then
  echo "ERROR: 证据包未通过校验 —— 不发布。包保留在 artifacts/acceptance/exports/${RUN_ID}。" >&2
  exit 1
fi

if [ "${PUBLISH}" -eq 0 ]; then
  echo "[5/6] 已指定 --no-publish，跳过发布。"
  echo "[6/6] 完成（未发布）。证据包: artifacts/acceptance/exports/${RUN_ID}"
  exit 0
fi

echo "[5/6] 脱敏 + 安全扫描 + 发布 ..."
if python3 scripts/publish_acceptance.py --run-id "${RUN_ID}" \
     --remote "${REMOTE}" --branch "${BRANCH}"; then
  echo "[6/6] 发布完成。"
  echo "      证据地址: https://github.com/godzwp117/RosSystem/tree/${BRANCH}/artifacts/acceptance/published/${RUN_ID}"
  exit 0
fi

echo "ERROR: 发布未完成（网络/权限/安全扫描）。" >&2
echo "       本地验收结果与待发布产物均已保留，未被删除。" >&2
echo "       排查后重试: python3 scripts/publish_acceptance.py --run-id ${RUN_ID} --remote ${REMOTE} --branch ${BRANCH}" >&2
exit 1
