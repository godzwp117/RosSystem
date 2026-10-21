"""M2 当前请求身份绑定：签发者信任边界、请求绑定、原子防重放与文件安全。

本文件对应的审查结论（第二阶段 P0-1）
=====================================
1. **HMAC 有效不等于身份已认证。** 签名只证明"持有密钥的人写了这些字段"。
   因此核验器把 `checks.signature` 与 `checks.issuer` 分开，并且只有签发者被
   **受信任签发者清单**标记为 `VERIFIED_IDENTITY_SOURCE` 才可能 AUTHENTICATED。
2. **仓库不交付任何受信任签发者清单**，也不交付真实签发端，因此生产路径恒为
   UNKNOWN。测试里的 VERIFIED 清单只存在于 tmp_path。
3. **防重放不是可选项。** 未配置账本、账本损坏、账本不可写一律不得 AUTHENTICATED。
4. **判重必须原子。** 见 `test_concurrent_same_nonce_is_accepted_at_most_once`。
5. **证据必须绑定这一条请求**（含 task_id 与目标点摘要），不能只绑定 id 字符串。
6. 证据/密钥/清单/账本都按 fd 读取并拒绝符号链接与过宽权限。
"""
from __future__ import annotations

import json
import os
import secrets
import stat
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for extra in (ROOT, ROOT / 'scripts', ROOT / 'tests' / 'unit'):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from identity_trust import current_identity as ci  # noqa: E402
from identity_trust.assessor import assessment  # noqa: E402
from test_identity_trust_assessor import sample  # noqa: E402,F401  (fixture)
from test_team_process_protocol import envelope  # noqa: E402

TEST_ONLY_ISSUER = 'test-only:unit'
VERIFIED_ISSUER = 'issuer:synthetic-verified'


# ---------------------------------------------------------------- 夹具
def make_key(path, *, mode=0o600, raw=None):
    path = Path(path)
    path.write_bytes(raw if raw is not None else secrets.token_hex(32).encode())
    os.chmod(path, mode)
    return path


def make_issuers(path, trust, issuer_id, *, mode=0o600, source='TEST_ONLY_SYNTHETIC'):
    path = Path(path)
    path.write_text(json.dumps({
        'contract': ci.ISSUER_CONTRACT,
        'issuers': [{'id': issuer_id, 'trust': trust,
                     'identity_source': source,
                     'reviewed_by': 'phase-2-test-fixture'}],
    }, indent=2), encoding='utf-8')
    os.chmod(path, mode)
    return path


def body_for(document, *, issuer_id=TEST_ONLY_ISSUER, nonce=None, overrides=None,
             digest=True):
    action = document['candidate_action']
    body = {
        'contract': ci.CONTRACT,
        'issuer': {'id': issuer_id, 'identity_source': 'TEST_ONLY_SYNTHETIC'},
        'request_id': document['request_id'],
        'resource': action['action_resource'],
        'operation': action['operation'],
        'request_digest': ci.request_digest(document) if digest else '0' * 64,
        'received_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'nonce': nonce or secrets.token_hex(16),
        'evidence_kind': ci.EVIDENCE_KIND,
        'remote_identity': {'authenticated': True,
                            'security_identity': 'sros2://TEST_ONLY/planner'},
        'producer': {'name': 'tests/unit/test_identity_current_binding.py',
                     'scope': 'CONTROLLED_TEST'},
    }
    body.update(overrides or {})
    return body


def mint(tmp_path, key, document, *, issuer_id=TEST_ONLY_ISSUER, nonce=None,
         overrides=None, digest=True, name='witness.json'):
    body = body_for(document, issuer_id=issuer_id, nonce=nonce,
                    overrides=overrides, digest=digest)
    path = tmp_path / name
    path.write_text(json.dumps({'body': body,
                                'signature': {'alg': 'hmac-sha256',
                                              'value': ci.sign(body, ci.load_key(str(key)))}}),
                    encoding='utf-8')
    return path, body


def verify(document, witness=None, key=None, issuers=None, ledger=None, now=None):
    return ci.verify(document, str(witness) if witness else None,
                     str(key) if key else None,
                     issuers_path=str(issuers) if issuers else None,
                     ledger=ledger, now=now)


@pytest.fixture
def doc():
    return envelope(None)


@pytest.fixture
def key(tmp_path):
    return make_key(tmp_path / 'witness.key')


@pytest.fixture
def ledger(tmp_path):
    return ci.Ledger(str(tmp_path / 'ledger.jsonl'))


# ---------------------------------------------------------------- 默认姿态
def test_no_witness_is_unknown(doc):
    result = verify(doc)
    assert result['status'] == ci.STATUS_UNKNOWN
    assert result['evidence_kind'] == 'NONE'
    assert ci.f0_accepts(result) is False


def test_signature_without_trusted_issuer_is_not_authentication(tmp_path, doc, key, ledger):
    """签名有效但签发者不可信 -> 仍是 UNKNOWN（这是本轮最重要的修正）。"""
    witness, _body = mint(tmp_path, key, doc)
    result = verify(doc, witness, key, ledger=ledger)
    assert result['checks']['signature'] == 'VALID'
    assert result['checks']['issuer'] == 'NOT_LISTED'
    assert result['status'] == ci.STATUS_UNKNOWN
    assert result['binding'] == 'WITNESS_ISSUER_UNTRUSTED'
    assert ci.f0_accepts(result) is False


def test_test_only_issuer_is_never_accepted_by_f0(tmp_path, doc, key, ledger):
    witness, _body = mint(tmp_path, key, doc)
    issuers = make_issuers(tmp_path / 'issuers.json', ci.TRUST_TEST_ONLY,
                           TEST_ONLY_ISSUER)
    result = verify(doc, witness, key, issuers=issuers, ledger=ledger)
    assert result['status'] == ci.STATUS_TEST_ONLY
    assert result['checks']['issuer'] == ci.TRUST_TEST_ONLY
    assert result['evidence_kind'] == ci.EVIDENCE_KIND_SIGNED
    assert ci.f0_accepts(result) is False


def test_verified_issuer_path_only_with_explicit_allowlist(tmp_path, doc, key, ledger):
    """机制存在，但只能由显式受信任清单打开；仓库不交付该清单。"""
    witness, _body = mint(tmp_path, key, doc, issuer_id=VERIFIED_ISSUER)
    issuers = make_issuers(tmp_path / 'issuers.json', ci.TRUST_VERIFIED,
                           VERIFIED_ISSUER, source='SYNTHETIC_TEST_SOURCE')
    result = verify(doc, witness, key, issuers=issuers, ledger=ledger)
    assert result['status'] == ci.STATUS_AUTHENTICATED
    assert result['checks'] == {'signature': 'VALID', 'issuer': ci.TRUST_VERIFIED,
                                'request_binding': 'MATCH', 'freshness': 'OK',
                                'replay': 'RESERVED'}
    assert ci.f0_accepts(result) is True
    # 仓库里没有任何受信任签发者清单（否则等于把身份信任锚静默打开）
    assert not [p for p in (ROOT / 'config').rglob('*issuer*')
                if p.is_file()]


# ---------------------------------------------------------------- 完整性与绑定
def test_tampered_signature_is_rejected(tmp_path, doc, key, ledger):
    witness, _body = mint(tmp_path, key, doc)
    document = json.loads(witness.read_text(encoding='utf-8'))
    document['body']['remote_identity']['security_identity'] = 'sros2://attacker'
    witness.write_text(json.dumps(document), encoding='utf-8')
    result = verify(doc, witness, key, ledger=ledger)
    assert result['status'] == ci.STATUS_UNKNOWN
    assert result['checks']['signature'] == 'INVALID'


@pytest.mark.parametrize('field,value,binding', [
    ('request_id', 'req-someone-else', 'WITNESS_REQUEST_BINDING_MISMATCH'),
    ('resource', '/rg/nav_execute', 'WITNESS_REQUEST_BINDING_MISMATCH'),
    ('operation', 'CANCEL', 'WITNESS_REQUEST_BINDING_MISMATCH'),
])
def test_attestation_must_bind_request_resource_operation(tmp_path, doc, key,
                                                          ledger, field, value, binding):
    witness, _body = mint(tmp_path, key, doc, overrides={field: value})
    result = verify(doc, witness, key, ledger=ledger)
    assert result['status'] == ci.STATUS_UNKNOWN
    assert result['binding'] == binding
    assert result['checks']['request_binding'] == 'MISMATCH'


def test_attestation_must_bind_the_exact_target(tmp_path, key, ledger):
    """同一 request_id 但目标点不同 -> 不能复用同一份证据。"""
    original = envelope(None, target={'frame_id': 'map', 'x': 1.5, 'y': 1.5, 'z': 0.0})
    forged = envelope(None, target={'frame_id': 'map', 'x': 9.0, 'y': 9.0, 'z': 0.0})
    witness, _body = mint(tmp_path, key, original)
    result = verify(forged, witness, key, ledger=ledger)
    assert result['status'] == ci.STATUS_UNKNOWN
    assert result['checks']['request_binding'] == 'MISMATCH'
    # 原请求本身是可核验的（证明差异来自目标点，而不是其它字段）
    assert verify(original, witness, key, ledger=ledger)['status'] in (
        ci.STATUS_UNKNOWN, ci.STATUS_TEST_ONLY)


def test_stale_and_future_attestations_are_rejected(tmp_path, doc, key, ledger):
    witness, _body = mint(tmp_path, key, doc)
    stale = verify(doc, witness, key, ledger=ledger,
                   now=time.time() + ci.MAX_REMOTE_AGE_SEC + 10)
    assert stale['status'] == ci.STATUS_UNKNOWN
    assert stale['checks']['freshness'] == 'STALE'
    future = verify(doc, witness, key, ledger=ledger,
                    now=time.time() - ci.MAX_CLOCK_SKEW_SEC - 10)
    assert future['status'] == ci.STATUS_UNKNOWN
    assert future['checks']['freshness'] == 'FROM_FUTURE'


def test_remote_identity_not_authenticated_is_denied(tmp_path, doc, key, ledger):
    witness, _body = mint(tmp_path, key, doc,
                          overrides={'remote_identity': {'authenticated': False}})
    result = verify(doc, witness, key, ledger=ledger)
    assert result['status'] == ci.STATUS_DENIED


# ---------------------------------------------------------------- 账本与重放
def test_missing_ledger_never_authenticates(tmp_path, doc, key):
    witness, _body = mint(tmp_path, key, doc, issuer_id=VERIFIED_ISSUER)
    issuers = make_issuers(tmp_path / 'issuers.json', ci.TRUST_VERIFIED, VERIFIED_ISSUER)
    result = verify(doc, witness, key, issuers=issuers, ledger=None)
    assert result['status'] != ci.STATUS_AUTHENTICATED
    assert result['checks']['replay'] == 'LEDGER_UNAVAILABLE'


def test_corrupt_ledger_never_authenticates(tmp_path, doc, key):
    witness, _body = mint(tmp_path, key, doc, issuer_id=VERIFIED_ISSUER)
    issuers = make_issuers(tmp_path / 'issuers.json', ci.TRUST_VERIFIED, VERIFIED_ISSUER)
    path = tmp_path / 'ledger.jsonl'
    # 完整（以换行结束）但内容非法的行 -> 账本损坏，必须失败关闭
    path.write_text('{"kind": "nonce", "nonce": \n', encoding='utf-8')
    result = ci.verify(doc, str(witness), str(key), issuers_path=str(issuers),
                       ledger=ci.Ledger(str(path)))
    assert result['status'] != ci.STATUS_AUTHENTICATED
    assert result['checks']['replay'] == 'LEDGER_ERROR'


def test_unwritable_ledger_never_authenticates(tmp_path, doc, key):
    witness, _body = mint(tmp_path, key, doc, issuer_id=VERIFIED_ISSUER)
    issuers = make_issuers(tmp_path / 'issuers.json', ci.TRUST_VERIFIED, VERIFIED_ISSUER)
    directory = tmp_path / 'ledger-dir'
    directory.mkdir()
    result = ci.verify(doc, str(witness), str(key), issuers_path=str(issuers),
                       ledger=ci.Ledger(str(directory)))
    assert result['status'] != ci.STATUS_AUTHENTICATED
    assert result['checks']['replay'] in ('LEDGER_ERROR',)


def test_symlinked_ledger_is_refused(tmp_path, doc, key):
    witness, _body = mint(tmp_path, key, doc, issuer_id=VERIFIED_ISSUER)
    issuers = make_issuers(tmp_path / 'issuers.json', ci.TRUST_VERIFIED, VERIFIED_ISSUER)
    real = tmp_path / 'real.jsonl'
    real.write_text('', encoding='utf-8')
    link = tmp_path / 'link.jsonl'
    os.symlink(real, link)
    result = ci.verify(doc, str(witness), str(key), issuers_path=str(issuers),
                       ledger=ci.Ledger(str(link)))
    assert result['status'] != ci.STATUS_AUTHENTICATED
    assert result['checks']['replay'] == 'LEDGER_ERROR'


def test_replayed_nonce_is_rejected(tmp_path, doc, key):
    witness, _body = mint(tmp_path, key, doc, issuer_id=VERIFIED_ISSUER)
    issuers = make_issuers(tmp_path / 'issuers.json', ci.TRUST_VERIFIED, VERIFIED_ISSUER)
    path = str(tmp_path / 'ledger.jsonl')
    first = ci.verify(doc, str(witness), str(key), issuers_path=str(issuers),
                      ledger=ci.Ledger(path))
    assert first['status'] == ci.STATUS_AUTHENTICATED
    second = ci.verify(doc, str(witness), str(key), issuers_path=str(issuers),
                       ledger=ci.Ledger(path))
    assert second['status'] == ci.STATUS_UNKNOWN
    assert second['checks']['replay'] == 'REPLAYED'


#: 子进程脚本：等到统一的起跑时刻再核验，制造真实并发竞争。
RACE_SCRIPT = '''
import json, sys, time
sys.path.insert(0, sys.argv[1])
from identity_trust import current_identity as ci
spec = json.loads(sys.argv[2])
while time.time() < spec["start_at"]:
    pass
result = ci.verify(spec["envelope"], spec["witness"], spec["key"],
                   issuers_path=spec["issuers"], ledger=ci.Ledger(spec["ledger"]))
print(json.dumps({"status": result["status"],
                  "replay": result["checks"]["replay"]}))
'''


def test_concurrent_same_nonce_is_accepted_at_most_once(tmp_path, doc, key):
    """8 个**独立进程**同时核验同一份证据：只能有 1 个 RESERVED。

    用 subprocess 而不是 multiprocessing.Pool：某些受限环境（含本仓库的 CI
    沙箱）不允许创建 POSIX 信号量，Pool 会直接失败——那会让"并发正确性"
    变成永远测不到。统一用起跑时刻对齐，保证竞争真实发生。
    """
    import subprocess
    witness, _body = mint(tmp_path, key, doc, issuer_id=VERIFIED_ISSUER)
    issuers = make_issuers(tmp_path / 'issuers.json', ci.TRUST_VERIFIED, VERIFIED_ISSUER)
    ledger_path = str(tmp_path / 'ledger.jsonl')
    script = tmp_path / 'race.py'
    script.write_text(RACE_SCRIPT, encoding='utf-8')
    spec = json.dumps({'start_at': time.time() + 1.0,
                       'envelope': doc, 'witness': str(witness), 'key': str(key),
                       'issuers': str(issuers), 'ledger': ledger_path})
    children = [subprocess.Popen(
        [sys.executable, str(script), str(ROOT), spec],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for _ in range(8)]
    results = []
    for child in children:
        out, err = child.communicate(timeout=120)
        assert child.returncode == 0, err[-400:]
        results.append(json.loads(out))
    reserved = [row for row in results if row['replay'] == 'RESERVED']
    replayed = [row for row in results if row['replay'] == 'REPLAYED']
    assert len(reserved) == 1, results
    assert len(replayed) == 7, results
    assert sum(1 for row in results
               if row['status'] == ci.STATUS_AUTHENTICATED) == 1


# ---------------------------------------------------------------- 文件安全
def test_symlinked_witness_is_refused(tmp_path, doc, key, ledger):
    witness, _body = mint(tmp_path, key, doc)
    link = tmp_path / 'witness-link.json'
    os.symlink(witness, link)
    result = verify(doc, link, key, ledger=ledger)
    assert result['status'] == ci.STATUS_UNKNOWN
    assert 'symlink' in result['reason'] or 'unreadable' in result['reason']


def test_symlinked_key_is_refused(tmp_path, doc, ledger):
    key = make_key(tmp_path / 'real.key')
    link = tmp_path / 'link.key'
    os.symlink(key, link)
    witness, _body = mint(tmp_path, key, doc)
    result = verify(doc, witness, link, ledger=ledger)
    assert result['status'] == ci.STATUS_UNKNOWN
    assert 'symlink' in result['reason'] or 'unreadable' in result['reason']


def test_world_readable_key_is_refused(tmp_path, doc, ledger):
    key = make_key(tmp_path / 'loose.key')      # 先以 0600 铸造证据
    witness, _body = mint(tmp_path, key, doc)
    os.chmod(key, 0o644)                        # 再放宽权限 -> 核验必须拒绝
    result = verify(doc, witness, key, ledger=ledger)
    assert result['status'] == ci.STATUS_UNKNOWN
    assert 'permissions too open' in result['reason']


def test_world_readable_issuer_list_is_refused(tmp_path, doc, key, ledger):
    witness, _body = mint(tmp_path, key, doc, issuer_id=VERIFIED_ISSUER)
    issuers = make_issuers(tmp_path / 'issuers.json', ci.TRUST_VERIFIED,
                           VERIFIED_ISSUER, mode=0o644)
    result = verify(doc, witness, key, issuers=issuers, ledger=ledger)
    assert result['status'] != ci.STATUS_AUTHENTICATED
    assert result['checks']['issuer'] == 'ERROR'


def test_oversized_witness_is_refused(tmp_path, doc, key, ledger):
    big = tmp_path / 'big.json'
    big.write_bytes(b'{"body": "' + b'x' * (ci.MAX_WITNESS_BYTES + 1024) + b'"}')
    result = verify(doc, big, key, ledger=ledger)
    assert result['status'] == ci.STATUS_UNKNOWN


# ---------------------------------------------------------------- assessor 集成
def options(sample_tuple, *, witness=None, key=None, issuers=None, ledger=None,
            case=None):
    opts, _env, _run_dir = sample_tuple
    merged = dict(opts)
    merged.update({'identity_witness': witness, 'identity_witness_key': key,
                   'identity_issuers': issuers, 'identity_ledger': ledger})
    if case:
        merged['case'] = case
    from argparse import Namespace
    return Namespace(**merged)


def test_historical_authorized_is_not_current_identity(sample):
    _opts, env, _ = sample
    out = assessment(env, options(sample))
    current = out['extensions']['current_request_identity']
    assert out['status'] == 'AUTHORIZED'
    assert out['extensions']['historical_only'] is True
    assert current['status'] == ci.STATUS_UNKNOWN
    assert ci.f0_accepts(current) is False


def test_historical_authorization_reuse_is_detected(sample, tmp_path):
    _opts, env, _ = sample
    ledger = str(tmp_path / 'ledger.jsonl')
    first = assessment(env, options(sample, ledger=ledger))
    assert first['status'] == 'AUTHORIZED'
    assert first['extensions']['historical_authorization_reuse_detected'] is False
    second = assessment(env, options(sample, ledger=ledger))
    assert second['status'] == 'UNKNOWN'
    assert second['extensions']['historical_authorization_reuse_detected'] is True


def test_same_historical_evidence_for_a_brand_new_request_stays_unbound(sample, tmp_path):
    """历史证据对**新请求**天然可复用——这正是它不能当身份依据的原因。

    账本只能发现"同一条请求被重复解释"；对一条全新的 request_id，历史实验当然
    仍然可以（也应当）被解释。所以真正的防线不是账本，而是
    `current_request_identity` 恒为 UNKNOWN。
    """
    _opts, env, _ = sample
    ledger = str(tmp_path / 'ledger.jsonl')
    first = assessment(env, options(sample, ledger=ledger))
    second_env = json.loads(json.dumps(env))
    second_env['request_id'] = 'req-brand-new-after-historical'
    second = assessment(second_env, options(sample, ledger=ledger))
    for out in (first, second):
        assert out['status'] == 'AUTHORIZED'           # 历史结论本身仍成立
        assert out['extensions']['historical_only'] is True
        current = out['extensions']['current_request_identity']
        assert current['status'] == ci.STATUS_UNKNOWN
        assert ci.f0_accepts(current) is False
    # 新请求不会被误判成"历史授权复用"（它本来就该被独立解释）
    assert second['extensions']['historical_authorization_reuse_detected'] is False


def test_self_reported_identity_in_envelope_never_authenticates(sample):
    _opts, env, _ = sample
    env = json.loads(json.dumps(env))
    env['observations'][0]['detail'] = {
        'identity': {'subject': 'planner_node', 'resource': '/rg/guarded_navigate'},
        'declared_enclave': '/planner',
        'authenticated_identity': 'sros2://forged',
        'current_request_identity': {'status': 'AUTHENTICATED'},
    }
    out = assessment(env, options(sample))
    current = out['extensions']['current_request_identity']
    assert current['status'] == ci.STATUS_UNKNOWN
    assert ci.f0_accepts(current) is False
    assert 'authenticated_identity' not in out['subject']


def test_assessor_verified_issuer_reaches_authenticated(sample, tmp_path):
    """完整链路：真实评估器 + 受信任清单 + 账本 -> AUTHENTICATED。

    清单是 tmp_path 里的测试夹具；仓库不交付任何这样的清单。
    """
    _opts, env, _ = sample
    key = make_key(tmp_path / 'w.key')
    witness, _body = mint(tmp_path, key, env, issuer_id=VERIFIED_ISSUER)
    issuers = make_issuers(tmp_path / 'issuers.json', ci.TRUST_VERIFIED, VERIFIED_ISSUER)
    out = assessment(env, options(sample, witness=str(witness), key=str(key),
                                  issuers=str(issuers),
                                  ledger=str(tmp_path / 'ledger.jsonl')))
    current = out['extensions']['current_request_identity']
    assert current['status'] == ci.STATUS_AUTHENTICATED
    assert ci.f0_accepts(current) is True
    # 历史证据仍然独立存在
    assert out['status'] == 'AUTHORIZED'
