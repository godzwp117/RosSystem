"""Shared pytest setup for the unit tests.

Makes ``rg_policy`` importable directly from ``src/`` so the pure-Python core can
be tested even without a colcon build or a sourced ROS environment. When the
workspace *is* built and sourced, the installed copy is used instead -- either
way the assertions are identical.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, 'src')

for package in ('rg_policy',):
    candidate = os.path.join(SRC, package)
    if os.path.isdir(candidate) and candidate not in sys.path:
        sys.path.insert(0, candidate)

WORKSPACE_ROOT = ROOT
CONFIG_DIR = os.path.join(ROOT, 'config')
SCENARIO_CONFIG_DIR = os.path.join(CONFIG_DIR, 'scenarios')
DEFAULT_POLICY_PATH = os.path.join(CONFIG_DIR, 'task_policy.yaml')
ACTION_FILE = os.path.join(SRC, 'rg_interfaces', 'action', 'PatrolNavigate.action')


def _materialize_permissions_fixture():
    """Make the permissions-only lab fixture available as ``security/keystore``.

    Why this exists
    ---------------
    ``tests/unit/test_identity_trust_real_logs.py`` interprets the archived SROS 2
    run 20261009T093144Z. Interpreting it requires the *generated* DDS
    ``permissions.xml`` for each enclave, because the assessor refuses to conclude
    anything from a runtime log unless the generated permissions can be compared
    with the source policy. The real keystore is deliberately git-ignored (it holds
    private keys) and is wiped after every experiment, so a fresh checkout had no
    permissions at all and 13 evidence-interpretation tests failed.

    This hook restores only the non-secret ``permissions.xml`` files from
    ``tests/fixtures/sros2_lab_permissions`` (produced by the real sros2 0.13.6
    toolchain from the same policy). It never creates keys, never overwrites a
    real keystore, and marks the directory so the Enforce scripts can tell it
    apart from a usable lab CA.

    A real Enforce run still requires ``scripts/setup_sros2.sh``; a permissions
    fixture without ``public/ca.cert.pem`` cannot start a secure participant.
    """
    if os.environ.get('RG_DISABLE_LAB_PERMISSIONS_FIXTURE') == '1':
        return
    keystore = os.path.join(ROOT, 'security', 'keystore')
    fixture = os.path.join(ROOT, 'tests', 'fixtures', 'sros2_lab_permissions')
    if os.path.isfile(os.path.join(keystore, 'public', 'ca.cert.pem')):
        return  # real lab CA present -- leave it untouched
    source_enclaves = os.path.join(fixture, 'enclaves')
    if not os.path.isdir(source_enclaves):
        return
    for name in sorted(os.listdir(source_enclaves)):
        source = os.path.join(source_enclaves, name, 'permissions.xml')
        target_dir = os.path.join(keystore, 'enclaves', name)
        target = os.path.join(target_dir, 'permissions.xml')
        if not os.path.isfile(source):
            continue
        os.makedirs(target_dir, exist_ok=True)
        if not os.path.exists(target):
            with open(source, 'rb') as handle:
                payload = handle.read()
            with open(target, 'wb') as handle:
                handle.write(payload)
    marker = os.path.join(keystore, 'FIXTURE_ONLY_NO_PRIVATE_KEYS')
    if not os.path.exists(marker):
        with open(marker, 'w', encoding='utf-8') as handle:
            handle.write('permissions-only fixture from tests/fixtures/sros2_lab_permissions\n'
                         'no private keys; not usable for a DDS Enforce participant\n')


def pytest_sessionstart(session):  # noqa: ARG001 - pytest hook signature
    _materialize_permissions_fixture()
