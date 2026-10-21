#!/usr/bin/env python3
"""Gateway independent authorization evidence (1.1.0).

Locks in what the real run shows: the Gateway re-verifies the current-request
attestation itself, applies TaskPolicy independently, and cannot be made to
forward a goal by a missing or target-mismatched attestation.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = (ROOT / 'artifacts' / 'acceptance' / 'exports' /
           'm2_gateway_identity_v110')
MANIFEST = ARCHIVE / 'evidence_manifest.json'


def manifest():
    return json.loads(MANIFEST.read_text(encoding='utf-8'))


def run_dir():
    return ARCHIVE / manifest()['run_id']


def jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()
            if line.strip()]


def test_manifest_is_complete_and_secret_free():
    doc = manifest()
    assert doc['scope'] == 'TEST_ONLY_LAB'
    assert doc['secrets_included'] is False
    assert doc['secure_domain'] == 45
    for relative, expected in doc['files'].items():
        path = ARCHIVE / relative
        assert path.is_file(), relative
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected['sha256'], relative
    for path in ARCHIVE.rglob('*'):
        if path.is_file():
            assert path.suffix not in {'.pem', '.key', '.p7s'}, path
            assert b'PRIVATE KEY' not in path.read_bytes()[:4096], path


def test_summary_reports_eleven_checks_passed():
    summary = json.loads((run_dir() / 'summary.json').read_text(encoding='utf-8'))
    assert summary['contract'] == 'gateway-identity-lab/1'
    assert summary['failed'] == 0
    assert summary['passed'] == summary['total'] == 11


def test_gateway_allowed_only_the_valid_attestation():
    decisions = {row['request_id']: row for row in jsonl(run_dir() / 'audit.jsonl')
                 if row.get('event_type') == 'DecisionEvent'}
    assert decisions['req-gw-lab-001']['decision'] == 'ALLOW'
    assert decisions['req-gw-lab-001']['reason_code'] == 'ALLOW_IN_POLICY'
    for request_id in ('req-gw-lab-002', 'req-gw-lab-003'):
        assert decisions[request_id]['decision'] == 'BLOCK'
        assert decisions[request_id]['reason_code'] == 'IDENTITY_ATTESTATION_REJECTED'


def test_gateway_identity_audit_is_independent_of_f0():
    rows = {row['request_id']: row
            for row in jsonl(run_dir() / 'identity_audit.jsonl')}
    good = rows['req-gw-lab-001']
    assert good['event_type'] == 'GatewayIdentityCheck'
    assert good['decision'] == 'ALLOW'
    assert good['status'] == 'AUTHENTICATED_LAB'
    assert good['scope'] == 'LAB'
    assert good['checks']['signature'] == 'VALID'
    assert good['checks']['request_binding'] == 'MATCH'
    assert good['attestation_sha256']
    assert rows['req-gw-lab-002']['decision'] == 'BLOCK'
    assert rows['req-gw-lab-003']['decision'] == 'BLOCK'
    assert rows['req-gw-lab-003']['checks']['request_binding'] == 'MISMATCH'


def test_exactly_one_downstream_goal_for_the_three_cases():
    goals = jsonl(run_dir() / '_gateway_stack' / 'navsim_goals.jsonl')
    assert len(goals) == 1
    # The one goal belongs to the request the Gateway allowed.
    assert 'req-gw-lab-001' in json.dumps(goals[0], ensure_ascii=False)


def test_no_production_claim_in_the_archive():
    summary = json.loads((run_dir() / 'summary.json').read_text(encoding='utf-8'))
    assert summary['scope'] == 'TEST_ONLY_LAB'
    assert summary['secure_domain'] == 45
