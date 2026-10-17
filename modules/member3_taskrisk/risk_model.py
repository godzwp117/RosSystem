"""Independent explainable advisory rules. No ROS and no authorization.

Policies and optional Gateway history are operator-selected local read-only
paths. Historical inference is a snapshot, not Gateway's concurrent tracker.
"""
from __future__ import annotations

import hashlib
import math
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml

from rg_policy import reason_codes as rc
from rg_policy.task_policy import PolicyError, PolicySchemaError, parse_task_policy
from validate_team_contracts import check_rfc3339, load_json_strict_text

MAX_POLICY_BYTES = 65536
MAX_HISTORY_BYTES = 4 * 1024 * 1024
MAX_HISTORY_RECORDS = 20000
EVIDENCE_KINDS = {"RUNTIME_LOG", "CONTROLLED_SECURITY_EXPERIMENT", "UNIT_TEST"}


class HistoryUnavailable(ValueError):
    """Missing, incomplete, stale or temporally inconsistent evidence."""


class HistoryInvalid(ValueError):
    """Evidence exists but its content is malformed."""


class UniqueSafeLoader(yaml.SafeLoader):
    """Reject duplicate YAML keys instead of choosing the last one."""


def _unique_mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise PolicySchemaError("duplicate policy key: {0}".format(key))
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


@dataclass(frozen=True)
class Settings:
    policy_path: Path
    boundary_margin_m: float = 0.25  # distance heuristic, NOT a probability
    audit_log: Path | None = None
    audit_kind: str = "UNKNOWN"
    audit_session_start: str | None = None
    max_history_age_sec: float = 30.0
    duplicate_ttl_sec: float = 600.0

    def __post_init__(self):
        for name in ("boundary_margin_m", "max_history_age_sec", "duplicate_ttl_sec"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError("{0} must be finite numeric configuration".format(name))
            if not math.isfinite(value) or value < 0 or (
                    name != "boundary_margin_m" and value == 0):
                raise ValueError("invalid {0}".format(name))
        if self.audit_log is None and self.audit_session_start is not None:
            raise ValueError("session start requires --audit-log")


def timestamp(value):
    if not isinstance(value, str) or not check_rfc3339(value):
        raise HistoryInvalid("invalid timezone-aware timestamp")
    return datetime.fromisoformat(value.upper().replace("Z", "+00:00")).timestamp()


def load_policy(path):
    """Read bytes once so the recorded hash matches the parsed policy."""
    try:
        with Path(path).open("rb") as handle:
            raw = handle.read(MAX_POLICY_BYTES + 1)
    except OSError as exc:
        raise FileNotFoundError("local TaskPolicy unavailable") from exc
    if len(raw) > MAX_POLICY_BYTES:
        raise PolicySchemaError("TaskPolicy exceeds byte limit")
    try:
        document = yaml.load(raw.decode("utf-8"), Loader=UniqueSafeLoader)
        policy = parse_task_policy(document, str(path))
    except (yaml.YAMLError, UnicodeError, ValueError, TypeError, OverflowError,
            RecursionError) as exc:
        raise PolicySchemaError("TaskPolicy cannot be validated") from exc
    if len(policy.policy_version) > 64:
        raise PolicySchemaError("policy version exceeds output contract limit")
    return policy, hashlib.sha256(raw).hexdigest()


def read_history(settings, now):
    """Read a bounded whole-session journal from trusted local configuration.

    Operator must select ONE Gateway's dedicated journal, starting empty at
    audit_session_start. JSON cannot authenticate this precondition. Torn lines,
    missing pairs and stale files fail closed. mtime does not prove a live node.
    """
    if settings.audit_kind not in EVIDENCE_KINDS or not settings.audit_session_start:
        raise HistoryUnavailable("history provenance/session start not configured")
    start = timestamp(settings.audit_session_start)
    if start > now:
        raise HistoryUnavailable("session start is in the future")
    try:
        with Path(settings.audit_log).open("rb") as handle:
            info = os.fstat(handle.fileno())
            raw = handle.read(MAX_HISTORY_BYTES + 1)
    except OSError as exc:
        raise HistoryUnavailable("configured Gateway journal unavailable") from exc
    if len(raw) > MAX_HISTORY_BYTES:
        raise HistoryUnavailable("whole-session journal exceeds bounded capacity")
    if now - info.st_mtime > settings.max_history_age_sec or info.st_mtime > now + 5:
        raise HistoryUnavailable("journal snapshot is stale or clock is inconsistent")
    if raw and not raw.endswith(b"\n"):
        raise HistoryUnavailable("journal has a torn/in-progress final record")
    try:
        lines = raw.decode("utf-8").splitlines()
        if len(lines) > MAX_HISTORY_RECORDS:
            raise HistoryUnavailable("journal record limit exceeded")
        records = [load_json_strict_text(line, "Gateway history") for line in lines]
    except HistoryUnavailable:
        raise
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise HistoryInvalid("invalid journal JSONL") from exc
    arrivals, decisions = {}, {}
    for row in records:
        if not isinstance(row, dict):
            raise HistoryInvalid("journal record is not an object")
        event_type = row.get("event_type")
        if event_type not in {"RosCommEvent", "DecisionEvent", "ExecutionEvent"}:
            raise HistoryInvalid("unknown journal event type")
        if event_type == "ExecutionEvent":
            continue  # execution is not admission or a rate-budget input
        event_id = row.get("event_id")
        if not isinstance(event_id, str) or not event_id.strip():
            raise HistoryInvalid("missing event_id")
        if not all(isinstance(row.get(k), str) for k in ("request_id", "task_id")):
            raise HistoryInvalid("invalid request/task correlation")
        if event_type == "RosCommEvent":
            if row.get("resource") != "/rg/guarded_navigate" or event_id in arrivals:
                raise HistoryInvalid("wrong resource or duplicate arrival event")
            when = timestamp(row.get("received_at"))
            arrivals[event_id] = (when, row)
        else:
            if event_id in decisions or row.get("decision") not in rc.DECISIONS:
                raise HistoryInvalid("ambiguous decision event")
            if row.get("reason_code") not in rc.ACCEPTED_DECISION_REASON_CODES:
                raise HistoryInvalid("unknown Gateway reason code")
            when = timestamp(row.get("decision_at"))
            if (row["decision"] == "ALLOW") != (row["reason_code"] == rc.ALLOW_IN_POLICY):
                raise HistoryInvalid("inconsistent decision/reason code")
            decisions[event_id] = (when, row)
        if when < start or when > now:
            raise HistoryUnavailable("journal time is outside the configured session")
    if set(arrivals) != set(decisions):
        raise HistoryUnavailable("incomplete receipt/decision pairs")
    first_seen, admitted = {}, []
    for event_id, (when, row) in sorted(arrivals.items(), key=lambda kv: kv[1][0]):
        decision_at, decision = decisions[event_id]
        if (row["request_id"], row["task_id"]) != (decision["request_id"], decision["task_id"]):
            raise HistoryInvalid("receipt/decision correlation mismatch")
        if decision_at < when:
            raise HistoryUnavailable("decision precedes arrival; clock discontinuity")
        first_seen = {key: t for key, t in first_seen.items()
                      if t >= when - settings.duplicate_ttl_sec}
        first_seen.setdefault(row["request_id"], when)
        if decision["decision"] == "ALLOW":
            admitted.append(when)  # approximate Gateway monotonic admission by arrival time
    first_seen = {key: t for key, t in first_seen.items()
                  if t >= now - settings.duplicate_ttl_sec}
    return {"first_seen": first_seen,
            "admitted_in_window": sum(t >= now - 60.0 for t in admitted),
            "journal_sha256": hashlib.sha256(raw).hexdigest(),
            "record_count": len(records), "session_start": settings.audit_session_start,
            "operator_assumption": "dedicated complete current-session journal",
            "clock_basis": "wall-clock snapshot; not Gateway monotonic tracker"}


def reason_item(code, field, text):
    return {"reason_code": code, "policy_field": field, "explanation": text}


def infer(envelope, settings, now):
    """Compute independent rule advice + signed distance to allowed boundary.

    No call to policy_engine.evaluate (reserved for independent comparison).
    Retain all violated static clauses; primary reason uses baseline order.
    """
    refs = [{"ref": "modules/member3_taskrisk/risk_model.py", "kind": "UNKNOWN",
             "note": "deterministic advisory implementation; no DDS authentication"}]
    metadata = {"algorithm": "TASK_CONSTRAINT_RULES_V1", "authority": "ADVISORY_ONLY",
                "violations": [], "features": {}, "reason_code": None,
                "pending_gateway_checks": ["DUPLICATE_REQUEST", "RATE_LIMIT",
                                            "EXECUTION_TIMEOUT", "AUDIT_UNAVAILABLE"],
                "runtime_monitor": "NOT_READY", "dynamic_state_model": "NOT_INTEGRATED"}

    def result(status, risk, reason, rules):
        return status, {"risk_level": risk, "reason": reason, "rule_basis": rules,
                        "evidence_refs": refs, "extensions": {"member3": metadata}}

    try:
        policy, digest = load_policy(settings.policy_path)
    except FileNotFoundError:
        metadata["reason_code"] = rc.POLICY_MISSING
        return result("UNKNOWN", "UNKNOWN", "POLICY_MISSING: 本地策略不可用，无法形成建议",
                      ["不存在可读取的本地 TaskPolicy；不得默认允许"])
    except PolicyError:
        metadata["reason_code"] = rc.POLICY_MISSING
        return result("ERROR", "UNKNOWN", "POLICY_MISSING: 本地策略解析或验证失败",
                      ["TaskPolicy 不可用；模块安全失败关闭"])
    refs.append({"ref": str(settings.policy_path)[-512:], "kind": "UNKNOWN",
                 "note": "trusted local configuration selection, not DDS authorization"})
    metadata["policy_content_sha256"] = digest  # NOT authoritative policy_digest
    action, target = envelope["candidate_action"], envelope["candidate_action"]["target"]
    features = metadata["features"]
    features.update(policy_active=policy.active, task_matches=action["task_id"] == policy.task_id,
                    frame_matches=target["frame_id"] == policy.coordinate_frame,
                    target_finite=all(math.isfinite(target.get(k, 0)) for k in ("x", "y", "z")))
    violations = metadata["violations"]
    if not policy.active:
        violations.append(reason_item(rc.POLICY_MISSING, "active", "策略 active=false"))
    if not envelope["request_id"].strip():
        violations.append(reason_item(rc.INVALID_TARGET, "request_id", "请求标识为空白"))
    if not features["task_matches"]:
        violations.append(reason_item(rc.TASK_MISMATCH, "task_id", "候选任务与策略任务不匹配"))
    if not features["frame_matches"]:
        violations.append(reason_item(rc.INVALID_TARGET, "coordinate_frame", "坐标系与策略不匹配"))
    if not features["target_finite"]:
        violations.append(reason_item(rc.INVALID_TARGET, "target", "目标数值不是有限数"))
    if features["frame_matches"] and features["target_finite"]:
        x, y, r = target["x"], target["y"], policy.region
        margin = min(x-r.x_min, r.x_max-x, y-r.y_min, r.y_max-y)
        features.update(region_inside=margin >= 0, signed_boundary_margin_m=margin)
        if margin < 0:
            violations.append(reason_item(rc.OUT_OF_REGION, "allowed_region", "目标超出允许区域"))
    metadata["checked_policy_version"] = policy.policy_version
    history_issue = None
    if settings.audit_log is not None and not violations:
        try:
            history = read_history(settings, now)
            metadata["history_snapshot"] = {k: v for k, v in history.items() if k != "first_seen"}
            refs.append({"ref": str(settings.audit_log)[-512:], "kind": settings.audit_kind,
                         "note": "read-only session snapshot; not realtime monitoring"})
            features["duplicate_in_snapshot"] = envelope["request_id"] in history["first_seen"]
            features["admitted_in_snapshot"] = history["admitted_in_window"]
            if features["duplicate_in_snapshot"]:
                violations.append(reason_item(rc.DUPLICATE_REQUEST, "request_tracker",
                                              "同一业务 request_id 在历史去重窗口内已到达"))
            if history["admitted_in_window"] >= int(policy.max_requests_per_minute):
                violations.append(reason_item(rc.RATE_LIMIT, "max_requests_per_minute",
                                              "历史已准入次数达到滑动 60 秒预算"))
            metadata["pending_gateway_checks"] = ["CONCURRENT_TRACKER_RECHECK",
                                                  "EXECUTION_TIMEOUT", "AUDIT_UNAVAILABLE"]
        except HistoryUnavailable as exc:
            history_issue = ("UNKNOWN", str(exc))
        except HistoryInvalid as exc:
            history_issue = ("ERROR", str(exc))
    if violations:
        metadata["reason_code"] = violations[0]["reason_code"]
        answer = result("BLOCK_RECOMMENDED", "HIGH",
                        "{0}: {1}".format(metadata["reason_code"], violations[0]["explanation"]),
                        ["{0}: {1} ({2})".format(v["reason_code"], v["explanation"],
                                                 v["policy_field"]) for v in violations])
    elif history_issue:
        status, text = history_issue
        metadata["history_error"] = text
        answer = result(status, "UNKNOWN", "配置的历史证据不可用：" + text,
                        ["历史推理要求未满足，不推进；最终授权仅属于 Gateway"])
    else:
        metadata["reason_code"] = rc.ALLOW_IN_POLICY
        risk = "LOW" if features["signed_boundary_margin_m"] <= settings.boundary_margin_m else "NONE"
        answer = result("ALLOW_RECOMMENDED", risk, "ALLOW_IN_POLICY: 已检查条款未发现冲突，仍须 Gateway 准入",
                        ["任务 ID、坐标系及目标满足本次读取的 TaskPolicy",
                         "允许区域边界为闭区间；边界接近仅是距离提示，不新增拒绝规则",
                         "未检查项与并发状态由 Gateway 最终判定；建议不是执行许可"])
    answer[1]["policy_ref"] = {"policy_version": policy.policy_version}
    return answer
