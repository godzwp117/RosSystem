#!/usr/bin/env python3
"""Gateway independent identity decision: real DDS ingress -> Ed25519 -> Gateway.

Runs in the Jazzy container on the research domain (45) with the research
keystore. The Gateway is started with its identity gate enabled; it re-verifies
the attestation for the exact goal with its own trust anchor and nonce cache
before applying TaskPolicy. Three cases:

  G1  valid attestation + in-policy target -> Gateway ALLOW -> NavigationSim 1 Goal
  G2  no attestation                       -> Gateway BLOCK -> 0 Goal
  G3  attestation for a different target   -> Gateway BLOCK -> 0 Goal

The business policy is unchanged; the identity gate is additive and cannot turn
a policy BLOCK into ALLOW.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))

import sros2_check as sc  # noqa: E402
from identity_trust import current_identity as ci  # noqa: E402
from identity_trust import lab_issuer as li  # noqa: E402

EVIDENCE_ROOT = ROOT / 'tests' / 'evidence'
DOMAIN = '45'
RESOURCE = 'rt/m2/candidate_task'
KEYSTORE = ROOT / 'artifacts' / 'research' / 'v110' / 'm2-ingress' / 'keystore'
BINARY = Path('/tmp/m2_ingress')


def envelope(request_id, x, y):
    return {
        'schema_version': '1.0.0-proposed', 'run_id': 'run-gateway-lab',
        'request_id': request_id, 'created_at': li.utc_now(),
        'candidate_action': {'action_resource': '/rg/guarded_navigate',
                             'operation': 'NAVIGATE', 'task_id': 'patrol_a_001',
                             'target': {'frame_id': 'map', 'x': x, 'y': y, 'z': 0.0}},
        'observations': [{'source': 'security', 'kind': 'UNKNOWN',
                          'observed_at': li.utc_now()}],
        'evidence_refs': [{'ref': 'tests/integration/gateway_identity_lab.py',
                           'kind': 'CONTROLLED_SECURITY_EXPERIMENT'}],
    }


def send_intent(evidence, env, keydir, label):
    ledger = evidence / ('intent_%s.jsonl' % label)
    ledger.unlink(missing_ok=True)
    log = evidence / ('ingress_%s.log' % label)
    ingress = subprocess.Popen(
        [str(BINARY), '--role', 'ingress', '--keystore', str(KEYSTORE),
         '--enclave', '/witness', '--domain', DOMAIN, '--resource', RESOURCE,
         '--ledger', str(ledger), '--seconds', '18'],
        cwd=str(ROOT), stdout=open(log, 'wb'), stderr=subprocess.STDOUT)
    time.sleep(3)
    payload = li.payload_for_request(env['request_id'], env)
    goal = li.goal_uuid_for_request(env['request_id'])
    client = subprocess.run(
        [str(BINARY), '--role', 'client', '--keystore', str(KEYSTORE),
         '--enclave', '/planner', '--domain', DOMAIN, '--resource', RESOURCE,
         '--payload', payload, '--goal-uuid', goal, '--send', '1'],
        cwd=str(ROOT), capture_output=True, text=True, timeout=120)
    try:
        ingress.wait(timeout=30)
    except subprocess.TimeoutExpired:
        ingress.terminate()
        ingress.wait(timeout=10)
    if client.returncode != 0:
        raise RuntimeError('intent client failed: ' + (client.stderr or '')[-400:])
    env_path = evidence / ('envelope_%s.json' % label)
    env_path.write_text(json.dumps(env), encoding='utf-8')
    attest = evidence / ('attestation_%s.json' % label)
    li.issue(keydir, env_path, ledger, attest, require_subject='/CN=\\/planner')
    return attest, ledger


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args(argv)
    evidence = EVIDENCE_ROOT / args.run_id
    if evidence.exists():
        shutil.rmtree(evidence)
    evidence.mkdir(parents=True)
    checks = []
    summary = {'contract': 'gateway-identity-lab/1', 'run_id': args.run_id,
               'scope': 'TEST_ONLY_LAB', 'secure_domain': int(DOMAIN),
               'checks': checks}

    def check(name, ok, detail=''):
        checks.append({'check': name, 'result': 'PASS' if ok else 'FAIL',
                       'detail': str(detail)[:800]})

    keydir = evidence / 'issuer'
    li.gen_key(keydir, 'lab-ed25519-ingress-1')
    attest_dir = evidence / 'attestations'
    attest_dir.mkdir()
    sc.EVIDENCE_ROOT = str(EVIDENCE_ROOT)
    sc.RUN_ID = args.run_id
    sc.KEYSTORE = str(KEYSTORE)

    config = {'policy_path': str(ROOT / 'config' / 'task_policy.yaml'),
              'audit_log_path': str(evidence / 'audit.jsonl'),
              'identity_attestation_dir': str(attest_dir),
              'identity_public_key': str(keydir / li.PUB_NAME),
              'identity_issuers': str(keydir / li.TRUST_NAME),
              'identity_nonce_ledger': str(evidence / 'gateway_nonce.jsonl'),
              'identity_allow_lab_scope': True,
              'identity_audit_path': str(evidence / 'identity_audit.jsonl')}

    stack = sc.Case('_gateway_stack', 'gateway identity stack', 'ready', secure=True)
    nodes = []
    try:
        g1 = envelope('req-gw-lab-001', 1.5, 1.5)
        attest1, _ledger = send_intent(evidence, g1, keydir, 'g1')
        shutil.copyfile(attest1, attest_dir / (g1['request_id'] + '.json'))
        nodes, journal, audit, _log = sc.start_stack(
            stack, int(DOMAIN), True,
            {'navsim': '/navsim', 'gateway': '/gateway'},
            gateway_params=config, with_operator=False)
        if not stack.passed:
            check('secured gateway stack ready', False, stack.checks)
            raise RuntimeError('stack not ready')
        journal = Path(journal)
        # gateway_params overrides audit_log_path, so the typed DecisionEvents are
        # in the configured file, not in start_stack's default path.
        audit = evidence / 'audit.jsonl'

        before = sc.count_lines(journal)
        planner = sc.run_planner(stack, '/planner', int(DOMAIN), True,
                                 g1['request_id'], 1.5, 1.5, 1)
        goals = sc.count_lines(journal) - before
        result = planner['result'] or {}
        decisions = [r for r in sc.read_jsonl(audit)
                     if r.get('event_type') == 'DecisionEvent']
        allowed = [d for d in decisions if d.get('request_id') == g1['request_id']
                   and d.get('decision') == 'ALLOW']
        identity_audit = sc.read_jsonl(evidence / 'identity_audit.jsonl')
        g1_identity = [r for r in identity_audit
                       if r.get('request_id') == g1['request_id']]
        check('G1 planner gets EXECUTED through the gateway',
              result.get('status_code') == 'EXECUTED' and result.get('success') is True,
              result.get('status_code'))
        check('G1 NavigationSim receives exactly 1 Goal', goals == 1, goals)
        check('G1 Gateway TaskPolicy decision is ALLOW', bool(allowed), len(allowed))
        check('G1 Gateway independently verified the identity attestation',
              bool(g1_identity) and g1_identity[-1].get('decision') == 'ALLOW'
              and g1_identity[-1].get('scope') == ci.SCOPE_LAB,
              g1_identity[-1] if g1_identity else 'no identity audit')

        # G2: no attestation for this request.
        g2 = envelope('req-gw-lab-002', 1.5, 1.5)
        before = sc.count_lines(journal)
        planner2 = sc.run_planner(stack, '/planner', int(DOMAIN), True,
                                  g2['request_id'], 1.5, 1.5, 0)
        goals2 = sc.count_lines(journal) - before
        result2 = planner2['result'] or {}
        decisions = [r for r in sc.read_jsonl(audit)
                     if r.get('event_type') == 'DecisionEvent']
        blocked = [d for d in decisions if d.get('request_id') == g2['request_id']
                   and d.get('decision') == 'BLOCK']
        check('G2 missing attestation blocks at the gateway',
              blocked and blocked[-1].get('reason_code') ==
              'IDENTITY_ATTESTATION_REJECTED',
              blocked[-1] if blocked else 'no decision')
        check('G2 no downstream Goal', goals2 == 0, goals2)
        check('G2 planner does not get EXECUTED',
              result2.get('status_code') != 'EXECUTED', result2.get('status_code'))

        # G3: attestation for a different target.
        g3_signed = envelope('req-gw-lab-003', 9.0, 9.0)
        attest3, _ = send_intent(evidence, g3_signed, keydir, 'g3')
        shutil.copyfile(attest3, attest_dir / (g3_signed['request_id'] + '.json'))
        before = sc.count_lines(journal)
        planner3 = sc.run_planner(stack, '/planner', int(DOMAIN), True,
                                  g3_signed['request_id'], 1.5, 1.5, 0)
        goals3 = sc.count_lines(journal) - before
        result3 = planner3['result'] or {}
        decisions = [r for r in sc.read_jsonl(audit)
                     if r.get('event_type') == 'DecisionEvent']
        blocked3 = [d for d in decisions
                    if d.get('request_id') == g3_signed['request_id']
                    and d.get('decision') == 'BLOCK']
        check('G3 attestation bound to a different target is rejected',
              blocked3 and blocked3[-1].get('reason_code') ==
              'IDENTITY_ATTESTATION_REJECTED',
              blocked3[-1] if blocked3 else 'no decision')
        check('G3 no downstream Goal', goals3 == 0, goals3)
        check('G3 planner does not get EXECUTED',
              result3.get('status_code') != 'EXECUTED', result3.get('status_code'))
    except Exception as exc:  # noqa: BLE001
        check('gateway experiment completed without exception', False,
              '{0}: {1}'.format(type(exc).__name__, str(exc)[:400]))
    finally:
        if nodes:
            sc.stop_all(nodes)
    # cleanup private key
    shutil.rmtree(keydir, ignore_errors=True)
    check('private issuer key removed', not (keydir / li.KEY_NAME).exists())
    summary['finished_at'] = li.utc_now()
    summary['total'] = len(checks)
    summary['passed'] = sum(1 for c in checks if c['result'] == 'PASS')
    summary['failed'] = summary['total'] - summary['passed']
    (evidence / 'summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'run_id': args.run_id, 'passed': summary['passed'],
                      'total': summary['total'], 'failed': summary['failed']}))
    for item in checks:
        if item['result'] == 'FAIL':
            print('  FAIL: {0} -- {1}'.format(item['check'], item['detail'][:300]))
    return 0 if summary['failed'] == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
