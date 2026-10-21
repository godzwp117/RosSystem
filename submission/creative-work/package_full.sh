#!/usr/bin/env bash
# package_full.sh -- 生成**完整在线作品包**（含 ROS 2 运行源码）
#
# 与 package.sh（离线展示包）的区别：
#   - 本脚本额外打包 runtime/（ROS 2 源码、脚本、配置、schema）
#   - 附带 docker/（Dockerfile + 构建脚本）
#   - 排除密钥、keystore、私钥、.git、构建产物与大文件
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
VER="${1:-1.0.1}"
TOP="RosSystem-CreativeWork-Full"
OUT="$HERE/dist"
mkdir -p "$OUT"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
ROOT="$STAGE/$TOP"
mkdir -p "$ROOT"

echo "== 1) 展示层 =="
for item in dashboard replay tests docs run.sh stop.sh verify_package.sh README.md; do
  [ -e "$HERE/$item" ] && cp -a "$HERE/$item" "$ROOT/"
done
cp -a "$HERE/package_full.sh" "$ROOT/"

echo "== 2) 运行源码（白名单） =="
mkdir -p "$ROOT/runtime"
for item in src modules scripts config docs/interfaces identity_trust security; do
  [ -e "$REPO/$item" ] || continue
  case "$item" in
    security)
      # 只带**公开策略定义**，绝不带 keystore/私钥
      mkdir -p "$ROOT/runtime/security"
      [ -d "$REPO/security/policies" ] && cp -a "$REPO/security/policies" "$ROOT/runtime/security/"
      ;;
    *)
      cp -a "$REPO/$item" "$ROOT/runtime/" 2>/dev/null || true
      ;;
  esac
done
for f in README.md environment.md requirements.md; do
  [ -f "$REPO/$f" ] && cp -a "$REPO/$f" "$ROOT/runtime/" 2>/dev/null
done

echo "== 3) Docker 运行环境 =="
cp -a "$HERE/docker" "$ROOT/"

echo "== 4) 版本与清单 =="
cat > "$ROOT/VERSION.json" <<JSON
{
  "product": "RosSystem Creative Work",
  "package": "$TOP",
  "version": "$VER",
  "tested_core_sha": "2f3de257c9eac873093201292f6b2a9571da4f03",
  "release_branch_sha": "c5556e4be7008029c5a2b2b7b5fb752aa4b12c62",
  "modes": {"replay": "无需 ROS 2/Docker", "online": "需要 Docker + ROS 2 Jazzy"},
  "acceptance_in_archive": "NOT_SUPPORTED_IN_ARCHIVE",
  "acceptance_note": "严格 acceptance 需要完整 Git 检出的 40 位 SHA 与干净工作树；本包不含 .git，请在原仓库执行 --mode acceptance。"
}
JSON

echo "== 5) 安全扫描 =="
BAD="$(find "$ROOT" -type f \( -name '*.pem' -o -name '*.key' -o -name '*.p7s' -o -name 'id_rsa*' -o -name '*.crt' \) 2>/dev/null | grep -v '/security/policies/' | head -10)"
if [ -n "$BAD" ]; then
  echo "ERROR: 检测到密钥材料，拒绝打包：" >&2; echo "$BAD" >&2; exit 1
fi
if find "$ROOT" -type d -name keystore 2>/dev/null | grep -q .; then
  echo "ERROR: 检测到 keystore 目录，拒绝打包" >&2; exit 1
fi
rm -rf "$ROOT"/*/.git 2>/dev/null || true

echo "== 6) 生成压缩包（含顶层目录） =="
TAR="$OUT/$TOP-$VER.tar.gz"
tar -czf "$TAR" -C "$STAGE" "$TOP"
SIZE=$(du -h "$TAR" | cut -f1)
HASH=$(sha256sum "$TAR" | cut -d' ' -f1)
echo "文件: $TAR"
echo "大小: $SIZE"
echo "SHA-256: $HASH"
cat > "$OUT/$TOP-$VER.manifest.txt" <<MAN
file=$TAR
size=$SIZE
sha256=$HASH
top_dir=$TOP
tested_core_sha=2f3de257c9eac873093201292f6b2a9571da4f03
generated=$(date -u +%Y-%m-%dT%H:%M:%SZ)
MAN
echo "清单: $OUT/$TOP-$VER.manifest.txt"
