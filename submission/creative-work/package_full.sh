#!/usr/bin/env bash
# package_full.sh -- 生成**完整在线作品包**（含 ROS 2 运行源码）
#
# 与 package.sh（离线展示包）的区别：
#   - 本脚本额外打包 runtime/（ROS 2 源码、脚本、配置、schema、Mock、测试挂具）
#   - 附带 docker/（Dockerfile + 构建脚本）
#   - 排除密钥、keystore、私钥、.git、构建产物与大文件
#
# 1.0.2 修复（对应独立复现报告 D-01/D-02/D-05）：
#   * docs/interfaces 必须保留父目录，落到 runtime/docs/interfaces
#     （旧实现 cp -a docs/interfaces runtime/ 会拍平成 runtime/interfaces，
#      而全部代码按 runtime/docs/interfaces/... 读取）
#   * 白名单补上 mock_modules（受控在线 M1/M2 Mock）与 tests（三真实 M1
#     需要的私有观测 fixture、enforce 需要的 sros2_check.py）
#   * 取消会吞掉复制失败的 2>/dev/null || true，改为 fail-fast
#   * 打包后执行完整性门禁，缺任何必需文件直接失败，不产出"看似完整"的包
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
VER="${1:-1.0.3}"
TOP="RosSystem-CreativeWork-Full"
OUT="$HERE/dist"
mkdir -p "$OUT"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
ROOT="$STAGE/$TOP"
mkdir -p "$ROOT"

# 受测核心（安全判定基线）与归档提交是**不同**的 SHA，必须分别记录，不得混用。
BASELINE_CORE_SHA="2f3de257c9eac873093201292f6b2a9571da4f03"
ARCHIVE_BASELINE_SHA="e69325d8094e1d2bc309772650ae85a241751b31"
SOURCE_COMMIT="$(git -C "$REPO" rev-parse HEAD 2>/dev/null || echo UNKNOWN)"
# 只统计“已跟踪文件的修改”，未跟踪的发布产物不算源码脏。
SOURCE_DIRTY="$(git -C "$REPO" status --porcelain --untracked-files=no 2>/dev/null | wc -l | tr -d ' ')"
BUILT_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

echo "== 1) 展示层 =="
for item in dashboard replay tests docs run.sh stop.sh verify_package.sh README.md; do
  [ -e "$HERE/$item" ] || { echo "ERROR: 缺少展示层文件 $item" >&2; exit 1; }
  cp -a "$HERE/$item" "$ROOT/"
done
cp -a "$HERE/package_full.sh" "$ROOT/"
if [ -d "$HERE/reports" ]; then cp -a "$HERE/reports" "$ROOT/"; fi

echo "== 2) 运行源码（白名单，保持仓库相对布局） =="
mkdir -p "$ROOT/runtime"
# 注意：docs/interfaces 必须单独处理，cp -a 到 runtime/ 会把父目录拍平。
for item in src modules scripts config mock_modules tests identity_trust security; do
  [ -e "$REPO/$item" ] || { echo "ERROR: 仓库缺少必需目录 $item" >&2; exit 1; }
  case "$item" in
    security)
      # 只带**公开策略定义**，绝不带 keystore/私钥
      mkdir -p "$ROOT/runtime/security"
      [ -d "$REPO/security/policies" ] || { echo "ERROR: 缺少 security/policies" >&2; exit 1; }
      cp -a "$REPO/security/policies" "$ROOT/runtime/security/"
      ;;
    *)
      cp -a "$REPO/$item" "$ROOT/runtime/"
      ;;
  esac
done

# 接口契约：保留仓库相对路径 runtime/docs/interfaces
[ -d "$REPO/docs/interfaces" ] || { echo "ERROR: 缺少 docs/interfaces" >&2; exit 1; }
mkdir -p "$ROOT/runtime/docs"
cp -a "$REPO/docs/interfaces" "$ROOT/runtime/docs/"

for f in README.md environment.md requirements.md; do
  if [ -f "$REPO/$f" ]; then cp -a "$REPO/$f" "$ROOT/runtime/"; fi
done

echo "== 2b) 1.1.0 研究证据（只含非秘密材料） =="
mkdir -p "$ROOT/evidence"
for d in m2_sros2_enforce_v110 m2_sros2_enforce_v110_negative m2_lab_identity_v110 m2_gateway_identity_v110 research_v110; do
  src="$REPO/artifacts/acceptance/exports/$d"
  [ -d "$src" ] || { echo "ERROR: 缺少研究证据目录 $d" >&2; exit 1; }
  cp -a "$src" "$ROOT/evidence/"
done
if find "$ROOT/evidence" -type f \( -name '*.pem' -o -name '*.key' -o -name '*.p7s' \) | grep -q .; then
  echo "ERROR: 研究证据中包含密钥/证书材料，拒绝打包" >&2; exit 1
fi

echo "== 3) Docker 运行环境 =="
cp -a "$HERE/docker" "$ROOT/"

echo "== 4) 版本与构建清单 =="
cat > "$ROOT/VERSION.json" <<JSON
{
  "product": "RosSystem Creative Work",
  "package": "$TOP",
  "version": "$VER",
  "artifact_commit": "$SOURCE_COMMIT",
  "baseline_core_sha": "$BASELINE_CORE_SHA",
  "archive_baseline_sha": "$ARCHIVE_BASELINE_SHA",
  "modes": {"replay": "无需 ROS 2/Docker", "online": "需要 Docker + ROS 2 Jazzy"},
  "acceptance_in_archive": "NOT_SUPPORTED_IN_ARCHIVE",
  "acceptance_note": "严格 acceptance 需要完整 Git 检出的 40 位 SHA 与干净工作树；本包不含 .git，请在原仓库执行 --mode acceptance。"
}
JSON

cat > "$ROOT/runtime/BUILD_INFO.json" <<JSON
{
  "package": "$TOP",
  "version": "$VER",
  "built_at": "$BUILT_AT",
  "artifact_commit": "$SOURCE_COMMIT",
  "source_tree_dirty_entries": $SOURCE_DIRTY,
  "baseline_core_sha": "$BASELINE_CORE_SHA",
  "archive_baseline_sha": "$ARCHIVE_BASELINE_SHA",
  "runtime_layout": "runtime/docs/interfaces",
  "note": "本包不含 .git。artifact_commit 是生成该包的源码提交，baseline_core_sha 是安全判定所基于的历史受测核心；两者不得混用。"
}
JSON

echo "== 5) 安全扫描 =="
BAD="$(find "$ROOT" -type f \( -name '*.pem' -o -name '*.key' -o -name '*.p7s' -o -name 'id_rsa*' -o -name '*.crt' \) 2>/dev/null | grep -v '/security/policies/' || true)"
if [ -n "$BAD" ]; then
  echo "ERROR: 检测到密钥材料，拒绝打包：" >&2; echo "$BAD" >&2; exit 1
fi
if find "$ROOT" -type d -name keystore 2>/dev/null | grep -q .; then
  echo "ERROR: 检测到 keystore 目录，拒绝打包" >&2; exit 1
fi
rm -rf "$ROOT"/*/.git 2>/dev/null || true
find "$ROOT" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$ROOT" -name '*.pyc' -delete 2>/dev/null || true

echo "== 6) 打包完整性门禁 =="
REQUIRED=(
  runtime/docs/interfaces/examples/module_input_valid.json
  runtime/docs/interfaces/schemas/module_input.schema.json
  runtime/docs/interfaces/schemas/comm_risk_evidence.schema.json
  runtime/docs/interfaces/schemas/identity_trust_assessment.schema.json
  runtime/docs/interfaces/schemas/task_risk_decision.schema.json
  runtime/mock_modules/comm_risk_mock.py
  runtime/mock_modules/identity_trust_mock.py
  runtime/mock_modules/_protocol.py
  runtime/tests/fixtures/member1/rospace_comm_rows.json
  runtime/tests/integration/sros2_check.py
  runtime/scripts/final_system.sh
  runtime/scripts/run_three_real_online.py
  runtime/scripts/m3_online_drive.sh
  runtime/config/team_modules.member3.real.yaml
  runtime/config/team_modules.three-real.yaml
  runtime/config/task_policy.yaml
  runtime/security/policies/minimal_permissions.xml
  runtime/src/rg_interfaces/package.xml
  runtime/src/rg_gateway/package.xml
  runtime/identity_trust/assessor.py
  runtime/BUILD_INFO.json
  reports/ROSYSTEM_1_1_0_RESEARCH_AND_SECURITY_VALIDATION_REPORT.md
  evidence/research_v110/p01_p12_matrix.json
  dashboard/server.py
  dashboard/docker_runtime.py
  dashboard/evidence_loader.py
  dashboard/run_controller.py
  dashboard/static/index.html
  dashboard/static/app.js
  run.sh
  stop.sh
)
MISSING=0
for rel in "${REQUIRED[@]}"; do
  if [ ! -f "$ROOT/$rel" ]; then echo "  [MISSING] $rel" >&2; MISSING=1; fi
done
if [ "$MISSING" -ne 0 ]; then
  echo "ERROR: 打包完整性门禁失败，拒绝生成压缩包" >&2
  exit 1
fi
echo "  完整性门禁通过：${#REQUIRED[@]} 项必需文件全部存在"

echo "== 7) 生成压缩包（含顶层目录） =="
TAR="$OUT/$TOP-$VER.tar.gz"
tar -czf "$TAR" -C "$STAGE" "$TOP"
SIZE=$(stat -c %s "$TAR")
HASH=$(sha256sum "$TAR" | cut -d' ' -f1)
echo "$HASH  $(basename "$TAR")" > "$TAR.sha256"
echo "文件: $TAR"
echo "大小: $SIZE bytes"
echo "SHA-256: $HASH"
cat > "$OUT/$TOP-$VER.manifest.txt" <<MAN
file=$(basename "$TAR")
size_bytes=$SIZE
sha256=$HASH
top_dir=$TOP
version=$VER
artifact_commit=$SOURCE_COMMIT
baseline_core_sha=$BASELINE_CORE_SHA
archive_baseline_sha=$ARCHIVE_BASELINE_SHA
generated=$BUILT_AT
MAN
echo "清单: $OUT/$TOP-$VER.manifest.txt"
echo "校验: $TAR.sha256"
