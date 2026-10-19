#!/usr/bin/env bash
# member_env.sh -- 多成员开发环境的轻量配置解析（F0 / 任务 A）。
#
# 设计目标
# --------
# 「一成员一工作区、一容器、一开发 Domain」的 MVP 模式：
# 每名成员在自己的仓库副本上工作，用自己的容器名与开发 Domain，互不干扰。
#
# 为什么不用独立配置文件
# ----------------------
# 成员配置很少变化（4 条固定记录），引入 YAML/JSON 配置文件会多一层解析依赖，
# 也会让"配置从哪来"变得不透明。这里用环境变量 + 内建注册表：
#   * `RG_MEMBER` 选择成员档位；
#   * 显式的 `RG_CONTAINER` / `RG_DOMAIN_ID` 优先级最高；
#   * 两者冲突时**报错而不是猜**，避免"以为在用自己的环境"。
#
# 重要说明（不要把开发约定当成安全边界）
# --------------------------------------
# 这里的容器名与 Domain 号只是**开发约定**，用于避免成员之间互相看到对方的节点：
#   * 它们**不是** DDS 安全身份，不参与任何认证或授权判断；
#   * ROS Domain 只做发现隔离，**不提供密码学隔离**；
#   * 真正的身份与授权由安全通信配置（Enclave / 权限）承担，见 security/。
# 另外：单机共享 root 的容器**不能**宣称实现了成员间的强身份隔离。

# 成员注册表：成员标识 -> "容器名 开发Domain"
# 51..54 为成员开发域；M2 的安全测试域 43 保留其独立用途，不复用。
rg_member_profile() {
  case "$1" in
    1|member1|person1|人员一) echo "rg_member1 51" ;;
    2|member2|person2|人员二) echo "rg_member2 52" ;;
    3|member3|person3|人员三) echo "rg_member3 53" ;;
    4|member4|person4|人员四) echo "rg_member4 54" ;;
    *) return 1 ;;
  esac
}

rg_member_usage() {
  cat <<'EOF'
成员标识可选值：
  1 | member1 | person1 | 人员一   -> 容器 rg_member1, 开发 Domain 51
  2 | member2 | person2 | 人员二   -> 容器 rg_member2, 开发 Domain 52
  3 | member3 | person3 | 人员三   -> 容器 rg_member3, 开发 Domain 53
  4 | member4 | person4 | 人员四   -> 容器 rg_member4, 开发 Domain 54
EOF
}

# 解析 RG_MEMBER，把结果写入 RG_CONTAINER / RG_DOMAIN_ID（仅在未显式指定时）。
# 显式指定与成员档位冲突时直接失败，不做猜测。
rg_apply_member_profile() {
  [ -n "${RG_MEMBER:-}" ] || return 0

  local profile container domain
  if ! profile="$(rg_member_profile "${RG_MEMBER}")"; then
    echo "ERROR: 未知成员标识 RG_MEMBER='${RG_MEMBER}'。" >&2
    rg_member_usage >&2
    return 2
  fi
  container="${profile%% *}"
  domain="${profile##* }"

  if [ -n "${RG_CONTAINER_EXPLICIT:-}" ] && [ "${RG_CONTAINER}" != "${container}" ]; then
    echo "ERROR: 配置冲突 —— RG_MEMBER='${RG_MEMBER}' 对应容器 '${container}'，" >&2
    echo "       但显式指定了 RG_CONTAINER='${RG_CONTAINER}'。" >&2
    echo "       两者只能留一个，避免在非预期环境里构建/运行。" >&2
    return 2
  fi
  if [ -n "${RG_DOMAIN_EXPLICIT:-}" ] && [ "${RG_DOMAIN_ID}" != "${domain}" ]; then
    echo "ERROR: 配置冲突 —— RG_MEMBER='${RG_MEMBER}' 对应开发 Domain ${domain}，" >&2
    echo "       但显式指定了 ROS_DOMAIN_ID='${RG_DOMAIN_ID}'。" >&2
    echo "       两者只能留一个，避免误用他人的通信域。" >&2
    return 2
  fi

  RG_CONTAINER="${container}"
  RG_DOMAIN_ID="${domain}"
  export RG_CONTAINER RG_DOMAIN_ID
  return 0
}

# 读取容器创建时固化的环境变量值（容器环境不随宿主机后来修改而变化）。
rg_container_env() {  # $1=容器名 $2=变量名
  docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$1" 2>/dev/null \
    | sed -n "s/^$2=//p" | head -1
}

# 本次运行实际生效的 Domain：
#   * 显式指定（RG_DOMAIN_ID / RG_MEMBER）时用显式值；
#   * 否则采用容器创建时固化的值。
# 注意：必须把结果**记录下来**，不能假设"宿主机改了环境变量容器就会跟着变"。
rg_effective_domain() {  # $1=容器名
  local container="$1"
  if [ -n "${RG_DOMAIN_ID:-}" ]; then
    echo "${RG_DOMAIN_ID}"
    return 0
  fi
  rg_container_env "${container}" ROS_DOMAIN_ID
}

# 规范化工作区路径，避免符号链接/相对路径造成假匹配。
rg_normalize_path() {
  local path="$1"
  if command -v realpath >/dev/null 2>&1; then
    realpath -m "${path}" 2>/dev/null && return 0
  fi
  if command -v readlink >/dev/null 2>&1; then
    readlink -f "${path}" 2>/dev/null && return 0
  fi
  ( cd "${path}" 2>/dev/null && pwd -P ) || echo "${path}"
}
