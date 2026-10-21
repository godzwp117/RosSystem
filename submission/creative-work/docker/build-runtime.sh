#!/usr/bin/env bash
# build-runtime.sh -- 构建作品运行镜像（一次性，需联网拉基础镜像）
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE="${ROS_IMAGE:-rosystem-jazzy:1.0.0}"
echo "构建镜像: $IMAGE（基础镜像 ros:jazzy 需联网一次）"
docker build -t "$IMAGE" "$HERE"
echo "完成。运行时请设置 ROS_IMAGE=$IMAGE"
