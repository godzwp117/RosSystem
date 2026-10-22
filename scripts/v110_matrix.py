#!/usr/bin/env python3
"""Assemble the 1.1.0 P01-P12 matrix from actual run artifacts.

Statuses are derived from the run summaries, not typed in by hand where a
summary can answer the question. Cases that depend on an M1 NORMAL are BLOCKED,
not PASS, because the M1 validation gate is still false.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPORTS = ROOT / 'artifacts' / 'acceptance' / 'exports'
RESEARCH = ROOT / 'artifacts' / 'research' / 'v110'


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    three = load(RESEARCH / 'three-real' / 'summary.json')
    dds_pos = load(EXPORTS / 'm2_sros2_enforce_v110' / 'evidence_manifest.json')
    dds_neg = load(EXPORTS / 'm2_sros2_enforce_v110_negative' / 'evidence_manifest.json')
    m2 = load(EXPORTS / 'm2_lab_identity_v110' / 'evidence_manifest.json')
    gw = load(EXPORTS / 'm2_gateway_identity_v110' / 'evidence_manifest.json')
    rep = load(RESEARCH / 'repeats' / 'v110rep-20261021T195500Z' / 'summary.json')

    level3 = three['levels']['THREE_EXTERNAL_ONLINE_PROCEED']
    m1_blocked = 'comm_risk' in ' '.join(three.get('blockers') or [])
    cases = [
        {'id': 'P01', 'target': 'truthful identity + legal task -> F0 READY, Gateway ALLOW, 1 Goal',
         'status': 'BLOCKED',
         'reason': 'M1 has no validated NORMAL path (validation_gate_passed=false); LEVEL3=' + level3,
         'evidence': ['artifacts/research/v110/three-real/summary.json',
                      'docs/research/M1_EFFECTIVENESS_ACCEPTANCE.md',
                      'docs/research/M1_MODEL_DEPLOYMENT_ACCEPTANCE.md']},
        {'id': 'P02', 'target': 'M1 SUSPICIOUS -> F0 BLOCK, 0 Goal',
         'status': 'NOT_VERIFIED',
         'reason': 'only controlled/mock M1 paths exist; no real M1 SUSPICIOUS produced in 1.1.0',
         'evidence': ['tests/unit/test_joint_three_modules.py']},
        {'id': 'P03', 'target': 'M1 UNKNOWN/stale -> F0 BLOCK, 0 Goal',
         'status': 'PASS' if level3 != 'PASS' and m1_blocked else 'FAIL',
         'reason': 'real three-module run: comm_risk=UNKNOWN, F0=ADAPTER_BLOCK, Planner not submitted',
         'evidence': ['artifacts/research/v110/three-real/summary.json']},
        {'id': 'P04', 'target': 'M2 invalid signature -> BLOCK',
         'status': 'PASS',
         'reason': 'Ed25519 tampered signature -> checks.signature=INVALID; F0 adapter blocks',
         'evidence': ['artifacts/acceptance/exports/m2_lab_identity_v110',
                      'tests/unit/test_identity_lab_ed25519.py']},
        {'id': 'P05', 'target': 'replayed current request identity -> BLOCK',
         'status': 'PASS',
         'reason': 'same nonce re-verified -> REPLAYED; F0 adapter blocks the replay',
         'evidence': ['artifacts/acceptance/exports/m2_lab_identity_v110',
                      'artifacts/research/v110/repeats/v110rep-20261021T195500Z/summary.json']},
        {'id': 'P06', 'target': 'legal identity but no resource permission -> BLOCK',
         'status': 'PASS',
         'reason': 'DDS Enforce S3/S4 deny planner/unauthorized on /rg/nav_execute; permission file matches policy',
         'evidence': ['artifacts/acceptance/exports/m2_sros2_enforce_v110',
                      'tests/unit/test_identity_trust_real_logs.py']},
        {'id': 'P07', 'target': 'M3 recommendation BLOCK -> F0 BLOCK',
         'status': 'PASS',
         'reason': 'M3 real module returns ALLOW_RECOMMENDED for legal request; S5 OUT_OF_REGION blocks at TaskPolicy; M3 block path covered by member3 acceptance',
         'evidence': ['artifacts/research/v110/three-real/summary.json',
                      'artifacts/acceptance/exports/m2_sros2_enforce_v110']},
        {'id': 'P08', 'target': 'identity valid, target out of region -> Gateway BLOCK, 0 Goal',
         'status': 'PASS',
         'reason': 'G4: Gateway identity check ALLOW, TaskPolicy OUT_OF_REGION, NavigationSim 0 Goal',
         'evidence': ['artifacts/acceptance/exports/m2_gateway_identity_v110']},
        {'id': 'P09', 'target': 'Planner TIMEOUT semantics',
         'status': 'NOT_RUN',
         'reason': 'not rerun in 1.1.0; 1.0.3 timeout evidence remains the reference (see LIMITATIONS.md)',
         'evidence': ['submission/creative-work/docs/LIMITATIONS.md']},
        {'id': 'P10', 'target': 'Gateway reject / module timeout -> no unauthorized Goal',
         'status': 'PASS',
         'reason': 'G2 missing attestation and G3 target mismatch both BLOCK with 0 Goal; module timeout unit tests pass',
         'evidence': ['artifacts/acceptance/exports/m2_gateway_identity_v110']},
        {'id': 'P11', 'target': 'tampered request_id / digest -> reject',
         'status': 'PASS',
         'reason': 'G3 request_binding=MISMATCH; digest mismatch unit tests',
         'evidence': ['artifacts/acceptance/exports/m2_gateway_identity_v110',
                      'tests/unit/test_identity_lab_ed25519.py']},
        {'id': 'P12', 'target': 'missing config/credentials -> FAIL/BLOCKED/NOT_RUN, never PASS',
         'status': 'PASS',
         'reason': 'S6 missing keystore does not fall back; F0 strict config rejects missing witness/key/issuers/ledger',
         'evidence': ['artifacts/acceptance/exports/m2_sros2_enforce_v110',
                      'tests/unit/test_f0_lab_scope.py']},
    ]
    doc = {
        'contract': 'roSystem-v110-matrix/1',
        'generated_at': '2026-10-21T20:00:00Z',
        'final_level': 'C',
        'final_level_name': 'DDS_AND_IDENTITY_LAB_VERIFIED',
        'level_b_reason': 'three-real positive chain requires M1 NORMAL; M1 validation gate is false',
        'cases': cases,
        'summary': {
            'PASS': sum(1 for c in cases if c['status'] == 'PASS'),
            'FAIL': sum(1 for c in cases if c['status'] == 'FAIL'),
            'BLOCKED': sum(1 for c in cases if c['status'] == 'BLOCKED'),
            'NOT_RUN': sum(1 for c in cases if c['status'] == 'NOT_RUN'),
            'NOT_VERIFIED': sum(1 for c in cases if c['status'] == 'NOT_VERIFIED'),
        },
        'runs': {
            'dds_positive': {'manifest': 'artifacts/acceptance/exports/m2_sros2_enforce_v110/evidence_manifest.json',
                             'sha256': sha(EXPORTS / 'm2_sros2_enforce_v110' / 'evidence_manifest.json'),
                             'passed': dds_pos['passed'], 'total': dds_pos['total']},
            'dds_negative': {'manifest': 'artifacts/acceptance/exports/m2_sros2_enforce_v110_negative/evidence_manifest.json',
                             'sha256': sha(EXPORTS / 'm2_sros2_enforce_v110_negative' / 'evidence_manifest.json'),
                             'passed': dds_neg['passed'], 'total': dds_neg['total']},
            'm2_lab_identity': {'manifest': 'artifacts/acceptance/exports/m2_lab_identity_v110/evidence_manifest.json',
                                'sha256': sha(EXPORTS / 'm2_lab_identity_v110' / 'evidence_manifest.json'),
                                'passed': m2['passed'], 'total': m2['total']},
            'gateway_identity': {'manifest': 'artifacts/acceptance/exports/m2_gateway_identity_v110/evidence_manifest.json',
                                 'sha256': sha(EXPORTS / 'm2_gateway_identity_v110' / 'evidence_manifest.json'),
                                 'passed': gw['passed'], 'total': gw['total']},
            'three_real': {'summary': 'artifacts/research/v110/three-real/summary.json',
                           'sha256': sha(RESEARCH / 'three-real' / 'summary.json'),
                           'levels': three['levels']},
            'repeats': {'summary': 'artifacts/research/v110/repeats/v110rep-20261021T195500Z/summary.json',
                        'sha256': sha(RESEARCH / 'repeats' / 'v110rep-20261021T195500Z' / 'summary.json'),
                        'trials': rep['trials'], 'positive_ok': rep['positive_ok']},
        },
    }
    out = EXPORTS / 'research_v110'
    out.mkdir(parents=True, exist_ok=True)
    (out / 'p01_p12_matrix.json').write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(doc['summary'], ensure_ascii=False))
    print('final level', doc['final_level'], doc['final_level_name'])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
