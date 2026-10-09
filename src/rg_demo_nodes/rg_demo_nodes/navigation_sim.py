#!/usr/bin/env python3
"""navigation_sim -- minimal navigation executor stub (方案v1.2 §1.1 / §3.1).

Action Server for ``/rg/nav_execute``. On receiving a Goal it:

1. appends the target to its own executor journal (JSONL, one line per Goal),
2. logs a machine-readable ``NAVSIM_GOAL`` line,
3. publishes minimal Feedback,
4. optionally simulates latency / failure (test hooks only),
5. returns a Result.

It deliberately performs **no path planning and no map building**. It is the
placeholder for a future Nav2 ``/navigate_to_pose`` Adapter; the Gateway's
downstream Action name is a parameter so that swap does not change the
Planner <-> Gateway contract.

The journal is written *before* any simulated delay, so a downstream Goal count
remains observable even when the Gateway times the execution out. That is what
lets the A/B scenario harness assert "NavigationSim received exactly N Goals"
rather than eyeballing terminal text.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import threading
import time
from typing import Any, Dict, Optional

import rclpy
from rclpy.action import ActionServer
from rclpy.action.server import GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from rg_interfaces.action import PatrolNavigate
from rg_policy import reason_codes
from rg_policy.events import utc_now_iso

#: Frozen topology (方案v1.2 §2.1): the executor-side resource name.
NAV_EXECUTE_ACTION = '/rg/nav_execute'
DEFAULT_RECORD_PATH = 'logs/navsim_goals.jsonl'
EXECUTOR_THREADS = 4


def _goal_id_to_hex(goal_id: Any) -> str:
    raw = getattr(goal_id, 'uuid', None)
    if raw is None:
        return str(goal_id)
    return bytes(raw).hex()


class _JsonlJournal:
    """Append-only JSONL journal owned by the executor.

    Kept separate from the Gateway's audit sink on purpose: this is the
    executor's own receipt log, not part of the frozen audit event schema.
    """

    def __init__(self, path: str):
        self.path = os.path.abspath(str(path))
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        self._lock = threading.Lock()
        self._handle = open(self.path, 'a', encoding='utf-8')
        self._count = 0

    @property
    def count(self) -> int:
        with self._lock:
            return self._count

    def append(self, record: Dict[str, Any]) -> None:
        line = json.dumps(record, ensure_ascii=False, allow_nan=False)
        with self._lock:
            self._handle.write(line + '\n')
            self._handle.flush()
            self._count += 1

    def close(self) -> None:
        with self._lock:
            if not self._handle.closed:
                self._handle.flush()
                self._handle.close()


class NavigationSim(Node):
    def __init__(self) -> None:
        super().__init__('navigation_sim')

        self.action_name = NAV_EXECUTE_ACTION
        record_path = self.declare_parameter('record_path', DEFAULT_RECORD_PATH).value
        # Test hooks. Defaults keep the documented minimal behaviour.
        self.simulate_delay_sec = float(self.declare_parameter(
            'simulate_delay_sec', 0.0).value)
        self.simulate_failure = bool(self.declare_parameter(
            'simulate_failure', False).value)
        self.simulate_reject = bool(self.declare_parameter(
            'simulate_reject', False).value)
        self.emit_feedback = bool(self.declare_parameter('emit_feedback', True).value)

        self._journal = _JsonlJournal(record_path)
        self._cb_group = ReentrantCallbackGroup()
        self._server = ActionServer(
            self,
            PatrolNavigate,
            self.action_name,
            execute_callback=self._on_execute,
            goal_callback=self._on_goal_request,
            callback_group=self._cb_group,
        )
        self._goals_executed = 0

        self.get_logger().info('NAVSIM_READY ' + json.dumps({
            'node': self.get_name(),
            'action': self.action_name,
            'record_path': self._journal.path,
            'simulate_delay_sec': self.simulate_delay_sec,
            'simulate_failure': self.simulate_failure,
            'simulate_reject': self.simulate_reject,
            'path_planning': 'none (stub executor)',
            'executor_threads': EXECUTOR_THREADS,
        }, ensure_ascii=False))

    def _on_goal_request(self, goal_request: Any) -> Any:
        if self.simulate_reject:
            self.get_logger().warning('NAVSIM_REJECT_GOAL ' + json.dumps({
                'request_id': str(getattr(goal_request, 'request_id', '')),
            }, ensure_ascii=False))
            return GoalResponse.REJECT
        return GoalResponse.ACCEPT

    def _on_execute(self, goal_handle: Any) -> PatrolNavigate.Result:
        goal = goal_handle.request
        target = goal.target
        header = getattr(target, 'header', None)
        position = getattr(getattr(target, 'pose', None), 'position', None)

        request_id = str(goal.request_id)
        task_id = str(goal.task_id)
        frame_id = str(getattr(header, 'frame_id', '') or '')
        x = float(getattr(position, 'x', float('nan')))
        y = float(getattr(position, 'y', float('nan')))
        z = float(getattr(position, 'z', float('nan')))
        received_at = utc_now_iso()
        goal_id = _goal_id_to_hex(goal_handle.goal_id)

        # 1. journal first: the Goal count must be observable even if we are
        #    about to be timed out or killed mid-execution.
        self._journal.append({
            'received_at': received_at,
            'action': self.action_name,
            'goal_id': goal_id,
            'request_id': request_id,
            'task_id': task_id,
            'frame_id': frame_id,
            'x': x if _finite(x) else str(x),
            'y': y if _finite(y) else str(y),
            'z': z if _finite(z) else str(z),
            'recorded_only': True,
            'path_planning': False,
        })
        self._goals_executed += 1

        self.get_logger().info('NAVSIM_GOAL ' + json.dumps({
            'goal_id': goal_id,
            'request_id': request_id,
            'task_id': task_id,
            'frame_id': frame_id,
            'x': x if _finite(x) else str(x),
            'y': y if _finite(y) else str(y),
            'z': z if _finite(z) else str(z),
            'goals_executed': self._goals_executed,
            'received_at': received_at,
        }, ensure_ascii=False))

        # 2. minimal feedback
        if self.emit_feedback:
            try:
                goal_handle.publish_feedback(
                    PatrolNavigate.Feedback(progress=0.5, phase='EXECUTING'))
            except Exception:  # noqa: BLE001 - feedback is best effort
                pass

        # 3. optional latency / failure simulation (test hooks)
        if self.simulate_delay_sec > 0.0:
            time.sleep(self.simulate_delay_sec)

        if self.simulate_failure:
            goal_handle.abort()
            return PatrolNavigate.Result(
                success=False,
                status_code=reason_codes.EXECUTION_FAILED,
                detail='simulated executor failure for request_id={0}'.format(request_id),
            )

        goal_handle.succeed()
        return PatrolNavigate.Result(
            success=True,
            status_code=reason_codes.EXECUTED,
            detail='recorded target ({0}, {1}, {2}) in frame {3}; no path planning performed'.format(
                x, y, z, frame_id),
        )

    def destroy_node(self) -> bool:
        self.get_logger().info('NAVSIM_COUNTERS ' + json.dumps({
            'goals_executed': self._goals_executed,
            'journal_path': self._journal.path,
        }, ensure_ascii=False))
        try:
            self._server.destroy()
        except Exception:  # noqa: BLE001
            pass
        self._journal.close()
        return super().destroy_node()


def _finite(value: float) -> bool:
    return value == value and value not in (float('inf'), float('-inf'))


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
    node = NavigationSim()
    executor = MultiThreadedExecutor(num_threads=EXECUTOR_THREADS)
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
