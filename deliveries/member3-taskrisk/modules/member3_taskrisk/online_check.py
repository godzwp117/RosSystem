#!/usr/bin/env python3
"""L3 harness, only usable inside a built/sourced ROS 2 workspace.

Reuses baseline instance-owned process cleanup. Shadow controls send a DISTINCT
request through the existing Planner -> guarded Gateway, never to the executor.
An adapter-blocked request has no Gateway event: absence is not a Gateway BLOCK.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import module as m3  # noqa: E402
from experiments import envelope  # noqa: E402
sys.path.insert(0, str(m3.REPO / "tests/integration"))
import team_handoff_check as handoff  # noqa: E402
import team_demo  # noqa: E402


def records_for(path, request_id):
    """Strict parsing: no silent ignore of malformed authoritative evidence."""
    if not Path(path).is_file():
        raise RuntimeError("missing required journal: " + str(path))
    rows = [m3.vtc.load_json_strict_text(line, str(path))
            for line in Path(path).read_text(encoding="utf-8").splitlines()]
    return [r for r in rows if r.get("request_id") == request_id]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=m3.REPO / "tests/evidence/member3")
    parser.add_argument("--domain", type=int, required=True,
                        help="a domain reserved for your isolated member 3 test instance")
    args = parser.parse_args(argv)
    if not 0 <= args.domain <= 232:
        parser.error("domain must be between 0 and 232")
    if not shutil.which("ros2"):
        print(json.dumps({"L3_ROS2_ONLINE": "BLOCKED", "reason": "ros2 unavailable; no evidence fabricated"}))
        return 3
    if os.environ.get("ROS_SECURITY_ENABLE", "").lower() != "true" or os.environ.get(
            "ROS_SECURITY_STRATEGY") != "Enforce":
        print(json.dumps({"L3_ROS2_ONLINE": "BLOCKED",
                          "reason": "run in the team's existing DDS-Security Enforce environment"}))
        return 3  # never disable security to make an online check pass
    try:
        import rclpy  # noqa: F401
        from rg_interfaces.action import PatrolNavigate  # noqa: F401
    except ImportError:
        print(json.dumps({"L3_ROS2_ONLINE": "BLOCKED", "reason": "built ROS packages not sourced"}))
        return 3
    run_id = "m3-" + uuid.uuid4().hex[:12]
    base = args.out_dir.resolve() / run_id
    base.mkdir(parents=True, exist_ok=False)
    original = yaml.safe_load((m3.REPO / "config/task_policy.yaml").read_text())
    scenarios = [("normal", envelope(run_id+"-normal"), {}, "ALLOW_IN_POLICY"),
                 ("region", envelope(run_id+"-region", 5, 5), {}, "OUT_OF_REGION"),
                 ("task", envelope(run_id+"-task", task="other"), {}, "TASK_MISMATCH"),
                 ("frame", envelope(run_id+"-frame", frame="odom"), {}, "INVALID_TARGET"),
                 ("inactive", envelope(run_id+"-inactive"), {"active": False}, "POLICY_MISSING"),
                 ("duplicate", envelope(run_id+"-duplicate"), {}, "DUPLICATE_REQUEST"),
                 ("rate", envelope(run_id+"-rate"), {"max_requests_per_minute": 1}, "RATE_LIMIT")]
    results = []
    for label, env, changes, expected in scenarios:
        instance = handoff.Instance(str(base), run_id, str(args.domain), label)
        policy_path = Path(instance.dir) / "policy.yaml"
        data = dict(original, **changes)
        policy_path.write_text(yaml.safe_dump(data), encoding="utf-8")
        # Instance.start reads this test-harness constant; only this process changes
        # it. The repository and actual shared config/task_policy.yaml stay intact.
        handoff.POLICY = str(policy_path)
        case = {"scenario": label, "expected_gateway_reason": expected, "status": "FAIL"}
        try:
            started, detail = instance.start()
            if not started:
                raise RuntimeError(detail)
            ready, detail = instance.wait_ready(timeout=40)
            if not ready:
                raise RuntimeError(detail)
            answer = m3.decide(env, m3.Settings(policy_path))
            case["module_output"] = answer
            config = yaml.safe_load((m3.REPO / "config/team_modules.member3.yaml").read_text())
            for entry in config["modules"].values():
                entry["command"][0] = sys.executable
            config["modules"]["task_risk"]["command"] = [
                sys.executable, str(HERE / "module.py"), "--policy", str(policy_path)]
            cfg = Path(instance.dir) / "adapter.yaml"
            cfg.write_text(yaml.safe_dump(config), encoding="utf-8")
            inherited = os.environ.get("ROS_DOMAIN_ID")
            os.environ["ROS_DOMAIN_ID"] = str(args.domain)
            try:
                if label in {"duplicate", "rate"}:
                    seed = copy.deepcopy(env)
                    if label == "rate":
                        seed["request_id"] += "-seed"
                    seed_result = team_demo.run(json.dumps(seed), str(cfg), str(Path(instance.dir)/"adapter.jsonl"),
                                                str(m3.REPO), online={"enabled": True,
                                                   "planner_command": config["adapter"]["planner_command"],
                                                   "planner_timeout_sec": 30})
                    seed_decisions = [r for r in records_for(instance.audit_path, seed["request_id"])
                                      if r.get("event_type") == "DecisionEvent"]
                    if len(seed_decisions) != 1 or seed_decisions[0]["decision"] != "ALLOW":
                        raise RuntimeError("temporal seed did not reach real Gateway ALLOW")
                    if len(records_for(instance.navsim_path, seed["request_id"])) != 1:
                        raise RuntimeError("temporal seed has no NavigationSim Goal")
                    case["seed_adapter"] = seed_result
                before = len(records_for(instance.navsim_path, env["request_id"]))
                adapter = team_demo.run(json.dumps(env), str(cfg), str(Path(instance.dir)/"adapter.jsonl"),
                                        str(m3.REPO), online={"enabled": True,
                                          "planner_command": config["adapter"]["planner_command"],
                                          "planner_timeout_sec": 30})
                case["adapter"] = adapter
                after = len(records_for(instance.navsim_path, env["request_id"]))
                if answer["status"] != "ALLOW_RECOMMENDED":
                    if adapter["decision"] != "ADAPTER_BLOCK" or after != before:
                        raise RuntimeError("upstream block did not prevent submission")
                    if records_for(instance.audit_path, env["request_id"]):
                        raise RuntimeError("adapter-blocked request unexpectedly reached Gateway")
                    # Separate diagnostic control, always via guarded Gateway.
                    control = copy.deepcopy(env)
                    control["request_id"] += "-shadow"
                    proc = subprocess.run(team_demo.build_planner_argv(
                        config["adapter"]["planner_command"], control), cwd=m3.REPO,
                        env=dict(os.environ), capture_output=True, text=True, timeout=30, shell=False)
                    case["shadow_planner_exit_code"] = proc.returncode
                    checked_id = control["request_id"]
                    case["denial_layer"] = "UPSTREAM_ADAPTER; distinct shadow control through Gateway"
                    goal_delta = len(records_for(instance.navsim_path, checked_id))
                else:
                    checked_id = env["request_id"]
                    goal_delta = after-before
                    case["denial_layer"] = "GATEWAY" if expected != "ALLOW_IN_POLICY" else "NONE"
                decisions = [r for r in records_for(instance.audit_path, checked_id)
                             if r.get("event_type") == "DecisionEvent"]
                decision = decisions[-1] if decisions else None
                expected_delta = 1 if expected == "ALLOW_IN_POLICY" else 0
                if not decision or decision["reason_code"] != expected or goal_delta != expected_delta:
                    raise RuntimeError("Gateway decision / NavigationSim delta mismatch")
                case.update(status="PASS", gateway_decision=decision, downstream_goal_delta=goal_delta,
                            same_verdict=(answer["status"] == "ALLOW_RECOMMENDED") == (
                                decision["decision"] == "ALLOW"),
                            evidence_ref={"gateway": instance.audit_path, "navsim": instance.navsim_path})
            finally:
                if inherited is None:
                    os.environ.pop("ROS_DOMAIN_ID", None)
                else:
                    os.environ["ROS_DOMAIN_ID"] = inherited
        except Exception as exc:
            case["error"] = str(exc)
        finally:
            case["cleanup"] = instance.stop()
            if instance.group_members_alive():
                case["status"] = "FAIL"
                case["cleanup_error"] = "instance process group still alive"
        results.append(case)
    passed = all(r["status"] == "PASS" for r in results)
    report = {"L3_ROS2_ONLINE": "PASS" if passed else "FAIL", "run_id": run_id,
              "RUNTIME_MONITOR": "NOT_READY", "comm_identity_modules": "MOCK",
              "note": "only Member 3 task-rule integration; not end-to-end intrusion detection",
              "cases": results}
    (base / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"L3_ROS2_ONLINE": report["L3_ROS2_ONLINE"], "report": str(base/"report.json")},
                     ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
