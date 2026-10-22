#!/usr/bin/env python3
"""Repeated lab measurements for the 1.1.0 identity path (30 independent trials).

Scope: component-level correctness and latency for
  * Ed25519 attestation issue -> verify (fresh nonce each trial);
  * Gateway independent verification (fresh attestation + Gateway nonce cache);
  * negative controls (tampered signature, replayed nonce, wrong target).

This is not a full end-to-end DDS run; the end-to-end runs are separate and are
referenced in the report. Running 30 full stacks would add DDS variance to a
measurement that is about the verifier and the gate, so the scope is stated
explicitly rather than implied.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src' / 'rg_gateway'))

from identity_trust import current_identity as ci  # noqa: E402
from identity_trust import lab_issuer as li  # noqa: E402
from rg_gateway import identity_gate as gate  # noqa: E402


def envelope(request_id, x=1.5, y=1.5):
    return {'schema_version': '1.0.0-proposed', 'run_id': 'run-repeat',
            'request_id': request_id,
            'candidate_action': {'action_resource': '/rg/guarded_navigate',
                                 'operation': 'NAVIGATE', 'task_id': 'patrol_a_001',
                                 'target': {'frame_id': 'map', 'x': x, 'y': y, 'z': 0.0}}}


def goal(request_id, x=1.5, y=1.5):
    return SimpleNamespace(request_id=request_id, task_id='patrol_a_001',
                           target=SimpleNamespace(
                               header=SimpleNamespace(frame_id='map'),
                               pose=SimpleNamespace(position=SimpleNamespace(
                                   x=x, y=y, z=0.0))))


def ledger_row(env):
    return {'contract': 'trusted-action-events/1', 'event_kind': 'SEND_GOAL_RECEIVED',
            'resource': 'rt/m2/candidate_task',
            'goal_uuid': li.goal_uuid_for_request(env['request_id']),
            'request_digest': '0' * 64, 'task_code': 1001,
            'payload': li.payload_for_request(env['request_id'], env),
            'writer_guid': 'aa.bb.cc.dd.ee.ff.00.11.22.33.44.55|00000103',
            'participant_guid': 'aa.bb.cc.dd.ee.ff.00.11.22.33.44.55',
            'sample_sequence': 1, 'sender_authenticated': True,
            'certificate_subject': '/CN=\\/planner', 'ca_subject': '/CN=sros2CA',
            'received_at': li.utc_now(), 'source': 'TRUSTED_ACTION_INGRESS',
            'observer': 'M2_TRUSTED_INGRESS'}


def pct(values, p):
    values = sorted(values)
    if not values:
        return None
    index = min(len(values) - 1, max(0, int(round((p / 100.0) * (len(values) - 1)))))
    return values[index]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trials', type=int, default=30)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--out-dir', default=str(ROOT / 'artifacts' / 'research' / 'v110' / 'repeats'))
    args = parser.parse_args(argv)
    out = Path(args.out_dir) / args.run_id
    if out.exists():
        import shutil
        shutil.rmtree(out)
    out.mkdir(parents=True)
    keydir = out / 'keys'
    li.gen_key(keydir, 'lab-ed25519-ingress-1')
    verify_latency, issue_latency, gateway_latency = [], [], []
    positives = negatives = 0
    failures = []
    for index in range(args.trials):
        request_id = 'req-rep-{0:03d}'.format(index)
        env = envelope(request_id)
        ledger = out / ('ledger-%03d.jsonl' % index)
        ledger.write_text(json.dumps(ledger_row(env)) + '\n', encoding='utf-8')
        env_path = out / ('env-%03d.json' % index)
        env_path.write_text(json.dumps(env), encoding='utf-8')
        attest = out / ('att-%03d.json' % index)
        t0 = time.perf_counter_ns()
        li.issue(keydir, env_path, ledger, attest,
                 require_subject='/CN=\\/planner')
        issue_latency.append((time.perf_counter_ns() - t0) / 1e6)
        nonce = out / ('nonce-%03d.jsonl' % index)
        t0 = time.perf_counter_ns()
        result = ci.verify(env, str(attest), str(keydir / li.PUB_NAME),
                           issuers_path=str(keydir / li.TRUST_NAME),
                           ledger=ci.Ledger(str(nonce)))
        verify_latency.append((time.perf_counter_ns() - t0) / 1e6)
        if result['status'] == ci.STATUS_AUTHENTICATED_LAB and \
                ci.f0_accepts(result, allow_lab=True):
            positives += 1
        else:
            failures.append({'trial': index, 'kind': 'verify',
                             'status': result['status'], 'checks': result['checks']})
        # Gateway with its own nonce cache and a fresh attestation.
        att_dir = out / 'gateway_attestations'
        att_dir.mkdir(exist_ok=True)
        att_copy = att_dir / (request_id + '.json')
        import shutil as _sh
        _sh.copyfile(attest, att_copy)
        t0 = time.perf_counter_ns()
        gateway = gate.verify_goal(goal(request_id),
                                   attestation_dir=str(att_dir),
                                   public_key=str(keydir / li.PUB_NAME),
                                   issuers_path=str(keydir / li.TRUST_NAME),
                                   ledger_path=str(out / ('gw-nonce-%03d.jsonl' % index)),
                                   allow_lab_scope=True)
        gateway_latency.append((time.perf_counter_ns() - t0) / 1e6)
        if gateway['decision'] != gate.ALLOW:
            failures.append({'trial': index, 'kind': 'gateway', 'result': gateway})

    # Negative controls (each is a fresh attestation/ledger).
    for kind in ('tampered_signature', 'replay', 'wrong_target'):
        env = envelope('req-neg-' + kind)
        ledger = out / ('neg-%s.jsonl' % kind)
        ledger.write_text(json.dumps(ledger_row(env)) + '\n', encoding='utf-8')
        env_path = out / ('neg-%s-env.json' % kind)
        env_path.write_text(json.dumps(env), encoding='utf-8')
        attest = out / ('neg-%s-att.json' % kind)
        li.issue(keydir, env_path, ledger, attest)
        if kind == 'tampered_signature':
            doc = json.loads(attest.read_text(encoding='utf-8'))
            doc['signature']['value'] = '00' * 64
            attest.write_text(json.dumps(doc), encoding='utf-8')
            r = ci.verify(env, str(attest), str(keydir / li.PUB_NAME),
                          issuers_path=str(keydir / li.TRUST_NAME),
                          ledger=ci.Ledger(str(out / 'neg1.jsonl')))
            ok = r['status'] == ci.STATUS_UNKNOWN and r['checks']['signature'] == 'INVALID'
        elif kind == 'replay':
            nonce = out / 'neg2.jsonl'
            ci.verify(env, str(attest), str(keydir / li.PUB_NAME),
                      issuers_path=str(keydir / li.TRUST_NAME),
                      ledger=ci.Ledger(str(nonce)))
            r = ci.verify(env, str(attest), str(keydir / li.PUB_NAME),
                          issuers_path=str(keydir / li.TRUST_NAME),
                          ledger=ci.Ledger(str(nonce)))
            ok = r['status'] == ci.STATUS_UNKNOWN and r['checks']['replay'] == 'REPLAYED'
        else:
            wrong = envelope(env['request_id'], x=9.9, y=9.9)
            r = ci.verify(wrong, str(attest), str(keydir / li.PUB_NAME),
                          issuers_path=str(keydir / li.TRUST_NAME),
                          ledger=ci.Ledger(str(out / 'neg3.jsonl')))
            ok = r['status'] == ci.STATUS_UNKNOWN and r['checks']['request_binding'] == 'MISMATCH'
        negatives += 1 if ok else 0
        if not ok:
            failures.append({'kind': 'negative-' + kind, 'result': r})

    li.purge(keydir)
    summary = {
        'contract': 'v110-repeats/1', 'scope': 'LAB_COMPONENT',
        'run_id': args.run_id, 'trials': args.trials,
        'positive_ok': positives, 'negative_controls_ok': negatives,
        'failures': failures,
        'latency_ms': {
            'issue': {'p50': pct(issue_latency, 50), 'p95': pct(issue_latency, 95),
                      'p99': pct(issue_latency, 99),
                      'mean': statistics.fmean(issue_latency) if issue_latency else None},
            'verify': {'p50': pct(verify_latency, 50), 'p95': pct(verify_latency, 95),
                       'p99': pct(verify_latency, 99),
                       'mean': statistics.fmean(verify_latency) if verify_latency else None},
            'gateway_gate': {'p50': pct(gateway_latency, 50),
                             'p95': pct(gateway_latency, 95),
                             'p99': pct(gateway_latency, 99),
                             'mean': statistics.fmean(gateway_latency) if gateway_latency else None},
        },
        'note': ('component-level repeated trials; not a 30x full DDS end-to-end run. '
                 'Each trial used a fresh nonce and a fresh ledger.'),
        'm1_three_real_positive': 'BLOCKED: M1 validation gate remains false; see M1 reports',
    }
    (out / 'summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: summary[k] for k in
                      ('trials', 'positive_ok', 'negative_controls_ok', 'failures')}))
    return 0 if not failures and positives == args.trials and negatives == 3 else 1


if __name__ == '__main__':
    sys.exit(main())
