#!/usr/bin/env python3
"""rogue_action_client.py -- 受控测试客户端，用于 M2 越权访问实验（场景 S3/S4）。

它**不是产品组件**，只是实验仪器：向指定 Action 名称发送一个 Goal，并把结果以
机器可读的一行 JSON 输出，便于对照实验断言。

存在意义（关键实验设计）
------------------------
仅凭"客户端超时"不能证明 DDS 权限生效——也可能是服务端没起来、Action 名写错、
或客户端本身有 bug。因此本工具配合三类对照：
  * 用 /gateway 身份访问 /rg/nav_execute  **应当成功**（证明链路与客户端本身可用）
  * 用 /planner 身份访问 /rg/nav_execute  **应当失败**（越权）
  * 用 /unauthorized 身份访问同一资源    **应当失败**（无授权身份）
三者使用同一个客户端程序、同一份代码路径，唯一变量是安全身份。

用法：
  python3 tests/integration/rogue_action_client.py --action /rg/nav_execute \\
      --node-name rogue_client --x 1.5 --y 1.5

退出码：0 拿到 Result；2 服务端不可达/未在超时内出现；3 Action 层被拒；4 结果超时；
        5 安全初始化失败（凭证/Keystore）；6 DDS 访问控制拒绝创建 action client
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import uuid

import rclpy
from geometry_msgs.msg import PoseStamped
from rclpy.action import ActionClient
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from rg_interfaces.action import PatrolNavigate

EXIT_OK = 0
EXIT_NO_SERVER = 2
EXIT_GOAL_REJECTED = 3
EXIT_RESULT_TIMEOUT = 4
EXIT_ERROR = 5
EXIT_CLIENT_DENIED = 6


def _emit(payload: dict) -> None:
    print('ROGUE_RESULT ' + json.dumps(payload, ensure_ascii=False), flush=True)


def wait_future(future, timeout_sec, what):
    done = threading.Event()
    future.add_done_callback(lambda _f: done.set())
    if not done.wait(timeout_sec):
        raise TimeoutError('{0} 超时 {1}s'.format(what, timeout_sec))
    return future.result()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='越权访问实验客户端')
    parser.add_argument('--action', required=True, help='目标 Action 名称')
    parser.add_argument('--node-name', default='rogue_client')
    parser.add_argument('--request-id', default=None)
    parser.add_argument('--task-id', default='patrol_a_001')
    parser.add_argument('--frame-id', default='map')
    parser.add_argument('--x', type=float, default=1.5)
    parser.add_argument('--y', type=float, default=1.5)
    parser.add_argument('--server-wait', type=float, default=8.0)
    parser.add_argument('--result-wait', type=float, default=8.0)
    args = parser.parse_args(argv)

    request_id = args.request_id or uuid.uuid4().hex
    base = {'request_id': request_id, 'target_action': args.action,
            'node_name': args.node_name, 'enclave': None}
    # rclpy.init() 与节点创建都会触发 DDS 安全初始化：凭证缺失、权限不足都可能是
    # **在任何业务通信之前**就失败。必须把这一层也变成结构化的可断言证据，
    # 而不是让它以 Python traceback + exit 1 的形式消失。
    try:
        rclpy.init()
    except Exception as exc:  # noqa: BLE001
        base.update({'outcome': 'INIT_FAILED',
                     'detail': '{0}: {1}'.format(type(exc).__name__, exc)})
        _emit(base)
        return EXIT_ERROR
    try:
        node = Node(args.node_name)
    except Exception as exc:  # noqa: BLE001
        base.update({'outcome': 'NODE_CREATION_FAILED',
                     'detail': '{0}: {1}'.format(type(exc).__name__, exc)})
        _emit(base)
        try:
            if rclpy.ok():
                rclpy.shutdown()
        except Exception:  # noqa: BLE001
            pass
        return EXIT_ERROR
    group = ReentrantCallbackGroup()
    # DDS 访问控制会在**创建 action client 的 DDS 端点时**就拒绝未授权资源：
    # 典型输出 "[SECURITY Error] rr/<action>/_action/send_goalReply topic not found in allow rule"。
    # 这是比"客户端超时"强得多的证据，必须结构化保留。
    try:
        client = ActionClient(node, PatrolNavigate, args.action, callback_group=group)
    except Exception as exc:  # noqa: BLE001
        base.update({'outcome': 'ACTION_CLIENT_CREATION_DENIED',
                     'detail': '{0}: {1}'.format(type(exc).__name__, exc)})
        _emit(base)
        try:
            node.destroy_node()
        except Exception:  # noqa: BLE001
            pass
        try:
            if rclpy.ok():
                rclpy.shutdown()
        except Exception:  # noqa: BLE001
            pass
        return EXIT_CLIENT_DENIED
    executor = MultiThreadedExecutor(num_threads=2)
    executor.add_node(node)
    spin = threading.Thread(target=executor.spin, daemon=True)
    spin.start()

    exit_code = EXIT_ERROR
    try:
        if not client.wait_for_server(timeout_sec=args.server_wait):
            base.update({'outcome': 'NO_ACTION_SERVER',
                         'detail': '在 {0}s 内未发现 Action Server {1}'.format(
                             args.server_wait, args.action)})
            _emit(base)
            return EXIT_NO_SERVER

        goal = PatrolNavigate.Goal()
        goal.request_id = request_id
        goal.task_id = args.task_id
        target = PoseStamped()
        target.header.frame_id = args.frame_id
        target.pose.position.x = args.x
        target.pose.position.y = args.y
        target.pose.position.z = 0.0
        target.pose.orientation.w = 1.0
        goal.target = target

        try:
            handle = wait_future(client.send_goal_async(goal), args.server_wait, 'send_goal_async')
        except TimeoutError as exc:
            base.update({'outcome': 'SEND_GOAL_TIMEOUT', 'detail': str(exc)})
            _emit(base)
            return EXIT_NO_SERVER

        if not handle.accepted:
            base.update({'outcome': 'GOAL_REJECTED', 'detail': 'Action 层拒绝了 Goal'})
            _emit(base)
            return EXIT_GOAL_REJECTED

        try:
            wrapped = wait_future(handle.get_result_async(), args.result_wait, 'get_result_async')
        except TimeoutError as exc:
            base.update({'outcome': 'RESULT_TIMEOUT', 'detail': str(exc)})
            _emit(base)
            return EXIT_RESULT_TIMEOUT

        result = wrapped.result
        base.update({'outcome': 'RESULT',
                     'success': bool(getattr(result, 'success', False)),
                     'status_code': str(getattr(result, 'status_code', '')),
                     'detail': str(getattr(result, 'detail', ''))})
        _emit(base)
        exit_code = EXIT_OK
    except Exception as exc:  # noqa: BLE001
        base.update({'outcome': 'EXCEPTION', 'detail': '{0}: {1}'.format(type(exc).__name__, exc)})
        _emit(base)
        exit_code = EXIT_ERROR
    finally:
        try:
            executor.shutdown(timeout_sec=1.0)
        except Exception:  # noqa: BLE001
            pass
        try:
            node.destroy_node()
        except Exception:  # noqa: BLE001
            pass
        try:
            if rclpy.ok():
                rclpy.shutdown()
        except Exception:  # noqa: BLE001
            pass
    return exit_code


if __name__ == '__main__':
    sys.exit(main())
