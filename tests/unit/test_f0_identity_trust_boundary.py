"""F0 身份信任边界（P0 修复）的强制安全矩阵。

背景：修复前的漏洞
------------------
F0 只比较模块输出里的 `extensions.current_request_identity.status` 是否为
`AUTHENTICATED`。由于该对象由外部进程写出，任何模块都能自己写一个
`AUTHENTICATED`（甚至伪造完整的 `checks` 六个字段）从而得到
`READY_FOR_GATEWAY_SUBMISSION`，而它既没有签名密钥，也不在受信任签发者清单里。

修复后的边界
------------
严格模式（默认）下 F0 **不再消费**该字段，而是用受信任本地配置里的
原始证据（witness）、核验密钥（key）、受信任签发者清单（issuers）与
防重放账本（ledger），调用 `identity_trust/current_identity.py:verify()`
自行完成：签名核验 → 签发者信任判定 → 请求绑定比对 → 新鲜度检查 →
原子 nonce 预留。任一环节不成立即失败关闭。

关于本文件里的"正向"用例
------------------------
系统目前**没有**真正的生产 DDS 身份签发者（ROS 2 Jazzy 不向订阅端暴露
认证主体身份）。因此正向用例使用**人工构造的合成受信任清单**
（`VERIFIED_ISSUER`），它证明的是**核验代码在材料齐全时确实会放行**，
而不是"生产身份认证能力已经具备"。这一点在任何报告中都必须原样保留：
`CONTROLLED_TEST_ONLY` 不等于生产环境的真实 DDS 身份认证成功。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

pytest.importorskip('jsonschema', reason='需要 jsonschema>=4.0（Draft 2020-12）')

ROOT = Path(__file__).resolve().parents[2]
for extra in (ROOT, ROOT / 'scripts', ROOT / 'tests' / 'unit'):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from test_identity_current_binding import (  # noqa: E402
    TEST_ONLY_ISSUER, VERIFIED_ISSUER, make_issuers, make_key, mint)
from test_team_process_protocol import (  # noqa: E402
    envelope, proceed_control, run_adapter, write_config)

from identity_trust import current_identity as ci  # noqa: E402


# ---------------------------------------------------------------- 夹具
def _materials(tmp_path, env, *, trust=ci.TRUST_VERIFIED,
               issuer_id=VERIFIED_ISSUER, key_mode=0o600, issuers_mode=0o600,
               nonce=None, overrides=None, digest=True, name='witness.json'):
    """构造一整套受信任材料：密钥、签发者清单、签名证据。

    这些材料只会出现在**受信任本地配置**里；业务信封无法提供或影响它们。
    """
    # 先用 0600 建密钥完成签名，再按用例需要放宽，否则 mint() 自己就会
    # 因为 load_key 的权限检查而拒绝（那属于签发侧，不是被测边界）。
    key = make_key(tmp_path / 'attest.key', mode=0o600)
    issuers = make_issuers(tmp_path / 'issuers.json', trust, issuer_id,
                           mode=issuers_mode)
    witness, body = mint(tmp_path, key, env, issuer_id=issuer_id, nonce=nonce,
                         overrides=overrides, digest=digest, name=name)
    os.chmod(key, key_mode)
    return {'key': str(key), 'issuers': str(issuers), 'witness': str(witness),
            'body': body,
            'ledger': str(tmp_path / 'ledger.jsonl')}


def _block(materials, **extra):
    block = {'mode': 'STRICT', 'witness_path': materials['witness'],
             'key_path': materials['key'], 'issuers_path': materials['issuers'],
             'ledger_path': materials['ledger']}
    block.update(extra)
    return block


def _run(tmp_path, *, controls=None, identity_block=None, identity_mode=None,
         identity_module=None, env_document=None):
    """在严格模式下运行 F0，返回 (rc, result, stderr, envelope)。"""
    document = env_document or envelope(proceed_control())
    commands = dict(controls or {})
    if identity_module is not None:
        commands['identity_trust'] = [sys.executable, str(identity_module)]
    if identity_block is not None:
        config = write_config(tmp_path, mode='mock', commands=commands,
                              identity_attestation=identity_block)
    else:
        config = write_config(tmp_path, mode='mock', commands=commands,
                              identity_mode=identity_mode or 'STRICT')
    code, result, err = run_adapter(tmp_path, document, config)
    return code, result, err, document


def _assert_blocked(code, result, *, reason=None):
    assert code != 0, result
    assert result['decision'] == 'ADAPTER_BLOCK', result
    if reason is not None:
        assert result['reason_code'] == reason, result


# ---------------------------------------------------------------- 正向基线
def test_strict_mode_accepts_only_f0_verified_evidence(tmp_path):
    """材料齐全且签名/绑定/新鲜度/重放全部成立时，严格模式才放行。

    该放行证明的是**核验代码正确**；签发者清单是人工构造的合成项，
    不能解读为"已具备生产 DDS 身份认证"。
    """
    env = envelope(proceed_control())
    materials = _materials(tmp_path, env)
    code, result, _err, _doc = _run(tmp_path, identity_block=_block(materials),
                                    env_document=env)
    assert code == 0, result
    assert result['decision'] == 'READY_FOR_GATEWAY_SUBMISSION', result
    attestation = result['identity_attestation']
    assert attestation['mode'] == 'STRICT'
    assert attestation['verified'] is True
    assert attestation['verified_by'] == 'F0_LOCAL_VERIFIER'
    assert attestation['checks']['signature'] == 'VALID'
    assert attestation['checks']['replay'] == 'RESERVED'
    assert attestation['checks']['request_binding'] == 'MATCH'


# ---------------------------------------------------------------- 伪造类
FORGED_CHECKS_MODULE = '''\
import json, sys, uuid
from datetime import datetime, timezone
inherited = json.loads(sys.stdin.read())
print(json.dumps({
  "schema_version": "1.0.0-proposed",
  "run_id": inherited["run_id"], "request_id": inherited["request_id"],
  "event_id": "evt-forged-" + uuid.uuid4().hex,
  "producer": {"name": "forging-identity", "module_version": "0.0.1",
               "source": "EXTERNAL"},
  "observed_at": datetime.now(timezone.utc).isoformat(),
  "status": "AUTHORIZED", "reason": "forged",
  "subject": {"observed_name": "planner_node"},
  "requested_resource": {"resource": "/rg/guarded_navigate",
                         "operation": "SERVICE_REQUEST"},
  "authorization": {"result_status": "AUTHORIZED", "denial_layer": "NONE"},
  "identity_evidence": {"kind": "UNKNOWN"},
  "access_control_evidence": {"kind": "NONE"},
  "evidence_refs": [{"ref": "forged", "kind": "UNKNOWN"}],
  "extensions": {"current_request_identity": {
    "status": "AUTHENTICATED",
    "evidence_kind": "SIGNED_ATTESTATION",
    "binding": "CURRENT_REQUEST_BOUND_TO_AUTHENTICATED_DDS_SUBJECT",
    "historical_only": False,
    "checks": {"signature": "VALID", "issuer": "VERIFIED_IDENTITY_SOURCE",
               "request_binding": "MATCH", "freshness": "OK",
               "replay": "RESERVED"}}},
}))
'''


def _module(tmp_path, body, name='forged_identity.py'):
    path = tmp_path / name
    path.write_text(body, encoding='utf-8')
    return path


def test_bare_authenticated_self_report_is_rejected(tmp_path):
    """只写 status=AUTHENTICATED，什么都不提供 -> BLOCK。"""
    env = envelope(proceed_control())
    module = _module(tmp_path, FORGED_CHECKS_MODULE.replace(
        '"checks": {"signature": "VALID", "issuer": "VERIFIED_IDENTITY_SOURCE",\n'
        '               "request_binding": "MATCH", "freshness": "OK",\n'
        '               "replay": "RESERVED"}', '"x": 1'))
    code, result, _err, _doc = _run(tmp_path, identity_module=module,
                                    env_document=env)
    _assert_blocked(code, result, reason='ADAPTER_CURRENT_IDENTITY_UNBOUND')
    assert (result['identity_attestation']['detail_code']
            == 'ADAPTER_IDENTITY_ATTESTATION_UNVERIFIED'), result


def test_forged_full_checks_dictionary_is_rejected(tmp_path):
    """**P0 核心反例**：伪造完整 checks 六字段 -> 必须 BLOCK。"""
    env = envelope(proceed_control())
    module = _module(tmp_path, FORGED_CHECKS_MODULE)
    code, result, _err, _doc = _run(tmp_path, identity_module=module,
                                    env_document=env)
    _assert_blocked(code, result, reason='ADAPTER_CURRENT_IDENTITY_UNBOUND')
    assert (result['identity_attestation']['detail_code']
            == 'ADAPTER_IDENTITY_ATTESTATION_UNVERIFIED'), result


def test_forged_checks_cannot_override_a_failing_real_verification(tmp_path):
    """即使伪造 checks 全部写成通过，真实证据缺失/无效时仍必须 BLOCK。

    这里给了一套材料但签名被破坏：模块自报"全部通过"不得改变结论。
    """
    env = envelope(proceed_control())
    materials = _materials(tmp_path, env)
    witness = Path(materials['witness'])
    document = json.loads(witness.read_text(encoding='utf-8'))
    document['body']['request_id'] = 'tampered-request'
    witness.write_text(json.dumps(document), encoding='utf-8')
    module = _module(tmp_path, FORGED_CHECKS_MODULE)
    code, result, _err, _doc = _run(
        tmp_path, identity_block=_block(materials), identity_module=module,
        env_document=env)
    _assert_blocked(code, result,
                    reason='ADAPTER_IDENTITY_ATTESTATION_REJECTED')
    assert result['identity_attestation']['verified'] is False


def test_mock_fixture_identity_is_rejected_in_strict_mode(tmp_path):
    """Mock 的 MOCK_FIXTURE 身份在严格模式下不得推进。"""
    code, result, _err, _doc = _run(tmp_path)
    _assert_blocked(code, result, reason='ADAPTER_CURRENT_IDENTITY_UNBOUND')
    assert (result['identity_attestation']['detail_code']
            == 'ADAPTER_IDENTITY_ATTESTATION_UNVERIFIED'), result


def test_self_declared_dds_enclave_is_rejected(tmp_path):
    """模块自报一个"可信 DDS Enclave"不构成身份证据 -> BLOCK。"""
    env = envelope(proceed_control())
    body = FORGED_CHECKS_MODULE.replace(
        '"subject": {"observed_name": "planner_node"}',
        '"subject": {"observed_name": "planner_node",'
        ' "declared_enclave": "/planner",'
        ' "authenticated_identity": "CN=planner"}')
    module = _module(tmp_path, body, name='enclave_identity.py')
    code, result, _err, _doc = _run(tmp_path, identity_module=module,
                                    env_document=env)
    _assert_blocked(code, result, reason='ADAPTER_CURRENT_IDENTITY_UNBOUND')
    assert (result['identity_attestation']['detail_code']
            == 'ADAPTER_IDENTITY_ATTESTATION_UNVERIFIED'), result


def test_historical_only_identity_is_rejected(tmp_path):
    """historical_only=true 的当前身份结论不得推进（严格模式无材料 -> BLOCK）。"""
    env = envelope(proceed_control())
    body = FORGED_CHECKS_MODULE.replace('"historical_only": False',
                                        '"historical_only": True')
    module = _module(tmp_path, body, name='historical_identity.py')
    code, result, _err, _doc = _run(tmp_path, identity_module=module,
                                    env_document=env)
    _assert_blocked(code, result, reason='ADAPTER_CURRENT_IDENTITY_UNBOUND')
    assert (result['identity_attestation']['detail_code']
            == 'ADAPTER_IDENTITY_ATTESTATION_UNVERIFIED'), result


def test_historical_only_is_also_rejected_in_controlled_mode(tmp_path):
    """受控模式下 historical_only=true 仍被原有规则阻断（不因修复而放松）。"""
    body = FORGED_CHECKS_MODULE.replace('"historical_only": False',
                                        '"historical_only": True')
    env = envelope(proceed_control())
    module = _module(tmp_path, body, name='historical_ctl.py')
    code, result, _err, _doc = _run(tmp_path, identity_module=module,
                                    identity_mode='CONTROLLED_TEST_ONLY',
                                    env_document=env)
    _assert_blocked(code, result, reason='ADAPTER_CURRENT_IDENTITY_UNBOUND')


# ---------------------------------------------------------------- 无材料
def test_no_raw_credential_configured_is_rejected(tmp_path):
    """严格模式没有任何原始凭据 -> BLOCK（不得退化为信任自报）。"""
    code, result, _err, _doc = _run(tmp_path, identity_mode='STRICT')
    _assert_blocked(code, result, reason='ADAPTER_CURRENT_IDENTITY_UNBOUND')
    assert (result['identity_attestation']['detail_code']
            == 'ADAPTER_IDENTITY_ATTESTATION_UNVERIFIED'), result


def test_missing_witness_file_is_rejected(tmp_path):
    """配置了路径但证据文件不存在 -> BLOCK。"""
    env = envelope(proceed_control())
    materials = _materials(tmp_path, env)
    os.unlink(materials['witness'])
    code, result, _err, _doc = _run(tmp_path, identity_block=_block(materials),
                                    env_document=env)
    _assert_blocked(code, result, reason='ADAPTER_CURRENT_IDENTITY_UNBOUND')
    assert (result['identity_attestation']['detail_code']
            == 'ADAPTER_IDENTITY_ATTESTATION_UNVERIFIED'), result


def test_strict_mode_requires_key_material(tmp_path):
    """严格模式只给 witness 不给密钥 -> 配置非法（失败关闭）。"""
    env = envelope(proceed_control())
    materials = _materials(tmp_path, env)
    block = {'mode': 'STRICT', 'witness_path': materials['witness']}
    code, result, _err, _doc = _run(tmp_path, identity_block=block,
                                    env_document=env)
    _assert_blocked(code, result,
                    reason='ADAPTER_IDENTITY_ATTESTATION_CONFIG_INVALID')


def test_relative_witness_path_is_rejected(tmp_path):
    """相对路径可能被工作目录操纵 -> 配置非法。"""
    block = {'mode': 'STRICT', 'witness_path': 'witness.json',
             'key_path': 'k.bin'}
    code, result, _err, _doc = _run(tmp_path, identity_block=block)
    _assert_blocked(code, result,
                    reason='ADAPTER_IDENTITY_ATTESTATION_CONFIG_INVALID')


# ---------------------------------------------------------------- 核验失败类
def test_bad_signature_is_rejected(tmp_path):
    """签名与证据字节不匹配 -> BLOCK。"""
    env = envelope(proceed_control())
    materials = _materials(tmp_path, env)
    document = json.loads(Path(materials['witness']).read_text(encoding='utf-8'))
    document['signature']['value'] = '0' * 64
    Path(materials['witness']).write_text(json.dumps(document), encoding='utf-8')
    code, result, _err, _doc = _run(tmp_path, identity_block=_block(materials),
                                    env_document=env)
    _assert_blocked(code, result, reason='ADAPTER_IDENTITY_ATTESTATION_REJECTED')
    assert result['identity_attestation']['checks']['signature'] != 'VALID'


def test_issuer_not_in_trusted_list_is_rejected(tmp_path):
    """签发者不在受信任清单 -> BLOCK（签名有效不等于来源可信）。"""
    env = envelope(proceed_control())
    materials = _materials(tmp_path, env, issuer_id='issuer:not-listed')
    # 清单里登记的是另一个 id
    make_issuers(Path(materials['issuers']), ci.TRUST_VERIFIED, VERIFIED_ISSUER)
    code, result, _err, _doc = _run(tmp_path, identity_block=_block(materials),
                                    env_document=env)
    _assert_blocked(code, result, reason='ADAPTER_IDENTITY_ATTESTATION_REJECTED')
    assert result['identity_attestation']['binding'] == 'WITNESS_ISSUER_UNTRUSTED'


def test_test_only_issuer_is_rejected(tmp_path):
    """TEST_ONLY 签发者：签名与绑定成立，但不得作为在线身份授权依据。"""
    env = envelope(proceed_control())
    materials = _materials(tmp_path, env, trust=ci.TRUST_TEST_ONLY,
                           issuer_id=TEST_ONLY_ISSUER)
    code, result, _err, _doc = _run(tmp_path, identity_block=_block(materials),
                                    env_document=env)
    _assert_blocked(code, result, reason='ADAPTER_IDENTITY_ATTESTATION_REJECTED')
    assert (result['identity_attestation']['status']
            == ci.STATUS_TEST_ONLY), result


def test_request_digest_mismatch_is_rejected(tmp_path):
    """证据绑定的请求摘要与当前信封不一致 -> BLOCK。"""
    env = envelope(proceed_control())
    materials = _materials(tmp_path, env, overrides={'request_digest': '0' * 64})
    code, result, _err, _doc = _run(tmp_path, identity_block=_block(materials),
                                    env_document=env)
    _assert_blocked(code, result, reason='ADAPTER_IDENTITY_ATTESTATION_REJECTED')
    assert (result['identity_attestation']['checks']['request_binding']
            == 'MISMATCH'), result


def test_resource_operation_mismatch_is_rejected(tmp_path):
    """证据里的资源/操作与当前候选动作不一致 -> BLOCK。"""
    env = envelope(proceed_control())
    materials = _materials(tmp_path, env,
                           overrides={'resource': '/rg/nav_execute'})
    code, result, _err, _doc = _run(tmp_path, identity_block=_block(materials),
                                    env_document=env)
    _assert_blocked(code, result, reason='ADAPTER_IDENTITY_ATTESTATION_REJECTED')


def test_stale_evidence_is_rejected(tmp_path):
    """证据超出新鲜度窗口 -> BLOCK。"""
    env = envelope(proceed_control())
    materials = _materials(tmp_path, env,
                           overrides={'received_at': '2020-01-01T00:00:00Z'})
    code, result, _err, _doc = _run(tmp_path, identity_block=_block(materials),
                                    env_document=env)
    _assert_blocked(code, result, reason='ADAPTER_IDENTITY_ATTESTATION_REJECTED')
    assert result['identity_attestation']['checks']['freshness'] == 'STALE'


def test_replayed_nonce_is_rejected(tmp_path):
    """同一 nonce 第二次使用 -> BLOCK（防重放必须是硬条件）。"""
    env = envelope(proceed_control())
    nonce = 'a' * 32
    materials = _materials(tmp_path, env, nonce=nonce)
    code, result, _err, _doc = _run(tmp_path, identity_block=_block(materials),
                                    env_document=env)
    assert code == 0, result

    # 同一份证据再次提交（同一账本）：nonce 已被预留
    second_dir = tmp_path / 'second'
    second_dir.mkdir()
    env2 = envelope(proceed_control())
    block = _block(materials)
    config = write_config(second_dir, mode='mock', identity_attestation=block)
    code2, result2, _err2 = run_adapter(second_dir, env2, config)
    _assert_blocked(code2, result2,
                    reason='ADAPTER_IDENTITY_ATTESTATION_REJECTED')
    assert (result2['identity_attestation']['checks']['replay']
            == 'REPLAYED'), result2


def test_unavailable_ledger_is_rejected(tmp_path):
    """没有账本就无法排除重放 -> BLOCK（不可关闭重放检查）。"""
    env = envelope(proceed_control())
    materials = _materials(tmp_path, env)
    block = _block(materials)
    block.pop('ledger_path')
    code, result, _err, _doc = _run(tmp_path, identity_block=block,
                                    env_document=env)
    _assert_blocked(code, result, reason='ADAPTER_IDENTITY_ATTESTATION_REJECTED')
    assert (result['identity_attestation']['checks']['replay']
            in ('LEDGER_UNAVAILABLE', 'LEDGER_ERROR')), result


def test_corrupt_ledger_is_rejected(tmp_path):
    """账本损坏 -> BLOCK（失败关闭，不静默重置）。"""
    env = envelope(proceed_control())
    materials = _materials(tmp_path, env)
    Path(materials['ledger']).write_text('{not json}\n', encoding='utf-8')
    code, result, _err, _doc = _run(tmp_path, identity_block=_block(materials),
                                    env_document=env)
    _assert_blocked(code, result, reason='ADAPTER_IDENTITY_ATTESTATION_REJECTED')


def test_world_readable_key_is_rejected(tmp_path):
    """密钥文件权限过宽 -> 拒绝（凭据权限是被核验的一部分）。"""
    env = envelope(proceed_control())
    materials = _materials(tmp_path, env, key_mode=0o644)
    code, result, _err, _doc = _run(tmp_path, identity_block=_block(materials),
                                    env_document=env)
    _assert_blocked(code, result, reason='ADAPTER_IDENTITY_ATTESTATION_REJECTED')


def test_world_readable_issuer_list_is_rejected(tmp_path):
    """受信任签发者清单权限过宽 -> 拒绝。"""
    env = envelope(proceed_control())
    materials = _materials(tmp_path, env, issuers_mode=0o644)
    code, result, _err, _doc = _run(tmp_path, identity_block=_block(materials),
                                    env_document=env)
    _assert_blocked(code, result, reason='ADAPTER_IDENTITY_ATTESTATION_REJECTED')


# ---------------------------------------------------------------- 单一消费路径
def test_shared_witness_between_m2_and_f0_is_a_config_error(tmp_path):
    """M2 与 F0 指向同一份正式凭据 -> 配置非法（nonce 只能有一个权威消费者）。"""
    env = envelope(proceed_control())
    materials = _materials(tmp_path, env)
    shared = [sys.executable, 'identity_trust/assessor.py',
              '--identity-witness', materials['witness'],
              '--identity-witness-key', materials['key']]
    code, result, _err, _doc = _run(
        tmp_path, identity_block=_block(materials),
        controls={'identity_trust': shared}, env_document=env)
    _assert_blocked(code, result,
                    reason='ADAPTER_IDENTITY_ATTESTATION_CONFIG_INVALID')


# ---------------------------------------------------------------- 受控模式隔离
def test_controlled_mode_ready_is_explicitly_labelled(tmp_path):
    """受控模式的 READY 必须带明确标注：不得被表述为真实身份认证。"""
    code, result, _err, _doc = _run(tmp_path, identity_mode='CONTROLLED_TEST_ONLY')
    assert code == 0, result
    assert result['decision'] == 'READY_FOR_GATEWAY_SUBMISSION', result
    attestation = result['identity_attestation']
    assert attestation['mode'] == 'CONTROLLED_TEST_ONLY'
    assert attestation['verified'] is False
    assert attestation['verified_by'] == 'MODULE_SELF_REPORT'
    assert '不构成真实 DDS 身份认证' in attestation['caveat']
    assert '受控身份模式' in result['detail']


def test_controlled_mode_requires_explicit_reason(tmp_path):
    """受控模式必须给出非空理由，防止"随手把生产模式改成无身份检查"。"""
    code, result, _err, _doc = _run(
        tmp_path, identity_block={'mode': 'CONTROLLED_TEST_ONLY'})
    _assert_blocked(code, result,
                    reason='ADAPTER_IDENTITY_ATTESTATION_CONFIG_INVALID')


def test_unknown_identity_mode_is_rejected(tmp_path):
    """未知模式字符串 -> 配置非法（不猜测、不降级）。"""
    code, result, _err, _doc = _run(
        tmp_path, identity_block={'mode': 'PERMISSIVE'})
    _assert_blocked(code, result,
                    reason='ADAPTER_IDENTITY_ATTESTATION_CONFIG_INVALID')
