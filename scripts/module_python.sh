#!/bin/bash
# module_python.sh -- 为外部研究模块固定一个满足依赖的解释器。
#
# 为什么需要它
# ------------
# 成员交付配置的命令首部是裸 `python3`。在 Debian/Ubuntu 上系统 python3 的
# jsonschema 往往是 3.x，无法构造 Draft 2020-12 校验器；三个模块会在
# `validate(envelope, 'module_input')` 抛 ImportError，然后**正确**地
# 失败关闭并退出 2。适配层如实记录 ADAPTER_MODULE_EXIT_NONZERO，
# 但人看到的是"模块坏了"，而不是"解释器不合格"。
#
# 工作 A 的交接文件明确要求 B1 显式固定解释器。本脚本就是那个固定点：
# 它**先验证**候选解释器真的能构造 Draft 2020-12 校验器，再 exec，
# 绝不"看起来能跑就上"。
#
# 选择顺序（全部都要通过同一项自检）
#   1. $ROS_MODULE_PYTHON                      —— 显式覆盖，最高优先
#   2. <repo>/.research-venv/bin/python        —— 本地开发 venv
#   3. <repo>/tests/evidence/research-venv/bin/python
#   4. python3                                 —— 仅当它自己的 jsonschema 可用
#
# 全部不可用时**失败关闭**（退出 2 并打印明确原因），不做静默降级：
# 一旦悄悄退回不合格解释器，模块会以"输入非法"的形式假性失败，
# 掩盖真正的依赖问题。
#
# 用法：module_python.sh <module.py> [args...]
set -u

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

# 自检：能否构造 Draft 2020-12 校验器。只看 imports 不够，
# jsonschema 3.x 也能 import，但没有 Draft202012Validator。
_probe() {
    "$1" - <<'PY' >/dev/null 2>&1
import sys
try:
    import jsonschema
    from jsonschema import Draft202012Validator  # noqa: F401
except Exception:
    sys.exit(1)
try:
    from importlib.metadata import version
    major = int(version('jsonschema').split('.')[0])
except Exception:
    major = 0
sys.exit(0 if major >= 4 else 1)
PY
}

_candidates=()
if [ -n "${ROS_MODULE_PYTHON:-}" ]; then
    _candidates+=("$ROS_MODULE_PYTHON")
fi
_candidates+=("$REPO_ROOT/.research-venv/bin/python")
_candidates+=("$REPO_ROOT/tests/evidence/research-venv/bin/python")
_candidates+=("python3")

for candidate in "${_candidates[@]}"; do
    resolved=$(command -v "$candidate" 2>/dev/null || true)
    [ -z "$resolved" ] && continue
    if _probe "$resolved"; then
        exec "$resolved" "$@"
    fi
done

# 没有合格解释器：明确失败，不猜、不降级。
{
    echo "MODULE_PYTHON_UNQUALIFIED: 未找到满足 jsonschema>=4 (Draft 2020-12) 的解释器"
    echo "已尝试：${_candidates[*]}"
    echo "可通过 ROS_MODULE_PYTHON=/path/to/python 显式指定"
} >&2
exit 2
