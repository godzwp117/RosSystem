#!/usr/bin/env python3
"""Ed25519 lab request-identity: positive path and every fail-closed branch.

What is being tested
--------------------
`identity_trust/lab_issuer.py` signs a v3 attestation only after checking a real
DDS observation ledger (writer GUID -> authenticated certificate subject ->
request payload carries the exact request digest). `current_identity.verify`
then verifies the Ed25519 signature against a public key pinned by SHA-256 in a
LAB-scoped trusted issuer file, checks request binding, freshness and an atomic
nonce reservation, and F0 may accept it only with `allow_lab=True`.

The tests use a synthetic ledger with the exact contract produced by
`src/m2_witness/m2_ingress_witness.cpp`; the real-wire attribution is exercised
separately by tests/integration/m2_lab_identity_chain.py.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from identity_trust import current_identity as ci  # noqa: E402
from identity_trust import lab_issuer as li  # noqa: E402


def envelope(request='req-lab-001', resource='/rg/guarded_navigate',
             x=1.5, y=1.5):
    return {
        'schema_version': '1.0.0-proposed', 'run_id': 'run-lab',
        'request_id': request, 'created_at': '2026-10-21T18:00:00Z',
        'candidate_action': {'action_resource': resource, 'operation': 'NAVIGATE',
                             'task_id': 'patrol_a_001',
                             'target': {'frame_id': 'map', 'x': x, 'y': y}},
        'observations': [{'source': 'security', 'kind': 'UNKNOWN',
                          'observed_at': '2026-10-21T18:00:00Z'}],
        'evidence_refs': [{'ref': 'lab', 'kind': 'CONTROLLED_SECURITY_EXPERIMENT'}],
    }


def ledger_row(env, *, subject='/CN=\\/planner', authenticated=True, payload=None,
               goal_uuid=None, received_at=None):
    digest = ci.request_digest(env)
    return {
        'contract': 'trusted-action-events/1', 'event_kind': 'SEND_GOAL_RECEIVED',
        'resource': 'rt/m2/candidate_task',
        'goal_uuid': goal_uuid or li.goal_uuid_for_request(env['request_id']),
        'request_digest': '0' * 64, 'task_code': 1001,
        'payload': payload if payload is not None else li.payload_for_request(env['request_id'], env),
        'writer_guid': 'aa.bb.cc.dd.ee.ff.00.11.22.33.44.55|00000103',
        'participant_guid': 'aa.bb.cc.dd.ee.ff.00.11.22.33.44.55',
        'sample_sequence': 1, 'sender_authenticated': authenticated,
        'certificate_subject': subject, 'ca_subject': '/CN=sros2CA',
        'received_at': received_at or li.utc_now(),
        'source': 'TRUSTED_ACTION_INGRESS', 'observer': 'M2_TRUSTED_INGRESS',
    }


@pytest.fixture()
def lab(tmp_path):
    keydir = tmp_path / 'keys'
    info = li.gen_key(keydir, 'lab-ed25519-ingress-1')
    return {'dir': keydir, 'info': info}


def write_ledger(path, rows):
    path.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows),
                    encoding='utf-8')
    return path


def issue_for(lab, env, rows, tmp_path, **over):
    ledger = write_ledger(tmp_path / 'events.jsonl', rows)
    envelope_path = tmp_path / 'envelope.json'
    envelope_path.write_text(json.dumps(env), encoding='utf-8')
    out = tmp_path / 'attestation.json'
    result = li.issue(lab['dir'], envelope_path, ledger, out, **over)
    return out, result, ledger


def verify(lab, env, attestation, tmp_path, now=None, ledger_name='nonce.jsonl'):
    ledger = ci.Ledger(str(tmp_path / ledger_name))
    return ci.verify(env, str(attestation), str(lab['dir'] / li.PUB_NAME),
                     issuers_path=str(lab['dir'] / li.TRUST_NAME),
                     ledger=ledger, now=now)


def test_gen_key_is_lab_scoped_and_private_key_is_0600(lab):
    assert (lab['dir'] / li.KEY_NAME).stat().st_mode & 0o077 == 0
    assert (lab['dir'] / li.PUB_NAME).stat().st_mode & 0o077 == 0o044  # 0644
    trust = json.loads((lab['dir'] / li.TRUST_NAME).read_text(encoding='utf-8'))
    assert trust['contract'] == ci.ISSUER_CONTRACT_V2
    entry = trust['issuers'][0]
    assert entry['scope'] == ci.SCOPE_LAB
    assert entry['trust'] == ci.TRUST_VERIFIED
    assert 'PRIVATE KEY' not in (lab['dir'] / li.TRUST_NAME).read_text(encoding='utf-8')
    assert 'PRIVATE KEY' not in (lab['dir'] / li.PUB_NAME).read_text(encoding='utf-8')


def test_valid_attestation_is_lab_authenticated_not_production(lab, tmp_path):
    env = envelope()
    attestation, info, _ledger = issue_for(lab, env, [ledger_row(env)], tmp_path,
                                           require_subject='/CN=\\/planner')
    assert info['subject'] == '/CN=\\/planner'
    result = verify(lab, env, attestation, tmp_path)
    assert result['status'] == ci.STATUS_AUTHENTICATED_LAB
    assert result['trust_scope'] == ci.SCOPE_LAB
    assert result['checks'] == {'signature': 'VALID',
                                'issuer': ci.ISSUER_CHECK_LAB,
                                'request_binding': 'MATCH',
                                'freshness': 'OK', 'replay': 'RESERVED'}
    assert result['attestation']['signature_alg'] == 'ed25519'
    # The lab status is not production and is not accepted by default.
    assert ci.f0_accepts(result) is False
    assert ci.f0_accepts(result, allow_lab=True) is True
    assert result['status'] != ci.STATUS_AUTHENTICATED


def test_replay_of_the_same_nonce_fails_closed(lab, tmp_path):
    env = envelope()
    attestation, _info, _ = issue_for(lab, env, [ledger_row(env)], tmp_path)
    first = verify(lab, env, attestation, tmp_path)
    second = verify(lab, env, attestation, tmp_path)
    assert first['status'] == ci.STATUS_AUTHENTICATED_LAB
    assert second['status'] == ci.STATUS_UNKNOWN
    assert second['checks']['replay'] == 'REPLAYED'
    assert ci.f0_accepts(second, allow_lab=True) is False


def test_expired_attestation_fails_closed(lab, tmp_path):
    env = envelope()
    attestation, _info, _ = issue_for(lab, env, [ledger_row(env)], tmp_path)
    result = verify(lab, env, attestation, tmp_path,
                    now=time.time() + ci.MAX_REMOTE_AGE_SEC + 10)
    assert result['status'] == ci.STATUS_UNKNOWN
    assert result['checks']['freshness'] == 'STALE'


def test_future_timestamp_fails_closed(lab, tmp_path):
    env = envelope()
    attestation, _info, _ = issue_for(lab, env, [ledger_row(env)], tmp_path)
    result = verify(lab, env, attestation, tmp_path,
                    now=time.time() - ci.MAX_CLOCK_SKEW_SEC - 10)
    assert result['status'] == ci.STATUS_UNKNOWN
    assert result['checks']['freshness'] == 'FROM_FUTURE'


def test_request_digest_mismatch_fails_closed(lab, tmp_path):
    env = envelope()
    attestation, _info, _ = issue_for(lab, env, [ledger_row(env)], tmp_path)
    other = envelope(x=9.9, y=9.9)           # same id, different target
    result = verify(lab, other, attestation, tmp_path)
    assert result['status'] == ci.STATUS_UNKNOWN
    assert result['checks']['request_binding'] == 'MISMATCH'


def test_tampered_signature_fails_closed(lab, tmp_path):
    env = envelope()
    attestation, _info, _ = issue_for(lab, env, [ledger_row(env)], tmp_path)
    document = json.loads(attestation.read_text(encoding='utf-8'))
    value = bytearray.fromhex(document['signature']['value'])
    value[0] ^= 0xFF
    document['signature']['value'] = bytes(value).hex()
    attestation.write_text(json.dumps(document), encoding='utf-8')
    result = verify(lab, env, attestation, tmp_path)
    assert result['status'] == ci.STATUS_UNKNOWN
    assert result['checks']['signature'] == 'INVALID'


def test_tampered_body_fails_closed(lab, tmp_path):
    env = envelope()
    attestation, _info, _ = issue_for(lab, env, [ledger_row(env)], tmp_path)
    document = json.loads(attestation.read_text(encoding='utf-8'))
    document['body']['remote_identity']['security_identity'] = '/CN=\\/operator'
    attestation.write_text(json.dumps(document), encoding='utf-8')
    result = verify(lab, env, attestation, tmp_path)
    assert result['status'] == ci.STATUS_UNKNOWN
    assert result['checks']['signature'] == 'INVALID'


def test_wrong_public_key_fails_closed(lab, tmp_path):
    env = envelope()
    attestation, _info, _ = issue_for(lab, env, [ledger_row(env)], tmp_path)
    other = tmp_path / 'other-keys'
    li.gen_key(other, 'lab-ed25519-ingress-1')
    result = ci.verify(env, str(attestation), str(other / li.PUB_NAME),
                       issuers_path=str(lab['dir'] / li.TRUST_NAME),
                       ledger=ci.Ledger(str(tmp_path / 'n.jsonl')))
    assert result['status'] == ci.STATUS_UNKNOWN
    assert result['checks']['signature'] == 'KEY_MISMATCH'


def test_unknown_issuer_fails_closed(lab, tmp_path):
    env = envelope()
    attestation, _info, _ = issue_for(lab, env, [ledger_row(env)], tmp_path)
    other = tmp_path / 'other-keys'
    li.gen_key(other, 'some-other-lab-issuer')
    result = ci.verify(env, str(attestation), str(lab['dir'] / li.PUB_NAME),
                       issuers_path=str(other / li.TRUST_NAME),
                       ledger=ci.Ledger(str(tmp_path / 'n2.jsonl')))
    assert result['status'] == ci.STATUS_UNKNOWN
    assert result['checks']['issuer'] == 'NOT_LISTED'


def test_private_key_cannot_be_used_as_verification_key(lab, tmp_path):
    env = envelope()
    attestation, _info, _ = issue_for(lab, env, [ledger_row(env)], tmp_path)
    result = ci.verify(env, str(attestation), str(lab['dir'] / li.KEY_NAME),
                       issuers_path=str(lab['dir'] / li.TRUST_NAME),
                       ledger=ci.Ledger(str(tmp_path / 'n3.jsonl')))
    assert result['status'] == ci.STATUS_UNKNOWN
    assert result['checks']['signature'] == 'KEY_UNUSABLE'


def test_unauthenticated_event_is_not_signed(lab, tmp_path):
    env = envelope()
    with pytest.raises(li.LabError):
        issue_for(lab, env, [ledger_row(env, authenticated=False)], tmp_path)


def test_payload_digest_mismatch_is_not_signed(lab, tmp_path):
    env = envelope()
    row = ledger_row(env)
    row['payload'] = env['request_id'] + '|' + 'f' * 64
    with pytest.raises(li.LabError):
        issue_for(lab, env, [row], tmp_path)


def test_wrong_subject_is_not_signed(lab, tmp_path):
    env = envelope()
    with pytest.raises(li.LabError):
        issue_for(lab, env, [ledger_row(env, subject='/CN=\\/operator')], tmp_path,
                  require_subject='/CN=\\/planner')


def test_stale_observation_is_not_signed(lab, tmp_path):
    env = envelope()
    old = li.utc_now(time.time() - 600)
    with pytest.raises(li.LabError):
        issue_for(lab, env, [ledger_row(env, received_at=old)], tmp_path)


def test_wrong_goal_uuid_is_not_signed(lab, tmp_path):
    env = envelope()
    with pytest.raises(li.LabError):
        issue_for(lab, env, [ledger_row(env, goal_uuid='0' * 32)], tmp_path)


def test_no_observation_is_not_signed(lab, tmp_path):
    env = envelope()
    with pytest.raises(li.LabError):
        issue_for(lab, env, [], tmp_path)


def test_shipped_lab_trust_is_lab_scope_only():
    """The repository must not ship a PRODUCTION-scoped issuer trust file."""
    suspicious = []
    for path in ROOT.rglob('issuers.json'):
        if any(part in {'.git', 'build', 'install', 'log', 'logs',
                        'node_modules'} for part in path.parts):
            continue
        try:
            document = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if document.get('contract') != ci.ISSUER_CONTRACT_V2:
            continue
        for entry in document.get('issuers') or []:
            if entry.get('scope') == ci.SCOPE_PRODUCTION:
                suspicious.append(str(path))
    assert not suspicious, suspicious
