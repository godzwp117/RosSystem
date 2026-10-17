#!/usr/bin/env python3
"""当前请求身份绑定：证据契约、受信任核验与重放检测。

为什么需要这个文件
==================
历史受控实验（S2/S3/S3C/S4）证明的是**当时那次运行中**某个已认证 DDS 主体
对某个资源的访问结果。它不能证明**当前**这条候选 Action 请求来自同一个
已认证主体。把历史 `AUTHORIZED` 直接当成"当前请求已通过身份认证"，
就是本项目的核心安全语义错误之一。

本文件因此把"当前请求身份绑定"单独抽出来，与历史证据解释（assessor.py）
彻底分离：

* 历史证据 -> `status` / `identity_evidence` / `authorization`（原有语义不变）；
* 当前请求身份 -> `extensions.current_request_identity`（本文件负责）。

现状（必须如实记录，不得含糊）
==============================
ROS 2 Jazzy + rclpy **没有**公开稳定的 API 让订阅端在收到样本时取得
"该样本发布者已完成 DDS-Security 认证的身份"。DDS-Security 的认证发生在
参与者发现/建链阶段；rclpy 的 `Subscription` 回调只给出反序列化后的消息，
不给出远端参与者的安全身份；Fast DDS 的 `DataReaderListener`/`on_data_available`
同样不携带身份信息，且未通过 rclpy 暴露。

因此 **"可信证据产生组件"目前不存在**，本项目不做以下任何一种伪造：

* 不从 `request_id` 推断身份；
* 不把业务 JSON 自报的 `declared_enclave` / 节点名 / `producer` 当作已认证身份；
* 不声称 `/rg/guarded_navigate` 的发送方已经过 DDS 认证。

本文件提供的是**可信证据的契约与核验器**：一旦（未来）有可信组件能产出
带签名的绑定证据，这里的核验逻辑即可启用；在此之前，默认路径恒为
`UNKNOWN`，且 F0 适配层要求 `AUTHENTICATED` 才允许推进，所以当前真实
链路的正确结果是**阻断**，而不是"看起来通过了"。

信任锚
======
证据必须由受信任本地配置（`--identity-witness-key`）指定的密钥做
HMAC-SHA256 签名；密钥与证据路径都**只能来自进程参数（受信任配置）**，
绝不从 stdin / 业务 JSON 读取。业务输入无法伪造一条能通过核验的证据，
除非攻击者已经拿到本地密钥——那已经超出本模块的防护边界。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time

CONTRACT = 'current-identity-witness/1'
SUPPORTED_CONTRACTS = (CONTRACT,)
#: 只接受这一种证据种类。'''MIDDLEWARE_IDENTITY_BINDING''' 表示
#: "由 DDS 中间件安全层产生的、针对当前请求的主体绑定"。
EVIDENCE_KIND = 'MIDDLEWARE_IDENTITY_BINDING'
MAX_WITNESS_BYTES = 64 * 1024
MAX_REMOTE_AGE_SEC = 30.0
MAX_CLOCK_SKEW_SEC = 5.0
NONCE_HEX_LEN = 32

STATUS_UNKNOWN = 'UNKNOWN'
STATUS_AUTHENTICATED = 'AUTHENTICATED'
STATUS_DENIED = 'DENIED'

REQUIRED_FIELDS = (
    'contract', 'request_id', 'resource', 'operation', 'received_at', 'nonce',
    'evidence_kind', 'remote_identity', 'producer',
)


class WitnessError(ValueError):
    """证据本身不可核验。调用方必须失败关闭。"""


def contract_description():
    """返回可信证据产生组件必须输出的字段清单（供文档与交接使用）。"""
    return {
        'contract': CONTRACT,
        'required_fields': list(REQUIRED_FIELDS),
        'signature': {'alg': 'hmac-sha256', 'over': 'canonical JSON of body',
                      'key_source': 'trusted local config --identity-witness-key'},
        'remote_identity.required': ['authenticated', 'security_identity'],
        'semantics': ('一条证据只能绑定一个 request_id + resource + operation + 时间窗；'
                      'nonce 由产生组件生成并只使用一次；'
                      '不得由业务 JSON 构造'),
        'producer_status': 'NOT_IMPLEMENTED: 现有 ROS 2 DDS API 不暴露当前请求主体身份',
    }


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

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def canonical(body):
    """证据体的确定性序列化（签名对象）。"""
    return json.dumps(body, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


# ---------------------------------------------------------------- 密钥
def load_key(path):
    """读取 HMAC 密钥。接受 64 位十六进制或 >=32 字节原始内容。"""
    if not path:
        raise WitnessError('no trusted witness key configured')
    try:
        raw = open(path, 'rb').read(4096)
    except OSError as exc:
        raise WitnessError('witness key unreadable: ' + type(exc).__name__) from None
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


# ---------------------------------------------------------------- 读取
def load_witness(path):
    if not path:
        raise WitnessError('no witness path configured')
    try:
        size = os.path.getsize(path)
    except OSError as exc:
        raise WitnessError('witness unreadable: ' + type(exc).__name__) from None
    if size > MAX_WITNESS_BYTES:
        raise WitnessError('witness exceeds size limit')
    try:
        raw = open(path, 'rb').read(MAX_WITNESS_BYTES + 1)
    except OSError as exc:
        raise WitnessError('witness unreadable: ' + type(exc).__name__) from None
    if len(raw) > MAX_WITNESS_BYTES:
        raise WitnessError('witness exceeds size limit')
    document = strict_json(raw.decode('utf-8'))
    if not isinstance(document, dict):
        raise WitnessError('witness must be a JSON object')
    body = document.get('body')
    signature = document.get('signature')
    if not isinstance(body, dict) or not isinstance(signature, dict):
        raise WitnessError('witness must contain body and signature objects')
    return body, signature


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


# ---------------------------------------------------------------- 账本
class Ledger:
    """追加式 JSONL 账本：检测 nonce 重放与同一请求的历史授权复用。

    账本路径只能来自受信任本地配置。写入失败时调用方必须失败关闭
    （否则"重放检测"形同不存在）。
    """

    def __init__(self, path):
        self.path = path
        self.records = []
        if path and os.path.isfile(path):
            with open(path, 'r', encoding='utf-8') as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        item = strict_json(line)
                    except (ValueError, WitnessError):
                        raise WitnessError('identity ledger is corrupt') from None
                    if isinstance(item, dict):
                        self.records.append(item)

    def seen_nonce(self, nonce):
        return any(item.get('kind') == 'nonce' and item.get('nonce') == nonce
                   for item in self.records)

    def seen_assessment(self, key):
        return any(item.get('kind') == 'assessment' and item.get('key') == key
                   for item in self.records)

    def append(self, record):
        if not self.path:
            return False
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(self.path, 'a', encoding='utf-8') as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + '\n')
            handle.flush()
            os.fsync(handle.fileno())
        self.records.append(record)
        return True


# ---------------------------------------------------------------- 核验
def verify(envelope, witness_path, key_path, ledger=None, now=None):
    """核验当前请求身份绑定证据，返回 `current_request_identity` 字典。

    返回字段固定为：
      status      AUTHENTICATED / DENIED / UNKNOWN
      evidence_kind  NONE / MIDDLEWARE_IDENTITY_BINDING
      binding     绑定结论（机器可读）
      reason      人类可读理由（<= 512 字符）
      historical_only  恒为 False（本对象只描述当前请求）
    """
    now = time.time() if now is None else float(now)
    result = {
        'status': STATUS_UNKNOWN,
        'evidence_kind': 'NONE',
        'binding': 'UNBOUND_NO_TRUSTED_CURRENT_IDENTITY_WITNESS',
        'reason': ('没有可信证据把当前请求绑定到已认证 DDS 主体：'
                   'ROS 2 Jazzy 未提供获取订阅端对端主体身份的 API，'
                   '且业务 JSON 自报身份不构成认证'),
        'historical_only': False,
        'producer': contract_description()['producer_status'],
    }

    if not witness_path:
        return result

    try:
        body, signature = load_witness(witness_path)
        key = load_key(key_path)
        if signature.get('alg') != 'hmac-sha256':
            raise WitnessError('unsupported signature algorithm')
        expected = sign(body, key)
        if not hmac.compare_digest(str(signature.get('value', '')), expected):
            raise WitnessError('witness signature invalid')
        if body.get('contract') not in SUPPORTED_CONTRACTS:
            raise WitnessError('unsupported witness contract')
        for field in REQUIRED_FIELDS:
            if field not in body:
                raise WitnessError('witness missing field: ' + field)
        remote = body.get('remote_identity')
        if not isinstance(remote, dict):
            raise WitnessError('witness remote_identity must be an object')
        if remote.get('authenticated') is not True:
            result.update(status=STATUS_DENIED, binding='WITNESS_REMOTE_NOT_AUTHENTICATED',
                          reason='可信证据显示远端主体未通过 DDS 认证')
            return result
        if body.get('evidence_kind') != EVIDENCE_KIND:
            raise WitnessError('unsupported evidence kind')
        if body.get('request_id') != envelope.get('request_id'):
            # 身份错绑 / 串单：证据属于另一条请求
            result.update(binding='WITNESS_REQUEST_ID_MISMATCH',
                          reason='证据绑定的是另一条 request_id，不能用于当前请求（串单）')
            return result
        action = envelope.get('candidate_action') or {}
        if body.get('resource') != action.get('action_resource'):
            result.update(binding='WITNESS_RESOURCE_MISMATCH',
                          reason='证据绑定的资源与当前候选资源不同（跨资源复用）')
            return result
        if body.get('operation') != action.get('operation'):
            result.update(binding='WITNESS_OPERATION_MISMATCH',
                          reason='证据绑定的操作与当前候选操作不同')
            return result
        nonce = body.get('nonce')
        if not isinstance(nonce, str) or len(nonce) != NONCE_HEX_LEN or \
                any(ch not in '0123456789abcdef' for ch in nonce):
            raise WitnessError('invalid nonce')
        received = _rfc3339_to_epoch(body.get('received_at'))
        if received - now > MAX_CLOCK_SKEW_SEC:
            result.update(binding='WITNESS_FROM_FUTURE',
                          reason='证据时间戳晚于本地时钟允许的偏差')
            return result
        if now - received > MAX_REMOTE_AGE_SEC:
            result.update(binding='WITNESS_STALE',
                          reason='证据已超出新鲜度窗口（{0:.0f}s）'.format(MAX_REMOTE_AGE_SEC))
            return result
        if ledger is not None and ledger.seen_nonce(nonce):
            result.update(binding='WITNESS_NONCE_REPLAYED',
                          reason='该证据的 nonce 已使用过（重放）')
            return result
    except WitnessError as exc:
        result.update(binding='WITNESS_REJECTED', reason=str(exc)[:400])
        return result

    if ledger is not None:
        try:
            ledger.append({'kind': 'nonce', 'nonce': nonce,
                           'request_id': body.get('request_id'),
                           'ts': int(now)})
        except OSError as exc:
            result.update(binding='WITNESS_LEDGER_WRITE_FAILED',
                          reason='重放账本写入失败（{0}）；维持 UNKNOWN'.format(
                              type(exc).__name__))
            return result

    result.update(status=STATUS_AUTHENTICATED,
                  evidence_kind=EVIDENCE_KIND,
                  binding='CURRENT_REQUEST_BOUND_TO_AUTHENTICATED_DDS_SUBJECT',
                  reason='可信签名证据把当前请求的发布者绑定到已认证 DDS 主体')
    result['security_identity'] = str(remote.get('security_identity'))[:256]
    return result


def assessment_key(case_id, experiment_run, request_id, resource):
    """历史证据解释的业务键。同一键再次出现即为历史授权复用。"""
    raw = '\x00'.join([str(case_id), str(experiment_run), str(request_id),
                       str(resource)]).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()
