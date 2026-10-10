#!/usr/bin/env bash
# Interactive shell inside the ROS 2 Jazzy environment, at the workspace root,
# with ROS and this workspace's install/ overlay already sourced.
set -uo pipefail

RG_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${RG_SCRIPT_DIR}/lib.sh"

mode="$(rg_mode)"
case "${mode}" in
  native)
    echo "[shell] native mode: sourcing /opt/ros/${ROS_DISTRO}/setup.bash + install/setup.bash"
    exec bash --rcfile <(printf '%s\n' \
      "source /opt/ros/${ROS_DISTRO}/setup.bash" \
      "[ -f '${RG_WS_HOST}/install/setup.bash' ] && source '${RG_WS_HOST}/install/setup.bash'" \
      "cd '${RG_WS_HOST}'") -i
    ;;
  container)
    rg_require_container || exit 3
    echo "[shell] container mode: ${RG_CONTAINER} (${RG_CONTAINER_WS}), ROS + install/ sourced"
    # F0 修复：原先硬编码 `docker exec -it`，在没有终端的环境（脚本、CI、自动化、
    # 管道输入）下会直接失败：
    #   cannot attach stdin to a TTY-enabled container because stdin is not a terminal
    # 现在按是否真的有终端来决定是否申请 TTY，并支持直接执行一条命令。
    if [ "$#" -gt 0 ]; then
      # 传入命令：非交互执行，供自动化与联调脚本使用
      docker exec "${RG_CONTAINER}" bash -lc "
        source /opt/ros/jazzy/setup.bash
        [ -f ${RG_CONTAINER_WS}/install/setup.bash ] && source ${RG_CONTAINER_WS}/install/setup.bash
        cd ${RG_CONTAINER_WS}
        $*
      "
      exit $?
    fi
    if [ -t 0 ] && [ -t 1 ]; then
      docker exec -it "${RG_CONTAINER}" bash -lc "
        source /opt/ros/jazzy/setup.bash
        [ -f ${RG_CONTAINER_WS}/install/setup.bash ] && source ${RG_CONTAINER_WS}/install/setup.bash
        cd ${RG_CONTAINER_WS}
        exec bash -i
      "
    else
      echo "ERROR: 当前没有可用的终端，无法启动交互式 shell。" >&2
      echo "       若要在自动化环境中执行命令，请把命令作为参数传入：" >&2
      echo "         scripts/shell.sh '<command>'" >&2
      exit 2
    fi
    ;;
  *)
    echo "ERROR: no ROS environment available. Run scripts/container_up.sh first." >&2
    exit 3
    ;;
esac
