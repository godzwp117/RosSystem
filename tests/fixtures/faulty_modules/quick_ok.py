#!/usr/bin/env python3
"""LIM-01 正例 fixture：读入 stdin 后立即输出一个合法 JSON 对象并正常退出。

用途：证明「进程在超时前自行结束」这一路径也会被 judge_timeout 正确分类为
clean_completion，而不是被误判为挂起/超时。
"""
import json
import sys

payload = json.load(sys.stdin)
print(json.dumps({
    'schema_version': '1.0.0-proposed',
    'run_id': payload.get('run_id', 'x'),
    'request_id': payload.get('request_id', 'y'),
    'event_id': 'evt-quick-ok',
    'producer': {'name': 'quick_ok', 'source': 'MOCK', 'module_version': '0'},
    'observed_at': '2026-10-16T00:00:00Z',
    'status': 'NORMAL',
    'evidence_refs': [{'ref': 'tests/fixtures/faulty_modules/quick_ok.py',
                       'kind': 'MOCK'}],
}, ensure_ascii=False))
