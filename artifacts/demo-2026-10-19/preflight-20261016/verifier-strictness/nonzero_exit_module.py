import json, sys
env = json.load(sys.stdin)
json.dump({
 "schema_version":"1.0.0-proposed","run_id":env["run_id"],"request_id":env["request_id"],
 "event_id":"m3-{0}-nz".format(env["request_id"]),
 "producer":{"name":"nz","source":"EXTERNAL","module_version":"0"},
 "observed_at":"2026-10-16T00:00:00Z","status":"UNKNOWN",
 "task_id":env["candidate_action"]["task_id"],
 "candidate_action":{"action_resource":"/rg/guarded_navigate","operation":"NAVIGATE"},
 "target":env["candidate_action"]["target"],"risk_level":"UNKNOWN",
 "reason":"POLICY_MISSING: 本地策略不可用","rule_basis":["fail closed"],
 "evidence_refs":[{"ref":"fake","kind":"UNKNOWN"}],
 "policy_ref":{"policy_version":"1.0"},
 "extensions":{"member3":{"reason_code":"POLICY_MISSING"}},
}, sys.stdout)
sys.exit(1)     # <-- valid JSON, correct status, yet the process FAILED
