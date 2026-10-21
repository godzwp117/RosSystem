"""Member 2: offline fixtures validate logic; real DDS results require ROS 2 Jazzy."""
import json
import subprocess
import sys
from pathlib import Path
from xml.sax.saxutils import escape

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from identity_trust.assessor import (assessment, dds_denial_evidence,  # noqa: E402
                                     native_denial_records, normalize_ansi,
                                     permission_permits, policy_permits, strict_json)

#: 真实 Fast DDS 拒绝日志的行内形状（含 Permissions.cpp 原生源码位置）。
NATIVE_DENIAL_PLAIN = (
    '2026-10-09 09:31:57.547 [SECURITY Error] rr/rg/nav_execute/_action/send_goalReply '
    'topic not found in allow rule. (./src/cpp/security/accesscontrol/Permissions.cpp:1246) '
    '-> Function check_create_datareader')
#: 与归档证据一致的着色形状：控制序列插进 SECURITY Error 字样内部。
NATIVE_DENIAL_ANSI = (
    '\x1b[37;1m2026-10-09 09:31:57.547 \x1b[31;1m[\x1b[37;1mSECURITY\x1b[31;1m Error] '
    '\x1b[37mrr/rg/nav_execute/_action/send_goalReply topic not found in allow rule. '
    '(./src/cpp/security/accesscontrol/Permissions.cpp:1246)\x1b[34;1m -> Function '
    '\x1b[36mcheck_create_datareader\x1b[m')

sys.path.insert(0, str(ROOT / 'scripts'))
import validate_team_contracts as vtc  # noqa: E402


def rogue_result(node, action, outcome, **extra):
    payload = {'node_name': node, 'target_action': action, 'outcome': outcome}
    payload.update(extra)
    return 'ROGUE_RESULT ' + json.dumps(payload) + '\n'


@pytest.fixture
def sample(tmp_path):
    policy = tmp_path / 'policy.xml'
    policy.write_text('''<policy version="0.2.0"><enclaves>
    <enclave path="/planner"><profiles><profile ns="/" node="planner_node"><services request="ALLOW"><service>/rg/guarded_navigate/_action/send_goal</service></services></profile></profiles></enclave>
    <enclave path="/gateway"><profiles><profile ns="/" node="security_gateway"><services request="ALLOW"><service>/rg/nav_execute/_action/send_goal</service></services></profile></profiles></enclave>
    <enclave path="/unauthorized"><profiles><profile ns="/" node="rogue_client"/></profiles></enclave>
    </enclaves></policy>''', encoding='utf-8')
    ks = tmp_path / 'keystore'
    for enclave, allowed in [('planner', '/rg/guarded_navigate'), ('gateway', '/rg/nav_execute'), ('unauthorized', None)]:
        d = ks / 'enclaves' / enclave
        d.mkdir(parents=True)
        rule = ''
        if allowed:
            target = allowed[1:] + '/_action/send_goal'
            rule = f'<allow_rule><domains><id>43</id></domains><publish><topics><topic>rq/{target}Request</topic></topics></publish><subscribe><topics><topic>rr/{target}Reply</topic></topics></subscribe></allow_rule>'
        (d / 'permissions.xml').write_text(f'<permissions><grant name="{enclave}"><subject_name>CN={enclave}</subject_name>{rule or "<allow_rule><domains><id>43</id></domains></allow_rule>"}<default>DENY</default></grant></permissions>', encoding='utf-8')
    evidence = tmp_path / 'evidence'
    run_dir = evidence / 'member2run01'
    cases = []
    entries = [
        ('S2', '/planner', '/rg/guarded_navigate', 1, 'planner.log', 'PLANNER_RESULT {"success":true,"status_code":"EXECUTED"}\n'),
        ('S3C', '/gateway', '/rg/nav_execute', 1, 'rogue_gateway.log', 'ROGUE_RESULT {"node_name":"security_gateway","target_action":"/rg/nav_execute","outcome":"RESULT","status_code":"EXECUTED","success":true}\n'),
        ('S3', '/planner', '/rg/nav_execute', 0, 'rogue_planner.log',
         NATIVE_DENIAL_PLAIN + '\n' + rogue_result('planner_node', '/rg/nav_execute', 'ACTION_CLIENT_CREATION_DENIED')),
        ('S4', '/unauthorized', '/rg/nav_execute', 0, 'rogue_unauthorized.log',
         NATIVE_DENIAL_ANSI + '\n' + rogue_result('rogue_client', '/rg/nav_execute', 'ACTION_CLIENT_CREATION_DENIED')),
    ]
    for case_id, enclave, resource, count, name, log in entries:
        folder = run_dir / case_id
        folder.mkdir(parents=True)
        (folder / name).write_text(log, encoding='utf-8')
        cases.append({'scenario_id': case_id, 'result': 'PASS', 'status': 'PASS', 'security_mode': 'enforce', 'source_enclave': enclave, 'requested_resource': resource, 'downstream_goal_count': count, 'checks': [{'result': 'PASS'}]})
    (run_dir / 'summary.json').write_text(json.dumps({'suite': 'sros2', 'run_id': 'member2run01', 'secure_domain': '43', 'failed': 0, 'scenarios': cases}), encoding='utf-8')
    env = {'schema_version': '1.0.0-proposed', 'run_id': 'run-f0-test', 'request_id': 'req-m2-1', 'created_at': '2026-10-14T08:00:00Z',
           'candidate_action': {'action_resource': '/rg/guarded_navigate', 'operation': 'NAVIGATE', 'task_id': 'patrol_a_001', 'target': {'frame_id': 'map', 'x': 1.5, 'y': 1.5}},
           'observations': [{'source': 'security', 'kind': 'UNKNOWN', 'observed_at': '2026-10-14T08:00:00Z'}],
           'evidence_refs': [{'ref': 'tests', 'kind': 'UNKNOWN'}]}
    return {'policy': policy, 'keystore': ks, 'evidence_root': evidence, 'experiment_run': 'member2run01', 'case': 'S2'}, env, run_dir


def invoke(sample, case):
    from argparse import Namespace
    opts, env, _ = sample
    return assessment(env, Namespace(**(opts | {'case': case})))


def test_01_normal_authorized(sample):
    out = invoke(sample, 'S2')
    assert out['status'] == 'AUTHORIZED'
    assert out['authorization']['denial_layer'] == 'NONE'
    assert 'authenticated_identity' not in out['subject']


def test_02_positive_control(sample):
    out = invoke(sample, 'S3C')
    assert out['status'] == 'UNKNOWN' and out['identity_evidence']['kind'] == 'CONTROLLED_SECURITY_EXPERIMENT'
    assert out['extensions']['positive_control_verified'] is True  # 不可将 nav_execute 权限转给 guarded_navigate


@pytest.mark.parametrize('case', ['S3', 'S4'])
def test_03_native_denial_evidence_preserved(sample, case):
    """历史拒绝证据必须保留，但**不得**解释为当前 guarded 请求被 DDS 拒绝。

    历史场景 S3/S4 针对 `/rg/nav_execute`，当前候选资源是
    `/rg/guarded_navigate`：资源不同，因此当前请求只能得到 UNKNOWN。
    """
    out = invoke(sample, case)
    assert out['status'] == 'UNKNOWN'
    assert out['authorization']['denial_layer'] == 'UNKNOWN'
    assert out['requested_resource']['resource'] == '/rg/guarded_navigate'
    # 场景、拒绝资源、原生权限错误三类证据仍然完整保留并可追溯
    ext = out['extensions']
    assert ext['historical_experiment_status'] == 'DENIED'
    assert ext['historical_experiment_resource'] == '/rg/nav_execute'
    assert ext['current_candidate_resource'] == '/rg/guarded_navigate'
    assert ext['current_request_binding'] == 'HISTORICAL_RESOURCE_MISMATCH'
    assert ext['historical_denial_topic'] == 'rr/rg/nav_execute/_action/send_goalReply'
    assert ext['historical_denial_log_line'] == 1
    assert 'not found in allow rule' in out['authorization']['denial_detail']
    assert any('rogue_gateway.log' in x['ref'] for x in out['evidence_refs'])


def test_03b_matching_resource_denial_is_reported(sample):
    """证据层在资源一致时给出 DENIED；assessment 层再决定能否用于当前请求。"""
    from identity_trust.assessor import examine
    opts, env, _ = sample
    # 证据层：S3 的拒绝资源与场景期望资源一致 -> DENIED
    detail = examine(opts['policy'], opts['keystore'], opts['evidence_root'],
                     opts['experiment_run'], 'S3')
    assert detail['status'] == 'DENIED'
    assert detail['resource'] == '/rg/nav_execute'
    assert detail['denial_topic'] == 'rr/rg/nav_execute/_action/send_goalReply'
    # assessment 层：当前候选资源是 /rg/guarded_navigate，资源不匹配 -> 不得推进
    out = invoke(sample, 'S3')
    assert out['extensions']['current_request_binding'] == 'HISTORICAL_RESOURCE_MISMATCH'
    assert out['status'] == 'UNKNOWN'
    # S2 的授权资源与当前候选入口一致，才是允许推进的历史授权
    out2 = invoke(sample, 'S2')
    assert out2['extensions']['current_request_binding'] == 'HISTORICAL_RESOURCE_MATCHES_CURRENT'
    assert out2['status'] == 'AUTHORIZED'


def test_04_missing_generated_permissions_fails_closed(sample):
    opts, env, _ = sample
    (opts['keystore'] / 'enclaves/planner/permissions.xml').unlink()
    assert invoke(sample, 'S2')['status'] == 'UNKNOWN'


def test_05_invalid_xml_fails_closed(sample):
    opts, env, _ = sample
    opts['policy'].write_text('<policy><enclave', encoding='utf-8')
    assert invoke(sample, 'S2')['status'] == 'UNKNOWN'


def test_06_broad_fallback_rejected(sample):
    opts, env, _ = sample
    perm = opts['keystore'] / 'enclaves/planner/permissions.xml'
    perm.write_text(perm.read_text().replace('rq/rg/guarded_navigate/_action/send_goalRequest', 'rq/*Request'), encoding='utf-8')
    assert invoke(sample, 'S2')['status'] == 'UNKNOWN'


def test_07_no_native_log_not_denied(sample):
    opts, env, run = sample
    f = run / 'S3/rogue_planner.log'
    f.write_text('ROGUE_RESULT {"node_name":"planner_node","target_action":"/rg/nav_execute","outcome":"NO_ACTION_SERVER"}\n', encoding='utf-8')
    assert invoke(sample, 'S3')['status'] == 'UNKNOWN'


def test_08_broken_positive_control(sample):
    opts, env, run = sample
    f = run / 'S3C/rogue_gateway.log'
    f.write_text('ROGUE_RESULT {"node_name":"security_gateway","target_action":"/rg/nav_execute","outcome":"RESULT","success":false}\n', encoding='utf-8')
    assert invoke(sample, 'S3')['status'] == 'UNKNOWN'


def test_09_request_id_not_identity(sample):
    opts, env, _ = sample
    env['request_id'] = '/gateway'
    out = invoke(sample, 'S3')
    assert out['request_id'] == '/gateway'
    assert out['status'] == 'UNKNOWN'          # 自报 request_id 不能改变安全结论
    assert 'authenticated_identity' not in out['subject']


def test_10_unpinned_experiment_unknown(sample):
    opts, env, _ = sample
    opts['experiment_run'] = None
    assert invoke(sample, 'S2')['status'] == 'UNKNOWN'


def test_11_untrusted_observations_cannot_escalate(sample):
    opts, env, _ = sample
    env['observations'][0]['detail'] = {'role': 'gateway', 'authenticated': True, 'status': 'AUTHORIZED'}
    assert invoke(sample, 'S3')['status'] == 'UNKNOWN'   # 业务 JSON 自报不能升级结论


def test_12_schema_version_rejected(sample):
    from argparse import Namespace
    from identity_trust.assessor import assessment
    opts, env, _ = sample
    env['schema_version'] = '999'
    with pytest.raises(ValueError):
        assessment(env, Namespace(**opts))


def test_13_bad_run_id_fails_closed(sample):
    opts, env, _ = sample
    opts['experiment_run'] = '../elsewhere'
    assert invoke(sample, 'S2')['status'] == 'UNKNOWN'


def test_14_duplicate_json_key_rejected():
    with pytest.raises(ValueError):
        strict_json('{"run_id":"a","run_id":"b"}')


def test_15_permission_source_and_generated_comparison(sample):
    opts, env, _ = sample
    path = opts['keystore'] / 'enclaves/planner/permissions.xml'
    service = '/rg/guarded_navigate/_action/send_goal'
    assert policy_permits(opts['policy'], '/planner', service)[1]
    assert permission_permits(path, service)
    assert not permission_permits(path, '/rg/nav_execute/_action/send_goal')


def test_16_cli_one_json_and_stderr(sample):
    opts, env, _ = sample
    script = ROOT / 'identity_trust/assessor.py'
    proc = subprocess.run([sys.executable, str(script), '--policy', str(opts['policy']), '--keystore', str(opts['keystore']), '--evidence-root', str(opts['evidence_root']), '--experiment-run', opts['experiment_run'], '--case', 'S2'], input=json.dumps(env), capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert len(proc.stdout.strip().splitlines()) == 1
    assert json.loads(proc.stdout)['status'] == 'AUTHORIZED'


def test_17_domain_mismatch_fails_closed(sample):
    opts, env, _ = sample
    p = opts['keystore'] / 'enclaves/planner/permissions.xml'
    p.write_text(p.read_text().replace('<id>43</id>', '<id>42</id>'), encoding='utf-8')
    assert invoke(sample, 'S2')['status'] == 'UNKNOWN'


def test_18_only_local_experiment_evidence(sample):
    opts, env, _ = sample
    env['extensions'] = {'experiment_run': 'FAKE-PASS'}
    assert invoke(sample, 'S2')['status'] == 'AUTHORIZED'  # uses trusted CLI, not extensions


def test_19_client_timeout_cannot_count_as_denial(sample):
    opts, env, run = sample
    f = run / 'S3/rogue_planner.log'
    f.write_text('ROGUE_RESULT {"node_name":"planner_node","target_action":"/rg/nav_execute","outcome":"SEND_GOAL_TIMEOUT"}\n', encoding='utf-8')
    assert invoke(sample, 'S3')['status'] == 'UNKNOWN'


def test_20_conflicting_policy_and_runtime(sample):
    opts, env, run = sample
    policy = opts['policy']
    policy.write_text(policy.read_text().replace('/rg/guarded_navigate/_action/send_goal', '/rg/nav_execute/_action/send_goal'), encoding='utf-8')
    assert invoke(sample, 'S2')['status'] == 'UNKNOWN'


def test_21_default_allow_is_not_minimal(sample):
    opts, env, _ = sample
    p = opts['keystore'] / 'enclaves/planner/permissions.xml'
    p.write_text(p.read_text().replace('<default>DENY</default>', '<default>ALLOW</default>'), encoding='utf-8')
    assert invoke(sample, 'S2')['status'] == 'UNKNOWN'
