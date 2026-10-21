#!/usr/bin/env python3
"""Gateway-side, independent verification of the current-request attestation.

Why the Gateway checks again
----------------------------
F0 consuming an attestation does not make the Gateway's decision: F0 decides
whether the request may be *submitted*, while the Gateway decides whether it may
be *executed*. The two layers must remain independent, so the Gateway re-checks
the signed statement it is given for this exact goal (request_id, resource,
operation, task_id, target) against its own trust anchor and its own nonce cache.

The attestation is delivered through a side channel keyed by request_id because
the frozen Action interface has no field for signatures. The file is read with
the same hardened loader as the verifier (regular file, no symlink, size limit);
a request_id containing path separators is rejected before touching the file.

If `attestation_dir` is empty the gate is disabled and the Gateway behaves as in
1.0.3 (TaskPolicy only). Enabling it never falls back silently: any missing,
unreadable, mismatched or replayed attestation blocks the goal.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

_SAFE_REQUEST_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$')
GUARDED_ACTION = '/rg/guarded_navigate'
OPERATION = 'NAVIGATE'


def _bootstrap():
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / 'identity_trust' / 'current_identity.py').is_file():
            if str(parent) not in sys.path:
                sys.path.insert(0, str(parent))
            return parent
    return None


ROOT = _bootstrap()

BLOCK = 'BLOCK'
ALLOW = 'ALLOW'
DISABLED = 'DISABLED'
REASON_REJECTED = 'IDENTITY_ATTESTATION_REJECTED'
REASON_CONFIG = 'IDENTITY_ATTESTATION_CONFIG_INVALID'


def envelope_for_goal(goal):
    """Reconstruct exactly the fields covered by `request_digest`."""
    target = getattr(goal, 'target', None)
    header = getattr(target, 'header', None)
    position = getattr(getattr(target, 'pose', None), 'position', None)
    return {
        'request_id': str(getattr(goal, 'request_id', '')),
        'candidate_action': {
            'action_resource': GUARDED_ACTION,
            'operation': OPERATION,
            'task_id': str(getattr(goal, 'task_id', '')),
            'target': {
                'frame_id': str(getattr(header, 'frame_id', '') or ''),
                'x': float(getattr(position, 'x', 0.0)),
                'y': float(getattr(position, 'y', 0.0)),
                'z': float(getattr(position, 'z', 0.0)),
            },
        },
    }


def verify_goal(goal, *, attestation_dir, public_key, issuers_path, ledger_path,
                allow_lab_scope=False, now=None):
    """Return a JSON-serialisable decision; never raises for malformed input."""
    request_id = str(getattr(goal, 'request_id', ''))
    base = {'enabled': True, 'request_id': request_id[:128], 'decision': BLOCK,
            'verified': False, 'status': None, 'scope': None,
            'reason_code': REASON_REJECTED, 'reason': None, 'checks': None}
    if not attestation_dir:
        return {'enabled': False, 'decision': DISABLED, 'verified': False,
                'request_id': request_id[:128],
                'reason': 'gateway identity gate not configured'}
    if not _SAFE_REQUEST_ID.fullmatch(request_id):
        base['reason'] = 'request_id is not safe to use as a filename'
        return base
    for label, value in (('public_key', public_key), ('issuers_path', issuers_path),
                         ('ledger_path', ledger_path)):
        if not isinstance(value, str) or not value:
            base['reason_code'] = REASON_CONFIG
            base['reason'] = 'identity gate missing ' + label
            return base
    directory = Path(attestation_dir).resolve()
    candidate = (directory / (request_id + '.json')).resolve()
    if candidate.parent != directory:
        base['reason'] = 'attestation path escapes the configured directory'
        return base
    if not candidate.is_file() or candidate.is_symlink():
        base['reason'] = 'no attestation for this request_id'
        return base
    if ROOT is None:
        base['reason'] = 'identity_trust verifier not importable'
        return base
    from identity_trust import current_identity as ci
    try:
        ledger = ci.Ledger(ledger_path)
        envelope = envelope_for_goal(goal)
        result = ci.verify(envelope, str(candidate), public_key,
                           issuers_path=issuers_path, ledger=ledger, now=now)
    except Exception as exc:  # noqa: BLE001 - fail closed, record the class only
        base['reason'] = 'verifier exception: ' + type(exc).__name__
        return base
    accepted = ci.f0_accepts(result, allow_lab=allow_lab_scope)
    base.update({
        'verified': accepted,
        'status': result.get('status'),
        'scope': result.get('trust_scope'),
        'checks': result.get('checks'),
        'binding': result.get('binding'),
        'attestation_sha256': _sha256_file(candidate),
    })
    if accepted:
        base['decision'] = ALLOW
        base['reason_code'] = None
        base['reason'] = ('attestation verified at the gateway'
                          + (' (LAB scope)' if result.get('trust_scope') == 'LAB' else ''))
    else:
        base['reason'] = str(result.get('reason') or 'attestation rejected')[:400]
    return base


def _sha256_file(path):
    import hashlib
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(65536), b''):
            digest.update(chunk)
    return digest.hexdigest()
