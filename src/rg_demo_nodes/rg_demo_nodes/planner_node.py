#!/usr/bin/env python3
"""planner_node -- sends exactly one patrol target to the guarded entry point.

方案v1.2 §2.1 / §3.1: the Planner is an Action **Client** of
``/rg/guarded_navigate`` and nothing else. The egress Action name is a module
constant, not a parameter, so no launch configuration can point the Planner at
the executor or at any other resource. Coordinates come from launch parameters
(requirement 3).

The node sends one Goal, waits for the terminal Result under an explicit
timeout, prints a single machine-readable ``PLANNER_RESULT`` JSON line, and exits
with a code the scenario harness can assert on:

    0  Result received and (if ``expect_success`` >= 0) matching the expectation
    1  Result received but not matching ``expect_success``
    2  No Result: the Action Server never became available, or a wait timed out
    3  Goal was rejected at the Action layer (``GoalRejected``) rather than answered

Concurrency: a client-only node. ``MultiThreadedExecutor`` spins in a background
thread while the main thread blocks on bounded futures, so no callback can be
starved.
"""

from __future__ import annotations

import json
import signal
import sys
import threading
import uuid
from typing import Any, Dict, Optional

import rclpy
from rclpy.action import ActionClient
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from geometry_msgs.msg import PoseStamped

from rg_interfaces.action import PatrolNavigate
from rg_policy.futures import WaitTimeout, wait_for_future

#: Frozen topology (方案v1.2 §2.1): the Planner's only permitted egress.
GUARDED_NAVIGATE_ACTION = '/rg/guarded_navigate'

EXIT_OK = 0
EXIT_EXPECTATION_MISMATCH = 1
EXIT_NO_RESULT = 2
EXIT_GOAL_REJECTED = 3

GOAL_STATUS_NAMES = {
    0: 'STATUS_UNKNOWN',
    1: 'STATUS_ACCEPTED',
    2: 'STATUS_EXECUTING',
    3: 'STATUS_CANCELING',
    4: 'STATUS_SUCCEEDED',
    5: 'STATUS_CANCELED',
    6: 'STATUS_ABORTED',
}


class PlannerNode(Node):
    def __init__(self) -> None:
        super().__init__('planner_node')

        self.task_id = str(self.declare_parameter('task_id', 'patrol_a_001').value)
        self.request_id = str(self.declare_parameter('request_id', '').value).strip()
        self.frame_id = str(self.declare_parameter('frame_id', 'map').value)
        self.target_x = float(self.declare_parameter('target_x', 0.0).value)
        self.target_y = float(self.declare_parameter('target_y', 0.0).value)
        self.target_z = float(self.declare_parameter('target_z', 0.0).value)
        self.server_wait_timeout_sec = float(self.declare_parameter(
            'server_wait_timeout_sec', 20.0).value)
        self.result_timeout_sec = float(self.declare_parameter(
            'result_timeout_sec', 20.0).value)
        # -1 = report only, 0/1 = assert the business Result.success value.
        self.expect_success = int(self.declare_parameter('expect_success', -1).value)

        if not self.request_id:
            self.request_id = uuid.uuid4().hex
        self.goal_id = uuid.uuid4().hex
        self._last_feedback: Optional[Dict[str, Any]] = None

        self._cb_group = ReentrantCallbackGroup()
        self._client = ActionClient(
            self,
            PatrolNavigate,
            GUARDED_NAVIGATE_ACTION,
            callback_group=self._cb_group,
        )

    # ------------------------------------------------------------------ build
    def build_goal(self) -> PatrolNavigate.Goal:
        goal = PatrolNavigate.Goal()
        goal.request_id = self.request_id
        goal.task_id = self.task_id
        target = PoseStamped()
        target.header.stamp = self.get_clock().now().to_msg()
        target.header.frame_id = self.frame_id
        target.pose.position.x = self.target_x
        target.pose.position.y = self.target_y
        target.pose.position.z = self.target_z
        target.pose.orientation.w = 1.0
        goal.target = target
        return goal

    def _on_feedback(self, feedback_msg: Any) -> None:
        feedback = feedback_msg.feedback
        self._last_feedback = {
            'progress': float(getattr(feedback, 'progress', 0.0)),
            'phase': str(getattr(feedback, 'phase', '')),
        }

    def _emit(self, payload: Dict[str, Any]) -> None:
        print('PLANNER_RESULT ' + json.dumps(payload, ensure_ascii=False), flush=True)

    # -------------------------------------------------------------------- run
    def run_once(self) -> int:
        base = {
            'request_id': self.request_id,
            'task_id': self.task_id,
            'frame_id': self.frame_id,
            'target': {'x': self.target_x, 'y': self.target_y, 'z': self.target_z},
            'egress_action': GUARDED_NAVIGATE_ACTION,
            'goal_id': self.goal_id,
        }

        if not self._client.wait_for_server(timeout_sec=self.server_wait_timeout_sec):
            base.update({
                'outcome': 'NO_ACTION_SERVER',
                'detail': 'Action Server {0} was not available within {1}s'.format(
                    GUARDED_NAVIGATE_ACTION, self.server_wait_timeout_sec),
            })
            self._emit(base)
            return EXIT_NO_RESULT

        send_future = self._client.send_goal_async(
            self.build_goal(), feedback_callback=self._on_feedback)
        try:
            goal_handle = wait_for_future(
                send_future, self.server_wait_timeout_sec, 'send_goal_async')
        except WaitTimeout as exc:
            base.update({'outcome': 'GOAL_ACCEPTANCE_TIMEOUT', 'detail': str(exc)})
            self._emit(base)
            return EXIT_NO_RESULT

        if not goal_handle.accepted:
            base.update({
                'outcome': 'GOAL_REJECTED',
                'accepted': False,
                'detail': 'Goal was rejected at the Action layer (no Result payload exists)',
            })
            self._emit(base)
            return EXIT_GOAL_REJECTED

        result_future = goal_handle.get_result_async()
        try:
            wrapped = wait_for_future(
                result_future, self.result_timeout_sec, 'get_result_async')
        except WaitTimeout as exc:
            base.update({
                'outcome': 'RESULT_TIMEOUT',
                'accepted': True,
                'detail': str(exc),
            })
            self._emit(base)
            return EXIT_NO_RESULT

        result = wrapped.result
        success = bool(getattr(result, 'success', False))
        base.update({
            'outcome': 'RESULT',
            'accepted': True,
            'goal_status': GOAL_STATUS_NAMES.get(int(getattr(wrapped, 'status', 0)), 'UNKNOWN'),
            'success': success,
            'status_code': str(getattr(result, 'status_code', '')),
            'detail': str(getattr(result, 'detail', '')),
            'feedback_seen': self._last_feedback,
        })
        self._emit(base)

        if self.expect_success < 0:
            return EXIT_OK
        return EXIT_OK if success == bool(self.expect_success) else EXIT_EXPECTATION_MISMATCH

    def destroy_node(self) -> bool:
        try:
            self._client.destroy()
        except Exception:  # noqa: BLE001
            pass
        return super().destroy_node()


def _install_sigterm_handler() -> None:
    def _raise_keyboard_interrupt(signum, frame):  # noqa: ARG001
        raise KeyboardInterrupt
    try:
        signal.signal(signal.SIGTERM, _raise_keyboard_interrupt)
    except (ValueError, OSError):
        pass


def main(argv: Optional[list] = None) -> int:
    _install_sigterm_handler()
    rclpy.init(args=argv)
    node = PlannerNode()
    executor = MultiThreadedExecutor(num_threads=2)
    executor.add_node(node)
    spin_thread = threading.Thread(target=_spin, args=(executor,), daemon=True)
    spin_thread.start()
    exit_code = EXIT_NO_RESULT
    try:
        exit_code = node.run_once()
    except Exception as exc:  # noqa: BLE001
        node._emit({'outcome': 'PLANNER_ERROR', 'detail': str(exc)})
        exit_code = EXIT_NO_RESULT
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


def _spin(executor: MultiThreadedExecutor) -> None:
    try:
        executor.spin()
    except Exception:  # noqa: BLE001 - shutdown races are expected here
        pass


if __name__ == '__main__':
    sys.exit(main())
