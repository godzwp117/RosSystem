#!/usr/bin/env bash
# verify_package.sh -- 校验作品包：可解包、可启动、不含敏感材料
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TAR="${1:-}"
PASS=0; FAIL=0
ok(){ echo "  [PASS] $1"; PASS=$((PASS+1)); }
no(){ echo "  [FAIL] $1 -- $2"; FAIL=$((FAIL+1)); }

if [ -z "$TAR" ]; then TAR="$(ls -t "$HERE/dist"/*.tar.gz 2>/dev/null | head -1)"; fi
[ -z "$TAR" ] && { echo "未找到作品包" >&2; exit 2; }
echo "校验: $TAR"

W="$(mktemp -d)"; trap 'rm -rf "$W"' EXIT
tar -xzf "$TAR" -C "$W" 2>/dev/null
for f in run.sh stop.sh dashboard/server.py dashboard/evidence_loader.py \
         dashboard/run_controller.py dashboard/static/index.html \
         dashboard/static/app.js dashboard/static/style.css \
         replay/replay_manifest.json README.md; do
  [ -f "$W/$f" ] && ok "包含 $f" || no "缺少 $f" "文件不存在"
done
if [ -z "$(find "$W" -type f \( -name '*.pem' -o -name '*.key' -o -name '*.p7s' \) 2>/dev/null)" ]; then
  ok "不含密钥材料"
else
  no "含密钥材料" "打包不应包含密钥"
fi

PORT=$(( (RANDOM % 2000) + 18000 ))
( cd "$W" && PYTHON=python3 PORT=$PORT ./run.sh > "$W/boot.log" 2>&1 & )
for _ in $(seq 1 40); do
  curl -sS -o /dev/null "http://127.0.0.1:$PORT/api/health" 2>/dev/null && break
  sleep 0.25
done
CODE=$(curl -sS -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/" 2>/dev/null)
[ "$CODE" = "200" ] && ok "解包后可启动并返回页面（HTTP 200）" || no "启动失败" "HTTP $CODE"
if curl -sS "http://127.0.0.1:$PORT/api/replay" 2>/dev/null | grep -q 'rosystem-replay-snapshot'; then
  ok "回放证据接口可用"
else
  no "回放接口失败" "无有效响应"
fi
for p in $(ps -eo pid=,args= | awk -v port="$PORT" '/dashboard\/server\.py/ && index($0, port) && !/awk/ {print $1}'); do
  kill -TERM "$p" 2>/dev/null
done

echo
echo "结果: ${PASS} passed / $((PASS+FAIL)) total"
if [ "$FAIL" -eq 0 ]; then echo "PACKAGE_VERIFY=PASS"; exit 0; fi
echo "PACKAGE_VERIFY=FAIL"; exit 1
