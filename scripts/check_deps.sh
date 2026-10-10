#!/usr/bin/env bash
# check_deps.sh -- F0 运行依赖检查（工作包 A6）。
#
# 为什么需要单独的检查
# --------------------
# F0 的契约校验与适配层依赖 `jsonschema >= 4.0`（Draft 2020-12），
# 但 `ros:jazzy` 基础镜像**不带它**。此前它只存在于某些长期使用的容器里，
# 导致：
#   * 全新成员容器根本无法运行适配层；
#   * 报错是无法定位的 `TypeError: 'NoneType' object is not callable`；
#   * `container_up.sh` 里 `rg_ensure_validation_dep || true` 把安装失败**吞掉**，
#     调用方仍以为环境就绪 —— 直到交接环节才发现跑不起来。
#
# 本脚本做**真实能力检查**，而不是"包在不在"：
#   1. `jsonschema` 可导入；
#   2. 真实具备 `Draft202012Validator`（而不是只有旧版 Draft）；
#   3. **严格 RFC 3339 检查器自检通过** —— 这是 F0 的关键能力，
#      环境缺 `rfc3339-validator` 时 `format` 会静默失效。
#
# 退出码：0 = 可用；5 = 依赖不满足（调用方必须视为环境准备失败）；
#         3 = 容器不可用。
set -uo pipefail

RG_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${RG_SCRIPT_DIR}/lib.sh" 2>/dev/null || true

RG_CONTAINER="${RG_CONTAINER:-rg_jazzy}"

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker not found; cannot verify container dependencies." >&2
  exit 3
fi
if ! docker inspect "${RG_CONTAINER}" >/dev/null 2>&1; then
  echo "ERROR: container '${RG_CONTAINER}' does not exist. Run scripts/container_up.sh first." >&2
  exit 3
fi

read -r -d '' PROBE <<'PY' || true
import sys
try:
    import jsonschema
    from jsonschema import Draft202012Validator
except ImportError as exc:
    print('MISSING_IMPORT: {0}'.format(exc))
    sys.exit(1)

if not hasattr(jsonschema, 'Draft202012Validator'):
    print('MISSING_DRAFT: installed jsonschema={0} has no Draft202012Validator'.format(
        getattr(jsonschema, '__version__', '?')))
    sys.exit(2)

sys.path.insert(0, '/ws/scripts')
try:
    import validate_team_contracts as vtc
except Exception as exc:                                    # noqa: BLE001
    print('MISSING_VALIDATOR: cannot import validate_team_contracts: {0}'.format(exc))
    sys.exit(3)

ok, detail = vtc.self_check_format_checker()
if not ok:
    print('FORMAT_CHECKER_INACTIVE: {0}'.format(detail))
    sys.exit(4)

print('OK jsonschema={0} draft2020-12=yes format-checker=active'.format(
    getattr(jsonschema, '__version__', '?')))
PY

echo "[deps] verifying F0 runtime dependencies in '${RG_CONTAINER}'..."
OUTPUT="$(docker exec -i "${RG_CONTAINER}" python3 - <<<"${PROBE}" 2>&1)"
STATUS=$?
echo "  ${OUTPUT}"

if [ "${STATUS}" -ne 0 ]; then
  cat >&2 <<EOF

ERROR: F0 运行依赖不满足（退出码 ${STATUS}）。
       契约校验与安全适配层无法运行，环境**未**准备就绪。

  必需依赖 : python3-jsonschema >= 4.0（Draft 2020-12）
  安装方式 : docker exec ${RG_CONTAINER} apt-get update && \\
             docker exec ${RG_CONTAINER} apt-get install -y python3-jsonschema

  若当前环境确实无法安装（例如无网络），请显式设置
    RG_SKIP_DEP_CHECK=1
  以跳过检查 —— 但此时**不得**声称 F0 环境已就绪。
EOF
  exit 5
fi

echo "[deps] OK"
exit 0
