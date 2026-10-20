#!/usr/bin/env python3
"""Run offline F0 adapter checks with the real Member 2 module and pinned DDS evidence.

Requires the complete RosSystem checkout plus copied Member 2 overlay.
Does not send ROS 2 action goals or modify security policies.
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    try:
        import yaml
    except ImportError as exc:
        raise SystemExit('requires PyYAML: pip install -r requirements.txt') from exc
    p = argparse.ArgumentParser()
    p.add_argument('--experiment-run', required=True)
    p.add_argument('--evidence-root', default='tests/evidence')
    p.add_argument('--keystore', default='security/keystore')
    p.add_argument('--policy', default='security/policies/minimal_permissions.xml')
    args = p.parse_args()
    if not (ROOT / 'scripts/team_demo.py').is_file():
        raise SystemExit('请先把本交付包文件覆盖复制到完整 RosSystem baseline 工作区')
    config = yaml.safe_load((ROOT / 'config/team_modules.example.yaml').read_text(encoding='utf-8'))
    m = config['modules']['identity_trust']
    m.update(mode='external', command=[sys.executable, 'identity_trust/assessor.py',
             '--experiment-run', args.experiment_run, '--policy', str((ROOT / args.policy).resolve()),
             '--keystore', str((ROOT / args.keystore).resolve()),
             '--evidence-root', str((ROOT / args.evidence_root).resolve())], allow_fault_injection=False)
    with tempfile.TemporaryDirectory(prefix='rg_member2_') as temp:
        folder = Path(temp)
        cfg = folder / 'modules.yaml'
        inp = folder / 'input.json'
        cfg.write_text(yaml.safe_dump(config, allow_unicode=True), encoding='utf-8')
        expected = {'S2': 'READY_FOR_GATEWAY_SUBMISSION', 'S3': 'ADAPTER_BLOCK', 'S4': 'ADAPTER_BLOCK'}
        for case, outcome in expected.items():
            m['command'] += ['--case', case]
            cfg.write_text(yaml.safe_dump(config, allow_unicode=True), encoding='utf-8')
            now = '2026-10-14T08:00:00Z'
            inp.write_text(json.dumps({
                'schema_version': '1.0.0-proposed', 'run_id': 'member2-adapter-check',
                'request_id': 'member2-' + case, 'created_at': now,
                'candidate_action': {'action_resource': '/rg/guarded_navigate',
                    'operation': 'NAVIGATE', 'task_id': 'patrol_a_001',
                    'target': {'frame_id': 'map', 'x': 1.5, 'y': 1.5}},
                'observations': [{'source': 'offline_member2_replay', 'kind': 'MOCK',
                                  'observed_at': now,
                                  'detail': {'f0_mock': {'comm_risk': {'scenario': 'normal'},
                                                        'task_risk': {'scenario': 'allow'}}}}],
                'evidence_refs': [{'ref': 'scripts/member2_adapter_check.py', 'kind': 'MOCK'}],
            }, ensure_ascii=False), encoding='utf-8')
            proc = subprocess.run([sys.executable, str(ROOT / 'scripts/team_demo.py'),
                                   '--input', str(inp), '--config', str(cfg),
                                   '--workdir', str(ROOT), '--log', str(folder / 'adapter.jsonl')],
                                  capture_output=True, text=True, cwd=ROOT, timeout=90)
            try:
                out = json.loads(proc.stdout)
            except ValueError:
                print(f'{case}: FAIL stdout={proc.stdout[-600:]} stderr={proc.stderr[-600:]}')
                return 1
            is_ok = out.get('decision') == outcome and (proc.returncode == 0 if case == 'S2' else proc.returncode == 10)
            # The adapter's offline READY proves ONLY that this replay configuration
            # passed the pre-gateway checks, not that a live DDS request is authorized.
            print(f"{case}: {'PASS' if is_ok else 'FAIL'} expected={outcome} actual={out.get('decision')} reason={out.get('reason_code')}")
            if not is_ok:
                print(json.dumps(out, ensure_ascii=False, indent=2)[:2000])
                return 1
            m['command'] = m['command'][:-2]
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
