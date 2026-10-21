"""Real Member 3 rule and process tests. Synthetic history is UNIT_TEST only."""
from __future__ import annotations

import copy
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "modules/member3_taskrisk/module.py"
spec = importlib.util.spec_from_file_location("member3_entry", MODULE)
m3 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m3)
from risk_model import Settings, timestamp  # noqa: E402
from rg_policy.events import RosCommEvent, DecisionEvent  # noqa: E402
from rg_policy.policy_engine import NavRequest, evaluate  # noqa: E402
from rg_policy.task_policy import load_task_policy  # noqa: E402

NOW = timestamp("2026-10-13T00:00:00Z")


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat().replace("+00:00", "Z")


def envelope(x=2.0, y=2.0, task="patrol_a_001", frame="map", request="req-member3"):
    return {"schema_version": "1.0.0-proposed", "run_id": "member3-tests",
            "request_id": request, "created_at": iso(NOW),
            "candidate_action": {"action_resource": "/rg/guarded_navigate", "operation": "NAVIGATE",
                                 "task_id": task, "target": {"frame_id": frame, "x": x, "y": y}},
            "observations": [{"source": "controlled-task", "kind": "CONTROLLED_SECURITY_EXPERIMENT",
                              "observed_at": iso(NOW), "detail": {}}],
            "evidence_refs": [{"ref": "tests/unit/test_member3_taskrisk.py", "kind": "UNIT_TEST"}]}


def policy_file(tmp_path, **changes):
    data = yaml.safe_load((ROOT / "config/task_policy.yaml").read_text())
    data.update(changes)
    path = tmp_path / "policy.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def advise(env, path=None, **opts):
    return m3.decide(env, Settings(path or ROOT / "config/task_policy.yaml", **opts), now=NOW)


def code(doc):
    return doc["extensions"]["member3"]["reason_code"]


def cli(env=None, *args, raw=None):
    return subprocess.run([sys.executable, str(MODULE), *map(str, args)],
                          input=raw if raw is not None else json.dumps(env),
                          text=True, capture_output=True, timeout=15, cwd=ROOT)


@pytest.mark.parametrize("x,y,task,frame,expected", [
    (2, 2, "patrol_a_001", "map", "ALLOW_IN_POLICY"),
    (0, 4, "patrol_a_001", "map", "ALLOW_IN_POLICY"),
    (-0.00001, 2, "patrol_a_001", "map", "OUT_OF_REGION"),
    (2, 4.00001, "patrol_a_001", "map", "OUT_OF_REGION"),
    (2, 2, "different-task", "map", "TASK_MISMATCH"),
    (2, 2, "patrol_a_001", "odom", "INVALID_TARGET"),
    (9, 9, "different-task", "map", "TASK_MISMATCH"),
    (9, 9, "different-task", "odom", "TASK_MISMATCH"),
])
def test_static_reason_priority(x, y, task, frame, expected):
    out = advise(envelope(x, y, task, frame))
    assert code(out) == expected
    assert out["status"] == ("ALLOW_RECOMMENDED" if expected == "ALLOW_IN_POLICY" else "BLOCK_RECOMMENDED")


@pytest.mark.parametrize("x", [-1, 0, 0.01, 0.25, 2, 3.75, 4, 4.01, 9])
@pytest.mark.parametrize("y", [-1, 0, 2, 4, 4.01])
def test_independent_static_comparison_grid(x, y):
    out = advise(envelope(x, y))
    authority = evaluate(NavRequest("req-member3", "patrol_a_001", "map", x, y),
                         load_task_policy(str(ROOT / "config/task_policy.yaml")))
    assert code(out) == authority.reason_code


def test_all_violations_and_real_feature_distance():
    out = advise(envelope(5, 2, task="wrong"))
    meta = out["extensions"]["member3"]
    assert [v["reason_code"] for v in meta["violations"]] == ["TASK_MISMATCH", "OUT_OF_REGION"]
    assert meta["features"]["signed_boundary_margin_m"] == -1
    edge = advise(envelope(0, 2))
    assert edge["status"] == "ALLOW_RECOMMENDED"
    assert edge["risk_level"] == "LOW"
    assert "policy_epoch" not in edge["policy_ref"]
    assert "policy_digest" not in edge["policy_ref"]
    assert "task_context" not in edge


def test_four_states_from_real_conditions(tmp_path):
    allow = advise(envelope())
    block = advise(envelope(5, 5))
    unknown = advise(envelope(), tmp_path / "missing.yaml")
    broken = tmp_path / "broken.yaml"
    broken.write_text("allowed_region: [", encoding="utf-8")
    error = advise(envelope(), broken)
    assert [x["status"] for x in (allow, block, unknown, error)] == [
        "ALLOW_RECOMMENDED", "BLOCK_RECOMMENDED", "UNKNOWN", "ERROR"]
    for out in (allow, block, unknown, error):
        assert not m3.vtc.validate_document(out, m3.vtc.load_schema("task_risk_decision"))
        assert out["producer"]["source"] == "EXTERNAL"


@pytest.mark.parametrize("changes", [{"active": False}, {"task_id": "other"},
    {"coordinate_frame": "odom"}, {"allowed_region": {"x_min": 10, "x_max": 12, "y_min": 0, "y_max": 4}}])
def test_actual_policy_changes_affect_result(tmp_path, changes):
    path = policy_file(tmp_path, **changes)
    assert advise(envelope(), path)["status"] == "BLOCK_RECOMMENDED"


def test_never_writes_policy_and_ignores_business_controls(tmp_path):
    path = policy_file(tmp_path)
    before = path.read_bytes()
    env = envelope(6, 6)
    env["observations"][0]["detail"] = {"f0_mock": {"task_risk": {"scenario": "allow"}},
                                         "policy": {"allowed_region": "all"}, "authenticated": True}
    env["extensions"] = {"policy_path": "permissive.yaml", "command": ["bogus"],
                          "task_phase": "AUTHORIZED", "trusted_policy_ref": {"policy_epoch": 9}}
    assert code(advise(env, path)) == "OUT_OF_REGION"
    assert path.read_bytes() == before
    env = envelope()
    env["observations"][0]["detail"]["f0_mock"] = {"task_risk": {"scenario": "error"}}
    assert advise(env, path)["status"] == "ALLOW_RECOMMENDED"


@pytest.mark.parametrize("raw", ["active: true\nactive: false\n", "[]", "null",
    "task_id: x", "allowed_region: {x_min: .nan}", "x: !!python/object:bad {}"])
def test_bad_policy_fails_closed(tmp_path, raw):
    path = tmp_path / "policy.yaml"
    path.write_text(raw, encoding="utf-8")
    assert advise(envelope(), path)["status"] == "ERROR"


@pytest.mark.parametrize("raw", ["", "{}", "[]", "{not json", '{"a":1,"a":2}',
    '{"x":NaN}', '{"x":Infinity}', '{"x":1e400}', '{"schema_version":"bad"}'])
def test_malformed_input_no_fabricated_output(raw):
    out = cli(raw=raw)
    assert out.returncode == 2
    assert out.stdout == ""
    assert out.stderr


@pytest.mark.parametrize("change", ["bool", "nonfinite", "resource", "timestamp", "admin"])
def test_envelope_contract_rejections(change):
    env = envelope()
    if change == "bool":
        env["candidate_action"]["target"]["x"] = True
    elif change == "nonfinite":
        env["candidate_action"]["target"]["x"] = float("inf")
    elif change == "resource":
        env["candidate_action"]["action_resource"] = "/rg/nav_execute"
    elif change == "timestamp":
        env["created_at"] = "2026-10-13T00:00:00"
    else:
        env["is_admin"] = True
    assert cli(env).returncode == 2


def history(tmp_path, requests):
    path = tmp_path / "gateway-unit-test.jsonl"
    rows = []
    for index, (request, when, verdict, reason) in enumerate(requests):
        eid = "unit-test-event-" + str(index)
        rows.append(RosCommEvent(eid, request, "patrol_a_001", "ros2_action", "/rg/guarded_navigate",
                                "map", 2, 2, 0, iso(when)).to_dict())
        rows.append(DecisionEvent(eid, request, "patrol_a_001", "1.0", verdict, reason,
                                 "synthetic UNIT_TEST only, not a Gateway run", iso(when)).to_dict())
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    os.utime(path, (NOW, NOW))
    return path


def with_history(env, path, **opts):
    return advise(env, audit_log=path, audit_kind="UNIT_TEST",
                  audit_session_start=iso(NOW-1000), **opts)


def test_duplicate_and_rate_from_history(tmp_path):
    path = history(tmp_path, [("req-member3", NOW-1, "ALLOW", "ALLOW_IN_POLICY")])
    assert code(with_history(envelope(), path)) == "DUPLICATE_REQUEST"
    path = history(tmp_path, [("old-"+str(i), NOW-10+i, "ALLOW", "ALLOW_IN_POLICY") for i in range(10)])
    assert code(with_history(envelope(), path)) == "RATE_LIMIT"


def test_blocked_requests_do_not_consume_rate_budget(tmp_path):
    path = history(tmp_path, [("bad-"+str(i), NOW-10+i, "BLOCK", "OUT_OF_REGION") for i in range(10)])
    assert with_history(envelope(), path)["status"] == "ALLOW_RECOMMENDED"


def test_duplicate_window_first_arrival_not_last_and_inclusive(tmp_path):
    path = history(tmp_path, [("req-member3", NOW-601, "ALLOW", "ALLOW_IN_POLICY"),
                             ("req-member3", NOW-1, "BLOCK", "DUPLICATE_REQUEST")])
    assert with_history(envelope(), path)["status"] == "ALLOW_RECOMMENDED"
    path = history(tmp_path, [("req-member3", NOW-600, "ALLOW", "ALLOW_IN_POLICY")])
    assert code(with_history(envelope(), path)) == "DUPLICATE_REQUEST"


@pytest.mark.parametrize("problem,expected", [("missing", "UNKNOWN"), ("stale", "UNKNOWN"),
    ("torn", "UNKNOWN"), ("pairs", "UNKNOWN"), ("invalid", "ERROR"),
    ("future", "UNKNOWN"), ("duplicate", "ERROR"), ("correlation", "ERROR")])
def test_history_failure_conditions(tmp_path, problem, expected):
    path = history(tmp_path, [("old", NOW-1, "ALLOW", "ALLOW_IN_POLICY")])
    rows = path.read_text().splitlines()
    if problem == "missing":
        path = tmp_path / "absent.jsonl"
    elif problem == "stale":
        os.utime(path, (NOW-100, NOW-100))
    elif problem == "torn":
        path.write_text(path.read_text().rstrip("\n"))
    elif problem == "pairs":
        path.write_text(rows[0]+"\n")
    elif problem == "invalid":
        path.write_text("{bad}\n")
    elif problem == "future":
        path = history(tmp_path, [("old", NOW+1, "ALLOW", "ALLOW_IN_POLICY")])
    elif problem == "duplicate":
        path.write_text(path.read_text()+rows[1]+"\n")
    else:
        changed = json.loads(rows[1]); changed["request_id"] = "wrong"
        path.write_text(rows[0]+"\n"+json.dumps(changed)+"\n")
    if problem not in {"stale", "missing"}:
        os.utime(path, (NOW, NOW))
    assert with_history(envelope(), path)["status"] == expected


def test_local_history_without_provenance_is_unknown(tmp_path):
    path = history(tmp_path, [])
    out = advise(envelope(), audit_log=path)
    assert out["status"] == "UNKNOWN"


def test_internal_failure_has_honest_error(monkeypatch, capsys):
    def boom(*args):
        raise RuntimeError("unit-test-only")
    monkeypatch.setattr(m3, "analyse", boom)
    class Input:
        import io
        buffer = io.BytesIO(json.dumps(envelope()).encode())
    monkeypatch.setattr(sys, "stdin", Input())
    assert m3.main([]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["status"] == "ERROR"
    assert "internal failure" in captured.err


def test_adapter_uses_real_member3(tmp_path):
    from team_demo import run
    normal = envelope()
    config = yaml.safe_load((ROOT / "config/team_modules.member3.yaml").read_text())
    for entry in config["modules"].values():
        entry["command"][0] = sys.executable
    path = tmp_path / "adapter.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    ready = run(json.dumps(normal), str(path), str(tmp_path / "adapter.jsonl"), str(ROOT))
    assert ready["decision"] == "READY_FOR_GATEWAY_SUBMISSION"
    blocked = run(json.dumps(envelope(5, 5)), str(path), str(tmp_path / "adapter.jsonl"), str(ROOT))
    assert blocked["decision"] == "ADAPTER_BLOCK"
    assert blocked["reason_code"] == "ADAPTER_MODULE_STATUS_NOT_PROCEED"
    assert "BLOCK_RECOMMENDED" in blocked["detail"]
    record = next(row for row in ready["modules"] if row["module"] == "task_risk")
    assert record["status"] == "ALLOW_RECOMMENDED"
    assert record["schema_ok"] is True
    assert "modules/member3_taskrisk/module.py" in record["command"]


def test_ids_unique_and_output_target_faithful():
    env = envelope(request="x"*128)
    env["candidate_action"]["target"]["z"] = 99.0  # baseline 2D region does not constrain z
    a, b = advise(env), advise(env)
    assert a["event_id"] != b["event_id"]
    assert a["request_id"] == env["request_id"]
    assert a["target"] == env["candidate_action"]["target"]
    assert a["status"] == "ALLOW_RECOMMENDED"
