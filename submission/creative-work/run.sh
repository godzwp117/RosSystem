#!/usr/bin/env bash
# run.sh -- 启动 RosSystem 跨层安全决策控制台
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${PORT:-8787}"
PY="${PYTHON:-python3}"

echo "=============================================="
echo " RosSystem 跨层安全决策可视化控制台"
echo " 端口: $PORT   只监听 127.0.0.1"
echo "=============================================="

"$PY" - "$HERE" <<'PYCHK'
import sys, os
here = sys.argv[1]
sys.path.insert(0, os.path.join(here, 'dashboard'))
try:
    import evidence_loader  # noqa: F401
    import run_controller   # noqa: F401
except Exception as exc:
    print('依赖检查失败:', exc); raise SystemExit(1)
print('依赖检查: OK（仅标准库）')
PYCHK

exec "$PY" "$HERE/dashboard/server.py" --host 127.0.0.1 --port "$PORT"
