#!/usr/bin/env bash
# 本地复现 .github/workflows/member-module-gates.yml 的全部检查。
#
# 为什么需要它：CI 的凭据扫描会对**所有被跟踪文件** grep 敏感模式，
# 一旦某个测试源码里出现这些字面量，扫描会把测试文件本身判为疑似泄露。
# 本地先跑一遍可以在推送前发现这类问题，避免"推上去才发现 CI 红"。
#
# 用法：scripts/run_ci_checks_locally.sh
# 需要：python3（含 jsonschema>=4 与 pyyaml）
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

FAIL=0
step() { echo; echo "=== $* ==="; }
fail() { echo "  [FAIL] $*"; FAIL=1; }

step "检查 1a —— 契约校验"
if python3 scripts/validate_team_contracts.py --all --quiet; then
  echo "  [PASS] CONTRACT_OK"
else
  fail "契约校验未通过"
fi

step "检查 1b —— Schema 与样例覆盖"
if python3 scripts/check_schema_coverage.py; then
  echo "  [PASS] 覆盖检查通过"
else
  fail "覆盖检查未通过"
fi

step "检查 2 —— Python 基础语法"
python3 - <<'PY' || FAIL=1
import ast, pathlib, sys
bad = []
for path in pathlib.Path('.').rglob('*.py'):
    parts = set(path.parts)
    if parts & {'build', 'install', 'log', 'logs', '.git',
                'tests/evidence', '.research-venv'}:
        continue
    if 'site-packages' in path.parts:
        continue
    try:
        ast.parse(path.read_text(encoding='utf-8', errors='replace'))
    except SyntaxError as exc:
        bad.append('{0}: {1}'.format(path, exc))
if bad:
    print('  [FAIL] ' + '\n'.join(bad)); sys.exit(1)
print('  [PASS] 全部 Python 文件语法通过')
PY

step "检查 3 —— 模板与验收工具自测"
if python3 templates/member_module/test_module.py >/dev/null 2>&1; then
  echo "  [PASS] 模板自测通过"
else
  fail "模板自测未通过"
fi
python3 scripts/check_member_module.py --help >/dev/null 2>&1 \
  && python3 scripts/init_member_module.py --help >/dev/null 2>&1 \
  && echo "  [PASS] 验收工具与 init 工具可运行" || fail "工具 --help 失败"

step "检查 4 —— PR 模板"
PRT=.github/PULL_REQUEST_TEMPLATE.md
if [ -f "$PRT" ]; then
  ok=1
  for key in 'baseline 来源 SHA' '算法真实性' '安全边界' '合入门槛'; do
    grep -q "$key" "$PRT" || { fail "PR 模板缺少: $key"; ok=0; }
  done
  [ "$ok" = 1 ] && echo "  [PASS] PR 模板完整"
else
  fail "缺少 $PRT"
fi

step "检查 5 —— 敏感材料与大文件"
python3 - <<'PY' || FAIL=1
import re, subprocess, sys
files = subprocess.run(['git', 'ls-files'], capture_output=True,
                       text=True).stdout.splitlines()
bad = []

keys = [f for f in files
        if re.search(r'\.(pem|key|p12|pfx|crt|csr|der|srl)$', f)
        and not f.startswith(('security/keystore/', 'security/enclaves/'))
        and 'certifi' not in f and 'site-packages' not in f]
if keys:
    bad.append('密钥类文件: {0}'.format(keys))

for pattern in (r'^data/', r'^training_runs/', r'^models/', r'\.joblib$', r'\.tar\.gz$'):
    hits = [f for f in files if re.search(pattern, f)]
    if hits:
        bad.append('匹配 {0}: {1}'.format(pattern, hits))

if 'gitlog.md' in files:
    bad.append('gitlog.md 被跟踪')

cred = re.compile(r'(AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{20,}|BEGIN [A-Z ]*PRIVATE KEY)')
for f in files:
    if f.endswith(('.docx', '.png', '.jpg', '.pcap')):
        continue
    if f.startswith(('tests/evidence/', '.research-venv/')):
        continue
    try:
        text = open(f, 'rb').read().decode('utf-8', errors='ignore')
    except OSError:
        continue
    m = cred.search(text)
    if m:
        bad.append('疑似凭据泄露 {0}: {1}'.format(f, m.group(0)[:40]))

tree = subprocess.run(['git', 'ls-tree', '-r', '-l', 'HEAD'],
                      capture_output=True, text=True).stdout
for line in tree.splitlines():
    parts = line.split(None, 4)
    if len(parts) < 5:
        continue
    size, path = parts[3], parts[4]
    if path.endswith('.docx'):
        continue
    try:
        if int(size) > 5 * 1024 * 1024:
            bad.append('过大文件 {0} ({1})'.format(path, size))
    except ValueError:
        pass

if bad:
    for item in bad:
        print('  [FAIL] ' + item)
    sys.exit(1)
print('  [PASS] 无密钥 / 无数据模型 / 无 gitlog / 无凭据泄露 / 无过大文件')
PY

echo
if [ "$FAIL" = 0 ]; then
  echo "LOCAL_CI_MIRROR: PASS"
else
  echo "LOCAL_CI_MIRROR: FAIL"
fi
exit "$FAIL"
