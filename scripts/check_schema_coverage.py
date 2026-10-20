#!/usr/bin/env python3
"""FIX-01：CI 用的 Schema 样例覆盖检查。

为什么需要它
------------
原 CI 用**文件名前缀模糊匹配**关联 Schema 与样例：

    sample.name.startswith(stem.split('.')[0])

但样例的真实名称是 `comm_normal.json` / `module_input_valid.json`，
而 Schema 名称是 `comm_risk_evidence.schema.json` / `module_input.schema.json`。
前缀根本不匹配，于是**样例可能一个都没被校验，CI 却显示 PASS**。

本脚本**复用** `scripts/validate_team_contracts.py` 中已有的显式
`valid_map` 与非法样例 `manifest.json`，并补上它没有的**覆盖断言**：

  * 四份 Schema 文件必须存在且符合 Draft 2020-12；
  * 每份 Schema 至少有一个**真正参与校验**的合法样例 —— 否则失败；
  * 非法样例按 manifest 声明的类别被拒绝；
  * 总校验数 `checked_count` 为 0 必须失败。

输出每类的实际执行样例数（数字只能来自真实文件枚举与真实校验）。

用法：
    python3 scripts/check_schema_coverage.py
退出码：0 = 全部通过；1 = 存在覆盖缺口或校验失败。
"""

from __future__ import annotations

import os
import sys
from collections import Counter

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, 'scripts'))

import validate_team_contracts as vtc  # noqa: E402


def main() -> int:
    # 契约校验器在样例目录缺失时会直接抛异常；这里必须转成**干净的 FAIL**，
    # 而不是让 traceback 冒泡（否则 CI 只看到崩溃、看不到覆盖缺口）。
    try:
        result = vtc.validate_all()
    except Exception as exc:                   # noqa: BLE001
        print('FAIL: 契约校验无法执行（{0}: {1}）'.format(
            type(exc).__name__, exc))
        print('      常见原因：样例目录或 invalid/manifest.json 缺失。')
        print('\nSCHEMA_EXAMPLE_COVERAGE: FAIL')
        return 1

    schemas = result.get('schemas') or []
    valid = result.get('valid_examples') or []
    invalid = result.get('invalid_examples') or []
    errors = list(result.get('errors') or [])

    # ---- 1) 四份 Schema 必须存在且合法 ----
    expected = set(vtc.SCHEMA_FILES)
    # validate_all() 的 schemas 条目用 'name' 键
    present = {e.get('name') or e.get('schema') for e in schemas}
    missing = sorted(expected - present)
    bad_schema = [e for e in schemas if not e.get('ok')]

    print('=== Schema 文件 ===')
    for name in sorted(expected):
        entry = next((e for e in schemas
                      if (e.get('name') or e.get('schema')) == name), None)
        if entry is None:
            print('  {0}: 缺失'.format(name))
        else:
            print('  {0}: {1}'.format(name, 'Draft 2020-12 合法' if entry['ok']
                                      else '非法 - ' + entry.get('detail', '')))

    # ---- 2) 每份 Schema 至少一个真正被校验的合法样例 ----
    checked = Counter()
    passed = Counter()
    for entry in valid:
        checked[entry['schema']] += 1
        if entry.get('ok'):
            passed[entry['schema']] += 1

    print('\n=== 合法样例覆盖 ===')
    uncovered = []
    for name in sorted(expected):
        print('  {0}: checked {1}, passed {2}'.format(
            name, checked[name], passed[name]))
        if checked[name] == 0:
            uncovered.append(name)

    # ---- 3) 非法样例 ----
    rejected = sum(1 for e in invalid if e.get('ok'))
    print('\n=== 非法样例 ===')
    print('  invalid_cases: checked {0}, expected_rejections {1}, '
          'actual_rejections {2}'.format(len(invalid), len(invalid), rejected))
    for entry in invalid:
        if not entry.get('ok'):
            print('    [FAIL] {0}: {1}'.format(entry.get('file'),
                                               entry.get('detail', '')))

    total_checked = sum(checked.values())

    # ---- 4) 综合判定 ----
    failures = []
    if missing:
        failures.append('缺少 Schema 文件: {0}'.format(missing))
    if bad_schema:
        failures.append('Schema 不符合 Draft 2020-12: {0}'.format(
            [e.get('name') or e.get('schema') for e in bad_schema]))
    if uncovered:
        failures.append('以下 Schema 没有任何被校验的合法样例: {0}'.format(uncovered))
    if total_checked == 0:
        failures.append('checked_count=0：没有任何样例参与校验')
    if rejected != len(invalid):
        failures.append('非法样例未被全部拒绝: {0}/{1}'.format(
            rejected, len(invalid)))
    if len(invalid) == 0:
        failures.append('没有任何非法样例参与校验')
    if errors:
        failures.extend(errors[:5])

    print()
    if failures:
        for item in failures:
            print('FAIL: {0}'.format(item))
        print('\nSCHEMA_EXAMPLE_COVERAGE: FAIL')
        return 1

    print('SCHEMA_EXAMPLE_COVERAGE: PASS')
    print('  合法样例 {0} 条（覆盖 {1} 份 Schema），非法样例 {2} 条'.format(
        total_checked, len(expected), len(invalid)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
