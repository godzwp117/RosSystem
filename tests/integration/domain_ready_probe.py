#!/usr/bin/env python3
"""domain_ready_probe.py -- GAP-05 修复：不依赖 ROS 2 daemon 的就绪探测。

问题（GAP-05）
--------------
原有就绪探测用 `ros2 action list`。该命令通过 **共享的 ROS 2 daemon** 查询图，
而 daemon **按 Domain 缓存**上一次的图。当测试在 Domain 42 与 43（或 51/52）
之间切换时，daemon 可能仍在报告**上一个 Domain** 的图：

    * 假就绪：新 Domain 里根本没有该 Action，却报告"已发现"
    * 假失败：新 Domain 里确有该 Action，却报告"看不到"

两种都会误导排查。根因是"探测依赖了带缓存的间接层"，而不是"通信真的坏了"。

修复思路
--------
在本进程内用 rclpy **直接**探测：
    * 自己 `rclpy.init()` 并建节点，因此图属于**当前进程的 Domain**；
    * 用 `ActionClient.wait_for_server()` 做真实的服务端可达性判断；
    * 用 `node.get_action_names_and_types()` 取本域图快照；
    * 不通过 daemon，也不去重置/杀死其他实例的 daemon。

因此重复运行不依赖任何历史 daemon 状态，也不会影响其他成员。

用法：
    python3 tests/integration/domain_ready_probe.py --action /rg/guarded_navigate
    python3 tests/integration/domain_ready_probe.py --action /rg/guarded_navigate --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys

# 探测使用的 Action 类型：与冻结契约一致（未修改 PatrolNavigate.action）
ACTION_TYPES = {
    '/rg/guarded_navigate': 'rg_interfaces/action/PatrolNavigate',
    '/rg/nav_execute': 'rg_interfaces/action/PatrolNavigate',
}


def _load_action_type(type_name: str):
    from rosidl_runtime_py.utilities import get_action
    return get_action(type_name)


def probe(actions, timeout: float, *, discover: bool = True) -> dict:
    """在当前进程的 ROS Domain 内直接探测指定 Action。

    返回结构化结果，不抛异常 —— 调用方需要区分"确实没有服务端"与"探测本身出错"。
    """
    import rclpy
    from rclpy.action import ActionClient

    report = {
        'probe': 'rclpy_direct',
        'domain': os.environ.get('ROS_DOMAIN_ID', ''),
        'rmw': os.environ.get('RMW_IMPLEMENTATION', ''),
        'results': [],
        'discovered_actions': [],
        'error': None,
        'note': None,
    }

    rclpy.init()
    node = None
    try:
        node = rclpy.create_node('rg_domain_ready_probe')
        if discover:
            # 图快照**仅供诊断**，不是就绪判据。不同 rclpy 版本提供的 action 图 API
            # 不一致（本环境 Jazzy 的 Node 上没有 action 图方法），因此这里逐级降级，
            # 并把"不支持"如实记录为 note，而不是记成 error —— 避免把"诊断信息缺失"
            # 误报成"探测失败"。真正的就绪判据是下面的 wait_for_server()。
            snapshot = None
            for getter in (
                lambda: sorted(n for n, _t in node.get_action_names_and_types()),
                lambda: sorted(n for n, _t in
                               __import__('rclpy.action', fromlist=['x'])
                               .get_action_names_and_types(node)),
            ):
                try:
                    snapshot = getter()
                    break
                except Exception:  # noqa: BLE001
                    continue
            if snapshot is None:
                report['note'] = ('当前 rclpy 版本未提供 action 图查询 API；'
                                  '就绪判据仍由 wait_for_server 提供')
            else:
                report['discovered_actions'] = snapshot

        for action in actions:
            type_name = ACTION_TYPES.get(action)
            entry = {'action': action, 'ready': False, 'detail': ''}
            if not type_name:
                entry['detail'] = '未登记该 Action 的类型，拒绝猜测'
                report['results'].append(entry)
                continue
            try:
                action_type = _load_action_type(type_name)
                client = ActionClient(node, action_type, action)
                ready = bool(client.wait_for_server(timeout_sec=timeout))
                entry['ready'] = ready
                entry['detail'] = ('服务端在 {0}s 内可达'.format(timeout) if ready
                                   else '服务端在 {0}s 内不可达'.format(timeout))
                client.destroy()
            except Exception as exc:  # noqa: BLE001
                entry['detail'] = '{0}: {1}'.format(type(exc).__name__, exc)
            report['results'].append(entry)
    finally:
        try:
            if node is not None:
                node.destroy_node()
        except Exception:  # noqa: BLE001
            pass
        try:
            if rclpy.ok():
                rclpy.shutdown()
        except Exception:  # noqa: BLE001
            pass
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description='GAP-05：不依赖 ROS 2 daemon 的直接 Action 就绪探测')
    parser.add_argument('--action', action='append', default=None,
                        help='要探测的 Action 名（可重复）')
    parser.add_argument('--timeout', type=float, default=15.0)
    parser.add_argument('--json', action='store_true', help='输出 JSON')
    args = parser.parse_args(argv)

    actions = args.action or ['/rg/guarded_navigate', '/rg/nav_execute']
    report = probe(actions, args.timeout)

    if args.json:
        print(json.dumps(report, ensure_ascii=False))
    else:
        print('domain={0} rmw={1} probe={2}'.format(
            report['domain'], report['rmw'], report['probe']))
        for entry in report['results']:
            print('  [{0}] {1} ({2})'.format(
                'READY' if entry['ready'] else 'NOT_READY', entry['action'],
                entry['detail']))
        if report['discovered_actions']:
            print('  discovered: {0}'.format(', '.join(report['discovered_actions'])))
        if report['error']:
            print('  error: {0}'.format(report['error']))

    return 0 if all(e['ready'] for e in report['results']) else 1


if __name__ == '__main__':
    sys.exit(main())
