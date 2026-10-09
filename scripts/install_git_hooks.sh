#!/usr/bin/env bash
# 安装本地 Git 守卫（pre-commit / pre-push）。
#
# 说明：钩子不随版本库分发，必须每台开发机各自安装一次。
# 因此除本安装脚本外，CI 中另有一道独立检查，避免"忘记装钩子"导致漏网。
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOK_DIR="$(git -C "${REPO_ROOT}" rev-parse --git-dir)/hooks"
[ -d "${HOOK_DIR}" ] || mkdir -p "${HOOK_DIR}"
for hook in pre-commit pre-push; do
  src="${REPO_ROOT}/scripts/hooks/${hook}"
  dst="${HOOK_DIR}/${hook}"
  [ -f "${src}" ] || { echo "ERROR: 缺少 ${src}" >&2; exit 1; }
  if [ -f "${dst}" ] && ! grep -q "仅限本地" "${dst}" 2>/dev/null; then
    cp -f "${dst}" "${dst}.bak.$(date +%s)"
    echo "  已备份原有 ${hook}"
  fi
  cp -f "${src}" "${dst}"
  chmod +x "${dst}"
  echo "  已安装 ${hook} -> ${dst}"
done
echo "完成。可用以下方式自测："
echo "  git add -f gitlog.md && git commit -m test   # 应被拒绝"
