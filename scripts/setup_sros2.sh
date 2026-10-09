#!/usr/bin/env bash
# setup_sros2.sh -- 生成 SROS 2 keystore 与各角色 enclave（幂等）
#
# 步骤：
#   1. 预检策略文件（必须是合法 XML，且**不得含 XML 注释** —— 见下方说明）
#   2. 创建/复用 keystore（密钥只落在 security/keystore/，已被 .gitignore 排除）
#   3. 依策略为四个业务角色 + 一个"无授权测试身份"生成独立证书/私钥/permissions.xml
#   4. 调用 scripts/verify_sros2_permissions.py **核对生成结果确实最小权限**
#   5. 收紧密钥文件权限
#
# 两个实测得到的硬约束（都不是推测）：
#   * sros2 0.13.6 的 `generate_artifacts` 只要策略文件里存在 XML 注释，就会以
#     "failed to validate namespace: error not set" 失败；更危险的是它**在此之前
#     已经写好了 enclave 密钥与 permissions.xml，而内容是内置默认策略（rt/* 全开）**。
#     因此本脚本显式拒绝带注释的策略，并要求生成后独立复核。
#   * 安全模式使用独立的 DDS domain（默认 43），与普通模式的 42 隔离，
#     避免共用 ROS daemon 缓存或发现结果造成污染。
#
# 本脚本不修改宿主系统，也不重建容器。密钥绝不入库。
set -uo pipefail

RG_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${RG_SCRIPT_DIR}/lib.sh"

KEYSTORE_CTR="${RG_CONTAINER_WS}/security/keystore"
POLICY_CTR="${RG_CONTAINER_WS}/security/policies/minimal_permissions.xml"
POLICY_HOST="${RG_WS_HOST}/security/policies/minimal_permissions.xml"
KEYSTORE_HOST="${RG_WS_HOST}/security/keystore"
ENCLAVES="/operator /planner /gateway /navsim /task_admin /unauthorized"
SECURE_DOMAIN_ID="${RG_SECURE_DOMAIN_ID:-43}"

if [ ! -f "${POLICY_HOST}" ]; then
  echo "ERROR: 策略文件不存在: ${POLICY_HOST}" >&2
  exit 3
fi

# --- 预检：合法 XML 且不含注释 -------------------------------------------------
python3 - "${POLICY_HOST}" <<'PY' || exit 3
import re, sys, xml.etree.ElementTree as ET
path = sys.argv[1]
text = open(path, encoding='utf-8').read()
try:
    ET.fromstring(text)
except ET.ParseError as exc:
    print('ERROR: 策略 XML 解析失败: {0}'.format(exc), file=sys.stderr)
    sys.exit(3)
comments = len(re.findall(r'<!--', text))
if comments:
    print('ERROR: 策略文件含 {0} 处 XML 注释。sros2 0.13.6 遇到注释即校验失败，'.format(comments), file=sys.stderr)
    print('       且会先写出"默认全开"的 permissions.xml，属于危险回退。', file=sys.stderr)
    print('       请把说明移到 security/policies/README.md。', file=sys.stderr)
    sys.exit(3)
print('[sros2] 策略预检通过：合法 XML、无注释、无危险回退风险')
PY

# --- keystore：domain 不一致时重建（governance 的 domain 在创建时固化）---------
NEED_RECREATE=0
if [ -d "${KEYSTORE_HOST}" ] && [ -f "${KEYSTORE_HOST}/public/ca.cert.pem" ]; then
  if ! grep -q "<id>${SECURE_DOMAIN_ID}</id>" "${KEYSTORE_HOST}/enclaves/governance.xml" 2>/dev/null; then
    echo "[sros2] 现有 keystore 的 governance 不是 domain ${SECURE_DOMAIN_ID}，将重建 keystore"
    NEED_RECREATE=1
  fi
else
  NEED_RECREATE=1
fi

if [ "${NEED_RECREATE}" -eq 1 ]; then
  echo "[sros2] 创建 keystore（ROS_DOMAIN_ID=${SECURE_DOMAIN_ID}）: ${KEYSTORE_CTR}"
  rg_ros "
    rm -rf '${KEYSTORE_CTR}'
    ROS_DOMAIN_ID=${SECURE_DOMAIN_ID} ros2 security create_keystore '${KEYSTORE_CTR}' || exit 1
  " || { echo "ERROR: keystore 创建失败" >&2; exit 1; }
else
  echo "[sros2] 复用现有 keystore（domain ${SECURE_DOMAIN_ID}）"
fi

echo "[sros2] 为 ${ENCLAVES} 生成密钥与权限 ..."
rg_ros "
  ROS_DOMAIN_ID=${SECURE_DOMAIN_ID} ros2 security generate_artifacts \
    -k '${KEYSTORE_CTR}' \
    -e ${ENCLAVES} \
    -p '${POLICY_CTR}'
" || { echo "ERROR: generate_artifacts 失败" >&2; exit 1; }

echo "[sros2] 核对生成结果是否为最小权限 ..."
python3 "${RG_SCRIPT_DIR}/verify_sros2_permissions.py" \
  --keystore "${KEYSTORE_HOST}" \
  --policy "${POLICY_HOST}" \
  --domain "${SECURE_DOMAIN_ID}"
status=$?
if [ "${status}" -ne 0 ]; then
  echo "ERROR: 权限核对失败（很可能已静默回退为默认全开策略）—— 不要据此宣称安全已生效。" >&2
  exit "${status}"
fi

echo "[sros2] 收紧密钥文件权限 ..."
chmod 700 "${KEYSTORE_HOST}" 2>/dev/null || true
chmod -R go-rwx "${KEYSTORE_HOST}" 2>/dev/null || true
rg_ros "chmod -R go-rwx '${KEYSTORE_CTR}'" >/dev/null 2>&1 || true

echo "[sros2] 完成。安全 domain=${SECURE_DOMAIN_ID}；enclave 列表:"
ls -1 "${KEYSTORE_HOST}/enclaves" 2>/dev/null | sed 's/^/         /'
echo "[sros2] 私钥仅位于 ${KEYSTORE_HOST}（已被 .gitignore 排除，禁止入库/上传）"
exit 0
