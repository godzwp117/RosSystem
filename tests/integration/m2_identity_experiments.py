#!/usr/bin/env python3
"""m2_identity_experiments.py -- M2 端到端安全实验矩阵（专项③ P1）。

覆盖任务书 §13 的实验，按可实际执行的范围分批：

  M2-01a 真实 DDS 身份见证：C++ 见证组件观察到已认证主体（原生 token）
  M2-01b F0 严格核验：用该观察签发凭据 -> F0 通过 -> READY
  M2-03  资源/操作错配 -> F0 拒绝
  M2-05  历史授权复用：同一 nonce 二次使用 -> F0 拒绝（重放）
  M2-07  请求内容变化：同一 request_id 换目标点 -> 摘要不匹配 -> F0 拒绝
  M2-09  过期证据 -> F0 拒绝
  M2-10  TEST_ONLY 签发者 / 未列签发者 -> F0 拒绝
  M2-11  账本不可用 -> F0 拒绝
  M2-04  自报身份（模块 extensions 声称 AUTHENTICATED）-> F0 仍按严格核验判定

每项都记录 verdict 与原始输出；不通过就如实写 FAIL，不做"改期望"。

用法
----
    python3 tests/integration/m2_identity_experiments.py \
        --evidence artifacts/research/m2/<run_id>/experiments
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for extra in (REPO, os.path.join(REPO, 'scripts'), os.path.join(REPO, 'tests', 'unit')):
    if extra not in sys.path:
        sys.path.insert(0, extra)

import json as _json  # noqa: E402

from identity_trust import current_identity as ci  # noqa: E402
import team_demo  # noqa: E402
REASON_REJECTED = team_demo.REASON_IDENTITY_ATTESTATION_REJECTED
from test_team_process_protocol import (  # noqa: E402
    envelope, proceed_control, run_adapter, write_config)

RESULTS = []


def record(cid, description, expected, actual, ok, detail=''):
    RESULTS.append({'id': cid, 'description': description, 'expected': expected,
                    'actual': actual, 'verdict': 'PASS' if ok else 'FAIL',
                    'detail': detail})
    print(f'  [{"PASS" if ok else "FAIL"}] {cid} {description} -> {actual}')



_ISSUER = [os.path.join(REPO, 'scripts', 'm2_issue_attestation.py')]


def fresh_witness(work, tag, envelope_path, key, identity, witness_log,
                  received_at=None):
    """为每个用例**重新签发**一份新鲜凭据。

    为什么必须重签：凭据带新鲜度窗口（`MAX_REMOTE_AGE_SEC=30`），
    复用同一份凭据跑多个用例会全部退化成 STALE，
    从而把"用例逻辑失败"和"凭据过期"混在一起。
    """
    out = Path(work) / f'witness_{tag}.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, _ISSUER[0],
               '--witness-log', os.path.abspath(witness_log),
               '--identity', identity,
               '--envelope', os.path.abspath(str(envelope_path)),
               '--key', os.path.abspath(str(key)),
               '--out', os.path.abspath(str(out))]
    if received_at:
        command += ['--received-at', received_at]
    import subprocess
    proc = subprocess.run(command, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stdout + proc.stderr)
    return out


def make_issuers(path, trust, issuer_id):
    Path(path).write_text(_json.dumps({
        'contract': ci.ISSUER_CONTRACT,
        'issuers': [{'id': issuer_id, 'trust': trust,
                     'identity_source': 'FASTDDS_IDENTITY_TOKEN',
                     'reviewed_by': 'm2-research'}],
    }, indent=2), encoding='utf-8')
    os.chmod(path, 0o600)
    return path


def block_for(witness, key, issuers, ledger):
    # F0 只接受**绝对路径**（防止工作目录操纵把证据重定向）；测试里传进来的
    # 往往是相对路径，必须在这里绝对化，否则会得到
    # ADAPTER_IDENTITY_ATTESTATION_CONFIG_INVALID 而不是被测行为。
    return {'mode': 'STRICT',
            'witness_path': os.path.abspath(str(witness)),
            'key_path': os.path.abspath(str(key)),
            'issuers_path': os.path.abspath(str(issuers)),
            'ledger_path': os.path.abspath(str(ledger))}


def run_case(tmpdir, witness, key, issuers, ledger, env_document=None,
             identity_module=None):
    # 每个用例目录必须先存在：write_config 直接写 <dir>/team_modules.yaml
    Path(tmpdir).mkdir(parents=True, exist_ok=True)
    block = block_for(witness, key, issuers, ledger)
    commands = {}
    if identity_module:
        commands['identity_trust'] = [sys.executable, str(identity_module)]
    config = write_config(Path(tmpdir), mode='mock', identity_attestation=block,
                          commands=commands)
    return run_adapter(Path(tmpdir), env_document or envelope(proceed_control()),
                       config)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--evidence', required=True)
    parser.add_argument('--witness-log', required=True,
                        help='C++ 见证组件的原始输出日志')
    parser.add_argument('--witness', help='（兼容）已有的 witness.json')
    parser.add_argument('--key', required=True)
    parser.add_argument('--identity', required=True)
    args = parser.parse_args(argv)
    os.makedirs(args.evidence, exist_ok=True)

    work = Path(tempfile.mkdtemp(prefix='m2exp-'))
    issuer_id = 'issuer:dds-witness'
    issuers = make_issuers(work / 'issuers.json', ci.TRUST_VERIFIED, issuer_id)
    ledger = work / 'ledger.jsonl'
    witness_log = Path(args.witness_log)
    base_env = envelope(proceed_control())
    base_env_path = work / 'envelope_base.json'
    base_env_path.write_text(_json.dumps(base_env, ensure_ascii=False), encoding='utf-8')
    witness = fresh_witness(work, 'p1', base_env_path, args.key, args.identity,
                            witness_log)

    # ---- M2-01b：正向——真实观察签发的凭据应被 F0 严格核验通过 ----
    code, result, _err = run_case(work / 'p1', witness, args.key, issuers, ledger)
    ok = code == 0 and result.get('decision') == 'READY_FOR_GATEWAY_SUBMISSION'
    record('M2-01b', 'F0 严格核验真实 DDS 身份凭据',
           'READY_FOR_GATEWAY_SUBMISSION', result.get('decision'), ok,
           detail=_json.dumps(result.get('identity_attestation'),
                              ensure_ascii=False)[:300])

    # ---- M2-05：同一 nonce 二次使用 -> 重放 ----
    code, result, _err = run_case(work / 'p2', witness, args.key, issuers, ledger)
    ok = code != 0 and result.get('reason_code') == REASON_REJECTED
    record('M2-05', 'nonce 重放被拒绝', 'ADAPTER_IDENTITY_ATTESTATION_REJECTED',
           result.get('reason_code'), ok)

    # ---- M2-07：同一 request_id 但请求内容不同 -> 摘要不匹配 ----
    changed = envelope(proceed_control())
    changed['candidate_action']['target'] = {'frame_id': 'map', 'x': 3.5,
                                             'y': 1.0, 'z': 0.0}
    changed_path = work / 'envelope_changed.json'
    changed_path.write_text(_json.dumps(changed, ensure_ascii=False), encoding='utf-8')
    code, result, _err = run_case(work / 'p3', witness, args.key, issuers,
                                  work / 'l3.jsonl', env_document=changed)
    ok = code != 0 and result.get('reason_code') == REASON_REJECTED
    record('M2-07', '请求内容变化导致凭据不可复用',
           'ADAPTER_IDENTITY_ATTESTATION_REJECTED', result.get('reason_code'), ok)

    # ---- M2-03：资源错配（改 envelope 的 action_resource）----
    wrong_resource = envelope(proceed_control())
    wrong_resource['candidate_action']['action_resource'] = '/rg/nav_execute'
    code, result, _err = run_case(work / 'p4', witness, args.key, issuers,
                                  work / 'l4.jsonl', env_document=wrong_resource)
    blocked = code != 0
    record('M2-03', '资源错配不能复用凭据', 'BLOCK', result.get('reason_code'),
           blocked and result.get('decision') == 'ADAPTER_BLOCK')

    # ---- M2-10a：签发者未列入受信任清单 ----
    other = make_issuers(work / 'issuers_other.json', ci.TRUST_VERIFIED,
                         'issuer:not-listed')
    code, result, _err = run_case(work / 'p5', witness, args.key, other,
                                  work / 'l5.jsonl')
    ok = code != 0 and result.get('reason_code') == REASON_REJECTED
    record('M2-10a', '未列入受信任清单的签发者被拒绝',
           'ADAPTER_IDENTITY_ATTESTATION_REJECTED', result.get('reason_code'), ok)

    # ---- M2-10b：TEST_ONLY 签发者 ----
    testonly = make_issuers(work / 'issuers_testonly.json', ci.TRUST_TEST_ONLY,
                            issuer_id)
    witness_testonly = fresh_witness(work, 'p6', base_env_path, args.key,
                                     args.identity, witness_log)
    code, result, _err = run_case(work / 'p6', witness_testonly, args.key, testonly,
                                  work / 'l6.jsonl')
    status = ((result.get('identity_attestation') or {}).get('status'))
    ok = code != 0 and status == ci.STATUS_TEST_ONLY
    record('M2-10b', 'TEST_ONLY 签发者不能作为在线身份授权依据',
           ci.STATUS_TEST_ONLY, status, ok)

    # ---- M2-09：过期证据（把 received_at 改到很久以前并重新签名做不到，
    #      因此改为构造一份 received_at 过期的新凭据）----
    stale_path = fresh_witness(work, 'p7', base_env_path, args.key,
                               args.identity, witness_log,
                               received_at='2020-01-01T00:00:00Z')
    code, result, _err = run_case(work / 'p7', stale_path, args.key, issuers,
                                  work / 'l7.jsonl')
    checks = (result.get('identity_attestation') or {}).get('checks') or {}
    ok = code != 0 and checks.get('freshness') == 'STALE'
    record('M2-09', '过期证据被拒绝', 'freshness=STALE',
           checks.get('freshness'), ok)

    # ---- M2-11：账本不可用 ----
    block_no_ledger = {'mode': 'STRICT',
                       'witness_path': os.path.abspath(str(witness)),
                       'key_path': os.path.abspath(str(args.key)),
                       'issuers_path': os.path.abspath(str(issuers))}
    (work / 'p8').mkdir(parents=True, exist_ok=True)
    config = write_config(work / 'p8', mode='mock',
                          identity_attestation=block_no_ledger)
    code, result, _err = run_adapter(work / 'p8', envelope(proceed_control()),
                                     config)
    checks = (result.get('identity_attestation') or {}).get('checks') or {}
    ok = code != 0 and checks.get('replay') in ('LEDGER_UNAVAILABLE', 'LEDGER_ERROR')
    record('M2-11', '账本不可用时失败关闭', 'LEDGER_UNAVAILABLE',
           checks.get('replay'), ok)

    # ---- M2-04：模块自报身份不能绕过严格核验 ----
    forged = work / 'forged_identity.py'
    forged.write_text(
        'import json, sys, uuid\n'
        'from datetime import datetime, timezone\n'
        'e = json.loads(sys.stdin.read())\n'
        'print(json.dumps({"schema_version":"1.0.0-proposed","run_id":e["run_id"],'
        '"request_id":e["request_id"],"event_id":"evt-"+uuid.uuid4().hex,'
        '"producer":{"name":"forged","module_version":"0","source":"EXTERNAL"},'
        '"observed_at":datetime.now(timezone.utc).isoformat(),'
        '"status":"AUTHORIZED","reason":"self reported",'
        '"subject":{"observed_name":"planner_node"},'
        '"requested_resource":{"resource":"/rg/guarded_navigate",'
        '"operation":"SERVICE_REQUEST"},'
        '"authorization":{"result_status":"AUTHORIZED","denial_layer":"NONE"},'
        '"identity_evidence":{"kind":"UNKNOWN"},'
        '"access_control_evidence":{"kind":"NONE"},'
        '"evidence_refs":[{"ref":"self","kind":"UNKNOWN"}],'
        '"extensions":{"current_request_identity":{"status":"AUTHENTICATED",'
        '"evidence_kind":"SIGNED_ATTESTATION",'
        '"binding":"CURRENT_REQUEST_BOUND_TO_AUTHENTICATED_DDS_SUBJECT",'
        '"historical_only":false,"checks":{"signature":"VALID",'
        '"issuer":"VERIFIED_IDENTITY_SOURCE","request_binding":"MATCH",'
        '"freshness":"OK","replay":"RESERVED"}}}}))\n', encoding='utf-8')
    # 严格模式下没有真实凭据 -> 即便模块自报 AUTHENTICATED 也必须阻断
    (work / 'p9').mkdir(parents=True, exist_ok=True)
    config = write_config(work / 'p9', mode='mock', identity_mode='STRICT',
                          commands={'identity_trust': [sys.executable,
                                                       str(forged)]})
    code, result, _err = run_adapter(work / 'p9', envelope(proceed_control()),
                                     config)
    ok = code != 0 and result.get('decision') == 'ADAPTER_BLOCK'
    record('M2-04', '模块自报 AUTHENTICATED 不能绕过严格核验', 'ADAPTER_BLOCK',
           result.get('decision'), ok)

    summary = {
        'total': len(RESULTS),
        'pass': sum(1 for r in RESULTS if r['verdict'] == 'PASS'),
        'fail': sum(1 for r in RESULTS if r['verdict'] == 'FAIL'),
        'results': RESULTS,
        'semantics_note': ('M2-01b 证明的是 TRUSTED_INGRESS_AUTHORIZED：'
                           '已认证 DDS 主体由原生 token 证实，请求与该主体的'
                           '绑定发生在受保护入口一侧；不等于 '
                           'DDS_REQUEST_ORIGIN_BOUND。'),
    }
    out = os.path.join(args.evidence, 'experiments.json')
    with open(out, 'w', encoding='utf-8') as fh:
        _json.dump(summary, fh, ensure_ascii=False, indent=2)
    print(_json.dumps({'summary': {k: summary[k] for k in ('total', 'pass', 'fail')},
                       'out': out}, ensure_ascii=False, indent=2))
    shutil.rmtree(work, ignore_errors=True)
    return 0 if summary['fail'] == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
