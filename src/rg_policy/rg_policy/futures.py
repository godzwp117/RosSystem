"""Bounded waiting on future-like objects, without importing rclpy.

rclpy's ``Future`` is used from two different thread contexts in this project
(the Gateway's Action Server worker thread and the Planner's main thread), so the
bounded-wait helper lives here as shared, ROS-free, unit-testable code.

Safety note for the Gateway
---------------------------
Blocking inside an rclpy Action ``execute_callback`` is only deadlock-free under a
specific executor arrangement. ``MultiThreadedExecutor`` (rclpy 7.1.12,
``executors.py``) submits every waitable callback as a task onto its internal
``ThreadPoolExecutor``; ``await_or_execute`` invokes a *synchronous* callback
inline on that worker. Blocking here therefore occupies exactly one worker
thread while the remaining workers keep servicing peer responses -- provided the
caller passes a non-coroutine callback, uses a multi-threaded executor with
``num_threads >= 2``, and registers its Action Client in a separate
``ReentrantCallbackGroup``. Callers outside that arrangement must not use this
helper from inside a ROS callback.
"""

from __future__ import annotations

import threading
from typing import Any


class WaitTimeout(Exception):
    """A bounded wait expired."""


def wait_for_future(future: Any, timeout_sec: float, what: str) -> Any:
    """Block the current thread until ``future`` settles, or raise ``WaitTimeout``.

    ``future`` must provide ``add_done_callback(cb)`` and ``result()`` (the rclpy
    ``Future`` contract). ``result()`` re-raises any exception stored on the
    future, which callers must handle as a fail-closed condition.
    """
    done = threading.Event()
    future.add_done_callback(lambda _future: done.set())
    if not done.wait(timeout_sec):
        raise WaitTimeout('{0} did not complete within {1:.3f}s'.format(what, timeout_sec))
    return future.result()
