#!/usr/bin/env python3
"""m1_normal_traffic_fpr.py -- 真实正常/异常 ROS 2 流量的误报与检出回归（第三轮 P1）。

为什么需要它
-----------
第二轮只测了**一个** 50 Hz 场景，而且用的是与训练不一致的 1 秒窗口，
于是得到"正常流量全部 1.0"的结论。这既不能说明误报率，也不能说明检出力。

本工具在隔离 Domain 上真实发布，按**训练窗口契约（30 秒）**采集并打分：

* `normal` 场景：2 / 10 / 50 / 100 Hz 规则发布、以及不规则间隔；
* `anomaly` 场景：高频消息风暴（500 Hz），用于检验模型对异常负载的敏感度；
* 每个场景单独保存窗口特征、分数、契约状态；
* 汇总每场景的"有效判定率 / 误报率 / UNKNOWN 率"。

标签来源
--------
标签**由实验条件产生**（本脚本决定发布频率与模式），
**不是**根据模型输出反推的。异常场景是"异常负载"，
不声称等价于真实攻击，报告里必须这样写。

用法
----
    python3 scripts/m1_normal_traffic_fpr.py --container rg_m1p3 --domain 59 \
        --evidence artifacts/research/m1-phase3/<run_id>/fpr
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL = 'modules/member1_comm/model/comm_risk_window_model.json'

#: 每个场景：名称、发布命令、标签（由实验条件决定）
SCENARIOS = [
    ('normal_2hz', 'ros2 topic pub --rate 2 {topic} std_msgs/msg/String "{{data: t}}"', 'normal'),
    ('normal_10hz', 'ros2 topic pub --rate 10 {topic} std_msgs/msg/String "{{data: t}}"', 'normal'),
    ('normal_50hz', 'ros2 topic pub --rate 50 {topic} std_msgs/msg/String "{{data: t}}"', 'normal'),
    ('normal_100hz', 'ros2 topic pub --rate 100 {topic} std_msgs/msg/String "{{data: t}}"', 'normal'),
    ('anomaly_storm_500hz',
     'ros2 topic pub --rate 500 {topic} std_msgs/msg/String "{{data: t}}"', 'anomaly'),
]


def now_iso():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def run_in_container(container, script, timeout=600):
    proc = subprocess.run(['docker', 'exec', container, 'bash', '-lc', script],
                          capture_output=True, text=True, timeout=timeout)
    return proc


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--container', default='rg_m1p3')
    parser.add_argument('--domain', default='59')
    parser.add_argument('--evidence', required=True)
    parser.add_argument('--publish-seconds', type=float, default=38.0)
    parser.add_argument('--window-seconds', type=float, default=30.0)
    parser.add_argument('--only', default=None,
                        help='只跑指定场景（逗号分隔）')
    args = parser.parse_args(argv)
    os.makedirs(args.evidence, exist_ok=True)

    selected = SCENARIOS
    if args.only:
        wanted = {name.strip() for name in args.only.split(',')}
        selected = [s for s in SCENARIOS if s[0] in wanted]

    results = []
    for name, template, label in selected:
        topic = f'/m1p3/{name}'
        # 采集器在**容器内**运行，只能写容器路径；宿主机读回同一文件。
        # 早期版本把宿主机绝对路径直接传给容器，导致
        # FileNotFoundError（容器里没有 /home/...）。
        host_out = os.path.join(os.path.abspath(args.evidence), f'{name}.json')
        relative = os.path.relpath(host_out, REPO)
        container_out = '/ws/' + relative
        publish = template.format(topic=topic)
        script = (
            'set +u; source /opt/ros/jazzy/setup.bash; set -u; cd /ws; '
            f'export ROS_DOMAIN_ID={args.domain}; '
            f'(timeout {int(args.publish_seconds) + 6} {publish} >/dev/null 2>&1 &) ; '
            'sleep 3; '
            f'python3 modules/member1_comm/collector/ros2_window.py '
            f'--topic {topic} --type std_msgs/msg/String '
            f'--duration {args.publish_seconds} --interval {args.window_seconds} '
            f'--model {MODEL} --out {container_out}'
        )
        proc = run_in_container(args.container, script)
        entry = {'scenario': name, 'label': label, 'topic': topic,
                 'window_seconds': args.window_seconds,
                 'returncode': proc.returncode,
                 'stderr_tail': (proc.stderr or '')[-300:]}
        try:
            document = json.load(open(host_out, encoding='utf-8'))
            entry['verdict'] = document.get('verdict')
            entry['contract'] = document.get('window_contract')
            windows = document.get('windows') or []
            entry['windows'] = len(windows)
            entry['samples'] = [w.get('samples') for w in windows]
            entry['features'] = [w.get('features') for w in windows]
        except Exception as exc:                              # noqa: BLE001
            entry['error'] = file_error = f'{type(exc).__name__}: {exc}'
        results.append(entry)
        status = (entry.get('verdict') or {}).get('status')
        print(f'  {name:24s} label={label:8s} verdict={status}')

    # 汇总：有效判定率 / 误报 / UNKNOWN
    summary = {'generated_at': now_iso(), 'container': args.container,
               'domain': args.domain, 'window_seconds': args.window_seconds,
               'scenarios': results}
    normal = [r for r in results if r['label'] == 'normal']
    anomaly = [r for r in results if r['label'] == 'anomaly']
    def effective(rows):
        return sum(1 for r in rows
                   if (r.get('verdict') or {}).get('status') == 'SCORED')
    def attacked(rows):
        return sum(1 for r in rows
                   if ((r.get('verdict') or {}).get('score_mean') or 0) >= 0.5)
    summary['aggregate'] = {
        'normal_scenarios': len(normal),
        'normal_effective': effective(normal),
        'normal_scored_as_attack': attacked(normal),
        'normal_unknown': len(normal) - effective(normal),
        'anomaly_scenarios': len(anomaly),
        'anomaly_effective': effective(anomaly),
        'anomaly_scored_as_attack': attacked(anomaly),
        'note': ('normal 场景被判 attack 即误报；anomaly 场景被判 attack 即检出。'
                 'UNKNOWN 计为"未给结论"，不能算作正确判定。'),
    }
    with open(os.path.join(args.evidence, 'fpr_matrix.json'), 'w',
              encoding='utf-8') as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)

    lines = ['# 真实 ROS 2 正常/异常流量回归', '',
             f'- 容器：{args.container}（Domain {args.domain}）',
             f'- 窗口：{args.window_seconds} s（与训练契约一致）',
             f'- 生成时间：{summary["generated_at"]}', '',
             '| 场景 | 标签 | 状态 | 窗口数 | 平均分 | 判定 |',
             '| --- | --- | --- | --- | --- | --- |']
    for r in results:
        verdict = r.get('verdict') or {}
        score = verdict.get('score_mean')
        decision = ('ATTACK' if (score or 0) >= 0.5 else 'NORMAL') if score is not None else '-'
        lines.append('| {0} | {1} | {2} | {3} | {4} | {5} |'.format(
            r['scenario'], r['label'], verdict.get('status'),
            r.get('windows'), score, decision))
    lines += ['', '## 汇总', '',
              f'- 正常场景：{summary["aggregate"]["normal_scenarios"]} 个，'
              f'有效判定 {summary["aggregate"]["normal_effective"]}，'
              f'误报 {summary["aggregate"]["normal_scored_as_attack"]}，'
              f'UNKNOWN {summary["aggregate"]["normal_unknown"]}',
              f'- 异常场景：{summary["aggregate"]["anomaly_scenarios"]} 个，'
              f'有效判定 {summary["aggregate"]["anomaly_effective"]}，'
              f'检出 {summary["aggregate"]["anomaly_scored_as_attack"]}',
              '', '> 异常场景是"异常负载"，不等价于真实攻击；标签由实验条件决定，'
              '不是按模型输出反推。']
    with open(os.path.join(args.evidence, 'fpr_matrix.md'), 'w',
              encoding='utf-8') as fh:
        fh.write('\n'.join(lines) + '\n')
    print(json.dumps(summary['aggregate'], ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
