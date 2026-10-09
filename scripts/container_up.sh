#!/usr/bin/env bash
# Create/start the ROS 2 Jazzy container used by every other script.
#
# The development host is Ubuntu 22.04 (jammy); ROS 2 Jazzy is only packaged for
# Ubuntu 24.04 (noble), so the ROS environment lives in a container and this
# workspace is bind-mounted into it. Nothing is installed on the host.
set -euo pipefail

RG_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RG_WS_HOST="$(cd "${RG_SCRIPT_DIR}/.." && pwd)"
RG_CONTAINER="${RG_CONTAINER:-rg_jazzy}"
RG_IMAGE="${RG_IMAGE:-ros:jazzy}"
RG_DOMAIN_ID="${ROS_DOMAIN_ID:-42}"

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker not found. Install docker, or run these scripts on a native Jazzy host." >&2
  exit 3
fi

if docker inspect "${RG_CONTAINER}" >/dev/null 2>&1; then
  if [ "$(docker inspect -f '{{.State.Running}}' "${RG_CONTAINER}")" = "true" ]; then
    echo "[container] '${RG_CONTAINER}' is already running."
    exit 0
  fi
  echo "[container] starting existing container '${RG_CONTAINER}'..."
  docker start "${RG_CONTAINER}" >/dev/null
  echo "[container] started."
  exit 0
fi

echo "[container] pulling ${RG_IMAGE} (if needed)..."
docker pull "${RG_IMAGE}"

echo "[container] creating '${RG_CONTAINER}' with ${RG_WS_HOST} -> ${RG_CONTAINER_WS:-/ws}"
docker run -d --name "${RG_CONTAINER}" \
  -v "${RG_WS_HOST}:${RG_CONTAINER_WS:-/ws}" \
  -w "${RG_CONTAINER_WS:-/ws}" \
  -e "ROS_DOMAIN_ID=${RG_DOMAIN_ID}" \
  -e ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST \
  -e RMW_IMPLEMENTATION=rmw_fastrtps_cpp \
  "${RG_IMAGE}" sleep infinity >/dev/null

sleep 1
echo "[container] ready. ROS inside the container:"
docker exec "${RG_CONTAINER}" bash -lc '
  source /opt/ros/jazzy/setup.bash
  echo "  OS:        $(. /etc/os-release && echo "$PRETTY_NAME")"
  echo "  ROS_DISTRO: $ROS_DISTRO"
  echo "  python3:   $(python3 --version 2>&1)"
  echo "  RMW:       ${RMW_IMPLEMENTATION}"
  echo "  ros2:      $(command -v ros2)"
  echo "  colcon:    $(command -v colcon)"
'
