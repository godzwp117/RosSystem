#!/usr/bin/env python3
"""task_admin_client.py -- 可信任务切换的轻量管理客户端（按需运行，请求完成即退出）。

安全边界（对应任务书 C6）
------------------------
* 本程序**不含任何身份自称**：它没有 role 字段、没有 admin 标志，也不靠节点名取得权限。
  它的权限完全来自运行它时指定的 SROS 2 enclave
  （`ROS_SECURITY_ENCLAVE_OVERRIDE=/task_admin`）。
* 因此"用 /planner 身份跑同一个程序"必然被 DDS 拒绝 —— 这正是场景 D8 要验证的，
  它与 D9（/task_admin 身份成功）构成同一份代码路径的正反对照。
* 请求里只有"切到哪个已知阶段"的意图，不携带任何策略正文，客户端无法自报放大权限。

用法：
  python3 tests/integration/task_admin_client.py \
      --transition-id t-1 --target-task-id patrol_a_001 \
      --target-task-phase ZONE_B --expected-epoch 0

退出码：0 服务端接受；3 服务端拒绝（业务原因）；2 服务不可达；5 安全/初始化失败
"""

from __future__ import annotations

import argparse
import json
import sys
import threading

import rclpy
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from rg_interfaces.srv import SwitchTask

EXIT_OK = 0
EXIT_UNAVAILABLE = 2
EXIT_REJECTED = 3
EXIT_ERROR = 5

SERVICE_NAME = '/rg/task_control/switch'


def _emit(payload: dict) -> None:
    print('TASK_ADMIN_RESULT ' + json.dumps(payload, ensure_ascii=False), flush=True)


def wait_future(future, timeout_sec, what):
    done = threading.Event()
    future.add_done_callback(lambda _f: done.set())
    if not done.wait(timeout_sec):
        raise TimeoutError('{0} 超时 {1}s'.format(what, timeout_sec))
    return future.result()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='发送一次可信任务切换请求')
    parser.add_argument('--transition-id', required=True)
    parser.add_argument('--target-task-id', required=True)
    parser.add_argument('--target-task-phase', required=True)
    parser.add_argument('--expected-epoch', type=int, required=True)
    parser.add_argument('--node-name', default='task_admin_cli')
    parser.add_argument('--service', default=SERVICE_NAME)
    parser.add_argument('--server-wait', type=float, default=8.0)
    parser.add_argument('--call-wait', type=float, default=10.0)
    args = parser.parse_args(argv)

    base = {'transition_id': args.transition_id,
            'target_task_id': args.target_task_id,
            'target_task_phase': args.target_task_phase,
            'expected_epoch': args.expected_epoch,
            'service': args.service}
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
    exit_code = EXIT_ERROR
    executor = MultiThreadedExecutor(num_threads=2)
    executor.add_node(node)
    spin = threading.Thread(target=executor.spin, daemon=True)
    spin.start()
    try:
        # 与 Action 客户端同理：DDS 访问控制会在创建服务客户端端点时就拒绝未授权资源，
        # 这是比"调用超时"强得多的证据，必须结构化保留。
        try:
            client = node.create_client(SwitchTask, args.service, callback_group=group)
        except Exception as exc:  # noqa: BLE001
            base.update({'outcome': 'SERVICE_CLIENT_CREATION_DENIED',
                         'detail': '{0}: {1}'.format(type(exc).__name__, exc)})
            _emit(base)
            return EXIT_ERROR

        if not client.wait_for_service(timeout_sec=args.server_wait):
            base.update({'outcome': 'SERVICE_UNAVAILABLE',
                         'detail': '在 {0}s 内未发现服务 {1}'.format(
                             args.server_wait, args.service)})
            _emit(base)
            return EXIT_UNAVAILABLE

        request = SwitchTask.Request()
        request.transition_id = args.transition_id
        request.target_task_id = args.target_task_id
        request.target_task_phase = args.target_task_phase
        request.expected_epoch = int(args.expected_epoch)
        try:
            response = wait_future(client.call_async(request), args.call_wait, 'call_async')
        except TimeoutError as exc:
            base.update({'outcome': 'CALL_TIMEOUT', 'detail': str(exc)})
            _emit(base)
            return EXIT_UNAVAILABLE
        except Exception as exc:  # noqa: BLE001
            base.update({'outcome': 'CALL_FAILED',
                         'detail': '{0}: {1}'.format(type(exc).__name__, exc)})
            _emit(base)
            return EXIT_ERROR

        base.update({'outcome': 'RESPONSE',
                     'accepted': bool(response.accepted),
                     'reason_code': str(response.reason_code),
                     'current_epoch': int(response.current_epoch),
                     'active_task_id': str(response.active_task_id),
                     'active_task_phase': str(response.active_task_phase),
                     'policy_digest': str(response.policy_digest),
                     'detail': str(response.detail)})
        _emit(base)
        exit_code = EXIT_OK if response.accepted else EXIT_REJECTED
    except Exception as exc:  # noqa: BLE001
        base.update({'outcome': 'EXCEPTION',
                     'detail': '{0}: {1}'.format(type(exc).__name__, exc)})
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
