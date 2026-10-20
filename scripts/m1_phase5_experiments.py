#!/usr/bin/env python3
"""m1_phase5_experiments.py -- G2 图行为实验 + G3 独立会话采集（宿主侧编排）。

设计纪律
========
* 每个会话 = 一次独立的采集进程调用 = 一个独立样本单位；
* 标签由**实验条件**决定（`label_basis` 写明事实），脚本不读模型输出；
* 异常不使用"频率更高"这一条捷径：churn / 端点侦察 / 纯查询 都是
  **定性不同**的行为；
* 纯查询侦察若在快照上不可见，就是不可见，脚本不会为它插入特征。

G2 与 G3 的区别
---------------
G2 是**机制验证**（每次一个场景，回答"能不能看见"），
G3 是**数据集采集**（多会话，供后续评估）。
两者共用同一个采集器，但输出到不同目录。

用法
----
    python3 scripts/m1_phase5_experiments.py --out <dir> --group g2
    python3 scripts/m1_phase5_experiments.py --out <dir> --group g3
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 容器与 Domain 可由环境变量覆盖：不同轮次使用不同研究容器，
# 硬编码会导致采集写进**上一轮**的工作树（第六轮已实际踩到）。
CONTAINER = os.environ.get('M1_EXPERIMENT_CONTAINER', 'rg_m1g')
DOMAIN = os.environ.get('M1_EXPERIMENT_DOMAIN', '69')
COLLECTOR = 'scripts/m1_graph_collector.py'


def publisher_script(path, body):
    return (path, body)


# ---------------------------------------------------------------- 行为注入脚本
BEHAVIOURS = {
    # 合法高频/低频发布
    'publish': '''import sys, time
import rclpy
from rclpy.node import Node
from std_msgs.msg import String
topic, rate, seconds = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
rclpy.init()
node = Node('m1g_pub')
pub = node.create_publisher(String, topic, 200)
period = 1.0 / rate if rate > 0 else 0.05
deadline = time.monotonic() + seconds
while time.monotonic() < deadline:
    pub.publish(String(data='t'))
    rclpy.spin_once(node, timeout_sec=0)
    time.sleep(period)
''',
    # 正常节点加入/退出/重启
    'join_leave': '''import sys, time
import rclpy
from rclpy.node import Node
seconds = float(sys.argv[1])
rclpy.init()
deadline = time.monotonic() + seconds
while time.monotonic() < deadline:
    n = Node('m1g_visitor')
    end = time.monotonic() + 8
    while time.monotonic() < end:
        rclpy.spin_once(n, timeout_sec=0)
    n.destroy_node()
    time.sleep(6)
''',
    # 异常 churn：高频创建销毁
    'churn': '''import sys, time
import rclpy
from rclpy.node import Node
seconds = float(sys.argv[1])
rclpy.init()
deadline = time.monotonic() + seconds
cycle = 0
while time.monotonic() < deadline:
    nodes = [Node('m1g_churn_%d_%d' % (cycle, i)) for i in range(5)]
    end = time.monotonic() + 1.2
    while time.monotonic() < end:
        for n in nodes:
            rclpy.spin_once(n, timeout_sec=0)
    for n in nodes:
        n.destroy_node()
    cycle += 1
    time.sleep(0.5)
''',
    # 端点侦察：持续新建 publisher（图拓扑变化）
    'endpoint_recon': '''import sys, time
import rclpy
from rclpy.node import Node
from std_msgs.msg import String
seconds = float(sys.argv[1])
rclpy.init()
node = Node('m1g_recon')
pubs = []
deadline = time.monotonic() + seconds
round_no = 0
while time.monotonic() < deadline:
    p = node.create_publisher(String, '/m1g/recon/probe_%d' % round_no, 10)
    pubs.append(p)
    end = time.monotonic() + 2.0
    while time.monotonic() < end:
        rclpy.spin_once(node, timeout_sec=0)
    round_no += 1
    time.sleep(0.4)
''',
    # 纯查询侦察：只读图信息，不改变拓扑
    'pure_query': '''import sys, time
import rclpy
from rclpy.node import Node
seconds = float(sys.argv[1])
rclpy.init()
node = Node('m1g_query')
deadline = time.monotonic() + seconds
while time.monotonic() < deadline:
    node.get_node_names()
    node.get_topic_names_and_types()
    node.get_service_names_and_types()
    end = time.monotonic() + 0.5
    while time.monotonic() < end:
        rclpy.spin_once(node, timeout_sec=0)
''',
    # 极短命的端点：用于漏采实验
    'blip': '''import sys, time
import rclpy
from rclpy.node import Node
from std_msgs.msg import String
seconds, lifetime = float(sys.argv[1]), float(sys.argv[2])
rclpy.init()
deadline = time.monotonic() + seconds
count = 0
while time.monotonic() < deadline:
    n = Node('m1g_blip_%d' % count)
    n.create_publisher(String, '/m1g/blip/%d' % count, 10)
    end = time.monotonic() + lifetime
    while time.monotonic() < end:
        rclpy.spin_once(n, timeout_sec=0)
    n.destroy_node()
    count += 1
    time.sleep(1.0)
''',
}

#: G2 机制验证场景
G2_SCENARIOS = [
    ('g2-01-stable', 'graph-stable-normal', 'normal',
     'stable legitimate publisher and subscriber; no topology change expected',
     'publish', '10', ['5']),
    ('g2-02-join', 'node-join-normal', 'normal',
     'a legitimate node joins the graph and stays',
     'join_leave', '14', []),
    ('g2-03-churn', 'node-churn-anomaly', 'anomaly',
     'abnormal discovery behaviour: nodes created and destroyed repeatedly',
     'churn', '40', []),
    ('g2-04-endpoint-recon', 'endpoint-recon-anomaly', 'anomaly',
     'reconnaissance that creates visible endpoints on the graph',
     'endpoint_recon', '40', []),
    ('g2-05-pure-query', 'pure-query-anomaly', 'anomaly',
     'graph queries only; topology expected unchanged (observability test)',
     'pure_query', '40', []),
    ('g2-06-high-rate', 'high-rate-normal', 'normal',
     'legitimate 500 Hz publisher; high rate is not a violation',
     'publish', '500', ['40']),
    ('g2-07-graph-only', 'graph-only-no-messages', 'anomaly',
     'churn with zero business messages; graph channel must still work',
     'churn', '40', []),
    ('g2-08-blip', 'short-lived-endpoints', 'normal',
     'endpoints shorter than the poll interval (miss observability test)',
     'blip', '40', ['0.05']),
]

#: G3 数据集会话（每类独立会话）
G3_SESSIONS = []
for index, rate in enumerate([1, 2, 5, 10, 20, 50, 100, 200, 500, 1000]):
    G3_SESSIONS.append(
        (f'g3-norm-{rate:04d}hz-s{index:02d}', 'normal-rate', 'normal',
         f'authorized {rate} Hz publisher, within expected workload',
         'publish', str(rate), ['40']))
for index in range(5):
    G3_SESSIONS.append(
        (f'g3-norm-restart-s{index:02d}', 'normal-restart', 'normal',
         'authorized node joins and leaves once; a restart is not a violation',
         'join_leave', '40', []))
for index in range(5):
    G3_SESSIONS.append(
        (f'g3-anom-flood-s{index:02d}', 'anomaly-flood', 'anomaly',
         'unbounded 2000 Hz flood, far beyond any authorized workload',
         'publish', '2000', ['40']))
for index in range(5):
    G3_SESSIONS.append(
        (f'g3-anom-churn-s{index:02d}', 'anomaly-churn', 'anomaly',
         'abnormal discovery: sustained node create/destroy churn',
         'churn', '40', []))
for index in range(5):
    G3_SESSIONS.append(
        (f'g3-anom-recon-s{index:02d}', 'anomaly-endpoint-recon', 'anomaly',
         'reconnaissance creating visible endpoints continuously',
         'endpoint_recon', '40', []))


def now_iso():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def docker_exec(script, timeout=600):
    return subprocess.run(['docker', 'exec', CONTAINER, 'bash', '-lc', script],
                          capture_output=True, text=True, timeout=timeout)


def install_behaviours(out_dir):
    for name, body in BEHAVIOURS.items():
        tmp = os.path.join(out_dir, f'_behaviour_{name}.py')
        with open(tmp, 'w', encoding='utf-8') as fh:
            fh.write(body)
        subprocess.run(['docker', 'cp', tmp, f'{CONTAINER}:/tmp/m1g_{name}.py'],
                       check=True, capture_output=True)


def run_session(entry, out_dir, duration, window, subdir):
    (session_id, scenario, label, basis, behaviour,
     arg0, extra) = entry
    topic = '/m1g/' + session_id.replace('-', '_')
    host_out = os.path.abspath(os.path.join(out_dir, subdir, f'{session_id}.json'))
    container_out = '/ws/' + os.path.relpath(host_out, REPO)
    args = ' '.join([f"'{a}'" for a in [arg0] + extra])
    if behaviour == 'blip':
        actor = (f'python3 /tmp/m1g_blip.py {args}')
    elif behaviour in ('churn', 'endpoint_recon', 'pure_query'):
        actor = f'python3 /tmp/m1g_{behaviour}.py {args}'
    elif behaviour == 'join_leave':
        actor = f'python3 /tmp/m1g_join_leave.py {args}'
    else:
        actor = f'python3 /tmp/m1g_publish.py {topic} {args}'
    script = (
        'set +u; source /opt/ros/jazzy/setup.bash; set -u; cd /ws; '
        f'export ROS_DOMAIN_ID={DOMAIN}; '
        f'(timeout {int(duration) + 25} {actor} >/dev/null 2>&1 &) ; '
        'sleep 2; '
        f'python3 {COLLECTOR} --session-id {session_id} --scenario {scenario} '
        f'--label {label} --label-basis "{basis}" --topic {topic} '
        f'--duration {duration} --window {window} --poll-interval 0.2 '
        f'--domain {DOMAIN} --out {container_out}')
    proc = docker_exec(script)
    entry_out = {'session_id': session_id, 'scenario': scenario,
                 'label': label, 'label_basis': basis,
                 'returncode': proc.returncode,
                 'stderr_tail': (proc.stderr or '')[-160:]}
    try:
        with open(host_out, encoding='utf-8') as fh:
            document = json.load(fh)
        summary = document.get('summary') or {}
        entry_out.update({
            'windows_total': summary.get('windows_total'),
            'windows_message_ok': summary.get('windows_message_ok'),
            'windows_graph_valid': summary.get('windows_graph_valid'),
        })
    except Exception as exc:                                 # noqa: BLE001
        entry_out['error'] = f'{type(exc).__name__}: {exc}'
    return entry_out


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True)
    parser.add_argument('--group', required=True, choices=['g2', 'g3'])
    parser.add_argument('--duration', type=float, default=40.0)
    parser.add_argument('--window', type=float, default=30.0)
    args = parser.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)
    install_behaviours(args.out)

    entries = G2_SCENARIOS if args.group == 'g2' else G3_SESSIONS
    subdir = 'g2_graph_scenarios' if args.group == 'g2' else 'g3_sessions'
    results = []
    for entry in entries:
        outcome = run_session(entry, args.out, args.duration, args.window, subdir)
        results.append(outcome)
        print(f'  {outcome["session_id"]:28s} label={outcome["label"]:8s} '
              f'win={outcome.get("windows_total")} '
              f'msg_ok={outcome.get("windows_message_ok")} '
              f'graph_ok={outcome.get("windows_graph_valid")} '
              f'rc={outcome["returncode"]}')

    manifest = {'contract': 'm1-phase5-collection/1',
                'generated_at': now_iso(), 'group': args.group,
                'container': CONTAINER, 'domain': DOMAIN,
                'window_sec': args.window, 'duration_sec': args.duration,
                'sessions': results}
    path = os.path.join(args.out, f'{args.group}_manifest.json')
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
    print(json.dumps({'group': args.group, 'sessions': len(results),
                      'ok': sum(1 for r in results if not r.get('error'))},
                     ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
