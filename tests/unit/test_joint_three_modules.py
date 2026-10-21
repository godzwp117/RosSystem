"""三成员真实模块联合调用：关联、隔离与失败关闭。

为什么不用 F0 做联合证据
------------------------
F0（scripts/team_demo.py）在**第一个非推进模块**处短路：这是它有意的失败快速
路径，可以避免为一条注定被阻断的请求继续启动更多进程。代价是当 comm_risk 为
UNKNOWN 时，identity_trust / task_risk 根本不会被调用，无法作为"三模块联合
运行"的证据。

因此本文件复用 F0 的**同一套安全原语**（`team_demo.invoke_module`：
有界读取、独立进程组、超时终止、Schema 校验）逐个调用三个真实模块，
只用于采集证据与验证关联/隔离。它**不产生任何准入结论**，
也不创建任何下游执行通道；准入权威仍然只有 SecurityGateway。

F0 的短路行为本身也是被测对象（见 test_f0_stops_at_first_blocking_module）。
"""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest

pytest.importorskip('jsonschema', reason='需要 jsonschema>=4.0（Draft 2020-12）')

ROOT = Path(__file__).resolve().parents[2]
for extra in (ROOT, ROOT / 'scripts', ROOT / 'tests' / 'unit'):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import validate_team_contracts as vtc  # noqa: E402
import team_demo  # noqa: E402
from test_team_process_protocol import envelope, proceed_control, run_adapter, write_config  # noqa: E402

PROBES = ROOT / 'tests' / 'fixtures' / 'member1' / 'rospace_comm_rows.json'
MODEL = ROOT / 'modules/member1_comm/model/comm_risk_model.json'
FEATURES = ROOT / 'modules/member1_comm/features.json'
MANIFEST = ROOT / 'modules/member1_comm/model/model_manifest.json'
KEYSTORE = ROOT / 'security/keystore'
EVIDENCE = ROOT / 'artifacts/acceptance/exports/m2_sros2_enforce/logs/tests_evidence'
EXPERIMENT_RUN = '20261009T093144Z'
NEEDS_LOCAL_EVIDENCE = pytest.mark.skipif(
    not (KEYSTORE / 'enclaves').is_dir() or not EVIDENCE.is_dir(),
    reason=('需要本地 SROS2 keystore（security/keystore，已在 .gitignore 排除）'
            '与归档的 S2 受控实验证据；这两者都不是版本控制内容'))


def probe_row(above=False):
    document = json.loads(PROBES.read_text(encoding='utf-8'))
    threshold = document['model']['threshold']
    if above:
        return next(r for r in document['rows'] if r['score'] >= threshold)
    return next(r for r in document['rows'] if r['score'] < threshold)


def joint_envelope(row):
    document = envelope(proceed_control())
    detail = document['observations'][0]['detail']
    detail['rospace_comm'] = {'features': {
        'feature_names': row['feature_names'], 'values': row['values']}}
    detail['f0_runtime'] = {
        'communication': {'resource': '/rg/guarded_navigate',
                          'resource_type': 'Action', 'operation': 'GOAL_SEND'},
        'request_count': 12,
        'window': {'start': '2026-10-10T11:59:55Z',
                   'end': '2026-10-10T12:00:00Z', 'duration_ms': 5000},
    }
    document['observations'][0]['observed_at'] = '2026-10-10T11:59:58Z'
    return document


def all_real_config(tmp_path, *, comm_extra=(), comm_timeout=10):
    tmp_path.mkdir(parents=True, exist_ok=True)
    sha = json.loads(MANIFEST.read_text(encoding='utf-8'))['model_sha256']
    commands = {
        'comm_risk': [sys.executable, 'modules/member1_comm/module.py',
                      '--model', str(MODEL), '--model-sha256', sha,
                      '--features', str(FEATURES), *comm_extra],
        'identity_trust': [sys.executable, 'identity_trust/assessor.py',
                           '--experiment-run', EXPERIMENT_RUN,
                           '--evidence-root', str(EVIDENCE),
                           '--policy', str(ROOT / 'security/policies/minimal_permissions.xml'),
                           '--keystore', str(KEYSTORE),
                           '--case', 'S2'],
        'task_risk': [sys.executable, 'modules/member3_taskrisk/module.py',
                      '--policy', str(ROOT / 'config/task_policy.yaml')],
    }
    path = write_config(tmp_path, commands=commands,
                        timeouts={'comm_risk': comm_timeout, 'identity_trust': 10,
                                  'task_risk': 10})
    return team_demo.load_config(path)['modules']


def call(modules, name, document, records, invocation_id):
    text = json.dumps(document, ensure_ascii=False)
    return team_demo.invoke_module(name, modules[name], text, str(ROOT),
                                   invocation_id, records)


@NEEDS_LOCAL_EVIDENCE
def test_all_three_real_modules_are_really_invoked(tmp_path):
    """三个真实模块都能被真实调用，且各自是独立进程。"""
    modules = all_real_config(tmp_path)
    document = joint_envelope(probe_row())
    records = []
    invocation_id = uuid.uuid4().hex[:12]
    outputs = {}
    for name in team_demo.MODULE_ORDER:
        outputs[name], _record = call(modules, name, document, records, invocation_id)
    assert len(records) == 3
    for record in records:
        assert record['exit_code'] == 0, record
        assert record['schema_ok'] is True, record
        assert record['stdout_bytes'] > 0
        assert record['mode'] == 'mock' or record['command']  # 命令来自受信任配置
    assert {r['module'] for r in records} == set(team_demo.MODULE_ORDER)
    # 真实模块可执行文件各不相同（不会误用同一个入口）
    assert len({record['command'][1] for record in records}) == 3
    # 独立进程组：三个 PID / PGID 互不相同
    pids = [record['pid'] for record in records]
    pgids = [record['pgid'] for record in records]
    assert len(set(pids)) == 3 and len(set(pgids)) == 3
    assert outputs['comm_risk']['status'] == 'UNKNOWN'
    assert outputs['identity_trust']['status'] == 'AUTHORIZED'
    assert outputs['task_risk']['status'] == 'ALLOW_RECOMMENDED'


@NEEDS_LOCAL_EVIDENCE
def test_ids_correlate_and_event_ids_are_unique(tmp_path):
    """request_id / run_id 必须一致，event_id 必须互不相同（防串单）。"""
    modules = all_real_config(tmp_path)
    document = joint_envelope(probe_row())
    records = []
    invocation_id = uuid.uuid4().hex[:12]
    outputs = {name: call(modules, name, document, records, invocation_id)[0]
               for name in team_demo.MODULE_ORDER}
    event_ids = [doc['event_id'] for doc in outputs.values()]
    assert len(set(event_ids)) == 3, event_ids
    for name, doc in outputs.items():
        assert doc['request_id'] == document['request_id'], name
        assert doc['run_id'] == document['run_id'], name
        assert not vtc.validate_document(
            doc, vtc.load_schema(team_demo.EXPECTED_INTERFACE[name]))
    # 三份输出都能被 F0 的一致性检查接受（不抛 AdapterBlock）
    team_demo.check_consistency(document, outputs)


@NEEDS_LOCAL_EVIDENCE
def test_one_module_timeout_does_not_disturb_the_others(tmp_path):
    """单模块超时只终止该次调用的进程组，不影响其它模块。"""
    modules = all_real_config(tmp_path, comm_timeout=0.05)
    document = joint_envelope(probe_row())
    records = []
    invocation_id = uuid.uuid4().hex[:12]
    with pytest.raises(team_demo.AdapterBlock) as caught:
        call(modules, 'comm_risk', document, records, invocation_id)
    assert caught.value.reason_code == team_demo.REASON_TIMEOUT
    timed_out = records[0]
    assert timed_out['cleanup'] in ('terminated', 'already_gone',
                                    'terminated+killed'), timed_out
    # 另一个模块在之后仍然可以正常真实运行
    modules_ok = all_real_config(tmp_path / 'second', comm_timeout=10)
    output, record = call(modules_ok, 'task_risk', document, [], invocation_id)
    assert record['exit_code'] == 0
    assert output['status'] in ('ALLOW_RECOMMENDED', 'BLOCK_RECOMMENDED')


@NEEDS_LOCAL_EVIDENCE
def test_f0_invokes_all_three_then_blocks_on_status(tmp_path):
    """F0 会先调用**全部**三个模块，再统一判定推进条件。

    这一点很重要，容易误判：
      * 进程/协议级故障（超时、非零退出、Schema 非法）会**立即**抛出 AdapterBlock，
        后续模块不再启动（失败快速）；
      * 状态级不推进（UNKNOWN / DENIED / BLOCK_RECOMMENDED）不会提前中止，
        三个模块都真实跑完，最后统一判定为 ADAPTER_BLOCK。

    因此一次真实联合调用就能同时拿到三个模块的证据，适合 B1 做联合审计。
    """
    all_real_config(tmp_path / 'cfg')
    config_path = str(tmp_path / 'cfg' / 'team_modules.yaml')
    _code, result, _err = run_adapter(tmp_path, joint_envelope(probe_row()), config_path)
    assert result['decision'] == 'ADAPTER_BLOCK'
    assert result['reason_code'] == team_demo.REASON_NOT_PROCEED
    records = {r['module']: r for r in result['modules']}
    assert set(records) == set(team_demo.MODULE_ORDER)
    for name, record in records.items():
        assert record['exit_code'] == 0, (name, record)
        assert record['schema_ok'] is True, (name, record)
    # 三份真实结论：M1 证据不足、M2 历史授权、M3 规则允许但不构成准入
    assert records['comm_risk']['status'] == 'UNKNOWN'
    assert records['identity_trust']['status'] == 'AUTHORIZED'
    assert records['task_risk']['status'] == 'ALLOW_RECOMMENDED'


@NEEDS_LOCAL_EVIDENCE
def test_shipped_joint_config_is_usable_and_blocks(tmp_path):
    """仓库交付的 config/team_modules.all-real.yaml 可直接用于联合运行取证。

    唯一改动是把命令首部的裸 `python3` 换成当前解释器（与验收器的
    resolve_interpreter 同一做法）：交付配置面向"已装好依赖的 python3"，
    而测试必须固定解释器，否则 jsonschema 版本差异会让模块失败关闭。
    """
    import yaml
    document = yaml.safe_load(
        (ROOT / 'config' / 'team_modules.all-real.yaml').read_text(encoding='utf-8'))
    for entry in document['modules'].values():
        if entry['command'][0] == 'python3':
            entry['command'][0] = sys.executable
        # 交付配置把重放账本写在 logs/ 下（运行时状态）。测试必须重定向到
        # tmp_path，否则同一 request_id 的第二次运行会被正确判定为
        # "历史授权复用" -> UNKNOWN，使结果不可重复。
        command = entry['command']
        for index, part in enumerate(command):
            if part == '--identity-ledger' and index + 1 < len(command):
                command[index + 1] = str(tmp_path / 'identity_ledger.jsonl')
    config = tmp_path / 'all-real.yaml'
    config.write_text(yaml.safe_dump(document, allow_unicode=True), encoding='utf-8')
    _code, result, _err = run_adapter(tmp_path, joint_envelope(probe_row()), str(config))
    assert result['decision'] == 'ADAPTER_BLOCK'
    assert len(result['modules']) == 3
    assert all(r['schema_ok'] for r in result['modules'])
    statuses = {r['module']: r['status'] for r in result['modules']}
    assert statuses['identity_trust'] == 'AUTHORIZED'
    assert statuses['task_risk'] == 'ALLOW_RECOMMENDED'
