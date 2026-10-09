"""Pure admission-decision function.

方案v1.2 §3.3: "接口与判定分离：``policy_engine.evaluate(request, policy)`` 为纯
Python 函数，便于后续扩展。"

``evaluate`` is a *pure* function: no clock, no file IO, no ROS, no mutable
state. Duplicate detection and rate limiting are time-dependent, so they live in
``RequestTracker`` and are composed by the Gateway *around* this function. That
split keeps the security-relevant policy comparison exhaustively unit-testable.

Evaluation order (first failing rule wins; documented so that audit records are
reproducible when a request violates more than one rule):

1. policy absent / inactive          -> POLICY_MISSING
2. request_id missing                -> INVALID_TARGET
3. task_id missing or mismatched     -> TASK_MISMATCH
4. frame_id missing or mismatched    -> INVALID_TARGET
5. non-finite x/y/z                  -> INVALID_TARGET
6. target outside allowed_region     -> OUT_OF_REGION
7. otherwise                         -> ALLOW_IN_POLICY
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Optional

from . import reason_codes
from .task_policy import TaskPolicy


@dataclass(frozen=True)
class NavRequest:
    """Business-relevant projection of ``PatrolNavigate.Goal``.

    Deliberately ROS-free so that unit tests never need an rclpy context.
    """

    request_id: str
    task_id: str
    frame_id: str
    x: float
    y: float
    z: float = 0.0

    def as_dict(self) -> Dict[str, Any]:
        return {
            'request_id': self.request_id,
            'task_id': self.task_id,
            'frame_id': self.frame_id,
            'x': self.x,
            'y': self.y,
            'z': self.z,
        }


@dataclass(frozen=True)
class Decision:
    decision: str
    reason_code: str
    detail: str
    policy_version: str

    @property
    def allowed(self) -> bool:
        return self.decision == reason_codes.DECISION_ALLOW

    def as_dict(self) -> Dict[str, Any]:
        return {
            'decision': self.decision,
            'reason_code': self.reason_code,
            'detail': self.detail,
            'policy_version': self.policy_version,
        }


def _block(reason_code: str, detail: str, policy_version: str) -> Decision:
    return Decision(
        decision=reason_codes.DECISION_BLOCK,
        reason_code=reason_code,
        detail=detail,
        policy_version=policy_version,
    )


def _is_finite_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(float(value))


def evaluate(request: NavRequest, policy: Optional[TaskPolicy]) -> Decision:
    """Decide whether ``request`` may produce a downstream Goal.

    Returns a ``Decision``; never raises. A missing/inactive policy always
    blocks -- there is no bypass path.
    """
    # 1. authoritative policy present and in force
    if policy is None:
        return _block(
            reason_codes.POLICY_MISSING,
            'no authoritative TaskPolicy is loaded',
            reason_codes.POLICY_VERSION_UNKNOWN,
        )
    version = policy.policy_version
    if not policy.active:
        return _block(
            reason_codes.POLICY_MISSING,
            "authoritative policy '{0}' is marked active: false".format(version),
            version,
        )

    # 2. request_id must be usable for audit correlation
    if not isinstance(request.request_id, str) or not request.request_id.strip():
        return _block(
            reason_codes.INVALID_TARGET,
            'request_id must be a non-empty string',
            version,
        )

    # 3. task must match the authoritative policy (client self-report is not trusted)
    if not isinstance(request.task_id, str) or not request.task_id.strip():
        return _block(
            reason_codes.TASK_MISMATCH,
            'task_id must be a non-empty string',
            version,
        )
    if request.task_id != policy.task_id:
        return _block(
            reason_codes.TASK_MISMATCH,
            "request task_id '{0}' != policy task_id '{1}'".format(
                request.task_id, policy.task_id),
            version,
        )

    # 4. frame_id must equal the policy coordinate_frame
    if not isinstance(request.frame_id, str) or not request.frame_id.strip():
        return _block(
            reason_codes.INVALID_TARGET,
            'target frame_id must be a non-empty string',
            version,
        )
    if request.frame_id != policy.coordinate_frame:
        return _block(
            reason_codes.INVALID_TARGET,
            "target frame_id '{0}' != policy coordinate_frame '{1}'".format(
                request.frame_id, policy.coordinate_frame),
            version,
        )

    # 5. numbers must be finite (NaN / +-Inf are rejected, never coerced)
    for name, value in (('x', request.x), ('y', request.y), ('z', request.z)):
        if not _is_finite_number(value):
            return _block(
                reason_codes.INVALID_TARGET,
                'target.{0} is not a finite number: {1!r}'.format(name, value),
                version,
            )

    # 6. region containment (inclusive bounds)
    if not policy.region.contains(float(request.x), float(request.y)):
        return _block(
            reason_codes.OUT_OF_REGION,
            'target ({0}, {1}) outside allowed_region {2}'.format(
                request.x, request.y, policy.region.as_dict()),
            version,
        )

    # 7. allowed
    return Decision(
        decision=reason_codes.DECISION_ALLOW,
        reason_code=reason_codes.ALLOW_IN_POLICY,
        detail='target ({0}, {1}) inside allowed_region {2}'.format(
            request.x, request.y, policy.region.as_dict()),
        policy_version=version,
    )
