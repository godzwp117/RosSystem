#!/usr/bin/env python3
"""redaction_check.py -- 脱敏与安全发布门禁测试（E1–E10）。

设计原则
--------
* E1–E5、E7 用**合成夹具**直接验证脱敏语义，不依赖 ROS/Docker，跑得快且定位准；
* E6 复用真实 M2 summary 验证导出器字段修复；
* E8–E10 驱动**真实发布器**，断言"该拒绝时确实没有推送"，并用远程 SHA 前后比对作为
  客观证据 —— 而不是只看脚本自己打印的状态字符串。

在宿主机执行：
    python3 tests/integration/redaction_check.py
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import re
import tempfile
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(ROOT, 'scripts')
EVIDENCE_ROOT = os.path.join(ROOT, 'tests', 'evidence')
REDACT = os.path.join(SCRIPTS, 'redact_evidence.py')
SAFETY = os.path.join(SCRIPTS, 'check_evidence_safety.py')
PUBLISH = os.path.join(SCRIPTS, 'publish_acceptance.py')


def load_publisher():
    spec = importlib.util.spec_from_file_location('rg_publish', PUBLISH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def utc_stamp():
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def now_iso():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def sh(argv, timeout=900, cwd=None):
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, cwd=cwd or ROOT)
    return proc.returncode, (proc.stdout or '') + (proc.stderr or '')


def parse_status(output: str):
    """发布器在不同路径下分别用单行/缩进 JSON 输出，统一用正则取状态。"""
    match = re.search(r'"status"\s*:\s*"([A-Z_]+)"', output)
    return match.group(1) if match else None


def remote_sha(remote='origin', branch='evidence/m3'):
    code, out = sh(['git', 'ls-remote', '--heads', remote, branch], timeout=120)
    if code == 0 and out.strip():
        return out.split()[0]
    return None


class Case:
    def __init__(self, case_id, name, expected):
        self.case_id = case_id
        self.name = name
        self.expected = expected
        self.checks = []
        self.commands = []
        self.dir = None
        self.note = ''

    def check(self, name, ok, detail=''):
        if isinstance(detail, (list, tuple)):
            detail = '; '.join(str(d) for d in detail) or '(empty)'
        self.checks.append({'check': name, 'result': 'PASS' if ok else 'FAIL',
                            'detail': str(detail)[:500]})
        return ok

    @property
    def passed(self):
        return bool(self.checks) and all(c['result'] == 'PASS' for c in self.checks)

    def finalize(self, observed=None):
        """把本用例实际观察到的内容落盘，作为可校验的证据文件。

        校验器要求"PASS 场景必须有真实执行证据"，空目录不算证据；
        这里把我们检查过的对象与结论一并写入，便于他人独立复核。
        """
        if not self.dir:
            return
        os.makedirs(self.dir, exist_ok=True)
        with open(os.path.join(self.dir, 'details.json'), 'w', encoding='utf-8') as handle:
            json.dump({'case': self.case_id, 'name': self.name,
                       'expected': self.expected, 'checks': self.checks,
                       'observed': observed or {}}, handle, ensure_ascii=False, indent=2)

    def summary(self):
        evidence = []
        if self.dir and os.path.isdir(self.dir):
            for base, _d, files in os.walk(self.dir):
                for name in sorted(files):
                    evidence.append(os.path.relpath(os.path.join(base, name), ROOT))
        return {
            'scenario': self.case_id,
            'scenario_id': self.case_id,
            'description': self.name,
            'scenario_name': self.name,
            'expected_result': self.expected,
            'actual_result': '; '.join('{0}={1}'.format(c['check'], c['result'])
                                       for c in self.checks)[:600],
            'result': 'PASS' if self.passed else 'FAIL',
            'status': 'PASS' if self.passed else 'FAIL',
            'evidence_dir': os.path.relpath(self.dir, ROOT) if self.dir else '',
            'command': self.commands[0]['argv'] if self.commands else [],
            'commands': self.commands,
            'exit_code': self.commands[0]['exit_code'] if self.commands else 0,
            'duration_ms': int(sum(c.get('duration_sec') or 0 for c in self.commands) * 1000),
            'log_path': evidence[0] if evidence else None,
            'evidence_files': evidence,
            'reason_code': None,
            'checks': self.checks,
            'notes': [self.note] if self.note else [],
            'suite': 'redaction',
        }


def make_fixture(root):
    """构造含各类敏感信息的合成证据目录。"""
    os.makedirs(os.path.join(root, 'logs'), exist_ok=True)
    host_user = os.environ.get('USER') or 'someuser'
    ws = ROOT
    with open(os.path.join(root, 'logs', 'app.log'), 'w', encoding='utf-8') as handle:
        handle.write('INFO start\n')
        handle.write('INFO user={0} home=/home/{0}/project\n'.format(host_user))
        handle.write('INFO workspace={0}/logs\n'.format(ws))
        handle.write('INFO resource=/rg/guarded_navigate decision=ALLOW reason=ALLOW_IN_POLICY\n')
        handle.write('INFO ip=192.168.1.77 mac=aa:bb:cc:dd:ee:ff\n')
        handle.write('INFO latency_ms=12 exit_code=0\n')
    with open(os.path.join(root, 'logs', 'audit.jsonl'), 'w', encoding='utf-8') as handle:
        for index in range(3):
            handle.write(json.dumps({
                'event_id': 'e' * 32, 'request_id': 'req-{0}'.format(index),
                'task_id': 'patrol_a_001', 'decision': 'ALLOW',
                'reason_code': 'ALLOW_IN_POLICY', 'downstream_goal_count': 1,
                'path_hint': '/home/{0}/x'.format(host_user),
            }, ensure_ascii=False) + '\n')
    with open(os.path.join(root, 'logs', 'config.yaml'), 'w', encoding='utf-8') as handle:
        handle.write('task_id: patrol_a_001\npolicy_version: "1.0"\n')
        handle.write('api_key: SUPERSECRETVALUE123\n')
        handle.write('log_dir: {0}/logs\n'.format(ws))
    return host_user


def e1_e2_e4_e5(case, tmp):
    fixture = os.path.join(tmp, 'fixture')
    out = os.path.join(tmp, 'redacted')
    os.makedirs(fixture, exist_ok=True)
    host_user = make_fixture(fixture)
    code, output = sh([sys.executable, REDACT, '--src', fixture, '--dst', out,
                       '--workspace-root', ROOT])
    case.commands.append({'step': 'redact', 'argv': [REDACT, '--src', fixture, '--dst', out],
                          'exit_code': code, 'duration_sec': 0})
    case.check('脱敏命令成功', code == 0, output.strip().splitlines()[-1:] or '')

    app = open(os.path.join(out, 'logs', 'app.log'), encoding='utf-8').read()
    # E1 宿主用户名
    e1 = host_user not in app
    case.check('E1 宿主真实用户名在公开副本中被脱敏', e1,
               'USER_n 占位' if e1 else '仍含真实用户名')
    # E2 绝对路径 → 稳定别名
    e2 = '/home/' not in app and '${WORKSPACE}' in app
    case.check('E2 绝对本地路径转换为稳定别名 ${WORKSPACE}', e2,
               '${WORKSPACE} 已出现且无 /home/' if e2 else app[:120])
    # 业务字段必须保留
    keep = '/rg/guarded_navigate' in app and 'ALLOW_IN_POLICY' in app and 'decision=ALLOW' in app
    case.check('E2b 业务资源名/判定/原因码未被破坏', keep, 'rg/guarded_navigate + ALLOW_IN_POLICY')
    # E4 JSONL 每行仍可解析
    lines = [line for line in open(os.path.join(out, 'logs', 'audit.jsonl'),
                                   encoding='utf-8').read().splitlines() if line.strip()]
    parsed = []
    ok4 = True
    for line in lines:
        try:
            parsed.append(json.loads(line))
        except json.JSONDecodeError:
            ok4 = False
    case.check('E4 JSONL 脱敏后每行仍可解析', ok4 and len(parsed) == 3,
               '{0} 行全部解析成功'.format(len(parsed)))
    # E5 event_id / request_id 关联保持
    ids = [item.get('event_id') for item in parsed]
    reqs = [item.get('request_id') for item in parsed]
    ok5 = ids == ['e' * 32] * 3 and reqs == ['req-0', 'req-1', 'req-2']
    case.check('E5 event_id/request_id 跨事件关联未丢失', ok5, 'id 与顺序一致')
    # 类型不变
    types_ok = all(isinstance(item.get('downstream_goal_count'), int) for item in parsed)
    case.check('E5b 数字类型保持（未被字符串化）', types_ok, 'downstream_goal_count 仍为 int')
    # 路径字段被脱敏但结构保留
    hints = [item.get('path_hint') for item in parsed]
    case.check('E5c JSON 中的路径值也被脱敏', all(h and '/home/' not in h for h in hints),
               str(hints[0])[:60])
    # YAML 敏感键
    yaml_text = open(os.path.join(out, 'logs', 'config.yaml'), encoding='utf-8').read()
    case.check('YAML 中 api_key 值被替换为 [REDACTED_SECRET]',
               'SUPERSECRETVALUE123' not in yaml_text and '[REDACTED_SECRET]' in yaml_text,
               'api_key 已脱敏')
    case.check('YAML 中业务字段（task_id/policy_version）保留',
               'patrol_a_001' in yaml_text and 'policy_version' in yaml_text, 'ok')
    return out


def e3(case, tmp):
    fixture = os.path.join(tmp, 'e3_fixture')
    os.makedirs(fixture, exist_ok=True)
    token = 'ghp_' + 'A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8'
    with open(os.path.join(fixture, 'leak.log'), 'w', encoding='utf-8') as handle:
        handle.write('token={0}\n'.format(token))
    with open(os.path.join(fixture, 'id_rsa'), 'w', encoding='utf-8') as handle:
        handle.write('-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXk=\n'
                     '-----END OPENSSH PRIVATE KEY-----\n')
    code, _ = sh([sys.executable, SAFETY, '--path', fixture, '--quiet'])
    case.commands.append({'step': 'safety_scan_injected', 'argv': [SAFETY, '--path', fixture],
                          'exit_code': code, 'duration_sec': 0})
    case.check('E3 含 Token 的目录被安全扫描判定为阻断', code == 1, 'exit={0}'.format(code))
    # 密钥材料必须被拒绝进入发布包
    out = os.path.join(tmp, 'e3_redacted')
    code2, _ = sh([sys.executable, REDACT, '--src', fixture, '--dst', out,
                   '--workspace-root', ROOT])
    case.check('E3b 密钥类文件被拒绝进入发布副本', code2 == 1
               and not os.path.exists(os.path.join(out, 'id_rsa')),
               'id_rsa 未出现在脱敏输出')
    # 脱敏后 Token 不再出现
    leak_text = open(os.path.join(out, 'leak.log'), encoding='utf-8').read()
    case.check('E3c 可脱敏的 Token 在公开副本中已被替换', token not in leak_text
               and '[REDACTED_SECRET]' in leak_text, leak_text.strip()[:60])
    scan_code, _ = sh([sys.executable, SAFETY, '--path', out, '--quiet'])
    case.check('E3d 脱敏后的副本通过安全扫描', scan_code == 0,
               'safety exit={0}'.format(scan_code))


def find_sros2_summary():
    """动态发现最近一次 sros2 场景 summary，避免把 run_id 写死。

    写死 run_id 会在 evidence 目录被清理后变成假失败（曾发生一次）。
    """
    import glob
    candidates = []
    for path in glob.glob(os.path.join(ROOT, 'tests', 'evidence', '*', 'summary.json')):
        try:
            with open(path, 'r', encoding='utf-8') as handle:
                doc = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue
        if doc.get('suite') == 'sros2':
            candidates.append((os.path.getmtime(path), path))
    return sorted(candidates)[-1][1] if candidates else None


def e6(case, tmp):
    summary = find_sros2_summary()
    if not summary:
        case.check('E6 前置：存在 sros2 安全场景 summary', False,
                   '未找到 suite=sros2 的 summary（请先运行 sros2_check.py）')
        return
    outdir = os.path.join(tmp, 'e6')
    code, output = sh([sys.executable, os.path.join(SCRIPTS, 'export_acceptance.py'),
                       '--phase', 'M2', '--status', 'PASS', '--run-id', 'e6_probe',
                       '--security-mode', 'enforce', '--security-summary', summary,
                       '--outdir', outdir])
    case.commands.append({'step': 'export', 'argv': ['export_acceptance.py', '--run-id', 'e6_probe'],
                          'exit_code': code, 'duration_sec': 0})
    case.check('E6 导出成功', code == 0, output.strip().splitlines()[-1:] or '')
    doc = json.load(open(os.path.join(outdir, 'e6_probe', 'security_results.json'),
                         encoding='utf-8'))
    by_id = {item['scenario_id']: item for item in doc['scenarios']}
    case.check('E6b 真实下游 Goal 数被保留（S3=0, S2=1, S3C=1）',
               by_id.get('S3', {}).get('downstream_goal_count') == 0
               and by_id.get('S2', {}).get('downstream_goal_count') == 1
               and by_id.get('S3C', {}).get('downstream_goal_count') == 1,
               {k: by_id.get(k, {}).get('downstream_goal_count')
                for k in ('S2', 'S3', 'S3C', 'S5')})
    case.check('E6c 拒绝层与原因码被保留',
               by_id.get('S3', {}).get('rejection_layer') == 'dds_security'
               and by_id.get('S3', {}).get('reason_code') == 'ACTION_CLIENT_CREATION_DENIED'
               and by_id.get('S5', {}).get('rejection_layer') == 'business_task_policy',
               'S3=dds_security / S5=business_task_policy')
    case.check('E6d actual_result 不再是 None/- 占位',
               'navsim_goals=None' not in str(by_id.get('S3', {}).get('actual_result'))
               and 'None' not in str(by_id.get('S3', {}).get('actual_result'))[:40],
               str(by_id.get('S3', {}).get('actual_result'))[:80])
    case.check('E6e Enforce 场景 domain 标为 43（非容器默认 42）',
               by_id.get('S2', {}).get('ros_domain_id') == 43
               and by_id.get('S1_normal_mode_a_zone', {}).get('ros_domain_id') == 42,
               {k: by_id.get(k, {}).get('ros_domain_id')
                for k in ('S1_normal_mode_a_zone', 'S2')})


def e7(case, tmp):
    """公开包哈希必须按脱敏后内容重算，且原包哈希不被冒充。"""
    pub = load_publisher()
    src = os.path.join(ROOT, 'artifacts', 'acceptance', 'published', 'm2_sros2_enforce')
    if not os.path.isdir(src):
        case.check('E7 前置：存在已发布副本', False, src)
        return
    code, _ = sh([sys.executable, os.path.join(SCRIPTS, 'verify_acceptance.py'), src, '--quiet'])
    case.commands.append({'step': 'verify_published', 'argv': ['verify_acceptance.py', src],
                          'exit_code': code, 'duration_sec': 0})
    case.check('E7 公开包自身校验通过（哈希按脱敏后内容重算）', code == 0,
               'verify exit={0}'.format(code))
    manifest = json.load(open(os.path.join(src, 'manifest.json'), encoding='utf-8'))
    red = manifest.get('redaction') or {}
    original = os.path.join(ROOT, 'artifacts', 'acceptance', 'exports', 'm2_sros2_enforce')
    same = True
    if os.path.isdir(original):
        for name in ('test_results.json', 'security_results.json'):
            a = os.path.join(original, name)
            b = os.path.join(src, name)
            if os.path.isfile(a) and os.path.isfile(b):
                if pub.sha256_file(a) == pub.sha256_file(b):
                    same = False
    case.check('E7b 公开包文件哈希与原始包不同（未被冒充）', same,
               '两个 JSON 的 SHA-256 均与原始包不同')
    case.check('E7c manifest 记录了 source_run_id 与原始包哈希引用',
               red.get('source_run_id') == 'm2_sros2_enforce'
               and bool(red.get('source_package_sha256')),
               'source_package_sha256={0}'.format(str(red.get('source_package_sha256'))[:16]))
    case.check('E7d 公开包内不含脱敏映射表', 'mapping' not in json.dumps(red, ensure_ascii=False),
               'redaction 块只含计数与引用')


def e8(case, tmp):
    """敏感信息扫描失败时，绝不能执行 git push。"""
    src = os.path.join(ROOT, 'artifacts', 'acceptance', 'exports', 'm2_sros2_enforce')
    if not os.path.isdir(src):
        case.check('E8 前置：存在源证据包', False, src)
        return
    run_id = 'e8_token_injection'
    work = os.path.join(tmp, 'e8')
    os.makedirs(work, exist_ok=True)
    pkg = os.path.join(work, run_id)
    shutil.copytree(src, pkg)
    # 注入一个真实格式的 Token（模拟"日志里混入凭证"）
    leak = os.path.join(pkg, 'logs', 'unit_tests.log')
    # 关键：这里刻意使用脱敏器**识别不到**的凭证形态（裸 JWT，且键名不含
    # password/token/secret 等敏感词）。否则脱敏器会先把它替换掉，扫描器自然
    # 无告警 —— 那样测的就不是"扫描门禁"，而是"脱敏器工作正常"。
    jwt = ('eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.'
           'eyJzdWIiOiJhZG1pbiIsImlhdCI6MTcwMDAwMDAwMH0.'
           'abcdefghijklmnopqrstuvwxyz0123456789ABCD')
    with open(leak, 'a', encoding='utf-8') as handle:
        handle.write('\nsession={0}\n'.format(jwt))
    pub = load_publisher()
    with open(os.path.join(pkg, 'manifest.json'), 'r', encoding='utf-8') as handle:
        manifest = json.load(handle)
    manifest['run_id'] = run_id
    with open(os.path.join(pkg, 'manifest.json'), 'w', encoding='utf-8') as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
    pub.rebuild_file_hashes(pkg, run_id)

    before = remote_sha()
    code, output = sh([sys.executable, PUBLISH, '--run-id', run_id, '--source-dir', pkg])
    after = remote_sha()
    case.commands.append({'step': 'publish_with_token', 'argv': [PUBLISH, '--run-id', run_id],
                          'exit_code': code, 'duration_sec': 0})
    status = parse_status(output)
    case.check('E8 含未脱敏凭证的证据发布被拒绝（非 0 退出）', code != 0, 'exit={0}'.format(code))
    case.check('E8b 发布状态为 BLOCKED，未伪装成功', status == 'BLOCKED', status)
    case.check('E8c 远程证据分支 SHA 未变化（确实没有 push）', before == after,
               'before={0} after={1}'.format(str(before)[:12], str(after)[:12]))


def e9(case, tmp):
    """无网络/无权限：保留本地待发布产物，状态不冒充 PASS。"""
    src = os.path.join(ROOT, 'artifacts', 'acceptance', 'exports', 'm2_sros2_enforce')
    if not os.path.isdir(src):
        case.check('E9 前置：存在源证据包', False, src)
        return
    run_id = 'e9_offline_retry'
    work = os.path.join(tmp, 'e9')
    os.makedirs(work, exist_ok=True)
    pkg = os.path.join(work, run_id)
    shutil.copytree(src, pkg)
    pub = load_publisher()
    with open(os.path.join(pkg, 'manifest.json'), 'r', encoding='utf-8') as handle:
        manifest = json.load(handle)
    manifest['run_id'] = run_id
    with open(os.path.join(pkg, 'manifest.json'), 'w', encoding='utf-8') as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
    pub.rebuild_file_hashes(pkg, run_id)

    code, output = sh([sys.executable, PUBLISH, '--run-id', run_id, '--source-dir', pkg,
                       '--remote', 'no_such_remote_rg'])
    status = parse_status(output)
    retry = None
    match = re.search(r'"retry_command"\s*:\s*"([^"]+)"', output)
    if match:
        retry = match.group(1)
    case.commands.append({'step': 'publish_offline', 'argv': [PUBLISH, '--run-id', run_id,
                                                              '--remote', 'no_such_remote_rg'],
                          'exit_code': code, 'duration_sec': 0})
    local = os.path.join(ROOT, 'artifacts', 'acceptance', 'published', run_id)
    case.check('E9 无可用 remote 时发布未报告成功', code != 0, 'exit={0}'.format(code))
    case.check('E9b 状态不是 PUBLISHED', status != 'PUBLISHED', status)
    case.check('E9c 本地待发布产物被保留', os.path.isfile(os.path.join(local, 'manifest.json')),
               local)


def e10(case):
    """同一 run_id 重复发布不得产生新提交、不得覆盖。"""
    if not os.path.isdir(os.path.join(ROOT, 'artifacts', 'acceptance', 'exports',
                                      'm2_sros2_enforce')):
        case.check('E10 前置：存在已发布证据包', False, 'missing')
        return
    before = remote_sha()
    code, output = sh([sys.executable, PUBLISH, '--run-id', 'm2_sros2_enforce'])
    after = remote_sha()
    status = parse_status(output)
    case.commands.append({'step': 'publish_twice', 'argv': [PUBLISH, '--run-id',
                                                            'm2_sros2_enforce'],
                          'exit_code': code, 'duration_sec': 0})
    case.check('E10 重复发布返回 ALREADY_PUBLISHED（幂等）', status == 'ALREADY_PUBLISHED',
               status)
    case.check('E10b 远程证据分支 SHA 未变化（无重复提交/无覆盖）', before == after,
               'before={0}'.format(str(before)[:12]))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='脱敏与发布门禁测试 E1-E10')
    parser.add_argument('--run-id', default=None)
    args = parser.parse_args(argv)
    run_id = args.run_id or utc_stamp()
    run_dir = os.path.join(EVIDENCE_ROOT, run_id)
    os.makedirs(run_dir, exist_ok=True)

    tmp = tempfile.mkdtemp(prefix='rg_redaction_')
    cases = []
    try:
        c1 = Case('E1_E2_E4_E5', '日志脱敏语义：用户名/路径/JSONL 可解析/事件关联/类型保持',
                  '公开副本中用户名与绝对路径被脱敏，业务字段与结构完整保留')
        c1.dir = os.path.join(run_dir, 'E1_E2_E4_E5')
        os.makedirs(c1.dir, exist_ok=True)
        out = e1_e2_e4_e5(c1, tmp)
        if os.path.isdir(out):
            shutil.copytree(out, os.path.join(c1.dir, 'redacted_copy'))
        cases.append(c1)

        c3 = Case('E3', '含 Token/私钥的材料不得进入公开证据',
                  '安全扫描判阻断、密钥类文件被拒绝、Token 被脱敏')
        c3.dir = os.path.join(run_dir, 'E3')
        os.makedirs(c3.dir, exist_ok=True)
        e3(c3, tmp)
        cases.append(c3)

        c6 = Case('E6', 'M2 安全场景导出保留真实 Goal 数与判定',
                  'downstream_goal_count / rejection_layer / reason_code / domain 正确')
        c6.dir = os.path.join(run_dir, 'E6')
        os.makedirs(c6.dir, exist_ok=True)
        e6(c6, tmp)
        cases.append(c6)

        c7 = Case('E7', '公开包哈希验证与来源可追溯',
                  '哈希按脱敏后内容重算、不冒充原始哈希、无映射表')
        c7.dir = os.path.join(run_dir, 'E7')
        os.makedirs(c7.dir, exist_ok=True)
        e7(c7, tmp)
        cases.append(c7)

        c8 = Case('E8', '敏感信息扫描失败不得执行 Git push',
                  '发布返回 BLOCKED 且远程 SHA 不变')
        c8.dir = os.path.join(run_dir, 'E8')
        os.makedirs(c8.dir, exist_ok=True)
        e8(c8, tmp)
        cases.append(c8)

        c9 = Case('E9', '无网络或无权限时保留待发布证据',
                  '状态非 PASS，本地待发布产物保留')
        c9.dir = os.path.join(run_dir, 'E9')
        os.makedirs(c9.dir, exist_ok=True)
        e9(c9, tmp)
        cases.append(c9)

        c10 = Case('E10', '同一 run_id 重复发布必须幂等',
                   '返回 ALREADY_PUBLISHED 且远程 SHA 不变')
        c10.dir = os.path.join(run_dir, 'E10')
        os.makedirs(c10.dir, exist_ok=True)
        e10(c10)
        cases.append(c10)

        # 统一落盘证据：把每个用例检查过的对象与结论写入其目录
        for case in cases:
            case.finalize({'checks_total': len(case.checks),
                           'checks_passed': sum(1 for c in case.checks if c['result'] == 'PASS'),
                           'commands': [{'step': c['step'], 'exit_code': c['exit_code']}
                                        for c in case.commands]})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    passed = sum(1 for c in cases if c.passed)
    summary = {
        'run_id': run_id, 'finished_at': now_iso(), 'workspace': ROOT,
        'suite': 'redaction', 'total': len(cases), 'passed': passed,
        'failed': len(cases) - passed,
        'scenarios': [c.summary() for c in cases],
    }
    with open(os.path.join(run_dir, 'summary.json'), 'w', encoding='utf-8') as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)

    print('\n' + '=' * 70)
    print('REDACTION SUMMARY ({0} passed / {1} total)'.format(passed, len(cases)))
    for case in cases:
        print('  [{0}] {1:<14} {2}'.format('PASS' if case.passed else 'FAIL',
                                           case.case_id, case.name[:46]))
        for check in case.checks:
            if check['result'] == 'FAIL':
                print('        FAIL: {0} -- {1}'.format(check['check'], check['detail'][:150]))
    print('evidence: {0}'.format(os.path.relpath(run_dir, ROOT)))
    return 0 if passed == len(cases) else 1


if __name__ == '__main__':
    sys.exit(main())
