#!/usr/bin/env python3
"""打印一个场景的 F0 结果摘要（被 m3_online_extra.sh 调用）。"""
from __future__ import annotations

import json
import os
import sys


def main(argv):
    out, cid = argv[1], argv[2]
    path = os.path.join(out, 'f0_{0}.json'.format(cid))
    try:
        with open(path, encoding='utf-8') as handle:
            document = json.load(handle)
    except Exception as exc:                      # noqa: BLE001
        print('  (F0 stdout 非 JSON)', exc)
        err = os.path.join(out, 'f0_{0}.err'.format(cid))
        if os.path.isfile(err):
            with open(err, encoding='utf-8', errors='replace') as handle:
                print('  stderr head:', handle.read()[:300])
        return 0
    print('  decision=%s reason=%s' % (document.get('decision'),
                                       document.get('reason_code')))
    for module in (document.get('modules') or []):
        print('    %-15s mode=%-9s exit=%s status=%s' % (
            module.get('module'), module.get('mode'), module.get('exit_code'),
            module.get('status')))
    online = document.get('online') or {}
    if online:
        print('  online: enabled=%s outcome=%s planner_exit=%s' % (
            online.get('enabled'), online.get('outcome'),
            online.get('planner_exit_code')))
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
