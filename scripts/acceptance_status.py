#!/usr/bin/env python3
"""acceptance_status.py -- 严格 acceptance 的状态聚合（唯一事实来源）。

为什么要独立成模块
==================
1.0.2 的 acceptance 用单一 rc_all 汇总：当 DDS Enforce 因缺少合法凭据返回
NOT_RUN 时，没有任何失败标志被置位，于是出现

    ENFORCE=NOT_RUN
    ACCEPTANCE=PASS
    exit_code=0

这违反了"严格验收"的语义：没跑的项目不能算通过。本模块把
"各项目状态 -> 整体结论 -> 退出码"固化为纯函数，既被 scripts/final_system.sh
调用，也被单元测试穷举覆盖，避免两处逻辑漂移。

状态定义
--------
PASS            该项实际执行，且满足对应通过条件
FAIL            该项实际执行后失败，或出现契约违反/实验异常
NOT_RUN         该项因缺少合法凭据、必要环境或其他前置条件而未执行
INCOMPLETE      整体没有 FAIL，但至少有一个必需项 NOT_RUN（或没有任何项执行）
PREFLIGHT_FAIL  严格预检失败，后续项目未执行

聚合规则（严格）
----------------
1. 任一 FAIL                -> FAIL        exit 1
2. 否则任一 NOT_RUN         -> INCOMPLETE  exit 9
3. 否则非空且全部 PASS      -> PASS        exit 0
4. 空集合                   -> INCOMPLETE  exit 9（未执行任何项目不得 PASS）

FAIL 与 NOT_RUN 同时存在时结果为 FAIL，但 NOT_RUN 项必须完整保留在输出里。
"""
from __future__ import annotations

import json
import sys

PASS = 'PASS'
FAIL = 'FAIL'
NOT_RUN = 'NOT_RUN'
INCOMPLETE = 'INCOMPLETE'
PREFLIGHT_FAIL = 'PREFLIGHT_FAIL'

ITEM_STATUSES = (PASS, FAIL, NOT_RUN)
EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_INCOMPLETE = 9


def parse_items(argv):
    """把 KEY=STATUS 形式的参数解析为有序字典。"""
    items = {}
    for raw in argv:
        if '=' not in raw:
            raise ValueError('项目状态必须形如 KEY=STATUS：{0!r}'.format(raw))
        key, status = raw.split('=', 1)
        key, status = key.strip(), status.strip()
        if not key:
            raise ValueError('项目名为空：{0!r}'.format(raw))
        if status not in ITEM_STATUSES:
            raise ValueError('未知状态 {0!r}（可选 {1}）'.format(
                status, ', '.join(ITEM_STATUSES)))
        if key in items:
            raise ValueError('项目重复：{0}'.format(key))
        items[key] = status
    return items


def aggregate(items):
    """返回 (整体状态, 退出码, not_run 列表, failed 列表)。"""
    failed = [k for k, v in items.items() if v == FAIL]
    not_run = [k for k, v in items.items() if v == NOT_RUN]
    if failed:
        return FAIL, EXIT_FAIL, not_run, failed
    if not_run:
        return INCOMPLETE, EXIT_INCOMPLETE, not_run, failed
    if items:
        return PASS, EXIT_PASS, not_run, failed
    # 一项都没执行：不得判 PASS
    return INCOMPLETE, EXIT_INCOMPLETE, not_run, failed


def summarize(items):
    status, code, not_run, failed = aggregate(items)
    return {
        'acceptance': status,
        'exit_code': code,
        'items': dict(items),
        'not_run': not_run,
        'failed': failed,
        'rule': 'FAIL>NOT_RUN>PASS；空集合=INCOMPLETE',
    }


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    as_json = False
    if argv and argv[0] == '--json':
        as_json = True
        argv = argv[1:]
    try:
        items = parse_items(argv)
    except ValueError as exc:
        print('ERROR: {0}'.format(exc), file=sys.stderr)
        return 2
    doc = summarize(items)
    if as_json:
        print(json.dumps(doc, ensure_ascii=False, indent=2))
    else:
        # 机器可读单行：STATUS EXITCODE NOT_RUN_CSV FAILED_CSV
        print('{0} {1} {2} {3}'.format(
            doc['acceptance'], doc['exit_code'],
            ','.join(doc['not_run']) or '-',
            ','.join(doc['failed']) or '-'))
        if doc['not_run']:
            print('NOT_RUN 项目：{0}'.format(', '.join(doc['not_run'])),
                  file=sys.stderr)
        if doc['failed']:
            print('FAIL 项目：{0}'.format(', '.join(doc['failed'])),
                  file=sys.stderr)
    return doc['exit_code']


if __name__ == '__main__':
    raise SystemExit(main())
