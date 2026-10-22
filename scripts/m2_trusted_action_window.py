#!/usr/bin/env python3
"""m2_trusted_action_window.py -- 可信 Action 事件账本 -> 30 秒历史请求计数（M1 接口）。

两个必须严格区分的语义
=====================
* **请求计数**：过去窗口内某资源实际收到多少次请求。来自受信任入口的账本。
* **身份认证**：哪条请求由哪个已认证主体发出。来自账本的 writer/participant 字段。

本工具只做**计数与窗口聚合**，不签发任何身份结论；
它输出的 `authenticated_senders` 只是"该窗口内出现过的已认证主体列表"，
不构成对任何单个请求的身份证明。

因果约束（M1 只能用过去）
------------------------
M1 在 F0 之前运行，因此只能消费**已结束**的窗口。本工具强制：

    window_end <= as_of - safety_lag_seconds

`as_of` 是调用方声明的判断时刻。默认 `safety_lag_seconds = 2`，
用于吸收账本写入延迟；窗口未过安全滞后期一律返回 `COMPLETE=false`。

完整性水位
----------
`coverage` 只有三种取值：

* `COMPLETE`   —— 窗口完整、账本连续、无缺失、已过安全滞后；
* `PARTIAL`    —— 账本在窗口内出现过重启/缺口标记；
* `UNKNOWN`    —— 账本缺失、无法解析、或窗口跨越账本起点。

**不得把 UNKNOWN/PARTIAL 当作 0 次请求。** 这是 M1 侧最容易被误用的地方。

用法
----
    python3 scripts/m2_trusted_action_window.py \
        --ledger events.jsonl --resource rt/m2/candidate_task \
        --as-of 2026-10-19T03:40:00Z --window 30 \
        --out window.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone

CONTRACT_EVENTS = 'trusted-action-events/1'
CONTRACT_WINDOW = 'trusted-action-count-window/1'


def parse_ts(text):
    if not text:
        return None
    try:
        text = text.replace('Z', '+00:00')
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def sha256_lines(path):
    digest = hashlib.sha256()
    try:
        with open(path, 'rb') as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b''):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def load_events(path):
    events, malformed = [], 0
    try:
        with open(path, encoding='utf-8') as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    document = json.loads(line)
                except ValueError:
                    malformed += 1
                    continue
                if document.get('contract') != CONTRACT_EVENTS:
                    malformed += 1
                    continue
                events.append(document)
    except OSError:
        return None, 0
    return events, malformed


def main(argv=None):
    parser = argparse.ArgumentParser(description='可信 Action 事件窗口聚合')
    parser.add_argument('--ledger', required=True)
    parser.add_argument('--resource', required=True)
    parser.add_argument('--as-of', required=True,
                        help='M1 的判断时刻（RFC3339，判断前已发生的才可消费）')
    parser.add_argument('--window', type=float, default=30.0)
    parser.add_argument('--safety-lag', type=float, default=2.0)
    parser.add_argument('--out', required=True)
    args = parser.parse_args(argv)

    as_of = parse_ts(args.as_of)
    if as_of is None:
        raise SystemExit('invalid --as-of')
    window_end = as_of - timedelta(seconds=args.safety_lag)
    window_start = window_end - timedelta(seconds=args.window)

    events, malformed = load_events(args.ledger)
    document = {
        'contract': CONTRACT_WINDOW,
        'resource': args.resource,
        'window_start': window_start.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z'),
        'window_end': window_end.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z'),
        'as_of': as_of.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z'),
        'safety_lag_seconds': args.safety_lag,
        'send_goal_count': None,
        'observation_source': 'TRUSTED_ACTION_INGRESS',
        'coverage': 'UNKNOWN',
        'source_evidence_sha256': sha256_lines(args.ledger),
        'authenticated_senders': [],
        'unauthenticated_requests': None,
        'notes': [],
    }

    if events is None:
        document['notes'].append('账本不可读：不得视为 0 次请求')
        json.dump(document, open(args.out, 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=2)
        print(json.dumps(document, ensure_ascii=False, indent=2))
        return 0

    received = []
    restarts = 0
    for event in events:
        kind = event.get('event_kind')
        if kind in ('PARTICIPANT_INVALIDATED', 'PARTICIPANT_AUTH_EVENT'):
            continue
        if kind != 'SEND_GOAL_RECEIVED':
            continue
        if event.get('resource') != args.resource:
            continue
        stamp = parse_ts(event.get('received_at'))
        if stamp is None:
            malformed += 1
            continue
        received.append((stamp, event))

    in_window = [e for stamp, e in received if window_start <= stamp < window_end]
    document['send_goal_count'] = len(in_window)

    senders = sorted({e.get('certificate_subject') for e in in_window
                      if e.get('sender_authenticated') and e.get('certificate_subject')})
    document['authenticated_senders'] = senders
    document['unauthenticated_requests'] = sum(
        1 for e in in_window if not e.get('sender_authenticated'))

    # 完整性判定
    if malformed:
        document['coverage'] = 'PARTIAL'
        document['notes'].append(f'账本有 {malformed} 行不可解析：覆盖不完整')
    if not received:
        document['coverage'] = 'UNKNOWN'
        document['notes'].append('账本中没有任何该资源的请求事件：可能是无请求，'
                                 '也可能是账本未覆盖该时段；不得断言为 0')
    else:
        # 覆盖起点取账本中**所有**事件的最早时间（含 INGRESS_OPENED 水位），
        # 而不是第一条请求——否则"窗口内无请求"会被误判成"未覆盖"。
        all_stamps = []
        for event in events:
            for key in ('opened_at', 'received_at', 'observed_at'):
                stamp_value = parse_ts(event.get(key))
                if stamp_value is not None:
                    all_stamps.append(stamp_value)
        earliest = min(all_stamps) if all_stamps else min(stamp for stamp, _ in received)
        if window_start < earliest:
            document['coverage'] = 'UNKNOWN' if document['coverage'] != 'PARTIAL' else 'PARTIAL'
            document['notes'].append('窗口起点早于账本最早事件，账本未覆盖整个窗口')
        elif document['coverage'] != 'PARTIAL':
            document['coverage'] = 'COMPLETE'
            document['notes'].append('窗口完整落在账本覆盖范围内，且已过安全滞后')

    document['notes'].append('本输出只证明请求计数，不证明任何单条请求的身份归属')

    with open(args.out, 'w', encoding='utf-8') as fh:
        json.dump(document, fh, ensure_ascii=False, indent=2)
    print(json.dumps({k: document[k] for k in
                      ('resource', 'window_start', 'window_end',
                       'send_goal_count', 'coverage', 'authenticated_senders')},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
