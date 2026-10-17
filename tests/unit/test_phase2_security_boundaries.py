"""第二阶段安全边界：F0 对身份自报的信任、Mock/受控测试隔离。

本文件同时承担两个职责
======================
1. **已修好的边界**用普通断言长期守住（M2 侧永不输出裸 AUTHENTICATED、
   受控 flag 只出现在受控配置、M1 的 MOCK 观测换不来 NORMAL 等）。
2. **尚未修好的边界**用 `xfail` 记录成可执行的反例，明确责任人（B1）。
   xfail 采用非严格模式，避免 B1 修好 F0 时把他们的 CI 直接打红；
   交接文件里写明"修复后请把这些用例改成普通断言"。

第二批（P0-2）的结论：F0 当前只比较 `extensions.current_request_identity.status`
字符串，因此"模块自己写一个 AUTHENTICATED"就能通过。这不是 M2 的缺陷，
而是适配层的信任边界过宽——修复归 B1。
"""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest
import yaml

pytest.importorskip('jsonschema', reason='需要 jsonschema>=4.0（Draft 2020-12）')

ROOT = Path(__file__).resolve().parents[2]
for extra in (ROOT, ROOT / 'scripts', ROOT / 'tests' / 'unit'):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import team_demo  # noqa: E402
from test_identity_trust_assessor import sample  # noqa: E402,F401  (fixture)
from test_team_process_protocol import (  # noqa: E402
    envelope, proceed_control, run_adapter, write_config)

CONFIG_DIR = ROOT / 'config'
CONTROLLED_CONFIG = CONFIG_DIR / 'team_modules.all-real.controlled-test.yaml'
ALL_REAL_CONFIG = CONFIG_DIR / 'team_modules.all-real.yaml'

#: 一个"自己声称身份已认证"的模块：除了状态字符串什么都没有。
SELF_REPORTING_IDENTITY = '''\
import json, sys, uuid
from datetime import datetime, timezone
inherited = json.loads(sys.stdin.read())
document = {
    "schema_version": "1.0.0-proposed",
    "run_id": inherited["run_id"],
    "request_id": inherited["request_id"],
    "event_id": "evt-selfreport-" + uuid.uuid4().hex,
    "producer": {"name": "self-reporting-identity", "module_version": "0.0.1",
                 "source": "EXTERNAL"},
    "observed_at": datetime.now(timezone.utc).isoformat(),
    "status": "AUTHORIZED",
    "reason": "self reported",
    "subject": {"observed_name": "planner_node"},
    "requested_resource": {"resource": "/rg/guarded_navigate",
                           "operation": "SERVICE_REQUEST"},
    "authorization": {"result_status": "AUTHORIZED", "denial_layer": "NONE"},
    "identity_evidence": {"kind": "UNKNOWN"},
    "access_control_evidence": {"kind": "NONE"},
    "evidence_refs": [{"ref": "self-report", "kind": "UNKNOWN"}],
    "extensions": {"current_request_identity": {
        "status": "AUTHENTICATED",
        "evidence_kind": "SIGNED_ATTESTATION",
        "binding": "CURRENT_REQUEST_BOUND_TO_AUTHENTICATED_DDS_SUBJECT",
        "historical_only": False}},
}
print(json.dumps(document))
'''


def _identity_module(tmp_path, body):
    module = tmp_path / 'identity_{0}.py'.format(uuid.uuid4().hex[:8])
    module.write_text(body, encoding='utf-8')
    return module


def _run_with_identity(tmp_path, module):
    config = write_config(tmp_path, mode='mock',
                          commands={'identity_trust': [sys.executable, str(module)]})
    return run_adapter(tmp_path, envelope(proceed_control()), config)


# ---------------------------------------------------------------- 已知缺口（B1）
@pytest.mark.xfail(reason=('P0-2 open: F0 仅比较 status 字符串，缺少对证据种类/签发者/'
                           '绑定的核验；修复责任人 B1（scripts/team_demo.py）。'
                           '修复后请把本用例改成普通断言。'),
                   strict=False)
def test_f0_rejects_bare_status_self_report(tmp_path):
    """没有签名、没有签发者、没有账本的"AUTHENTICATED"不应让 F0 推进。"""
    code, result, _err = _run_with_identity(
        tmp_path, _identity_module(tmp_path, SELF_REPORTING_IDENTITY))
    assert result['decision'] == 'ADAPTER_BLOCK', result
    assert result['reason_code'] == 'ADAPTER_CURRENT_IDENTITY_UNBOUND'


@pytest.mark.xfail(reason=('P0-2 open: mock 的 MOCK_FIXTURE 身份与真实签名证据在 F0 眼里'
                           '没有区别；修复责任人 B1。修复后改成普通断言。'),
                   strict=False)
def test_f0_rejects_mock_fixture_identity(tmp_path):
    """Mock 自报的身份不得让 F0 在"真实模式"下推进。"""
    config = write_config(tmp_path, mode='mock')
    _code, result, _err = run_adapter(tmp_path, envelope(proceed_control()), config)
    assert result['decision'] == 'ADAPTER_BLOCK', result


# ---------------------------------------------------------------- M2 侧已守住
def test_m2_never_emits_bare_authenticated(sample, tmp_path):
    """真实 M2：无证据 -> UNKNOWN；TEST_ONLY 签发者 -> AUTHENTICATED_TEST_ONLY。

    两种路径都**不得**出现裸 `AUTHENTICATED`——那会绕过签发者信任判定。
    """
    from test_identity_current_binding import (TEST_ONLY_ISSUER, make_issuers,
                                               make_key, mint, options)
    from identity_trust import current_identity as ci
    _opts, env, _ = sample

    plain = assessment_of(env, options(sample))
    assert plain['extensions']['current_request_identity']['status'] == ci.STATUS_UNKNOWN

    key = make_key(tmp_path / 'w.key')
    witness, _body = mint(tmp_path, key, env, issuer_id=TEST_ONLY_ISSUER)
    issuers = make_issuers(tmp_path / 'issuers.json', ci.TRUST_TEST_ONLY,
                           TEST_ONLY_ISSUER)
    test_only = assessment_of(env, options(
        sample, witness=str(witness), key=str(key), issuers=str(issuers),
        ledger=str(tmp_path / 'ledger.jsonl')))
    current = test_only['extensions']['current_request_identity']
    assert current['status'] == ci.STATUS_TEST_ONLY
    assert ci.f0_accepts(current) is False
    assert current['status'] != 'AUTHENTICATED'


def assessment_of(env, namespace):
    from identity_trust.assessor import assessment
    return assessment(env, namespace)


def test_m2_output_always_carries_verification_metadata(sample):
    """无论结论如何，输出都必须带 checks/verifier/attestation，便于事后复核。"""
    from test_identity_current_binding import options
    _opts, env, _ = sample
    out = assessment_of(env, options(sample))
    current = out['extensions']['current_request_identity']
    assert set(current['checks']) == {'signature', 'issuer', 'request_binding',
                                      'freshness', 'replay'}
    assert current['verifier']['contract']
    assert current['historical_only'] is False
    assert current['status'] != 'AUTHENTICATED'


def test_f0_accepts_predicate_is_strict():
    """B1 应改用这个谓词，而不是比较裸字符串。"""
    from identity_trust import current_identity as ci
    good = {'status': ci.STATUS_AUTHENTICATED,
            'evidence_kind': ci.EVIDENCE_KIND_SIGNED,
            'historical_only': False,
            'checks': {'signature': 'VALID', 'issuer': ci.TRUST_VERIFIED,
                       'request_binding': 'MATCH', 'freshness': 'OK',
                       'replay': 'RESERVED'}}
    assert ci.f0_accepts(good) is True
    for mutation in ({'status': ci.STATUS_TEST_ONLY},
                     {'evidence_kind': 'MOCK_FIXTURE'},
                     {'historical_only': True},
                     {'checks': dict(good['checks'], replay='REPLAYED')},
                     {'checks': dict(good['checks'], issuer='NOT_LISTED')},
                     {'checks': dict(good['checks'], signature='INVALID')},
                     {'checks': None}):
        candidate = dict(good)
        candidate.update(mutation)
        assert ci.f0_accepts(candidate) is False, mutation
    assert ci.f0_accepts(None) is False
    assert ci.f0_accepts({'status': 'AUTHENTICATED'}) is False


# ---------------------------------------------------------------- 配置隔离
def _config_documents():
    for path in sorted(CONFIG_DIR.glob('*.yaml')):
        yield path, yaml.safe_load(path.read_text(encoding='utf-8')) or {}


def test_controlled_test_flag_only_in_marked_places():
    """`--controlled-test` 只允许出现在两处：

    1. 文件名标记为 `*.controlled-test.yaml` 的**模块命令**里；
    2. 任意配置中**明确命名为 controlled_test 的 real_command_profiles 档案**里
       （档案只有在验收 fixture 显式引用时才生效，且不属于在线命令）。
    """
    offenders = []
    for path, document in _config_documents():
        for name, entry in (document.get('modules') or {}).items():
            command = (entry or {}).get('command') or []
            if '--controlled-test' in command and '.controlled-test.' not in path.name:
                offenders.append('{0}: modules.{1}.command'.format(path.name, name))
        for profile, entry in (document.get('real_command_profiles') or {}).items():
            if not isinstance(entry, dict):
                continue
            args = entry.get('args') or []
            command = entry.get('command') or []
            if '--controlled-test' in args or '--controlled-test' in command:
                if 'controlled_test' not in profile:
                    offenders.append('{0}: profile {1}'.format(path.name, profile))
    assert not offenders, offenders
    assert CONTROLATED_FLAG_PRESENT_IN_THE_CONTROLLED_CONFIG()


def CONTROLATED_FLAG_PRESENT_IN_THE_CONTROLLED_CONFIG():
    document = yaml.safe_load(CONTROLLED_CONFIG.read_text(encoding='utf-8'))
    return '--controlled-test' in document['modules']['comm_risk']['command']


def test_joint_real_config_uses_no_mock_modules():
    """三真实模块配置里不得出现任何 mock 入口。"""
    document = yaml.safe_load(ALL_REAL_CONFIG.read_text(encoding='utf-8'))
    for name, entry in document['modules'].items():
        assert entry['mode'] == 'external', (name, entry['mode'])
        assert not any('mock_modules' in part for part in entry['command']), name


def test_member1_real_config_keeps_others_mock_and_declares_it():
    """M1 真实化配置显式保留其余两位 Mock，且不做隐式降级。"""
    document = yaml.safe_load(
        (CONFIG_DIR / 'team_modules.member1.real.yaml').read_text(encoding='utf-8'))
    assert document['modules']['comm_risk']['mode'] == 'external'
    assert document['modules']['identity_trust']['mode'] == 'mock'
    assert document['modules']['task_risk']['mode'] == 'mock'


def test_mock_identity_marks_itself_as_fixture(tmp_path):
    """Mock 必须自报 MOCK_FIXTURE，否则下游无法区分"模拟"与"真实签名证据"。"""
    import subprocess
    proc = subprocess.run(
        [sys.executable, 'mock_modules/identity_trust_mock.py'],
        input=json.dumps(envelope(proceed_control())), capture_output=True,
        text=True, cwd=str(ROOT), timeout=60)
    assert proc.returncode == 0, proc.stderr[-400:]
    document = json.loads(proc.stdout)
    current = document['extensions']['current_request_identity']
    assert current['status'] == 'AUTHENTICATED'
    assert current['evidence_kind'] == 'MOCK_FIXTURE'


def test_adapter_audit_records_mode_so_mock_is_visible(tmp_path):
    """审计必须留下 mode，使"这次 READY 是 mock 撑起来的"可事后识别。"""
    config = write_config(tmp_path, mode='mock')
    _code, result, _err = run_adapter(tmp_path, envelope(proceed_control()), config)
    modes = {row['module']: row['mode'] for row in result['modules']}
    assert set(modes.values()) == {'mock'}
    log = (tmp_path / 'adapter.jsonl').read_text(encoding='utf-8').strip().splitlines()
    assert log and json.loads(log[0])['modules']


def test_m1_controlled_test_ready_is_auditable(tmp_path):
    """受控测试下 M1 给出 NORMAL 时，审计里必须能看到 controlled_test=true。

    否则一次"看起来像真实在线"的 READY 无法事后辨认，正是 P0-3 的关切。
    """
    from test_member1_adapter_integration import (config_with_real_comm,
                                                  probe, real_envelope)
    config = config_with_real_comm(tmp_path, '--controlled-test')
    _code, result, _err = run_adapter(tmp_path, real_envelope(probe('below')), config)
    assert result['decision'] == 'READY_FOR_GATEWAY_SUBMISSION', result
    log = (tmp_path / 'adapter.jsonl').read_text(encoding='utf-8').strip().splitlines()
    joined = '\n'.join(log)
    assert '--controlled-test' in joined      # 命令本身留痕
    assert '"mode": "mock"' in joined or "'mode': 'mock'" in joined
