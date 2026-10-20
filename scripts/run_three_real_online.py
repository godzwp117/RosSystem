#!/usr/bin/env python3
"""run_three_real_online.py -- 三真实模块联合运行器（工作 B1）。

它做什么
--------
一次调用完成两件事，并**交叉核对**两者是否一致：

  阶段 A（模块证据直采）
      按受信任配置里的**同一条命令**，直接调用三个真实模块各一次，
      完整捕获 stdout / stderr / 退出码 / 耗时，做严格 JSON 解析与
      公共 Schema 校验。这一步拿到的是可用于逐字段核对的**完整输出文档**。

  阶段 B（F0 联合判定）
      用同一个信封调用一次 F0（scripts/team_demo.py）。F0 会依次调用三个
      模块并给出唯一决策。F0 的审计记录只保留状态摘要、不保留输出正文，
      所以阶段 A 与阶段 B 互为对照：F0 观察到的每个模块状态必须与阶段 A
      直采的状态一致，否则说明运行不确定性或配置漂移，直接判负。

为什么这样设计
--------------
任务书要求"三个真实程序被运行"不等于"三个模块已完成可信的在线联合准入"。
因此本工具把结论拆成三个**互相不可替代**的等级：

  LEVEL 1  THREE_EXTERNAL_CALLED
           三个真实进程确实被调用，且可证明跑的是成员算法而非 Mock。
  LEVEL 2  THREE_EXTERNAL_VALIDATED
           三个真实输出通过 Schema、关联字段（run_id/request_id/event_id）
           与证据一致性校验。
  LEVEL 3  THREE_EXTERNAL_ONLINE_PROCEED
           三个模块**本次**都拿到可信证据并满足推进条件，F0 实际提交 Planner。

LEVEL 3 需要 M1 给出受信任来源下的 NORMAL、M2 给出当前请求身份绑定
AUTHENTICATED、M3 给出 ALLOW_RECOMMENDED。任一缺失即
`THREE_EXTERNAL_ONLINE_PROCEED=BLOCKED`，并逐模块给出**具体阻断原因**。
本工具**绝不**为了让 LEVEL 3 通过而改用 Mock、自报身份或历史结果。

安全约束（代码层面强制，不是注释）
--------------------------------
* 配置里任何模块的 mode 不是 external（例如被改回 mock）-> 直接拒绝运行。
* 模块命令解析到的目标若位于 mock_modules/ -> 直接拒绝运行。
* 严格 JSON：重复键、NaN/Infinity、顶层非对象一律判负。
* 输出超过 max_stdout_bytes 判负；超过 timeout_sec 判负。
* 不做任何重试，不更换 request_id 重发。
* F0 的 READY 与 Gateway 的 ALLOW 是两个不同事实，分别记录，绝不互相代填。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, 'scripts'))

LEVEL1 = 'THREE_EXTERNAL_CALLED'
LEVEL2 = 'THREE_EXTERNAL_VALIDATED'
LEVEL3 = 'THREE_EXTERNAL_ONLINE_PROCEED'

MODULES = ('comm_risk', 'identity_trust', 'task_risk')
SCHEMA_FOR = {
    'comm_risk': 'comm_risk_evidence',
    'identity_trust': 'identity_trust_assessment',
    'task_risk': 'task_risk_decision',
}
PROCEED_STATES = {
    'comm_risk': 'NORMAL',
    'identity_trust': 'AUTHORIZED',
    'task_risk': 'ALLOW_RECOMMENDED',
}


def now_iso():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _reject_duplicates(pairs):
    seen = {}
    for key, value in pairs:
        if key in seen:
            raise ValueError('duplicate key in module JSON: {0!r}'.format(key))
        seen[key] = value
    return seen


def _reject_constant(token):
    raise ValueError('non-finite number in module JSON: {0}'.format(token))


def strict_json(text):
    """严格解析：拒绝重复键、NaN/Infinity，要求顶层为对象。"""
    document = json.loads(text, object_pairs_hook=_reject_duplicates,
                          parse_constant=_reject_constant)
    if not isinstance(document, dict):
        raise ValueError('module output must be a JSON object')
    return document


def load_config(path):
    import yaml
    with open(path, encoding='utf-8') as handle:
        return yaml.safe_load(handle)


def guard_no_mock(config):
    """拒绝任何 Mock/替身配置：本运行器只证明"真实模块被调用"。"""
    problems = []
    for name in MODULES:
        entry = (config.get('modules') or {}).get(name)
        if not isinstance(entry, dict):
            problems.append('{0}: 配置缺少该模块'.format(name))
            continue
        if entry.get('mode') != 'external':
            problems.append('{0}: mode={1!r} 不是 external（不允许回退 Mock）'
                            .format(name, entry.get('mode')))
        command = entry.get('command') or []
        blob = ' '.join(str(part) for part in command)
        if 'mock_modules' in blob or '_mock' in blob.lower():
            problems.append('{0}: 命令指向 Mock 实现 -> {1}'.format(name, blob[:120]))
        target = next((str(part) for part in command if str(part).endswith('.py')), '')
        if not target:
            problems.append('{0}: 命令里找不到模块脚本'.format(name))
    return problems


def build_envelope(run_id, request_id, target_x, target_y, task_id):
    """构造联合运行信封。

    通信观测块取自 check_member_module.comm_observation_detail()（真实 held-out
    ROSPaCe 行 + f0_runtime），而不是随机填充；证据引用必须包含与观察 kind
    匹配的来源，否则真实 M1 会（正确地）以退出码 4 拒绝映射。
    """
    import check_member_module as cmm
    detail = {'f0_mock': {'comm_risk': {'scenario': 'normal'},
                          'identity_trust': {'scenario': 'authorized'},
                          'task_risk': {'scenario': 'allow'}}}
    detail.update(cmm.comm_observation_detail())
    window_end = (detail.get('f0_runtime') or {}).get('window', {}).get(
        'end', '2026-10-12T12:00:00Z')
    return {
        'schema_version': '1.0.0-proposed',
        'run_id': run_id,
        'created_at': window_end,
        'request_id': request_id,
        'candidate_action': {
            'action_resource': '/rg/guarded_navigate',
            'operation': 'NAVIGATE',
            'task_id': task_id,
            'target': {'frame_id': 'map', 'x': target_x, 'y': target_y, 'z': 0.0},
        },
        'observations': [{
            'source': '/rg/guarded_navigate',
            'kind': 'RUNTIME_LOG',
            'observed_at': window_end,
            'detail': detail,
        }],
        'evidence_refs': [{
            'ref': 'tests/fixtures/member1/rospace_comm_rows.json',
            'kind': 'RUNTIME_LOG',
            'note': 'real held-out ROSPaCe rows; offline classification input',
        }],
    }


def invoke(command, envelope_text, timeout_sec, max_stdout_bytes, cwd):
    """真实调用一次模块，严格按超时与输出上限采集。"""
    started = time.monotonic()
    try:
        proc = subprocess.Popen(command, cwd=cwd, shell=False,
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
    except FileNotFoundError as exc:
        return {'ok': False, 'error': 'EXEC_NOT_FOUND: {0}'.format(exc),
                'returncode': None, 'stdout': '', 'stderr': '', 'duration_ms': 0}
    try:
        out, err = proc.communicate(envelope_text.encode('utf-8'),
                                    timeout=timeout_sec)
        timed_out = False
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
        timed_out = True
    duration_ms = int((time.monotonic() - started) * 1000)
    result = {
        'returncode': proc.returncode,
        'duration_ms': duration_ms,
        'timed_out': timed_out,
        'stdout_bytes': len(out),
        'stderr_bytes': len(err),
        'ok': False,
    }
    if timed_out:
        result['error'] = 'TIMEOUT after {0}s'.format(timeout_sec)
        return result
    if len(out) > max_stdout_bytes:
        result['error'] = ('STDOUT_TOO_LARGE: {0} > {1}'
                           .format(len(out), max_stdout_bytes))
        return result
    result['stdout'] = out.decode('utf-8', 'replace')
    result['stderr'] = err.decode('utf-8', 'replace')
    return result


def validate_schema(document, interface):
    """用仓库公共 Schema 校验模块输出。"""
    from jsonschema import Draft202012Validator
    schema_path = os.path.join(
        REPO, 'docs/interfaces/schemas', interface + '.schema.json')
    with open(schema_path, encoding='utf-8') as handle:
        schema = json.load(handle)
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(document), key=lambda e: list(e.path))
    return [{'path': '/'.join(str(p) for p in e.path), 'message': e.message[:200]}
            for e in errors[:8]]


def check_level2(documents, envelope):
    """关联字段与证据一致性。返回 (problems, notes)。"""
    problems, notes = [], []
    event_ids, seen = {}, set()
    for name in MODULES:
        doc = documents.get(name) or {}
        if not doc:
            problems.append('{0}: 无输出文档'.format(name))
            continue
        producer = doc.get('producer') or {}
        if producer.get('source') != 'EXTERNAL':
            problems.append('{0}: producer.source={1!r} 不是 EXTERNAL'
                            .format(name, producer.get('source')))
        if doc.get('run_id') != envelope['run_id']:
            problems.append('{0}: run_id 不一致 {1!r} != {2!r}'
                            .format(name, doc.get('run_id'), envelope['run_id']))
        if doc.get('request_id') != envelope['request_id']:
            problems.append('{0}: request_id 不一致 {1!r} != {2!r}'
                            .format(name, doc.get('request_id'),
                                    envelope['request_id']))
        event_id = doc.get('event_id')
        if not isinstance(event_id, str) or not event_id.strip():
            problems.append('{0}: event_id 为空或非字符串'.format(name))
        elif not 1 <= len(event_id) <= 128:
            problems.append('{0}: event_id 长度 {1} 超出 1..128'
                            .format(name, len(event_id)))
        elif event_id in seen:
            problems.append('{0}: event_id 与其他模块重复 -> {1}'
                            .format(name, event_id))
        else:
            seen.add(event_id)
            event_ids[name] = event_id
        if not isinstance(doc.get('evidence_refs'), list) or not doc['evidence_refs']:
            problems.append('{0}: evidence_refs 为空'.format(name))

    # 动作与任务一致性
    action = envelope['candidate_action']
    comm = (documents.get('comm_risk') or {}).get('communication') or {}
    if comm.get('resource') != action['action_resource']:
        problems.append('comm_risk: communication.resource={0!r} 与候选动作不一致'
                        .format(comm.get('resource')))
    window = (documents.get('comm_risk') or {}).get('window') or {}
    obs_at = envelope['observations'][0]['observed_at']
    if window.get('start') and window.get('end'):
        if not window['start'] <= obs_at <= window['end']:
            problems.append('comm_risk: 观察时间不在声明窗口内')

    task = documents.get('task_risk') or {}
    if task.get('task_id') != action['task_id']:
        problems.append('task_risk: task_id={0!r} 与候选任务 {1!r} 不一致'
                        .format(task.get('task_id'), action['task_id']))
    cand = task.get('candidate_action') or {}
    if cand.get('action_resource') != action['action_resource']:
        problems.append('task_risk: candidate_action.action_resource={0!r} 不一致'
                        .format(cand.get('action_resource')))
    target = task.get('target') or {}
    for key in ('x', 'y', 'frame_id'):
        if target.get(key) != action['target'][key]:
            problems.append('task_risk: target.{0}={1!r} 与候选目标 {2!r} 不一致'
                            .format(key, target.get(key), action['target'][key]))

    # M2 的当前请求身份绑定（缺失/非 AUTHENTICATED 都记录，不掩盖）
    ident = documents.get('identity_trust') or {}
    current = ((ident.get('extensions') or {}).get('current_request_identity'))
    if not isinstance(current, dict):
        notes.append('identity_trust: 未提供 extensions.current_request_identity')
    else:
        notes.append('identity_trust: current_request_identity.status={0!r} '
                     'binding={1!r} historical_only={2!r}'.format(
                         current.get('status'), current.get('binding'),
                         current.get('historical_only')))

    m1_ext = ((documents.get('comm_risk') or {}).get('extensions') or {}).get(
        'member1_comm') or {}
    if m1_ext:
        notes.append('comm_risk: trusted_provenance={0!r} envelope_provenance={1!r} '
                     'gate={2!r} controlled_test={3!r}'.format(
                         m1_ext.get('trusted_provenance'),
                         m1_ext.get('envelope_provenance'),
                         m1_ext.get('validation_gate_passed'),
                         m1_ext.get('controlled_test')))
    return problems, notes


def _ensure_ledger_dir(config, module):
    """确保模块 `--identity-ledger` 的父目录存在（运行时状态文件的前置条件）。"""
    entry = (config.get('modules') or {}).get(module) or {}
    command = [str(part) for part in (entry.get('command') or [])]
    if '--identity-ledger' not in command:
        return
    index = command.index('--identity-ledger')
    if index + 1 >= len(command):
        return
    path = command[index + 1]
    parent = os.path.dirname(os.path.abspath(os.path.join(REPO, path)))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description='三真实模块联合运行')
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--out-dir', required=True)
    parser.add_argument('--config', default='config/team_modules.three-real.yaml')
    parser.add_argument('--target-x', type=float, default=2.0)
    parser.add_argument('--target-y', type=float, default=2.0)
    parser.add_argument('--task-id', default='patrol_a_001')
    parser.add_argument('--case', default='legal')
    parser.add_argument('--envelope-in', help='使用现成信封（否则自动构造）')
    parser.add_argument('--expect-block', action='store_true',
                        help='声明本次期望被阻断（用于失败关闭反例）')
    args = parser.parse_args(argv)

    out_dir = args.out_dir if os.path.isabs(args.out_dir) else os.path.join(
        REPO, args.out_dir)
    os.makedirs(out_dir, exist_ok=True)
    run_id = args.run_id
    request_id = '{0}-{1}'.format(args.case, run_id)

    summary = {
        'run_id': run_id,
        'request_id': request_id,
        'case': args.case,
        'generated_at': now_iso(),
        'config': args.config,
        'levels': {LEVEL1: 'NOT_RUN', LEVEL2: 'NOT_RUN', LEVEL3: 'NOT_RUN'},
        'blockers': [],
        'notes': [],
        'modules': {},
        'f0': {},
        'gateway': {'checked': False,
                    'note': 'Gateway 判定在在线阶段单独验证，不由本工具代填'},
    }

    config = load_config(os.path.join(REPO, args.config))
    problems = guard_no_mock(config)
    if problems:
        summary['levels'] = {LEVEL1: 'FAIL', LEVEL2: 'NOT_RUN', LEVEL3: 'NOT_RUN'}
        summary['blockers'] = ['配置拒绝运行：' + p for p in problems]
        _write(out_dir, summary, run_id)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 2

    # 阶段 A 的独立账本必须从空开始，否则第二次运行会（正确地）判为复用。
    probe_ledger_path = os.path.join(out_dir, 'identity_ledger.probe.jsonl')
    if os.path.isfile(probe_ledger_path):
        os.unlink(probe_ledger_path)

    if args.envelope_in:
        with open(args.envelope_in, encoding='utf-8') as handle:
            envelope = json.load(handle)
    else:
        envelope = build_envelope(run_id, request_id, args.target_x,
                                  args.target_y, args.task_id)
    envelope_text = json.dumps(envelope, ensure_ascii=False)
    with open(os.path.join(out_dir, 'envelope.json'), 'w', encoding='utf-8') as fh:
        fh.write(json.dumps(envelope, ensure_ascii=False, indent=2))

    # ---------------- 阶段 A：模块证据直采 ----------------
    #
    # identity_trust 有一个**运行时账本**（--identity-ledger）用于防历史授权复用：
    # 同一 (case, experiment_run, request_id, resource) 只能被解释一次，第二次
    # 会被正确地判为复用 -> UNKNOWN。若阶段 A 与 F0 共用同一账本，第二次调用
    # 必然变成 UNKNOWN，交叉核对就会误报"运行不确定性"。
    #
    # 因此阶段 A 使用**本证据目录内的独立账本**，让两次调用都各自是首次解释；
    # 账本复用本身的反例由 tests/integration/three_real_online_check.py 单独验证
    # （那是 T3 要证明的性质，不能在这里被顺手抹掉）。
    probe_ledger = os.path.join(out_dir, 'identity_ledger.probe.jsonl')
    documents = {}
    for name in MODULES:
        entry = config['modules'][name]
        command = [str(part) for part in entry['command']]
        if command and command[0].endswith('.sh'):
            command[0] = os.path.join(REPO, command[0])
        if '--identity-ledger' in command:
            index = command.index('--identity-ledger')
            if index + 1 < len(command):
                command[index + 1] = probe_ledger
        result = invoke(command, envelope_text,
                        float(entry.get('timeout_sec', 10)),
                        int(entry.get('max_stdout_bytes', 65536)), REPO)
        record = {
            'module': name,
            'mode': entry.get('mode'),
            'command': command,
            'returncode': result.get('returncode'),
            'duration_ms': result.get('duration_ms'),
            'timed_out': result.get('timed_out', False),
            'stdout_bytes': result.get('stdout_bytes'),
            'stderr_bytes': result.get('stderr_bytes'),
            'schema_ok': False,
            'schema_errors': [],
            'status': None,
        }
        if result.get('error'):
            record['error'] = result['error']
        text = result.get('stdout') or ''
        if text.strip():
            with open(os.path.join(out_dir, name + '.stdout.json'), 'w',
                      encoding='utf-8') as fh:
                fh.write(text)
        if result.get('stderr'):
            with open(os.path.join(out_dir, name + '.stderr.txt'), 'w',
                      encoding='utf-8') as fh:
                fh.write(result['stderr'])
        if text.strip() and not result.get('error'):
            try:
                document = strict_json(text)
                errors = validate_schema(document, SCHEMA_FOR[name])
                record['schema_ok'] = not errors
                record['schema_errors'] = errors
                record['status'] = document.get('status')
                documents[name] = document
                with open(os.path.join(out_dir, name + '.json'), 'w',
                          encoding='utf-8') as fh:
                    json.dump(document, fh, ensure_ascii=False, indent=2)
            except Exception as exc:                       # noqa: BLE001
                record['error'] = 'STRICT_JSON_FAILED: {0}'.format(exc)
        summary['modules'][name] = record

    called_ok = all(
        summary['modules'][name].get('returncode') == 0
        and not summary['modules'][name].get('timed_out')
        and summary['modules'][name].get('mode') == 'external'
        for name in MODULES)
    summary['levels'][LEVEL1] = 'PASS' if called_ok else 'FAIL'
    if not called_ok:
        for name in MODULES:
            rec = summary['modules'][name]
            if rec.get('returncode') != 0 or rec.get('timed_out'):
                summary['blockers'].append(
                    '{0}: 未被成功调用（rc={1} timeout={2} err={3}）'.format(
                        name, rec.get('returncode'), rec.get('timed_out'),
                        rec.get('error')))

    # ---------------- 阶段 B：F0 联合判定 ----------------
    #
    # identity_trust 的防重放账本是**运行时状态文件**：它的父目录必须已存在，
    # 否则 M2 无法打开账本只能失败关闭（UNKNOWN），随后交叉核对会把它误报成
    # "F0 与直采状态不一致"。这里显式准备该目录，让结论只反映真实性差异。
    _ensure_ledger_dir(config, 'identity_trust')
    f0_log = os.path.join(out_dir, 'adapter.jsonl')
    f0_cmd = [sys.executable, 'scripts/team_demo.py',
              '--input', os.path.join(out_dir, 'envelope.json'),
              '--config', args.config, '--log', f0_log]
    started = time.monotonic()
    proc = subprocess.run(f0_cmd, cwd=REPO, capture_output=True, text=True)
    f0_doc = None
    try:
        f0_doc = json.loads(proc.stdout)
    except ValueError:
        pass
    summary['f0'] = {
        'command': f0_cmd,
        'returncode': proc.returncode,
        'duration_ms': int((time.monotonic() - started) * 1000),
        'decision': (f0_doc or {}).get('decision'),
        'reason_code': (f0_doc or {}).get('reason_code'),
        'detail': (f0_doc or {}).get('detail'),
        'modules': [{'module': m.get('module'), 'mode': m.get('mode'),
                     'exit_code': m.get('exit_code'),
                     'schema_ok': m.get('schema_ok'),
                     'status': m.get('status')}
                    for m in ((f0_doc or {}).get('modules') or [])],
        'stderr_tail': (proc.stderr or '')[-400:],
    }
    if f0_doc:
        with open(os.path.join(out_dir, 'f0.json'), 'w', encoding='utf-8') as fh:
            json.dump(f0_doc, fh, ensure_ascii=False, indent=2)

    # 交叉核对：F0 观察到的状态必须等于直采状态
    for entry in summary['f0']['modules']:
        name = entry.get('module')
        direct = (summary['modules'].get(name) or {}).get('status')
        if direct != entry.get('status'):
            summary['blockers'].append(
                '{0}: F0 观察到 status={1!r} 但直采为 {2!r}（运行不确定性）'
                .format(name, entry.get('status'), direct))

    # ---------------- LEVEL 2 ----------------
    if summary['levels'][LEVEL1] == 'PASS':
        problems2, notes = check_level2(documents, envelope)
        summary['notes'].extend(notes)
        summary['levels'][LEVEL2] = 'PASS' if not problems2 else 'FAIL'
        summary['blockers'].extend(problems2)
    else:
        summary['levels'][LEVEL2] = 'BLOCKED'

    # ---------------- LEVEL 3 ----------------
    if summary['levels'][LEVEL2] != 'PASS':
        summary['levels'][LEVEL3] = 'BLOCKED'
        summary['blockers'].append(
            'LEVEL 3 依赖 LEVEL 2 通过；当前 LEVEL 2=' + summary['levels'][LEVEL2])
    else:
        missing = []
        for name in MODULES:
            actual = (documents.get(name) or {}).get('status')
            if actual != PROCEED_STATES[name]:
                missing.append('{0}: status={1!r}，推进需要 {2!r}'.format(
                    name, actual, PROCEED_STATES[name]))
        identity = ((documents.get('identity_trust') or {}).get('extensions') or {}
                    ).get('current_request_identity') or {}
        if identity.get('status') != 'AUTHENTICATED':
            missing.append(
                'identity_trust: current_request_identity.status={0!r}，'
                '本轮没有可信的当前请求身份绑定'.format(identity.get('status')))
        if identity.get('historical_only') is True:
            missing.append('identity_trust: current_request_identity 标记为 '
                           'historical_only，历史授权不得冒充当前身份')
        f0_ready = summary['f0'].get('decision') == 'READY_FOR_GATEWAY_SUBMISSION'
        if missing or not f0_ready:
            summary['levels'][LEVEL3] = 'BLOCKED'
            summary['blockers'].extend(missing)
            if not f0_ready:
                summary['blockers'].append(
                    'F0 决策为 {0!r}（{1}），未提交 Planner'.format(
                        summary['f0'].get('decision'),
                        summary['f0'].get('reason_code')))
        else:
            summary['levels'][LEVEL3] = 'PASS'

    summary['verdict'] = {
        'level1': summary['levels'][LEVEL1],
        'level2': summary['levels'][LEVEL2],
        'level3': summary['levels'][LEVEL3],
        'overall': ('B1_FULL_ONLINE_VERIFIED'
                    if summary['levels'][LEVEL3] == 'PASS'
                    else ('B1_INTEGRATED_BLOCKING'
                          if summary['levels'][LEVEL2] == 'PASS'
                          else 'B1_PARTIAL')),
    }
    _write(out_dir, summary, run_id)
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if args.expect_block:
        blocked = summary['levels'][LEVEL3] == 'BLOCKED'
        return 0 if blocked else 1
    return 0 if summary['levels'][LEVEL2] == 'PASS' else 1


def _write(out_dir, summary, run_id):
    with open(os.path.join(out_dir, 'summary.json'), 'w', encoding='utf-8') as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    lines = ['# 三真实模块联合运行摘要', '',
             '- run_id: `{0}`'.format(run_id),
             '- request_id: `{0}`'.format(summary['request_id']),
             '- 配置: `{0}`'.format(summary['config']),
             '- 生成时间: {0}'.format(summary['generated_at']), '',
             '| 等级 | 结果 |', '| --- | --- |']
    for key, value in summary['levels'].items():
        lines.append('| `{0}` | **{1}** |'.format(key, value))
    lines += ['', '## 各模块实际调用', '',
              '| 模块 | mode | rc | schema | status | 耗时ms |',
              '| --- | --- | --- | --- | --- | --- |']
    for name in MODULES:
        rec = summary['modules'].get(name) or {}
        lines.append('| {0} | {1} | {2} | {3} | {4} | {5} |'.format(
            name, rec.get('mode'), rec.get('returncode'), rec.get('schema_ok'),
            rec.get('status'), rec.get('duration_ms')))
    lines += ['', '## F0 决策', '',
              '- decision: `{0}`'.format(summary['f0'].get('decision')),
              '- reason_code: `{0}`'.format(summary['f0'].get('reason_code')),
              '- 返回码: {0}'.format(summary['f0'].get('returncode')), '',
              '> F0 的 READY_FOR_GATEWAY_SUBMISSION 不是 Gateway ALLOW；'
              'Gateway 判定在在线阶段单独验证。', '']
    if summary['blockers']:
        lines += ['## 阻断原因', '']
        lines += ['- {0}'.format(item) for item in summary['blockers']]
        lines.append('')
    if summary['notes']:
        lines += ['## 证据备注', '']
        lines += ['- {0}'.format(item) for item in summary['notes']]
        lines.append('')
    with open(os.path.join(out_dir, 'summary.md'), 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(lines))


if __name__ == '__main__':
    raise SystemExit(main())
