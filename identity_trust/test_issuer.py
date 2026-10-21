#!/usr/bin/env python3
"""受控测试用**签发器**（TEST_ONLY）：只能产生"签名与绑定成立"的证据。

这个文件为什么存在
==================
第二阶段审查确认：本系统**没有**任何组件能拿到"当前请求的 DDS 已认证主体身份"。
因此真实的签发端不存在，也不允许被伪造。但核验器的正例必须可测——
否则我们无法证明"核验器在证据齐全时确实会判 AUTHENTICATED"。

于是提供这个**明确标注为测试**的签发器：

* 它只能签发 `issuer.id` 以 `test-only:` 开头的证据；
* 它拒绝 `--trust verified`（不存在任何"已验证身份来源"可供它声称）；
* 产出的证据必须配一份 `trust: TEST_ONLY` 的受信任清单，核验结果因此只能是
  `AUTHENTICATED_TEST_ONLY`，`f0_accepts()` 恒为 False；
* 它不会、也不能把 `ONLINE_PROCEED_READY` 从 FAIL 变成 PASS。

用法（测试夹具）
================
```bash
python3 identity_trust/test_issuer.py --i-am-a-controlled-test-issuer \
    --key /tmp/test.key --issuer-id test-only:unit \
    --envelope envelope.json --out /tmp/witness.json
```

缺少 `--i-am-a-controlled-test-issuer` 时直接拒绝执行，避免被误接进生产流程。
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from identity_trust import current_identity as ci  # noqa: E402

TEST_ONLY_PREFIX = 'test-only:'


def build_attestation(envelope, issuer_id, security_identity, *, now=None,
                      nonce=None):
    """构造一条 TEST_ONLY 证据体（不含签名）。"""
    if not issuer_id.startswith(TEST_ONLY_PREFIX):
        raise ValueError('test issuer must use the {0!r} prefix'.format(TEST_ONLY_PREFIX))
    action = envelope['candidate_action']
    moment = datetime.fromtimestamp(
        time.time() if now is None else now, timezone.utc
    ).strftime('%Y-%m-%dT%H:%M:%SZ')
    return {
        'contract': ci.CONTRACT,
        'issuer': {'id': issuer_id,
                   'identity_source': 'TEST_ONLY_SYNTHETIC',
                   'assertion': 'CONTROLLED_TEST: not a DDS identity observation'},
        'request_id': envelope['request_id'],
        'resource': action['action_resource'],
        'operation': action['operation'],
        'request_digest': ci.request_digest(envelope),
        'received_at': moment,
        'nonce': nonce or secrets.token_hex(16),
        'evidence_kind': ci.EVIDENCE_KIND,
        'remote_identity': {'authenticated': True,
                            'security_identity': security_identity},
        'producer': {'name': 'identity_trust/test_issuer.py',
                     'version': '1.0.0',
                     'scope': 'CONTROLLED_TEST'},
    }


def sign_attestation(body, key):
    return {'alg': 'hmac-sha256', 'value': ci.sign(body, key)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--i-am-a-controlled-test-issuer', action='store_true',
                        help='必须显式确认这是受控测试签发器')
    parser.add_argument('--key', required=True, help='HMAC 密钥文件（0600）')
    parser.add_argument('--issuer-id', default='test-only:unit',
                        help='必须形如 test-only:<name>')
    parser.add_argument('--security-identity', default='sros2://TEST_ONLY/unknown',
                        help='仅作字段填充；不代表任何真实主体')
    parser.add_argument('--envelope', required=True, help='待绑定的信封 JSON')
    parser.add_argument('--out', required=True, help='输出证据文件')
    parser.add_argument('--nonce', help='覆盖 nonce（仅测试重放用）')
    parser.add_argument('--trust', choices=['test-only'], default='test-only',
                        help='只允许 test-only；不存在 verified 选项')
    args = parser.parse_args(argv)

    if not args.i_am_a_controlled_test_issuer:
        print('REFUSED: this is a CONTROLLED_TEST issuer; pass '
              '--i-am-a-controlled-test-issuer to acknowledge', file=sys.stderr)
        return 2
    try:
        key = ci.load_key(args.key)
    except ci.WitnessError as exc:
        print('KEY_INVALID: {0}'.format(exc), file=sys.stderr)
        return 2
    try:
        envelope = ci.strict_json(Path(args.envelope).read_text(encoding='utf-8'))
    except (OSError, ci.WitnessError) as exc:
        print('ENVELOPE_INVALID: {0}'.format(exc), file=sys.stderr)
        return 2
    try:
        body = build_attestation(envelope, args.issuer_id, args.security_identity,
                                 nonce=args.nonce)
    except (KeyError, TypeError, ValueError, ci.WitnessError) as exc:
        print('ATTESTATION_FAILED: {0}'.format(exc), file=sys.stderr)
        return 2
    document = {'body': body, 'signature': sign_attestation(body, key)}
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(document, indent=2, ensure_ascii=False),
                      encoding='utf-8')
    os.chmod(target, 0o600)
    print(json.dumps({'witness': str(target), 'issuer': args.issuer_id,
                      'scope': 'CONTROLLED_TEST',
                      'note': 'TEST_ONLY: 核验结果最多为 AUTHENTICATED_TEST_ONLY'}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
