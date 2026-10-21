#!/usr/bin/env python3
"""DDS lab negative experiments (1.1.0): trust root, signature, Enforce-off.

Design rule
-----------
A denial is only evidence of *DDS access control* if a positive control on the
same stack, in the same window, succeeds. Every negative case below is therefore
paired with a live control; "the server was not there" is never accepted as a
security result.

Cases
-----
N0  control: /gateway identity -> /rg/nav_execute succeeds (1 goal)
N1  a participant anchored in a *different* CA cannot join the domain-43 stack
N2  a tampered permissions.p7s makes the /planner participant unable to act
N3  Enforce disabled (control condition): the same unauthorized client succeeds
N4  certificate/enclave mismatch cannot inherit /gateway permissions
N5  tampering permissions.xml after signing is rejected (signature invalid)

All temporary keystores live in a private temp directory and are removed; no
private key is copied into the evidence tree.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import sros2_check as sc  # noqa: E402

EVIDENCE_ROOT = ROOT / 'tests' / 'evidence'
RUN_ID = os.environ.get('RG_NEG_RUN_ID') or time.strftime('v110ddsneg-%Y%m%dT%H%M%SZ', time.gmtime())
SECURE_DOMAIN = '43'
OPEN_DOMAIN = '44'
KEYSTORE = ROOT / 'security' / 'keystore'
POLICY = ROOT / 'security' / 'policies' / 'minimal_permissions.xml'
ACTION_EXECUTE = '/rg/nav_execute'


def sh(argv, env=None, timeout=300, check=True):
    full_env = dict(os.environ)
    full_env.update(env or {})
    proc = subprocess.run(argv, cwd=str(ROOT), env=full_env, capture_output=True,
                          text=True, timeout=timeout)
    if check and proc.returncode != 0:
        raise RuntimeError('{0} failed ({1}): {2}'.format(
            ' '.join(argv), proc.returncode, (proc.stderr or proc.stdout)[-800:]))
    return proc


def make_keystore(path, enclaves):
    sh(['ros2', 'security', 'create_keystore', str(path)], env={'ROS_DOMAIN_ID': SECURE_DOMAIN})
    sh(['ros2', 'security', 'generate_artifacts', '-k', str(path),
        '-e', *enclaves, '-p', str(POLICY)], env={'ROS_DOMAIN_ID': SECURE_DOMAIN})
    return path


def count_lines(path):
    try:
        return sum(1 for line in Path(path).read_text(encoding='utf-8').splitlines()
                   if line.strip())
    except OSError:
        return 0


def read_jsonl(path):
    rows = []
    try:
        for line in Path(path).read_text(encoding='utf-8').splitlines():
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    except OSError:
        pass
    return rows


def result_dir(label):
    target = EVIDENCE_ROOT / RUN_ID / label
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    return target


def run_planner(case_dir, keystore, request_id, x, y, expect_success=1, label='planner'):
    log_path = case_dir / (label + '.log')
    env = dict(os.environ)
    env.update({'ROS_DOMAIN_ID': SECURE_DOMAIN, 'ROS_SECURITY_ENABLE': 'true',
                'ROS_SECURITY_STRATEGY': 'Enforce',
                'ROS_SECURITY_KEYSTORE': str(keystore),
                'ROS_SECURITY_ENCLAVE_OVERRIDE': '/planner',
                'PYTHONUNBUFFERED': '1'})
    argv = ['ros2', 'run', 'rg_demo_nodes', 'planner_node', '--ros-args',
            '-p', 'request_id:={0}'.format(request_id),
            '-p', 'task_id:=patrol_a_001', '-p', 'frame_id:=map',
            '-p', 'target_x:={0}'.format(x), '-p', 'target_y:={0}'.format(y),
            '-p', 'expect_success:={0}'.format(expect_success)]
    proc = subprocess.run(argv, cwd=str(ROOT), env=env, capture_output=True,
                          text=True, timeout=240)
    output = (proc.stdout or '') + (proc.stderr or '')
    log_path.write_text(output, encoding='utf-8')
    parsed = None
    for line in output.splitlines():
        if line.strip().startswith('PLANNER_RESULT '):
            try:
                parsed = json.loads(line.strip()[len('PLANNER_RESULT '):])
            except json.JSONDecodeError:
                pass
    return {'exit_code': proc.returncode, 'result': parsed,
            'security_evidence': any(k in output.lower() for k in
                                     ('security', 'keystore', 'permission', 'denied')),
            'output_tail': output[-600:]}


class Case:
    def __init__(self, case_id, description):
        self.case_id = case_id
        self.description = description
        self.checks = []
        self.dir = result_dir(case_id)
        self.notes = []

    def check(self, name, ok, detail):
        self.checks.append({'check': name, 'result': 'PASS' if ok else 'FAIL',
                            'detail': str(detail)[:800]})
        return ok

    @property
    def passed(self):
        return bool(self.checks) and all(c['result'] == 'PASS' for c in self.checks)

    def summary(self):
        return {'case_id': self.case_id, 'description': self.description,
                'result': 'PASS' if self.passed else 'FAIL',
                'checks': self.checks, 'notes': self.notes,
                'evidence_dir': str(self.dir.relative_to(ROOT))}


def start_secure_stack():
    sc.EVIDENCE_ROOT = str(EVIDENCE_ROOT)
    sc.RUN_ID = RUN_ID
    sc.KEYSTORE = str(KEYSTORE)
    stack_case = sc.Case('_neg_stack', 'secured stack for negative experiments',
                         'ready', secure=True)
    nodes, journal, audit, gw_log = sc.start_stack(
        stack_case, int(SECURE_DOMAIN), True,
        {'operator': '/operator', 'navsim': '/navsim', 'gateway': '/gateway'})
    return nodes, Path(journal), Path(audit), stack_case


def control(case, journal, label='control_allow'):
    before = count_lines(journal)
    rogue = sc.run_rogue(case.dir, ACTION_EXECUTE, 'security_gateway', '/gateway',
                         int(SECURE_DOMAIN), True, 'neg-control', 1.5, 1.5,
                         label=label)
    goals = count_lines(journal) - before
    ok = (rogue['result'] or {}).get('outcome') == 'RESULT' and \
        (rogue['result'] or {}).get('success') is True and goals == 1
    case.check('正向对照：同一栈、同一窗口内 /gateway 身份直连成功（1 Goal）',
               ok, 'outcome={0} goals={1}'.format(
                   (rogue['result'] or {}).get('outcome'), goals))
    return ok


def n1_trust_root(case, journal, tmp):
    other = make_keystore(tmp / 'keystore_other_ca', ['/gateway'])
    before = count_lines(journal)
    rogue = sc.run_rogue(case.dir, ACTION_EXECUTE, 'security_gateway', '/gateway',
                         int(SECURE_DOMAIN), True, 'neg-wrong-ca', 1.5, 1.5,
                         keystore_override=str(other), label='wrong_ca_gateway')
    goals = count_lines(journal) - before
    outcome = (rogue['result'] or {}).get('outcome')
    case.check('不同 CA 的 /gateway 参与者无法加入 domain-43 安全域（未执行）',
               outcome != 'RESULT' and goals == 0,
               'outcome={0} goals={1} exit={2}'.format(outcome, goals, rogue['exit_code']))
    case.check('拒绝来自认证/信任根，而非服务缺失：同一栈的正向对照成功',
               control(case, journal, 'control_after_wrong_ca'), 'see control')
    case.notes.append('wrong-CA keystore generated in temp; certificates not archived')
    return case


def n2_tampered_p7s(case, journal, tmp):
    tampered = tmp / 'keystore_tampered_p7s'
    shutil.copytree(KEYSTORE, tampered, symlinks=True)
    p7s = tampered / 'enclaves' / 'planner' / 'permissions.p7s'
    data = bytearray(p7s.read_bytes())
    data[len(data) // 2] ^= 0xFF
    p7s.write_bytes(bytes(data))
    before = count_lines(journal)
    planner = run_planner(case.dir, tampered, 'neg-tampered-p7s', 1.5, 1.5,
                          expect_success=1, label='planner_tampered_p7s')
    goals = count_lines(journal) - before
    result = planner['result'] or {}
    case.check('permissions.p7s 被篡改后 /planner 不能完成执行',
               result.get('status_code') != 'EXECUTED' and goals == 0,
               'status={0} goals={1} exit={2}'.format(
                   result.get('status_code'), goals, planner['exit_code']))
    case.check('失败暴露安全/权限错误而不是静默成功',
               planner['security_evidence'], planner['output_tail'])
    # Positive control with the untouched keystore on the same stack.
    before = count_lines(journal)
    legit = run_planner(case.dir, KEYSTORE, 'neg-control-planner', 1.5, 1.5,
                        expect_success=1, label='planner_control')
    goals = count_lines(journal) - before
    good = legit['result'] or {}
    case.check('正向对照：未篡改的 /planner 在同一栈上成功（1 Goal）',
               good.get('status_code') == 'EXECUTED' and good.get('success') is True
               and goals == 1,
               'status={0} goals={1}'.format(good.get('status_code'), goals))
    return case


def n3_enforce_off(case):
    sc.EVIDENCE_ROOT = str(EVIDENCE_ROOT)
    sc.RUN_ID = RUN_ID
    stack_case = sc.Case('_open_stack', 'unsecured control stack', 'ready', secure=False)
    nodes, journal, audit, _log = sc.start_stack(
        stack_case, int(OPEN_DOMAIN), False,
        {'operator': None, 'navsim': None, 'gateway': None})
    try:
        if not stack_case.passed:
            case.check('非 Enforce 对照栈就绪', False,
                       [c for c in stack_case.checks if c['result'] == 'FAIL'])
            return case
        journal_path = Path(journal)
        before = count_lines(journal_path)
        rogue = sc.run_rogue(case.dir, ACTION_EXECUTE, 'rogue_client', '/unauthorized',
                             int(OPEN_DOMAIN), False, 'neg-enforce-off', 1.5, 1.5,
                             label='enforce_off_unauthorized')
        goals = count_lines(journal_path) - before
        outcome = (rogue['result'] or {}).get('outcome')
        case.check('Enforce 关闭时，同一未授权客户端确实能执行（1 Goal）',
                   outcome == 'RESULT' and (rogue['result'] or {}).get('success') is True
                   and goals == 1,
                   'outcome={0} goals={1}'.format(outcome, goals))
        case.notes.append('N3 is a control condition, not a security pass: it proves the '
                          'domain-43 denial is caused by DDS security rather than an '
                          'absent server.')
    finally:
        sc.stop_all(nodes)
    return case


def n4_cert_enclave_mismatch(case, journal, tmp):
    mismatch = tmp / 'keystore_cert_mismatch'
    shutil.copytree(KEYSTORE, mismatch, symlinks=True)
    gateway_dir = mismatch / 'enclaves' / 'gateway'
    unauthorized = mismatch / 'enclaves' / 'unauthorized'
    for name in ('cert.pem', 'key.pem'):
        shutil.copyfile(unauthorized / name, gateway_dir / name)
    before = count_lines(journal)
    rogue = sc.run_rogue(case.dir, ACTION_EXECUTE, 'security_gateway', '/gateway',
                         int(SECURE_DOMAIN), True, 'neg-cert-mismatch', 1.5, 1.5,
                         keystore_override=str(mismatch), label='cert_mismatch_gateway')
    goals = count_lines(journal) - before
    outcome = (rogue['result'] or {}).get('outcome')
    case.check('把 /unauthorized 证书放进 /gateway 目录不能继承 gateway 权限',
               outcome != 'RESULT' and goals == 0,
               'outcome={0} goals={1}'.format(outcome, goals))
    case.check('拒绝后同一栈正向对照仍成功（排除服务不可用）',
               control(case, journal, 'control_after_cert_mismatch'), 'see control')
    return case


def n5_tampered_xml(case, journal, tmp):
    """Editing permissions.xml after signing must not grant the added privilege.

    Measured behaviour (2026-10-21): Fast DDS loads the CMS-signed
    ``permissions.p7s``; editing ``permissions.xml`` alone neither grants the new
    topic nor breaks the existing grant. The security assertion is therefore
    "the added privilege is not effective", not "the participant fails to start".
    A failure to start would also be safe, but only this direction proves the
    tamper did not escalate.
    """
    tampered = tmp / 'keystore_tampered_xml'
    shutil.copytree(KEYSTORE, tampered, symlinks=True)
    permission = tampered / 'enclaves' / 'planner' / 'permissions.xml'
    text = permission.read_text(encoding='utf-8')
    needle = '<topic>rq/rg/guarded_navigate/_action/send_goalRequest</topic>'
    assert needle in text
    text = text.replace(needle, needle +
                        '<topic>rq/rg/nav_execute/_action/send_goalRequest</topic>'
                        '<topic>rr/rg/nav_execute/_action/send_goalReply</topic>')
    permission.write_text(text, encoding='utf-8')

    # 1) The extra privilege must NOT become effective.
    before = count_lines(journal)
    rogue = sc.run_rogue(case.dir, ACTION_EXECUTE, 'planner_node', '/planner',
                         int(SECURE_DOMAIN), True, 'neg-tampered-xml-direct', 1.5, 1.5,
                         keystore_override=str(tampered),
                         label='rogue_planner_tampered_xml')
    goals = count_lines(journal) - before
    outcome = (rogue['result'] or {}).get('outcome')
    case.check('签名后往 permissions.xml 添加 /rg/nav_execute 权限不生效',
               outcome != 'RESULT' and goals == 0,
               'outcome={0} goals={1}'.format(outcome, goals))
    case.check('拒绝来自 DDS 访问控制层的原生证据',
               'not found in allow rule' in rogue['output'] or
               'SECURITY Error' in rogue['output'],
               [line.strip()[-160:] for line in rogue['output'].splitlines()
                if 'not found in allow rule' in line or 'SECURITY Error' in line][:2])

    # 2) The signed baseline grant still works (the participant is not simply dead).
    before = count_lines(journal)
    planner = run_planner(case.dir, tampered, 'neg-tampered-xml-guarded', 1.5, 1.5,
                          expect_success=1, label='planner_tampered_xml')
    goals = count_lines(journal) - before
    result = planner['result'] or {}
    case.check('同一被篡改 XML 的参与者仍按已签名的基线权限工作（正向对照）',
               result.get('status_code') == 'EXECUTED' and goals == 1,
               'status={0} goals={1}'.format(result.get('status_code'), goals))
    case.notes.append('Measured: Fast DDS consumes the CMS-signed permissions.p7s; an '
                      'unsigned edit of permissions.xml is inert. Re-signing would require '
                      'the permissions CA private key, which is not available to a '
                      'participant.')
    return case


def main(argv=None):
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    if not (KEYSTORE / 'public' / 'ca.cert.pem').is_file():
        print('ERROR: no lab CA at {0}; run scripts/setup_sros2.sh first'.format(KEYSTORE),
              file=sys.stderr)
        return 3
    tmp = Path(tempfile.mkdtemp(prefix='rg-dds-neg-'))
    try:
        nodes, journal, audit, stack_case = start_secure_stack()
        results = []
        try:
            if not stack_case.passed:
                print('ERROR: secured stack not ready: {0}'.format(stack_case.checks),
                      file=sys.stderr)
                return 3
            results.append(n1_trust_root(Case('N1_trust_root_mismatch',
                                              'different CA cannot join'), journal, tmp))
            results.append(n2_tampered_p7s(Case('N2_tampered_permissions_p7s',
                                                'tampered signature rejected'), journal, tmp))
            results.append(n5_tampered_xml(Case('N5_tampered_permissions_xml',
                                                'post-signing edit rejected'), journal, tmp))
            results.append(n4_cert_enclave_mismatch(Case('N4_cert_enclave_mismatch',
                                                         'cert/dir mismatch rejected'),
                                                    journal, tmp))
            control_case = Case('N0_positive_control', 'gateway direct access')
            control(control_case, journal)
            results.append(control_case)
        finally:
            leftovers = sc.stop_all(nodes)
            if leftovers:
                print('WARN: leftover nodes: {0}'.format(leftovers), file=sys.stderr)
        results.append(n3_enforce_off(Case('N3_enforce_disabled_control',
                                           'unsecured control condition')))
        passed = sum(1 for c in results if c.passed)
        summary = {'contract': 'dds-lab-negative/1', 'run_id': RUN_ID,
                   'secure_domain': int(SECURE_DOMAIN), 'open_domain': int(OPEN_DOMAIN),
                   'total': len(results), 'passed': passed,
                   'failed': len(results) - passed,
                   'results': [c.summary() for c in results],
                   'scope': 'TEST_ONLY_LAB',
                   'note': ('negative cases are paired with same-stack positive controls; '
                            'N3 is a control condition showing what happens without Enforce, '
                            'not a security pass')}
        out = EVIDENCE_ROOT / RUN_ID / 'summary.json'
        out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n',
                       encoding='utf-8')
        print('\nDDS NEGATIVE SUMMARY ({0}/{1})'.format(passed, len(results)))
        for c in results:
            print('  [{0}] {1}'.format('PASS' if c.passed else 'FAIL', c.case_id))
            for check in c.checks:
                if check['result'] == 'FAIL':
                    print('        FAIL: {0} -- {1}'.format(check['check'],
                                                           check['detail'][:200]))
        print('evidence: {0}'.format(out.relative_to(ROOT)))
        return 0 if passed == len(results) else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())
