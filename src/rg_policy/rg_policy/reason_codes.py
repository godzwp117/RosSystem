"""Frozen reason-code / status-code vocabulary.

Source of truth: 方案v1.2 §2.3 "首轮 reason_code 规范".

Two distinct vocabularies are kept separate on purpose:

* ``DECISION_REASON_CODES`` -- produced by the *synchronous admission decision*
  inside the Gateway. Recorded in ``DecisionEvent.reason_code``.
* ``EXECUTION_STATUS_CODES`` -- produced while *forwarding and executing* an
  already-ALLOWed request. Recorded in ``ExecutionEvent.status_code`` and
  passed back through ``PatrolNavigate.Result.status_code``.

Codes are never invented at runtime: every value written to an audit record
must come from this module (enforced by the event dataclasses).
"""

from typing import Tuple

# --------------------------------------------------------------------------
# Decision reason codes (方案v1.2 §2.3)
# --------------------------------------------------------------------------
ALLOW_IN_POLICY = 'ALLOW_IN_POLICY'
TASK_MISMATCH = 'TASK_MISMATCH'
INVALID_TARGET = 'INVALID_TARGET'
OUT_OF_REGION = 'OUT_OF_REGION'
POLICY_MISSING = 'POLICY_MISSING'
DUPLICATE_REQUEST = 'DUPLICATE_REQUEST'
RATE_LIMIT = 'RATE_LIMIT'
EXECUTION_TIMEOUT = 'EXECUTION_TIMEOUT'

DECISION_REASON_CODES: Tuple[str, ...] = (
    ALLOW_IN_POLICY,
    TASK_MISMATCH,
    INVALID_TARGET,
    OUT_OF_REGION,
    POLICY_MISSING,
    DUPLICATE_REQUEST,
    RATE_LIMIT,
    EXECUTION_TIMEOUT,
)

#: Reason codes that mean "do not create a downstream Goal".
BLOCK_REASON_CODES: Tuple[str, ...] = tuple(
    code for code in DECISION_REASON_CODES if code != ALLOW_IN_POLICY
)

# --------------------------------------------------------------------------
# Documented extension (NOT part of the 首轮 list above).
#
# 方案v1.2 §2.3 requires that "审计服务失效不能绕过准入判断" and §3.3 that
# "日志失败不得放行违规请求". When the audit sink itself is unwritable the
# Gateway must still block, but none of the eight frozen codes truthfully names
# that cause -- mislabelling it as POLICY_MISSING/INVALID_TARGET would corrupt
# the audit trail. So exactly one extra code is added, kept in a separate tuple
# so that DECISION_REASON_CODES above remains the frozen contract.
# --------------------------------------------------------------------------
AUDIT_UNAVAILABLE = 'AUDIT_UNAVAILABLE'

#: Vocabulary accepted by DecisionEvent validation (frozen 8 + documented extension).
ACCEPTED_DECISION_REASON_CODES: Tuple[str, ...] = DECISION_REASON_CODES + (AUDIT_UNAVAILABLE,)

# --------------------------------------------------------------------------
# Decision verdicts
# --------------------------------------------------------------------------
DECISION_ALLOW = 'ALLOW'
DECISION_BLOCK = 'BLOCK'
DECISIONS: Tuple[str, ...] = (DECISION_ALLOW, DECISION_BLOCK)

# --------------------------------------------------------------------------
# Execution status codes (forwarding / executor phase)
# --------------------------------------------------------------------------
EXECUTED = 'EXECUTED'
EXECUTION_FAILED = 'EXECUTION_FAILED'
DOWNSTREAM_REJECTED = 'DOWNSTREAM_REJECTED'

EXECUTION_STATUS_CODES: Tuple[str, ...] = (
    EXECUTED,
    EXECUTION_FAILED,
    EXECUTION_TIMEOUT,
    DOWNSTREAM_REJECTED,
)

# --------------------------------------------------------------------------
# Explicit "no value exists" markers.
# 方案v1.2 §2.3: "关键字段不得默默赋默认值" -- when a field genuinely has no
# value (e.g. no policy could be loaded, no downstream Goal was ever created),
# an explicit, greppable marker is written instead of an empty string, so that
# "absent" can never be confused with "silently defaulted".
# --------------------------------------------------------------------------
POLICY_VERSION_UNKNOWN = 'UNKNOWN'
DOWNSTREAM_GOAL_ID_NONE = 'NONE'
TASK_ID_UNKNOWN = 'UNKNOWN'

# --------------------------------------------------------------------------
# Human-readable explanations, attached to audit records and Result.detail.
# --------------------------------------------------------------------------
REASON_DESCRIPTIONS = {
    ALLOW_IN_POLICY: 'request satisfies the authoritative TaskPolicy',
    TASK_MISMATCH: 'request task_id does not match the authoritative TaskPolicy task_id',
    INVALID_TARGET: 'request fields, frame_id, or target numbers are not usable',
    OUT_OF_REGION: 'target lies outside the authoritative allowed_region',
    POLICY_MISSING: 'no usable authoritative TaskPolicy is loaded (fail closed)',
    DUPLICATE_REQUEST: 'request_id was already seen within the duplicate window',
    RATE_LIMIT: 'admitted request rate exceeds max_requests_per_minute',
    EXECUTION_TIMEOUT: 'downstream execution did not finish within the configured timeout',
    AUDIT_UNAVAILABLE: 'audit sink is unwritable; failing closed instead of bypassing admission',
}


def describe(code: str) -> str:
    """Return a stable human-readable description for a reason/status code."""
    if code in REASON_DESCRIPTIONS:
        return REASON_DESCRIPTIONS[code]
    return 'downstream execution reported: {0}'.format(code)


def is_known_reason_code(code: str) -> bool:
    return code in DECISION_REASON_CODES


def is_accepted_reason_code(code: str) -> bool:
    return code in ACCEPTED_DECISION_REASON_CODES


def is_known_status_code(code: str) -> bool:
    return code in EXECUTION_STATUS_CODES
