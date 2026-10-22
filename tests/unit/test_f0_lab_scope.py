#!/usr/bin/env python3
"""F0 acceptance of LAB-scoped Ed25519 identity evidence.

The production path is unchanged: `AUTHENTICATED` requires a verified issuer and
is accepted by default. `AUTHENTICATED_LAB` is accepted **only** when the trusted
config sets `identity_attestation.allow_lab_scope: true`; without it F0 blocks.

These tests execute the real adapter subprocess (`scripts/team_demo.py`), so they
cover config parsing, the F0-side re-verification and the decision mapping, not
just `f0_accepts()` in isolation.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip('jsonschema', reason='needs jsonschema>=4')

ROOT = Path(__file__).resolve().parents[2]
for extra in (ROOT, ROOT / 'scripts', ROOT / 'tests' / 'unit'):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from test_team_process_protocol import (  # noqa: E402
    envelope, proceed_control, run_adapter, write_config)

from identity_trust import current_identity as ci  # noqa: E402
from identity_trust import lab_issuer as li  # noqa: E402


def ledger_row(env, *, subject='/CN=\\/planner', authenticated=True, received_at=None):
    return {
        'contract': 'trusted-action-events/1', 'event_kind': 'SEND_GOAL_RECEIVED',
        'resource': 'rt/m2/candidate_task',
        'goal_uuid': li.goal_uuid_for_request(env['request_id']),
        'request_digest': '0' * 64, 'task_code': 1001,
        'payload': li.payload_for_request(env['request_id'], env),
        'writer_guid': 'aa.bb.cc.dd.ee.ff.00.11.22.33.44.55|00000103',
        'participant_guid': 'aa.bb.cc.dd.ee.ff.00.11.22.33.44.55',
        'sample_sequence': 1, 'sender_authenticated': authenticated,
        'certificate_subject': subject, 'ca_subject': '/CN=sros2CA',
        'received_at': received_at or li.utc_now(),
        'source': 'TRUSTED_ACTION_INGRESS', 'observer': 'M2_TRUSTED_INGRESS',
    }


def materials(tmp_path, env, *, authenticated=True):
    keydir = tmp_path / 'keys'
    li.gen_key(keydir, 'lab-ed25519-ingress-1')
    ledger = tmp_path / 'events.jsonl'
    ledger.write_text(json.dumps(ledger_row(env, authenticated=authenticated)) + '\n',
                      encoding='utf-8')
    envelope_path = tmp_path / 'evidence-envelope.json'
    envelope_path.write_text(json.dumps(env), encoding='utf-8')
    attestation = tmp_path / 'attestation.json'
    li.issue(keydir, envelope_path, ledger, attestation,
             require_subject='/CN=\\/planner')
    return {'keydir': keydir, 'ledger': ledger, 'attestation': attestation,
            'nonce_ledger': tmp_path / 'nonce.jsonl'}


def identity_block(m, *, allow_lab=True, **over):
    block = {
        'mode': 'STRICT',
        'witness_path': str(m['attestation']),
        'key_path': str(m['keydir'] / li.PUB_NAME),
        'issuers_path': str(m['keydir'] / li.TRUST_NAME),
        'ledger_path': str(m['nonce_ledger']),
        'allow_lab_scope': allow_lab,
    }
    block.update(over)
    return block


def run(tmp_path, env, m, *, block=None, request_id='req-f0-lab'):
    config = write_config(tmp_path, mode='mock', identity_attestation=block or identity_block(m))
    return run_adapter(tmp_path, env, config)


def test_lab_identity_is_accepted_only_with_explicit_opt_in(tmp_path):
    env = envelope(proceed_control(), request_id='req-f0-lab')
    m = materials(tmp_path, env)
    code, result, err = run(tmp_path, env, m)
    assert code == 0, (result, err)
    assert result['decision'] == 'READY_FOR_GATEWAY_SUBMISSION', result
    assert result['identity_attestation']['verified'] is True
    assert result['identity_attestation']['scope'] == ci.SCOPE_LAB
    assert result['identity_attestation']['status'] == ci.STATUS_AUTHENTICATED_LAB

    # Fresh evidence (new nonce), no opt-in: F0 must block and say why. Reusing
    # the first attestation would test replay instead of scope policy.
    env2 = envelope(proceed_control(), request_id='req-f0-lab')
    noopt = tmp_path / 'noopt'
    noopt.mkdir()
    m2 = materials(noopt, env2)
    code2, result2, _ = run(noopt, env2, m2, block=identity_block(m2, allow_lab=False))
    assert code2 != 0
    assert result2['decision'] == 'ADAPTER_BLOCK'
    reason = (result2.get('identity_attestation') or {}).get('reason', '')
    assert 'allow_lab_scope' in reason, reason


def test_lab_opt_in_requires_issuers_and_ledger(tmp_path):
    env = envelope(proceed_control(), request_id='req-f0-lab-missing')
    m = materials(tmp_path, env)
    block = identity_block(m)
    block.pop('issuers_path')
    config = write_config(tmp_path, mode='mock', identity_attestation=block)
    code, result, _err = run_adapter(tmp_path, env, config)
    assert code != 0
    assert result['decision'] == 'ADAPTER_BLOCK'
    assert 'issuers_path' in result.get('detail', '')


def test_lab_attestation_cannot_be_replayed(tmp_path):
    env = envelope(proceed_control(), request_id='req-f0-lab-replay')
    m = materials(tmp_path, env)
    code, result, _ = run(tmp_path, env, m)
    assert code == 0 and result['decision'] == 'READY_FOR_GATEWAY_SUBMISSION'
    # Second invocation with the same single-use attestation.
    code2, result2, _ = run(tmp_path, env, m)
    assert code2 != 0
    assert result2['decision'] == 'ADAPTER_BLOCK'
    reason = (result2.get('identity_attestation') or {}).get('reason', '')
    assert 'REPLAYED' in reason or '重放' in reason


def test_unauthenticated_dds_observation_is_not_signed(tmp_path):
    env = envelope(proceed_control(), request_id='req-f0-lab-unauth')
    with pytest.raises(li.LabError):
        materials(tmp_path, env, authenticated=False)


def test_tampered_attestation_blocks(tmp_path):
    env = envelope(proceed_control(), request_id='req-f0-lab-tamper')
    m = materials(tmp_path, env)
    document = json.loads(m['attestation'].read_text(encoding='utf-8'))
    document['body']['request_id'] = 'req-other'
    m['attestation'].write_text(json.dumps(document), encoding='utf-8')
    code, result, _ = run(tmp_path, env, m)
    assert code != 0
    assert result['decision'] == 'ADAPTER_BLOCK'


def test_expired_attestation_blocks_at_f0(tmp_path, monkeypatch):
    env = envelope(proceed_control(), request_id='req-f0-lab-stale')
    m = materials(tmp_path, env)
    # Move the attestation validity out of the window by verifying against a
    # shifted clock is not possible through the subprocess; instead rewrite the
    # signed timestamp and re-sign with the lab key (simulating a stale issuer).
    from cryptography.hazmat.primitives import serialization
    key = serialization.load_pem_private_key(
        (m['keydir'] / li.KEY_NAME).read_bytes(), password=None)
    document = json.loads(m['attestation'].read_text(encoding='utf-8'))
    document['body']['received_at'] = li.utc_now(time.time() - 600)
    document['signature']['value'] = key.sign(ci.canonical(document['body'])).hex()
    m['attestation'].write_text(json.dumps(document), encoding='utf-8')
    code, result, _ = run(tmp_path, env, m)
    assert code != 0
    assert result['decision'] == 'ADAPTER_BLOCK'
    reason = (result.get('identity_attestation') or {}).get('reason', '')
    assert 'STALE' in reason or '新鲜度' in reason


def test_production_status_is_not_reachable_from_a_lab_scope(tmp_path):
    env = envelope(proceed_control(), request_id='req-f0-lab-prod')
    m = materials(tmp_path, env)
    result = ci.verify(
        env, str(m['attestation']), str(m['keydir'] / li.PUB_NAME),
        issuers_path=str(m['keydir'] / li.TRUST_NAME),
        ledger=ci.Ledger(str(m['nonce_ledger'])))
    assert result['status'] == ci.STATUS_AUTHENTICATED_LAB
    assert result['trust_scope'] == ci.SCOPE_LAB
    # The default acceptance (production semantics) rejects it.
    assert ci.f0_accepts(result) is False
