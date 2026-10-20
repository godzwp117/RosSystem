#!/usr/bin/env python3
"""m1_collect_sessions.py -- 在隔离 Domain 上真实采集 M1 研究会话（宿主侧编排）。

标签纪律
========
每个会话的标签由**实验条件**决定，写在 `label_basis` 里，例如
"authorized 500 Hz publisher, no policy violation"。
模型从不参与标签生成；本脚本也不读取任何模型输出。

场景设计（关键是"困难负例"）
==========================
normal 组刻意包含**表面上很像攻击**的正常行为：

* `norm-500hz`：合法 500 Hz 高速发布 —— 不能因为频率高就标成攻击；
* `norm-burst`：合法突发；
* `norm-restart`：发布者中途重启；
* `norm-irregular`：间隔抖动但合法。

anomaly 组用**定性不同**的违规，而不是单纯把频率调更高：

* `anom-discovery-churn`：会话期间反复创建/销毁节点（异常发现行为）；
* `anom-recon`：持续枚举 ROS 图并临时创建端点（侦察行为）；
* `anom-topic-flood`：远超任何授权负载的话题洪泛。

用法
----
    python3 scripts/m1_collect_sessions.py --out <dir> [--only a,b] [--duration 65]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTAINER = 'rg_m1r'
DOMAIN = '68'
COLLECTOR = 'scripts/m1_session_collector.py'

#: (session_id, scenario, label, label_basis, publisher_command_or_None)
SCENARIOS = [
    ('norm-002hz', 'normal-low-rate', 'normal',
     'authorized 2 Hz publisher, within expected load, no policy violation',
     'ros2 topic pub --rate 2 {topic} std_msgs/msg/String "{{data: t}}"'),
    ('norm-010hz', 'normal-mid-rate', 'normal',
     'authorized 10 Hz publisher, within expected load, no policy violation',
     'ros2 topic pub --rate 10 {topic} std_msgs/msg/String "{{data: t}}"'),
    ('norm-050hz', 'normal-high-rate', 'normal',
     'authorized 50 Hz publisher, within expected load, no policy violation',
     'ros2 topic pub --rate 50 {topic} std_msgs/msg/String "{{data: t}}"'),
    ('norm-500hz', 'normal-very-high-rate', 'normal',
     'authorized 500 Hz publisher; high rate alone is not a violation',
     'ros2 topic pub --rate 500 {topic} std_msgs/msg/String "{{data: t}}"'),
    ('norm-irregular', 'normal-irregular', 'normal',
     'authorized publisher with jittered intervals; timing noise is not a violation',
     'python3 /tmp/m1r_irregular.py {topic}'),
    ('norm-restart', 'normal-restart', 'normal',
     'authorized publisher restarts mid-session; a restart is not a violation',
     'python3 /tmp/m1r_restart.py {topic}'),
    ('anom-topic-flood', 'anomaly-flood', 'anomaly',
     'unbounded topic flood at 2000 Hz, far beyond any authorized workload',
     'ros2 topic pub --rate 2000 {topic} std_msgs/msg/String "{{data: t}}"'),
    ('anom-discovery-churn', 'anomaly-discovery-churn', 'anomaly',
     'abnormal discovery behavior: repeatedly creating and destroying nodes',
     'python3 /tmp/m1r_churn.py'),
    ('anom-recon', 'anomaly-recon', 'anomaly',
     'ROS graph reconnaissance: sustained enumeration plus transient endpoints',
     'python3 /tmp/m1r_recon.py'),
]

HELPERS = {
    '/tmp/m1r_irregular.py': '''import random, sys, time
import rclpy
from rclpy.node import Node
from std_msgs.msg import String
topic = sys.argv[1]
rclpy.init()
node = Node('m1r_irregular')
pub = node.create_publisher(String, topic, 10)
deadline = time.monotonic() + 120
while time.monotonic() < deadline:
    pub.publish(String(data='t'))
    rclpy.spin_once(node, timeout_sec=0)
    time.sleep(random.uniform(0.001, 0.06))
''',
    '/tmp/m1r_restart.py': '''import sys, time
import rclpy
from rclpy.node import Node
from std_msgs.msg import String
topic = sys.argv[1]
for cycle in range(3):
    rclpy.init()
    node = Node('m1r_restart_%d' % cycle)
    pub = node.create_publisher(String, topic, 10)
    deadline = time.monotonic() + 18
    while time.monotonic() < deadline:
        pub.publish(String(data='t'))
        rclpy.spin_once(node, timeout_sec=0)
        time.sleep(0.02)
    node.destroy_node()
    rclpy.shutdown()
    time.sleep(4)
''',
    '/tmp/m1r_churn.py': '''import time
import rclpy
from rclpy.node import Node
rclpy.init(args=None)
deadline = time.monotonic() + 120
cycle = 0
while time.monotonic() < deadline:
    nodes = []
    for i in range(6):
        n = Node('m1r_churn_%d_%d' % (cycle, i))
        nodes.append(n)
    end = time.monotonic() + 1.5
    while time.monotonic() < end:
        for n in nodes:
            rclpy.spin_once(n, timeout_sec=0)
    for n in nodes:
        n.destroy_node()
    cycle += 1
    time.sleep(0.8)
''',
    '/tmp/m1r_recon.py': '''import time
import rclpy
from rclpy.node import Node
from std_msgs.msg import String
rclpy.init()
node = Node('m1r_recon')
pubs = []
deadline = time.monotonic() + 120
round_no = 0
while time.monotonic() < deadline:
    try:
        node.get_node_names()
        node.get_topic_names_and_types()
        node.get_service_names_and_types()
    except Exception:
        pass
    if round_no % 3 == 0:
        p = node.create_publisher(String, '/m1r/recon/probe_%d' % round_no, 10)
        pubs.append(p)
    end = time.monotonic() + 2.0
    while time.monotonic() < end:
        rclpy.spin_once(node, timeout_sec=0)
    round_no += 1
    time.sleep(0.5)
'''}


def now_iso():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def docker_exec(script, timeout=600):
    return subprocess.run(['docker', 'exec', CONTAINER, 'bash', '-lc', script],
                          capture_output=True, text=True, timeout=timeout)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True)
    parser.add_argument('--only', default=None)
    parser.add_argument('--duration', type=float, default=65.0)
    parser.add_argument('--window', type=float, default=30.0)
    args = parser.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)

    # 把辅助发布器写进容器
    for path, body in HELPERS.items():
        tmp = os.path.join(args.out, '_helper.tmp')
        with open(tmp, 'w', encoding='utf-8') as fh:
            fh.write(body)
        subprocess.run(['docker', 'cp', tmp, f'{CONTAINER}:{path}'],
                       check=True, capture_output=True)

    selected = SCENARIOS
    if args.only:
        wanted = {t.strip() for t in args.only.split(',')}
        selected = [s for s in SCENARIOS if s[0] in wanted]

    summary = []
    for session_id, scenario, label, basis, publisher in selected:
        # ROS 2 话题名不允许 '-'，而 session_id 用 '-' 便于阅读；此处做映射。
        topic = '/m1r/' + session_id.replace('-', '_')
        host_out = os.path.abspath(os.path.join(args.out, f'{session_id}.json'))
        container_out = '/ws/' + os.path.relpath(host_out, REPO)
        publish = publisher.format(topic=topic) if publisher else None
        parts = ['set +u', 'source /opt/ros/jazzy/setup.bash', 'set -u',
                 'cd /ws', f'export ROS_DOMAIN_ID={DOMAIN}']
        if publish:
            parts.append(f'(timeout {int(args.duration) + 15} {publish} '
                         f'>/dev/null 2>&1 &)')
        parts.append('sleep 3')
        parts.append(
            f'python3 {COLLECTOR} --session-id {session_id} '
            f'--scenario {scenario} --label {label} '
            f'--label-basis "{basis}" --topic {topic} '
            f'--duration {args.duration} --window {args.window} '
            f'--domain {DOMAIN} --out {container_out}')
        proc = docker_exec('; '.join(parts))
        entry = {'session_id': session_id, 'scenario': scenario,
                 'label': label, 'label_basis': basis,
                 'returncode': proc.returncode,
                 'stderr_tail': (proc.stderr or '')[-200:]}
        try:
            with open(host_out, encoding='utf-8') as fh:
                document = json.load(fh)
            entry['windows'] = len(document.get('windows') or [])
            entry['insufficient'] = document.get('insufficient_windows')
        except Exception as exc:                             # noqa: BLE001
            entry['error'] = f'{type(exc).__name__}: {exc}'
        summary.append(entry)
        print(f'  {session_id:22s} label={label:8s} windows={entry.get("windows")}'
              f' insufficient={entry.get("insufficient")} rc={proc.returncode}')

    with open(os.path.join(args.out, 'collection_manifest.json'), 'w',
              encoding='utf-8') as fh:
        json.dump({'contract': 'm1-collection-manifest/1',
                   'generated_at': now_iso(), 'container': CONTAINER,
                   'domain': DOMAIN, 'window_sec': args.window,
                   'duration_sec': args.duration,
                   'sessions': summary}, fh, ensure_ascii=False, indent=2)
    print(json.dumps({'sessions': len(summary),
                      'ok': sum(1 for s in summary if not s.get('error'))},
                     ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
