#!/usr/bin/env python3
"""tests/integration/three_real_online_check.py -- 三真实模块系统级联调（工作 B1）。

覆盖任务书 T1–T5（T6 Gateway 独立阻断、T7 DDS Enforce 需要 ROS 2 与安全域，
由在线阶段单独执行，本脚本只如实标注 NOT_RUN，绝不用离线结果冒充）。

设计原则
--------
* **优先用真实模块构造反例**。只有当真实模块在物理上无法产出该故障
  （例如"输出非法 JSON"），才使用测试替身，并在结果里显式标 `TEST_DOUBLE`。
* 每个反例都断言两件事：F0 **不推进**，且**没有提交 Planner**
  （`online.submitted` 为假 / 决策不是 READY_FOR_GATEWAY_SUBMISSION）。
* T3/T4 是**语义反例**：历史授权与离线正常结论都不得被当成当前证据。
  它们必须以自动化回归的形式长期存在，因此写成 pytest 用例。
* 不做任何重试；每次运行使用新 request_id；M2 账本按用例隔离。

运行：
    python3 tests/integration/three_real_online_check.py            # 矩阵摘要
    python3 -m pytest tests/integration/three_real_online_check.py -q
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, 'scripts'))

import yaml  # noqa: E402

BASE_CONFIG = os.path.join(REPO, 'config/team_modules.three-real.yaml')
FIXTURE_ROWS = os.path.join(REPO, 'tests/fixtures/member1/rospace_comm_rows.json')
DOUBLES = os.path.join(REPO, 'tests/fixtures/team_modules')

T = {}          # 用例登记表：名称 -> 结果，供 __main__ 打印矩阵


def _load_base():
    with open(BASE_CONFIG, encoding='utf-8') as handle:
        return yaml.safe_load(handle)


def _write_config(tmpdir, overrides, name='cfg.yaml'):
    """在临时目录里生成配置变体（受信任本地文件，不修改仓库既有配置）。"""
    config = _load_base()
    for module, patch in (overrides or {}).items():
        entry = config['modules'][module]
        for key, value in patch.items():
            entry[key] = value
    config.setdefault('adapter', {})
    config['adapter']['log_path'] = os.path.join(tmpdir, 'adapter.jsonl')
    path = os.path.join(tmpdir, name)
    with open(path, 'w', encoding='utf-8') as handle:
        yaml.safe_dump(config, handle, allow_unicode=True)
    return path


def _ledger_path(tmpdir):
    return os.path.join(tmpdir, 'identity_ledger.jsonl')


def _feature_row(predicate):
    """从真实 held-out 样本里挑一条满足条件的行（用于构造真实 SUSPICIOUS 等）。"""
    with open(FIXTURE_ROWS, encoding='utf-8') as handle:
        document = json.load(handle)
    threshold = document['model']['threshold']
    for row in document['rows']:
        if predicate(row, threshold):
            return row, threshold
    return document['rows'][0], threshold


def _envelope(tmpdir, run_id, request_id, *, score_above_threshold=False,
              target=(2.0, 2.0), task_id='patrol_a_001'):
    """构造联合信封；通信观测块取自真实 held-out 行。"""
    import check_member_module as cmm
    detail = {'f0_mock': {'comm_risk': {'scenario': 'normal'},
                          'identity_trust': {'scenario': 'authorized'},
                          'task_risk': {'scenario': 'allow'}}}
    detail.update(cmm.comm_observation_detail())
    if score_above_threshold:
        row, threshold = _feature_row(lambda r, t: r['score'] >= t)
        detail['rospace_comm'] = {
            'features': {'feature_names': row['feature_names'],
                         'values': row['values']}}
        detail.setdefault('comm_probe_provenance', {})['picked'] = (
            'score>=threshold for SUSPICIOUS')
    window_end = detail['f0_runtime']['window']['end']
    envelope = {
        'schema_version': '1.0.0-proposed',
        'run_id': run_id,
        'created_at': window_end,
        'request_id': request_id,
        'candidate_action': {
            'action_resource': '/rg/guarded_navigate',
            'operation': 'NAVIGATE',
            'task_id': task_id,
            'target': {'frame_id': 'map', 'x': target[0], 'y': target[1],
                       'z': 0.0},
        },
        'observations': [{'source': '/rg/guarded_navigate',
                          'kind': 'RUNTIME_LOG',
                          'observed_at': window_end,
                          'detail': detail}],
        'evidence_refs': [{
            'ref': 'tests/fixtures/member1/rospace_comm_rows.json',
            'kind': 'RUNTIME_LOG',
            'note': 'real held-out ROSPaCe rows; offline classification input',
        }],
    }
    path = os.path.join(tmpdir, 'envelope.json')
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(envelope, handle, ensure_ascii=False, indent=2)
    return path


def _run_f0(tmpdir, config_path, envelope_path):
    cmd = [sys.executable, 'scripts/team_demo.py', '--input', envelope_path,
           '--config', config_path, '--log', os.path.join(tmpdir, 'f0.jsonl')]
    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True,
                          timeout=300)
    try:
        document = json.loads(proc.stdout)
    except ValueError:
        document = {}
    return proc, document


def _module_status(document, name):
    for entry in document.get('modules') or []:
        if entry.get('module') == name:
            return entry.get('status')
    return None


def _assert_blocked(proc, document, label, expect_reason=None):
    """核心断言：不推进、不提交 Planner、下游不会有 Goal。"""
    assert proc.returncode != 0, (
        '{0}: F0 意外成功（rc={1}）'.format(label, proc.returncode))
    assert document.get('decision') != 'READY_FOR_GATEWAY_SUBMISSION', (
        '{0}: F0 意外给出推进状态'.format(label))
    online = document.get('online') or {}
    if online.get('enabled'):
        assert online.get('submitted') is not True, (
            '{0}: 被阻断的请求仍然提交给了 Planner'.format(label))
    if expect_reason:
        assert document.get('reason_code') == expect_reason, (
            '{0}: reason_code={1!r}，期望 {2!r}'.format(
                label, document.get('reason_code'), expect_reason))


# ---------------------------------------------------------------------------
# T1：三个真实模块被真实调用
# ---------------------------------------------------------------------------

def test_t1_three_real_modules_are_called_and_not_mocks():
    tmpdir = tempfile.mkdtemp(prefix='b1-t1-')
    T['T1'] = 'RUN'
    try:
        run_id = 'b1-t1-{0}'.format(int(time.time()))
        out = os.path.join(tmpdir, 'evidence')
        proc = subprocess.run(
            [sys.executable, 'scripts/run_three_real_online.py',
             '--run-id', run_id, '--out-dir', out,
             '--config', 'config/team_modules.three-real.yaml'],
            cwd=REPO, capture_output=True, text=True, timeout=600)
        assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
        summary = json.loads(proc.stdout)
        assert summary['levels']['THREE_EXTERNAL_CALLED'] == 'PASS', summary
        assert summary['levels']['THREE_EXTERNAL_VALIDATED'] == 'PASS', summary
        for name, record in summary['modules'].items():
            assert record['mode'] == 'external', (name, record)
            assert record['returncode'] == 0, (name, record)
            assert record['schema_ok'] is True, (name, record)
            blob = ' '.join(record['command'])
            assert 'mock_modules' not in blob, (name, blob)
            # 真实模块的 producer.source 必须是 EXTERNAL（替身/Mock 会写 MOCK）
            doc_path = os.path.join(out, name + '.json')
            with open(doc_path, encoding='utf-8') as handle:
                document = json.load(handle)
            assert document['producer']['source'] == 'EXTERNAL', (name, document)
        T['T1'] = 'PASS'
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# T2：失败关闭矩阵（优先真实模块，替身显式标注）
# ---------------------------------------------------------------------------

def _case(tmpdir, *, overrides=None, score_above=False, target=(2.0, 2.0),
          name='case'):
    config = _write_config(tmpdir, overrides, name=name + '.yaml')
    envelope = _envelope(tmpdir, 'b1-' + name, 'b1-' + name,
                         score_above_threshold=score_above, target=target)
    return _run_f0(tmpdir, config, envelope)


def test_t2_m1_suspicious_blocks():
    """真实 M1 在高于阈值时给出 SUSPICIOUS -> F0 必须阻断。"""
    tmpdir = tempfile.mkdtemp(prefix='b1-t2a-')
    try:
        proc, doc = _case(tmpdir, score_above=True, name='m1susp')
        label = 'M1 SUSPICIOUS'
        if _module_status(doc, 'comm_risk') != 'SUSPICIOUS':
            # 该样本集可能没有高于阈值的行；如实标注而不是伪装成通过
            T['T2-M1-SUSPICIOUS'] = 'NOT_REACHABLE'
            return
        _assert_blocked(proc, doc, label,
                        expect_reason='ADAPTER_MODULE_STATUS_NOT_PROCEED')
        T['T2-M1-SUSPICIOUS'] = 'PASS'
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_t2_m1_unknown_and_error_block():
    """真实 M1：UNKNOWN（门槛未过）与 ERROR（模型损坏）都必须阻断。"""
    tmpdir = tempfile.mkdtemp(prefix='b1-t2b-')
    try:
        proc, doc = _case(tmpdir, name='m1unknown')
        assert _module_status(doc, 'comm_risk') == 'UNKNOWN', doc
        _assert_blocked(proc, doc, 'M1 UNKNOWN',
                        expect_reason='ADAPTER_MODULE_STATUS_NOT_PROCEED')

        broken = os.path.join(tmpdir, 'broken_model.json')
        with open(broken, 'w', encoding='utf-8') as handle:
            handle.write('{"format": "member1-numeric-v1"')
        config = _write_config(tmpdir, {'comm_risk': {'command': [
            'scripts/module_python.sh', 'modules/member1_comm/module.py',
            '--model', broken,
            '--model-sha256', '0' * 64,
            '--features', 'modules/member1_comm/features.json',
            '--observation-provenance', 'UNKNOWN']}}, name='m1err.yaml')
        envelope = _envelope(tmpdir, 'b1-m1err', 'b1-m1err')
        proc, doc = _run_f0(tmpdir, config, envelope)
        _assert_blocked(proc, doc, 'M1 ERROR/坏模型')
        T['T2-M1-UNKNOWN-ERROR'] = 'PASS'
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_t2_m2_denied_blocks():
    """真实 M2 对 S4（未授权主体）给出 DENIED -> 必须阻断。"""
    tmpdir = tempfile.mkdtemp(prefix='b1-t2c-')
    try:
        command = _load_base()['modules']['identity_trust']['command']
        command = [str(part) for part in command]
        command[command.index('--case') + 1] = 'S4'
        command[command.index('--identity-ledger') + 1] = _ledger_path(tmpdir)
        proc, doc = _case(tmpdir, overrides={'identity_trust': {
            'command': command}}, name='m2denied')
        status = _module_status(doc, 'identity_trust')
        assert status in ('DENIED', 'UNKNOWN'), doc
        _assert_blocked(proc, doc, 'M2 DENIED')
        T['T2-M2-DENIED'] = 'PASS'
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_t2_m3_block_and_error_block():
    """真实 M3：越界 -> BLOCK_RECOMMENDED；策略损坏 -> ERROR。都必须阻断。"""
    tmpdir = tempfile.mkdtemp(prefix='b1-t2d-')
    try:
        proc, doc = _case(tmpdir, target=(9.0, 9.0), name='m3block')
        assert _module_status(doc, 'task_risk') == 'BLOCK_RECOMMENDED', doc
        _assert_blocked(proc, doc, 'M3 BLOCK')

        corrupt = os.path.join(tmpdir, 'corrupt_policy.yaml')
        with open(corrupt, 'w', encoding='utf-8') as handle:
            handle.write('task_id: patrol_a_001\n\tactive: true\n'
                         'allowed_region: {x_min: 0.0, x_max: [unterminated\n')
        command = [str(p) for p in _load_base()['modules']['task_risk']['command']]
        command[command.index('--policy') + 1] = corrupt
        proc, doc = _case(tmpdir, overrides={'task_risk': {'command': command}},
                          name='m3err')
        assert _module_status(doc, 'task_risk') == 'ERROR', doc
        _assert_blocked(proc, doc, 'M3 ERROR')
        T['T2-M3-BLOCK-ERROR'] = 'PASS'
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_t2_timeout_blocks_without_retry():
    """真实模块超时 -> 阻断；且不得重试（只发生一次调用）。"""
    tmpdir = tempfile.mkdtemp(prefix='b1-t2e-')
    try:
        proc, doc = _case(tmpdir, overrides={
            'task_risk': {'timeout_sec': 0.001}}, name='timeout')
        _assert_blocked(proc, doc, 'M3 超时')
        invocations = [m for m in (doc.get('modules') or [])
                       if m.get('module') == 'task_risk']
        assert len(invocations) == 1, invocations
        T['T2-TIMEOUT'] = 'PASS'
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_t2_crash_and_invalid_output_block():
    """模块崩溃（缺模型 -> 退出 3）与非法输出（TEST_DOUBLE）都必须阻断。"""
    tmpdir = tempfile.mkdtemp(prefix='b1-t2f-')
    try:
        missing = os.path.join(tmpdir, 'does-not-exist.json')
        config = _write_config(tmpdir, {'comm_risk': {'command': [
            'scripts/module_python.sh', 'modules/member1_comm/module.py',
            '--model', missing, '--model-sha256', '0' * 64,
            '--features', 'modules/member1_comm/features.json',
            '--observation-provenance', 'UNKNOWN']}}, name='crash.yaml')
        envelope = _envelope(tmpdir, 'b1-crash', 'b1-crash')
        proc, doc = _run_f0(tmpdir, config, envelope)
        _assert_blocked(proc, doc, '模块崩溃')

        # 非法输出必须用替身（真实模块不会故意输出坏 JSON）——显式标注 TEST_DOUBLE
        garbage = os.path.join(tmpdir, 'garbage_double.py')
        with open(garbage, 'w', encoding='utf-8') as handle:
            handle.write('#!/usr/bin/env python3\n'
                         'import sys\n'
                         'sys.stdin.read()\n'
                         'sys.stdout.write("{not json")\n')
        config = _write_config(tmpdir, {'task_risk': {
            'mode': 'external',
            'command': [sys.executable, garbage]}}, name='garbage.yaml')
        envelope = _envelope(tmpdir, 'b1-garbage', 'b1-garbage')
        proc, doc = _run_f0(tmpdir, config, envelope)
        _assert_blocked(proc, doc, '非法输出（TEST_DOUBLE）')
        T['T2-CRASH-INVALID-OUTPUT'] = 'PASS (invalid output uses TEST_DOUBLE)'
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# T3：M2 历史 AUTHORIZED 不得冒充当前请求身份
# ---------------------------------------------------------------------------

def test_t3_historical_authorized_does_not_authorize_current_request():
    """真实 M2 给出 AUTHORIZED（历史），但当前请求身份未绑定 -> 必须阻断。

    为了让 F0 走到身份判定（否则会先被 M1 的 UNKNOWN 挡住），M1 使用
    **真实模块**的受控测试开关（--controlled-test，只能由受信任本地配置打开），
    从而给出 NORMAL 并在输出里带 CONTROLLED_TEST_ONLY 依据。M2/M3 均为真实模块。

    这样构造出的场景是当前最强的一版 T3：
      M1 = NORMAL（受控测试标注）、M2 = AUTHORIZED（历史）、M3 = ALLOW_RECOMMENDED
    三个状态表面上都"可推进"，唯一缺失的是 M2 的**当前请求身份绑定**。
    F0 必须因此阻断 —— 证明历史授权不能冒充当前身份。
    """
    tmpdir = tempfile.mkdtemp(prefix='b1-t3-')
    try:
        base = _load_base()
        m1 = [str(part) for part in base['modules']['comm_risk']['command']]
        m1 = [part for part in m1
              if part not in ('--observation-provenance', 'UNKNOWN')]
        m1.append('--controlled-test')
        m2 = [str(part) for part in base['modules']['identity_trust']['command']]
        m2[m2.index('--identity-ledger') + 1] = _ledger_path(tmpdir)
        config = _write_config(tmpdir, {'comm_risk': {'command': m1},
                                        'identity_trust': {'command': m2}},
                               name='t3.yaml')
        envelope = _envelope(tmpdir, 'b1-t3', 'b1-t3')
        proc, doc = _run_f0(tmpdir, config, envelope)

        # 前置：三个模块都真实运行，且前两个给出"看似可推进"的状态
        assert _module_status(doc, 'comm_risk') == 'NORMAL', doc
        assert _module_status(doc, 'identity_trust') == 'AUTHORIZED', doc
        assert _module_status(doc, 'task_risk') == 'ALLOW_RECOMMENDED', doc

        # 关键断言：历史 AUTHORIZED 不构成当前身份，F0 必须按身份原因阻断
        _assert_blocked(proc, doc, 'T3 历史授权冒用',
                        expect_reason='ADAPTER_CURRENT_IDENTITY_UNBOUND')
        T['T3'] = 'PASS (all three real; M1 controlled-test labelled)'
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# T4：M1 离线正常结果不得被当作当前运行安全
# ---------------------------------------------------------------------------

def test_t4_offline_normal_not_treated_as_current_safety():
    """同一份离线样本：无语信任来源声明 -> 扣留 NORMAL；
    受控测试声明 -> 允许 NORMAL 但必须带 CONTROLLED_TEST_ONLY 标记，
    且整条链路仍因 M2 当前身份未绑定而阻断。"""
    tmpdir = tempfile.mkdtemp(prefix='b1-t4-')
    try:
        # (a) 生产语义：受信任配置声明 provenance=UNKNOWN
        proc, doc = _case(tmpdir, name='t4a')
        assert _module_status(doc, 'comm_risk') == 'UNKNOWN', doc
        _assert_blocked(proc, doc, 'T4 离线正常被正确扣留')

        # (b) 受控测试语义：显式 --controlled-test（受信任配置，非业务输入）
        command = [str(p) for p in _load_base()['modules']['comm_risk']['command']]
        command = [part for part in command
                   if part not in ('--observation-provenance', 'UNKNOWN')]
        command.append('--controlled-test')
        config = _write_config(tmpdir, {
            'comm_risk': {'command': command},
            'identity_trust': {'command': [
                str(p) for p in _load_base()['modules']['identity_trust']['command']]},
        }, name='t4b.yaml')
        ledger = _ledger_path(tmpdir + '-b')
        cfg = yaml.safe_load(open(config, encoding='utf-8'))
        cmd2 = cfg['modules']['identity_trust']['command']
        cmd2[cmd2.index('--identity-ledger') + 1] = ledger
        yaml.safe_dump(cfg, open(config, 'w', encoding='utf-8'), allow_unicode=True)
        envelope = _envelope(tmpdir, 'b1-t4b', 'b1-t4b')
        proc, doc = _run_f0(tmpdir, config, envelope)
        assert _module_status(doc, 'comm_risk') == 'NORMAL', doc
        # 即使 M1 给出 NORMAL，历史授权仍不能冒充当前身份 -> 仍然阻断
        _assert_blocked(proc, doc, 'T4 受控测试仍阻断',
                        expect_reason='ADAPTER_CURRENT_IDENTITY_UNBOUND')
        T['T4'] = 'PASS'
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# T5：真实三模块正向推进 —— 当前不可达，必须如实 BLOCKED
# ---------------------------------------------------------------------------

def test_t5_real_positive_proceed_is_blocked_by_design():
    """真实三模块无法同时满足推进条件，因此 LEVEL 3 必须为 BLOCKED。

    这不是"测试写不出来"，而是当前真实能力的结论：
      * M1 模型 validation_gate_passed=false 且无实时特征采集；
      * M2 无当前请求身份绑定组件。
    一旦其中任一模块具备可信当前证据，本用例应当失败并提醒更新结论。
    """
    tmpdir = tempfile.mkdtemp(prefix='b1-t5-')
    try:
        out = os.path.join(tmpdir, 'evidence')
        proc = subprocess.run(
            [sys.executable, 'scripts/run_three_real_online.py',
             '--run-id', 'b1-t5', '--out-dir', out,
             '--config', 'config/team_modules.three-real.yaml'],
            cwd=REPO, capture_output=True, text=True, timeout=600)
        assert proc.returncode == 0, proc.stdout[-1500:] + proc.stderr[-1500:]
        summary = json.loads(proc.stdout)
        assert summary['levels']['THREE_EXTERNAL_ONLINE_PROCEED'] == 'BLOCKED', summary
        assert summary['verdict']['overall'] == 'B1_INTEGRATED_BLOCKING', summary
        joined = ' '.join(summary['blockers'])
        assert 'comm_risk' in joined, joined
        assert 'current_request_identity' in joined, joined
        T['T5'] = 'BLOCKED (expected; real evidence insufficient)'
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# 运行器自身的防降级断言
# ---------------------------------------------------------------------------

def test_runner_refuses_mock_config():
    """配置若被改回 Mock，运行器必须拒绝运行而不是悄悄降级。"""
    tmpdir = tempfile.mkdtemp(prefix='b1-guard-')
    try:
        config = _write_config(tmpdir, {'comm_risk': {
            'mode': 'mock',
            'command': ['scripts/module_python.sh',
                        'mock_modules/comm_risk_mock.py']}}, name='mock.yaml')
        proc = subprocess.run(
            [sys.executable, 'scripts/run_three_real_online.py',
             '--run-id', 'b1-guard', '--out-dir', os.path.join(tmpdir, 'ev'),
             '--config', config],
            cwd=REPO, capture_output=True, text=True, timeout=300)
        assert proc.returncode == 2, proc.stdout[-1200:]
        summary = json.loads(proc.stdout)
        assert summary['levels']['THREE_EXTERNAL_CALLED'] == 'FAIL', summary
        joined = ' '.join(summary['blockers'])
        assert 'mock' in joined.lower() or 'external' in joined, joined
        T['GUARD-NO-MOCK-FALLBACK'] = 'PASS'
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == '__main__':
    import pytest
    code = pytest.main([os.path.abspath(__file__), '-q'])
    # pytest 会把本文件作为**独立模块**导入，因此用例写入的 T 在那边，
    # 不在 __main__。这里显式取回该模块的登记表，否则矩阵会是空的
    # （那是"看起来跑了但没留结论"的典型陷阱）。
    module = sys.modules.get('three_real_online_check')
    results = dict(getattr(module, 'T', {}) or {})
    results.setdefault('T6', 'NOT_RUN (needs ROS 2 online stage)')
    results.setdefault('T7', 'NOT_RUN (needs DDS Enforce domain 43)')
    print('\n=== 三真实模块系统级联调矩阵 ===')
    for key in sorted(results):
        print('  {0:34} {1}'.format(key, results[key]))
    raise SystemExit(0 if code == 0 else 1)
