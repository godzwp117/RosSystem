#!/usr/bin/env python3
"""redact_evidence.py -- 验收证据脱敏（Task B）。

设计目标
--------
把"本地真实证据"转换为"可公开发布的证据"，同时**不破坏**：
  * 审计链与事件关联（event_id / request_id / task_id 原样保留）
  * 业务判定（ALLOW / BLOCK / reason_code 原样保留）
  * 机器可解析性（JSON/JSONL 脱敏后仍可解析；数字/布尔/数组类型不变）
  * 事件顺序、测试通过数量、真实错误原因

与"简单把整份文本里的字符串清空"的区别
--------------------------------------
1. **按字段语义脱敏**：JSON/JSONL/YAML 先解析结构，命中敏感字段名的值替换为
   `[REDACTED_SECRET]`，其余字符串再做模式脱敏；数字/布尔/None 一律不动。
2. **白名单业务字段**：PRESERVE_FIELDS 中的字段（run_id、event_id、reason_code、
   decision、policy_digest…）完全不参与文本替换，避免"脱敏把证据也脱没了"。
3. **确定性映射**：同一运行实例内，同一实体（用户名/主机名/私有路径/IP）始终映射到
   同一个占位符，便于跨日志关联；映射表**只存在于内存**，绝不写入发布产物。

不做的事（诚实声明）
--------------------
* 不做"可逆加密"或"假名化后仍可还原"：占位符是单向的。
* 不保证能识别任意未知形态的机密；它是基于模式的防线，配合
  `check_evidence_safety.py` 的独立扫描共同使用。

用法：
    python3 scripts/redact_evidence.py --src <pkg_dir> --dst <out_dir>
        [--workspace-root PATH] [--report FILE] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import sys
from collections import Counter

PLACEHOLDER_WORKSPACE = '${WORKSPACE}'
PLACEHOLDER_PRIVATE_PATH = '${PRIVATE_PATH}'
PLACEHOLDER_SECRET = '[REDACTED_SECRET]'

# 这些字段是"证据本身"，脱敏时一律原样保留（业务字段白名单）。
PRESERVE_FIELDS = frozenset({
    'run_id', 'scenario_id', 'event_id', 'request_id', 'task_id', 'task_phase',
    'policy_version', 'policy_epoch', 'policy_digest', 'transition_id',
    'reason_code', 'decision', 'status_code', 'security_mode', 'source_enclave',
    'requested_resource', 'downstream_goal_count', 'timestamp_utc', 'duration_ms',
    'exit_code', 'status', 'result', 'schema_version', 'algorithm',
    'expected_result', 'actual_result', 'rejection_layer', 'source_role',
    'previous_task_phase', 'next_task_phase', 'previous_epoch', 'next_epoch',
    'previous_policy_digest', 'next_policy_digest', 'transition_at',
    'target_task_id', 'target_task_phase', 'expected_epoch', 'current_epoch',
    'active_task_id', 'active_task_phase', 'accepted', 'ros_domain_id',
    'container_default_domain_id', 'frame_id', 'x', 'y', 'z',
})

# 字段名命中即整体替换为 [REDACTED_SECRET]
SENSITIVE_KEY_PATTERN = re.compile(
    r'(password|passwd|passphrase|secret|token|api[_-]?key|private[_-]?key|'
    r'access[_-]?key|authorization|credential|client[_-]?secret|bearer)',
    re.IGNORECASE)

# ---------------------------------------------------------------- 文本模式
# 顺序很重要：先清机密（PEM 里可能含任意内容），再处理路径/身份。
PEM_BLOCK_RE = re.compile(
    r'-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----',
    re.DOTALL)
PEM_CERT_RE = re.compile(
    r'-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----', re.DOTALL)
TOKEN_RES = (
    re.compile(r'\bgh[pousr]_[A-Za-z0-9]{16,}\b'),
    re.compile(r'\bgithub_pat_[A-Za-z0-9_]{20,}\b'),
    re.compile(r'\bAKIA[0-9A-Z]{16}\b'),
    re.compile(r'\bsk-[A-Za-z0-9]{20,}\b'),
    re.compile(r'\bxox[baprs]-[A-Za-z0-9-]{10,}\b'),
)
AUTH_HEADER_RE = re.compile(r'(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}')
KV_SECRET_RE = re.compile(
    r'(?i)\b([A-Za-z0-9_.-]*(?:password|passwd|secret|token|api[_-]?key|'
    r'private[_-]?key|credential)[A-Za-z0-9_.-]*)(\s*[:=]\s*)("?)([^\s"\',;]{3,})\3')
ENV_SECRET_RE = re.compile(
    r'(?i)\b([A-Z0-9_]*(?:PASSWORD|SECRET|TOKEN|PRIVATE_KEY|API_KEY|CREDENTIAL)[A-Z0-9_]*)'
    r'=(\S+)')

HOME_PATH_RE = re.compile(r'(?<![\w$@])(/(?:home|Users)/([A-Za-z0-9._-]+))(/[^\s"\'`,;)\]}]*)?')
ROOT_PATH_RE = re.compile(r'(?<![\w$@])(/root)(/[^\s"\'`,;)\]}]*)?')
WIN_PATH_RE = re.compile(r'(?i)\b([A-Z]:\\Users\\([^\\\s]+)(?:\\[^\s"\'`,;)\]}]*)?)')
PRIVATE_IP_RE = re.compile(
    r'\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}'
    r'|192\.168\.\d{1,3}\.\d{1,3}'
    r'|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b')
MAC_RE = re.compile(r'\b(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}\b')

TEXT_SUFFIXES = ('.json', '.jsonl', '.yaml', '.yml', '.log', '.txt', '.md', '.env',
                 '.json5', '.cfg', '.ini', '.sh', '.py', '.xml', '.csv', '.action',
                 '.srv', '.msg', '.out', '.err', '.report', '.conf')
# 这些后缀属于密钥材料，一律拒绝进入发布包
FORBIDDEN_SUFFIXES = ('.pem', '.key', '.p12', '.pfx', '.jks', '.keystore', '.csr',
                      '.der', '.srl', '.crt', '.p7s', '.p7b', '.kdb')


class Redactor:
    """确定性脱敏器：同一实例内同实体 → 同占位符。"""

    def __init__(self, workspace_root: str, extra_usernames=(), extra_hostnames=(),
                 extra_paths=()):
        self.workspace_root = os.path.abspath(workspace_root)
        self.counts = Counter()
        self._user_map: dict = {}
        self._host_map: dict = {}
        self._ip_map: dict = {}
        self._mac_map: dict = {}
        self._path_map: dict = {}

        # 需要脱敏的本地身份（真实值只在本进程内存中出现）
        self.usernames = {u for u in extra_usernames if u}
        self.hostnames = {h for h in extra_hostnames if h}
        # 说明：工作区目录名（如 RosSystem）本身不是身份标识，刻意不脱敏，
        # 否则会把 ${WORKSPACE} 之类稳定别名也一起打散。
        try:
            import getpass
            self.usernames.add(getpass.getuser())
        except Exception:  # noqa: BLE001
            pass
        for key in ('USER', 'LOGNAME', 'USERNAME'):
            value = os.environ.get(key)
            if value:
                self.usernames.add(value)
        try:
            self.hostnames.add(socket.gethostname())
        except Exception:  # noqa: BLE001
            pass
        # 已知私有路径前缀（除了工作区本身）
        self.extra_paths = [p for p in extra_paths if p]

    # ------------------------------------------------------------ 映射
    @staticmethod
    def _ordinal(mapping: dict, key: str, prefix: str) -> str:
        if key not in mapping:
            mapping[key] = '{0}_{1}'.format(prefix, len(mapping) + 1)
        return mapping[key]

    def user_token(self, name: str) -> str:
        return self._ordinal(self._user_map, name, 'USER')

    def host_token(self, name: str) -> str:
        return self._ordinal(self._host_map, name, 'HOST')

    def ip_token(self, addr: str) -> str:
        return '${' + self._ordinal(self._ip_map, addr, 'PRIVATE_IP') + '}'

    def mac_token(self, value: str) -> str:
        return '${' + self._ordinal(self._mac_map, value.lower(), 'DEVICE_ID') + '}'

    # ------------------------------------------------------------ 文本
    def redact_text(self, text: str) -> str:
        if not text:
            return text

        def _pem(match):
            self.counts['private_key_material'] += 1
            return PLACEHOLDER_SECRET

        text = PEM_BLOCK_RE.sub(_pem, text)

        def _cert(match):
            self.counts['certificate_material'] += 1
            return PLACEHOLDER_SECRET

        text = PEM_CERT_RE.sub(_cert, text)

        for pattern in TOKEN_RES:
            def _tok(match):
                self.counts['token'] += 1
                return PLACEHOLDER_SECRET
            text = pattern.sub(_tok, text)

        def _auth(match):
            self.counts['authorization_header'] += 1
            return match.group(1) + ' ' + PLACEHOLDER_SECRET

        text = AUTH_HEADER_RE.sub(_auth, text)

        def _kv(match):
            value = match.group(4)
            if value == PLACEHOLDER_SECRET or value.startswith('${'):
                return match.group(0)
            self.counts['credential_assignment'] += 1
            return '{0}{1}{2}{3}{2}'.format(match.group(1), match.group(2),
                                            match.group(3), PLACEHOLDER_SECRET)

        text = KV_SECRET_RE.sub(_kv, text)

        def _env(match):
            if match.group(2).startswith('${') or match.group(2) == PLACEHOLDER_SECRET:
                return match.group(0)
            self.counts['credential_env'] += 1
            return '{0}={1}'.format(match.group(1), PLACEHOLDER_SECRET)

        text = ENV_SECRET_RE.sub(_env, text)

        # 工作区真实路径 → 稳定别名（必须先于通用 /home 规则）
        workspace_variants = {self.workspace_root,
                              self.workspace_root.rstrip('/'),
                              os.path.realpath(self.workspace_root)}
        for variant in sorted(workspace_variants, key=len, reverse=True):
            if variant and variant in text:
                occurrences = text.count(variant)
                text = text.replace(variant, PLACEHOLDER_WORKSPACE)
                self.counts['workspace_path'] += occurrences

        for extra in self.extra_paths:
            if extra and extra in text:
                text = text.replace(extra, PLACEHOLDER_PRIVATE_PATH)
                self.counts['private_path'] += 1

        def _home(match):
            user = match.group(2)
            self.usernames.add(user)
            self.counts['home_path'] += 1
            return PLACEHOLDER_PRIVATE_PATH

        text = HOME_PATH_RE.sub(_home, text)

        def _root(match):
            self.counts['private_path'] += 1
            return PLACEHOLDER_PRIVATE_PATH

        text = ROOT_PATH_RE.sub(_root, text)
        text = WIN_PATH_RE.sub(lambda m: PLACEHOLDER_PRIVATE_PATH, text)

        # 主机名（先长后短，避免子串误替换）
        for host in sorted(self.hostnames, key=len, reverse=True):
            if host and host in text:
                token = self.host_token(host)
                text = text.replace(host, token)
                self.counts['hostname'] += 1

        # 独立出现的用户名（词边界，避免命中更长标识符的一部分）
        for user in sorted(self.usernames, key=len, reverse=True):
            if not user or len(user) < 3:
                continue
            pattern = re.compile(r'(?<![\w.-])' + re.escape(user) + r'(?![\w.-])')
            if pattern.search(text):
                token = self.user_token(user)
                text, n = pattern.subn(token, text)
                self.counts['username'] += n

        text = PRIVATE_IP_RE.sub(lambda m: self.ip_token(m.group(0)), text)
        text = MAC_RE.sub(lambda m: self.mac_token(m.group(0)), text)
        return text

    # ------------------------------------------------------------ 结构
    def redact_value(self, value, key=None):
        if key is not None and key in PRESERVE_FIELDS:
            return value
        if key is not None and isinstance(key, str) and SENSITIVE_KEY_PATTERN.search(key):
            if isinstance(value, (dict, list)):
                return PLACEHOLDER_SECRET
            if value in (None, ''):
                return value
            self.counts['sensitive_field'] += 1
            return PLACEHOLDER_SECRET
        if isinstance(value, str):
            return self.redact_text(value)
        if isinstance(value, dict):
            return {k: self.redact_value(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [self.redact_value(item) for item in value]
        # 数字 / 布尔 / None 原样保留，保证类型不变
        return value

    def redact_json_bytes(self, raw: bytes):
        doc = json.loads(raw.decode('utf-8'))
        return self.redact_value(doc)

    def redact_jsonl_bytes(self, raw: bytes) -> bytes:
        out_lines = []
        for line in raw.decode('utf-8').splitlines():
            stripped = line.strip()
            if not stripped:
                out_lines.append(line)
                continue
            try:
                doc = json.loads(stripped)
            except json.JSONDecodeError:
                # 不是合法 JSON 的行按文本处理，仍保证输出可解析性不被破坏
                out_lines.append(self.redact_text(line))
                continue
            out_lines.append(json.dumps(self.redact_value(doc), ensure_ascii=False))
        return ('\n'.join(out_lines) + '\n').encode('utf-8')

    YAML_KV_RE = re.compile(r'^(\s*(?:-\s*)?)([A-Za-z0-9_.-]+)(\s*:\s*)(.*)$')

    def redact_yaml_text(self, text: str) -> str:
        out = []
        for line in text.splitlines():
            match = self.YAML_KV_RE.match(line)
            if match and SENSITIVE_KEY_PATTERN.search(match.group(2)):
                out.append('{0}{1}{2}{3}'.format(match.group(1), match.group(2),
                                                 match.group(3), PLACEHOLDER_SECRET))
            else:
                out.append(self.redact_text(line))
        return '\n'.join(out) + ('\n' if text.endswith('\n') else '')


MAX_TEXT_BYTES = 64 * 1024 * 1024


def read_text_file(path: str):
    """完整读取并判定是否为文本。返回 (text, raw) 或 None。

    这里刻意**整文件解码**而不是采样：早先按 64KB 采样时，采样边界恰好截断了一个
    多字节中文字符，导致解码失败、文件被当成二进制**原样复制而未脱敏** ——
    一次静默的脱敏绕过。证据文件都很小，整文件解码既正确又便宜。
    """
    try:
        size = os.path.getsize(path)
    except OSError:
        return None
    if size > MAX_TEXT_BYTES:
        return None
    try:
        with open(path, 'rb') as handle:
            raw = handle.read()
    except OSError:
        return None
    if b'\x00' in raw:
        return None
    try:
        return raw.decode('utf-8'), raw
    except UnicodeDecodeError:
        return None


def redact_package(src_dir: str, dst_dir: str, workspace_root: str,
                   extra_usernames=(), extra_hostnames=(), extra_paths=()):
    """把 src_dir 脱敏复制到 dst_dir。返回 (redactor, report)。"""
    redactor = Redactor(workspace_root, extra_usernames, extra_hostnames, extra_paths)
    report = {'files_redacted': 0, 'files_copied_verbatim': 0, 'files_opaque': 0,
              'files_blocked': 0, 'blocked_files': [], 'opaque_files': [],
              'bytes_in': 0, 'bytes_out': 0}
    if not os.path.isdir(src_dir):
        raise FileNotFoundError('源证据目录不存在: {0}'.format(src_dir))
    if os.path.exists(dst_dir):
        shutil.rmtree(dst_dir)
    os.makedirs(dst_dir, exist_ok=True)

    for base, dirnames, filenames in os.walk(src_dir):
        dirnames.sort()
        rel_dir = os.path.relpath(base, src_dir)
        target_dir = dst_dir if rel_dir == '.' else os.path.join(dst_dir, rel_dir)
        os.makedirs(target_dir, exist_ok=True)
        for name in sorted(filenames):
            src = os.path.join(base, name)
            dst = os.path.join(target_dir, name)
            report['bytes_in'] += os.path.getsize(src)
            lower = name.lower()
            if lower.endswith(FORBIDDEN_SUFFIXES):
                # 密钥类文件绝不进入发布包
                report['files_blocked'] += 1
                report['blocked_files'].append(os.path.relpath(src, src_dir))
                redactor.counts['blocked_key_file'] += 1
                continue
            loaded = read_text_file(src)
            if loaded is None:
                # 非文本或过大：原样复制，但必须被记录，且由独立扫描器复核，
                # 不能假装"没有敏感信息"。
                shutil.copy2(src, dst)
                report['files_opaque'] += 1
                report['opaque_files'].append(os.path.relpath(src, src_dir))
                report['bytes_out'] += os.path.getsize(dst)
                continue
            _text, raw = loaded
            try:
                if lower.endswith('.jsonl'):
                    out = redactor.redact_jsonl_bytes(raw)
                    report['files_redacted'] += 1
                elif lower.endswith('.json'):
                    doc = redactor.redact_json_bytes(raw)
                    out = json.dumps(doc, ensure_ascii=False, indent=2).encode('utf-8')
                    report['files_redacted'] += 1
                elif lower.endswith(('.yaml', '.yml')):
                    out = redactor.redact_yaml_text(raw.decode('utf-8')).encode('utf-8')
                    report['files_redacted'] += 1
                else:
                    out = redactor.redact_text(raw.decode('utf-8')).encode('utf-8')
                    report['files_redacted'] += 1
            except (json.JSONDecodeError, UnicodeDecodeError):
                # 解析失败时退化为逐行文本脱敏，仍不放弃脱敏
                out = redactor.redact_text(raw.decode('utf-8', 'replace')).encode('utf-8')
                redactor.counts['fallback_text_redaction'] += 1
                report['files_redacted'] += 1
            with open(dst, 'wb') as handle:
                handle.write(out)
            report['bytes_out'] += len(out)
    report['mapping_counts'] = dict(redactor.counts)
    return redactor, report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='验收证据脱敏')
    parser.add_argument('--src', required=True, help='原始证据包目录')
    parser.add_argument('--dst', required=True, help='脱敏输出目录')
    parser.add_argument('--workspace-root', default=os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), help='工作区真实路径（替换为 ${WORKSPACE}）')
    parser.add_argument('--extra-username', action='append', default=[])
    parser.add_argument('--extra-hostname', action='append', default=[])
    parser.add_argument('--extra-path', action='append', default=[])
    parser.add_argument('--report', default=None, help='脱敏报告 JSON 输出路径')
    args = parser.parse_args(argv)

    try:
        redactor, report = redact_package(
            args.src, args.dst, args.workspace_root,
            extra_usernames=args.extra_username,
            extra_hostnames=args.extra_hostname,
            extra_paths=args.extra_path)
    except FileNotFoundError as exc:
        print('ERROR: {0}'.format(exc), file=sys.stderr)
        return 2

    summary = {
        'source_dir': os.path.abspath(args.src),
        'output_dir': os.path.abspath(args.dst),
        'files_redacted': report['files_redacted'],
        'files_opaque_copied': report['files_opaque'],
        'opaque_files': report['opaque_files'],
        'files_rejected_as_key_material': report['files_blocked'],
        'rejected_files': report['blocked_files'],
        'bytes_in': report['bytes_in'],
        'bytes_out': report['bytes_out'],
        'redaction_counts': report['mapping_counts'],
    }
    print('REDACTION SUMMARY {0}'.format(json.dumps(summary, ensure_ascii=False)))
    if args.report:
        with open(args.report, 'w', encoding='utf-8') as handle:
            json.dump(summary, handle, ensure_ascii=False, indent=2)
    # 注意：映射表刻意不落盘。任何把真实值写进发布产物的行为都是泄露。
    return 1 if report['files_blocked'] else 0


if __name__ == '__main__':
    sys.exit(main())
