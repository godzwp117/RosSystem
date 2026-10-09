"""rg_policy -- ROS-free, unit-testable core of the RoboGuard minimal base.

Public surface
--------------
* ``reason_codes``    frozen reason/status vocabulary
* ``task_policy``     authoritative TaskPolicy loader + schema validation
* ``policy_engine``   pure ``evaluate(request, policy)`` admission decision
* ``request_tracker`` duplicate / rate-limit accounting
* ``events``          audit event schema + JSONL sink

Nothing in this package imports ``rclpy``: the security-relevant logic must be
testable without a ROS graph, and must never depend on the middleware for its
correctness.
"""

from . import (events, futures, policy_engine, reason_codes, request_tracker,
               task_policy, task_state)
from .events import (
    AuditSinkError,
    DecisionEvent,
    EventWriter,
    ExecutionEvent,
    RosCommEvent,
    events_of_type,
    new_event_id,
    read_events,
    trace_by_event_id,
    utc_now_iso,
)
from .futures import WaitTimeout, wait_for_future
from .policy_engine import Decision, NavRequest, evaluate
from .request_tracker import RequestTracker
from .task_state import (
    ActiveTaskSnapshot, STATE_ACTIVE, STATE_RECOVERY_REQUIRED, STATE_SWITCHING,
    STATE_UNINITIALIZED, TASK_STATES, TaskPhase, TaskStateMachine, TaskTransitionEvent,
    canonical_policy_payload, compute_policy_digest, parse_task_phases,
)
from .task_policy import (
    AllowedRegion,
    PolicyError,
    PolicyMissingError,
    PolicyProvider,
    PolicySchemaError,
    TaskPolicy,
    load_task_policy,
    parse_task_policy,
)

__all__ = [
    'events',
    'futures',
    'policy_engine',
    'reason_codes',
    'request_tracker',
    'task_policy',
    'task_state',
    'ActiveTaskSnapshot',
    'TaskPhase',
    'TaskStateMachine',
    'TaskTransitionEvent',
    'canonical_policy_payload',
    'compute_policy_digest',
    'parse_task_phases',
    'TASK_STATES',
    'AllowedRegion',
    'AuditSinkError',
    'Decision',
    'DecisionEvent',
    'EventWriter',
    'ExecutionEvent',
    'NavRequest',
    'PolicyError',
    'PolicyMissingError',
    'PolicyProvider',
    'PolicySchemaError',
    'RequestTracker',
    'RosCommEvent',
    'TaskPolicy',
    'WaitTimeout',
    'evaluate',
    'events_of_type',
    'load_task_policy',
    'new_event_id',
    'parse_task_policy',
    'read_events',
    'trace_by_event_id',
    'utc_now_iso',
    'wait_for_future',
]
