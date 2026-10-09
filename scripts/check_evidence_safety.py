#!/usr/bin/env python3
"""check_evidence_safety.py -- 证据包敏感信息扫描门禁（Task B / B6-E8）。

与 redact_evidence.py 的关系（重要）
------------------------------------
本扫描器**刻意不复用脱敏器的正则**。脱敏器负责"改写"，扫描器负责"独立否决"：
如果两者共用同一套模式，脱敏器没识别出来的东西，扫描器也一定识别不出来，
于是"扫描通过"就退化成"脱敏器自认为没问题"。因此这里的模式集更宽（例如同时覆盖
`/home/`、`/Users/`、`C:\\Users\\`、绝对路径变体、赋值式凭证、私钥正文、高熵串），
并额外检查文件名与占位符使用情况。

结论语义（不得混淆）
--------------------
* exit 0 = 未发现阻断级问题（**不等于**"绝对没有敏感信息"，见 --strict 说明）
* exit 1 = 存在阻断级问题 → 调用方（发布器）必须**拒绝 push**
* exit 2 = 用法/路径错误

用法：
    python3 scripts/check_evidence_safety.py --path <dir_or_tar.gz>
        [--username X]... [--hostname Y]... [--json report.json] [--quiet]
"""

from __future__ import annotations

import argparse
import io
import json
import math
import os
import re
import socket
import sys
import tarfile

# ---------------------------------------------------------------- 模式（独立定义）
PRIVATE_KEY_RE = re.compile(r'-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----')
CERT_BLOCK_RE = re.compile(r'-----BEGIN CERTIFICATE-----')
SSH_KEY_RE = re.compile(r'-----BEGIN OPENSSH PRIVATE KEY-----')

TOKEN_RES = [
    ('github_token', re.compile(r'\bgh[pousr]_[A-Za-z0-9]{16,}\b')),
    ('github_pat', re.compile(r'\bgithub_pat_[A-Za-z0-9_]{20,}\b')),
    ('aws_access_key', re.compile(r'\bAKIA[0-9A-Z]{16}\b')),
    ('openai_key', re.compile(r'\bsk-[A-Za-z0-9]{20,}\b')),
    ('slack_token', re.compile(r'\bxox[baprs]-[A-Za-z0-9-]{10,}\b')),
    ('jwt', re.compile(r'\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b')),
]

# 绝对主机路径：占位符 ${WORKSPACE}/${PRIVATE_PATH} 不算命中
HOST_PATH_RES = [
    ('posix_home_path', re.compile(r'(?<![\w$@])/(?:home|Users)/[A-Za-z0-9._-]+')),
    ('root_path', re.compile(r'(?<![\w$@])/root(?:/|\b)')),
    ('windows_user_path', re.compile(r'(?i)\b[A-Z]:\\Users\\[^\\\s]+')),
    ('wsl_mnt_path', re.compile(r'(?i)/mnt/[a-z]/Users/[^/\s]+')),
]

CREDENTIAL_RES = [
    ('credential_assignment', re.compile(
        r'(?i)\b[A-Za-z0-9_.-]*(?:password|passwd|passphrase|secret|token|'
        r'api[_-]?key|private[_-]?key|access[_-]?key|credential)[A-Za-z0-9_.-]*\s*[:=]\s*'
        r'(?!\[REDACTED_SECRET\]|\$\{)[^\s"\',;]{3,}')),
    ('authorization_header', re.compile(r'(?i)\b(?:bearer|basic)\s+(?!\[REDACTED_SECRET\])'
                                        r'[A-Za-z0-9._~+/=-]{12,}')),
]

PRIVATE_IP_RE = re.compile(
    r'\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}'
    r'|192\.168\.\d{1,3}\.\d{1,3}'
    r'|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b')
MAC_RE = re.compile(r'\b(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}\b')
HIGH_ENTROPY_RE = re.compile(r'\b[A-Za-z0-9+/]{40,}={0,2}\b')
HEX_RE = re.compile(r'^[0-9a-fA-F]+$')

FORBIDDEN_SUFFIXES = ('.pem', '.key', '.p12', '.pfx', '.jks', '.keystore', '.csr',
                      '.der', '.srl', '.crt', '.p7s', '.p7b', '.kdb', '.ppk')
KEYSTORE_PATH_RE = re.compile(r'security/keystore')

MAX_TEXT_BYTES = 64 * 1024 * 1024


def shannon_entropy(text: str) -> float:
    if not text:
        return 0.0
    counts = {}
    for ch in text:
        counts[ch] = counts.get(ch, 0) + 1
    total = len(text)
    return -sum((n / total) * math.log2(n / total) for n in counts.values())


def mask(excerpt: str) -> str:
    """扫描报告自身也不能泄露敏感值。"""
    excerpt = excerpt.strip()
    if len(excerpt) <= 12:
        return excerpt[:4] + '…'
    return excerpt[:10] + '…' + excerpt[-2:]


class Finding:
    __slots__ = ('severity', 'category', 'path', 'line', 'excerpt')

    def __init__(self, severity, category, path, line, excerpt):
        self.severity = severity
        self.category = category
        self.path = path
        self.line = line
        self.excerpt = excerpt

    def to_dict(self):
        return {'severity': self.severity, 'category': self.category,
                'path': self.path, 'line': self.line, 'excerpt': mask(self.excerpt)}


def iter_files(path: str):
    """产出 (显示用相对路径, 读取函数)。支持目录与 .tar.gz。"""
    if os.path.isdir(path):
        for base, dirnames, filenames in os.walk(path):
            dirnames.sort()
            for name in sorted(filenames):
                full = os.path.join(base, name)
                yield os.path.relpath(full, path), (lambda p=full: open(p, 'rb').read())
        return
    if tarfile.is_tarfile(path):
        with tarfile.open(path, 'r:*') as archive:
            for member in archive.getmembers():
                if not member.isfile():
                    continue
                handle = archive.extractfile(member)
                if handle is None:
                    continue
                data = handle.read()
                yield member.name, (lambda d=data: d)
        return
    raise FileNotFoundError('既不是目录也不是可读归档: {0}'.format(path))


def scan_text(text: str, rel: str, findings: list, identities: dict):
    def add(severity, category, line_no, line_text):
        findings.append(Finding(severity, category, rel, line_no, line_text))

    for line_no, line in enumerate(text.splitlines(), 1):
        if PRIVATE_KEY_RE.search(line) or SSH_KEY_RE.search(line):
            add('BLOCKING', 'private_key_material', line_no, line)
        if CERT_BLOCK_RE.search(line):
            add('WARNING', 'certificate_material', line_no, line)
        for category, pattern in TOKEN_RES:
            if pattern.search(line):
                add('BLOCKING', category, line_no, line)
        for category, pattern in HOST_PATH_RES:
            if pattern.search(line):
                add('BLOCKING', category, line_no, line)
        for category, pattern in CREDENTIAL_RES:
            if pattern.search(line):
                add('BLOCKING', category, line_no, line)
        for user in identities['usernames']:
            if user and re.search(r'(?<![\w.-])' + re.escape(user) + r'(?![\w.-])', line):
                add('BLOCKING', 'host_username', line_no, line)
                break
        for host in identities['hostnames']:
            if host and len(host) >= 4 and host in line:
                add('BLOCKING', 'host_name', line_no, line)
                break
        if PRIVATE_IP_RE.search(line):
            add('WARNING', 'private_ip', line_no, line)
        if MAC_RE.search(line):
            add('WARNING', 'device_identifier', line_no, line)
        if KEYSTORE_PATH_RE.search(line):
            add('WARNING', 'keystore_path_reference', line_no, line)
        for candidate in HIGH_ENTROPY_RE.findall(line):
            if HEX_RE.match(candidate):
                continue  # sha256/commit sha 等十六进制摘要属正常证据
            if candidate.startswith('${') or candidate == '[REDACTED_SECRET]':
                continue
            # 排除路径形串：含 '/' 但不含 base64 特有的 '+' 时更像文件路径
            # （路径泄露由上面的 HOST_PATH_RES 专门负责），否则会产生大量误报，
            # 误报一多，真正的告警就会被忽略。
            if '/' in candidate and '+' not in candidate:
                continue
            if shannon_entropy(candidate) >= 4.2:
                add('WARNING', 'high_entropy_blob', line_no, candidate)
                break


def scan_path(path: str, identities: dict, check_json: bool = True):
    findings: list = []
    stats = {'files_scanned': 0, 'bytes_scanned': 0, 'files_skipped_binary': 0,
             'json_files_parsed': 0, 'json_parse_errors': []}
    for rel, reader in iter_files(path):
        stats['files_scanned'] += 1
        lower = rel.lower()
        if lower.endswith(FORBIDDEN_SUFFIXES):
            findings.append(Finding('BLOCKING', 'key_file_present', rel, 0, rel))
            continue
        try:
            raw = reader()
        except OSError:
            continue
        stats['bytes_scanned'] += len(raw)
        if b'\x00' in raw or len(raw) > MAX_TEXT_BYTES:
            stats['files_skipped_binary'] += 1
            findings.append(Finding('WARNING', 'opaque_binary_file', rel, 0, rel))
            continue
        try:
            text = raw.decode('utf-8')
        except UnicodeDecodeError:
            text = raw.decode('utf-8', 'replace')
            findings.append(Finding('WARNING', 'not_valid_utf8', rel, 0, rel))

        if check_json and lower.endswith('.json'):
            try:
                json.loads(text)
                stats['json_files_parsed'] += 1
            except json.JSONDecodeError as exc:
                stats['json_parse_errors'].append('{0}: {1}'.format(rel, exc))
        if check_json and lower.endswith('.jsonl'):
            for line_no, line in enumerate(text.splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    json.loads(line)
                except json.JSONDecodeError as exc:
                    stats['json_parse_errors'].append('{0}:{1}: {2}'.format(rel, line_no, exc))
                    break
        scan_text(text, rel, findings, identities)
    return findings, stats


def default_identities(extra_usernames, extra_hostnames):
    usernames = set(extra_usernames)
    hostnames = set(extra_hostnames)
    try:
        import getpass
        usernames.add(getpass.getuser())
    except Exception:  # noqa: BLE001
        pass
    for key in ('USER', 'LOGNAME', 'USERNAME'):
        value = os.environ.get(key)
        if value:
            usernames.add(value)
    try:
        hostnames.add(socket.gethostname())
    except Exception:  # noqa: BLE001
        pass
    # 过滤掉过短/无意义的通用名，避免把正常英文单词当成用户名误报
    usernames = {u for u in usernames if u and len(u) >= 3 and u.lower() not in
                 ('root', 'user', 'ubuntu', 'ros', 'admin')}
    hostnames = {h for h in hostnames if h and len(h) >= 4}
    return {'usernames': sorted(usernames), 'hostnames': sorted(hostnames)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='证据包敏感信息扫描门禁')
    parser.add_argument('--path', required=True, help='证据目录或 .tar.gz')
    parser.add_argument('--username', action='append', default=[])
    parser.add_argument('--hostname', action='append', default=[])
    parser.add_argument('--json', dest='json_out', default=None)
    parser.add_argument('--quiet', action='store_true')
    parser.add_argument('--allow-warnings', action='store_true',
                        help='仅 WARNING 时返回 0（默认也是 0，此开关用于显式声明）')
    args = parser.parse_args(argv)

    if not os.path.exists(args.path):
        print('ERROR: 路径不存在: {0}'.format(args.path), file=sys.stderr)
        return 2

    identities = default_identities(args.username, args.hostname)
    try:
        findings, stats = scan_path(args.path, identities)
    except (FileNotFoundError, tarfile.TarError) as exc:
        print('ERROR: 无法读取证据: {0}'.format(exc), file=sys.stderr)
        return 2

    blocking = [f for f in findings if f.severity == 'BLOCKING']
    warnings = [f for f in findings if f.severity == 'WARNING']
    by_category = {}
    for finding in findings:
        by_category[finding.category] = by_category.get(finding.category, 0) + 1

    report = {
        'path': os.path.abspath(args.path),
        'result': 'FAIL' if blocking else 'PASS',
        'blocking_count': len(blocking),
        'warning_count': len(warnings),
        'categories': by_category,
        'stats': stats,
        'identities_checked': {'usernames': len(identities['usernames']),
                               'hostnames': len(identities['hostnames'])},
        'findings': [f.to_dict() for f in (blocking + warnings)][:200],
        'semantics': ('exit 0 表示未发现阻断级问题，不表示绝对不存在敏感信息；'
                      '扫描器与脱敏器使用独立模式集，互为补充而非互相证明。'),
    }

    if not args.quiet:
        print('=== 证据安全扫描: {0} ==='.format(args.path))
        print('  扫描文件={files_scanned} 字节={bytes_scanned} 二进制跳过={files_skipped_binary}'
              .format(**stats))
        print('  JSON 解析成功={json_files_parsed} 解析失败={json_parse_errors}'
              .format(**stats))
        for category, count in sorted(by_category.items()):
            severity = 'BLOCKING' if any(f.category == category and f.severity == 'BLOCKING'
                                         for f in findings) else 'WARNING'
            print('    [{0}] {1}: {2}'.format(severity, category, count))
        for finding in blocking[:20]:
            print('    BLOCK {0}:{1} [{2}] {3}'.format(
                finding.path, finding.line, finding.category, mask(finding.excerpt)))
        print('EVIDENCE SAFETY: {0}'.format(report['result']))

    if args.json_out:
        with open(args.json_out, 'w', encoding='utf-8') as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
    return 1 if blocking else 0


if __name__ == '__main__':
    sys.exit(main())
