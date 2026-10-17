"""成员二：历史证据解释与**当前请求身份绑定**的分离。

本文件验证的核心安全命题
------------------------
1. 历史受控实验的 AUTHORIZED **不等于**当前请求已通过 DDS 身份认证。
2. 业务 JSON 自报的 enclave / 节点名 / request_id 都不能被提升为已认证身份。
3. 没有可信证据时当前身份恒为 UNKNOWN（失败关闭）。
4. 一旦（未来）有可信组件产出带签名的绑定证据，核验器能识别：
   签名篡改、串单（request_id 错绑）、跨资源复用、时间过期、nonce 重放。
5. F0 适配层要求 `extensions.current_request_identity.status == AUTHENTICATED`
   才允许推进；历史授权不足以推进。
"""
from __future__ import annotations

import json
import time
import uuid
from argparse import Namespace
from pathlib import Path

import pytest

import sys

ROOT = Path(__file__).resolve().parents[2]
for extra in (ROOT, ROOT / 'scripts', ROOT / 'tests' / 'unit'):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from identity_trust import current_identity as ci  # noqa: E402
from identity_trust.assessor import assessment  # noqa: E402
from test_identity_trust_assessor import sample  # noqa: E402,F401  (fixture)
from test_team_process_protocol import (  # noqa: E402
    envelope, proceed_control, run_adapter, write_config)

import validate_team_contracts as vtc  # noqa: E402


# ---------------------------------------------------------------- 工具
def options(sample_tuple, *, witness=None, key=None, ledger=None, case=None):
    opts, _env, _run_dir = sample_tuple
    merged = dict(opts)
    merged.update({'identity_witness': witness,
                   'identity_witness_key': key,
                   'identity_ledger': ledger})
    if case:
        merged['case'] = case
    return Namespace(**merged)


def mint_witness(tmp_path, envelope_document, *, overrides=None, key=None):
    """构造一条**测试用**签名证据（模拟未来可信产生组件的输出）。"""
    key = key or (tmp_path / 'witness.key')
    if not key.exists():
        key.write_bytes(uuid.uuid4().hex.encode('ascii'))
    body = {
        'contract': ci.CONTRACT,
        'request_id': envelope_document['request_id'],
        'resource': envelope_document['candidate_action']['action_resource'],
        'operation': envelope_document['candidate_action']['operation'],
        'received_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'nonce': uuid.uuid4().hex,
        'evidence_kind': ci.EVIDENCE_KIND,
        'remote_identity': {'authenticated': True,
                            'security_identity': 'sros2://test-domain/planner'},
        'producer': {'name': 'test-witness', 'api': 'TEST_ONLY'},
    }
    body.update(overrides or {})
    document = {'body': body,
                'signature': {'alg': 'hmac-sha256',
                              'value': ci.sign(body, ci.load_key(str(key)))}}
    path = tmp_path / 'witness.json'
    path.write_text(json.dumps(document), encoding='utf-8')
    return path, key


# ---------------------------------------------------------------- 语义分离
def test_historical_authorized_is_not_current_identity(sample):
    """S2 历史授权成功 -> 顶层 AUTHORIZED，但当前身份仍是 UNKNOWN。"""
    opts, env, _ = sample
    out = assessment(env, options(sample))
    assert out['status'] == 'AUTHORIZED'
    assert out['extensions']['historical_only'] is True
    current = out['extensions']['current_request_identity']
    assert current['status'] == 'UNKNOWN'
    assert current['evidence_kind'] == 'NONE'
    assert current['historical_only'] is False
    assert 'NO_MIDDLEWARE_IDENTITY_API' in current['producer'] or \
        'NOT_IMPLEMENTED' in current['producer']
    # 输出仍必须符合公共契约
    assert not vtc.validate_document(out, vtc.load_schema('identity_trust_assessment'))


def test_self_reported_identity_never_authenticates(sample):
    """业务 JSON 里自报 enclave/节点名/身份，不能被当作认证成功。"""
    opts, env, _ = sample
    env = json.loads(json.dumps(env))
    env['observations'][0]['detail'] = {
        'identity': {'subject': 'planner_node', 'resource': '/rg/guarded_navigate'},
        'declared_enclave': '/planner',
        'authenticated_identity': 'sros2://forged',
        'current_identity': {'status': 'AUTHENTICATED'},
    }
    out = assessment(env, options(sample))
    current = out['extensions']['current_request_identity']
    assert current['status'] == 'UNKNOWN'
    assert 'authenticated_identity' not in out['subject']


def test_replay_ledger_detects_historical_authorization_reuse(sample, tmp_path):
    """同一份历史证据被重复解释 -> 第二次判定为历史授权复用并阻断。"""
    _opts, env, _ = sample
    ledger = tmp_path / 'ledger.jsonl'
    first = assessment(env, options(sample, ledger=ledger))
    assert first['status'] == 'AUTHORIZED'
    assert first['extensions']['historical_authorization_reuse_detected'] is False
    second = assessment(env, options(sample, ledger=ledger))
    assert second['status'] == 'UNKNOWN'
    assert second['extensions']['historical_authorization_reuse_detected'] is True
    assert second['extensions']['current_request_binding'] == 'HISTORICAL_AUTHORIZATION_REUSE'


# ---------------------------------------------------------------- 证据核验
def test_signed_witness_authenticates_current_request(tmp_path):
    env = envelope(proceed_control())
    witness, key = mint_witness(tmp_path, env)
    result = ci.verify(env, str(witness), str(key), now=time.time())
    assert result['status'] == 'AUTHENTICATED'
    assert result['evidence_kind'] == ci.EVIDENCE_KIND
    assert result['historical_only'] is False


def test_tampered_witness_is_rejected(tmp_path):
    env = envelope(proceed_control())
    witness, key = mint_witness(tmp_path, env)
    document = json.loads(witness.read_text(encoding='utf-8'))
    document['body']['remote_identity']['security_identity'] = 'sros2://attacker'
    witness.write_text(json.dumps(document), encoding='utf-8')
    result = ci.verify(env, str(witness), str(key), now=time.time())
    assert result['status'] == 'UNKNOWN'
    assert 'signature' in result['reason']


def test_witness_for_other_request_is_rejected(tmp_path):
    env = envelope(proceed_control())
    other = envelope(proceed_control(), request_id='req-someone-else')
    witness, key = mint_witness(tmp_path, other)
    result = ci.verify(env, str(witness), str(key), now=time.time())
    assert result['status'] == 'UNKNOWN'
    assert result['binding'] == 'WITNESS_REQUEST_ID_MISMATCH'


def test_witness_for_other_resource_is_rejected(tmp_path):
    env = envelope(proceed_control())
    witness, key = mint_witness(
        tmp_path, env, overrides={'resource': '/rg/nav_execute'})
    result = ci.verify(env, str(witness), str(key), now=time.time())
    assert result['status'] == 'UNKNOWN'
    assert result['binding'] == 'WITNESS_RESOURCE_MISMATCH'


def test_stale_witness_is_rejected(tmp_path):
    env = envelope(proceed_control())
    witness, key = mint_witness(tmp_path, env)
    result = ci.verify(env, str(witness), str(key),
                       now=time.time() + ci.MAX_REMOTE_AGE_SEC + 5)
    assert result['status'] == 'UNKNOWN'
    assert result['binding'] == 'WITNESS_STALE'


def test_replayed_nonre_is_rejected(tmp_path):
    env = envelope(proceed_control())
    witness, key = mint_witness(tmp_path, env)
    ledger = ci.Ledger(str(tmp_path / 'nonce-ledger.jsonl'))
    first = ci.verify(env, str(witness), str(key), ledger=ledger, now=time.time())
    assert first['status'] == 'AUTHENTICATED'
    ledger = ci.Ledger(str(tmp_path / 'nonce-ledger.jsonl'))
    second = ci.verify(env, str(witness), str(key), ledger=ledger, now=time.time())
    assert second['status'] == 'UNKNOWN'
    assert second['binding'] == 'WITNESS_NONCE_REPLAYED'


def test_unauthenticated_remote_identity_is_denied(tmp_path):
    env = envelope(proceed_control())
    witness, key = mint_witness(
        tmp_path, env, overrides={'remote_identity': {'authenticated': False}})
    result = ci.verify(env, str(witness), str(key), now=time.time())
    assert result['status'] == 'DENIED'


def test_wrong_evidence_kind_is_rejected(tmp_path):
    env = envelope(proceed_control())
    witness, key = mint_witness(
        tmp_path, env, overrides={'evidence_kind': 'SELF_REPORTED'})
    result = ci.verify(env, str(witness), str(key), now=time.time())
    assert result['status'] == 'UNKNOWN'
    assert 'evidence kind' in result['reason']


# ---------------------------------------------------------------- F0 语义
UNBOUND_MODULE = '''import json, sys, uuid
from datetime import datetime, timezone
inherited = json.loads(sys.stdin.read())
document = {
    "schema_version": "1.0.0-proposed",
    "run_id": inherited["run_id"],
    "request_id": inherited["request_id"],
    "event_id": "evt-unbound-" + uuid.uuid4().hex,
    "producer": {"name": "unbound-identity", "module_version": "0.0.1",
                 "source": "EXTERNAL"},
    "observed_at": datetime.now(timezone.utc).isoformat(),
    "status": "AUTHORIZED",
    "reason": "历史受控实验授权成功",
    "subject": {"observed_name": "planner_node"},
    "requested_resource": {"resource": "/rg/guarded_navigate",
                           "operation": "SERVICE_REQUEST"},
    "authorization": {"result_status": "AUTHORIZED", "denial_layer": "NONE"},
    "identity_evidence": {"kind": "CONTROLLED_SECURITY_EXPERIMENT"},
    "access_control_evidence": {"kind": "NONE"},
    "evidence_refs": [{"ref": "archived-experiment", "kind":
                       "CONTROLLED_SECURITY_EXPERIMENT"}],
    "extensions": {"historical_only": True,
                   "current_request_identity": {
                       "status": "__CURRENT_STATUS__",
                       "evidence_kind": "__CURRENT_KIND__",
                       "binding": "__CURRENT_BINDING__",
                       "historical_only": False}},
}
print(json.dumps(document))
'''


def write_identity_module(tmp_path, name, status, kind, binding):
    module = tmp_path / name
    module.write_text(
        UNBOUND_MODULE.replace('__CURRENT_STATUS__', status)
        .replace('__CURRENT_KIND__', kind)
        .replace('__CURRENT_BINDING__', binding), encoding='utf-8')
    return module


def test_f0_blocks_historical_authorized_without_current_binding(tmp_path):
    """顶层 AUTHORIZED + 当前身份 UNKNOWN -> 适配层必须阻断。"""
    module = write_identity_module(
        tmp_path, 'unbound_identity.py', 'UNKNOWN', 'NONE',
        'UNBOUND_NO_TRUSTED_CURRENT_IDENTITY_WITNESS')
    config = write_config(tmp_path, mode='mock',
                          commands={'identity_trust': [sys.executable, str(module)]})
    _code, result, _err = run_adapter(tmp_path, envelope(proceed_control()), config)
    assert result['decision'] == 'ADAPTER_BLOCK'
    assert result['reason_code'] == 'ADAPTER_CURRENT_IDENTITY_UNBOUND'
    record = next(r for r in result['modules'] if r['module'] == 'identity_trust')
    assert record['schema_ok'] is True
    assert record['status'] == 'AUTHORIZED'


def test_f0_ready_when_identity_reports_current_binding(tmp_path):
    """当前身份 AUTHENTICATED 时同一份输出才可能推进（模拟模块）。"""
    module = write_identity_module(
        tmp_path, 'bound_identity.py', 'AUTHENTICATED', 'MOCK_FIXTURE', 'TEST_BOUND')
    config = write_config(tmp_path, mode='mock',
                          commands={'identity_trust': [sys.executable, str(module)]})
    _code, result, _err = run_adapter(tmp_path, envelope(proceed_control()), config)
    assert result['decision'] == 'READY_FOR_GATEWAY_SUBMISSION', result
