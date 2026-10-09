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
    docker exec -it "${RG_CONTAINER}" bash -lc "
      source /opt/ros/jazzy/setup.bash
      [ -f ${RG_CONTAINER_WS}/install/setup.bash ] && source ${RG_CONTAINER_WS}/install/setup.bash
      cd ${RG_CONTAINER_WS}
      exec bash -i
    "
    ;;
  *)
    echo "ERROR: no ROS environment available. Run scripts/container_up.sh first." >&2
    exit 3
    ;;
esac
