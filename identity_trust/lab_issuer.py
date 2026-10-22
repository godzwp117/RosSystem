#!/usr/bin/env python3
"""LAB-ONLY Ed25519 issuer for current-request identity attestations.

What this is
------------
A controlled lab issuer that signs a v3 attestation only after it has checked a
real DDS observation ledger produced by `src/m2_witness/m2_ingress_witness.cpp`:

  * the sample was received by the trusted ingress (not self-reported by the
    requester);
  * the sample's writer GUID maps to a participant whose DDS certificate was
    authenticated by the lab CA (`sender_authenticated=true`);
  * the observed payload carries this exact request_id and the request digest
    computed from the current envelope;
  * the goal UUID follows the shared convention for that request_id;
  * the observation is recent.

Only then does it sign `request_id + resource + operation + request_digest +
received_at + nonce + remote_identity` with Ed25519. The verifier pins the
public key by SHA-256 in a trusted issuers file with `scope: LAB`.

What this is not
----------------
It is not a production identity issuer. The key lives in a local file, the
trust anchor is a temporary lab CA, and the attested resource is the
pre-admission intent topic, not the ROS Action `send_goal` service request.
F0 accepts the result only when explicitly configured to allow the LAB scope.

Commands
--------
  gen-key  --key-dir DIR --issuer-id ID [--force]
  issue    --key-dir DIR --envelope ENVELOPE.json --ledger EVENTS.jsonl \
           --out ATTESTATION.json [--require-subject '/CN=\\/planner']
  verify   --key-dir DIR --envelope ENVELOPE.json --attestation ATTESTATION.json
  purge    --key-dir DIR

Every command requires `--i-am-a-lab-issuer`, and every run prints `TEST_ONLY`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from identity_trust import current_identity as ci  # noqa: E402

LAB = 'TEST_ONLY_LAB'
KEY_NAME = 'issuer.key.pem'
PUB_NAME = 'issuer.pub.pem'
TRUST_NAME = 'issuers.json'
MAX_LEDGER = 32 * 1024 * 1024


class LabError(RuntimeError):
    pass


def utc_now(epoch=None):
    moment = time.time() if epoch is None else float(epoch)
    return datetime.fromtimestamp(moment, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def goal_uuid_for_request(request_id):
    """Shared convention so the DDS sample is tied to one request_id."""
    return hashlib.sha256(('rg-goal:' + request_id).encode('utf-8')).hexdigest()[:32]


def payload_for_request(request_id, envelope):
    return request_id + '|' + ci.request_digest(envelope)


def _from_crypto():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey, Ed25519PublicKey)
    return serialization, Ed25519PrivateKey, Ed25519PublicKey


def gen_key(key_dir, issuer_id, force=False):
    key_dir = Path(key_dir)
    target_key = key_dir / KEY_NAME
    target_pub = key_dir / PUB_NAME
    target_trust = key_dir / TRUST_NAME
    if target_key.exists() and not force:
        raise LabError('key already exists (pass --force to replace): ' + str(target_key))
    key_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(key_dir, 0o700)
    serialization, Ed25519PrivateKey, _pub = _from_crypto()
    private = Ed25519PrivateKey.generate()
    public = private.public_key()
    key_pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption())
    pub_pem = public.public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo)
    fd = os.open(str(target_key), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'wb') as handle:
        handle.write(key_pem)
        handle.flush()
        os.fsync(handle.fileno())
    target_pub.write_bytes(pub_pem)
    os.chmod(target_pub, 0o644)
    der = public.public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo)
    fingerprint = hashlib.sha256(der).hexdigest()
    trust = {
        'contract': ci.ISSUER_CONTRACT_V2,
        'issuers': [{
            'id': issuer_id,
            'trust': ci.TRUST_VERIFIED,
            'scope': ci.SCOPE_LAB,
            'identity_source': 'LAB_DDS_INGRESS_WITNESS',
            'reviewed_by': 'LAB_SELF_REVIEW_TEST_ONLY',
            'public_key_sha256': fingerprint,
        }],
        'note': ('TEST_ONLY lab trust anchor. The identity source is a lab DDS ingress '
                 'witness on a separate research domain; it is not a production issuer.'),
    }
    target_trust.write_text(json.dumps(trust, ensure_ascii=False, indent=2) + '\n',
                            encoding='utf-8')
    os.chmod(target_trust, 0o600)
    return {'key': str(target_key), 'public_key': str(target_pub),
            'trusted_issuers': str(target_trust),
            'issuer_id': issuer_id, 'scope': ci.SCOPE_LAB,
            'public_key_sha256': fingerprint, 'test_only': True}


def load_private_key(path):
    _ser, _priv, _pub = _from_crypto()
    from cryptography.hazmat.primitives import serialization
    raw = Path(path).read_bytes()
    if b'PRIVATE KEY' not in raw:
        raise LabError('not a PEM private key: ' + str(path))
    key = serialization.load_pem_private_key(raw, password=None)
    _ser2, Ed25519PrivateKey, _pub2 = _from_crypto()
    if not isinstance(key, Ed25519PrivateKey):
        raise LabError('private key is not Ed25519')
    return key


def load_issuer(key_dir):
    key_dir = Path(key_dir)
    trust_path = key_dir / TRUST_NAME
    if not trust_path.is_file():
        raise LabError('trusted issuers file missing: ' + str(trust_path))
    document = ci.strict_json(trust_path.read_text(encoding='utf-8'))
    if document.get('contract') != ci.ISSUER_CONTRACT_V2:
        raise LabError('unsupported issuer contract')
    entries = [e for e in document.get('issuers') or [] if isinstance(e, dict)]
    if len(entries) != 1:
        raise LabError('lab trust file must contain exactly one issuer')
    entry = entries[0]
    if entry.get('scope') != ci.SCOPE_LAB:
        raise LabError('lab issuer must be LAB-scoped')
    return entry, trust_path


def read_ledger(path):
    raw = Path(path).read_bytes()
    if len(raw) > MAX_LEDGER:
        raise LabError('ledger too large')
    digest = hashlib.sha256(raw).hexdigest()
    rows = []
    for index, line in enumerate(raw.decode('utf-8', 'strict').splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = ci.strict_json(line)
        except ci.WitnessError as exc:
            raise LabError('ledger line {0} is not strict JSON: {1}'.format(index, exc))
        if isinstance(row, dict):
            row['__line__'] = index
            rows.append(row)
    return digest, rows


def find_event(rows, request_id, envelope_digest, *, max_age, now,
               require_goal_uuid=True):
    expected_goal = goal_uuid_for_request(request_id)
    candidates = []
    for row in rows:
        if row.get('contract') != 'trusted-action-events/1':
            continue
        if row.get('event_kind') != 'SEND_GOAL_RECEIVED':
            continue
        if row.get('sender_authenticated') is not True:
            continue
        if not str(row.get('certificate_subject') or '').strip():
            continue
        payload = row.get('payload')
        if not isinstance(payload, str) or '|' not in payload:
            continue
        rid, _, digest = payload.partition('|')
        if rid != request_id:
            continue
        if digest != envelope_digest:
            raise LabError('observed payload digest does not match the envelope')
        if require_goal_uuid and row.get('goal_uuid') != expected_goal:
            raise LabError('observed goal_uuid does not match the request convention')
        try:
            received = ci._rfc3339_to_epoch(row.get('received_at'))
        except ci.WitnessError:
            continue
        if now - received > max_age:
            continue
        if received - now > ci.MAX_CLOCK_SKEW_SEC:
            continue
        candidates.append(row)
    if not candidates:
        raise LabError('no fresh authenticated DDS observation for this request')
    candidates.sort(key=lambda item: item.get('__line__', 0))
    return candidates[-1], len(candidates)


def issue(key_dir, envelope_path, ledger_path, out_path, *, require_subject=None,
          nonce=None, max_event_age=120.0, now=None, require_goal_uuid=True):
    now = time.time() if now is None else float(now)
    entry, _trust_path = load_issuer(key_dir)
    private = load_private_key(Path(key_dir) / KEY_NAME)
    serialization, _priv, _pub = _from_crypto()
    public = private.public_key()
    der = public.public_bytes(serialization.Encoding.DER,
                              serialization.PublicFormat.SubjectPublicKeyInfo)
    if hashlib.sha256(der).hexdigest() != entry.get('public_key_sha256'):
        raise LabError('private key does not match the pinned public key')
    envelope = ci.strict_json(Path(envelope_path).read_text(encoding='utf-8'))
    request_id = envelope.get('request_id')
    if not isinstance(request_id, str) or not request_id or '|' in request_id:
        raise LabError('envelope request_id is missing or contains "|"')
    action = envelope.get('candidate_action') or {}
    digest = ci.request_digest(envelope)
    ledger_sha, rows = read_ledger(ledger_path)
    event, matches = find_event(rows, request_id, digest, max_age=max_event_age,
                                now=now, require_goal_uuid=require_goal_uuid)
    subject = event['certificate_subject']
    if require_subject and subject != require_subject:
        raise LabError('DDS-observed subject {0!r} != required {1!r}'.format(
            subject, require_subject))
    body = {
        'contract': ci.CONTRACT_ED25519,
        'issuer': {'id': entry['id'],
                   'identity_source': entry['identity_source'],
                   'assertion': 'LAB_DDS_INGRESS_OBSERVATION'},
        'request_id': request_id,
        'resource': action.get('action_resource'),
        'operation': action.get('operation'),
        'request_digest': digest,
        'received_at': utc_now(now),
        'nonce': nonce or secrets.token_hex(16),
        'evidence_kind': ci.EVIDENCE_KIND_SIGNED,
        'remote_identity': {'authenticated': True,
                            'security_identity': subject},
        'producer': {'name': 'identity_trust/lab_issuer.py',
                     'version': '1.0.0', 'scope': LAB,
                     'witness': 'M2_TRUSTED_DDS_INGRESS'},
        'witness': {
            'ledger_sha256': ledger_sha,
            'event_line': event.get('__line__'),
            'event_received_at': event.get('received_at'),
            'writer_guid': event.get('writer_guid'),
            'participant_guid': event.get('participant_guid'),
            'certificate_subject': subject,
            'matches': matches,
            'ingress_resource': event.get('resource'),
        },
    }
    signature = private.sign(ci.canonical(body)).hex()
    document = {'body': body,
                'signature': {'alg': 'ed25519', 'value': signature,
                              'key_sha256': entry['public_key_sha256']}}
    target = Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as handle:
        json.dump(document, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
    return {'attestation': str(target), 'request_id': request_id,
            'subject': subject, 'issuer': entry['id'], 'scope': ci.SCOPE_LAB,
            'matches': matches, 'ledger_sha256': ledger_sha,
            'test_only': True}


def verify(key_dir, envelope_path, attestation_path, *, nonce_ledger=None,
           allow_lab=False):
    entry, _trust_path = load_issuer(key_dir)
    envelope = ci.strict_json(Path(envelope_path).read_text(encoding='utf-8'))
    ledger = ci.Ledger(nonce_ledger) if nonce_ledger else None
    result = ci.verify(envelope, str(attestation_path),
                       str(Path(key_dir) / PUB_NAME),
                       issuers_path=str(Path(key_dir) / TRUST_NAME),
                       ledger=ledger,
                       ledger_error=None if ledger else 'verify-only invocation')
    return {'status': result.get('status'), 'trust_scope': result.get('trust_scope'),
            'checks': result.get('checks'), 'binding': result.get('binding'),
            'f0_accepts_lab': ci.f0_accepts(result, allow_lab=True),
            'f0_accepts_default': ci.f0_accepts(result, allow_lab=False),
            'reason': result.get('reason')}


def purge(key_dir):
    key_dir = Path(key_dir)
    removed = []
    if key_dir.is_dir():
        for name in (KEY_NAME, PUB_NAME, TRUST_NAME):
            path = key_dir / name
            if path.is_file():
                path.unlink()
                removed.append(str(path))
    return {'removed': removed}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--i-am-a-lab-issuer', action='store_true',
                        help='acknowledge that this is TEST_ONLY lab material')
    sub = parser.add_subparsers(dest='command', required=True)
    gen = sub.add_parser('gen-key')
    gen.add_argument('--key-dir', required=True)
    gen.add_argument('--issuer-id', default='lab-ed25519-ingress-1')
    gen.add_argument('--force', action='store_true')
    issue_p = sub.add_parser('issue')
    issue_p.add_argument('--key-dir', required=True)
    issue_p.add_argument('--envelope', required=True)
    issue_p.add_argument('--ledger', required=True)
    issue_p.add_argument('--out', required=True)
    issue_p.add_argument('--require-subject', default=None)
    issue_p.add_argument('--nonce', default=None)
    issue_p.add_argument('--max-event-age', type=float, default=120.0)
    ver = sub.add_parser('verify')
    ver.add_argument('--key-dir', required=True)
    ver.add_argument('--envelope', required=True)
    ver.add_argument('--attestation', required=True)
    ver.add_argument('--nonce-ledger', default=None)
    pur = sub.add_parser('purge')
    pur.add_argument('--key-dir', required=True)
    args = parser.parse_args(argv)
    if not args.i_am_a_lab_issuer:
        print('REFUSED: pass --i-am-a-lab-issuer to acknowledge TEST_ONLY lab scope',
              file=sys.stderr)
        return 2
    try:
        if args.command == 'gen-key':
            print(json.dumps({'test_only': True, **gen_key(
                args.key_dir, args.issuer_id, force=args.force)}, ensure_ascii=False))
        elif args.command == 'issue':
            print(json.dumps({'test_only': True, **issue(
                args.key_dir, args.envelope, args.ledger, args.out,
                require_subject=args.require_subject, nonce=args.nonce,
                max_event_age=args.max_event_age)}, ensure_ascii=False))
        elif args.command == 'verify':
            print(json.dumps({'test_only': True, **verify(
                args.key_dir, args.envelope, args.attestation,
                nonce_ledger=args.nonce_ledger)}, ensure_ascii=False))
        elif args.command == 'purge':
            print(json.dumps({'test_only': True, **purge(args.key_dir)},
                             ensure_ascii=False))
    except (LabError, ci.WitnessError, OSError, ValueError) as exc:
        print('LAB_ISSUER_ERROR: {0}'.format(str(exc)[:500]), file=sys.stderr)
        return 3
    return 0


if __name__ == '__main__':
    sys.exit(main())
