#!/usr/bin/env python3
"""M2 回归：**真实归档 DDS 拒绝日志**的 ANSI 规范化与证据解释。

背景（修复前已复现的缺陷）
--------------------------
`artifacts/acceptance/exports/m2_sros2_enforce/logs/tests_evidence/20261009T093144Z`
中 S3/S4 的原生 Fast DDS 拒绝日志由终端着色输出写入文件，控制序列**插进**
`SECURITY Error` 字样内部，导致旧的 `DENIAL_RE` 完全无法匹配：

    ESC[31;1m[ ESC[37;1mSECURITY ESC[31;1m Error]

结果是 S3/S4 被误判为「无原生拒绝证据」而失败关闭为 UNKNOWN，真实的 DDS
权限拒绝证据被丢弃。旧单元测试使用**手工合成的无 ANSI**日志，因此看不到该缺陷。

本文件使用归档真实字节，覆盖任务书要求的全部负例，并明确：
  * 超时 / Action Server 不可达 / 业务 TaskPolicy 阻断 / 普通异常
    **不得**被解释为 DDS 权限拒绝；
  * 缺少 S3C 正向对照时不得给出拒绝结论；
  * 日志资源与期望资源不一致时不得给出拒绝结论；
  * 权限文件与运行证据矛盾时失败关闭；
  * 缺失/损坏日志失败关闭。

归档证据只读：所有负例都在 tmp_path 中构造副本，绝不改写
`artifacts/acceptance/exports/` 下的原始记录。
"""
from __future__ import annotations

import json
import shutil
import sys
from argparse import Namespace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

from identity_trust.assessor import (assessment, dds_denial_evidence,  # noqa: E402
                                     examine, native_denial_records,
                                     native_denial_line, normalize_ansi,
                                     permission_permits, policy_permits)
import validate_team_contracts as vtc  # noqa: E402

#: 归档的真实 SROS2 域 43 Enforce 实验（7/7 PASS）。
ARCHIVE = (ROOT / 'artifacts' / 'acceptance' / 'exports' / 'm2_sros2_enforce'
           / 'logs' / 'tests_evidence')
RUN_ID = '20261009T093144Z'
REAL_RUN = ARCHIVE / RUN_ID

REAL_LOG_FILES = {
    'S2': 'planner.log',
    'S3': 'rogue_planner.log',
    'S3C': 'rogue_gateway.log',
    'S4': 'rogue_unauthorized.log',
}

POLICY = ROOT / 'security' / 'policies' / 'minimal_permissions.xml'
KEYSTORE = ROOT / 'security' / 'keystore'


def envelope(request='req-m2-real', resource='/rg/guarded_navigate'):
    return {
        'schema_version': '1.0.0-proposed', 'run_id': 'run-m2-real',
        'request_id': request, 'created_at': '2026-10-14T08:00:00Z',
        'candidate_action': {'action_resource': resource, 'operation': 'NAVIGATE',
                             'task_id': 'patrol_a_001',
                             'target': {'frame_id': 'map', 'x': 1.5, 'y': 1.5}},
        'observations': [{'source': 'security', 'kind': 'UNKNOWN',
                          'observed_at': '2026-10-14T08:00:00Z'}],
        'evidence_refs': [{'ref': 'tests/unit/test_identity_trust_real_logs.py',
                           'kind': 'UNIT_TEST'}],
    }


def opts(**over):
    base = {'policy': str(POLICY), 'keystore': str(KEYSTORE),
            'evidence_root': str(ARCHIVE), 'experiment_run': RUN_ID, 'case': 'S3'}
    base.update(over)
    return Namespace(**base)


def assert_schema(payload):
    """输出必须符合未修改的公共 Schema。"""
    schema = json.loads((ROOT / 'docs' / 'interfaces' / 'schemas'
                         / 'identity_trust_assessment.schema.json')
                        .read_text(encoding='utf-8'))
    errors = vtc.validate_document(payload, schema)
    assert not errors, errors


class EvidenceCopy:
    """在 tmp_path 中重建一份可修改的受控实验证据树。"""

    def __init__(self, tmp_path, run_id='run-real-01', real=True):
        self.run_id = run_id
        self.root = tmp_path / 'evidence'
        self.run = self.root / run_id
        self.run.mkdir(parents=True)
        real_run = REAL_RUN
        summary = json.loads((real_run / 'summary.json').read_text(encoding='utf-8'))
        self.scenarios = {s['scenario_id']: dict(s) for s in summary['scenarios']}
        for case, name in REAL_LOG_FILES.items():
            (self.run / case).mkdir()
            source = real_run / case / name
            target = self.run / case / name
            if real:
                shutil.copyfile(source, target)      # 真实字节，含 ANSI
            else:
                target.write_bytes(source.read_bytes())
        self.write_summary()

    def log_path(self, case):
        return self.run / case / REAL_LOG_FILES[case]

    def write_log(self, case, text, encoding='utf-8'):
        self.log_path(case).write_text(text, encoding=encoding)

    def write_log_bytes(self, case, data):
        self.log_path(case).write_bytes(data)

    def write_summary(self, drop=(), **over):
        cases = [v for k, v in self.scenarios.items() if k not in drop]
        doc = {'suite': 'sros2', 'run_id': self.run_id, 'secure_domain': '43',
               'failed': 0, 'scenarios': cases}
        doc.update(over)
        (self.run / 'summary.json').write_text(json.dumps(doc), encoding='utf-8')

    def options(self, case='S3', keystore=None, policy=None):
        return opts(evidence_root=str(self.root), experiment_run=self.run_id,
                    case=case, keystore=str(keystore or KEYSTORE),
                    policy=str(policy or POLICY))


# ---------------------------------------------------------------------------
# 1) 真实日志的 ANSI 规范化（正例）
# ---------------------------------------------------------------------------

def test_real_s3_log_bytes_contain_interleaved_ansi():
    """前置事实：归档 S3 日志确实把控制序列插进 SECURITY Error 字样内部。"""
    raw = (REAL_RUN / 'S3' / 'rogue_planner.log').read_bytes()
    assert b'\x1b[' in raw, '归档日志必须含 ANSI 控制序列'
    assert b'SECURITY' in raw and b'not found in allow rule' in raw
    # 插入位置：SECURITY 之前与 Error 之前都有转义序列
    assert b'\x1b[37;1mSECURITY\x1b[31;1m Error]' in raw


def test_normalize_ansi_is_lossless_for_plain_text():
    plain = 'no escapes here\n'
    text, stats = normalize_ansi(plain)
    assert text == plain and stats['had_escapes'] is False


def test_normalize_ansi_strips_csi_and_reports_counts():
    raw = (REAL_RUN / 'S3' / 'rogue_planner.log').read_text(encoding='utf-8',
                                                            errors='replace')
    text, stats = normalize_ansi(raw)
    assert stats['had_escapes'] is True
    assert stats['csi'] > 0
    assert '\x1b' not in text
    assert stats['residual_ctrl'] == 0
    # 规范化后原生签名恢复可读
    assert '[SECURITY Error]' in text
    assert 'not found in allow rule' in text
    assert 'Permissions.cpp:1246' in text


def test_normalize_ansi_does_not_rewrite_semantics():
    """规范化只删除转义序列，不改变任何非转义字符。"""
    raw = (REAL_RUN / 'S4' / 'rogue_unauthorized.log').read_text(
        encoding='utf-8', errors='replace')
    text, _ = normalize_ansi(raw)
    strip_esc = lambda s: ''.join(  # noqa: E731
        ch for ch in s if ch != '\x1b')
    # 规范化结果必须等于「原文按正规文法删除转义序列」的结果
    import re as _re
    expected = _re.sub('\x1b\\[[0-?]*[ -/]*[@-~]', '', raw)
    expected = _re.sub('\x1b[@-Z\\\\-_]', '', expected)
    assert text == expected


@pytest.mark.parametrize('case', ['S3', 'S4'])
def test_real_denial_log_yields_native_records(case):
    """真实 S3/S4 日志必须抽出原生拒绝记录，且资源与场景期望一致。"""
    raw = (REAL_RUN / case / REAL_LOG_FILES[case]).read_text(
        encoding='utf-8', errors='replace')
    records = native_denial_records(raw)
    assert records, '真实日志必须抽出至少一条原生拒绝记录'
    topics = {r[2] for r in records}
    assert topics == {'rr/rg/nav_execute/_action/send_goalReply'}
    for line_no, line, topic in records:
        assert line_no >= 1
        assert 'not found in allow rule' in line
        assert 'Permissions.cpp' in line


def test_real_log_without_ansi_also_matches():
    """要求：不含 ANSI 的真实 DDS 拒绝日志同样必须匹配。

    这里对真实字节做**有损的 ANSI 删除**得到等价的纯文本日志。
    """
    raw = (REAL_RUN / 'S3' / 'rogue_planner.log').read_text(
        encoding='utf-8', errors='replace')
    plain, _ = normalize_ansi(raw)
    records = native_denial_records(plain)
    assert records and records[0][2] == 'rr/rg/nav_execute/_action/send_goalReply'
    observed = {'outcome': 'ACTION_CLIENT_CREATION_DENIED'}
    detail = dds_denial_evidence(plain, '/rg/nav_execute', observed)
    assert detail['resource_topic'] == 'rr/rg/nav_execute/_action/send_goalReply'


@pytest.mark.parametrize('case', ['S3', 'S4'])
def test_real_evidence_reaches_denied_at_evidence_layer(case):
    """证据层（资源一致）必须给出 DENIED，而不是失败关闭。"""
    detail = examine(POLICY, KEYSTORE, ARCHIVE, RUN_ID, case)
    assert detail['status'] == 'DENIED'
    assert detail['denial_topic'] == 'rr/rg/nav_execute/_action/send_goalReply'
    assert 'not found in allow rule' in detail['denial']
    # S3C 正向对照必须存在
    assert detail['control_refs'], '拒绝结论必须依赖同 run 的正向对照'


@pytest.mark.parametrize('case', ['S3', 'S4'])
def test_real_evidence_current_request_stays_unknown(case):
    """当前候选入口是 /rg/guarded_navigate：历史 /rg/nav_execute 判定不得搬用。"""
    out = assessment(envelope(), opts(case=case))
    assert out['status'] == 'UNKNOWN'
    assert out['extensions']['current_request_binding'] == 'HISTORICAL_RESOURCE_MISMATCH'
    assert out['extensions']['historical_experiment_status'] == 'DENIED'
    assert out['extensions']['historical_experiment_resource'] == '/rg/nav_execute'
    assert out['requested_resource']['resource'] == '/rg/guarded_navigate'
    assert_schema(out)


def test_real_s3c_control_is_not_promoted_to_current_request():
    out = assessment(envelope(), opts(case='S3C'))
    assert out['status'] == 'UNKNOWN'
    assert out['extensions']['positive_control_verified'] is True
    assert out['extensions']['current_request_binding'] == 'HISTORICAL_RESOURCE_MISMATCH'


def test_real_s2_authorizes_only_matching_entry_resource():
    out = assessment(envelope(), opts(case='S2'))
    assert out['status'] == 'AUTHORIZED'
    assert out['extensions']['current_request_binding'] == 'HISTORICAL_RESOURCE_MATCHES_CURRENT'
    assert 'authenticated_identity' not in out['subject']
    assert_schema(out)


# ---------------------------------------------------------------------------
# 2) 不得误判为 DDS 拒绝（负例）
# ---------------------------------------------------------------------------

def test_plain_text_non_dds_line_is_not_a_denial():
    """"SECURITY Error" 但**没有** allow-rule 语义的行不算拒绝。"""
    line = ('[SECURITY Error] Error checking creation of local reader '
            '(./src/cpp/security/accesscontrol/Permissions.cpp:1246)')
    assert native_denial_line(line) is None


def test_multi_line_reassembly_is_not_a_denial():
    """跨行拼接不得构成拒绝证据（旧正则的 `.{0,600}?` 可跨行）。"""
    text = ('2026-10-09 [SECURITY Error] some unrelated reader warning\n'
            '2026-10-09 note: topic not found in allow rule was mentioned earlier\n')
    assert native_denial_records(text) == []


@pytest.mark.parametrize('outcome', [
    'SEND_GOAL_TIMEOUT', 'RESULT_TIMEOUT', 'GOAL_ACCEPTANCE_TIMEOUT',
    'NO_ACTION_SERVER', 'ACTION_SERVER_UNREACHABLE', 'GOAL_REJECTED',
])
def test_timeout_and_unreachable_are_never_dds_denials(outcome):
    """客户端超时 / Action Server 不可达即使伴随原生文本也不是 DDS 拒绝。"""
    raw = (REAL_RUN / 'S3' / 'rogue_planner.log').read_text(
        encoding='utf-8', errors='replace')
    with pytest.raises(ValueError) as info:
        dds_denial_evidence(raw, '/rg/nav_execute', {'outcome': outcome})
    assert 'not a DDS access-control denial' in str(info.value)


@pytest.mark.parametrize('marker', ['OUT_OF_REGION', 'TASK_MISMATCH',
                                    'DUPLICATE_REQUEST', 'RATE_LIMIT',
                                    'POLICY_MISSING'])
def test_business_policy_block_is_not_dds_denial(marker):
    """业务 TaskPolicy BLOCK 不得冒充 DDS 权限拒绝。"""
    raw = (REAL_RUN / 'S3' / 'rogue_planner.log').read_text(
        encoding='utf-8', errors='replace')
    observed = {'outcome': 'ACTION_CLIENT_CREATION_DENIED', 'reason_code': marker}
    with pytest.raises(ValueError) as info:
        dds_denial_evidence(raw, '/rg/nav_execute', observed)
    assert 'business policy' in str(info.value)


def test_unknown_outcome_class_is_rejected():
    raw = (REAL_RUN / 'S3' / 'rogue_planner.log').read_text(
        encoding='utf-8', errors='replace')
    with pytest.raises(ValueError) as info:
        dds_denial_evidence(raw, '/rg/nav_execute', {'outcome': 'UNEXPECTED_THING'})
    assert 'not a native denial class' in str(info.value)


def test_real_log_rewritten_to_timeout_cannot_deny(tmp_path):
    """把真实拒绝日志换成超时场景：必须 UNKNOWN，不得 DENIED。"""
    copy = EvidenceCopy(tmp_path)
    copy.write_log('S3', 'ROGUE_RESULT ' + json.dumps({
        'node_name': 'planner_node', 'target_action': '/rg/nav_execute',
        'outcome': 'SEND_GOAL_TIMEOUT'}) + '\n')
    out = assessment(envelope(), copy.options('S3'))
    assert out['status'] == 'UNKNOWN'
    assert out['authorization']['denial_layer'] == 'UNKNOWN'
    assert_schema(out)


# ---------------------------------------------------------------------------
# 3) 缺少正向对照 / 资源不一致 / 权限矛盾 / 缺失损坏
# ---------------------------------------------------------------------------

def test_missing_positive_control_fails_closed(tmp_path):
    """S3/S4 必须依赖同 run 的 S3C 正向对照。"""
    copy = EvidenceCopy(tmp_path)
    copy.write_log('S3C', 'ROGUE_RESULT ' + json.dumps({
        'node_name': 'security_gateway', 'target_action': '/rg/nav_execute',
        'outcome': 'RESULT', 'success': False}) + '\n')
    out = assessment(envelope(), copy.options('S3'))
    assert out['status'] == 'UNKNOWN'
    assert '正向对照' in out['reason'] or 'control' in out['reason']


def test_missing_positive_control_scenario_fails_closed(tmp_path):
    copy = EvidenceCopy(tmp_path)
    copy.write_summary(drop=('S3C',))
    out = assessment(envelope(), copy.options('S3'))
    assert out['status'] == 'UNKNOWN'


def test_denial_resource_mismatch_fails_closed(tmp_path):
    """日志中的拒绝资源与场景期望资源不一致 -> 不得 DENIED。"""
    copy = EvidenceCopy(tmp_path)
    copy.write_log('S3', (
        '2026-10-09 [SECURITY Error] rr/rg/other_action/_action/send_goalReply '
        'topic not found in allow rule. '
        '(./src/cpp/security/accesscontrol/Permissions.cpp:1246)\n'
        'ROGUE_RESULT ' + json.dumps({
            'node_name': 'planner_node', 'target_action': '/rg/nav_execute',
            'outcome': 'ACTION_CLIENT_CREATION_DENIED'}) + '\n'))
    out = assessment(envelope(), copy.options('S3'))
    assert out['status'] == 'UNKNOWN'
    assert 'does not match expected resource' in out['reason']


def test_denial_resource_mismatch_with_ansi_fails_closed(tmp_path):
    copy = EvidenceCopy(tmp_path)
    copy.write_log('S3', (
        '\x1b[31;1m[\x1b[37;1mSECURITY\x1b[31;1m Error] \x1b[37m'
        'rr/rg/wrong_action/_action/send_goalReply topic not found in allow rule. '
        '(./src/cpp/security/accesscontrol/Permissions.cpp:1246)\x1b[m\n'
        'ROGUE_RESULT ' + json.dumps({
            'node_name': 'planner_node', 'target_action': '/rg/nav_execute',
            'outcome': 'ACTION_CLIENT_CREATION_DENIED'}) + '\n'))
    out = assessment(envelope(), copy.options('S3'))
    assert out['status'] == 'UNKNOWN'
    assert 'does not match expected resource' in out['reason']


def test_permission_file_contradicting_runtime_fails_closed(tmp_path):
    """权限文件与运行证据矛盾 -> 失败关闭（不得沿用历史拒绝）。

    构造方式：源策略仍不允许 planner 访问 /rg/nav_execute，但把**生成的**
    DDS permissions.xml 改成允许。两者不一致必须导致失败关闭，而不是
    因为「运行日志里确实有拒绝」就接受这个被篡改的配置。
    """
    copy = EvidenceCopy(tmp_path)
    keystore = tmp_path / 'keystore'
    shutil.copytree(KEYSTORE, keystore)
    target = keystore / 'enclaves' / 'planner' / 'permissions.xml'
    text = target.read_text(encoding='utf-8')
    text = text.replace(
        '<topic>rq/rg/guarded_navigate/_action/send_goalRequest</topic>',
        '<topic>rq/rg/guarded_navigate/_action/send_goalRequest</topic>'
        '<topic>rq/rg/nav_execute/_action/send_goalRequest</topic>')
    text = text.replace(
        '<topic>rr/rg/guarded_navigate/_action/send_goalReply</topic>',
        '<topic>rr/rg/guarded_navigate/_action/send_goalReply</topic>'
        '<topic>rr/rg/nav_execute/_action/send_goalReply</topic>')
    target.write_text(text, encoding='utf-8')
    # 前置事实：确实构成了「源策略拒绝 / 生成权限允许」的矛盾
    service = '/rg/nav_execute/_action/send_goal'
    assert policy_permits(POLICY, '/planner', service)[1] is False
    assert permission_permits(target, service) is True
    out = assessment(envelope(), copy.options('S3', keystore=keystore))
    assert out['status'] == 'UNKNOWN'
    assert 'policy and generated DDS permission disagree' in out['reason']
    assert '失败关闭' in out['reason']


def test_missing_case_log_fails_closed(tmp_path):
    copy = EvidenceCopy(tmp_path)
    copy.log_path('S3').unlink()
    out = assessment(envelope(), copy.options('S3'))
    assert out['status'] == 'UNKNOWN'
    assert out['access_control_evidence']['kind'] == 'UNKNOWN'


def test_corrupt_binary_log_fails_closed(tmp_path):
    """损坏（非 UTF-8/含 NUL）日志不得被解释成拒绝。"""
    copy = EvidenceCopy(tmp_path)
    copy.write_log_bytes('S3', b'\xff\xfe\x00\x00SECURITY\x00garbage\x00')
    out = assessment(envelope(), copy.options('S3'))
    assert out['status'] == 'UNKNOWN'


def test_truncated_denial_line_fails_closed(tmp_path):
    """被截断的原生报错（缺 Permissions.cpp 位置）不得算作拒绝。"""
    copy = EvidenceCopy(tmp_path)
    copy.write_log('S3', (
        '2026-10-09 [SECURITY Error] rr/rg/nav_execute/_action/send_goalReply '
        'topic not found in allow rule\n'
        'ROGUE_RESULT ' + json.dumps({
            'node_name': 'planner_node', 'target_action': '/rg/nav_execute',
            'outcome': 'ACTION_CLIENT_CREATION_DENIED'}) + '\n'))
    out = assessment(envelope(), copy.options('S3'))
    assert out['status'] == 'UNKNOWN'


def test_corrupt_summary_fails_closed(tmp_path):
    copy = EvidenceCopy(tmp_path)
    (copy.run / 'summary.json').write_text('{"suite": "sros2",', encoding='utf-8')
    out = assessment(envelope(), copy.options('S3'))
    assert out['status'] == 'UNKNOWN'


def test_summary_with_failed_scenario_fails_closed(tmp_path):
    copy = EvidenceCopy(tmp_path)
    copy.write_summary(failed=1)
    out = assessment(envelope(), copy.options('S3'))
    assert out['status'] == 'UNKNOWN'


def test_log_oversized_rejected(tmp_path):
    copy = EvidenceCopy(tmp_path)
    copy.write_log_bytes('S3', b'x' * (3_000_000 + 1))
    out = assessment(envelope(), copy.options('S3'))
    assert out['status'] == 'UNKNOWN'


def test_symlinked_log_rejected(tmp_path):
    copy = EvidenceCopy(tmp_path)
    real = copy.log_path('S3')
    payload = real.read_bytes()
    real.unlink()
    elsewhere = tmp_path / 'elsewhere.log'
    elsewhere.write_bytes(payload)
    real.symlink_to(elsewhere)
    out = assessment(envelope(), copy.options('S3'))
    assert out['status'] == 'UNKNOWN'


# ---------------------------------------------------------------------------
# 4) 历史证据与当前请求的绑定声明
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('case', ['S2', 'S3', 'S3C', 'S4'])
def test_every_output_states_binding_and_limitation(case):
    out = assessment(envelope(), opts(case=case))
    ext = out['extensions']
    assert ext['historical_only'] is True
    assert 'current_request_binding' in ext
    assert 'historical_experiment_resource' in ext
    assert 'current_candidate_resource' in ext
    assert '都不是 DDS 已认证身份' in ext['identity_binding_note']
    # 任何情况下都不得填入已认证身份
    assert 'authenticated_identity' not in out['subject']
    assert_schema(out)


def test_self_declared_identity_cannot_change_binding():
    """业务 JSON 自报身份不得被当作 DDS 已认证身份。"""
    env = envelope()
    env['observations'][0]['detail'] = {
        'authenticated': True, 'enclave': '/gateway', 'role': 'gateway',
        'dds_identity': 'CN=/gateway'}
    env['extensions'] = {'authenticated_identity': 'CN=/gateway',
                         'experiment_run': 'attacker-chosen-run'}
    out = assessment(env, opts(case='S2'))
    # 结论只由受信任配置 + 归档证据决定
    assert out['status'] == 'AUTHORIZED'
    assert 'authenticated_identity' not in out['subject']
    assert out['extensions']['experiment_run_id'] == RUN_ID
    assert_schema(out)


def test_archive_is_never_modified():
    """本测试文件绝不改写归档证据（只读断言）。"""
    before = (REAL_RUN / 'S3' / 'rogue_planner.log').read_bytes()
    assert b'\x1b[' in before
    assert (REAL_RUN / 'S3C' / 'rogue_gateway.log').is_file()


# ---------------------------------------------------------------------------
# 5) 通用验收器的真实模块模式（M2）
# ---------------------------------------------------------------------------

REAL_CONFIG = ROOT / 'config' / 'team_modules.member2.real.yaml'
REAL_FIXTURE = ROOT / 'config' / 'acceptance' / 'real_scenarios.member2.yaml'


def _run_m2_checker(tmp_path, run_id):
    import subprocess
    return subprocess.run(
        [sys.executable, str(ROOT / 'scripts' / 'check_member_module.py'),
         '--module', 'identity_trust', '--config', str(REAL_CONFIG),
         '--real-fixture', str(REAL_FIXTURE),
         '--out-dir', str(tmp_path), '--run-id', run_id],
        capture_output=True, text=True, timeout=900, cwd=str(ROOT))


def test_m2_real_fixture_reaches_gate(tmp_path):
    """真实评估器在真实 fixture 下的四场景状态必须正确。

    注意（WORK_A / A2 语义收紧）
    ---------------------------
    历史实现曾断言 `meets_pr_gate is True`，因为 S2 的历史 `AUTHORIZED` 被视为
    足以让适配层推进。这在语义上是错的：历史受控实验只证明**当时那次运行**中
    某个已认证主体访问成功，不证明当前这条候选请求的发送方身份。
    现在 F0 额外要求 `extensions.current_request_identity.status ==
    AUTHENTICATED`；真实模块在拿不到中间件身份证据时只能给 UNKNOWN，
    因此**没有任何一条真实路径能让适配层推进**（下面逐条断言）。

    L1 协议门槛仍然通过：四场景状态、Schema、可追溯性、ID 关联、失败关闭。
    "通过 L1 门槛"与"能证明当前请求身份"是两条不同的轴，后者见交接文件里
    的 ONLINE_PROCEED_READY = FAIL。
    """
    proc = _run_m2_checker(tmp_path, 'm2-gate')
    assert proc.returncode == 0, proc.stdout[-3000:] + proc.stderr[-2000:]
    report = json.loads((tmp_path / 'm2-gate' / 'report.json')
                        .read_text(encoding='utf-8'))
    assert report['meets_pr_gate'] is True, report.get('counts')
    rows = {r['scenario']: r for r in report['real_state_matrix']}
    # 没有任何一条真实场景能让适配层给出 READY
    adapter_rows = [c for c in report['checks'] if c['id'].startswith('REAL-ADP-')]
    assert adapter_rows
    assert all(c['decision'] == 'ADAPTER_BLOCK' for c in adapter_rows), adapter_rows
    assert set(rows) == {'s2-authorized', 's3c-positive-control',
                         's3-native-denial', 's4-native-denial'}
    assert rows['s2-authorized']['actual_state'] == 'AUTHORIZED'
    for name in ('s3c-positive-control', 's3-native-denial', 's4-native-denial'):
        assert rows[name]['actual_state'] == 'UNKNOWN', rows[name]
        assert rows[name]['actual_class'] == 'LEGAL_BLOCK'
    for row in rows.values():
        assert row['schema_ok'] is True
        assert row['traceability_ok'] is True
        assert row['ids_ok'] is True


def test_m2_real_fixture_blocks_and_never_authorizes_nav_execute(tmp_path):
    """S3/S4 的历史拒绝不得被提升为当前 guarded 请求的结论。"""
    _run_m2_checker(tmp_path, 'm2-block')
    report = json.loads((tmp_path / 'm2-block' / 'report.json')
                        .read_text(encoding='utf-8'))
    checks = {c['id']: c for c in report['checks']}
    for name in ('S3C-POSITIVE-CONTROL', 'S3-NATIVE-DENIAL', 'S4-NATIVE-DENIAL'):
        entry = checks['REAL-ADP-{0}'.format(name)]
        assert entry['status'] == 'PASS', entry
        assert entry['decision'] == 'ADAPTER_BLOCK'
    # S2 的历史资源与当前候选入口一致，模块级结论是 AUTHORIZED，
    # 但**当前请求身份未绑定**，适配层必须阻断在 ADAPTER_CURRENT_IDENTITY_UNBOUND。
    s2 = checks['REAL-ADP-S2-AUTHORIZED']
    assert s2['status'] == 'PASS', s2
    assert s2['decision'] == 'ADAPTER_BLOCK', s2
    assert s2['reason_code'] == 'ADAPTER_CURRENT_IDENTITY_UNBOUND', s2
    assert s2.get('gateway_decision') is None


def test_m2_fixture_cannot_inject_commands(tmp_path):
    """M2 fixture 同样受「业务输入不得指定命令」约束。"""
    import yaml as _yaml
    sys.path.insert(0, str(ROOT / 'scripts'))
    import check_member_module as cmm
    document = _yaml.safe_load(REAL_FIXTURE.read_text(encoding='utf-8'))
    document['real_scenarios']['identity_trust'][0]['envelope_patch']['command'] = '/bin/sh'
    bad = tmp_path / 'bad-m2.yaml'
    bad.write_text(_yaml.safe_dump(document, allow_unicode=True), encoding='utf-8')
    with pytest.raises(cmm.FixtureError):
        cmm.parse_real_fixture(str(bad), 'identity_trust',
                               cmm.load_yaml(str(REAL_CONFIG)))


def test_m2_non_dds_outcome_still_cannot_deny_end_to_end(tmp_path):
    """真实 fixture 通路下，超时场景仍然只能是 UNKNOWN。"""
    copy = EvidenceCopy(tmp_path)
    copy.write_log('S3', 'ROGUE_RESULT ' + json.dumps({
        'node_name': 'planner_node', 'target_action': '/rg/nav_execute',
        'outcome': 'SEND_GOAL_TIMEOUT'}) + '\n')
    out = assessment(envelope(), copy.options('S3'))
    assert out['status'] == 'UNKNOWN'
    assert out['authorization']['denial_layer'] == 'UNKNOWN'
@pytest.mark.parametrize('request_id', [
    'req-m2-short',
    'r' * 64,
    'r' * 80,       # 模块对 request_id 的保留长度上限（见模块实现）
])
def test_event_id_correlates_with_request_id_within_schema_limit(request_id):
    """event_id 必须含 request_id（验收器 ID-03），且不超过 Schema 128 字符。"""
    env = envelope(request=request_id)
    out = assessment(env, opts(case='S2'))
    event_id = out['event_id']
    assert request_id in event_id
    assert len(event_id) <= 128, len(event_id)
    assert_schema(out)


@pytest.mark.parametrize('length', [81, 100, 128])
def test_event_id_never_exceeds_schema_limit_for_long_request_ids(length):
    """超长 request_id 下 event_id 仍必须满足 Schema（宁可截断也不能越界）。

    契约张力 R-1：request_id > 80 字符时被截断，此时「event_id 含完整
    request_id」不成立。若改用较短的随机后缀，可把完整包含上限提高到 102，
    但 103 字符以上的 request_id 仍然无法同时满足两条约束。本模块选择
    与 modules/member3_taskrisk 相同的 80 字符约定，并始终保证 Schema 合法。
    """
    env = envelope(request='r' * length)
    out = assessment(env, opts(case='S2'))
    assert len(out['event_id']) <= 128, len(out['event_id'])
    assert_schema(out)
