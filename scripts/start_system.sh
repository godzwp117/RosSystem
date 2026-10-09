#!/usr/bin/env bash
# =============================================================================
# start_system.sh -- RoboGuard 最小 ROS 2 业务基底统一启动脚本
#
# 职责边界（严格限定，不做其他事）：
#   1. 运行环境初始化：定位项目根目录、检查 Docker/daemon、复用 container_up.sh、
#      校验容器内 /ws 挂载与 ROS 2 Jazzy 环境、必要时调用 build.sh 构建。
#   2. 统一启动：复用现有 ros2 launch rg_demo_nodes stack.launch.py。
#   3. 就绪检测：轮询 ROS 2 通信资源（Action 名称 + 类型）与实际进程，不用固定 sleep。
#   4. 生命周期：前台运行、SIGINT/SIGTERM 优雅关闭、只清理本实例进程组。
#
# 明确不做：
#   * 不新增/替换 launch 文件（stack.launch.py 已满足需求）。
#   * 不新增 ROS 2 节点或 Python 总控进程，不修改 Action 契约、事件结构、原因码。
#   * 不执行 pkill ros2 / docker stop rg_jazzy 等无差别清理。
#   * 不引入调度服务器、Web 控制台、数据库等组件。
#
# 用法：
#   scripts/start_system.sh            启动现有系统（install/ 缺失时自动构建一次）
#   scripts/start_system.sh --build    先重新构建再启动
#   scripts/start_system.sh --help     显示帮助
#
# 测试 A~F 与验收记录见提交说明；本脚本只负责启动与生命周期管理。
# =============================================================================
set -uo pipefail
# 刻意不使用 set -m（job control）：
#   启用 job control 后，脚本执行前台命令（sleep）时会把它放进独立进程组并设为终端前台组，
#   此时终端 Ctrl+C 只会送达该前台组，脚本自身收不到 SIGINT，trap 不会触发（真实终端下的坑）。
#   关闭 job control 后，脚本与前台命令共享终端前台进程组，Ctrl+C 能可靠送到脚本并触发 trap；
#   后台 docker exec 虽会一并收到 SIGINT 而退出，但清理并不依赖它——而是依据实例目录里
#   记录的容器内进程组 ID（PGID）显式向前台组之外的容器进程组发送信号。

# ---------------------------------------------------------------------------
# 0. 常量与路径（自动定位项目根目录，不依赖调用者当前目录）
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WS_HOST="$(cd "${SCRIPT_DIR}/.." && pwd)"

# 复用 lib.sh 的容器相关约定（RG_CONTAINER / RG_CONTAINER_WS / rg_mode / rg_require_container）
# shellcheck source=lib.sh
source "${SCRIPT_DIR}/lib.sh"

CONTAINER="${RG_CONTAINER}"
CTR_WS="${RG_CONTAINER_WS}"

POLICY_HOST="${WS_HOST}/config/task_policy.yaml"
POLICY_CTR="${CTR_WS}/config/task_policy.yaml"

RUN_ROOT_HOST="${WS_HOST}/logs/start_system"
RUN_ROOT_CTR="${CTR_WS}/logs/start_system"
POINTER_HOST="${RUN_ROOT_HOST}/current_instance.env"

LAUNCH_PKG="rg_demo_nodes"
LAUNCH_FILE="stack.launch.py"

UPSTREAM_ACTION="/rg/guarded_navigate"
DOWNSTREAM_ACTION="/rg/nav_execute"
ACTION_TYPE="rg_interfaces/action/PatrolNavigate"

# 可调参数（仅在确有需要时通过环境变量覆盖，不对外暴露多余命令行开关）
READY_TIMEOUT="${RG_READY_TIMEOUT:-90}"        # 就绪检测总超时（秒）
SHUTDOWN_TIMEOUT="${RG_SHUTDOWN_TIMEOUT:-15}"  # 优雅关闭总超时（秒，SIGINT 宽限）
HEARTBEAT_TIMEOUT="${RG_HEARTBEAT_TIMEOUT:-45}" # 容器内看门狗判定宿主心跳过期的阈值（秒）
HEARTBEAT_INTERVAL=5                           # 宿主心跳间隔（秒）
WATCHDOG_INTERVAL=3                            # 容器内看门狗检查间隔（秒）
ACTION_LIST_TIMEOUT=10                         # 单次 ros2 action list 超时（秒）

EXIT_OK=0
EXIT_USAGE=2
EXIT_ENV=3
EXIT_BUSY=4
EXIT_BUILD=5
EXIT_READY=6
EXIT_RUNTIME=7

# ---------------------------------------------------------------------------
# 1. 输出助手
# ---------------------------------------------------------------------------
info()  { printf '[start] %s\n' "$*"; }
ok()    { printf '[  ok ] %s\n' "$*"; }
warn()  { printf '[warn ] %s\n' "$*" >&2; }
fail()  { printf '[error] %s\n' "$*" >&2; }
rule()  { printf '%s\n' "--------------------------------------------------------------------"; }

# ---------------------------------------------------------------------------
# 2. 容器内执行助手
#    rg_mode() == native 时（在容器内直接运行）退化为本地执行，保持与现有脚本一致。
# ---------------------------------------------------------------------------
CTR_PRELUDE="cd ${CTR_WS} 2>/dev/null || exit 3
source /opt/ros/jazzy/setup.bash
if [ -f install/setup.bash ]; then source install/setup.bash; fi"

# ctr_raw "<bash 片段>"：容器内原样执行（不 source ROS），用于挂载/进程等检查
ctr_raw() {
  if [ "$(rg_mode)" = "native" ]; then
    bash -c "$1"
  else
    docker exec "${CONTAINER}" bash -c "$1"
  fi
}

# ctr_ros "<bash 片段>"：容器内执行，并已 source ROS 2 + 本工作空间 install/
ctr_ros() {
  if [ "$(rg_mode)" = "native" ]; then
    bash -c "${CTR_PRELUDE}
$1"
  else
    docker exec "${CONTAINER}" bash -c "${CTR_PRELUDE}
$1"
  fi
}

# ---------------------------------------------------------------------------
# 3. 命令行参数
# ---------------------------------------------------------------------------
DO_BUILD=0
usage() {
  cat <<'USAGE'
用法:
  scripts/start_system.sh            启动现有系统（install/ 缺失时自动构建一次）
  scripts/start_system.sh --build    先重新构建工作空间，再启动
  scripts/start_system.sh --help     显示本帮助

说明:
  前台启动 RoboGuard 最小 ROS 2 业务基底，常驻节点为 operator_node /
  security_gateway / navigation_sim（不含 planner_node，业务请求需另行按需提交）。
  就绪判据：/rg/guarded_navigate 与 /rg/nav_execute 均可发现且类型为
  rg_interfaces/action/PatrolNavigate，且三个节点进程存活。
  Ctrl+C 只停止本次启动实例的进程组，不会停止容器、也不会清理其他 ROS 2 进程。

退出码:
  0 正常停止     2 参数错误     3 环境错误    4 已有实例
  5 构建失败     6 就绪超时     7 运行期异常退出
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --build) DO_BUILD=1 ;;
    -h|--help) usage; exit "${EXIT_OK}" ;;
    *) fail "未知参数: $1"; usage >&2; exit "${EXIT_USAGE}" ;;
  esac
  shift
done

# ---------------------------------------------------------------------------
# 4. 运行环境初始化
# ---------------------------------------------------------------------------
info "项目根目录: ${WS_HOST}"

if ! command -v docker >/dev/null 2>&1; then
  fail "未找到 docker 命令。本项目的 ROS 2 Jazzy 运行在容器中，需要 Docker。"
  exit "${EXIT_ENV}"
fi

if ! docker info >/dev/null 2>&1; then
  fail "Docker daemon 不可用（docker info 失败）。请先启动 Docker，例如: sudo service docker start"
  exit "${EXIT_ENV}"
fi
ok "Docker 命令与 daemon 可用"

# 复用既有 container_up.sh 确保 rg_jazzy 已启动（幂等）
info "调用 scripts/container_up.sh 确保容器 ${CONTAINER} 运行中 ..."
if ! bash "${SCRIPT_DIR}/container_up.sh"; then
  fail "container_up.sh 执行失败，容器 ${CONTAINER} 未就绪"
  exit "${EXIT_ENV}"
fi
if ! rg_require_container; then
  exit "${EXIT_ENV}"
fi
ok "容器 ${CONTAINER} 正在运行"

# --- 校验 /ws 挂载：必须与宿主工作区一致；不一致时明确报错，绝不删除或重建容器 ---
EXPECTED_MOUNT="${WS_HOST}=>${CTR_WS}"
ACTUAL_MOUNTS="$(docker inspect -f '{{range .Mounts}}{{.Source}}=>{{.Destination}}{{"\n"}}{{end}}' "${CONTAINER}" 2>/dev/null || true)"
if ! printf '%s\n' "${ACTUAL_MOUNTS}" | grep -qxF "${EXPECTED_MOUNT}"; then
  fail "容器 ${CONTAINER} 的工作区挂载不符合预期。"
  fail "  期望: ${EXPECTED_MOUNT}"
  fail "  实际:"
  printf '%s\n' "${ACTUAL_MOUNTS}" | sed 's/^/         /' >&2
  fail "本脚本不会删除或重建已有容器。请人工确认后处理，例如："
  fail "  docker rm -f ${CONTAINER} && scripts/container_up.sh"
  exit "${EXIT_ENV}"
fi
ok "工作区挂载正确: ${EXPECTED_MOUNT}"

if ! ctr_raw "[ -d ${CTR_WS}/src ]"; then
  fail "容器内 ${CTR_WS}/src 不存在，工作区内容不可用（挂载可能未完成）"
  exit "${EXIT_ENV}"
fi
ok "容器内工作区可读（${CTR_WS}/src 存在）"

# --- 校验容器内 ROS 2 Jazzy 环境 ---
ROS_PROBE="$(ctr_raw 'source /opt/ros/jazzy/setup.bash >/dev/null 2>&1 || { echo NO_SETUP; exit 0; }
printf "DISTRO=%s\n" "${ROS_DISTRO:-}"
command -v ros2 >/dev/null 2>&1 && printf "ROS2=ok\n" || printf "ROS2=missing\n"
python3 -c "import rclpy" >/dev/null 2>&1 && printf "RCLPY=ok\n" || printf "RCLPY=missing\n"
printf "DOMAIN=%s\n" "${ROS_DOMAIN_ID:-unset}"')"
if ! printf '%s\n' "${ROS_PROBE}" | grep -q '^DISTRO=jazzy$'; then
  fail "容器内 ROS 2 Jazzy 环境不可用："
  printf '%s\n' "${ROS_PROBE}" | sed 's/^/         /' >&2
  exit "${EXIT_ENV}"
fi
if ! printf '%s\n' "${ROS_PROBE}" | grep -q '^ROS2=ok$' || ! printf '%s\n' "${ROS_PROBE}" | grep -q '^RCLPY=ok$'; then
  fail "容器内 ros2 CLI 或 rclpy 不可用："
  printf '%s\n' "${ROS_PROBE}" | sed 's/^/         /' >&2
  exit "${EXIT_ENV}"
fi
CTR_DOMAIN="$(printf '%s\n' "${ROS_PROBE}" | sed -n 's/^DOMAIN=//p')"
ok "容器内 ROS 2 Jazzy 环境可用（ROS_DISTRO=jazzy, ros2/rclpy 均正常, ROS_DOMAIN_ID=${CTR_DOMAIN}）"

# --- 权威策略文件必须存在（缺失即拒绝启动，不提供绕过） ---
if [ ! -f "${POLICY_HOST}" ]; then
  fail "权威任务策略文件不存在: ${POLICY_HOST}"
  fail "安全策略只允许从该可信文件加载，缺失时不启动（fail closed）。"
  exit "${EXIT_ENV}"
fi
if ! ctr_raw "[ -f ${POLICY_CTR} ]"; then
  fail "权威任务策略文件在容器内不可见: ${POLICY_CTR}"
  fail "宿主与容器的工作区挂载可能不一致，已拒绝启动。"
  exit "${EXIT_ENV}"
fi
ok "权威策略文件存在且容器内可见: ${POLICY_CTR}"

# ---------------------------------------------------------------------------
# 5. 单实例互斥：先检测，后构建
#    （重要：build.sh 会调用 rg_reap_stragglers 清理同名节点进程，
#      因此必须在确认没有运行中实例之后才允许构建。）
# ---------------------------------------------------------------------------
# 读取记录文件字段（KEY=value 格式，逐行解析，不 source 执行任何内容）
record_get() { sed -n "s/^$2=//p" "$1" 2>/dev/null | head -1; }

# 列出本系统三个常驻节点的 PID（任意实例启动的）
# 必须排除僵尸进程：容器 PID 1 是 `sleep infinity`，不回收孤儿进程，容器内会长期积累
# <defunct>；僵尸的 cmd 里仍带 [navigation_sim] / [operator_node] 这类名字，若不排除会
# 让"节点存活数"被僵尸凑满，从而把未就绪误判为已就绪。
ctr_node_pids() {
  ctr_raw "ps -eo pid=,stat=,cmd= --no-headers 2>/dev/null \
    | grep -vE '^[[:space:]]*[0-9]+[[:space:]]+Z' \
    | grep -E 'rg_gateway/lib/rg_gateway/security_gateway|rg_demo_nodes/lib/rg_demo_nodes/(navigation_sim|operator_node)' \
    | grep -v grep | sed 's/^ *//' | cut -d' ' -f1"
}

# 进程组是否仍有“活”进程。必须排除僵尸（stat 以 Z 开头）：僵尸已终止、不占资源、
# 无法被 kill，把它算作残留会导致误报以及 25s+8s 的无谓等待。
ctr_group_alive() {
  ctr_raw "ps -eo pgid=,stat= --no-headers 2>/dev/null | grep -qE '^[[:space:]]*$1[[:space:]]+[^Z]'"
}

# 该进程组是否确实是本项目的 ros2 launch（避免 PID 复用导致误杀）
ctr_group_is_our_launch() {
  ctr_raw "ps -eo pgid=,cmd= --no-headers 2>/dev/null \
    | grep -E '^[[:space:]]*$1[[:space:]]' \
    | grep -q 'ros2 launch ${LAUNCH_PKG} ${LAUNCH_FILE}'"
}

RUNNING_PGID=""
RUNNING_PIDS=""
RUNNING_RECORD=""
RUNNING_RUN_ID=""

detect_running_instance() {
  RUNNING_PGID=""; RUNNING_PIDS=""; RUNNING_RECORD=""; RUNNING_RUN_ID=""

  if [ -f "${POINTER_HOST}" ]; then
    local pgid run_id
    pgid="$(record_get "${POINTER_HOST}" launch_pgid)"
    run_id="$(record_get "${POINTER_HOST}" run_id)"
    if [ -n "${pgid}" ] && ctr_group_alive "${pgid}" && ctr_group_is_our_launch "${pgid}"; then
      RUNNING_PGID="${pgid}"
      RUNNING_RECORD="${POINTER_HOST}"
      RUNNING_RUN_ID="${run_id}"
      return 0
    fi
    warn "发现过期实例记录（记录中的进程组 ${pgid:-空} 已不存在）: run_id=${run_id:-未知}"
    warn "该记录将被本次启动覆盖，不会清理任何进程。"
  fi

  # 兜底：进程扫描（覆盖非本脚本启动的同类实例，例如 run_demo.sh / 手工 launch）
  local pids
  pids="$(ctr_node_pids)"
  if [ -n "${pids}" ]; then
    RUNNING_PIDS="$(printf '%s' "${pids}" | tr '\n' ' ')"
    return 0
  fi
  return 1
}

if detect_running_instance; then
  fail "检测到已在运行的 RoboGuard 系统实例，拒绝重复启动。"
  if [ -n "${RUNNING_PGID}" ]; then
    fail "  实例 run_id      : ${RUNNING_RUN_ID:-未知}"
    fail "  实例记录文件     : ${RUNNING_RECORD}"
    fail "  容器内进程组 ID  : ${RUNNING_PGID}"
  fi
  if [ -n "${RUNNING_PIDS}" ]; then
    fail "  容器内节点 PID   : ${RUNNING_PIDS}"
  fi
  fail "本脚本不会清理其他运行中的 ROS 2 节点。"
  fail "如需停止该实例：在其前台终端按 Ctrl+C；或仅终止它自己的进程组："
  [ -n "${RUNNING_PGID}" ] && fail "  docker exec ${CONTAINER} kill -INT -- -${RUNNING_PGID}"
  exit "${EXIT_BUSY}"
fi
ok "未发现运行中的同类实例，可以启动"

# ---------------------------------------------------------------------------
# 6. 构建（默认复用已有产物；缺失或 --build 时才构建）
# ---------------------------------------------------------------------------
NEED_BUILD=0
BUILD_REASON=""
if [ "${DO_BUILD}" -eq 1 ]; then
  NEED_BUILD=1; BUILD_REASON="用户指定 --build"
elif [ ! -f "${WS_HOST}/install/setup.bash" ]; then
  NEED_BUILD=1; BUILD_REASON="缺少 install/setup.bash"
elif [ ! -x "${WS_HOST}/install/rg_gateway/lib/rg_gateway/security_gateway" ]; then
  NEED_BUILD=1; BUILD_REASON="缺少已构建的 security_gateway 可执行文件"
elif [ ! -x "${WS_HOST}/install/rg_demo_nodes/lib/rg_demo_nodes/navigation_sim" ]; then
  NEED_BUILD=1; BUILD_REASON="缺少已构建的 navigation_sim 可执行文件"
elif [ ! -x "${WS_HOST}/install/rg_demo_nodes/lib/rg_demo_nodes/operator_node" ]; then
  NEED_BUILD=1; BUILD_REASON="缺少已构建的 operator_node 可执行文件"
fi

if [ "${NEED_BUILD}" -eq 1 ]; then
  info "需要构建（原因：${BUILD_REASON}），调用 scripts/build.sh ..."
  if ! bash "${SCRIPT_DIR}/build.sh"; then
    fail "构建失败（build.sh 返回非零）。构建日志: ${WS_HOST}/logs/build.log"
    exit "${EXIT_BUILD}"
  fi
  ok "构建完成"
else
  ok "已有构建产物，跳过构建（如需重建: scripts/start_system.sh --build）"
fi

# ---------------------------------------------------------------------------
# 7. 创建本次实例的独立运行目录
# ---------------------------------------------------------------------------
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_DIR_HOST="${RUN_ROOT_HOST}/${RUN_ID}"
RUN_DIR_CTR="${RUN_ROOT_CTR}/${RUN_ID}"
mkdir -p "${RUN_DIR_HOST}"

AUDIT_CTR="${RUN_DIR_CTR}/audit.jsonl"
NAVSIM_CTR="${RUN_DIR_CTR}/navsim_goals.jsonl"
LAUNCH_LOG_CTR="${RUN_DIR_CTR}/launch.log"
HOST_LOG="${RUN_DIR_HOST}/start_system.log"
RUNNER_HOST="${RUN_DIR_HOST}/container_runner.sh"
PIDFILE_CTR="${RUN_DIR_CTR}/launch.pid"
PGFILE_CTR="${RUN_DIR_CTR}/launch.pgid"
HB_CTR="${RUN_DIR_CTR}/heartbeat"
HB_HOST="${RUN_DIR_HOST}/heartbeat"

info "本次实例目录: ${RUN_DIR_HOST}"

# ---------------------------------------------------------------------------
# 8. 容器内启动器（写入实例目录，便于事后审计；通过 stdin 交给容器内 bash -s 执行）
# ---------------------------------------------------------------------------
cat > "${RUNNER_HOST}" <<'RUNNER_EOF'
#!/usr/bin/env bash
# 容器内启动器 -- 由 start_system.sh 生成，只服务本次实例。
# 关键点：
#   * setsid 让 ros2 launch 成为独立会话/进程组组长，其所有子节点继承同一 PGID，
#     宿主据此可以精确地只终止本实例的进程树。
#   * 心跳看门狗：若宿主脚本异常消失（含 kill -9，无法执行清理），心跳文件停止更新，
#     看门狗在阈值后只终止本实例进程组，避免容器内节点长期残留。
#
# 注意：这里刻意不使用 set -u。ROS 的 /opt/ros/jazzy/setup.bash 会引用未定义的
# AMENT_TRACE_SETUP_FILES，在 set -u 下 source 会直接失败。改为对必需的环境变量
# 做显式 :? 校验。
set -o pipefail

: "${RG_CTR_WS:?缺少环境变量 RG_CTR_WS}"
: "${RG_RUN_DIR_CTR:?缺少环境变量 RG_RUN_DIR_CTR}"
: "${RG_LAUNCH_PKG:?缺少环境变量 RG_LAUNCH_PKG}"
: "${RG_LAUNCH_FILE:?缺少环境变量 RG_LAUNCH_FILE}"
: "${RG_POLICY_CTR:?缺少环境变量 RG_POLICY_CTR}"
: "${RG_AUDIT_CTR:?缺少环境变量 RG_AUDIT_CTR}"
: "${RG_NAVSIM_CTR:?缺少环境变量 RG_NAVSIM_CTR}"
: "${RG_HEARTBEAT_TIMEOUT:?缺少环境变量 RG_HEARTBEAT_TIMEOUT}"
: "${RG_WATCHDOG_INTERVAL:?缺少环境变量 RG_WATCHDOG_INTERVAL}"

cd "${RG_CTR_WS}" || exit 3
source /opt/ros/jazzy/setup.bash
if [ -f install/setup.bash ]; then source install/setup.bash; fi

RUN_DIR="${RG_RUN_DIR_CTR}"
LAUNCH_LOG="${RUN_DIR}/launch.log"     # 只承载 ros2 launch 自身的 stdout/stderr
RUNNER_LOG="${RUN_DIR}/runner.log"     # 启动器与看门狗自己的消息
HB="${RUN_DIR}/heartbeat"
PIDFILE="${RUN_DIR}/launch.pid"
PGFILE="${RUN_DIR}/launch.pgid"

mkdir -p "${RUN_DIR}"
touch "${HB}"

# ---------------------------------------------------------------------------
# 生成极小的信号复位启动器，再用它拉起 ros2 launch。
#
# 为什么必须这样做：非交互 bash 用 `&` 启动的后台任务会把 SIGINT/SIGQUIT 置为
# SIG_IGN（POSIX 行为），而 bash 的 trap 无法恢复“进入 shell 时已被忽略”的信号。
# 直接 `setsid ros2 launch ... &` 会让 ros2 launch 本体永远收不到 Ctrl+C —— 表面
# 上能退出，只是因为它的子节点各自装了 rclpy 的 SIGINT 处理器；一旦有子节点卡住，
# 整组就只能等到 SIGTERM/SIGKILL 升级才清理。Python 可以直接 sigaction 复位为
# SIG_DFL，从而把 Ctrl+C 真正送到 ros2 launch 本体，实现正常的优雅关闭。
# 同时用 os.setsid() 建立独立会话/进程组，宿主据此精确清理本实例（且 setsid(2)
# 不会 fork，PID 保持不变，不像 setsid(1) 在被调用者已是组长时会分叉）。
# ---------------------------------------------------------------------------
LAUNCHER_PY="${RUN_DIR}/launch_with_default_signals.py"
cat > "${LAUNCHER_PY}" <<'PY'
"""复位信号处置 -> 建立独立会话 -> 记录自身 PID/PGID -> exec 目标命令。

参数: <pidfile> <pgfile> <command> [args...]

PID/PGID 必须由本进程自己写：它才是持有正确 PGID 的进程。若由外部在 `&` 之后立刻用
ps 去读，会与 os.setsid() 竞态，可能读到外层 bash 的进程组；那样退出清理会杀错进程组，
真正的 ros2 launch 反而成为孤儿（已实测复现过）。
"""
import os
import signal
import sys

signal.signal(signal.SIGINT, signal.SIG_DFL)
signal.signal(signal.SIGQUIT, signal.SIG_DFL)
try:
    os.setsid()
except OSError:
    pass

pidfile, pgfile = sys.argv[1], sys.argv[2]
with open(pidfile, 'w') as handle:
    handle.write('{0}\n'.format(os.getpid()))
with open(pgfile, 'w') as handle:
    handle.write('{0}\n'.format(os.getpgid(0)))

os.execvp(sys.argv[3], sys.argv[3:])
PY

# PYTHONUNBUFFERED=1：ros2 launch 是 Python 程序，输出到文件时默认块缓冲，
# 会让 tail -f launch.log 长时间看不到内容。
export PYTHONUNBUFFERED=1
python3 "${LAUNCHER_PY}" "${PIDFILE}" "${PGFILE}" \
  ros2 launch "${RG_LAUNCH_PKG}" "${RG_LAUNCH_FILE}" \
  policy_path:="${RG_POLICY_CTR}" \
  audit_log_path:="${RG_AUDIT_CTR}" \
  navsim_record_path:="${RG_NAVSIM_CTR}" \
  start_operator:=true \
  >"${LAUNCH_LOG}" 2>&1 &
LAUNCH_PID=$!

# 等待启动器写出 PID/PGID：由持有正确 PGID 的进程自己写，避免与 os.setsid() 竞态
waited=0
while [ ! -s "${PIDFILE}" ] && [ "${waited}" -lt 200 ]; do
  sleep 0.1
  waited=$((waited + 1))
done
if [ ! -s "${PIDFILE}" ] || [ ! -s "${PGFILE}" ]; then
  echo "[runner] ERROR: 启动器未在 20s 内写出 PID/PGID 文件" >>"${RUNNER_LOG}"
  exit 4
fi
LAUNCH_PID="$(tr -d ' \n' <"${PIDFILE}")"
LAUNCH_PGID="$(tr -d ' \n' <"${PGFILE}")"
if [ -z "${LAUNCH_PID}" ] || [ -z "${LAUNCH_PGID}" ]; then
  echo "[runner] ERROR: PID/PGID 文件内容为空" >>"${RUNNER_LOG}"
  exit 4
fi
echo "[runner] ros2 launch 已启动 pid=${LAUNCH_PID} pgid=${LAUNCH_PGID}" >>"${RUNNER_LOG}"

# 心跳看门狗：宿主异常消失（含 kill -9，宿主自身已无法执行清理）时接管清理。
# 采用与宿主相同的 INT->TERM->KILL 升级顺序并排除僵尸，确保"宿主没了、容器里节点还在"
# 这种情况不会长期存在。
(
  while sleep "${RG_WATCHDOG_INTERVAL}"; do
    [ -f "${HB}" ] || exit 0
    mt="$(stat -c %Y "${HB}" 2>/dev/null)" || exit 0
    now="$(date +%s)"
    age=$(( now - mt ))
    [ "${age}" -gt "${RG_HEARTBEAT_TIMEOUT}" ] || continue

    echo "[watchdog] 宿主心跳已过期 ${age}s（阈值 ${RG_HEARTBEAT_TIMEOUT}s），接管清理进程组 ${LAUNCH_PGID}" >>"${RUNNER_LOG}"
    for sig in INT TERM KILL; do
      kill -"${sig}" -- "-${LAUNCH_PGID}" 2>/dev/null
      w=0
      while [ "${w}" -lt 8 ]; do
        if ! ps -eo pgid=,stat= --no-headers 2>/dev/null \
             | grep -qE "^[[:space:]]*${LAUNCH_PGID}[[:space:]]+[^Z]"; then
          echo "[watchdog] 进程组 ${LAUNCH_PGID} 已清理（信号 ${sig}）" >>"${RUNNER_LOG}"
          exit 0
        fi
        sleep 1
        w=$((w + 1))
      done
    done
    echo "[watchdog] 进程组 ${LAUNCH_PGID} 在 SIGKILL 后仍有非僵尸成员，请人工检查" >>"${RUNNER_LOG}"
    exit 1
  done
) &
WATCHDOG_PID=$!

wait "${LAUNCH_PID}"
RC=$?
kill "${WATCHDOG_PID}" 2>/dev/null
echo "[runner] ros2 launch 已退出 rc=${RC}" >>"${RUNNER_LOG}"
exit "${RC}"
RUNNER_EOF

# ---------------------------------------------------------------------------
# 9. 启动实例 + 心跳 + 宿主侧清理兜底
# ---------------------------------------------------------------------------
LAUNCHER_PID=""
LAUNCH_PGID=""
STOP_REQUESTED=0
UNEXPECTED_EXIT=0
SHUTDOWN_DONE=0
MAIN_PID=$$

# --- 清理机制：必须在真正启动实例之前就位，保证任何退出路径都能兜底 ---
# 只操作本实例自己的进程组（${LAUNCH_PGID}），不触碰其他 ROS 2 进程、不停止容器。
graceful_shutdown() {
  [ "${SHUTDOWN_DONE}" -eq 1 ] && return 0
  SHUTDOWN_DONE=1

  local pgid="${1:-}"
  [ -z "${pgid}" ] && return 0

  if ! ctr_group_alive "${pgid}"; then
    info "本实例进程组 ${pgid} 已不存在，无需清理"
    rm -f "${POINTER_HOST}" 2>/dev/null || true
    return 0
  fi

  info "向本实例进程组 ${pgid} 发送 SIGINT（仅本实例，不影响其他 ROS 2 进程）..."
  ctr_raw "kill -INT -- -${pgid} 2>/dev/null" || true

  local waited=0
  while [ "${waited}" -lt "${SHUTDOWN_TIMEOUT}" ]; do
    ctr_group_alive "${pgid}" || break
    sleep 1
    waited=$((waited + 1))
  done

  if ctr_group_alive "${pgid}"; then
    warn "SIGINT 后 ${SHUTDOWN_TIMEOUT}s 仍有进程残留，升级为 SIGTERM"
    ctr_raw "kill -TERM -- -${pgid} 2>/dev/null" || true
    waited=0
    while [ "${waited}" -lt 6 ]; do
      ctr_group_alive "${pgid}" || break
      sleep 1
      waited=$((waited + 1))
    done
  fi

  if ctr_group_alive "${pgid}"; then
    warn "SIGTERM 后仍有残留，升级为 SIGKILL（仅本实例进程组）"
    ctr_raw "kill -KILL -- -${pgid} 2>/dev/null" || true
    sleep 2
  fi

  if ctr_group_alive "${pgid}"; then
    fail "进程组 ${pgid} 仍有残留进程，请人工检查:"
    ctr_raw "ps -eo pid,pgid,stat,cmd --no-headers | grep -E '^[[:space:]]*[0-9]+[[:space:]]+${pgid}[[:space:]]'" 2>/dev/null | sed 's/^/         /' >&2 || true
    return 1
  fi
  ok "本实例进程组 ${pgid} 已全部清理"
  # 只有在确认本实例已无存活进程时才移除“当前实例”指针。
  # 若仍有残留则保留指针，使下一次启动能据此明确拒绝，而不是误判为可启动。
  rm -f "${POINTER_HOST}" 2>/dev/null || true
  return 0
}

cleanup_all() {
  kill "${HEARTBEAT_PID:-}" 2>/dev/null || true
  rm -f "${HB_HOST}" 2>/dev/null || true
  if [ "${SHUTDOWN_DONE}" -eq 0 ]; then
    graceful_shutdown "${LAUNCH_PGID}" || true
  fi
}
trap 'cleanup_all' EXIT

touch "${HB_HOST}"

# 心跳：只在宿主主进程存活时更新。宿主被 kill -9 时该子进程会在数秒内自行退出，
# 心跳随之过期，容器内看门狗接管清理。
heartbeat_loop() {
  while kill -0 "${MAIN_PID}" 2>/dev/null; do
    touch "${HB_HOST}" 2>/dev/null || break
    sleep "${HEARTBEAT_INTERVAL}"
  done
}
heartbeat_loop &
HEARTBEAT_PID=$!

on_signal() { STOP_REQUESTED=1; }
trap on_signal INT TERM

info "启动常驻节点: ros2 launch ${LAUNCH_PKG} ${LAUNCH_FILE} ..."
docker exec -i \
  -e "RG_CTR_WS=${CTR_WS}" \
  -e "RG_RUN_DIR_CTR=${RUN_DIR_CTR}" \
  -e "RG_LAUNCH_PKG=${LAUNCH_PKG}" \
  -e "RG_LAUNCH_FILE=${LAUNCH_FILE}" \
  -e "RG_POLICY_CTR=${POLICY_CTR}" \
  -e "RG_AUDIT_CTR=${AUDIT_CTR}" \
  -e "RG_NAVSIM_CTR=${NAVSIM_CTR}" \
  -e "RG_HEARTBEAT_TIMEOUT=${HEARTBEAT_TIMEOUT}" \
  -e "RG_WATCHDOG_INTERVAL=${WATCHDOG_INTERVAL}" \
  "${CONTAINER}" bash -s <"${RUNNER_HOST}" >"${HOST_LOG}" 2>&1 &
LAUNCHER_PID=$!

# 等待容器内启动器写出 PGID（有超时，不无限等待）
# 除“文件出现”外，还必须确认该进程组确实是本项目的 ros2 launch：
# 这样即使出现竞态或 PID 复用，也不会把清理目标指向无关的进程组。
wait_for_pgid() {
  local waited=0 candidate
  while [ "${waited}" -lt 30 ]; do
    if [ -s "${RUN_DIR_HOST}/launch.pgid" ]; then
      candidate="$(tr -d ' \n' <"${RUN_DIR_HOST}/launch.pgid")"
      if [ -n "${candidate}" ] && ctr_group_is_our_launch "${candidate}"; then
        LAUNCH_PGID="${candidate}"
        return 0
      fi
    fi
    if ! kill -0 "${LAUNCHER_PID}" 2>/dev/null; then
      return 1
    fi
    sleep 1
    waited=$((waited + 1))
  done
  return 1
}

if ! wait_for_pgid; then
  fail "容器内启动器未能在 30s 内报告 ros2 launch 进程信息（提前退出或启动失败）"
  fail "启动器日志: ${HOST_LOG}"
  tail -20 "${HOST_LOG}" 2>/dev/null | sed 's/^/         /' >&2
  tail -20 "${RUN_DIR_HOST}/runner.log" 2>/dev/null | sed 's/^/         /' >&2
  tail -20 "${RUN_DIR_HOST}/launch.log" 2>/dev/null | sed 's/^/         /' >&2
  exit "${EXIT_RUNTIME}"
fi
info "ros2 launch 已在容器内启动 (pgid=${LAUNCH_PGID})，开始就绪检测 ..."

# ---------------------------------------------------------------------------
# 10. 就绪检测：轮询 Action 名称 + 类型 + 节点进程，不使用固定 sleep
# ---------------------------------------------------------------------------
ACTION_OUT=""
action_state() {  # $1=action 名；输出 MISSING / OK / TYPE_MISMATCH:...
  local line
  line="$(printf '%s\n' "${ACTION_OUT}" | grep -E "^$1[[:space:]]" | head -1)"
  if [ -z "${line}" ]; then
    echo "MISSING"
  elif printf '%s' "${line}" | grep -qF "[${ACTION_TYPE}]"; then
    echo "OK"
  else
    echo "TYPE_MISMATCH:${line}"
  fi
}

ctr_node_names() {  # 输出当前存活的常驻节点名（每行一个，排除僵尸）
  # 注意 cmdline 形如 "/usr/bin/python3 /ws/install/rg_gateway/lib/rg_gateway/security_gateway --ros-args ..."，
  # 节点名不在行尾，因此不能用 $ 锚定，直接在已过滤的行里提取名字即可。
  # 先按 stat 字段排除僵尸进程（见 ctr_node_pids 的说明）。
  ctr_raw "ps -eo stat=,cmd= --no-headers 2>/dev/null \
    | grep -vE '^[[:space:]]*Z' \
    | grep -E 'rg_gateway/lib/rg_gateway/security_gateway|rg_demo_nodes/lib/rg_demo_nodes/navigation_sim|rg_demo_nodes/lib/rg_demo_nodes/operator_node' \
    | grep -v grep \
    | grep -oE '(security_gateway|navigation_sim|operator_node)' | sort -u"
}

READY=0
READY_ELAPSED=0
LAST_PROGRESS=""
UP_STATE="UNKNOWN"
DOWN_STATE="UNKNOWN"
NODES=""
NODE_COUNT=0
while [ "${READY_ELAPSED}" -lt "${READY_TIMEOUT}" ]; do
  if [ "${STOP_REQUESTED}" -eq 1 ]; then
    break
  fi
  if ! kill -0 "${LAUNCHER_PID}" 2>/dev/null; then
    UNEXPECTED_EXIT=1
    break
  fi

  ACTION_OUT="$(ctr_ros "timeout ${ACTION_LIST_TIMEOUT} ros2 action list -t 2>/dev/null" 2>/dev/null || true)"
  UP_STATE="$(action_state "${UPSTREAM_ACTION}")"
  DOWN_STATE="$(action_state "${DOWNSTREAM_ACTION}")"
  NODES="$(ctr_node_names)"
  NODE_COUNT="$(printf '%s\n' "${NODES}" | grep -c . || true)"

  PROGRESS="up=${UP_STATE} down=${DOWN_STATE} nodes=${NODE_COUNT}/3"
  if [ "${PROGRESS}" != "${LAST_PROGRESS}" ]; then
    info "  [${READY_ELAPSED}s] 就绪检测: ${UPSTREAM_ACTION}=${UP_STATE}  ${DOWNSTREAM_ACTION}=${DOWN_STATE}  节点=${NODE_COUNT}/3"
    LAST_PROGRESS="${PROGRESS}"
  fi

  if [ "${UP_STATE}" = "OK" ] && [ "${DOWN_STATE}" = "OK" ] && [ "${NODE_COUNT}" -eq 3 ]; then
    READY=1
    break
  fi

  # 类型不匹配属于确定性错误，立即失败而不是等到超时
  case "${UP_STATE}${DOWN_STATE}" in
    *TYPE_MISMATCH*)
      fail "Action 类型不匹配，期望 [${ACTION_TYPE}]："
      [ "${UP_STATE#TYPE_MISMATCH:}" != "${UP_STATE}" ] && fail "  ${UP_STATE#TYPE_MISMATCH:}"
      [ "${DOWN_STATE#TYPE_MISMATCH:}" != "${DOWN_STATE}" ] && fail "  ${DOWN_STATE#TYPE_MISMATCH:}"
      UNEXPECTED_EXIT=1
      break
      ;;
  esac

  sleep 2
  READY_ELAPSED=$((READY_ELAPSED + 2))
done

# ---------------------------------------------------------------------------
# 11. 就绪失败处理（先清理本实例，再以非零码退出）
# ---------------------------------------------------------------------------
if [ "${STOP_REQUESTED}" -eq 1 ]; then
  info "启动过程中收到停止信号，正在清理本实例 ..."
  cleanup_all
  wait "${LAUNCHER_PID}" 2>/dev/null || true
  info "已停止（未完成启动）。日志目录: ${RUN_DIR_HOST}"
  exit "${EXIT_OK}"
fi

if [ "${READY}" -ne 1 ]; then
  rule
  fail "系统未能在 ${READY_TIMEOUT}s 内就绪。"
  case "${UP_STATE}" in
    MISSING) fail "  ${UPSTREAM_ACTION}: 未发现" ;;
    OK)      fail "  ${UPSTREAM_ACTION}: 正常" ;;
    *)       fail "  ${UPSTREAM_ACTION}: ${UP_STATE}" ;;
  esac
  case "${DOWN_STATE}" in
    MISSING) fail "  ${DOWNSTREAM_ACTION}: 未发现" ;;
    OK)      fail "  ${DOWNSTREAM_ACTION}: 正常" ;;
    *)       fail "  ${DOWNSTREAM_ACTION}: ${DOWN_STATE}" ;;
  esac
  fail "  存活常驻节点: ${NODE_COUNT}/3 (${NODES//$'\n'/, })"
  [ "${UNEXPECTED_EXIT}" -eq 1 ] && fail "  启动进程已提前退出（exit）"
  fail "正在清理本实例，详见日志:"
  fail "  ${RUN_DIR_HOST}/runner.log"
  fail "  ${RUN_DIR_HOST}/launch.log"
  fail "  ${HOST_LOG}"
  graceful_shutdown "${LAUNCH_PGID}" || true
  wait "${LAUNCHER_PID}" 2>/dev/null || true
  exit "${EXIT_READY}"
fi

# ---------------------------------------------------------------------------
# 12. 启动成功：写入实例记录（仅用于本脚本的互斥判断，不参与安全决策）
# ---------------------------------------------------------------------------
{
  echo "run_id=${RUN_ID}"
  echo "container=${CONTAINER}"
  echo "host_pid=${MAIN_PID}"
  echo "launch_pid=$(tr -d ' \n' <"${RUN_DIR_HOST}/launch.pid" 2>/dev/null)"
  echo "launch_pgid=${LAUNCH_PGID}"
  echo "started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "run_dir_host=${RUN_DIR_HOST}"
  echo "run_dir_ctr=${RUN_DIR_CTR}"
  echo "policy_path=${POLICY_CTR}"
  echo "audit_log=${AUDIT_CTR}"
  echo "navsim_record=${NAVSIM_CTR}"
  echo "launch_log=${LAUNCH_LOG_CTR}"
  echo "runner_log=${RUN_DIR_CTR}/runner.log"
  echo "ros_domain_id=${CTR_DOMAIN}"
} > "${POINTER_HOST}"
cp "${POINTER_HOST}" "${RUN_DIR_HOST}/instance.env"

rule
echo " RoboGuard 最小 ROS 2 业务基底已启动"
rule
# 说明：此处刻意不用 printf %-Ns 对齐——CJK 字符占 2 个显示列但占 3 字节，
# %-Ns 按字节补空格会导致错位。改为手工对齐到 14 显示列。
echo " 实例 ID       : ${RUN_ID}"
echo " 容器          : ${CONTAINER} (ROS_DOMAIN_ID=${CTR_DOMAIN})"
echo " 常驻节点      : operator_node / security_gateway / navigation_sim"
echo " Action(入口)  : ${UPSTREAM_ACTION} [${ACTION_TYPE}]  <- security_gateway"
echo " Action(执行端): ${DOWNSTREAM_ACTION} [${ACTION_TYPE}]  <- navigation_sim"
echo " 权威策略      : ${POLICY_CTR} (Gateway 只读加载；/rg/task_info 不是授权来源)"
echo " 审计日志      : ${RUN_DIR_HOST}/audit.jsonl"
echo " NavSim 记录   : ${RUN_DIR_HOST}/navsim_goals.jsonl"
echo " Launch 日志   : ${RUN_DIR_HOST}/launch.log"
echo " 启动器日志    : ${RUN_DIR_HOST}/runner.log"
echo " 实例进程组    : 容器内 PGID ${LAUNCH_PGID}（本实例专用，退出时只清理它）"
rule
echo " 前台运行中。按 Ctrl+C 停止本实例（不影响容器，也不影响其他 ROS 2 进程）。"
echo " 业务请求需另开终端按需提交（planner_node 不是常驻服务）："
echo
echo "   docker exec ${CONTAINER} bash -lc 'source /opt/ros/jazzy/setup.bash && cd ${CTR_WS} && source install/setup.bash && \\"
echo "     ros2 run rg_demo_nodes planner_node --ros-args -p request_id:=manual-a-1 -p frame_id:=map \\"
echo "     -p target_x:=1.5 -p target_y:=1.5 -p expect_success:=1'"
echo
echo " 查看运行日志:  tail -f ${RUN_DIR_HOST}/launch.log"
echo
warn " 注意：统一启动成功 != 已启用 SROS 2 / DDS-Security。"
warn "       当前无密码学身份认证，也无不可绕过的 DDS 资源隔离（security/ 仅为预留）。"
rule

# ---------------------------------------------------------------------------
# 13. 前台监控 + 优雅退出
# ---------------------------------------------------------------------------
while :; do
  if [ "${STOP_REQUESTED}" -eq 1 ]; then
    break
  fi
  if ! kill -0 "${LAUNCHER_PID}" 2>/dev/null; then
    UNEXPECTED_EXIT=1
    break
  fi
  sleep 1
done

if [ "${STOP_REQUESTED}" -eq 1 ]; then
  info "收到停止信号，正在优雅关闭本实例 ..."
  graceful_shutdown "${LAUNCH_PGID}"
  SHUTDOWN_RC=$?
  # 回收宿主侧 docker exec；进程组已被清理，正常会很快返回
  waited=0
  while kill -0 "${LAUNCHER_PID}" 2>/dev/null && [ "${waited}" -lt 15 ]; do
    sleep 1
    waited=$((waited + 1))
  done
  kill -0 "${LAUNCHER_PID}" 2>/dev/null && warn "宿主侧 docker exec 尚未退出（不影响容器内节点清理）"

  rule
  echo " 本实例已停止"
  rule
  echo " 实例 ID       : ${RUN_ID}"
  if [ "${SHUTDOWN_RC}" -eq 0 ]; then
    echo " 清理结果      : 本实例进程组已全部清理"
  else
    echo " 清理结果      : 存在残留，请人工检查（见上方错误）"
  fi
  echo " 容器状态      : $(docker inspect -f '{{.State.Running}}' "${CONTAINER}" 2>/dev/null | sed 's/true/运行中（保留）/; s/false/已停止/')"
  echo " 日志保留      : ${RUN_DIR_HOST}"
  echo "   - audit.jsonl        : $(wc -l < "${RUN_DIR_HOST}/audit.jsonl" 2>/dev/null || echo 0) 条"
  echo "   - navsim_goals.jsonl : $(wc -l < "${RUN_DIR_HOST}/navsim_goals.jsonl" 2>/dev/null || echo 0) 条"
  echo "   - launch.log         : 完整 ros2 launch 输出"
  echo "   - runner.log         : 启动器/看门狗消息"
  rule
  exit "${EXIT_OK}"
fi

# 非用户请求的退出：说明 launch 提前结束
rule
fail "ros2 launch 进程意外退出（非用户停止）。"
fail "  launch 日志: ${RUN_DIR_HOST}/launch.log"
fail "  启动器日志: ${RUN_DIR_HOST}/runner.log"
tail -15 "${RUN_DIR_HOST}/runner.log" 2>/dev/null | sed 's/^/         /' >&2
tail -10 "${RUN_DIR_HOST}/launch.log" 2>/dev/null | sed 's/^/         /' >&2
graceful_shutdown "${LAUNCH_PGID}" || true
exit "${EXIT_RUNTIME}"
