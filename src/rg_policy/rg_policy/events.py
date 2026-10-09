"""Audit event schema + append-only JSONL sink.

方案v1.2 §2.3 frozen fields:

    RosCommEvent   event_id, request_id, task_id, observed_via, resource,
                   frame_id, x, y, received_at          (on Goal reception)
    DecisionEvent  event_id, policy_version, decision, reason_code,
                   decision_at                          (after sync evaluation)
    ExecutionEvent event_id, downstream_goal_id, success, status_code,
                   finished_at                          (after executor result)

All three share one ``event_id`` per request and always carry ``request_id``
(and ``task_id``) so a single request can be traced end to end, including the
rejected case where no ExecutionEvent may ever exist.

Design notes
------------
* ``__post_init__`` validates every field, so a malformed audit record raises at
  construction time instead of silently reaching the log. Missing values must be
  passed as explicit markers (``POLICY_VERSION_UNKNOWN`` /
  ``DOWNSTREAM_GOAL_ID_NONE``); there are no constructor defaults.
* Emitted JSON is strict (``allow_nan=False``). A non-finite target number --
  which is a *valid thing to receive and must be recorded faithfully* -- is
  written as the string ``"NaN"`` / ``"Infinity"`` / ``"-Infinity"`` and flagged
  by the explicit ``target_finite`` boolean. Nothing is silently sanitized.
"""

from __future__ import annotations

import json
import math
import os
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, ClassVar, Dict, Iterable, List, Optional

from . import reason_codes


def utc_now_iso() -> str:
    """ISO-8601 UTC, millisecond precision, ``Z`` suffix."""
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def new_event_id() -> str:
    return uuid.uuid4().hex


def encode_number(value: Any) -> Any:
    """Encode a target component without losing information.

    Finite -> JSON number. Non-finite -> canonical string token, so the record
    stays strictly-parseable JSON while remaining faithful to the input.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return str(value)
    number = float(value)
    if math.isnan(number):
        return 'NaN'
    if math.isinf(number):
        return 'Infinity' if number > 0 else '-Infinity'
    return number


def _require_str(value: Any, field: str, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError("event field '{0}' must be a string, got {1}".format(
            field, type(value).__name__))
    if not allow_empty and not value.strip():
        raise ValueError(
            "event field '{0}' must not be empty; pass an explicit marker instead".format(field))
    return value


def _require_bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError("event field '{0}' must be a boolean, got {1}".format(
            field, type(value).__name__))
    return value


def _require_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("event field '{0}' must be a number, got {1}".format(
            field, type(value).__name__))
    return float(value)


@dataclass(frozen=True)
class RosCommEvent:
    """Created the moment the Gateway receives an Action Goal."""

    EVENT_TYPE: ClassVar[str] = 'RosCommEvent'

    event_id: str
    request_id: str
    task_id: str
    observed_via: str
    resource: str
    frame_id: str
    x: float
    y: float
    z: float
    received_at: str

    def __post_init__(self) -> None:
        object.__setattr__(self, 'event_id', _require_str(self.event_id, 'event_id'))
        object.__setattr__(self, 'request_id', _require_str(
            self.request_id, 'request_id', allow_empty=True))
        object.__setattr__(self, 'task_id', _require_str(
            self.task_id, 'task_id', allow_empty=True))
        object.__setattr__(self, 'observed_via', _require_str(self.observed_via, 'observed_via'))
        object.__setattr__(self, 'resource', _require_str(self.resource, 'resource'))
        object.__setattr__(self, 'frame_id', _require_str(
            self.frame_id, 'frame_id', allow_empty=True))
        object.__setattr__(self, 'x', _require_number(self.x, 'x'))
        object.__setattr__(self, 'y', _require_number(self.y, 'y'))
        object.__setattr__(self, 'z', _require_number(self.z, 'z'))
        object.__setattr__(self, 'received_at', _require_str(self.received_at, 'received_at'))

    @property
    def target_finite(self) -> bool:
        return all(math.isfinite(value) for value in (self.x, self.y, self.z))

    def to_dict(self) -> Dict[str, Any]:
        return {
            'event_type': self.EVENT_TYPE,
            'event_id': self.event_id,
            'request_id': self.request_id,
            'task_id': self.task_id,
            'observed_via': self.observed_via,
            'resource': self.resource,
            'frame_id': self.frame_id,
            'x': encode_number(self.x),
            'y': encode_number(self.y),
            'z': encode_number(self.z),
            'target_finite': self.target_finite,
            'received_at': self.received_at,
        }


@dataclass(frozen=True)
class DecisionEvent:
    """Created after the synchronous admission rules have been evaluated."""

    EVENT_TYPE: ClassVar[str] = 'DecisionEvent'

    event_id: str
    request_id: str
    task_id: str
    policy_version: str
    decision: str
    reason_code: str
    detail: str
    decision_at: str
    # --- M3 可选关联字段（向后兼容：老代码不传则为 None，事件结构不破坏）---
    task_phase: str = None
    policy_epoch: int = None
    policy_digest: str = None

    def __post_init__(self) -> None:
        object.__setattr__(self, 'event_id', _require_str(self.event_id, 'event_id'))
        object.__setattr__(self, 'request_id', _require_str(
            self.request_id, 'request_id', allow_empty=True))
        object.__setattr__(self, 'task_id', _require_str(
            self.task_id, 'task_id', allow_empty=True))
        object.__setattr__(self, 'policy_version', _require_str(
            self.policy_version, 'policy_version'))
        decision = _require_str(self.decision, 'decision')
        if decision not in reason_codes.DECISIONS:
            raise ValueError("event field 'decision' must be one of {0}, got {1!r}".format(
                reason_codes.DECISIONS, decision))
        reason = _require_str(self.reason_code, 'reason_code')
        if not reason_codes.is_accepted_reason_code(reason):
            raise ValueError(
                "event field 'reason_code' must come from rg_policy.reason_codes, got {0!r}"
                .format(reason))
        object.__setattr__(self, 'reason_code', reason)
        object.__setattr__(self, 'detail', _require_str(self.detail, 'detail'))
        object.__setattr__(self, 'decision_at', _require_str(self.decision_at, 'decision_at'))

    def to_dict(self) -> Dict[str, Any]:
        return {
            'event_type': self.EVENT_TYPE,
            'event_id': self.event_id,
            'request_id': self.request_id,
            'task_id': self.task_id,
            'policy_version': self.policy_version,
            'decision': self.decision,
            'reason_code': self.reason_code,
            'detail': self.detail,
            'decision_at': self.decision_at,
            'task_phase': self.task_phase,
            'policy_epoch': self.policy_epoch,
            'policy_digest': self.policy_digest,
        }


@dataclass(frozen=True)
class ExecutionEvent:
    """Created only after a downstream Goal was created and reached a terminal state."""

    EVENT_TYPE: ClassVar[str] = 'ExecutionEvent'

    event_id: str
    request_id: str
    task_id: str
    downstream_goal_id: str
    success: bool
    status_code: str
    detail: str
    finished_at: str

    def __post_init__(self) -> None:
        object.__setattr__(self, 'event_id', _require_str(self.event_id, 'event_id'))
        object.__setattr__(self, 'request_id', _require_str(
            self.request_id, 'request_id', allow_empty=True))
        object.__setattr__(self, 'task_id', _require_str(
            self.task_id, 'task_id', allow_empty=True))
        object.__setattr__(self, 'downstream_goal_id', _require_str(
            self.downstream_goal_id, 'downstream_goal_id'))
        object.__setattr__(self, 'success', _require_bool(self.success, 'success'))
        status = _require_str(self.status_code, 'status_code')
        if not reason_codes.is_known_status_code(status):
            raise ValueError(
                "event field 'status_code' must come from rg_policy.reason_codes, got {0!r}"
                .format(status))
        object.__setattr__(self, 'status_code', status)
        object.__setattr__(self, 'detail', _require_str(self.detail, 'detail'))
        object.__setattr__(self, 'finished_at', _require_str(self.finished_at, 'finished_at'))

    def to_dict(self) -> Dict[str, Any]:
        return {
            'event_type': self.EVENT_TYPE,
            'event_id': self.event_id,
            'request_id': self.request_id,
            'task_id': self.task_id,
            'downstream_goal_id': self.downstream_goal_id,
            'success': self.success,
            'status_code': self.status_code,
            'detail': self.detail,
            'finished_at': self.finished_at,
        }


AuditEvent = (RosCommEvent, DecisionEvent, ExecutionEvent)


class AuditSinkError(RuntimeError):
    """Raised when an audit record could not be persisted."""


class EventWriter:
    """Thread-safe append-only JSONL sink.

    One line per event, flushed immediately, so an external test harness can
    tail and count records while the system is still running. The Gateway treats
    any write failure as a fail-closed condition.
    """

    def __init__(self, path: str, fsync: bool = False):
        self._path = os.path.abspath(str(path))
        self._fsync = bool(fsync)
        self._lock = threading.Lock()
        self._handle = None
        self._written = 0
        directory = os.path.dirname(self._path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        try:
            self._handle = open(self._path, 'a', encoding='utf-8')
        except OSError as exc:
            raise AuditSinkError('cannot open audit log {0}: {1}'.format(self._path, exc))

    @property
    def path(self) -> str:
        return self._path

    @property
    def written(self) -> int:
        with self._lock:
            return self._written

    def write(self, event: Any) -> Dict[str, Any]:
        if not hasattr(event, 'to_dict'):
            raise TypeError('audit events must expose to_dict(), got {0}'.format(type(event)))
        record = event.to_dict()
        line = json.dumps(record, ensure_ascii=False, allow_nan=False, sort_keys=False)
        with self._lock:
            if self._handle is None or self._handle.closed:
                raise AuditSinkError('audit log {0} is closed'.format(self._path))
            try:
                self._handle.write(line + '\n')
                self._handle.flush()
                if self._fsync:
                    os.fsync(self._handle.fileno())
            except OSError as exc:
                raise AuditSinkError(
                    'cannot write audit record to {0}: {1}'.format(self._path, exc))
            self._written += 1
        return record

    def close(self) -> None:
        with self._lock:
            if self._handle is not None and not self._handle.closed:
                self._handle.flush()
                self._handle.close()

    def __enter__(self) -> 'EventWriter':
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def read_events(path: str) -> List[Dict[str, Any]]:
    """Read a JSONL audit file into a list of dicts (harness / test helper)."""
    records: List[Dict[str, Any]] = []
    if not os.path.isfile(path):
        return records
    with open(path, 'r', encoding='utf-8') as handle:
        for line in handle:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def events_of_type(records: Iterable[Dict[str, Any]], event_type: str) -> List[Dict[str, Any]]:
    return [record for record in records if record.get('event_type') == event_type]


def trace_by_event_id(records: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Group audit records by ``event_id`` for end-to-end traceability checks."""
    grouped: Dict[str, Dict[str, Any]] = {}
    for record in records:
        key = record.get('event_id')
        bucket = grouped.setdefault(key, {'event_id': key, 'records': []})
        bucket['records'].append(record)
        bucket[record.get('event_type', 'unknown')] = record
    return grouped
