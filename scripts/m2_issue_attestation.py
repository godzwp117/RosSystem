#!/usr/bin/env python3
"""m2_issue_attestation.py -- 用"真实观察到的 DDS 身份"签发 F0 可核验的凭据（专项③ P1）。

它处在什么位置
--------------
C++ 见证组件（`src/m2_witness/m2_identity_witness.cpp`）通过 Fast DDS 的
`ParticipantProxyData::identity_token_` **真实观察到**：某个 GUID 前缀的对端
Participant 已经过 PKI-DH 认证，且其证书主体是 `dds.cert.sn`（例如 `/CN=/m2_peer`）。

本脚本把这条**原生观察**转成 F0 能核验的凭据（`current-identity-attestation/2`）：

    body = {contract, issuer, request_id, resource, operation, request_digest,
            received_at, nonce, evidence_kind, remote_identity, producer}
    signature = HMAC-SHA256(canonical(body), key)

其中 `remote_identity.security_identity` **必须**来自见证日志里真实出现过、
且与要求身份完全一致的那条记录；找不到就拒绝签发。

它究竟证明了什么（必须精确）
--------------------------
* 证明了：**存在一个已通过 DDS-Security PKI-DH 认证的 Participant，
  其证书主体为 X**（这是原生 DDS 身份，不是自报）。
* **没有**证明：某条具体的 Action 请求是由该 Participant 发出的。
  本脚本把请求摘要与"被观察到的已认证主体"绑定，这个绑定动作发生在
  **受保护入口**这一侧；因此其安全语义是
  `TRUSTED_INGRESS_AUTHORIZED`，而不是 `DDS_REQUEST_ORIGIN_BOUND`。

要跨到后者，见证组件必须自己订阅 Action goal 话题并读取
`SampleInfo.sample_identity().writer_guid()`，把 writer 所属 Participant
与凭据直接绑定 —— 那是尚未完成的下一步（见报告）。

用法
----
    python3 scripts/m2_issue_attestation.py \
        --witness-log witness_probe.log --identity /CN=/m2_peer \
        --envelope envelope.json --key att.key --out witness.json
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import secrets
import sys
import time
from datetime import datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from identity_trust import current_identity as ci  # noqa: E402


def now_iso():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def observed_identities(witness_log):
    """从见证日志中提取所有"真实观察到"的已认证身份。

    只接受 `has_identity=true` 且带 `dds.cert.sn` 的记录；
    证书主体为空的一律忽略（未启用安全时就是这样）。
    """
    found = []
    with open(witness_log, encoding='utf-8') as fh:
        for line in fh:
            line = line.strip()
            if not line.startswith('{'):
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if record.get('event') != 'participant_discovered':
                continue
            token = record.get('identity_token') or {}
            properties = token.get('properties') or {}
            cert = properties.get('dds.cert.sn')
            if not cert:
                continue
            found.append({
                'guid_prefix': record.get('guid_prefix'),
                'participant_name': record.get('name'),
                'security_identity': cert,
                'cert_algo': properties.get('dds.cert.algo'),
                'ca_subject': properties.get('dds.ca.sn'),
                'token_class': token.get('class_id'),
                'security_attributes': record.get('security_attributes'),
            })
    return found


def main(argv=None):
    parser = argparse.ArgumentParser(description='用真实观察到的 DDS 身份签发凭据')
    parser.add_argument('--witness-log', required=True)
    parser.add_argument('--identity', required=True,
                        help='要求的证书主体，例如 /CN=/m2_peer')
    parser.add_argument('--envelope', required=True)
    parser.add_argument('--key', required=True, help='HMAC 密钥文件（0600）')
    parser.add_argument('--out', required=True)
    parser.add_argument('--issuer-id', default='issuer:dds-witness')
    parser.add_argument('--ledger', default=None,
                        help='仅用于记录；nonce 的权威消费在 F0 侧')
    parser.add_argument('--nonce', default=None)
    parser.add_argument('--received-at', default=None)
    args = parser.parse_args(argv)

    observations = observed_identities(args.witness_log)
    matched = [o for o in observations if o['security_identity'] == args.identity]
    if not matched:
        print(json.dumps({
            'result': 'REFUSED',
            'reason': ('见证日志中没有出现证书主体为 %r 的已认证 Participant；'
                       '不得凭空签发身份凭据' % args.identity),
            'observed': sorted({o['security_identity'] for o in observations}),
        }, ensure_ascii=False, indent=2))
        return 3
    observation = matched[0]

    envelope = json.load(open(args.envelope, encoding='utf-8'))
    action = envelope.get('candidate_action') or {}
    key = ci.load_key(args.key)
    nonce = args.nonce or secrets.token_hex(16)
    if len(nonce) != 32 or any(c not in '0123456789abcdef' for c in nonce):
        print(json.dumps({'result': 'REFUSED', 'reason': 'nonce 必须是 32 位十六进制'}))
        return 4

    body = {
        'contract': ci.CONTRACT,
        # 契约要求 issuer 是对象（含 id），不是字符串；
        # 写成字符串会让 verify() 判为"未声明签发者"。
        'issuer': {'id': args.issuer_id,
                   'identity_source': 'FASTDDS_IDENTITY_TOKEN',
                   'reviewed_by': 'm2-research'},
        'request_id': envelope.get('request_id'),
        'resource': action.get('action_resource'),
        'operation': action.get('operation'),
        'request_digest': ci.request_digest(envelope),
        'received_at': args.received_at or now_iso(),
        'nonce': nonce,
        'evidence_kind': ci.EVIDENCE_KIND,
        'remote_identity': {
            # 这一行**是**原生 DDS 身份：来自 ParticipantProxyData::identity_token_
            'authenticated': True,
            'security_identity': observation['security_identity'],
            'source': 'FASTDDS_IDENTITY_TOKEN',
            'token_class': observation['token_class'],
            'cert_algo': observation['cert_algo'],
            'ca_subject': observation['ca_subject'],
            'guid_prefix': observation['guid_prefix'],
            'participant_name': observation['participant_name'],
            'security_attributes': observation['security_attributes'],
        },
        'producer': {
            'component': 'src/m2_witness/m2_identity_witness.cpp',
            'observation': 'on_participant_discovery + ParticipantProxyData::identity_token_',
        },
    }
    document = {'body': body,
                'signature': {'alg': 'hmac-sha256',
                              'value': ci.sign(body, key)}}
    with open(args.out, 'w', encoding='utf-8') as fh:
        json.dump(document, fh, ensure_ascii=False, indent=2)
    print(json.dumps({
        'result': 'ISSUED',
        'out': args.out,
        'security_identity': observation['security_identity'],
        'guid_prefix': observation['guid_prefix'],
        'request_id': body['request_id'],
        'request_digest': body['request_digest'][:16] + '...',
        'nonce': nonce,
        'semantics': ('TRUSTED_INGRESS_AUTHORIZED：'
                      '已认证 DDS 主体由原生 token 证实，'
                      '但请求与该主体的绑定由受保护入口完成，'
                      '不等于 DDS_REQUEST_ORIGIN_BOUND'),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
