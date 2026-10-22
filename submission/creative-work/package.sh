#!/usr/bin/env bash
# package.sh -- 生成可执行的**离线回放**作品包（自动排除密钥材料）
#
# 1.0.2：补上完整性门禁与可移植的 .sha256（旧实现把绝对路径写进校验文件，
# 换目录后 sha256sum -c 会找不到文件）。
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VER="${1:-1.0.3}"
OUT="$HERE/dist"
NAME="RosSystem-creative-work-$VER"
mkdir -p "$OUT"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

for item in dashboard replay tests docs reports run.sh stop.sh package.sh package_full.sh verify_package.sh README.md; do
  [ -e "$HERE/$item" ] || { echo "ERROR: 缺少 $item" >&2; exit 1; }
  cp -a "$HERE/$item" "$STAGE/"
done
# paper/ lives at the repository root, not under submission/creative-work.
PAPER_SRC="$(cd "$HERE/../.." && pwd)/paper"
[ -d "$PAPER_SRC" ] || { echo "ERROR: 缺少 $PAPER_SRC" >&2; exit 1; }
cp -a "$PAPER_SRC" "$STAGE/paper"

find "$STAGE" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$STAGE" -name '*.pyc' -delete 2>/dev/null || true

BAD="$(find "$STAGE" -type f \( -name '*.pem' -o -name '*.key' -o -name '*.p7s' -o -name 'id_rsa*' \) 2>/dev/null | head -5 || true)"
if [ -n "$BAD" ]; then
  echo "ERROR: 作品包中检测到密钥材料，拒绝打包：" >&2; echo "$BAD" >&2; exit 1
fi

REQUIRED=(run.sh stop.sh dashboard/server.py dashboard/evidence_loader.py \
          reports/ROSYSTEM_1_1_0_RESEARCH_AND_SECURITY_VALIDATION_REPORT.md \
          paper/PAPER_FACTS_FINAL.md paper/EXPERIMENT_RESULTS.csv \
          dashboard/run_controller.py dashboard/docker_runtime.py \
          dashboard/static/index.html dashboard/static/app.js \
          dashboard/static/style.css replay/replay_manifest.json README.md)
MISSING=0
for rel in "${REQUIRED[@]}"; do
  [ -f "$STAGE/$rel" ] || { echo "  [MISSING] $rel" >&2; MISSING=1; }
done
[ "$MISSING" -eq 0 ] || { echo "ERROR: 离线包完整性门禁失败" >&2; exit 1; }

TAR="$OUT/$NAME.tar.gz"
tar -czf "$TAR" -C "$STAGE" .
SIZE=$(stat -c %s "$TAR")
HASH=$(sha256sum "$TAR" | cut -d' ' -f1)
echo "$HASH  $(basename "$TAR")" > "$TAR.sha256"
echo "已生成: $TAR"
echo "大小: $SIZE bytes"
echo "SHA-256: $HASH"
