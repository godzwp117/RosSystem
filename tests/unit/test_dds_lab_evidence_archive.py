#!/usr/bin/env python3
"""Audit the 1.1.0 DDS lab evidence archive (self-describing, non-secret).

The 1.0.3 archive kept denial logs but not the generated `permissions.xml`; that
is why its evidence could not be interpreted on a clean checkout. This test
locks in the replacement property for the 1.1.0 archive:

  * the generated permissions travel with the evidence;
  * no private key or certificate material travels with it;
  * every byte is covered by a recorded SHA-256;
  * the summary really is a passing domain-43 Enforce run with a positive
    control and native denials, not merely "some logs exist";
  * the manifest is provenance metadata, **not** a cryptographic attestation.

The 1.0.3 archive is read-only: this test asserts the historical gap instead of
rewriting history.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from identity_trust.assessor import (permission_permits, policy_permits)  # noqa: E402

ARCHIVE = (ROOT / 'artifacts' / 'acceptance' / 'exports' /
           'm2_sros2_enforce_v110')
MANIFEST = ARCHIVE / 'evidence_manifest.json'
POLICY = ROOT / 'security' / 'policies' / 'minimal_permissions.xml'


def manifest():
    return json.loads(MANIFEST.read_text(encoding='utf-8'))


def test_manifest_is_present_and_not_a_self_declared_trust_root():
    doc = manifest()
    assert doc['contract'] == 'dds-lab-evidence/1'
    assert doc['scope'] == 'TEST_ONLY_LAB'
    # Hash manifests prove integrity, not origin. The schema must not pretend
    # otherwise by carrying a signature field it cannot back.
    assert 'signature' not in doc
    assert doc['secrets_included'] is False
    assert 'not usable to impersonate' in doc['private_key_policy']
    assert doc['git_head'], 'archive must record the source commit'
    assert doc['command'], 'archive must record the exact command'
    assert doc['exit_code'] == 0


def test_every_archived_byte_is_hashed_and_present():
    doc = manifest()
    assert doc['files'], 'no files listed'
    for relative, expected in doc['files'].items():
        path = ARCHIVE / relative
        assert path.is_file(), relative
        payload = path.read_bytes()
        assert len(payload) == expected['bytes'], relative
        assert hashlib.sha256(payload).hexdigest() == expected['sha256'], relative


def test_archive_contains_no_private_key_or_certificate_material():
    for path in ARCHIVE.rglob('*'):
        if not path.is_file():
            continue
        assert path.suffix not in {'.pem', '.key', '.p7s', '.p12', '.pfx'}, path
        head = path.read_bytes()[:4096]
        assert b'PRIVATE KEY' not in head, path
        assert b'BEGIN CERTIFICATE' not in head, path


def test_generated_permissions_travel_with_the_evidence():
    doc = manifest()
    assert doc['enclaves'], 'no enclave permissions recorded'
    for name, entry in doc['enclaves'].items():
        path = ARCHIVE / entry['permissions_path']
        assert path.is_file(), name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == \
            entry['permissions_sha256'], name
        assert entry['default_deny'] is True, name
        assert entry['domain_43'] is True, name
        assert entry['certificate']['subject'] == 'CN = /' + name, name
        # The certificate subject is public; the private key is not archived.
        assert entry['certificate']['sha256_fingerprint']


def test_permissions_are_consistent_with_the_source_policy():
    doc = manifest()
    assert hashlib.sha256(POLICY.read_bytes()).hexdigest() == doc['policy']['sha256']
    for enclave, service, allowed in (
            ('/planner', '/rg/guarded_navigate/_action/send_goal', True),
            ('/planner', '/rg/nav_execute/_action/send_goal', False),
            ('/gateway', '/rg/nav_execute/_action/send_goal', True),
            ('/unauthorized', '/rg/nav_execute/_action/send_goal', False)):
        _version, policy_allows = policy_permits(POLICY, enclave, service)
        name = enclave.strip('/')
        entry = doc['enclaves'][name]
        generated = permission_permits(
            ARCHIVE / entry['permissions_path'], service, domain=43)
        assert policy_allows is allowed
        assert generated is allowed


def test_summary_is_a_passing_domain_43_enforce_run():
    doc = manifest()
    run_dir = ARCHIVE / doc['run_id']
    summary = json.loads((run_dir / 'summary.json').read_text(encoding='utf-8'))
    assert summary['suite'] == 'sros2'
    assert summary['run_id'] == doc['run_id']
    assert str(summary['secure_domain']) == '43'
    assert summary['failed'] == 0
    assert summary['passed'] == summary['total'] == 7
    cases = {c['scenario_id']: c for c in summary['scenarios']}
    assert set(cases) == {'S1_normal_mode_a_zone', 'S2', 'S5', 'S3C', 'S3',
                          'S4', 'S6'}
    assert all(c['result'] == 'PASS' and c['status'] == 'PASS'
               for c in cases.values()), cases


def test_scenarios_prove_both_allow_and_deny():
    doc = manifest()
    summary = json.loads((ARCHIVE / doc['run_id'] / 'summary.json')
                         .read_text(encoding='utf-8'))
    cases = {c['scenario_id']: c for c in summary['scenarios']}
    # Legitimate identity + legitimate task: executed downstream.
    assert cases['S2']['reason_code'] == 'ALLOW_IN_POLICY'
    assert cases['S2']['downstream_goal_count'] == 1
    # Legitimate identity + out-of-region task: business policy refuses.
    assert cases['S5']['reason_code'] == 'OUT_OF_REGION'
    assert cases['S5']['downstream_goal_count'] == 0
    # Positive control: the same direct client succeeds as /gateway.
    assert cases['S3C']['reason_code'] == 'EXECUTED'
    assert cases['S3C']['downstream_goal_count'] == 1
    # Planner and unauthorized identity are denied by DDS, with no goal.
    for case in ('S3', 'S4'):
        assert cases[case]['reason_code'] == 'ACTION_CLIENT_CREATION_DENIED'
        assert cases[case]['downstream_goal_count'] == 0
    # Missing keystore does not silently fall back to unsecured communication.
    assert cases['S6']['downstream_goal_count'] == 0


def test_native_denial_bytes_are_archived_not_paraphrased():
    doc = manifest()
    run_dir = ARCHIVE / doc['run_id']
    s3 = (run_dir / 'S3' / 'rogue_planner.log').read_bytes()
    assert b'SECURITY' in s3
    assert b'not found in allow rule' in s3
    assert b'Permissions.cpp' in s3
    assert b'\x1b[' in s3, 'the real interleaved ANSI bytes must be kept'
    s3c = (run_dir / 'S3C' / 'rogue_gateway.log').read_text(
        encoding='utf-8', errors='replace')
    assert 'ROGUE_RESULT' in s3c


def test_historical_archive_gap_is_asserted_not_rewritten():
    historical = (ROOT / 'artifacts' / 'acceptance' / 'exports' /
                  'm2_sros2_enforce' / 'logs' / 'tests_evidence' /
                  '20261009T093144Z')
    if not historical.is_dir():
        pytest.skip('1.0.3 archive not present in this checkout')
    assert not list(historical.rglob('permissions.xml')), (
        'the 1.0.3 archive is expected to lack permissions.xml; if this changed, '
        'the historical record was modified and must be explained')
    # The new archive is the one that carries permissions.
    assert list(ARCHIVE.rglob('permissions.xml'))


def test_archive_does_not_claim_production_scope():
    doc = manifest()
    assert doc['scope'] == 'TEST_ONLY_LAB'
    assert 'production' not in doc['scope'].lower()
    assert doc['note'].startswith('permissions.xml are policy-derived')


# ---------------------------------------------------------------------------
# Negative DDS suite (trust root / tampered signature / Enforce-off control)
# ---------------------------------------------------------------------------
NEG_ARCHIVE = (ROOT / 'artifacts' / 'acceptance' / 'exports' /
               'm2_sros2_enforce_v110_negative')
NEG_MANIFEST = NEG_ARCHIVE / 'evidence_manifest.json'


def neg_manifest():
    return json.loads(NEG_MANIFEST.read_text(encoding='utf-8'))


def neg_summary():
    doc = neg_manifest()
    return json.loads((NEG_ARCHIVE / doc['run_id'] / 'summary.json')
                      .read_text(encoding='utf-8'))


def test_negative_manifest_hashes_and_no_secrets():
    doc = neg_manifest()
    assert doc['scope'] == 'TEST_ONLY_LAB'
    assert doc['secrets_included'] is False
    for relative, expected in doc['files'].items():
        path = NEG_ARCHIVE / relative
        assert path.is_file(), relative
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected['sha256'], relative
    for path in NEG_ARCHIVE.rglob('*'):
        if path.is_file():
            assert path.suffix not in {'.pem', '.key', '.p7s'}, path
            assert b'PRIVATE KEY' not in path.read_bytes()[:4096], path


def test_negative_suite_is_complete_and_paired_with_controls():
    doc = neg_manifest()
    summary = neg_summary()
    assert summary['contract'] == 'dds-lab-negative/1'
    assert summary['failed'] == 0
    assert summary['passed'] == summary['total'] == 6
    cases = {c['case_id']: c for c in summary['results']}
    assert set(cases) == {
        'N0_positive_control', 'N1_trust_root_mismatch',
        'N2_tampered_permissions_p7s', 'N4_cert_enclave_mismatch',
        'N5_tampered_permissions_xml', 'N3_enforce_disabled_control'}
    assert all(c['result'] == 'PASS' for c in cases.values())
    # Every denial case must carry its own positive control in the same stack.
    for case in ('N1_trust_root_mismatch', 'N4_cert_enclave_mismatch'):
        names = ' '.join(chk['check'] for chk in cases[case]['checks'])
        assert '正向对照' in names, case
    assert '正向对照' in ' '.join(
        chk['check'] for chk in cases['N2_tampered_permissions_p7s']['checks'])
    assert '正向对照' in ' '.join(
        chk['check'] for chk in cases['N5_tampered_permissions_xml']['checks'])


def test_enforce_off_is_a_control_condition_not_a_security_pass():
    summary = neg_summary()
    case = {c['case_id']: c for c in summary['results']}['N3_enforce_disabled_control']
    assert 'not a security pass' in ' '.join(case['notes'])
    assert any('确实能执行' in chk['check'] for chk in case['checks'])


def test_tampered_xml_finding_is_recorded_as_measured():
    summary = neg_summary()
    case = {c['case_id']: c for c in summary['results']}['N5_tampered_permissions_xml']
    notes = ' '.join(case['notes'])
    assert 'CMS-signed permissions.p7s' in notes
    assert 'inert' in notes
