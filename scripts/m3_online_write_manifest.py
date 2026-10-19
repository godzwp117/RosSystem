#!/usr/bin/env python3
"""写入 M3 在线联调的**权威清单** manifest.json。

目的：为跨层证据复核提供**外部**期望值。若期望 request_id 取自各层自己的
记录，则篡改该层即可通过，形成自证循环。清单由驱动器在场景执行前写入。
"""
from __future__ import annotations

import json
import os
import sys


def main(argv):
    run_dir, run_id, spec_json = argv[1], argv[2], argv[3]
    scenarios = json.loads(spec_json)
    os.makedirs(run_dir, exist_ok=True)
    path = os.path.join(run_dir, 'manifest.json')
    document = {'run_id': run_id, 'scenarios': scenarios}
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(document, handle, ensure_ascii=False, indent=2)
    print('manifest ->', path)
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
