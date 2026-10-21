#!/usr/bin/env python3
"""Real-wire lab chain: DDS ingress observation -> Ed25519 attestation -> F0.

This runs inside the ROS 2 Jazzy container. It does not simulate the DDS part:

1. starts the trusted ingress (`src/m2_witness/m2_ingress_witness.cpp`) in the
   research domain with the lab CA;
2. sends candidate intents from `/planner` and `/operator` participants over a
   secured DDS topic;
3. checks the ledger attributes each sample to the *writer's authenticated
   certificate subject* (never to a self-declared field);
4. has the lab issuer check that observation and sign a v3 Ed25519 attestation
   bound to the exact request digest;
5. verifies it with the production verifier and with the F0 adapter;
6. runs the negative cases (wrong subject, tampered payload, stale observation,
   replayed nonce, tampered signature).

Scope is recorded as TEST_ONLY_LAB. The attested resource is the pre-admission
intent topic, not the ROS Action send_goal service; that distinction is written
into the summary and must not be erased in reports.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from identity_trust import current_identity as ci  # noqa: E402
from identity_trust import lab_issuer as li  # noqa: E402

DEFAULT_KS = ROOT / 'artifacts' / 'research' / 'v110' / 'm2-ingress' / 'keystore'
BINARY = Path('/tmp/m2_ingress')
DOMAIN = 45
RESOURCE = 'rt/m2/candidate_task'
EVIDENCE = ROOT / 'tests' / 'evidence'


def sh(argv, **kwargs):
    kwargs.setdefault('cwd', str(ROOT))
    kwargs.setdefault('capture_output', True)
    kwargs.setdefault('text', True)
    return subprocess.run(argv, **kwargs)


def build_binary():
    if BINARY.is_file():
        return {'binary': str(BINARY), 'reused': True}
    argv = ['g++', '-std=c++17', '-O2',
            str(ROOT / 'src' / 'm2_witness' / 'm2_ingress_witness.cpp'),
            '-o', str(BINARY),
            '-I/opt/ros/jazzy/include/fastrtps',
            '-I/opt/ros/jazzy/include/fastcdr',
            '-L/opt/ros/jazzy/lib', '-lfastrtps', '-lfastcdr', '-lpthread']
    proc = sh(argv, timeout=300)
    if proc.returncode != 0:
        raise RuntimeError('compile failed: ' + (proc.stderr or proc.stdout)[-800:])
    return {'binary': str(BINARY), 'reused': False,
            'command': ' '.join(argv)}


def envelope(request_id, x=1.5, y=1.5):
    return {
        'schema_version': '1.0.0-proposed', 'run_id': 'run-m2-lab',
        'request_id': request_id, 'created_at': li.utc_now(),
        'candidate_action': {'action_resource': '/rg/guarded_navigate',
                             'operation': 'NAVIGATE', 'task_id': 'patrol_a_001',
                             'target': {'frame_id': 'map', 'x': x, 'y': y,
                                        'z': 0.0}},
        'observations': [{'source': 'security', 'kind': 'UNKNOWN',
                          'observed_at': li.utc_now()}],
        'evidence_refs': [{'ref': 'tests/integration/m2_lab_identity_chain.py',
                           'kind': 'CONTROLLED_SECURITY_EXPERIMENT'}],
    }


def count_events(ledger, event_kind=None):
    if not ledger.is_file():
        return 0
    rows = [json.loads(line) for line in ledger.read_text(encoding='utf-8').splitlines()
            if line.strip()]
    if event_kind:
        rows = [r for r in rows if r.get('event_kind') == event_kind]
    return len(rows)


def run_ingress_experiment(evidence, keystore, run_id):
    ledger = evidence / 'intent_events.jsonl'
    ledger.unlink(missing_ok=True)
    ingress_log = evidence / 'ingress.log'
    ingress = subprocess.Popen(
        [str(BINARY), '--role', 'ingress', '--keystore', str(keystore),
         '--enclave', '/witness', '--domain', str(DOMAIN),
         '--resource', RESOURCE, '--ledger', str(ledger), '--seconds', '30'],
        cwd=str(ROOT), stdout=open(ingress_log, 'wb'), stderr=subprocess.STDOUT)
    time.sleep(4)
    env_planner = envelope('req-lab-p01')
    env_operator = envelope('req-lab-p02', x=2.5, y=2.5)
    clients = []
    for name, env_doc, enclave in (('planner', env_planner, '/planner'),
                                   ('operator', env_operator, '/operator')):
        payload = li.payload_for_request(env_doc['request_id'], env_doc)
        goal = li.goal_uuid_for_request(env_doc['request_id'])
        log = evidence / ('client_{0}.log'.format(name))
        with open(log, 'wb') as handle:
            proc = subprocess.run(
                [str(BINARY), '--role', 'client', '--keystore', str(keystore),
                 '--enclave', enclave, '--domain', str(DOMAIN),
                 '--resource', RESOURCE, '--payload', payload,
                 '--goal-uuid', goal, '--send', '1'],
                cwd=str(ROOT), stdout=handle, stderr=subprocess.STDOUT, timeout=120)
        clients.append({'identity': enclave, 'request_id': env_doc['request_id'],
                        'exit_code': proc.returncode, 'log': log.name,
                        'payload': payload, 'goal_uuid': goal})
        time.sleep(1)
    # An identity that may not publish on the ingress topic must not be observed.
    rogue_log = evidence / 'client_rogue.log'
    with open(rogue_log, 'wb') as handle:
        rogue = subprocess.run(
            [str(BINARY), '--role', 'client', '--keystore', str(keystore),
             '--enclave', '/rogue', '--domain', str(DOMAIN),
             '--resource', RESOURCE, '--payload', 'req-lab-rogue|' + 'f' * 64,
             '--goal-uuid', li.goal_uuid_for_request('req-lab-rogue'),
             '--send', '1'],
            cwd=str(ROOT), stdout=handle, stderr=subprocess.STDOUT, timeout=120)
    try:
        ingress.wait(timeout=45)
    except subprocess.TimeoutExpired:
        ingress.terminate()
        ingress.wait(timeout=10)
    return {'ledger': ledger, 'ingress_log': ingress_log, 'clients': clients,
            'rogue_exit': rogue.returncode,
            'envelopes': {'planner': env_planner, 'operator': env_operator}}


def attribution_checks(ledger, clients):
    rows = [json.loads(line) for line in ledger.read_text(encoding='utf-8').splitlines()
            if line.strip()]
    events = [r for r in rows if r.get('event_kind') == 'SEND_GOAL_RECEIVED']
    checks = []
    for client in clients:
        matching = [e for e in events if e.get('goal_uuid') == client['goal_uuid']]
        subject_ok = (len(matching) == 1
                      and matching[0].get('certificate_subject') ==
                      '/CN=\\/' + client['identity'].strip('/')
                      and matching[0].get('sender_authenticated') is True)
        checks.append({
            'check': 'DDS sample of {0} attributed to {1}'.format(
                client['request_id'], client['identity']),
            'result': 'PASS' if subject_ok else 'FAIL',
            'detail': json.dumps([{k: e.get(k) for k in
                                   ('certificate_subject', 'sender_authenticated',
                                    'writer_guid', 'participant_guid')}
                                  for e in matching], ensure_ascii=False)})
    # No sample may be attributed to the other identity.
    subjects = {e.get('certificate_subject') for e in events}
    cross_ok = not any('operator' in (e.get('payload') or '')
                       and e.get('certificate_subject') != '/CN=\\/operator'
                       for e in events)
    checks.append({'check': 'no cross-identity attribution in the ledger',
                   'result': 'PASS' if cross_ok else 'FAIL',
                   'detail': str(sorted(subjects))})
    checks.append({'check': 'unauthorized /rogue participant produced no sample',
                   'result': 'PASS' if not any(
                       r.get('event_kind') == 'SEND_GOAL_RECEIVED'
                       and 'rogue' in (r.get('payload') or '') for r in rows) else 'FAIL',
                   'detail': 'DDS access control blocks the writer; the witness cannot '
                             'observe a blocked sender (recorded as a blind spot)'})
    return checks, events


def adapter_config(evidence, keydir, attest_path, nonce_ledger):
    import yaml
    config = {
        'adapter': {'log_path': str(evidence / 'adapter.jsonl')},
        'modules': {
            'comm_risk': {'mode': 'mock', 'interface': 'comm_risk_evidence',
                          'command': ['python3', 'mock_modules/comm_risk_mock.py'],
                          'timeout_sec': 10, 'max_stdout_bytes': 65536,
                          'allow_fault_injection': False},
            'identity_trust': {'mode': 'mock', 'interface': 'identity_trust_assessment',
                               'command': ['python3', 'mock_modules/identity_trust_mock.py'],
                               'timeout_sec': 10, 'max_stdout_bytes': 65536,
                               'allow_fault_injection': False},
            'task_risk': {'mode': 'mock', 'interface': 'task_risk_decision',
                          'command': ['python3', 'mock_modules/task_risk_mock.py'],
                          'timeout_sec': 10, 'max_stdout_bytes': 65536,
                          'allow_fault_injection': False},
        },
        'identity_attestation': {
            'mode': 'STRICT',
            'witness_path': str(attest_path),
            'key_path': str(keydir / li.PUB_NAME),
            'issuers_path': str(keydir / li.TRUST_NAME),
            'ledger_path': str(nonce_ledger),
            'allow_lab_scope': True,
        },
    }
    path = evidence / 'team_modules.lab.yaml'
    path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding='utf-8')
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--keystore', default=str(DEFAULT_KS))
    args = parser.parse_args(argv)
    keystore = Path(args.keystore)
    if not (keystore / 'public' / 'ca.cert.pem').is_file():
        print('ERROR: research keystore missing; run scripts/setup_m2_ingress_lab.sh',
              file=sys.stderr)
        return 3
    evidence = EVIDENCE / args.run_id
    if evidence.exists():
        shutil.rmtree(evidence)
    evidence.mkdir(parents=True)
    checks = []
    summary = {'contract': 'm2-lab-identity/1', 'run_id': args.run_id,
               'scope': 'TEST_ONLY_LAB', 'secure_domain': DOMAIN,
               'started_at': li.utc_now(), 'checks': checks,
               'note': ('attested resource is the pre-admission intent topic '
                        '(rt/m2/candidate_task); this is not the ROS Action '
                        'send_goal service request')}

    def check(name, ok, detail):
        checks.append({'check': name, 'result': 'PASS' if ok else 'FAIL',
                       'detail': str(detail)[:800]})

    try:
        summary['build'] = build_binary()
        experiment = run_ingress_experiment(evidence, keystore, args.run_id)
        summary['ledger_sha256'] = hashlib.sha256(
            experiment['ledger'].read_bytes()).hexdigest()
        summary['ingress_open_events'] = count_events(experiment['ledger'], 'INGRESS_OPENED')
        summary['send_goal_events'] = count_events(experiment['ledger'], 'SEND_GOAL_RECEIVED')
        attr_checks, events = attribution_checks(experiment['ledger'],
                                                 experiment['clients'])
        for item in attr_checks:
            check(item['check'], item['result'] == 'PASS', item['detail'])
        check('each client process exited 0', all(c['exit_code'] == 0
                                                  for c in experiment['clients']),
              [c['exit_code'] for c in experiment['clients']])
        check('unauthorized writer cannot create a secured writer',
              experiment['rogue_exit'] != 0, experiment['rogue_exit'])

        keydir = evidence / 'issuer_public'
        li.gen_key(keydir, 'lab-ed25519-ingress-1')
        planner = experiment['clients'][0]
        env_planner = experiment['envelopes']['planner']
        envelope_path = evidence / 'envelope_planner.json'
        envelope_path.write_text(json.dumps(env_planner, indent=2), encoding='utf-8')
        attest = evidence / 'attestation_planner.json'
        issued = li.issue(keydir, envelope_path, experiment['ledger'], attest,
                          require_subject='/CN=\\/planner')
        check('issuer required the DDS-observed /planner subject',
              issued['subject'] == '/CN=\\/planner', issued['subject'])
        nonce_ledger = evidence / 'nonce_ledger.jsonl'
        verified = li.verify(keydir, envelope_path, attest,
                             nonce_ledger=nonce_ledger)
        check('verifier returns AUTHENTICATED_LAB with all checks valid',
              verified['status'] == ci.STATUS_AUTHENTICATED_LAB
              and verified['checks'] == {'signature': 'VALID',
                                         'issuer': ci.ISSUER_CHECK_LAB,
                                         'request_binding': 'MATCH',
                                         'freshness': 'OK',
                                         'replay': 'RESERVED'},
              json.dumps(verified, ensure_ascii=False)[:600])
        check('default F0 acceptance rejects lab status, opt-in accepts it',
              verified['f0_accepts_default'] is False
              and verified['f0_accepts_lab'] is True, json.dumps(verified, ensure_ascii=False))
        replay = li.verify(keydir, envelope_path, attest, nonce_ledger=nonce_ledger)
        check('replaying the same nonce fails closed',
              replay['status'] == ci.STATUS_UNKNOWN
              and replay['checks']['replay'] == 'REPLAYED', replay['checks'])

        # Negative issuance cases.
        try:
            li.issue(keydir, envelope_path, experiment['ledger'],
                     evidence / 'should_not_exist.json',
                     require_subject='/CN=\\/operator')
            wrong_subject_ok = False
        except li.LabError:
            wrong_subject_ok = True
        check('issuer refuses a subject that does not match the observation',
              wrong_subject_ok, 'wrong subject rejected')
        tampered_ledger = evidence / 'tampered_ledger.jsonl'
        tampered = []
        for line in experiment['ledger'].read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get('event_kind') == 'SEND_GOAL_RECEIVED':
                row['payload'] = row.get('payload', '') + 'x'
            tampered.append(json.dumps(row))
        tampered_ledger.write_text('\n'.join(tampered) + '\n', encoding='utf-8')
        try:
            li.issue(keydir, envelope_path, tampered_ledger,
                     evidence / 'should_not_exist2.json')
            tamper_ok = False
        except li.LabError:
            tamper_ok = True
        check('issuer refuses a ledger whose payload digest was altered',
              tamper_ok, 'tampered payload rejected')
        stale = []
        for line in experiment['ledger'].read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get('event_kind') == 'SEND_GOAL_RECEIVED':
                row['received_at'] = li.utc_now(time.time() - 600)
            stale.append(json.dumps(row))
        stale_ledger = evidence / 'stale_ledger.jsonl'
        stale_ledger.write_text('\n'.join(stale) + '\n', encoding='utf-8')
        try:
            li.issue(keydir, envelope_path, stale_ledger,
                     evidence / 'should_not_exist3.json')
            stale_ok = False
        except li.LabError:
            stale_ok = True
        check('issuer refuses a stale observation', stale_ok, 'stale rejected')
        document = json.loads(attest.read_text(encoding='utf-8'))
        document['signature']['value'] = '00' * 64
        tampered_attest = evidence / 'tampered_attestation.json'
        tampered_attest.write_text(json.dumps(document), encoding='utf-8')
        bad = ci.verify(env_planner, str(tampered_attest),
                        str(keydir / li.PUB_NAME),
                        issuers_path=str(keydir / li.TRUST_NAME),
                        ledger=ci.Ledger(str(evidence / 'tamper_nonce.jsonl')))
        check('tampered signature is rejected', bad['status'] == ci.STATUS_UNKNOWN
              and bad['checks']['signature'] == 'INVALID', bad['checks'])

        # F0 adapter with the real-wire attestation (mock business modules).
        adapter_nonce = evidence / 'adapter_nonce.jsonl'
        config = adapter_config(evidence, keydir, attest, adapter_nonce)
        proc = sh([sys.executable, str(ROOT / 'scripts' / 'team_demo.py'),
                   '--input', str(envelope_path), '--config', str(config),
                   '--log', str(evidence / 'adapter.jsonl'),
                   '--workdir', str(ROOT)], timeout=120)
        try:
            adapter = json.loads(proc.stdout)
        except ValueError:
            adapter = {'decision': 'UNPARSEABLE',
                       'raw': (proc.stdout or proc.stderr)[:400]}
        check('F0 adapter reaches READY with the real-wire lab attestation',
              proc.returncode == 0
              and adapter.get('decision') == 'READY_FOR_GATEWAY_SUBMISSION',
              json.dumps({k: adapter.get(k) for k in
                          ('decision', 'reason_code', 'identity_attestation')},
                         ensure_ascii=False)[:700])
        proc2 = sh([sys.executable, str(ROOT / 'scripts' / 'team_demo.py'),
                    '--input', str(envelope_path), '--config', str(config),
                    '--log', str(evidence / 'adapter2.jsonl'),
                    '--workdir', str(ROOT)], timeout=120)
        try:
            adapter2 = json.loads(proc2.stdout)
        except ValueError:
            adapter2 = {'decision': 'UNPARSEABLE'}
        check('F0 adapter blocks the replayed attestation',
              proc2.returncode != 0 and adapter2.get('decision') == 'ADAPTER_BLOCK',
              adapter2.get('reason_code'))

        # Keep only public material; remove the private key before archiving.
        public_key = keydir / li.PUB_NAME
        trust = keydir / li.TRUST_NAME
        # Public key material is archived as .pub (never .pem): the evidence
        # archiver refuses anything that looks like certificate/key material.
        shutil.copyfile(public_key, evidence / 'issuer_public.pub')
        shutil.copyfile(trust, evidence / 'issuers.json')
        shutil.rmtree(keydir, ignore_errors=True)
        check('private issuer key removed before archiving',
              not (keydir / li.KEY_NAME).exists()
              and not any(b'PRIVATE KEY' in p.read_bytes()
                          for p in evidence.rglob('*') if p.is_file()),
              'no private key in evidence')
        summary['attestation'] = {
            'request_id': issued['request_id'], 'subject': issued['subject'],
            'issuer': issued['issuer'], 'scope': issued['scope'],
            'ledger_sha256': issued['ledger_sha256'],
            'public_key_sha256': json.loads(
                (evidence / 'issuers.json').read_text(encoding='utf-8')
            )['issuers'][0]['public_key_sha256'],
        }
        summary['adapter_decision'] = adapter.get('decision')
        summary['note'] = summary['note'] + (
            '; the DDS witness proves writer-GUID -> authenticated certificate subject '
            'and request payload binding; it does not prove the later ROS Action '
            'send_goal was sent by the same participant, which remains a documented gap')
    except Exception as exc:  # noqa: BLE001 - recorded as a failure, not hidden
        check('chain completed without exception', False,
              '{0}: {1}'.format(type(exc).__name__, str(exc)[:400]))
    summary['finished_at'] = li.utc_now()
    summary['total'] = len(checks)
    summary['passed'] = sum(1 for c in checks if c['result'] == 'PASS')
    summary['failed'] = summary['total'] - summary['passed']
    (evidence / 'summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'run_id': args.run_id, 'passed': summary['passed'],
                      'total': summary['total'],
                      'failed': summary['failed']}, ensure_ascii=False))
    for item in checks:
        if item['result'] == 'FAIL':
            print('  FAIL: {0} -- {1}'.format(item['check'], item['detail'][:300]))
    return 0 if summary['failed'] == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
