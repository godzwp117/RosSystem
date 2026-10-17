#!/usr/bin/env python3
"""当前请求身份绑定：受信任证据契约、签发者信任边界、原子防重放。

安全定位（第二阶段审查后的最终结论）
====================================
**HMAC 签名有效 ≠ DDS 身份已认证。** 一纸签名只能证明"持有密钥的人写了这些字段"，
不能证明"A 这个已认证 DDS 主体发出了这条请求"。因此本模块把两者彻底分开：

* `checks.signature`   —— 字节完整性（HMAC-SHA256）；
* `checks.issuer`      —— 签发者是否在**受信任签发者清单**中，且其声明的身份来源
                           属于"已验证"类；
* `checks.request_binding` —— 证据是否绑定到**这一条**请求（含 task_id/目标点摘要）；
* `checks.freshness`   —— 新鲜度与时钟偏差；
* `checks.replay`      —— 原子 nonce 预留（不是"先查后写"）。

只有五项同时成立，且签发者被清单标记为 `VERIFIED_IDENTITY_SOURCE`，才返回
`AUTHENTICATED`。仓库**不交付**任何受信任签发者清单，也不交付满足该条件的签发端，
因此真实部署路径恒为 `UNKNOWN`——这是刻意保留的失败关闭。

为什么仍然保留"可核验"的能力
============================
一旦（未来）存在真实身份来源（例如中间件层对当前参与者的身份绑定、或带硬件保护的
见证服务），只需新增一份**受审查的签发者清单**即可启用，代码无需改动。清单本身就是
信任锚：它的存在与内容是一次需要评审的安全决策，且必须与密钥分开保管。

现状事实（必须原样转述，不得模糊）
==================================
ROS 2 Jazzy + rclpy 没有公开稳定 API 让订阅端取得"该样本发布者已完成 DDS-Security
认证的身份"。DDS-Security 的认证发生在参与者发现/建链阶段；rclpy 的 Subscription
回调只给出反序列化后的消息；Fast DDS 的 DataReaderListener/on_data_available 同样
不携带身份，且未经 rclpy 暴露。因此**可信证据产生组件不存在**，本仓库只交付契约、
核验器、受控测试签发器（TEST_ONLY）与失败关闭默认路径。

受控测试签发器的隔离
====================
`identity_trust/test_issuer.py` 只能为 `TEST_ONLY` 签发者签名，产出的状态是
`AUTHENTICATED_TEST_ONLY`，`f0_accepts()` 恒为 False。它不能把
`ONLINE_PROCEED_READY` 从 FAIL 变成 PASS。

文件与权限加固
==============
* 证据 / 密钥 / 签发者清单：`O_NOFOLLOW` + `fstat` 校验普通文件 + 尺寸上限 +
  从 fd 读取（避免 `getsize` 后再 `open` 的 TOCTOU）。
* 密钥与签发者清单要求权限不宽于 `0600`（组/其他位必须为 0）。
* 账本：`O_NOFOLLOW|O_APPEND`，`fcntl.flock(LOCK_EX)` 内完成"重读-判重-追加-fsync"，
  并发实例不会同时接受同一 nonce；账本损坏/不可写一律不得给出 AUTHENTICATED。
"""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import hmac
import json
import os
import stat
import time

CONTRACT = 'current-identity-attestation/2'
SUPPORTED_CONTRACTS = (CONTRACT,)
ISSUER_CONTRACT = 'trusted-identity-issuers/1'
#: 证据种类（签发者的**声明**，只在签发者受信任时才有意义）。
EVIDENCE_KIND = 'MIDDLEWARE_IDENTITY_BINDING'
EVIDENCE_KIND_SIGNED = 'SIGNED_ATTESTATION'

MAX_WITNESS_BYTES = 64 * 1024
MAX_KEY_BYTES = 4096
MAX_ISSUERS_BYTES = 64 * 1024
MAX_LEDGER_BYTES = 8 * 1024 * 1024
MAX_REMOTE_AGE_SEC = 30.0
MAX_CLOCK_SKEW_SEC = 5.0
NONCE_HEX_LEN = 32

STATUS_UNKNOWN = 'UNKNOWN'
STATUS_DENIED = 'DENIED'
STATUS_AUTHENTICATED = 'AUTHENTICATED'
#: 签名与绑定都成立，但签发者只是 TEST_ONLY 角色。F0 不得据此推进。
STATUS_TEST_ONLY = 'AUTHENTICATED_TEST_ONLY'

TRUST_VERIFIED = 'VERIFIED_IDENTITY_SOURCE'
TRUST_TEST_ONLY = 'TEST_ONLY'
KNOWN_TRUST = (TRUST_VERIFIED, TRUST_TEST_ONLY)

REQUIRED_FIELDS = (
    'contract', 'issuer', 'request_id', 'resource', 'operation', 'request_digest',
    'received_at', 'nonce', 'evidence_kind', 'remote_identity', 'producer',
)

VERIFIER = {'name': 'identity_trust/current_identity.py', 'contract': CONTRACT,
            'version': '2.0.0'}


class WitnessError(ValueError):
    """证据/密钥/清单/账本不可核验。调用方必须失败关闭。"""


# ---------------------------------------------------------------- 严格 JSON
def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise WitnessError('duplicate JSON key: ' + str(key))
            result[key] = value
        return result

    def constant(value):
        raise WitnessError('non-finite JSON constant: ' + str(value))

    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, TypeError) as exc:
        raise WitnessError('invalid JSON: ' + str(exc)[:120]) from None


def canonical(value):
    """确定性序列化（签名与摘要对象）。"""
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


# ---------------------------------------------------------------- 安全读取
def _read_regular(path, *, limit, where, require_private=False):
    """以 fd 为单位安全读取普通文件（拒绝符号链接/非常规文件/超大文件）。"""
    if not path:
        raise WitnessError('{0}: no path configured'.format(where))
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_CLOEXEC', 0)
    try:
        fd = os.open(str(path), flags)
    except OSError as exc:
        raise WitnessError('{0}: unreadable or symlink refused ({1})'.format(
            where, exc.strerror or exc.errno)) from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise WitnessError('{0}: not a regular file'.format(where))
        if require_private and (info.st_mode & 0o077):
            raise WitnessError(
                '{0}: permissions too open (mode {1:o}); must be 0600'.format(
                    where, stat.S_IMODE(info.st_mode)))
        if info.st_size > limit:
            raise WitnessError('{0}: exceeds size limit'.format(where))
        chunks, total = [], 0
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise WitnessError('{0}: exceeds size limit'.format(where))
            chunks.append(chunk)
        return b''.join(chunks), info
    finally:
        os.close(fd)


def _rfc3339_to_epoch(value):
    if not isinstance(value, str) or not value:
        raise WitnessError('invalid timestamp')
    text = value.strip()
    if text.endswith('Z'):
        text = text[:-1] + '+00:00'
    import datetime as _dt
    try:
        parsed = _dt.datetime.fromisoformat(text)
    except ValueError:
        raise WitnessError('invalid RFC3339 timestamp') from None
    if parsed.tzinfo is None:
        raise WitnessError('timestamp must carry a timezone')
    return parsed.timestamp()


# ---------------------------------------------------------------- 请求摘要
def request_digest(envelope):
    """当前请求的规范化摘要（绑定 task_id 与目标点，不只是 id 字符串）。"""
    action = (envelope or {}).get('candidate_action') or {}
    target = action.get('target') or {}
    body = {
        'request_id': (envelope or {}).get('request_id'),
        'action_resource': action.get('action_resource'),
        'operation': action.get('operation'),
        'task_id': action.get('task_id'),
        'target': {key: target.get(key) for key in ('frame_id', 'x', 'y', 'z')},
    }
    try:
        return hashlib.sha256(canonical(body)).hexdigest()
    except (TypeError, ValueError):
        raise WitnessError('request digest unavailable (non-canonical envelope)') from None


# ---------------------------------------------------------------- 密钥
def load_key(path, *, require_private=True):
    """读取 HMAC 密钥：64 位十六进制，或 >=32 字节原始内容。"""
    raw, info = _read_regular(path, limit=MAX_KEY_BYTES, where='witness key',
                              require_private=require_private)
    text = raw.strip()
    if len(text) == 64:
        try:
            key = bytes.fromhex(text.decode('ascii'))
        except (ValueError, UnicodeDecodeError):
            key = text
    else:
        key = text
    if len(key) < 32:
        raise WitnessError('witness key too short (<32 bytes)')
    return key


def sign(body, key):
    return hmac.new(key, canonical(body), hashlib.sha256).hexdigest()


# ---------------------------------------------------------------- 证据与清单
def load_witness(path):
    raw, _info = _read_regular(path, limit=MAX_WITNESS_BYTES, where='witness')
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        raise WitnessError('witness is not UTF-8') from None
    document = strict_json(text)
    if not isinstance(document, dict):
        raise WitnessError('witness must be a JSON object')
    body = document.get('body')
    signature = document.get('signature')
    if not isinstance(body, dict) or not isinstance(signature, dict):
        raise WitnessError('witness must contain body and signature objects')
    return body, signature


def load_trusted_issuers(path):
    """读取受信任签发者清单。未配置时返回空清单（=> 永不 AUTHENTICATED）。"""
    if not path:
        return {}
    raw, _info = _read_regular(path, limit=MAX_ISSUERS_BYTES,
                               where='trusted issuers', require_private=True)
    try:
        document = strict_json(raw.decode('utf-8'))
    except UnicodeDecodeError:
        raise WitnessError('trusted issuers is not UTF-8') from None
    if not isinstance(document, dict) or document.get('contract') != ISSUER_CONTRACT:
        raise WitnessError('trusted issuers contract unsupported')
    entries = document.get('issuers')
    if not isinstance(entries, list):
        raise WitnessError('trusted issuers must be a list')
    result = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise WitnessError('issuer entry must be an object')
        issuer_id = entry.get('id')
        trust = entry.get('trust')
        if not isinstance(issuer_id, str) or not issuer_id.strip():
            raise WitnessError('issuer entry missing id')
        if trust not in KNOWN_TRUST:
            raise WitnessError('issuer {0!r} has unknown trust class {1!r}'.format(
                issuer_id, trust))
        if issuer_id in result:
            raise WitnessError('duplicate issuer id {0!r}'.format(issuer_id))
        result[issuer_id] = {'trust': trust,
                             'identity_source': str(entry.get('identity_source', ''))[:256],
                             'reviewed_by': str(entry.get('reviewed_by', ''))[:128]}
    return result


# ---------------------------------------------------------------- 账本
class Ledger:
    """追加式 JSONL 账本：原子 nonce 预留 + 历史授权复用检测。

    并发正确性
    ----------
    `peek` 与 `append` 分开调用会产生竞态（两个实例同时"没看到"同一 nonce）。
    因此对外只暴露 `reserve()`：在 `flock(LOCK_EX)` 临界区内**重读文件 → 判重 →
    追加 → fsync**，一个 nonce 只可能被预留一次。

    损坏处理
    --------
    * 完整但不可解析的行 -> `WitnessError('ledger corrupt')`（失败关闭）；
    * 末尾未以换行结束的残行 -> 视为崩溃残片，忽略但如实记录
      （`truncated_tail=True`），因为 O_APPEND 单次 write 的残片不可能对应
      "已成功预留"的决定。
    """

    def __init__(self, path):
        self.path = str(path) if path else None
        self.truncated_tail = False
        self.record_count = 0

    def _open(self):
        if not self.path:
            raise WitnessError('identity ledger not configured')
        flags = (os.O_RDWR | os.O_CREAT | os.O_APPEND
                 | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_CLOEXEC', 0))
        try:
            fd = os.open(self.path, flags, 0o600)
        except OSError as exc:
            raise WitnessError('ledger unopenable: {0}'.format(
                exc.strerror or exc.errno)) from None
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            os.close(fd)
            raise WitnessError('ledger must be a regular file')
        return fd

    @contextlib.contextmanager
    def _locked(self):
        fd = self._open()
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                yield fd
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    def _read_locked(self, fd):
        os.lseek(fd, 0, os.SEEK_SET)
        chunks, total = [], 0
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_LEDGER_BYTES:
                raise WitnessError('identity ledger exceeds size limit')
            chunks.append(chunk)
        text = b''.join(chunks).decode('utf-8', 'strict')
        records, truncated = [], False
        lines = text.split('\n')
        tail = lines.pop() if lines else ''
        if tail:
            truncated = True  # 末尾残片：忽略，不参与判重
        for line in lines:
            if not line.strip():
                continue
            item = strict_json(line)
            if not isinstance(item, dict):
                raise WitnessError('identity ledger record is not an object')
            records.append(item)
        self.truncated_tail = truncated
        self.record_count = len(records)
        return records

    def _reserve(self, kind, field, value, record):
        with self._locked() as fd:
            records = self._read_locked(fd)
            for item in records:
                if item.get('kind') == kind and item.get(field) == value:
                    return 'already_present'
            payload = dict(record)
            payload['kind'] = kind
            line = json.dumps(payload, ensure_ascii=False, sort_keys=True) + '\n'
            os.write(fd, line.encode('utf-8'))
            os.fsync(fd)
            return 'reserved'

    def reserve_nonce(self, nonce, record):
        """预留一个 nonce。返回 'reserved' 或 'already_present'。"""
        record = dict(record)
        record['nonce'] = nonce
        return self._reserve('nonce', 'nonce', nonce, record)

    def reserve_assessment(self, key, record):
        """预留一次历史证据解释。返回 'reserved' 或 'already_present'。"""
        record = dict(record)
        record['key'] = key
        return self._reserve('assessment', 'key', key, record)


# ---------------------------------------------------------------- 结果构造
def _base_result():
    return {
        'status': STATUS_UNKNOWN,
        'evidence_kind': 'NONE',
        'binding': 'UNBOUND_NO_TRUSTED_CURRENT_IDENTITY_WITNESS',
        'reason': ('没有可信证据把当前请求绑定到已认证 DDS 主体：'
                   'ROS 2 Jazzy 未提供获取订阅端对端主体身份的 API，'
                   '且业务 JSON 自报身份不构成认证'),
        'historical_only': False,
        'verifier': dict(VERIFIER),
        'checks': {'signature': 'NOT_PRESENT', 'issuer': 'NOT_EVALUATED',
                   'request_binding': 'NOT_CHECKED', 'freshness': 'NOT_CHECKED',
                   'replay': 'NOT_RESERVED'},
        'attestation': {},
        'producer': 'NOT_IMPLEMENTED: 现有 ROS 2 DDS API 不暴露当前请求主体身份',
    }


def contract_description():
    """可信证据产生组件必须满足的字段级契约（供交接与实现方使用）。"""
    return {
        'contract': CONTRACT,
        'required_fields': list(REQUIRED_FIELDS),
        'signature': {'alg': 'hmac-sha256', 'over': 'canonical JSON of body',
                      'key_source': 'trusted local config --identity-witness-key'},
        'request_digest': {'algorithm': 'sha256 of canonical JSON',
                           'fields': ['request_id', 'action_resource', 'operation',
                                      'task_id', 'target.{frame_id,x,y,z}']},
        'issuer': {'required': ['id', 'identity_source'],
                   'must_be_listed_in': 'trusted issuers file (--identity-issuers)'},
        'remote_identity.required': ['authenticated', 'security_identity'],
        'trust_note': ('签名只证明字节完整性。只有签发者被受信任清单标记为 '
                       'VERIFIED_IDENTITY_SOURCE 时，才可能得到 AUTHENTICATED；'
                       '仓库不交付任何此类清单，因此默认路径恒为 UNKNOWN。'),
        'producer_status': 'NOT_IMPLEMENTED',
    }


def f0_accepts(current_identity):
    """供 F0 调用的**唯一**判定入口（避免 F0 直接比较裸状态字符串）。

    必须同时满足：状态为 AUTHENTICATED、证据种类为签名证据、签发者已被
    受信任清单标记为已验证、nonce 已原子预留。任何一项缺失都视为"未绑定"。
    """
    if not isinstance(current_identity, dict):
        return False
    checks = current_identity.get('checks')
    if not isinstance(checks, dict):
        return False
    return (
        current_identity.get('status') == STATUS_AUTHENTICATED
        and current_identity.get('evidence_kind') == EVIDENCE_KIND_SIGNED
        and checks.get('signature') == 'VALID'
        and checks.get('issuer') == TRUST_VERIFIED
        and checks.get('request_binding') == 'MATCH'
        and checks.get('freshness') == 'OK'
        and checks.get('replay') == 'RESERVED'
        and current_identity.get('historical_only') is False
    )


# ---------------------------------------------------------------- 核验
def verify(envelope, witness_path, key_path, *, issuers_path=None,
           ledger=None, ledger_error=None, now=None):
    """核验当前请求身份绑定证据，返回 `current_request_identity` 字典。

    永不抛异常：任何不满足条件的情况都返回 `status != AUTHENTICATED`。
    """
    now = time.time() if now is None else float(now)
    result = _base_result()
    if not witness_path:
        return result

    try:
        issuers = load_trusted_issuers(issuers_path)
    except WitnessError as exc:
        result.update(binding='WITNESS_ISSUER_CLOCK_UNUSABLE',
                      reason='受信任签发者清单不可核验：' + str(exc)[:200])
        result['checks']['issuer'] = 'ERROR'
        return result

    try:
        body, signature = load_witness(witness_path)
        key = load_key(key_path)
        if signature.get('alg') != 'hmac-sha256':
            raise WitnessError('unsupported signature algorithm')
        if not hmac.compare_digest(str(signature.get('value', '')), sign(body, key)):
            raise WitnessError('witness signature invalid')
        result['checks']['signature'] = 'VALID'
        if body.get('contract') not in SUPPORTED_CONTRACTS:
            raise WitnessError('unsupported witness contract')
        for field in REQUIRED_FIELDS:
            if field not in body:
                raise WitnessError('witness missing field: ' + field)
        if body.get('evidence_kind') != EVIDENCE_KIND:
            raise WitnessError('unsupported evidence kind')
        remote = body.get('remote_identity')
        if not isinstance(remote, dict):
            raise WitnessError('witness remote_identity must be an object')
    except WitnessError as exc:
        result.update(binding='WITNESS_REJECTED', reason=str(exc)[:400])
        result['checks']['signature'] = ('INVALID'
                                         if 'signature' in str(exc) else
                                         result['checks']['signature'])
        return result

    # 判定顺序（有意如此）
    # ------------------
    # 签名 -> 字段 -> **请求绑定** -> 新鲜度 -> 签发者信任 -> 原子预留。
    # 请求绑定放在信任判定之前：证据属于别的请求时，无论签发者多可信都必须先拒绝；
    # 签发者信任放在预留之前：不可信签发者不得消耗账本条目（避免被用来刷日志）。
    issuer_body = body.get('issuer')
    if not isinstance(issuer_body, dict):
        result.update(binding='WITNESS_ISSUER_UNDECLARED',
                      reason='证据未声明签发者，无法判断身份来源是否可信')
        result['checks']['issuer'] = 'NOT_DECLARED'
        return result
    issuer_id = str(issuer_body.get('id', ''))[:128]

    # 远程身份声明
    if remote.get('authenticated') is not True:
        result.update(status=STATUS_DENIED, evidence_kind=EVIDENCE_KIND_SIGNED,
                      binding='WITNESS_REMOTE_NOT_AUTHENTICATED',
                      reason='证据声明远端主体未通过认证')
        return result

    # 请求绑定
    action = (envelope or {}).get('candidate_action') or {}
    problems = []
    if body.get('request_id') != envelope.get('request_id'):
        problems.append('request_id')
    if body.get('resource') != action.get('action_resource'):
        problems.append('resource')
    if body.get('operation') != action.get('operation'):
        problems.append('operation')
    try:
        digest = request_digest(envelope)
    except WitnessError:
        problems.append('digest_unavailable')
        digest = None
    if digest is not None and body.get('request_digest') != digest:
        problems.append('request_digest')
    if problems:
        result.update(binding='WITNESS_REQUEST_BINDING_MISMATCH',
                      reason='证据与当前请求不匹配：' + ','.join(problems))
        result['checks']['request_binding'] = 'MISMATCH'
        return result
    result['checks']['request_binding'] = 'MATCH'

    # 新鲜度
    try:
        received = _rfc3339_to_epoch(body.get('received_at'))
    except WitnessError as exc:
        result.update(binding='WITNESS_TIMESTAMP_INVALID', reason=str(exc)[:200])
        result['checks']['freshness'] = 'INVALID'
        return result
    if received - now > MAX_CLOCK_SKEW_SEC:
        result.update(binding='WITNESS_FROM_FUTURE',
                      reason='证据时间戳晚于本地时钟允许的偏差')
        result['checks']['freshness'] = 'FROM_FUTURE'
        return result
    if now - received > MAX_REMOTE_AGE_SEC:
        result.update(binding='WITNESS_STALE',
                      reason='证据已超出新鲜度窗口（{0:.0f}s）'.format(MAX_REMOTE_AGE_SEC))
        result['checks']['freshness'] = 'STALE'
        return result
    result['checks']['freshness'] = 'OK'

    # 签发者信任判定（必须在签名与绑定之后：先证完整与归属，再谈信任）
    entry = issuers.get(issuer_id)
    if entry is None:
        result.update(binding='WITNESS_ISSUER_UNTRUSTED',
                      reason=('签发者 {0!r} 不在受信任清单内：签名有效只证明字节完整，'
                              '不证明其掌握任何已认证 DDS 身份').format(issuer_id))
        result['checks']['issuer'] = 'NOT_LISTED'
        return result
    result['checks']['issuer'] = entry['trust']
    result['attestation'] = {'issuer_id': issuer_id,
                             'identity_source': entry['identity_source'] or
                             str(issuer_body.get('identity_source', ''))[:256]}
    result['attestation']['request_digest'] = str(body.get('request_digest'))[:64]

    # 原子防重放（AUTHENTICATED 的前置条件，不是可选项）
    nonce = body.get('nonce')
    if not isinstance(nonce, str) or len(nonce) != NONCE_HEX_LEN or \
            any(ch not in '0123456789abcdef' for ch in nonce):
        result.update(binding='WITNESS_NONCE_INVALID', reason='nonce 格式非法')
        result['checks']['replay'] = 'NONCE_INVALID'
        return result
    if ledger is None:
        result.update(binding='WITNESS_LEDGER_UNAVAILABLE',
                      reason=('未配置可用的重放账本（{0}）：无法排除重放，'
                              '因此不得判定为已认证').format(
                                  ledger_error or 'not configured'))
        result['checks']['replay'] = 'LEDGER_UNAVAILABLE'
        return result
    try:
        outcome = ledger.reserve_nonce(nonce, {
            'request_id': body.get('request_id'),
            'resource': body.get('resource'),
            'issuer': issuer_id,
            'ts': int(now),
        })
    except WitnessError as exc:
        result.update(binding='WITNESS_LEDGER_WRITE_FAILED',
                      reason='重放账本不可用（{0}）；维持 UNKNOWN'.format(str(exc)[:160]))
        result['checks']['replay'] = 'LEDGER_ERROR'
        return result
    if outcome == 'already_present':
        result.update(binding='WITNESS_NONCE_REPLAYED',
                      reason='该证据的 nonce 已使用过（重放）')
        result['checks']['replay'] = 'REPLAYED'
        return result
    result['checks']['replay'] = 'RESERVED'

    # 到这里：完整、可信签发者、绑定、新鲜、首次使用
    if entry['trust'] == TRUST_TEST_ONLY:
        result.update(status=STATUS_TEST_ONLY, evidence_kind=EVIDENCE_KIND_SIGNED,
                      binding='TEST_ONLY_ISSUER_ATTESTATION',
                      reason=('签名与绑定均成立，但签发者仅为 TEST_ONLY 角色：'
                              '不得作为在线身份授权依据'))
    else:
        result.update(status=STATUS_AUTHENTICATED, evidence_kind=EVIDENCE_KIND_SIGNED,
                      binding='CURRENT_REQUEST_BOUND_TO_AUTHENTICATED_DDS_SUBJECT',
                      reason='受信任签发者证明当前请求主体已通过 DDS 身份认证')
    result['attestation']['security_identity'] = str(
        remote.get('security_identity', ''))[:256]
    return result


def assessment_key(case_id, experiment_run, request_id, resource):
    """历史证据解释的业务键。同一键再次出现即为历史授权复用。"""
    raw = '\x00'.join([str(case_id), str(experiment_run), str(request_id),
                       str(resource)]).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()
