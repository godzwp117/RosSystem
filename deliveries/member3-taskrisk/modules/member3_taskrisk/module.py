#!/usr/bin/env python3
"""TaskRiskDecision stdin/stdout entry point; advice only, fail closed."""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
for path in (REPO / "scripts", REPO / "src" / "rg_policy", Path(__file__).resolve().parent):
    sys.path.insert(0, str(path))

import validate_team_contracts as vtc  # noqa: E402
from risk_model import Settings, infer  # noqa: E402

MODULE_VERSION = "0.1.0"
MAX_INPUT_BYTES = 1024 * 1024


def validate_input(envelope):
    def finite_tree(value):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("non-finite number in input")
        if isinstance(value, dict):
            for item in value.values():
                finite_tree(item)
        elif isinstance(value, list):
            for item in value:
                finite_tree(item)
    finite_tree(envelope)
    errors = vtc.validate_document(envelope, vtc.load_schema("module_input"))
    if errors:
        raise ValueError("input violates ModuleInputEnvelope: " + errors[0][:200])


def analyse(module, envelope, context):
    """Template-compatible algorithm hook. Configuration is NOT business JSON."""
    if module != "task_risk":
        raise ValueError("this implementation only supports task_risk")
    return infer(envelope, context["settings"], context["now"])


def build_output(envelope, state, detail):
    action = envelope["candidate_action"]
    document = {
        "schema_version": vtc.CONTRACT_VERSION,
        "run_id": envelope["run_id"], "request_id": envelope["request_id"],
        "event_id": "m3-{0}-{1}".format(envelope["request_id"][:80], uuid.uuid4().hex),
        "producer": {"name": "member3_taskrisk", "source": "EXTERNAL",
                     "module_version": MODULE_VERSION},
        "observed_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "status": state, "task_id": action["task_id"],
        "candidate_action": {"action_resource": action["action_resource"],
                             "operation": action["operation"]},
        "target": dict(action["target"]),
        **detail,
    }
    errors = vtc.validate_document(document, vtc.load_schema("task_risk_decision"))
    if errors:
        raise ValueError("internal output contract violation: " + errors[0][:200])
    return document


def decide(envelope, settings, now=None):
    validate_input(envelope)
    state, detail = analyse("task_risk", envelope,
                            {"settings": settings, "now": time.time() if now is None else now})
    return build_output(envelope, state, detail)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Member 3 task risk advisory rules")
    parser.add_argument("--module", choices=["task_risk"], default="task_risk")
    parser.add_argument("--policy", type=Path, default=REPO / "config" / "task_policy.yaml")
    parser.add_argument("--boundary-margin-m", type=float, default=0.25)
    parser.add_argument("--audit-log", type=Path)
    parser.add_argument("--audit-kind", choices=["RUNTIME_LOG", "CONTROLLED_SECURITY_EXPERIMENT",
                                               "UNIT_TEST", "UNKNOWN"], default="UNKNOWN")
    parser.add_argument("--audit-session-start", help="operator-set RFC3339 Gateway session start")
    parser.add_argument("--max-history-age-sec", type=float, default=30.0)
    parser.add_argument("--duplicate-ttl-sec", type=float, default=600.0)
    args = parser.parse_args(argv)
    try:
        settings = Settings(args.policy, args.boundary_margin_m, args.audit_log, args.audit_kind,
                            args.audit_session_start, args.max_history_age_sec, args.duplicate_ttl_sec)
        raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        if len(raw) > MAX_INPUT_BYTES:
            raise ValueError("stdin exceeds 1 MiB limit")
        envelope = vtc.load_json_strict_text(raw.decode("utf-8"), "stdin")
        validate_input(envelope)
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        print("[member3] invalid input/config: " + str(exc)[:250], file=sys.stderr)
        return 2
    try:
        state, detail = analyse("task_risk", envelope, {"settings": settings, "now": time.time()})
        document = build_output(envelope, state, detail)
    except Exception as exc:
        print("[member3] internal failure: " + type(exc).__name__, file=sys.stderr)
        try:
            document = build_output(envelope, "ERROR", {
                "reason": "模块内部异常，未能形成任务风险判断",
                "risk_level": "UNKNOWN", "rule_basis": ["内部异常必须失败关闭"],
                "evidence_refs": [{"ref": "modules/member3_taskrisk/module.py", "kind": "UNKNOWN",
                                   "note": "internal failure; no permission inferred"}]})
        except Exception:
            return 4
    print("[member3] status=" + document["status"], file=sys.stderr)
    print(json.dumps(document, ensure_ascii=False, allow_nan=False, separators=(",", ":")))
    return 0  # successful protocol execution != allow


if __name__ == "__main__":
    sys.exit(main())
