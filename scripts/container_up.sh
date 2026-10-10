#!/usr/bin/env bash
# Create/start the ROS 2 Jazzy container used by every other script.
#
# The development host is Ubuntu 22.04 (jammy); ROS 2 Jazzy is only packaged for
# Ubuntu 24.04 (noble), so the ROS environment lives in a container and this
# workspace is bind-mounted into it. Nothing is installed on the host.
#
# F0 变更（任务 A / GAP-01）
# -------------------------
# 旧实现在容器已存在时**直接复用或启动**，不校验该容器绑定的是哪个宿主工作区。
# 后果：成员二沿用了成员一的容器名，脚本输出成功，实际却在成员一的代码上构建运行。
#
# 现在复用前必须逐项核对：工作区挂载（源与目标）、工作目录、镜像、
# 创建时固化的 ROS_DOMAIN_ID、RMW 实现、运行状态。任何一项不符即失败退出，
# 并打印"期望 / 实际 / 容器名 / 处理建议"。
#
# 本脚本**绝不**删除、重建或修改一个已存在的容器 —— 那可能是其他成员的运行环境。
#
# 用法：
#   scripts/container_up.sh                      # 默认容器（rg_jazzy / 42）
#   RG_MEMBER=2 scripts/container_up.sh          # 成员二 -> rg_member2 / 52
#   RG_CONTAINER=rg_m2 ROS_DOMAIN_ID=60 scripts/container_up.sh
set -euo pipefail

RG_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=member_env.sh
source "${RG_SCRIPT_DIR}/member_env.sh"

RG_WS_HOST="$(cd "${RG_SCRIPT_DIR}/.." && pwd)"
RG_CONTAINER_WS="${RG_CONTAINER_WS:-/ws}"

# 记录"是否由调用方显式指定"，用于成员档位冲突检测与 Domain 语义区分。
RG_CONTAINER_EXPLICIT=""
[ -n "${RG_CONTAINER:-}" ] && RG_CONTAINER_EXPLICIT=1
RG_DOMAIN_EXPLICIT=""
[ -n "${ROS_DOMAIN_ID:-}" ] && RG_DOMAIN_EXPLICIT=1
RG_CONTAINER="${RG_CONTAINER:-rg_jazzy}"

rg_apply_member_profile || exit 2

RG_IMAGE="${RG_IMAGE:-ros:jazzy}"
RG_RMW="${RG_RMW:-rmw_fastrtps_cpp}"
# Domain 取值优先级：ROS_DOMAIN_ID（显式） > 成员档位 > 默认 42。
# 注意必须先把 ROS_DOMAIN_ID 纳入，否则"显式要求 99"会被静默忽略成 42，
# 导致 Domain 不匹配检测失效（实测踩过一次）。
RG_DOMAIN_ID="${ROS_DOMAIN_ID:-${RG_DOMAIN_ID:-42}}"
if [ -n "${RG_MEMBER:-}" ]; then RG_DOMAIN_EXPLICIT=1; fi

WS_HOST_NORM="$(rg_normalize_path "${RG_WS_HOST}")"

fail_mismatch() { echo "ERROR: $*" >&2; exit 4; }

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker not found. Install docker, or run these scripts on a native Jazzy host." >&2
  exit 3
fi

# ---------------------------------------------------------------- 复用前核对
if docker inspect "${RG_CONTAINER}" >/dev/null 2>&1; then
  echo "[container] '${RG_CONTAINER}' already exists -- verifying configuration before reuse"

  ACTUAL_STATE="$(docker inspect -f '{{.State.Running}}' "${RG_CONTAINER}")"
  ACTUAL_IMAGE="$(docker inspect -f '{{.Config.Image}}' "${RG_CONTAINER}")"
  ACTUAL_WORKDIR="$(docker inspect -f '{{.Config.WorkingDir}}' "${RG_CONTAINER}")"
  ACTUAL_DOMAIN="$(rg_container_env "${RG_CONTAINER}" ROS_DOMAIN_ID)"
  ACTUAL_RMW="$(rg_container_env "${RG_CONTAINER}" RMW_IMPLEMENTATION)"

  # 目标挂载点对应的源路径（容器可能有多个挂载，只取目标匹配的那一条）
  ACTUAL_MOUNT_SRC="$(docker inspect -f \
    "{{range .Mounts}}{{if eq .Destination \"${RG_CONTAINER_WS}\"}}{{.Source}}{{end}}{{end}}" \
    "${RG_CONTAINER}" 2>/dev/null || true)"

  MISMATCH=0
  report() { # $1=项 $2=期望 $3=实际
    printf '  [不符] %-18s 期望: %s\n' "$1" "$2"
    printf '         %-18s 实际: %s\n' '' "$3"
    MISMATCH=1
  }

  if [ -z "${ACTUAL_MOUNT_SRC}" ]; then
    report "工作区挂载" "${WS_HOST_NORM} -> ${RG_CONTAINER_WS}" \
           "容器内没有挂载到 ${RG_CONTAINER_WS} 的卷"
  else
    ACTUAL_SRC_NORM="$(rg_normalize_path "${ACTUAL_MOUNT_SRC}")"
    if [ "${ACTUAL_SRC_NORM}" != "${WS_HOST_NORM}" ]; then
      report "工作区挂载源" "${WS_HOST_NORM}" "${ACTUAL_SRC_NORM}"
    fi
  fi

  if [ "${ACTUAL_WORKDIR}" != "${RG_CONTAINER_WS}" ]; then
    report "容器工作目录" "${RG_CONTAINER_WS}" "${ACTUAL_WORKDIR:-<空>}"
  fi
  if [ "${ACTUAL_IMAGE}" != "${RG_IMAGE}" ]; then
    report "容器镜像" "${RG_IMAGE}" "${ACTUAL_IMAGE}"
  fi
  if [ "${ACTUAL_RMW}" != "${RG_RMW}" ]; then
    report "RMW 实现" "${RG_RMW}" "${ACTUAL_RMW:-<未设置>}"
  fi

  # Domain：仅在本次**显式**要求时比对；未显式要求则沿用容器固化值。
  if [ -n "${RG_DOMAIN_EXPLICIT}" ] && [ "${ACTUAL_DOMAIN}" != "${RG_DOMAIN_ID}" ]; then
    report "ROS_DOMAIN_ID" "${RG_DOMAIN_ID}（本次显式要求）" "${ACTUAL_DOMAIN:-<未设置>}"
  fi

  if [ "${MISMATCH}" -ne 0 ]; then
    cat >&2 <<EOF

容器 '${RG_CONTAINER}' 的既有配置与本次请求不一致，已拒绝复用。

  期望工作区 : ${WS_HOST_NORM}
  实际工作区 : ${ACTUAL_MOUNT_SRC:-<无挂载>}
  容器名称   : ${RG_CONTAINER}
  容器状态   : $([ "${ACTUAL_STATE}" = "true" ] && echo 运行中 || echo 已停止)

安全提示：
  直接复用会在他人的代码上构建与运行，改动会落到错误的工作区，且不易察觉。
  本脚本不会删除或重建既有容器（它可能属于其他成员）。

处理建议（任选其一，均不影响既有容器）：
  1) 在**正确的工作区**下运行本脚本：
       cd ${WS_HOST_NORM} && RG_MEMBER=<你的成员号> scripts/container_up.sh
  2) 使用你自己的容器名与开发 Domain（推荐）：
       RG_MEMBER=<你的成员号> scripts/container_up.sh
     成员档位见 scripts/member_env.sh（一成员一容器一开发 Domain）。
  3) 确需复用该容器时，先与容器所有者确认，并显式指定其配置：
       RG_CONTAINER=${RG_CONTAINER} ROS_DOMAIN_ID=${ACTUAL_DOMAIN:-<容器值>} scripts/container_up.sh

注意：Docker 容器创建时固化的环境变量不会因宿主机后来修改而更新；
      若确实需要不同的 Domain，应新建独立容器，而不是假设容器会跟随外部变化。
EOF
    exit 4
  fi

  echo "  [ok] 工作区挂载: ${WS_HOST_NORM} -> ${RG_CONTAINER_WS}"
  echo "  [ok] 工作目录: ${ACTUAL_WORKDIR}   镜像: ${ACTUAL_IMAGE}"
  echo "  [ok] ROS_DOMAIN_ID: ${ACTUAL_DOMAIN:-<未设置>}   RMW: ${ACTUAL_RMW:-<未设置>}"

  # 配置核对**通过之后**才决定是否启动（已停止的容器不得"先启动再检查"）
  if [ "${ACTUAL_STATE}" = "true" ]; then
    echo "[container] '${RG_CONTAINER}' is already running (configuration verified)."
    echo "[container] effective ROS_DOMAIN_ID=${ACTUAL_DOMAIN:-<unset>} (容器固化值)"
    exit 0
  fi
  echo "[container] configuration verified; starting existing container '${RG_CONTAINER}'..."
  docker start "${RG_CONTAINER}" >/dev/null
  echo "[container] started."
  exit 0
fi

# ---------------------------------------------------------------- 新建容器
echo "[container] pulling ${RG_IMAGE} (if needed)..."
docker pull "${RG_IMAGE}"

echo "[container] creating '${RG_CONTAINER}' with ${WS_HOST_NORM} -> ${RG_CONTAINER_WS} (ROS_DOMAIN_ID=${RG_DOMAIN_ID})"
docker run -d --name "${RG_CONTAINER}" \
  -v "${WS_HOST_NORM}:${RG_CONTAINER_WS}" \
  -w "${RG_CONTAINER_WS}" \
  -e "ROS_DOMAIN_ID=${RG_DOMAIN_ID}" \
  -e ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST \
  -e "RMW_IMPLEMENTATION=${RG_RMW}" \
  "${RG_IMAGE}" sleep infinity >/dev/null

sleep 1

# 新建后立即回读，确认实际生效值（不做"创建成功即配置正确"的假设）
NEW_DOMAIN="$(rg_container_env "${RG_CONTAINER}" ROS_DOMAIN_ID)"
NEW_RMW="$(rg_container_env "${RG_CONTAINER}" RMW_IMPLEMENTATION)"
NEW_MOUNT="$(docker inspect -f \
  "{{range .Mounts}}{{if eq .Destination \"${RG_CONTAINER_WS}\"}}{{.Source}}{{end}}{{end}}" \
  "${RG_CONTAINER}" 2>/dev/null || true)"

if [ "$(rg_normalize_path "${NEW_MOUNT}")" != "${WS_HOST_NORM}" ]; then
  fail_mismatch "新建容器后回读挂载源不一致（期望 ${WS_HOST_NORM}，实际 ${NEW_MOUNT}）"
fi

echo "[container] created. verified configuration:"
echo "  workspace mount   : $(rg_normalize_path "${NEW_MOUNT}") -> ${RG_CONTAINER_WS}"
echo "  ROS_DOMAIN_ID     : ${NEW_DOMAIN}"
echo "  RMW_IMPLEMENTATION: ${NEW_RMW}"

echo "[container] ready. ROS inside the container:"
docker exec "${RG_CONTAINER}" bash -lc '
  source /opt/ros/jazzy/setup.bash
  echo "  OS:        $(. /etc/os-release && echo "$PRETTY_NAME")"
  echo "  ROS_DISTRO: $ROS_DISTRO"
  echo "  python3:   $(python3 --version 2>&1)"
  echo "  RMW:       ${RMW_IMPLEMENTATION}"
  echo "  domain:    ${ROS_DOMAIN_ID}"
  echo "  ros2:      $(command -v ros2)"
  echo "  colcon:    $(command -v colcon)"
'
