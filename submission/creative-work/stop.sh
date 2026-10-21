#!/usr/bin/env bash
# stop.sh -- 停止控制台（只匹配本作品的 server.py，不做全局 pkill）
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIDFILE="$HERE/.dashboard.pid"
if [ -f "$PIDFILE" ]; then
  PID="$(cat "$PIDFILE")"
  if kill -0 "$PID" 2>/dev/null; then
    kill -TERM "$PID" && echo "已停止控制台 PID=$PID"
    rm -f "$PIDFILE"; exit 0
  fi
  rm -f "$PIDFILE"
fi
# 兜底：只匹配本目录的 server.py
PIDS="$(ps -eo pid=,args= | grep -F "$HERE/dashboard/server.py" | grep -v grep | awk '{print $1}')"
if [ -n "$PIDS" ]; then
  echo "$PIDS" | xargs -r kill -TERM
  echo "已停止控制台：$PIDS"; exit 0
fi
echo "未发现运行中的控制台"; exit 0
