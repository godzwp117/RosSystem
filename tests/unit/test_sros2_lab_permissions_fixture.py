#!/usr/bin/env python3
"""Lab permissions fixture: non-secret, policy-derived, and not a keystore.

Background
----------
The archived SROS 2 run `20261009T093144Z` contains runtime denial logs but no
`permissions.xml`: the keystore holding them was generated at experiment time and
deliberately wiped (it contains private keys, and `security/keystore/` is
git-ignored). The identity assessor refuses to turn a runtime denial into a
conclusion unless the *generated* DDS permission can be compared with the source
policy, so 13 evidence-interpretation tests failed on a fresh checkout with the
message "DDS permissions missing".

The fix is not to weaken the assessor. It is to keep a **permissions-only,
non-secret** artifact of the lab toolchain in the repository:

  tests/fixtures/sros2_lab_permissions/
    MANIFEST.json
    enclaves/<role>/permissions.xml     (no cert.pem, no key.pem, no CA)

These tests pin that fixture to the policy source and prove it cannot be
mistaken for a usable keystore. The real Enforce experiments still have to
generate a full keystore with `scripts/setup_sros2.sh`.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from identity_trust.assessor import (permission_permits, policy_permits)  # noqa: E402

FIXTURE = ROOT / 'tests' / 'fixtures' / 'sros2_lab_permissions'
MANIFEST = FIXTURE / 'MANIFEST.json'
POLICY = ROOT / 'security' / 'policies' / 'minimal_permissions.xml'


def manifest():
    return json.loads(MANIFEST.read_text(encoding='utf-8'))


def policy_enclaves():
    import xml.etree.ElementTree as ET
    root = ET.fromstring(POLICY.read_bytes())
    return {e.get('path') for e in root.iter() if e.tag == 'enclave'}


def test_manifest_hashes_match_committed_files():
    doc = manifest()
    assert doc['scope'] == 'TEST_ONLY'
    assert doc['contains_private_keys'] is False
    assert doc['files'], 'fixture manifest must list files'
    for relative, expected in doc['files'].items():
        payload = (FIXTURE / relative).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == expected, relative


def test_fixture_contains_no_key_or_certificate_material():
    names = {p.name for p in FIXTURE.rglob('*') if p.is_file()}
    forbidden = {'key.pem', 'cert.pem', 'ca.cert.pem', 'identity_ca.cert.pem',
                 'permissions_ca.cert.pem', 'permissions.p7s', 'governance.p7s',
                 'governance.xml'}
    assert not (names & forbidden), names & forbidden
    # Nothing in the fixture may look like PEM private key material.
    for path in FIXTURE.rglob('*'):
        if path.is_file() and path.suffix != '.json':
            data = path.read_bytes()
            assert b'PRIVATE KEY' not in data, path
            assert b'BEGIN CERTIFICATE' not in data, path


def test_policy_hash_is_current():
    doc = manifest()
    expected = hashlib.sha256(POLICY.read_bytes()).hexdigest()
    assert doc['policy_sha256'] == expected, (
        'policy changed since the lab permissions fixture was generated; '
        'regenerate it with scripts/setup_sros2.sh and refresh MANIFEST.json')


def test_fixture_covers_every_policy_enclave_and_nothing_else():
    expected = policy_enclaves()
    got = {'/' + p.parent.name for p in FIXTURE.glob('enclaves/*/permissions.xml')}
    assert got == expected, (sorted(got), sorted(expected))


@pytest.mark.parametrize('enclave,service,allowed', [
    # Services are action sub-services ("<action>/_action/send_goal"), which is
    # how the source policy spells them; policy_permits dispatches on request=ALLOW.
    ('/planner', '/rg/guarded_navigate/_action/send_goal', True),
    ('/planner', '/rg/nav_execute/_action/send_goal', False),
    ('/gateway', '/rg/nav_execute/_action/send_goal', True),
    ('/unauthorized', '/rg/nav_execute/_action/send_goal', False),
])
def test_generated_permission_agrees_with_source_policy(enclave, service, allowed):
    _version, policy_allows = policy_permits(POLICY, enclave, service)
    permission = FIXTURE / 'enclaves' / enclave.strip('/') / 'permissions.xml'
    generated_allows = permission_permits(permission, service, domain=43)
    assert policy_allows is allowed
    assert generated_allows is allowed


def test_fixture_is_not_a_usable_keystore():
    """No CA certificate means no DDS participant can start from this fixture."""
    assert not (FIXTURE / 'public' / 'ca.cert.pem').exists()
    assert not (FIXTURE / 'private').exists()
    # The materialized copy under security/keystore (git-ignored) must either be a
    # real lab CA or be explicitly marked as the fixture.
    keystore = ROOT / 'security' / 'keystore'
    if keystore.is_dir() and not (keystore / 'public' / 'ca.cert.pem').exists():
        marker = keystore / 'FIXTURE_ONLY_NO_PRIVATE_KEYS'
        assert marker.is_file(), (
            'permissions-only fixture was materialized without a marker; '
            'scripts could mistake it for a usable keystore')
        assert 'no private keys' in marker.read_text(encoding='utf-8')


def test_fixture_note_does_not_impersonate_historical_material():
    note = manifest()['note']
    assert 'NOT the keystore used by the 2026-10-09 historical run' in note
    assert 'Regenerate the full keystore' in note


def test_domain_is_the_secure_lab_domain():
    doc = manifest()
    assert doc['secure_domain_id'] == 43
    for path in FIXTURE.glob('enclaves/*/permissions.xml'):
        text = path.read_text(encoding='utf-8')
        assert '<id>43</id>' in text, path


def test_fixture_permissions_are_default_deny():
    for path in FIXTURE.glob('enclaves/*/permissions.xml'):
        text = path.read_text(encoding='utf-8')
        assert '<default>DENY</default>' in text, path
