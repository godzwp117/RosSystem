#!/usr/bin/env bash
# Shared helpers for the RoboGuard base scripts.
#
# Environment model
# -----------------
# This project's frozen target is ROS 2 Jazzy, which is only packaged for
# Ubuntu 24.04. The development host is Ubuntu 22.04, so the ROS environment is
# provided by the `ros:jazzy` container (see README.md / environment.md).
#
# The scripts below therefore work in two modes:
#   * NATIVE     -- $ROS_DISTRO is set and `ros2` is on PATH: run in place.
#   * CONTAINER  -- otherwise: run inside $RG_CONTAINER, with this workspace
#                   bind-mounted at $RG_CONTAINER_WS.
# Override with RG_MODE=native|container to force one.

set -o pipefail

RG_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RG_WS_HOST="$(cd "${RG_SCRIPT_DIR}/.." && pwd)"
RG_CONTAINER="${RG_CONTAINER:-rg_jazzy}"
RG_IMAGE="${RG_IMAGE:-ros:jazzy}"
RG_CONTAINER_WS="${RG_CONTAINER_WS:-/ws}"
RG_LOG_DIR="${RG_WS_HOST}/logs"

mkdir -p "${RG_LOG_DIR}"

rg_mode() {
  if [ -n "${RG_MODE:-}" ]; then
    echo "${RG_MODE}"
    return
  fi
  if [ -n "${ROS_DISTRO:-}" ] && command -v ros2 >/dev/null 2>&1; then
    echo "native"
  elif command -v docker >/dev/null 2>&1; then
    echo "container"
  else
    echo "none"
  fi
}

# rg_ros "<shell command>" -- run a command inside the ROS environment, from the
# workspace root, with ROS and this workspace's install/ overlay sourced.
rg_ros() {
  local command_string="$1"
  local mode
  mode="$(rg_mode)"

  case "${mode}" in
    native)
      (
        cd "${RG_WS_HOST}" || exit 3
        # shellcheck disable=SC1090
        source "/opt/ros/${ROS_DISTRO}/setup.bash"
        if [ -f install/setup.bash ]; then
          # shellcheck disable=SC1091
          source install/setup.bash
        fi
        eval "${command_string}"
      )
      ;;
    container)
      docker exec "${RG_CONTAINER}" bash -lc "
        set -o pipefail
        cd ${RG_CONTAINER_WS} || exit 3
        source /opt/ros/jazzy/setup.bash
        if [ -f install/setup.bash ]; then source install/setup.bash; fi
        ${command_string}
      "
      ;;
    *)
      echo "ERROR: no ROS environment available." >&2
      echo "       Set up the container first: scripts/container_up.sh" >&2
      return 3
      ;;
  esac
}

# rg_evidenced <name> <log-relative-path> <command...>
# Runs the command, tees its output to logs/<name>.log, and prints the
# command / exit code / log path triple required by task requirement 12.
rg_evidenced() {
  local name="$1"
  local log_path="$2"
  shift 2
  local command_string="$*"

  echo "---------------------------------------------------------------"
  echo "[run] ${name}"
  echo "[cmd] ${command_string}"
  mkdir -p "$(dirname "${log_path}")"

  rg_ros "${command_string}" 2>&1 | tee "${log_path}"
  local status="${PIPESTATUS[0]}"

  echo "[exit] ${status}"
  echo "[log] ${log_path}"
  echo "---------------------------------------------------------------"
  return "${status}"
}

rg_require_container() {
  if ! command -v docker >/dev/null 2>&1; then
    echo "ERROR: docker is not available and no native ROS environment was found." >&2
    return 3
  fi
  if ! docker inspect "${RG_CONTAINER}" >/dev/null 2>&1; then
    echo "ERROR: container '${RG_CONTAINER}' does not exist. Run scripts/container_up.sh" >&2
    return 3
  fi
  if [ "$(docker inspect -f '{{.State.Running}}' "${RG_CONTAINER}")" != "true" ]; then
    echo "ERROR: container '${RG_CONTAINER}' is not running. Run scripts/container_up.sh" >&2
    return 3
  fi
  return 0
}

# Kill any node process left over from a previous run. The bracket trick stops
# pkill from matching its own command line.
rg_reap_stragglers() {
  rg_ros '
    killed=0
    for pattern in \
        "rg_gateway/lib/rg_gateway/security_[g]ateway" \
        "rg_demo_nodes/lib/rg_demo_nodes/navigation_[s]im" \
        "rg_demo_nodes/lib/rg_demo_nodes/planner_[n]ode" \
        "rg_demo_nodes/lib/rg_demo_nodes/operator_[n]ode"; do
      if pkill -9 -f "$pattern" 2>/dev/null; then killed=1; fi
    done
    sleep 0.4
    if [ "$killed" = "1" ]; then echo "[reap] killed leftover node process(es)"; fi
  ' >/dev/null 2>&1 || true
}
