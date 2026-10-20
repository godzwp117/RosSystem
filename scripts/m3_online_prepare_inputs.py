#!/usr/bin/env python3
"""为 ON-03 / ON-04 / ON-06 生成输入与隔离的受信任配置。

被 scripts/m3_online_extra.sh 调用。**不修改** Gateway 权威策略：ON-03 指向
一个故意不存在的策略文件，ON-04 指向一个故意不可解析的测试策略文件，
ON-06 使用正式策略（只读）。
"""
from __future__ import annotations

import json
import os
import sys

import yaml

SCENARIOS = {
    # cid: (policy 取值, planner 超时)
    'ON03': ('absent', None),
    'ON04': ('corrupt', None),
    'ON06': ('real', 0.5),
}


def main(argv):
    in_dir, run_id, ws = argv[1], argv[2], argv[3]
    os.makedirs(in_dir, exist_ok=True)
    base = json.load(open(os.path.join(
        ws, 'docs/interfaces/examples/module_input_valid.json'), encoding='utf-8'))

    for cid in SCENARIOS:
        doc = dict(base)
        doc['run_id'] = run_id
        doc['request_id'] = '{0}-{1}'.format(cid.lower(), run_id)
        doc['candidate_action'] = dict(base['candidate_action'])
        doc['candidate_action']['target'] = {'frame_id': 'map', 'x': 1.5,
                                            'y': 1.5, 'z': 0.0}
        with open(os.path.join(in_dir, cid + '.json'), 'w', encoding='utf-8') as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=2)
        print('input', cid, '->', doc['request_id'])

    policies = {
        'ON03': os.path.join(in_dir, 'task_policy_absent.yaml'),
        'ON04': os.path.join(in_dir, 'task_policy_corrupt.yaml'),
        'ON06': os.path.join(ws, 'config/task_policy.yaml'),
    }
    # ON-04：真实存在的**不可解析** YAML（制表符缩进 + 未闭合流式映射）
    with open(policies['ON04'], 'w', encoding='utf-8') as fh:
        fh.write('task_id: patrol_a_001\n'
                 'policy_version: "1.0-corrupt"\n'
                 '\tactive: true\n'
                 'allowed_region: {x_min: 0.0, x_max: [unterminated\n')
    # ON-03：确保该文件**确实不存在**
    if os.path.exists(policies['ON03']):
        os.unlink(policies['ON03'])

    src_cfg = os.path.join(ws, 'config/team_modules.member3.real.yaml')
    for cid, policy in policies.items():
        doc = yaml.safe_load(open(src_cfg, encoding='utf-8'))
        cmd = list(doc['modules']['task_risk']['command'])
        out, index = [], 0
        while index < len(cmd):
            if cmd[index] == '--policy' and index + 1 < len(cmd):
                out += ['--policy', policy]
                index += 2
                continue
            out.append(cmd[index])
            index += 1
        if '--policy' not in out:
            out += ['--policy', policy]
        doc['modules']['task_risk']['command'] = out
        doc.setdefault('adapter', {})['log_path'] = (
            '/tmp/m3_online/adapter_%s.jsonl' % cid)
        with open(os.path.join(in_dir, cid + '_config.yaml'), 'w',
                  encoding='utf-8') as fh:
            yaml.safe_dump(doc, fh, allow_unicode=True)
        print('config', cid, '-> policy', policy)
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
