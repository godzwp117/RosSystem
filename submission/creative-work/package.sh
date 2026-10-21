#!/usr/bin/env bash
# package.sh -- 生成可执行参赛作品包（自动排除密钥材料）
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VER="${1:-1.0.0}"
OUT="$HERE/dist"
NAME="RosSystem-creative-work-$VER"
mkdir -p "$OUT"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

for item in dashboard replay tests docs run.sh stop.sh package.sh verify_package.sh README.md; do
  [ -e "$HERE/$item" ] && cp -a "$HERE/$item" "$STAGE/"
done

BAD="$(find "$STAGE" -type f \( -name '*.pem' -o -name '*.key' -o -name '*.p7s' -o -name 'id_rsa*' \) 2>/dev/null | head -5)"
if [ -n "$BAD" ]; then
  echo "ERROR: 作品包中检测到密钥材料，拒绝打包：" >&2; echo "$BAD" >&2; exit 1
fi

TAR="$OUT/$NAME.tar.gz"
tar -czf "$TAR" -C "$STAGE" .
echo "已生成: $TAR"
echo "大小: $(du -h "$TAR" | cut -f1)"
sha256sum "$TAR" | tee "$TAR.sha256"
