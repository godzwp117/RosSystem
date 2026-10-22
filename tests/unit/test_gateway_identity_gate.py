#!/usr/bin/env python3
"""Gateway-side independent identity verification (1.1.0).

The Gateway must decide execution itself: it re-verifies the signed statement for
this exact goal, with its own trust anchor and its own nonce cache. These tests
call the same function the ROS node calls, without starting DDS.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
for extra in (ROOT, ROOT / 'tests' / 'unit', ROOT / 'src' / 'rg_gateway'):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from identity_trust import current_identity as ci  # noqa: E402
from identity_trust import lab_issuer as li  # noqa: E402
from rg_gateway import identity_gate as gate  # noqa: E402


def goal(request_id='req-gw-001', task_id='patrol_a_001', frame='map',
         x=1.5, y=1.5, z=0.0):
    return SimpleNamespace(
        request_id=request_id, task_id=task_id,
        target=SimpleNamespace(
            header=SimpleNamespace(frame_id=frame),
            pose=SimpleNamespace(position=SimpleNamespace(x=x, y=y, z=z))))


def ledger_row(envelope, *, subject='/CN=\\/planner', authenticated=True):
    return {
        'contract': 'trusted-action-events/1', 'event_kind': 'SEND_GOAL_RECEIVED',
        'resource': 'rt/m2/candidate_task',
        'goal_uuid': li.goal_uuid_for_request(envelope['request_id']),
        'request_digest': '0' * 64, 'task_code': 1001,
        'payload': li.payload_for_request(envelope['request_id'], envelope),
        'writer_guid': 'aa.bb.cc.dd.ee.ff.00.11.22.33.44.55|00000103',
        'participant_guid': 'aa.bb.cc.dd.ee.ff.00.11.22.33.44.55',
        'sample_sequence': 1, 'sender_authenticated': authenticated,
        'certificate_subject': subject, 'ca_subject': '/CN=sros2CA',
        'received_at': li.utc_now(),
        'source': 'TRUSTED_ACTION_INGRESS', 'observer': 'M2_TRUSTED_INGRESS',
    }


@pytest.fixture()
def materials(tmp_path):
    keydir = tmp_path / 'keys'
    li.gen_key(keydir, 'lab-ed25519-ingress-1')
    g = goal()
    envelope = gate.envelope_for_goal(g)
    ledger = tmp_path / 'events.jsonl'
    ledger.write_text(json.dumps(ledger_row(envelope)) + '\n', encoding='utf-8')
    env_path = tmp_path / 'envelope.json'
    env_path.write_text(json.dumps(envelope), encoding='utf-8')
    att_dir = tmp_path / 'attestations'
    att_dir.mkdir()
    li.issue(keydir, env_path, ledger, att_dir / (g.request_id + '.json'),
             require_subject='/CN=\\/planner')
    return {'keydir': keydir, 'attestation_dir': att_dir,
            'ledger': tmp_path / 'nonce.jsonl', 'goal': g,
            'envelope': envelope}


def call(materials, g=None, **over):
    kwargs = {
        'attestation_dir': str(materials['attestation_dir']),
        'public_key': str(materials['keydir'] / li.PUB_NAME),
        'issuers_path': str(materials['keydir'] / li.TRUST_NAME),
        'ledger_path': str(materials['ledger']),
        'allow_lab_scope': True,
    }
    kwargs.update(over)
    return gate.verify_goal(g or materials['goal'], **kwargs)


def test_gateway_accepts_a_valid_lab_attestation(materials):
    result = call(materials)
    assert result['decision'] == gate.ALLOW
    assert result['verified'] is True
    assert result['scope'] == ci.SCOPE_LAB
    assert result['status'] == ci.STATUS_AUTHENTICATED_LAB
    assert result['checks']['request_binding'] == 'MATCH'
    assert result['attestation_sha256']


def test_gateway_rejects_replay_with_its_own_cache(materials):
    assert call(materials)['decision'] == gate.ALLOW
    second = call(materials)
    assert second['decision'] == gate.BLOCK
    assert second['checks']['replay'] == 'REPLAYED'


def test_gateway_rejects_a_different_target(materials):
    other = goal(x=9.9, y=9.9)
    result = call(materials, other)
    assert result['decision'] == gate.BLOCK
    assert result['checks']['request_binding'] == 'MISMATCH'


def test_gateway_rejects_missing_attestation(materials):
    materials['attestation_dir'] = materials['attestation_dir'] / 'empty'
    materials['attestation_dir'].mkdir()
    result = call(materials)
    assert result['decision'] == gate.BLOCK
    assert 'no attestation' in result['reason']


def test_gateway_rejects_unsafe_request_id(materials):
    bad = goal(request_id='../etc/passwd')
    result = call(materials, bad)
    assert result['decision'] == gate.BLOCK
    assert 'not safe' in result['reason']


def test_gateway_rejects_symlinked_attestation(materials, tmp_path):
    real = materials['attestation_dir'] / (materials['goal'].request_id + '.json')
    elsewhere = tmp_path / 'elsewhere.json'
    elsewhere.write_bytes(real.read_bytes())
    real.unlink()
    real.symlink_to(elsewhere)
    result = call(materials)
    assert result['decision'] == gate.BLOCK


def test_gateway_requires_explicit_lab_opt_in(materials):
    result = call(materials, allow_lab_scope=False)
    assert result['decision'] == gate.BLOCK
    assert result['status'] == ci.STATUS_AUTHENTICATED_LAB


def test_gateway_gate_disabled_keeps_103_behaviour(materials):
    result = call(materials, attestation_dir='')
    assert result['decision'] == gate.DISABLED
    assert result['enabled'] is False


def test_envelope_for_goal_matches_the_request_digest():
    env = gate.envelope_for_goal(goal())
    assert env['candidate_action']['target'] == {'frame_id': 'map',
                                                'x': 1.5, 'y': 1.5, 'z': 0.0}
    assert len(ci.request_digest(env)) == 64
