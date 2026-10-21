#!/usr/bin/env python3
"""Archive a SROS 2 lab run together with the non-secret material needed to read it.

Why this exists
---------------
The 1.0.3 archive of run `20261009T093144Z` kept the runtime logs but not the
generated DDS `permissions.xml`. Interpreting those logs therefore required a
keystore that had been wiped, and 13 evidence-interpretation tests failed on a
fresh checkout. Copying private keys into evidence is not an acceptable fix:
that would turn an evidence directory into an impersonation kit.

This tool archives exactly the non-secret half of the lab context:

  * the run tree (logs, summary.json, navsim/goal JSONL, audit JSONL);
  * each enclave's generated `permissions.xml` (default-DENY grants);
  * SHA-256 of the policy, the CA certificate, each permission file and each
    archived artifact;
  * the certificate subjects (public identities), the ROS/RMW/tool versions,
    the command, the exit code and the git commit.

It refuses to archive private keys, certificates with private keys, or a run
whose summary is not a passing domain-43 SROS 2 experiment.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_SUFFIXES = {'.key', '.pem', '.p7s', '.p12', '.pfx'}
FORBIDDEN_BYTES = (b'PRIVATE KEY',)


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def utc_now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def refuse(message):
    print('REFUSED: ' + message, file=sys.stderr)
    raise SystemExit(2)


def check_no_secrets(tree):
    for path in tree.rglob('*'):
        if not path.is_file():
            continue
        if path.suffix in FORBIDDEN_SUFFIXES:
            refuse('refusing to archive key/certificate material: ' + str(path))
        with open(path, 'rb') as handle:
            head = handle.read(4096)
        if any(marker in head for marker in FORBIDDEN_BYTES):
            refuse('refusing to archive private key bytes: ' + str(path))


def cert_subject(cert_path):
    try:
        out = subprocess.run(
            ['openssl', 'x509', '-in', str(cert_path), '-noout', '-subject',
             '-fingerprint', '-sha256'],
            capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    subject, fingerprint = None, None
    for line in out.stdout.splitlines():
        if line.startswith('subject='):
            subject = line[len('subject='):].strip()
        if 'Fingerprint=' in line:
            fingerprint = line.split('=', 1)[1].strip()
    return {'subject': subject, 'sha256_fingerprint': fingerprint}


def image_digest(image):
    try:
        out = subprocess.run(
            ['docker', 'image', 'inspect', image, '--format',
             '{{index .RepoDigests 0}}'],
            capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', required=True,
                        help='tests/evidence/<run-id> produced by sros2_check.py')
    parser.add_argument('--out-dir', required=True,
                        help='destination, e.g. artifacts/acceptance/exports/m2_sros2_enforce_v110')
    parser.add_argument('--keystore', default=str(ROOT / 'security' / 'keystore'))
    parser.add_argument('--policy', default=str(ROOT / 'security' / 'policies' /
                                                'minimal_permissions.xml'))
    parser.add_argument('--command', default='')
    parser.add_argument('--exit-code', type=int, default=0)
    parser.add_argument('--stdout-log', default=None,
                        help='optional captured stdout/stderr of the run')
    parser.add_argument('--image', default='rosystem-verify-1.0.3:latest')
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args(argv)

    run_dir = Path(args.run_dir).resolve()
    out_dir = Path(args.out_dir).resolve()
    keystore = Path(args.keystore).resolve()
    policy = Path(args.policy).resolve()
    if not run_dir.is_dir():
        refuse('run dir missing: ' + str(run_dir))
    if out_dir.exists():
        if not args.force:
            refuse('destination exists (pass --force to replace): ' + str(out_dir))
        shutil.rmtree(out_dir)
    summary_path = run_dir / 'summary.json'
    if not summary_path.is_file():
        refuse('run has no summary.json')
    summary = json.loads(summary_path.read_text(encoding='utf-8'))
    run_id = summary.get('run_id')
    contract = summary.get('contract') or 'sros2'
    if contract == 'dds-lab-negative/1':
        # Negative suite: every case is paired with a same-stack positive control;
        # the suite is only archivable when all cases pass.
        if summary.get('failed') != 0 or summary.get('passed') != summary.get('total'):
            refuse('negative suite is not fully passing; archive it as a failure')
    else:
        if summary.get('suite') != 'sros2':
            refuse('not a sros2 run')
        if summary.get('failed') != 0:
            refuse('run has failures; archive it as a failure, not as a passing run')
    if str(summary.get('secure_domain')) != '43':
        refuse('secure domain is not 43')
    if run_id != run_dir.name:
        refuse('summary run_id does not match directory name')

    check_no_secrets(run_dir)

    out_dir.mkdir(parents=True, exist_ok=True)
    run_target = out_dir / run_id
    shutil.copytree(run_dir, run_target, symlinks=False)

    permissions_dir = out_dir / 'keystore_permissions'
    permissions_dir.mkdir(parents=True, exist_ok=True)
    enclaves = {}
    for permission in sorted(keystore.glob('enclaves/*/permissions.xml')):
        name = permission.parent.name
        target = permissions_dir / name / 'permissions.xml'
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(permission, target)
        enclaves[name] = {
            'permissions_sha256': sha256(target),
            'permissions_path': str(target.relative_to(out_dir)),
            'default_deny': '<default>DENY</default>' in target.read_text(encoding='utf-8'),
            'domain_43': '<id>43</id>' in target.read_text(encoding='utf-8'),
        }
        cert = permission.parent / 'cert.pem'
        if cert.is_file():
            enclaves[name]['certificate'] = cert_subject(cert)
    if not enclaves:
        refuse('keystore has no generated permissions to archive')

    ca_cert = keystore / 'public' / 'ca.cert.pem'
    ca = cert_subject(ca_cert) if ca_cert.is_file() else None

    stdout_log = None
    if args.stdout_log and Path(args.stdout_log).is_file():
        payload = Path(args.stdout_log).read_bytes()
        if any(marker in payload for marker in FORBIDDEN_BYTES):
            refuse('stdout log contains private key bytes')
        target = out_dir / 'run_stdout.log'
        target.write_bytes(payload)
        stdout_log = {'path': target.name, 'sha256': sha256(target),
                      'bytes': len(payload)}

    files = {}
    for path in sorted(out_dir.rglob('*')):
        if path.is_file() and path.name != 'evidence_manifest.json':
            files[str(path.relative_to(out_dir))] = {
                'sha256': sha256(path), 'bytes': path.stat().st_size}
        elif path.is_file() and path.name == 'evidence_manifest.json':
            continue
    check_no_secrets(out_dir)

    git_head = None
    git_dirty = None
    try:
        git_head = subprocess.run(
            ['git', '-C', str(ROOT), 'rev-parse', 'HEAD'],
            capture_output=True, text=True, timeout=15).stdout.strip() or None
        porcelain = subprocess.run(
            ['git', '-C', str(ROOT), 'status', '--porcelain'],
            capture_output=True, text=True, timeout=15).stdout
        git_dirty = bool(porcelain.strip())
    except (OSError, subprocess.SubprocessError):
        pass

    manifest = {
        'contract': 'dds-lab-evidence/1',
        'scope': 'TEST_ONLY_LAB',
        'run_id': run_id,
        'archived_at': utc_now(),
        'command': args.command,
        'exit_code': args.exit_code,
        'normal_domain': summary.get('normal_domain'),
        'secure_domain': summary.get('secure_domain'),
        'total': summary.get('total'),
        'passed': summary.get('passed'),
        'failed': summary.get('failed'),
        'policy': {'path': str(policy.relative_to(ROOT)) if policy.is_relative_to(ROOT)
                   else str(policy), 'sha256': sha256(policy)},
        'ca_certificate': ca,
        'enclaves': enclaves,
        'secrets_included': False,
        'certificates_are_public_only': True,
        'private_key_policy': ('keystore private keys are never copied; the archive is '
                               'not usable to impersonate any participant'),
        'git_head': git_head,
        'git_worktree_dirty': git_dirty,
        'host': {'uname': os.uname().sysname + ' ' + os.uname().release},
        'image': {'name': args.image, 'digest': image_digest(args.image)},
        'run_stdout': stdout_log,
        'files': files,
        'note': ('permissions.xml are policy-derived, non-secret artifacts included so the '
                 'run can be interpreted without the wiped keystore; they are NOT the '
                 '2026-10-09 historical evidence'),
    }
    target = out_dir / 'evidence_manifest.json'
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n',
                      encoding='utf-8')
    print(json.dumps({'archive': str(out_dir), 'run_id': run_id,
                      'passed': summary.get('passed'), 'total': summary.get('total'),
                      'files': len(files), 'manifest_sha256': sha256(target)},
                     ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
