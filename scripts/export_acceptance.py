#!/usr/bin/env python3
"""export_acceptance.py -- 导出标准化验收证据包（仅用 Python 标准库）。

设计要点
--------
* **只读原始数据**：不修改 `logs/`、`tests/evidence/` 中的任何文件，只做复制。
* **数据必须真实**：commit SHA 来自 `git rev-parse HEAD`；镜像 ID/RepoDigest 来自
  `docker inspect`；ROS/RMW 版本来自容器内实际查询。取不到就写 `null`，绝不编造。
* **脱敏**：`security/keystore/`、私钥类文件一律不纳入；正文命中密钥/口令模式的文件
  也会被排除并记入 `file_hashes.json:excluded`。
* **完整性**：包内每个文件计算 SHA-256 写入 `file_hashes.json`；`file_hashes.json`
  自身不参与哈希（无法自哈希），归档包哈希写在与包同级的 `.sha256` sidecar 中，
  这样打包之后包内文件不再变化，哈希始终自洽。

用法示例
--------
    python3 scripts/export_acceptance.py --phase P0 --status PASS \\
        --run-id p0_before_m1 --note "M1 修改前的原始快照"

    python3 scripts/export_acceptance.py --phase M2 --status PASS \\
        --security-mode enforce --security-results /tmp/m2_security.json

导出后可用 scripts/verify_acceptance.py 校验。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime, timezone

SCHEMA_VERSION = '1.0'
REPOSITORY = 'godzwp117/RosSystem'
DEFAULT_CONTAINER = os.environ.get('RG_CONTAINER', 'rg_jazzy')
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUTDIR = os.path.join(REPO_ROOT, 'artifacts', 'acceptance', 'exports')

# ---------------------------------------------------------------------------
# 脱敏规则
# ---------------------------------------------------------------------------
# 路径/文件名命中即排除（不读取内容）
EXCLUDE_PATH_PATTERNS = [
    re.compile(r'(^|/)security/keystore(/|$)'),
    re.compile(r'(^|/)\.git(/|$)'),
    re.compile(r'(^|/)build(/|$)'),
    re.compile(r'(^|/)install(/|$)'),
    re.compile(r'(^|/)__pycache__(/|$)'),
]
EXCLUDE_SUFFIXES = (
    '.pem', '.key', '.p12', '.pfx', '.csr', '.srl', '.der', '.jks',
    '.pyc', '.pyo', '.so', '.o', '.a',
)
# 正文命中即排除（文本文件）
SECRET_CONTENT_PATTERNS = [
    re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----'),
    re.compile(r'-----BEGIN CERTIFICATE-----'),
    re.compile(r'\bpassword\s*[:=]\s*\S+', re.IGNORECASE),
    re.compile(r'\bsecret\s*[:=]\s*\S+', re.IGNORECASE),
    re.compile(r'\bapi[_-]?key\s*[:=]\s*\S+', re.IGNORECASE),
    re.compile(r'\btoken\s*[:=]\s*[A-Za-z0-9._\-]{16,}', re.IGNORECASE),
]
TEXT_SUFFIXES = ('.log', '.json', '.jsonl', '.md', '.txt', '.yaml', '.yml', '.xml', '.py', '.sh', '.cfg', '.ini')


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def run(argv, timeout=60, cwd=None):
    """执行命令，返回 (exit_code, stdout+stderr)。失败不抛异常。"""
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, cwd=cwd)
        return proc.returncode, (proc.stdout or '') + (proc.stderr or '')
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b''):
            digest.update(chunk)
    return digest.hexdigest()


def is_excluded_path(rel_path: str) -> str:
    """命中脱敏规则时返回原因，否则返回空串。"""
    for pattern in EXCLUDE_PATH_PATTERNS:
        if pattern.search(rel_path):
            return 'path_rule:{0}'.format(pattern.pattern)
    if rel_path.lower().endswith(EXCLUDE_SUFFIXES):
        return 'suffix_rule'
    return ''


def content_has_secret(path: str) -> str:
    if not path.lower().endswith(TEXT_SUFFIXES):
        return ''
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as handle:
            text = handle.read(1 << 20)
    except OSError:
        return ''
    for pattern in SECRET_CONTENT_PATTERNS:
        if pattern.search(text):
            return 'content_rule:{0}'.format(pattern.pattern)
    return ''


# ---------------------------------------------------------------------------
# 真实环境采集
# ---------------------------------------------------------------------------
def collect_source() -> dict:
    code, head = run(['git', 'rev-parse', 'HEAD'])
    commit_sha = head.strip() if code == 0 and re.fullmatch(r'[0-9a-f]{40}', head.strip()) else ''
    code, status = run(['git', 'status', '--porcelain'])
    dirty_lines = [line for line in status.splitlines() if line.strip()] if code == 0 else []
    code, tags = run(['git', 'tag', '--points-at', 'HEAD'])
    head_tags = [t for t in tags.split() if t] if code == 0 else []
    code, remote = run(['git', 'config', '--get', 'remote.origin.url'])
    repo = REPOSITORY
    if code == 0 and remote.strip():
        match = re.search(r'[:/]([^/:]+/[^/]+?)(?:\.git)?$', remote.strip())
        if match:
            repo = match.group(1)
    source = {
        'repository': repo,
        'commit_sha': commit_sha,
        'git_dirty': bool(dirty_lines),
        'dirty_files': dirty_lines[:200],
        'tags': head_tags,
    }
    if not commit_sha:
        source['commit_sha_error'] = 'git rev-parse HEAD failed; SHA 不可用，未编造'
    return source


def _container_exec(script: str, timeout: int = 120):
    return run(['docker', 'exec', DEFAULT_CONTAINER, 'bash', '-lc',
                'source /opt/ros/jazzy/setup.bash >/dev/null 2>&1; ' + script], timeout=timeout)


def collect_environment() -> dict:
    host_os = ''
    try:
        with open('/etc/os-release', 'r', encoding='utf-8') as handle:
            for line in handle:
                if line.startswith('PRETTY_NAME='):
                    host_os = line.split('=', 1)[1].strip().strip('"')
                    break
    except OSError:
        host_os = os.uname().sysname
    code, kernel = run(['uname', '-r'])

    env = {
        'host_os': host_os or 'unknown',
        'kernel': kernel.strip() if code == 0 else '',
        'container_name': DEFAULT_CONTAINER,
        'ros_distro': '',
        'rmw_implementation': '',
        'docker_image_id': '',
        'docker_image_digest': None,
    }

    # 容器内版本（真实查询）
    code, out = _container_exec(
        'echo "DISTRO=${ROS_DISTRO}"; echo "RMW=${RMW_IMPLEMENTATION}"; '
        'echo "DOMAIN=${ROS_DOMAIN_ID}"; echo "PY=$(python3 --version 2>&1)"; '
        'python3 -c "import rclpy,importlib.metadata as m;'
        'print(\'RCLPY=\'+m.version(\'rclpy\'))" 2>/dev/null; '
        'python3 -c "import importlib.metadata as m;print(\'SROS2=\'+m.version(\'sros2\'))" 2>/dev/null; '
        'echo "OPENSSL=$(openssl version 2>&1)"')
    for line in out.splitlines():
        if line.startswith('DISTRO='):
            env['ros_distro'] = line.split('=', 1)[1].strip()
        elif line.startswith('RMW='):
            env['rmw_implementation'] = line.split('=', 1)[1].strip() or 'default(rmw_fastrtps_cpp)'
        elif line.startswith('DOMAIN='):
            env['ros_domain_id'] = line.split('=', 1)[1].strip()
        elif line.startswith('PY='):
            env['python_version'] = line.split('=', 1)[1].strip()
        elif line.startswith('RCLPY='):
            env['rclpy_version'] = line.split('=', 1)[1].strip()
        elif line.startswith('SROS2='):
            env['sros2_version'] = line.split('=', 1)[1].strip()
        elif line.startswith('OPENSSL='):
            env['openssl_version'] = line.split('=', 1)[1].strip()

    # 镜像 ID / digest：来自 docker inspect；没有 RepoDigest 就写 null
    code, image = run(['docker', 'inspect', '-f', '{{.Image}}', DEFAULT_CONTAINER])
    if code == 0 and image.strip():
        env['docker_image_id'] = image.strip()
    code, ref = run(['docker', 'inspect', '-f', '{{.Config.Image}}', DEFAULT_CONTAINER])
    image_ref = ref.strip() if code == 0 else ''
    if image_ref:
        env['docker_image_ref'] = image_ref
        code, digests = run(['docker', 'image', 'inspect', image_ref, '-f', '{{json .RepoDigests}}'])
        if code == 0:
            try:
                parsed = json.loads(digests.strip())
            except json.JSONDecodeError:
                parsed = []
            env['docker_image_digest'] = parsed[0] if parsed else None
    return env


# ---------------------------------------------------------------------------
# 证据收集
# ---------------------------------------------------------------------------
class PackageBuilder:
    def __init__(self, root: str):
        self.root = root
        self.copied: list = []
        self.excluded: list = []

    def copy_file(self, src: str, rel_dest: str) -> str:
        """复制单个文件进证据包；命中脱敏规则则排除。返回包内相对路径或空串。"""
        if not os.path.isfile(src):
            return ''
        reason = is_excluded_path(rel_dest)
        if not reason:
            reason = content_has_secret(src)
        if reason:
            self.excluded.append({'source': src, 'reason': reason})
            return ''
        dest = os.path.join(self.root, rel_dest)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(src, dest)
        self.copied.append(rel_dest)
        return rel_dest

    def copy_tree(self, src_dir: str, rel_dest_dir: str, max_files: int = 4000) -> list:
        out = []
        if not os.path.isdir(src_dir):
            return out
        for base, dirs, files in os.walk(src_dir):
            dirs[:] = [d for d in dirs if d not in {'__pycache__', '.git'}]
            for name in sorted(files):
                if len(out) >= max_files:
                    return out
                src = os.path.join(base, name)
                rel = os.path.relpath(src, src_dir)
                copied = self.copy_file(src, os.path.join(rel_dest_dir, rel))
                if copied:
                    out.append(copied)
        return out


def scenario_from_runner_entry(entry: dict, pkg: 'PackageBuilder', evidence_rel: str) -> dict:
    """把 scenario_runner 的 summary 条目转换为冻结的 scenario 记录。"""
    expectations = entry.get('expectations') or {}
    expected_bits = []
    if 'navsim_goals' in expectations:
        expected_bits.append('navsim_goals={0}'.format(expectations['navsim_goals']))
    if expectations.get('decision_codes'):
        expected_bits.append('decision_codes={0}'.format(','.join(expectations['decision_codes'])))
    if 'execution_events' in expectations:
        expected_bits.append('execution_events={0}'.format(expectations['execution_events']))
    if 'reject_logs' in expectations:
        expected_bits.append('reject_logs={0}'.format(expectations['reject_logs']))
    expected = '; '.join(expected_bits) or (entry.get('description') or 'see checks')

    actual = 'navsim_goals={0}; decisions={1}; executions={2}; rejects={3}'.format(
        entry.get('navsim_goal_count'),
        ','.join(entry.get('decision_sequence') or []) or '-',
        ','.join(entry.get('execution_status_codes') or []) or '-',
        entry.get('reject_log_lines'))

    commands = entry.get('commands') or []
    argv: list = []
    exit_code = None
    duration_ms = 0
    for command in commands:
        if command.get('argv') and not argv:
            argv = list(command['argv'])
        if command.get('duration_sec'):
            duration_ms += int(float(command['duration_sec']) * 1000)
    planner_exits = [c for c in (entry.get('planner_exit_codes') or []) if c is not None]
    if planner_exits:
        exit_code = planner_exits[0]
    else:
        # 非业务场景（如 start_system 生命周期检查）没有 planner 退出码，
        # 回退到最后一个有返回码的命令，保证 PASS 场景也有真实返回码可核。
        for command in reversed(commands):
            if command.get('exit_code') is not None:
                exit_code = command['exit_code']
                break

    decision_codes = entry.get('decision_sequence') or []
    exec_codes = entry.get('execution_status_codes') or []
    reason = exec_codes[-1] if exec_codes else (decision_codes[-1] if decision_codes else None)

    evidence_files = list(entry.get('_evidence_files') or [])
    log_path = None
    for candidate in evidence_files:
        if candidate.endswith('gateway.log'):
            log_path = candidate
            break
    if log_path is None and evidence_files:
        log_path = evidence_files[0]

    scenario_id = entry.get('scenario') or entry.get('scenario_id')
    scenario_name = entry.get('description') or entry.get('scenario_name') or scenario_id
    record = {
        'scenario_id': scenario_id,
        'scenario_name': scenario_name,
        'expected_result': expected,
        'actual_result': actual,
        # scenario_runner 用 'result'，本仓较新的检查脚本用 'status'，两者都要接受，
        # 否则缺失的键会被默认成 NOT_RUN，把"通过"错报成"未执行"。
        'status': entry.get('result') or entry.get('status') or 'NOT_RUN',
        'command': argv,
        'exit_code': exit_code,
        'duration_ms': duration_ms,
        'log_path': log_path,
        'evidence_files': evidence_files,
        'reason_code': reason,
        'checks': entry.get('checks') or [],
        'suite': entry.get('suite'),
    }
    # 安全对照实验场景会带 security_mode / enclave / rejection_layer 等字段，
    # 必须原样保留，否则 security_results.json 会丢失"拒绝发生在哪一层"的关键信息。
    for key in ('security_mode', 'source_role', 'source_enclave', 'requested_resource',
                'downstream_goal_count', 'rejection_layer', 'notes'):
        if entry.get(key) is not None:
            record[key] = entry[key]
    return record


def collect_scenarios(summary_paths: list, pkg: PackageBuilder) -> tuple:
    """读 scenario_runner 的 summary.json，复制其证据目录，返回 (scenarios, sources)。"""
    scenarios = []
    sources = []
    for summary_path in summary_paths:
        if not os.path.isfile(summary_path):
            sources.append({'path': summary_path, 'status': 'MISSING'})
            continue
        try:
            with open(summary_path, 'r', encoding='utf-8') as handle:
                summary = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            sources.append({'path': summary_path, 'status': 'UNREADABLE', 'error': str(exc)})
            continue
        run_name = os.path.basename(os.path.dirname(summary_path))
        sources.append({'path': summary_path, 'status': 'OK',
                        'run': run_name, 'scenarios': len(summary.get('scenarios') or [])})
        for entry in summary.get('scenarios') or []:
            ev_dir = entry.get('evidence_dir')
            rel_files: list = []
            if ev_dir and os.path.isdir(ev_dir):
                entry_id = (entry.get('scenario') or entry.get('scenario_id') or 'unknown')
                rel_files = pkg.copy_tree(
                    ev_dir, os.path.join('logs', 'tests_evidence', run_name, entry_id))
            entry = dict(entry)
            entry['_evidence_files'] = rel_files
            scenarios.append(scenario_from_runner_entry(entry, pkg, ev_dir or ''))
        pkg.copy_file(summary_path, os.path.join('logs', 'tests_evidence', run_name, 'summary.json'))
        md = os.path.join(os.path.dirname(summary_path), 'summary.md')
        pkg.copy_file(md, os.path.join('logs', 'tests_evidence', run_name, 'summary.md'))
    return scenarios, sources


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='导出标准化验收证据包')
    parser.add_argument('--phase', required=True, choices=['P0', 'M1', 'M2'])
    parser.add_argument('--status', required=True, choices=['PASS', 'FAIL', 'PARTIAL', 'BLOCKED'])
    parser.add_argument('--run-id', default=None)
    parser.add_argument('--security-mode', default='disabled', choices=['disabled', 'enforce'])
    parser.add_argument('--scenario-summary', action='append', default=None,
                        help='scenario_runner 的 summary.json 路径，可重复；默认为 tests/evidence/*/summary.json')
    parser.add_argument('--security-results', default=None,
                        help='M2 安全对照实验结果 JSON（含 enclaves 与 scenarios）')
    parser.add_argument('--security-summary', action='append', default=None,
                        help='安全对照实验的 summary.json（suite=sros2）。其场景写入 '
                             'security_results.json，且不计入 test_results.json，避免重复计数')
    parser.add_argument('--include', action='append', default=None,
                        help='额外纳入证据包的日志文件或目录，可重复')
    parser.add_argument('--note', action='append', default=None, help='备注，可重复')
    parser.add_argument('--status-matrix', default=None, help='状态矩阵 JSON 文件路径')
    parser.add_argument('--outdir', default=DEFAULT_OUTDIR)
    parser.add_argument('--no-archive', action='store_true')
    parser.add_argument('--quiet', action='store_true')

    args = parser.parse_args(argv)

    def _abs(path):
        if path is None:
            return None
        return path if os.path.isabs(path) else os.path.join(REPO_ROOT, path)

    args.security_results = _abs(args.security_results)
    args.status_matrix = _abs(args.status_matrix)
    args.include = [_abs(p) for p in (args.include or [])]
    args.scenario_summary = [_abs(p) for p in (args.scenario_summary or [])] or None
    args.outdir = args.outdir if os.path.isabs(args.outdir) else os.path.join(REPO_ROOT, args.outdir)

    run_id = args.run_id or '{0}_{1}'.format(args.phase.lower(), utc_stamp())
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{2,63}', run_id):
        print('ERROR: run_id 非法（仅允许字母数字 . _ -，3~64 字符）: {0}'.format(run_id), file=sys.stderr)
        return 2

    pkg_root = os.path.join(args.outdir, run_id)
    if os.path.exists(pkg_root):
        print('ERROR: 证据包已存在，拒绝覆盖: {0}'.format(pkg_root), file=sys.stderr)
        return 2
    os.makedirs(pkg_root)

    pkg = PackageBuilder(pkg_root)
    print('[export] run_id={0} phase={1} status={2}'.format(run_id, args.phase, args.status))

    source = collect_source()
    environment = collect_environment()
    print('[export] commit={0} dirty={1} image={2}'.format(
        source['commit_sha'][:12] or '<unavailable>', source['git_dirty'],
        (environment['docker_image_digest'] or environment['docker_image_id'])[:30]))

    # --- 收集场景证据 ---
    security_summaries = args.security_summary or []
    if args.scenario_summary:
        summaries = [p for p in args.scenario_summary if p not in security_summaries]
    else:
        summaries = []
        skipped_security = []
        evidence_root = os.path.join(REPO_ROOT, 'tests', 'evidence')
        if os.path.isdir(evidence_root):
            for name in sorted(os.listdir(evidence_root)):
                candidate = os.path.join(evidence_root, name, 'summary.json')
                if not os.path.isfile(candidate):
                    continue
                if candidate in security_summaries:
                    continue
                try:
                    with open(candidate, 'r', encoding='utf-8') as handle:
                        suite = json.load(handle).get('suite')
                except (OSError, json.JSONDecodeError):
                    suite = None
                if suite == 'sros2':
                    skipped_security.append(candidate)
                    continue
                summaries.append(candidate)
        if skipped_security and not security_summaries:
            print('[export] WARN 发现 {0} 个 suite=sros2 的证据目录但未用 --security-summary 指定，'
                  '已跳过（避免与 test_results 重复计数）:'.format(len(skipped_security)))
            for item in skipped_security:
                print('         - {0}'.format(os.path.relpath(item, REPO_ROOT)))
    scenarios, summary_sources = collect_scenarios(summaries, pkg)
    print('[export] scenarios={0} from {1} summary file(s)'.format(len(scenarios), len(summaries)))

    # --- 安全对照实验（suite=sros2）场景：归入 security_results.json ---
    sec_from_summary = []
    sec_summary_sources = []
    if security_summaries:
        sec_from_summary, sec_summary_sources = collect_scenarios(security_summaries, pkg)
        print('[export] security scenarios (from summary) = {0}'.format(len(sec_from_summary)))

    # --- 安全对照实验结果 ---
    security = None
    if security_summaries and not args.security_results:
        enclaves_meta = []
        policy_path = os.path.join(REPO_ROOT, 'security', 'policies', 'minimal_permissions.xml')
        if os.path.isfile(policy_path):
            try:
                import xml.etree.ElementTree as _ET
                root = _ET.parse(policy_path).getroot()
                for enclave in root.iter():
                    if enclave.tag.split('}')[-1] != 'enclave':
                        continue
                    topics, services, nodes = set(), set(), []
                    for profile in enclave.iter():
                        tag = profile.tag.split('}')[-1]
                        if tag == 'profile':
                            nodes.append(profile.get('node'))
                        elif tag == 'topic' and profile.text:
                            topics.add(profile.text.strip())
                        elif tag == 'service' and profile.text:
                            services.add(profile.text.strip())
                    enclaves_meta.append({
                        'enclave': enclave.get('path'),
                        'role': (enclave.get('path') or '').strip('/'),
                        'nodes': [n for n in nodes if n],
                        'allowed_resources': sorted(topics | services),
                        'denied_resources': [],
                    })
            except Exception as exc:  # noqa: BLE001
                print('[export] WARN 解析策略失败: {0}'.format(exc))
        security = {
            'schema_version': SCHEMA_VERSION,
            'run_id': run_id,
            'security_mode': args.security_mode,
            'keystore_path': os.path.join(REPO_ROOT, 'security', 'keystore'),
            'keystore_included_in_package': False,
            'enclaves': enclaves_meta,
            'scenarios': sec_from_summary,
            'generated_from': [s2['path'] for s2 in sec_summary_sources],
            'policy_file': os.path.relpath(policy_path, REPO_ROOT) if os.path.isfile(policy_path) else None,
        }
        pkg.copy_file(policy_path, 'logs/security_policy/minimal_permissions.xml')
    elif args.security_results:
        if os.path.isfile(args.security_results):
            with open(args.security_results, 'r', encoding='utf-8') as handle:
                raw = json.load(handle)
            sec_scenarios = []
            for entry in raw.get('scenarios') or []:
                record = {key: entry.get(key) for key in (
                    'scenario_id', 'scenario_name', 'expected_result', 'actual_result', 'status',
                    'command', 'exit_code', 'duration_ms', 'log_path', 'evidence_files',
                    'reason_code', 'security_mode', 'source_role', 'source_enclave',
                    'requested_resource', 'downstream_goal_count', 'rejection_layer', 'checks', 'notes')}
                record.setdefault('security_mode', args.security_mode)
                record['evidence_files'] = list(record.get('evidence_files') or [])
                if record['status'] is None:
                    record['status'] = 'NOT_RUN'
                sec_scenarios.append(record)
            security = {
                'schema_version': SCHEMA_VERSION,
                'run_id': run_id,
                'security_mode': args.security_mode,
                'keystore_path': raw.get('keystore_path'),
                'enclaves': raw.get('enclaves') or [],
                'scenarios': sec_scenarios,
                'generated_from': [args.security_results],
            }
            pkg.copy_file(args.security_results, 'logs/security_results_input.json')
            print('[export] security scenarios={0}'.format(len(sec_scenarios)))
        else:
            security = {'schema_version': SCHEMA_VERSION, 'run_id': run_id,
                        'security_mode': args.security_mode, 'keystore_path': None,
                        'enclaves': [], 'scenarios': [],
                        'error': 'security-results 文件不存在: {0}'.format(args.security_results)}
            print('[export] WARN security-results 文件不存在，security_results.json 记为空')

    # --- 日志 ---
    default_logs = []
    logs_root = os.path.join(REPO_ROOT, 'logs')
    if os.path.isdir(logs_root):
        for name in sorted(os.listdir(logs_root)):
            path = os.path.join(logs_root, name)
            if os.path.isfile(path) and name.endswith(('.log', '.txt', '.json', '.jsonl')):
                default_logs.append(path)
    for item in (args.include or []):
        if os.path.isdir(item):
            pkg.copy_tree(item, os.path.join('logs', 'extra', os.path.basename(item.rstrip('/'))))
        else:
            default_logs.append(item)
    for path in default_logs:
        pkg.copy_file(path, os.path.join('logs', os.path.basename(path)))
    # 权威策略（不含密钥，纳入以便复核判定依据）
    pkg.copy_file(os.path.join(REPO_ROOT, 'config', 'task_policy.yaml'), 'logs/config/task_policy.yaml')

    # --- 汇总 ---
    all_records = list(scenarios) + list((security or {}).get('scenarios', []))
    test_summary = {
        'passed': sum(1 for s in all_records if s['status'] == 'PASS'),
        'failed': sum(1 for s in all_records if s['status'] == 'FAIL'),
        'not_run': sum(1 for s in all_records if s['status'] == 'NOT_RUN'),
        'blocked': sum(1 for s in all_records if s['status'] == 'BLOCKED'),
        'total': len(all_records),
    }

    status_matrix = None
    if args.status_matrix and os.path.isfile(args.status_matrix):
        try:
            with open(args.status_matrix, 'r', encoding='utf-8') as handle:
                status_matrix = json.load(handle)
        except (OSError, json.JSONDecodeError):
            status_matrix = None

    # --- 写包内文件（顺序：业务文件 -> 哈希 -> manifest） ---
    def write_json(rel_path: str, payload) -> str:
        dest = os.path.join(pkg_root, rel_path)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, 'w', encoding='utf-8') as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=False)
            handle.write('\n')
        pkg.copied.append(rel_path)
        return rel_path

    write_json('environment.json', {
        'schema_version': SCHEMA_VERSION, 'run_id': run_id,
        'timestamp_utc': utc_now_iso(), 'environment': environment,
    })
    write_json('test_results.json', {
        'schema_version': SCHEMA_VERSION, 'run_id': run_id,
        'generated_from': [s['path'] for s in summary_sources],
        'sources': summary_sources,
        'scenarios': scenarios,
    })
    if security is not None:
        write_json('security_results.json', security)

    notes = list(args.note or [])
    notes.append('file_hashes.json 不包含自身哈希（无法自哈希）；归档包 SHA-256 记录在 '
                 'exports/<run_id>.tar.gz.sha256 sidecar 中，故打包后包内哈希保持自洽。')

    manifest = {
        'schema_version': SCHEMA_VERSION,
        'run_id': run_id,
        'timestamp_utc': utc_now_iso(),
        'phase': args.phase,
        'status': args.status,
        'source': source,
        'environment': environment,
        'security_mode': args.security_mode,
        'test_summary': test_summary,
        'notes': notes,
        'artifacts': {
            'archive': None if args.no_archive else '{0}.tar.gz'.format(run_id),
            'archive_sha256': None,
            'file_count': 0,
            'total_bytes': 0,
        },
    }
    if status_matrix is not None:
        manifest['status_matrix'] = status_matrix
    write_json('manifest.json', manifest)

    # --- 计算哈希 ---
    files = []
    total_bytes = 0
    for rel in sorted(set(pkg.copied)):
        abs_path = os.path.join(pkg_root, rel)
        if not os.path.isfile(abs_path):
            continue
        size = os.path.getsize(abs_path)
        total_bytes += size
        files.append({'path': rel, 'sha256': sha256_file(abs_path), 'size_bytes': size})
    write_json('file_hashes.json', {
        'schema_version': SCHEMA_VERSION, 'run_id': run_id, 'algorithm': 'sha256',
        'files': files,
        'excluded': pkg.excluded,
    })

    # 回填 manifest 的计数（重写后需重算 manifest 的哈希）
    manifest['artifacts']['file_count'] = len(files) + 1
    manifest['artifacts']['total_bytes'] = total_bytes
    with open(os.path.join(pkg_root, 'manifest.json'), 'w', encoding='utf-8') as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
    # manifest.json 正文变了 -> 其哈希必须重算
    for record in files:
        if record['path'] == 'manifest.json':
            record['sha256'] = sha256_file(os.path.join(pkg_root, 'manifest.json'))
            record['size_bytes'] = os.path.getsize(os.path.join(pkg_root, 'manifest.json'))
    with open(os.path.join(pkg_root, 'file_hashes.json'), 'w', encoding='utf-8') as handle:
        json.dump({'schema_version': SCHEMA_VERSION, 'run_id': run_id, 'algorithm': 'sha256',
                   'files': files, 'excluded': pkg.excluded}, handle, ensure_ascii=False, indent=2)
        handle.write('\n')

    archive_path = None
    archive_sha = None
    if not args.no_archive:
        archive_path = os.path.join(args.outdir, '{0}.tar.gz'.format(run_id))
        with tarfile.open(archive_path, 'w:gz') as tar:
            tar.add(pkg_root, arcname=run_id)
        archive_sha = sha256_file(archive_path)
        with open(archive_path + '.sha256', 'w', encoding='utf-8') as handle:
            handle.write('{0}  {1}\n'.format(archive_sha, os.path.basename(archive_path)))

    result = {
        'run_id': run_id,
        'package_dir': pkg_root,
        'archive': archive_path,
        'archive_sha256': archive_sha,
        'files': len(files) + 1,
        'total_bytes': total_bytes,
        'scenarios': len(scenarios),
        'security_scenarios': len((security or {}).get('scenarios', [])),
        'excluded': pkg.excluded,
        'test_summary': test_summary,
    }
    if not args.quiet:
        print('[export] files={0} bytes={1}'.format(result['files'], result['total_bytes']))
        if pkg.excluded:
            print('[export] 脱敏排除 {0} 个文件:'.format(len(pkg.excluded)))
            for item in pkg.excluded[:10]:
                print('         - {0} ({1})'.format(item['source'], item['reason']))
        print('[export] package: {0}'.format(pkg_root))
        if archive_path:
            print('[export] archive: {0}'.format(archive_path))
            print('[export] sha256 : {0}'.format(archive_sha))
        print('[export] test_summary: {0}'.format(test_summary))
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
