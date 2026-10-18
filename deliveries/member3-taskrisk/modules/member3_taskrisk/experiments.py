#!/usr/bin/env python3
"""Controlled rule evaluation; explicitly NOT a ROS 2 online evidence producer."""
from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import module as m3  # noqa: E402
from risk_model import Settings  # noqa: E402
from rg_policy.policy_engine import NavRequest, evaluate  # noqa: E402
from rg_policy.task_policy import load_task_policy, PolicyError  # noqa: E402
import team_demo  # noqa: E402

BASELINE_SHA = "a4c597161d254192b662ee7b8f4d17f76a89cc16"


def envelope(request_id, x=2.0, y=2.0, task="patrol_a_001", frame="map"):
    stamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {"schema_version": "1.0.0-proposed", "run_id": "member3-controlled",
            "request_id": request_id, "created_at": stamp,
            "candidate_action": {"action_resource": "/rg/guarded_navigate", "operation": "NAVIGATE",
                                 "task_id": task, "target": {"frame_id": frame, "x": x, "y": y}},
            "observations": [{"source": "controlled-action-generator", "kind": "CONTROLLED_SECURITY_EXPERIMENT",
                              "observed_at": stamp, "detail": {}}],
            "evidence_refs": [{"ref": "modules/member3_taskrisk/experiments.py",
                               "kind": "CONTROLLED_SECURITY_EXPERIMENT",
                               "note": "project-generated action cases, not ROSPaCe labels"}]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=m3.REPO / "logs/member3/offline")
    args = parser.parse_args(argv)
    out = args.out_dir.resolve()
    if (out / "report.json").exists():
        parser.error("output already contains report; choose a new directory")
    out.mkdir(parents=True, exist_ok=True)
    normal_policy = m3.REPO / "config/task_policy.yaml"
    policy = load_task_policy(str(normal_policy))
    inactive = out / "inactive-policy.yaml"
    inactive_doc = yaml.safe_load(normal_policy.read_text())
    inactive_doc["active"] = False
    inactive.write_text(yaml.safe_dump(inactive_doc), encoding="utf-8")
    broken = out / "broken-policy.yaml"
    broken.write_text("allowed_region: [", encoding="utf-8")
    missing = out / "missing-policy.yaml"
    controlled = []
    coordinates = [-0.001, 0.0, 0.01, 0.25, 2.0, 3.75, 3.99, 4.0, 4.001]
    for x in coordinates:
        for y in coordinates:
            expected = "ALLOW_IN_POLICY" if 0 <= x <= 4 and 0 <= y <= 4 else "OUT_OF_REGION"
            controlled.append((envelope("grid-{0}".format(len(controlled)), x, y), normal_policy, expected))
    controlled += [(envelope("wrong-task", task="other"), normal_policy, "TASK_MISMATCH"),
                   (envelope("wrong-frame", frame="odom"), normal_policy, "INVALID_TARGET"),
                   (envelope("multiple", 5, 5, task="other"), normal_policy, "TASK_MISMATCH"),
                   (envelope("inactive"), inactive, "POLICY_MISSING"),
                   (envelope("absent"), missing, "POLICY_MISSING"),
                   (envelope("broken"), broken, "POLICY_MISSING")]
    rows, durations = [], []
    for env, path, expected in controlled:
        started = time.perf_counter()
        answer = m3.decide(env, Settings(path))
        durations.append((time.perf_counter()-started)*1000)
        candidate, target = env["candidate_action"], env["candidate_action"]["target"]
        try:
            local_policy = load_task_policy(str(path))
        except PolicyError:
            local_policy = None
        reference = evaluate(NavRequest(env["request_id"], candidate["task_id"],
                                        target["frame_id"], target["x"], target["y"]), local_policy)
        reason = answer["extensions"]["member3"]["reason_code"]
        # Minimal, deliberately weaker ablation: geometry-only advice, no task/frame/policy checks.
        geometry_allow = 0 <= target["x"] <= 4 and 0 <= target["y"] <= 4
        rows.append({"request_id": env["request_id"], "input": env, "output": answer,
                     "expected_reason": expected, "actual_reason": reason,
                     "static_reference": reference.as_dict(),
                     "reference_is_live_gateway": False,
                     "geometry_only_ablation_allow": geometry_allow,
                     "correct": reason == expected,
                     "same_static_verdict": (answer["status"] == "ALLOW_RECOMMENDED") == reference.allowed})

    # Four REAL process conditions. Do not change f0_mock.scenario to control Member 3.
    matrix = [("allow", envelope("process-allow"), normal_policy, "ALLOW_RECOMMENDED"),
              ("block", envelope("process-block", 5, 5), normal_policy, "BLOCK_RECOMMENDED"),
              ("unknown", envelope("process-unknown"), missing, "UNKNOWN"),
              ("error", envelope("process-error"), broken, "ERROR")]
    process_rows = []
    config_base = yaml.safe_load((m3.REPO / "config/team_modules.member3.yaml").read_text())
    for label, env, path, expected in matrix:
        command = [sys.executable, str(Path(m3.__file__)), "--policy", str(path)]
        proc = subprocess.run(command, input=json.dumps(env), text=True, capture_output=True,
                              cwd=m3.REPO, timeout=15, shell=False)
        answer = json.loads(proc.stdout) if proc.stdout else None
        config = copy.deepcopy(config_base)
        for item in config["modules"].values():
            item["command"][0] = sys.executable
        config["modules"]["task_risk"]["command"] = command
        cfg = out / (label+"-adapter.yaml")
        cfg.write_text(yaml.safe_dump(config), encoding="utf-8")
        adapter_result = team_demo.run(json.dumps(env), str(cfg), str(out / "adapter.jsonl"), str(m3.REPO))
        expected_adapter = "READY_FOR_GATEWAY_SUBMISSION" if label == "allow" else "ADAPTER_BLOCK"
        passed = proc.returncode == 0 and answer is not None and answer["status"] == expected
        passed = passed and not m3.vtc.validate_document(answer, m3.vtc.load_schema("task_risk_decision"))
        passed = passed and adapter_result["decision"] == expected_adapter
        if label != "allow":
            passed = passed and adapter_result["reason_code"] == "ADAPTER_MODULE_STATUS_NOT_PROCEED"
        process_rows.append({"case": label, "command": command, "exit_code": proc.returncode,
                             "stderr": proc.stderr, "stdout_bytes": len(proc.stdout.encode()),
                             "output": answer, "adapter": adapter_result, "pass": passed})
        (out / (label+"-input.json")).write_text(json.dumps(env, ensure_ascii=False, indent=2), encoding="utf-8")
        (out / (label+"-output.json")).write_text(proc.stdout, encoding="utf-8")

    normal_rows = [r for r in rows if r["expected_reason"] == "ALLOW_IN_POLICY"]
    bad_rows = [r for r in rows if r["expected_reason"] != "ALLOW_IN_POLICY"]
    actual_allow = lambda r: r["output"]["status"] == "ALLOW_RECOMMENDED"
    report = {"baseline_sha": BASELINE_SHA, "contract_status": "PROPOSED_V1",
              "module_version": m3.MODULE_VERSION, "implementation": "deterministic rule prototype",
              "dataset_source": "controlled cases generated from local TaskPolicy; not captured ROS traffic",
              "case_count": len(rows), "correct_cases": sum(r["correct"] for r in rows),
              "static_comparator": "rg_policy.policy_engine.evaluate, NOT a live Gateway",
              "static_verdict_agreement": sum(r["same_static_verdict"] for r in rows)/len(rows),
              "false_positive_rate": sum(not actual_allow(r) for r in normal_rows)/len(normal_rows),
              "false_negative_rate": sum(actual_allow(r) for r in bad_rows)/len(bad_rows),
              "geometry_only_ablation_false_negative_rate": sum(r["geometry_only_ablation_allow"] for r in bad_rows)/len(bad_rows),
              "inprocess_latency_ms_median": sorted(durations)[len(durations)//2],
              "latency_note": "local in-process validation+rule calls, NOT realtime ROS throughput",
              "four_state_process_checks": process_rows,
              "L1_REAL_CONDITIONS": "PASS" if all(r["pass"] for r in process_rows) else "FAIL",
              "L2_CONTROLLED_STATIC": "PASS" if all(r["correct"] for r in rows) else "FAIL",
              "L3_ROS2_ONLINE": "BLOCKED", "RUNTIME_MONITOR": "NOT_READY",
              "eight_code_coverage": {"ALLOW_IN_POLICY": "CONTROLLED_STATIC",
                  "TASK_MISMATCH": "CONTROLLED_STATIC", "INVALID_TARGET": "CONTROLLED_STATIC",
                  "OUT_OF_REGION": "CONTROLLED_STATIC", "POLICY_MISSING": "CONTROLLED_STATIC",
                  "DUPLICATE_REQUEST": "UNIT_TEST_HISTORY_ONLY", "RATE_LIMIT": "UNIT_TEST_HISTORY_ONLY",
                  "EXECUTION_TIMEOUT": "NOT_READY_GATEWAY_EXECUTION_ONLY"},
              "disagreements_to_investigate_online": [
                  "static module allows, Gateway blocks duplicate/rate due to its live tracker",
                  "local policy snapshot differs from Gateway policy during policy reload",
                  "advisory history unavailable closes upstream while Gateway static rules could allow",
                  "Gateway allows admission, execution later times out: different layers"],
              "cases": rows}
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("case_count", "correct_cases", "L1_REAL_CONDITIONS",
                                            "L2_CONTROLLED_STATIC", "L3_ROS2_ONLINE", "RUNTIME_MONITOR")},
                     ensure_ascii=False, indent=2))
    return 0 if report["L1_REAL_CONDITIONS"] == report["L2_CONTROLLED_STATIC"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
