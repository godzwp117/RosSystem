#!/usr/bin/env python3
"""operator_node -- announces the current patrol task summary.

Publisher of ``/rg/task_info`` (``std_msgs/msg/String`` carrying JSON), per
方案v1.2 §2.1.

Boundary (方案v1.2 §2.2): this topic is **advisory only**. It deliberately does
not carry ``allowed_region`` or any other field that could be mistaken for the
authoritative policy, and the Gateway does not subscribe to it at all. The
authoritative TaskPolicy is loaded exclusively from ``config/task_policy.yaml``.
"""

from __future__ import annotations

import json
import signal
import sys
from typing import Optional

import rclpy
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from std_msgs.msg import String

from rg_policy.events import utc_now_iso

#: Frozen topic name (方案v1.2 §2.1).
TASK_INFO_TOPIC = '/rg/task_info'


class OperatorNode(Node):
    def __init__(self) -> None:
        super().__init__('operator_node')

        self.task_id = str(self.declare_parameter('task_id', 'patrol_a_001').value)
        self.policy_version = str(self.declare_parameter('policy_version', '1.0').value)
        self.coordinate_frame = str(self.declare_parameter('coordinate_frame', 'map').value)
        self.description = str(self.declare_parameter(
            'description', 'perimeter patrol, A zone').value)
        self.publish_period_sec = float(self.declare_parameter(
            'publish_period_sec', 2.0).value)

        self._cb_group = ReentrantCallbackGroup()
        self._publisher = self.create_publisher(String, TASK_INFO_TOPIC, 10)
        self._published = 0

        self._publish_once()
        if self.publish_period_sec > 0.0:
            self.create_timer(
                self.publish_period_sec, self._publish_once, callback_group=self._cb_group)

        self.get_logger().info('OPERATOR_READY ' + json.dumps({
            'node': self.get_name(),
            'topic': TASK_INFO_TOPIC,
            'task_id': self.task_id,
            'publish_period_sec': self.publish_period_sec,
            'authority': 'advisory_only',
        }, ensure_ascii=False))

    def _publish_once(self) -> None:
        # The summary intentionally mirrors the shape of the authoritative policy
        # *without* the allowed region, so it can never be used to widen access.
        summary = {
            'task_id': self.task_id,
            'policy_version': self.policy_version,
            'coordinate_frame': self.coordinate_frame,
            'description': self.description,
            'published_at': utc_now_iso(),
            'authority': 'advisory_only',
            'note': (
                'task summary only; the authoritative TaskPolicy is read by security_gateway '
                'from config/task_policy.yaml and cannot be overridden by this message'
            ),
        }
        message = String()
        message.data = json.dumps(summary, ensure_ascii=False)
        self._publisher.publish(message)
        self._published += 1
        self.get_logger().info('TASK_INFO ' + message.data)

    def destroy_node(self) -> bool:
        self.get_logger().info('OPERATOR_COUNTERS ' + json.dumps({
            'messages_published': self._published,
        }, ensure_ascii=False))
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
    node = OperatorNode()
    executor = SingleThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            executor.shutdown(timeout_sec=2.0)
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
    return 0


if __name__ == '__main__':
    sys.exit(main())
