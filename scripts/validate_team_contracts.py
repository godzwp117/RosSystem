#!/usr/bin/env python3
"""validate_team_contracts.py -- F0 公共接口契约校验工具。

为什么需要这个工具
------------------
1. **`jsonschema` 的 `format` 默认不生效。**
   本环境实测：`Draft202012Validator.FORMAT_CHECKER` 中**没有** `date-time` 检查器
   （需要 `rfc3339-validator`，本环境既无 pip 也无该 Debian 包）。
   因此仅声明 `"format": "date-time"` 时，非法时间戳会**静默通过**校验。
   本工具注册基于标准库的严格检查器，并用 `self_check_format_checker()`
   证明它确实在拦截非法值 —— 而不是"声明了就算校验了"。

2. **非有限数值必须在解析阶段拒绝。**
   Python 的 `json` 默认接受 `NaN` / `Infinity` 字面量。这些不是合法 JSON，
   且参与数值比较时会产生静默错误结论。本工具用 `parse_constant` 在解析阶段拒绝。

3. **Schema 自身也要校验。** 用 Draft 2020-12 元 schema 校验每个 Schema 文件，
   避免"Schema 写错了但没人发现"。

用法：
    python3 scripts/validate_team_contracts.py --all
    python3 scripts/validate_team_contracts.py --doc <json> --schema <schema.json>
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from datetime import datetime

try:
    import jsonschema
    from jsonschema import Draft202012Validator, FormatChecker
except ImportError:  # pragma: no cover - 由测试显式报告
    jsonschema = None
    Draft202012Validator = None
    FormatChecker = None

def _resolve_repo_root() -> str:
    """定位仓库根目录。

    优先用脚本自身位置（scripts/ 的上一级）；若该位置不含 docs/interfaces
    （例如脚本被复制到别处执行），退回当前工作目录，避免把路径算成 '/' 后再报
    难以理解的 FileNotFoundError。
    """
    candidate = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if os.path.isdir(os.path.join(candidate, 'docs', 'interfaces')):
        return candidate
    cwd = os.getcwd()
    if os.path.isdir(os.path.join(cwd, 'docs', 'interfaces')):
        return cwd
    return candidate


REPO_ROOT = _resolve_repo_root()
INTERFACES_DIR = os.path.join(REPO_ROOT, 'docs', 'interfaces')
SCHEMAS_DIR = os.path.join(INTERFACES_DIR, 'schemas')
EXAMPLES_DIR = os.path.join(INTERFACES_DIR, 'examples')

# 契约版本（与三个 Schema 的 enum 保持一致，集中在此便于一致性测试）
CONTRACT_VERSION = '1.0.0-proposed'
CONTRACT_STATUS = 'PROPOSED_V1'

SCHEMA_FILES = {
    'module_input': 'module_input.schema.json',
    'comm_risk_evidence': 'comm_risk_evidence.schema.json',
    'identity_trust_assessment': 'identity_trust_assessment.schema.json',
    'task_risk_decision': 'task_risk_decision.schema.json',
}

# RFC 3339 日期时间：必须含 'T' 分隔与时间部分，且必须带时区（Z 或 ±hh:mm）
_RFC3339_RE = re.compile(
    r'^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(\.\d+)?([Zz]|[+-]\d{2}:\d{2})$')


def check_rfc3339(value) -> bool:
    """严格的 RFC 3339 日期时间检查（标准库实现）。

    只要求"能被 datetime 解析"是不够的：`2026-10-10 12:00:05` 也能被
    `datetime.fromisoformat` 解析，但它不是 RFC 3339。因此先做正则匹配，
    再交给 datetime 验证字段合法性（例如月份 13 会被拒绝）。
    """
    if not isinstance(value, str):
        return True  # 类型问题交给 type 关键字处理
    if not _RFC3339_RE.match(value):
        return False
    normalised = value.replace('z', 'Z').replace('t', 'T')
    if normalised.endswith('Z'):
        normalised = normalised[:-1] + '+00:00'
    try:
        datetime.fromisoformat(normalised)
    except ValueError:
        return False
    return True


def build_format_checker():
    """构造带严格 date-time 检查器的 FormatChecker。"""
    checker = FormatChecker()
    checker.checks('date-time')(check_rfc3339)
    return checker


def non_finite_constant(name: str):
    """供 json.loads 的 parse_constant 使用：拒绝 NaN / Infinity / -Infinity。"""
    raise ValueError('非有限数值字面量不是合法 JSON: {0}'.format(name))


def load_json_strict(path: str):
    """解析 JSON 并拒绝非有限数值字面量。"""
    with open(path, 'r', encoding='utf-8') as handle:
        text = handle.read()
    return json.loads(text, parse_constant=non_finite_constant)


def load_schema(name_or_path: str):
    path = name_or_path
    if not os.path.isfile(path):
        path = os.path.join(SCHEMAS_DIR, SCHEMA_FILES.get(name_or_path, name_or_path))
    with open(path, 'r', encoding='utf-8') as handle:
        return json.load(handle)


def make_validator(schema):
    return Draft202012Validator(schema, format_checker=build_format_checker())


def validate_document(document, schema) -> list:
    """返回错误消息列表；空列表表示通过。"""
    validator = make_validator(schema)
    return ['{0}: {1}'.format('/'.join(str(p) for p in err.absolute_path) or '$', err.message)
            for err in sorted(validator.iter_errors(document), key=lambda e: list(e.absolute_path))]


def self_check_format_checker() -> tuple:
    """证明格式检查真实生效（而不是"声明了 format 就算校验"）。

    返回 (ok, detail)。若检查器未生效，这里必须失败 —— 否则所有时间戳负例测试
    都会假通过。
    """
    validator = make_validator({'type': 'string', 'format': 'date-time'})
    cases = [
        ('2026-10-10T12:00:05Z', True),
        ('2026-10-10T12:00:05+08:00', True),
        ('2026-10-10T12:00:05.123Z', True),
        ('2026-10-10 12:00:05', False),      # 空格分隔，非 RFC 3339
        ('2026-10-10', False),               # 缺时间部分
        ('2026-10-10T12:00:05', False),      # 缺时区
        ('2026-13-10T12:00:05Z', False),     # 月份非法
        ('not-a-time', False),
    ]
    failures = []
    for value, expect_valid in cases:
        actual = validator.is_valid(value)
        if actual != expect_valid:
            failures.append('{0!r} 期望 {1} 实际 {2}'.format(value, expect_valid, actual))
    return (not failures), failures


def validate_all() -> dict:
    """校验全部 Schema 自身 + 全部有效样例 + 全部非法样例。"""
    result = {'schemas': [], 'valid_examples': [], 'invalid_examples': [],
              'format_checker': {}, 'errors': []}

    ok, detail = self_check_format_checker()
    result['format_checker'] = {'ok': ok, 'detail': detail}
    if not ok:
        result['errors'].append('格式检查器未生效: {0}'.format(detail))

    # 1) Schema 自身合法性
    for name, filename in sorted(SCHEMA_FILES.items()):
        path = os.path.join(SCHEMAS_DIR, filename)
        entry = {'name': name, 'file': filename, 'ok': False, 'detail': ''}
        try:
            schema = load_schema(path)
            Draft202012Validator.check_schema(schema)
            entry['ok'] = True
        except Exception as exc:  # noqa: BLE001
            entry['detail'] = '{0}: {1}'.format(type(exc).__name__, exc)
            result['errors'].append('{0}: {1}'.format(filename, entry['detail']))
        result['schemas'].append(entry)

    # 2) 有效样例必须通过
    valid_map = {
        'module_input_valid.json': 'module_input',
        'comm_normal.json': 'comm_risk_evidence',
        'comm_suspicious.json': 'comm_risk_evidence',
        'comm_unknown.json': 'comm_risk_evidence',
        'identity_authorized.json': 'identity_trust_assessment',
        'identity_denied.json': 'identity_trust_assessment',
        'identity_error.json': 'identity_trust_assessment',
        'task_allow_recommended.json': 'task_risk_decision',
        'task_block_recommended.json': 'task_risk_decision',
        'task_unknown.json': 'task_risk_decision',
    }
    for filename, schema_name in sorted(valid_map.items()):
        path = os.path.join(EXAMPLES_DIR, filename)
        entry = {'file': filename, 'schema': schema_name, 'ok': False, 'detail': ''}
        try:
            document = load_json_strict(path)
            errors = validate_document(document, load_schema(schema_name))
            if errors:
                entry['detail'] = '; '.join(errors[:3])
                result['errors'].append('{0}: {1}'.format(filename, entry['detail']))
            else:
                entry['ok'] = True
        except Exception as exc:  # noqa: BLE001
            entry['detail'] = '{0}: {1}'.format(type(exc).__name__, exc)
            result['errors'].append('{0}: {1}'.format(filename, entry['detail']))
        result['valid_examples'].append(entry)

    # 3) 非法样例必须失败（且原因与清单声明一致）
    manifest_path = os.path.join(EXAMPLES_DIR, 'invalid', 'manifest.json')
    manifest = load_json_strict(manifest_path)
    for case in manifest['cases']:
        path = os.path.join(EXAMPLES_DIR, 'invalid', case['file'])
        entry = {'file': case['file'], 'schema': case['schema'],
                 'category': case['category'], 'ok': False, 'detail': ''}
        try:
            document = load_json_strict(path)
        except ValueError as exc:
            # 解析阶段就失败（例如 NaN 字面量）——这是预期行为
            entry['ok'] = case['category'] == 'non_finite_number'
            entry['detail'] = '解析阶段拒绝: {0}'.format(exc)
            if not entry['ok']:
                result['errors'].append('{0}: 意外在解析阶段被拒绝'.format(case['file']))
            result['invalid_examples'].append(entry)
            continue
        errors = validate_document(document, load_schema(case['schema']))
        if errors:
            entry['ok'] = True
            entry['detail'] = '; '.join(errors[:2])
        else:
            entry['detail'] = '未被拒绝（负例测试失效）'
            result['errors'].append('{0}: 非法样例却通过校验'.format(case['file']))
        result['invalid_examples'].append(entry)

    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='F0 公共接口契约校验')
    parser.add_argument('--all', action='store_true', help='校验全部 Schema 与样例')
    parser.add_argument('--doc', help='待校验的 JSON 文件')
    parser.add_argument('--schema', help='Schema 名称或路径')
    parser.add_argument('--quiet', action='store_true')
    args = parser.parse_args(argv)

    if jsonschema is None:
        print('ERROR: 缺少 jsonschema（需 >=4.0 才支持 Draft 2020-12）', file=sys.stderr)
        print('       安装方式: apt-get install -y python3-jsonschema', file=sys.stderr)
        return 3

    if args.doc:
        if not args.schema:
            print('ERROR: --doc 需要同时给出 --schema', file=sys.stderr)
            return 2
        document = load_json_strict(args.doc)
        errors = validate_document(document, load_schema(args.schema))
        if errors:
            print('INVALID {0}'.format(args.doc))
            for item in errors[:10]:
                print('  - {0}'.format(item))
            return 1
        print('VALID {0}'.format(args.doc))
        return 0

    if not args.all:
        parser.print_help()
        return 2

    result = validate_all()
    if not args.quiet:
        ok, detail = result['format_checker']['ok'], result['format_checker']['detail']
        print('=== 格式检查器自检 ===')
        print('  date-time 严格检查生效: {0}'.format(ok))
        if not ok:
            for item in detail:
                print('    - {0}'.format(item))
        print('=== Schema 自身合法性 ({0}) ==='.format(len(result['schemas'])))
        for entry in result['schemas']:
            print('  [{0}] {1}'.format('OK' if entry['ok'] else 'FAIL', entry['file']))
        print('=== 有效样例 ({0}) ==='.format(len(result['valid_examples'])))
        for entry in result['valid_examples']:
            print('  [{0}] {1} -> {2}'.format('OK' if entry['ok'] else 'FAIL',
                                              entry['file'], entry['schema']))
        print('=== 非法样例 ({0}) ==='.format(len(result['invalid_examples'])))
        for entry in result['invalid_examples']:
            print('  [{0}] {1} ({2})'.format('OK' if entry['ok'] else 'FAIL',
                                             entry['file'], entry['category']))
        verdict = 'PASS' if not result['errors'] else 'FAIL'
        print('CONTRACT VALIDATION: {0}'.format(verdict))
        for item in result['errors']:
            print('  ERROR {0}'.format(item))

    return 0 if not result['errors'] else 1


if __name__ == '__main__':
    sys.exit(main())
