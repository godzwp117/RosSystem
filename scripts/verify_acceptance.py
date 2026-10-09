#!/usr/bin/env python3
"""verify_acceptance.py -- 校验验收证据包（仅用 Python 标准库）。

校验项（对应任务要求 A3）
------------------------
1. JSON 是否符合 Schema（内置 JSON Schema 子集校验器，见 README「Schema 子集」）
2. 必填字段是否完整
3. 每个文件的 SHA-256 是否与 `file_hashes.json` 一致；包内是否有多余未登记文件
4. 场景引用的 `log_path` / `evidence_files` 是否真实存在
5. 判定为 PASS 的场景是否有真实执行证据（命令、返回码、存在的证据文件、无 FAIL 断言）
6. 证据包内是否含敏感密钥文件或密钥正文
7. 归档包 SHA-256 是否与 sidecar 一致（若存在）

用法：
    python3 scripts/verify_acceptance.py artifacts/acceptance/exports/<run_id>
    python3 scripts/verify_acceptance.py artifacts/acceptance/exports/<run_id>.tar.gz
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tarfile
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_PATH = os.path.join(REPO_ROOT, 'artifacts', 'acceptance', 'schema', 'acceptance.schema.json')
DEFAULT_EXPORTS = os.path.join(REPO_ROOT, 'artifacts', 'acceptance', 'exports')

KEY_FILE_SUFFIXES = ('.pem', '.key', '.p12', '.pfx', '.csr', '.srl', '.der', '.jks')
KEY_CONTENT_PATTERNS = [
    re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----'),
    re.compile(r'-----BEGIN CERTIFICATE-----'),
]
FORBIDDEN_PATH_PATTERNS = [
    re.compile(r'(^|/)security/keystore(/|$)'),
]


# ---------------------------------------------------------------------------
# 极简 JSON Schema 校验器（只支持本仓 schema 用到的关键字）
# ---------------------------------------------------------------------------
class SchemaError(Exception):
    pass


def _resolve_ref(root: dict, ref: str) -> dict:
    if not ref.startswith('#/'):
        raise SchemaError('仅支持本地 $ref: {0}'.format(ref))
    node = root
    for part in ref[2:].split('/'):
        part = part.replace('~1', '/').replace('~0', '~')
        if not isinstance(node, dict) or part not in node:
            raise SchemaError('无法解析 $ref: {0}'.format(ref))
        node = node[part]
    return node


def _type_ok(value, expected: str) -> bool:
    if expected == 'string':
        return isinstance(value, str)
    if expected == 'integer':
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == 'number':
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == 'boolean':
        return isinstance(value, bool)
    if expected == 'array':
        return isinstance(value, list)
    if expected == 'object':
        return isinstance(value, dict)
    if expected == 'null':
        return value is None
    return True


def validate(instance, schema: dict, root: dict, path: str = '$', errors: list = None) -> list:
    errors = [] if errors is None else errors

    if '$ref' in schema:
        return validate(instance, _resolve_ref(root, schema['$ref']), root, path, errors)

    if 'type' in schema:
        expected = schema['type']
        types = expected if isinstance(expected, list) else [expected]
        if not any(_type_ok(instance, t) for t in types):
            errors.append('{0}: 类型应为 {1}，实际 {2}'.format(path, expected, type(instance).__name__))
            return errors

    if 'oneOf' in schema:
        # 至少满足一个分支才算通过；所有分支都失败时报错并列出首个分支的原因。
        matched = False
        first_reason = None
        for option in schema['oneOf']:
            branch_errors = []
            validate(instance, option, root, path, branch_errors)
            if not branch_errors:
                matched = True
                break
            if first_reason is None:
                first_reason = branch_errors[0]
        if not matched:
            errors.append('{0}: 不满足 oneOf 任一分支（{1}）'.format(path, first_reason))
            return errors

    if 'enum' in schema and instance not in schema['enum']:
        errors.append('{0}: 取值必须是 {1} 之一，实际 {2!r}'.format(path, schema['enum'], instance))

    if isinstance(instance, str):
        if 'pattern' in schema and not re.search(schema['pattern'], instance):
            errors.append('{0}: 不匹配 pattern {1}（实际 {2!r}）'.format(path, schema['pattern'], instance[:80]))
        if 'minLength' in schema and len(instance) < schema['minLength']:
            errors.append('{0}: 长度小于 minLength={1}'.format(path, schema['minLength']))

    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if 'minimum' in schema and instance < schema['minimum']:
            errors.append('{0}: 小于 minimum={1}'.format(path, schema['minimum']))

    if isinstance(instance, dict):
        for field in schema.get('required', []):
            if field not in instance:
                errors.append('{0}: 缺少必填字段 {1!r}'.format(path, field))
        properties = schema.get('properties', {})
        for key, value in instance.items():
            if key in properties:
                validate(value, properties[key], root, '{0}.{1}'.format(path, key), errors)
            elif schema.get('additionalProperties') is False:
                errors.append('{0}: 不允许的额外字段 {1!r}'.format(path, key))
        if 'additionalProperties' in schema and isinstance(schema['additionalProperties'], dict):
            for key, value in instance.items():
                if key not in properties:
                    validate(value, schema['additionalProperties'], root,
                             '{0}.{1}'.format(path, key), errors)

    if isinstance(instance, list) and 'items' in schema:
        for index, item in enumerate(instance):
            validate(item, schema['items'], root, '{0}[{1}]'.format(path, index), errors)

    return errors


# ---------------------------------------------------------------------------
# 校验主流程
# ---------------------------------------------------------------------------
class Report:
    def __init__(self):
        self.errors: list = []
        self.warnings: list = []
        self.checks: list = []

    def check(self, name: str, ok: bool, detail: str, warning_only: bool = False):
        self.checks.append((name, ok, detail, warning_only))
        if not ok:
            (self.warnings if warning_only else self.errors).append('{0}: {1}'.format(name, detail))

    @property
    def ok(self) -> bool:
        return not self.errors


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b''):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: str):
    with open(path, 'r', encoding='utf-8') as handle:
        return json.load(handle)


def verify_package(pkg_root: str, schema_path: str, outdir: str, allow_not_run: bool) -> Report:
    report = Report()

    # --- 必需文件 ---
    required_files = ['manifest.json', 'environment.json', 'test_results.json', 'file_hashes.json']
    missing = [name for name in required_files if not os.path.isfile(os.path.join(pkg_root, name))]
    report.check('包内必需文件齐备', not missing,
                 '缺: {0}'.format(missing) if missing else 'manifest/environment/test_results/file_hashes 均存在')
    if missing:
        return report

    try:
        schema = load_json(schema_path)
    except (OSError, json.JSONDecodeError) as exc:
        report.check('Schema 可读', False, str(exc))
        return report
    report.check('Schema 可读', True, schema_path)

    manifest = load_json(os.path.join(pkg_root, 'manifest.json'))

    # 1+2. Schema / 必填字段
    errs = validate(manifest, schema, schema, '$')
    report.check('manifest.json 符合 Schema 且必填字段完整', not errs, '; '.join(errs[:6]) or 'OK')

    test_results = load_json(os.path.join(pkg_root, 'test_results.json'))
    tr_schema = {'$ref': '#/$defs/test_results', '$defs': schema.get('$defs', {})}
    errs = validate(test_results, tr_schema, tr_schema, '$')
    report.check('test_results.json 符合 Schema', not errs, '; '.join(errs[:6]) or 'OK')

    sec_path = os.path.join(pkg_root, 'security_results.json')
    sec_results = None
    if os.path.isfile(sec_path):
        sec_results = load_json(sec_path)
        sec_schema = {'$ref': '#/$defs/security_results', '$defs': schema.get('$defs', {})}
        errs = validate(sec_results, sec_schema, sec_schema, '$')
        report.check('security_results.json 符合 Schema', not errs, '; '.join(errs[:6]) or 'OK')

    hashes = load_json(os.path.join(pkg_root, 'file_hashes.json'))
    fh_schema = {'$ref': '#/$defs/file_hashes', '$defs': schema.get('$defs', {})}
    errs = validate(hashes, fh_schema, fh_schema, '$')
    report.check('file_hashes.json 符合 Schema', not errs, '; '.join(errs[:6]) or 'OK')

    # 3. 哈希一致性
    mismatched, missing_files = [], []
    registered = set()
    for record in hashes.get('files', []):
        rel = record['path']
        registered.add(rel)
        abs_path = os.path.join(pkg_root, rel)
        if not os.path.isfile(abs_path):
            missing_files.append(rel)
            continue
        actual = sha256_file(abs_path)
        if actual != record['sha256']:
            mismatched.append('{0} (记录 {1}… 实际 {2}…)'.format(rel, record['sha256'][:12], actual[:12]))
    report.check('所有登记文件的 SHA-256 与内容一致', not mismatched and not missing_files,
                 '不一致: {0}; 缺失: {1}'.format(mismatched[:5], missing_files[:5]) if (mismatched or missing_files) else
                 '{0} 个文件哈希校验通过'.format(len(registered)))

    on_disk = set()
    for base, dirs, files in os.walk(pkg_root):
        dirs[:] = [d for d in dirs if d != '__pycache__']
        for name in files:
            on_disk.add(os.path.relpath(os.path.join(base, name), pkg_root))
    unregistered = sorted(on_disk - registered - {'file_hashes.json'})
    report.check('包内无未登记文件', not unregistered,
                 '未登记: {0}'.format(unregistered[:8]) if unregistered else '所有文件均已登记')

    # 4+5. 场景证据真实性与 PASS 证据
    all_scenarios = list(test_results.get('scenarios') or [])
    if sec_results:
        all_scenarios += list(sec_results.get('scenarios') or [])
    bad_refs, weak_pass, not_run_ids = [], [], []
    for sc in all_scenarios:
        sid = sc.get('scenario_id')
        refs = []
        if sc.get('log_path'):
            refs.append(sc['log_path'])
        refs += list(sc.get('evidence_files') or [])
        for rel in refs:
            if not os.path.isfile(os.path.join(pkg_root, rel)):
                bad_refs.append('{0} -> {1}'.format(sid, rel))
        if sc.get('status') == 'PASS':
            problems = []
            if not sc.get('command'):
                problems.append('无 command')
            if sc.get('exit_code') is None:
                problems.append('无 exit_code')
            if not (sc.get('evidence_files') or []):
                problems.append('无 evidence_files')
            failed_checks = [c for c in (sc.get('checks') or []) if c.get('result') == 'FAIL']
            if failed_checks:
                problems.append('存在 FAIL 断言: {0}'.format([c.get('check') for c in failed_checks][:3]))
            if problems:
                weak_pass.append('{0}: {1}'.format(sid, '; '.join(problems)))
        if sc.get('status') == 'NOT_RUN':
            not_run_ids.append(sid)

    report.check('场景引用的日志/证据文件均存在', not bad_refs,
                 '缺失引用: {0}'.format(bad_refs[:6]) if bad_refs else '{0} 个场景引用全部存在'.format(len(all_scenarios)))
    report.check('PASS 场景均有真实执行证据', not weak_pass,
                 '证据不足: {0}'.format(weak_pass[:6]) if weak_pass else '全部 PASS 场景均有命令/返回码/证据文件')

    # 阶段 PASS 与 test_summary 自洽
    if manifest.get('status') == 'PASS':
        summary = manifest.get('test_summary') or {}
        inconsistent = []
        if summary.get('failed'):
            inconsistent.append('failed={0}'.format(summary.get('failed')))
        if summary.get('not_run'):
            inconsistent.append('not_run={0}'.format(summary.get('not_run')))
        report.check('阶段判定 PASS 与 test_summary 自洽（无 failed / not_run）', not inconsistent,
                     '阶段 PASS 但 {0}'.format(', '.join(inconsistent)) if inconsistent else
                     'passed={0} failed=0 not_run=0'.format(summary.get('passed')),
                     warning_only=allow_not_run)
    if not_run_ids:
        report.check('NOT_RUN 场景已显式标注（未默认按通过处理）', True,
                     '{0} 个 NOT_RUN: {1}'.format(len(not_run_ids), not_run_ids[:6]))

    # 6. 敏感文件扫描
    secret_hits = []
    for rel in sorted(on_disk):
        if any(p.search(rel) for p in FORBIDDEN_PATH_PATTERNS):
            secret_hits.append('路径命中密钥库: {0}'.format(rel))
            continue
        if rel.lower().endswith(KEY_FILE_SUFFIXES):
            secret_hits.append('密钥类文件: {0}'.format(rel))
            continue
        if rel.lower().endswith(('.json', '.jsonl', '.log', '.txt', '.md', '.yaml', '.xml', '.py', '.sh')):
            try:
                with open(os.path.join(pkg_root, rel), 'r', encoding='utf-8', errors='replace') as handle:
                    text = handle.read(1 << 20)
            except OSError:
                continue
            for pattern in KEY_CONTENT_PATTERNS:
                if pattern.search(text):
                    secret_hits.append('正文含密钥/证书材料: {0}'.format(rel))
                    break
    report.check('证据包内无敏感密钥文件或密钥正文', not secret_hits,
                 '命中: {0}'.format(secret_hits[:6]) if secret_hits else '扫描 {0} 个文件，未发现密钥材料'.format(len(on_disk)))

    # 7. 归档哈希
    run_id = manifest.get('run_id') or os.path.basename(pkg_root.rstrip('/'))
    archive = os.path.join(outdir, '{0}.tar.gz'.format(run_id))
    sidecar = archive + '.sha256'
    if os.path.isfile(archive) and os.path.isfile(sidecar):
        with open(sidecar, 'r', encoding='utf-8') as handle:
            expected = handle.read().split()[0]
        actual = sha256_file(archive)
        report.check('归档包 SHA-256 与 sidecar 一致', expected == actual,
                     '期望 {0}… 实际 {1}…'.format(expected[:16], actual[:16]) if expected != actual else
                     'sha256={0}'.format(actual))
    else:
        report.check('归档包 SHA-256 校验', True,
                     '未找到归档或 sidecar（使用 --no-archive 导出时正常）', warning_only=True)

    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='校验验收证据包')
    parser.add_argument('package', help='证据包目录，或 .tar.gz 归档')
    parser.add_argument('--schema', default=SCHEMA_PATH)
    parser.add_argument('--outdir', default=DEFAULT_EXPORTS,
                        help='证据包所在目录（用于定位归档 sidecar），默认 <repo>/artifacts/acceptance/exports')
    parser.add_argument('--allow-not-run', action='store_true',
                        help='把「阶段 PASS 但存在 not_run」降级为警告（默认按错误处理）')
    parser.add_argument('--quiet', action='store_true')
    args = parser.parse_args(argv)

    schema_path = args.schema if os.path.isabs(args.schema) else os.path.join(os.getcwd(), args.schema)
    if not os.path.isfile(schema_path):
        print('ERROR: 找不到 Schema: {0}'.format(schema_path), file=sys.stderr)
        return 2

    tmpdir = None
    target = args.package
    if target.endswith(('.tar.gz', '.tgz')):
        tmpdir = tempfile.mkdtemp(prefix='rg_verify_')
        with tarfile.open(target, 'r:gz') as tar:
            tar.extractall(tmpdir)
        entries = [name for name in os.listdir(tmpdir) if os.path.isdir(os.path.join(tmpdir, name))]
        if len(entries) != 1:
            print('ERROR: 归档内应只有 1 个顶层目录，实际 {0}'.format(entries), file=sys.stderr)
            return 2
        pkg_root = os.path.join(tmpdir, entries[0])
        outdir = os.path.dirname(os.path.abspath(target))
    else:
        pkg_root = os.path.abspath(target)
        outdir = os.path.abspath(args.outdir)

    if not os.path.isdir(pkg_root):
        print('ERROR: 证据包目录不存在: {0}'.format(pkg_root), file=sys.stderr)
        return 2

    report = verify_package(pkg_root, schema_path, outdir, args.allow_not_run)

    if not args.quiet:
        print('=== 证据包校验: {0} ==='.format(os.path.basename(pkg_root.rstrip('/'))))
        for name, ok, detail, warning_only in report.checks:
            tag = 'PASS' if ok else ('WARN' if warning_only else 'FAIL')
            print('  [{0}] {1}'.format(tag, name))
            print('         {0}'.format(detail))
        if report.errors:
            print('\n错误 {0} 项:'.format(len(report.errors)))
            for item in report.errors:
                print('  - {0}'.format(item))
        if report.warnings:
            print('\n警告 {0} 项:'.format(len(report.warnings)))
            for item in report.warnings:
                print('  - {0}'.format(item))
        print('\nVERIFY RESULT: {0}'.format('PASS' if report.ok else 'FAIL'))

    if tmpdir:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)
    return 0 if report.ok else 1


if __name__ == '__main__':
    sys.exit(main())
