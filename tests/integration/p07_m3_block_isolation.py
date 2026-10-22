#!/usr/bin/env python3
"""P07 isolation: a real M3 BLOCK_RECOMMENDED must block at F0.

This is deliberately NOT the three-real positive chain. M1/M2 are MOCK so that
the only non-proceed status is produced by the real M3 External process. The
config declares CONTROLLED_TEST_ONLY identity; the result cannot be used as a
three-real identity or admission claim.

Evidence produced:
  envelope.json, task_risk.stdout.json/stderr, f0_result.json, adapter.jsonl,
  summary.json with checks, commands, exit codes and explicit limitations.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

import run_three_real_online as rt  # noqa: E402

CONFIG = ROOT / 'config' / 'team_modules.p07-isolation.yaml'
OUT_ROOT = ROOT / 'artifacts' / 'research' / 'v110' / 'p07'
M3_CMD = [sys.executable, str(ROOT / 'modules' / 'member3_taskrisk' / 'module.py'),
          '--policy', str(ROOT / 'config' / 'scenarios' / 'task_policy_tight_region.yaml')]


def invoke(argv, stdin_text):
    t0 = time.perf_counter()
    proc = subprocess.run(argv, cwd=str(ROOT), input=stdin_text, text=True,
                          capture_output=True, timeout=120)
    return {'argv': argv, 'exit_code': proc.returncode, 'stdout': proc.stdout,
            'stderr': proc.stderr, 'duration_ms': round((time.perf_counter() - t0) * 1000, 3)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args(argv)
    out = OUT_ROOT / args.run_id
    out.mkdir(parents=True, exist_ok=True)
    envelope = rt.build_envelope(args.run_id, 'p07-' + args.run_id, 2.0, 2.0,
                                 'patrol_a_001')
    envelope['observations'][0]['detail']['f0_mock'] = {
        'comm_risk': {'scenario': 'normal'},
        'identity_trust': {'scenario': 'authorized'},
        'task_risk': {'scenario': 'allow'},
    }
    envelope_text = json.dumps(envelope, ensure_ascii=False)
    (out / 'envelope.json').write_text(json.dumps(envelope, ensure_ascii=False, indent=2) + '\n',
                                       encoding='utf-8')
    checks = []

    def check(name, ok, detail=''):
        checks.append({'check': name, 'result': 'PASS' if ok else 'FAIL',
                       'detail': str(detail)[:900]})

    m3 = invoke(M3_CMD, envelope_text)
    (out / 'task_risk.stdout.txt').write_text(m3['stdout'], encoding='utf-8')
    (out / 'task_risk.stderr.txt').write_text(m3['stderr'], encoding='utf-8')
    (out / 'task_risk.command.json').write_text(json.dumps({'argv': m3['argv'],
                                                           'exit_code': m3['exit_code'],
                                                           'duration_ms': m3['duration_ms']},
                                                          indent=2) + '\n', encoding='utf-8')
    try:
        m3_doc = json.loads(m3['stdout'])
    except ValueError:
        m3_doc = {}
    check('real M3 process exits 0', m3['exit_code'] == 0, m3['exit_code'])
    check("real M3 outputs BLOCK_RECOMMENDED", m3_doc.get('status') == 'BLOCK_RECOMMENDED',
          m3_doc.get('status'))
    violations = ((m3_doc.get('extensions') or {}).get('member3') or {}).get('violations') or []
    codes = {v.get('reason_code') for v in violations if isinstance(v, dict)}
    check("real M3 reason is OUT_OF_REGION (tight policy, target 2.0/2.0)",
          'OUT_OF_REGION' in codes or str(m3_doc.get('reason', '')).startswith('OUT_OF_REGION'),
          {'violations': violations, 'reason': m3_doc.get('reason')})
    check('real M3 producer source is EXTERNAL',
          (m3_doc.get('producer') or {}).get('source') == 'EXTERNAL',
          (m3_doc.get('producer') or {}).get('source'))

    f0 = invoke([sys.executable, str(ROOT / 'scripts' / 'team_demo.py'),
                 '--input', str(out / 'envelope.json'),
                 '--config', str(CONFIG),
                 '--log', str(out / 'adapter.jsonl'),
                 '--workdir', str(ROOT), '--online'],
                envelope_text)
    (out / 'f0.stdout.txt').write_text(f0['stdout'], encoding='utf-8')
    (out / 'f0.stderr.txt').write_text(f0['stderr'], encoding='utf-8')
    (out / 'f0.command.json').write_text(json.dumps({'argv': f0['argv'],
                                                    'exit_code': f0['exit_code'],
                                                    'duration_ms': f0['duration_ms']},
                                                   indent=2) + '\n', encoding='utf-8')
    try:
        f0_doc = json.loads(f0['stdout'])
    except ValueError:
        f0_doc = {}
    (out / 'f0_result.json').write_text(json.dumps(f0_doc, ensure_ascii=False, indent=2) + '\n',
                                        encoding='utf-8')
    check('F0 exits with its documented block code (10)', f0['exit_code'] == 10, f0['exit_code'])
    check('F0 decision is ADAPTER_BLOCK', f0_doc.get('decision') == 'ADAPTER_BLOCK',
          f0_doc.get('decision'))
    check('F0 reason is ADAPTER_MODULE_STATUS_NOT_PROCEED',
          f0_doc.get('reason_code') == 'ADAPTER_MODULE_STATUS_NOT_PROCEED',
          f0_doc.get('reason_code'))
    detail = str(f0_doc.get('detail') or '')
    check('F0 detail names task_risk and BLOCK_RECOMMENDED',
          'task_risk' in detail and 'BLOCK_RECOMMENDED' in detail, detail)
    modules = {m.get('module'): m for m in (f0_doc.get('modules') or [])}
    check('F0 observed the real M3 as external + BLOCK_RECOMMENDED',
          (modules.get('task_risk') or {}).get('mode') == 'external'
          and (modules.get('task_risk') or {}).get('status') == 'BLOCK_RECOMMENDED',
          modules.get('task_risk'))
    check('M1/M2 are MOCK and only used for isolation',
          (modules.get('comm_risk') or {}).get('mode') == 'mock'
          and (modules.get('identity_trust') or {}).get('mode') == 'mock',
          {k: (modules.get(k) or {}).get('mode') for k in ('comm_risk', 'identity_trust')})
    online = f0_doc.get('online') or {}
    check('Planner was NOT submitted after the block',
          online.get('enabled') is True and online.get('submitted') is False
          and online.get('outcome') == 'NOT_SUBMITTED_ADAPTER_BLOCK', online)
    check('No Gateway audit exists because no request was submitted',
          not (out / 'gateway_audit.jsonl').exists(),
          'gateway not started; F0 blocked before Planner')
    check('No downstream Goal can exist (no submission path)',
          not (out / 'navsim_goals.jsonl').exists(),
          'NavigationSim not started; no Goal was generated')

    summary = {
        'contract': 'p07-isolation/1',
        'run_id': args.run_id,
        'scope': 'CONTROLLED_ISOLATION',
        'not_three_real': True,
        'config': str(CONFIG.relative_to(ROOT)),
        'm3_policy': 'config/scenarios/task_policy_tight_region.yaml',
        'm3_command': m3['argv'],
        'f0_command': f0['argv'],
        'm3_result': {'status': m3_doc.get('status'),
                      'reason_code': m3_doc.get('reason_code'),
                      'producer': m3_doc.get('producer'),
                      'exit_code': m3['exit_code']},
        'f0_result': {'decision': f0_doc.get('decision'),
                      'reason_code': f0_doc.get('reason_code'),
                      'detail': f0_doc.get('detail'),
                      'online': online,
                      'modules': [{'module': m.get('module'), 'mode': m.get('mode'),
                                   'status': m.get('status')} for m in
                                  (f0_doc.get('modules') or [])]},
        'gateway_received': 0,
        'downstream_goal_count': 0,
        'gateway_method': 'Gateway not started; no Planner submission after F0 block',
        'goal_method': 'NavigationSim not started; no submission path',
        'checks': checks,
        'limitations': [
            'M1/M2 are MOCK; this isolates M3 and is not a three-real result.',
            'The real M3 uses an isolated read-only tight-region policy; the authoritative TaskPolicy is untouched.',
            'Gateway and NavigationSim were not started; "0 received / 0 goal" is a consequence of no submission, not a running-stack observation.',
        ],
    }
    summary['total'] = len(checks)
    summary['passed'] = sum(1 for c in checks if c['result'] == 'PASS')
    summary['failed'] = summary['total'] - summary['passed']
    (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n',
                                      encoding='utf-8')
    print(json.dumps({'run_id': args.run_id, 'passed': summary['passed'],
                      'total': summary['total'], 'failed': summary['failed']}))
    for item in checks:
        if item['result'] == 'FAIL':
            print('  FAIL: {0} -- {1}'.format(item['check'], item['detail']))
    return 0 if summary['failed'] == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
