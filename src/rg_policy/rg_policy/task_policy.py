"""Read-only loader + schema validator for the authoritative TaskPolicy.

方案v1.2 §2.2 / §2.3:
  * the security policy is loaded *only* from local trusted configuration;
  * `/rg/task_info` may inform the Planner, but may never override the
    authoritative policy;
  * every load/validation failure is a fail-closed condition (POLICY_MISSING),
    never a warning that lets a request through;
  * required fields are never silently defaulted.

This module performs no ROS calls and holds no global state, so it is fully
unit-testable on a plain interpreter.
"""

from __future__ import annotations

import math
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional, Tuple

import yaml

from . import reason_codes

#: Fields that must be present in task_policy.yaml. Absence is a schema error.
REQUIRED_FIELDS: Tuple[str, ...] = (
    'task_id',
    'policy_version',
    'active',
    'coordinate_frame',
    'allowed_region',
    'max_requests_per_minute',
)

REGION_FIELDS: Tuple[str, ...] = ('x_min', 'x_max', 'y_min', 'y_max')


class PolicyError(Exception):
    """Base class for every authoritative-policy failure.

    Any PolicyError means "there is no usable authoritative policy right now",
    which the Gateway must translate into a BLOCK (reason POLICY_MISSING).
    """

    reason_code = reason_codes.POLICY_MISSING

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class PolicyMissingError(PolicyError):
    """The policy file does not exist or cannot be read."""


class PolicySchemaError(PolicyError):
    """The policy file exists but does not satisfy the frozen schema."""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def _require_non_empty_str(raw: Mapping[str, Any], field: str) -> str:
    value = raw[field]
    if not isinstance(value, str):
        raise PolicySchemaError(
            "field '{0}' must be a string, got {1}".format(field, type(value).__name__))
    if not value.strip():
        raise PolicySchemaError("field '{0}' must not be empty".format(field))
    return value


def _require_bool(raw: Mapping[str, Any], field: str) -> bool:
    value = raw[field]
    # bool is a subclass of int, so check it explicitly before any numeric check.
    if not isinstance(value, bool):
        raise PolicySchemaError(
            "field '{0}' must be a boolean, got {1}".format(field, type(value).__name__))
    return value


def _require_finite_number(raw: Mapping[str, Any], field: str) -> float:
    value = raw[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PolicySchemaError(
            "field '{0}' must be a number, got {1}".format(field, type(value).__name__))
    number = float(value)
    if not math.isfinite(number):
        raise PolicySchemaError(
            "field '{0}' must be a finite number, got {1!r}".format(field, value))
    return number


@dataclass(frozen=True)
class AllowedRegion:
    """Axis-aligned 2-D region from the authoritative policy (metres, map frame)."""

    x_min: float
    x_max: float
    y_min: float
    y_max: float

    def contains(self, x: float, y: float) -> bool:
        """Inclusive containment test. ``z`` is not constrained by a 2-D policy."""
        return self.x_min <= x <= self.x_max and self.y_min <= y <= self.y_max

    def as_dict(self) -> Dict[str, float]:
        return {'x_min': self.x_min, 'x_max': self.x_max,
                'y_min': self.y_min, 'y_max': self.y_max}


@dataclass(frozen=True)
class TaskPolicy:
    """Immutable snapshot of the authoritative task policy."""

    task_id: str
    policy_version: str
    active: bool
    coordinate_frame: str
    region: AllowedRegion
    max_requests_per_minute: float
    source_path: str
    loaded_at: str
    extra_fields: Tuple[str, ...] = ()

    def as_dict(self) -> Dict[str, Any]:
        return {
            'task_id': self.task_id,
            'policy_version': self.policy_version,
            'active': self.active,
            'coordinate_frame': self.coordinate_frame,
            'allowed_region': self.region.as_dict(),
            'max_requests_per_minute': self.max_requests_per_minute,
            'source_path': self.source_path,
            'loaded_at': self.loaded_at,
            'extra_fields': list(self.extra_fields),
        }


def parse_task_policy(document: Any, source_path: str) -> TaskPolicy:
    """Validate an already-parsed YAML document against the frozen schema."""
    if not isinstance(document, dict):
        raise PolicySchemaError(
            'policy root must be a mapping, got {0}'.format(type(document).__name__))

    missing = [field for field in REQUIRED_FIELDS if field not in document]
    if missing:
        raise PolicySchemaError(
            'policy is missing required field(s): {0}'.format(', '.join(sorted(missing))))

    task_id = _require_non_empty_str(document, 'task_id')
    policy_version = _require_non_empty_str(document, 'policy_version')
    active = _require_bool(document, 'active')
    coordinate_frame = _require_non_empty_str(document, 'coordinate_frame')
    max_requests_per_minute = _require_finite_number(document, 'max_requests_per_minute')
    if max_requests_per_minute <= 0:
        raise PolicySchemaError(
            'field max_requests_per_minute must be > 0, got {0!r}'.format(max_requests_per_minute))

    region_raw = document['allowed_region']
    if not isinstance(region_raw, dict):
        raise PolicySchemaError(
            'field allowed_region must be a mapping, got {0}'.format(type(region_raw).__name__))
    missing_region = [field for field in REGION_FIELDS if field not in region_raw]
    if missing_region:
        raise PolicySchemaError(
            'allowed_region is missing required field(s): {0}'.format(
                ', '.join(sorted(missing_region))))

    x_min = _require_finite_number(region_raw, 'x_min')
    x_max = _require_finite_number(region_raw, 'x_max')
    y_min = _require_finite_number(region_raw, 'y_min')
    y_max = _require_finite_number(region_raw, 'y_max')
    if x_min > x_max:
        raise PolicySchemaError('allowed_region x_min > x_max ({0} > {1})'.format(x_min, x_max))
    if y_min > y_max:
        raise PolicySchemaError('allowed_region y_min > y_max ({0} > {1})'.format(y_min, y_max))

    extra = tuple(sorted(set(document) - set(REQUIRED_FIELDS)))

    return TaskPolicy(
        task_id=task_id,
        policy_version=policy_version,
        active=active,
        coordinate_frame=coordinate_frame,
        region=AllowedRegion(x_min=x_min, x_max=x_max, y_min=y_min, y_max=y_max),
        max_requests_per_minute=max_requests_per_minute,
        source_path=str(source_path),
        loaded_at=_utc_now_iso(),
        extra_fields=extra,
    )


def load_task_policy(path: str) -> TaskPolicy:
    """Read + validate the authoritative policy file.

    Raises:
        PolicyMissingError: file absent / unreadable / not valid YAML.
        PolicySchemaError: file present but violating the frozen schema.
    """
    if path is None or not str(path).strip():
        raise PolicyMissingError('policy path is empty')

    resolved = str(path)
    if not os.path.isfile(resolved):
        raise PolicyMissingError('policy file not found: {0}'.format(resolved))

    try:
        with open(resolved, 'r', encoding='utf-8') as handle:
            text = handle.read()
    except OSError as exc:
        raise PolicyMissingError('policy file not readable: {0}: {1}'.format(resolved, exc))

    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise PolicySchemaError('policy YAML is not parseable: {0}: {1}'.format(resolved, exc))

    return parse_task_policy(document, resolved)


class PolicyProvider:
    """Read-only, mtime-cached policy loader.

    The file is opened read-only and never written by this process. Reloading is
    keyed on ``(st_mtime_ns, st_size)`` so that replacing the policy on disk takes
    effect on the next request without restarting the Gateway -- which is exactly
    what the "policy missing" / "policy swapped" scenarios exercise.

    A failed reload *replaces* the cached policy with ``None``: fail closed.
    """

    def __init__(self, path: str):
        self._path = str(path)
        self._lock = threading.Lock()
        self._cache_key: Optional[Tuple[int, int]] = None
        self._cached_policy: Optional[TaskPolicy] = None
        self._cached_error: Optional[PolicyError] = None
        self._reload_count = 0

    @property
    def path(self) -> str:
        return self._path

    @property
    def reload_count(self) -> int:
        with self._lock:
            return self._reload_count

    def _stat_key(self) -> Optional[Tuple[int, int]]:
        try:
            info = os.stat(self._path)
        except OSError:
            return None
        return (info.st_mtime_ns, info.st_size)

    def current(self) -> Tuple[Optional[TaskPolicy], Optional[PolicyError]]:
        """Return ``(policy, None)`` or ``(None, PolicyError)``. Never raises."""
        with self._lock:
            key = self._stat_key()
            if key is not None and key == self._cache_key:
                return self._cached_policy, self._cached_error

            try:
                policy = load_task_policy(self._path)
            except PolicyError as exc:
                policy, error = None, exc
            else:
                error = None

            self._cache_key = key
            self._cached_policy = policy
            self._cached_error = error
            self._reload_count += 1
            return policy, error

    def invalidate(self) -> None:
        with self._lock:
            self._cache_key = None
            self._cached_policy = None
            self._cached_error = None
