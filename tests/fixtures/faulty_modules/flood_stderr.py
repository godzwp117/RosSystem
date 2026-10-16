#!/usr/bin/env python3
"""故障模块：stdout 输出一个合法 JSON，但 stderr 持续洪泛。"""
import json
import sys
sys.stderr.write('E' * 4096)
sys.stderr.flush()
print(json.dumps({'schema_version': '1.0.0-proposed', 'run_id': 'r',
                  'request_id': 'q', 'event_id': 'e',
                  'producer': {'name': 'x', 'module_version': '1', 'source': 'MOCK'},
                  'observed_at': '2026-10-12T00:00:00Z', 'status': 'NORMAL',
                  'reason': '', 'evidence_refs': [{'ref': 'x', 'kind': 'MOCK'}],
                  'communication': {'resource': '/rg/guarded_navigate',
                                    'resource_type': 'Action'},
                  'window': {'start': '2026-10-12T00:00:00Z',
                             'end': '2026-10-12T00:00:00Z', 'duration_ms': 0},
                  'request_count': 1, 'anomaly_category': 'NONE',
                  'risk_level': 'NONE', 'basis': ['x']}))
sys.stdout.flush()
for _ in range(200000):
    sys.stderr.write('F' * 4096)
    sys.stderr.flush()
