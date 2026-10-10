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

# 成员档位解析（一成员一容器一开发 Domain）。显式指定的 RG_CONTAINER /
# ROS_DOMAIN_ID 优先级最高；与成员档位冲突时 member_env.sh 会直接失败，
# 避免"以为在自己的环境里"却实际用了别人的容器或通信域。
RG_CONTAINER_EXPLICIT=""
[ -n "${RG_CONTAINER:-}" ] && RG_CONTAINER_EXPLICIT=1
RG_DOMAIN_EXPLICIT=""
[ -n "${ROS_DOMAIN_ID:-}" ] && RG_DOMAIN_EXPLICIT=1
# shellcheck source=member_env.sh
source "${RG_SCRIPT_DIR}/member_env.sh"
rg_apply_member_profile || { echo "ERROR: 成员环境配置冲突" >&2; return 2 2>/dev/null || exit 2; }

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
      # 显式把本次生效的 Domain 传给容器进程。
      # 原因：容器创建时固化的环境变量不会随宿主机后来修改而更新；显式传入
      # 才能保证"测试进程实际用的 Domain"与"记录下来的值"一致（GAP-06）。
      local _rg_domain
      _rg_domain="$(rg_effective_domain "${RG_CONTAINER}")"
      if [ -n "${_rg_domain}" ]; then
        docker exec -e "ROS_DOMAIN_ID=${_rg_domain}" "${RG_CONTAINER}" bash -lc "
          set -o pipefail
          cd ${RG_CONTAINER_WS} || exit 3
          source /opt/ros/jazzy/setup.bash
          if [ -f install/setup.bash ]; then source install/setup.bash; fi
          ${command_string}
        "
      else
        docker exec "${RG_CONTAINER}" bash -lc "
          set -o pipefail
          cd ${RG_CONTAINER_WS} || exit 3
          source /opt/ros/jazzy/setup.bash
          if [ -f install/setup.bash ]; then source install/setup.bash; fi
          ${command_string}
        "
      fi
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

# ---------------------------------------------------------------------------
# 运行中实例检测（任务 B3）
#
# 背景：构建/测试脚本此前会无条件调用 rg_reap_stragglers（内部是 pkill -9），
# 一旦用户正在运行受管理实例，构建就会把它的节点杀掉。正确行为是**拒绝执行**，
# 而不是替用户清理正在运行的系统。
# ---------------------------------------------------------------------------

# 受管理实例的记录文件（由 scripts/start_system.sh 维护）
rg_instance_record() {
  echo "${RG_WS_HOST}/logs/start_system/current_instance.env"
}

# 若记录中的实例进程组仍有非僵尸成员，输出该 PGID；否则输出空。
rg_running_instance_pgid() {
  local record pgid
  record="$(rg_instance_record)"
  [ -f "${record}" ] || return 0
  pgid="$(sed -n 's/^launch_pgid=//p' "${record}" 2>/dev/null | head -1)"
  [ -n "${pgid}" ] || return 0
  # 只统计非僵尸进程（容器 PID 1 不回收孤儿，僵尸会被误判为存活）
  if rg_ros "ps -eo pgid=,stat= --no-headers 2>/dev/null | grep -qE '^[[:space:]]*${pgid}[[:space:]]+[^Z]'" >/dev/null 2>&1; then
    echo "${pgid}"
  fi
}

# 本项目的三个常驻节点进程 PID（排除僵尸）
rg_managed_node_pids() {
  rg_ros "ps -eo pid=,stat=,cmd= --no-headers 2>/dev/null \
    | grep -vE '^[[:space:]]*[0-9]+[[:space:]]+Z' \
    | grep -E 'rg_gateway/lib/rg_gateway/security_gateway|rg_demo_nodes/lib/rg_demo_nodes/(navigation_sim|operator_node)' \
    | grep -v grep | sed 's/^ *//' | cut -d' ' -f1" 2>/dev/null | tr '\n' ' '
}

# 无运行中实例返回 0；存在则打印明确错误并返回 4。
rg_require_no_running_instance() {
  local pgid pids
  pgid="$(rg_running_instance_pgid)"
  pids="$(rg_managed_node_pids)"
  if [ -n "${pgid}" ] || [ -n "${pids// /}" ]; then
    echo "ERROR: 检测到正在运行的受管理实例，拒绝执行本次操作。" >&2
    [ -n "${pgid}" ] && echo "       实例进程组(容器内 PGID): ${pgid}" >&2
    [ -n "${pids// /}" ] && echo "       常驻节点 PID: ${pids}" >&2
    echo "       请先停止该实例（在其前台终端按 Ctrl+C；或 scripts/start_system.sh 提示的命令）。" >&2
    echo "       本脚本不会主动清理正在运行的 ROS 2 节点。" >&2
    return 4
  fi
  return 0
}

# 清理上一轮遗留的节点进程。
# 为安全起见：检测到**运行中的受管理实例**时默认跳过清理，避免误杀用户正在使用的系统；
# 测试脚手架确实需要强制清理时，显式设置 RG_REAP_FORCE=1。
rg_reap_stragglers() {
  if [ "${RG_REAP_FORCE:-0}" != "1" ]; then
    if ! rg_require_no_running_instance >/dev/null 2>&1; then
      echo "[reap] 检测到运行中的受管理实例 -> 跳过清理（确需强制清理请设 RG_REAP_FORCE=1）" >&2
      return 0
    fi
  fi
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
