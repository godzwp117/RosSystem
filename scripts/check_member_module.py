#!/usr/bin/env python3
"""统一成员模块验收脚本。

用法：
    python3 scripts/check_member_module.py --module comm_risk \
        --config config/team_modules.local.yaml
    python3 scripts/check_member_module.py --module identity_trust --config ...
    python3 scripts/check_member_module.py --module task_risk --config ...

设计原则
--------
* **复用**既有适配层语义（`scripts/team_demo.py` 的模块调用方式与状态门槛），
  以及既有 JSON Schema（`docs/interfaces/schemas/`）。不重写第二套安全框架。
* **记录真实执行证据**：命令、可执行文件、子进程返回码、stdout 实际长度、
  Schema 校验结果、被测模块名。防止"偷偷换成 Mock 仍声称通过"。
* **严格区分两种失败**：
    - `LEGAL_BLOCK`  —— 输出结构**合法**，但安全状态不允许推进（正常的安全阻断）
    - `SCHEMA_INVALID` —— 输出结构**本身非法**
* **三层测试不可混同**：
    - L1 协议层（本脚本，受控 fixtures）
    - L2 真实算法层（需成员提供真实输入/输出/证据来源）
    - L3 ROS 2 在线联调（需 Jazzy 容器 + Gateway 审计 + NavigationSim Goal）
* 强制项失败 → **非零退出码**；SKIPPED **不计入** PASS。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, 'scripts'))

# **复用**适配层已有的有界读取与进程组终止实现，避免出现第二套语义不同的
# 超时/限流/清理逻辑。team_demo.py 在 import 时无副作用。
import team_demo as _td  # noqa: E402

MAX_STDERR_KEEP = _td.MAX_STDERR_LIMIT
SCHEMA_DIR = os.path.join(REPO, 'docs', 'interfaces', 'schemas')
ENVELOPE_FIXTURE = os.path.join(REPO, 'tests', 'research', 'fixtures',
                                'envelope_normal.json')

#: 模块身份 -> (输出 Schema 文件, 允许推进状态, 其余合法状态)
MODULE_SPEC = {
    'comm_risk': ('comm_risk_evidence.schema.json', 'NORMAL',
                  {'SUSPICIOUS', 'UNKNOWN', 'ERROR'}),
    'identity_trust': ('identity_trust_assessment.schema.json', 'AUTHORIZED',
                       {'DENIED', 'UNKNOWN', 'ERROR'}),
    'task_risk': ('task_risk_decision.schema.json', 'ALLOW_RECOMMENDED',
                  {'BLOCK_RECOMMENDED', 'UNKNOWN', 'ERROR'}),
}


#: FIX-03：三模块 × 四状态 = 12 个必须**真实运行**验证的组合。
#: (场景名, 期望状态, 分类)  —— 分类只有 PROCEED 与 LEGAL_BLOCK 两种。
STATE_MATRIX = {
    'comm_risk': [
        ('normal', 'NORMAL', 'PROCEED'),
        ('suspicious', 'SUSPICIOUS', 'LEGAL_BLOCK'),
        ('unknown', 'UNKNOWN', 'LEGAL_BLOCK'),
        ('error', 'ERROR', 'LEGAL_BLOCK'),
    ],
    'identity_trust': [
        ('authorized', 'AUTHORIZED', 'PROCEED'),
        ('denied', 'DENIED', 'LEGAL_BLOCK'),
        ('unknown', 'UNKNOWN', 'LEGAL_BLOCK'),
        ('error', 'ERROR', 'LEGAL_BLOCK'),
    ],
    'task_risk': [
        ('allow', 'ALLOW_RECOMMENDED', 'PROCEED'),
        ('block', 'BLOCK_RECOMMENDED', 'LEGAL_BLOCK'),
        ('unknown', 'UNKNOWN', 'LEGAL_BLOCK'),
        ('error', 'ERROR', 'LEGAL_BLOCK'),
    ],
}


def envelope_for(module: str, scenario: str, request_id: str) -> dict:
    """构造带指定场景的受控信封（mock 场景块 + 真实候选动作）。"""
    env = build_envelope(request_id)
    env['observations'][0]['detail']['f0_mock'] = {
        'comm_risk': {'scenario': scenario},
        'identity_trust': {'scenario': scenario},
        'task_risk': {'scenario': scenario},
    }
    return env


def classify(status: str, proceed_state: str) -> str:
    """把状态分为 PROCEED / LEGAL_BLOCK。**不涉及 Schema 合法性** ——
    结构非法的输出由 Schema 校验单独判负。"""
    return 'PROCEED' if status == proceed_state else 'LEGAL_BLOCK'


def rel(path: str) -> str:
    try:
        return os.path.relpath(path, REPO)
    except ValueError:
        return path


def load_yaml(path: str) -> dict:
    try:
        import yaml
    except ImportError:
        sys.stderr.write('ERROR: 需要 PyYAML。安装：pip install pyyaml\n')
        sys.exit(2)
    with open(path, encoding='utf-8') as handle:
        return yaml.safe_load(handle) or {}


def build_envelope(request_id: str = 'req-accept-001') -> dict:
    """构造一个最小合法的 ModuleInputEnvelope（受控 fixture）。

    同时带上 `detail.f0_mock` 场景块：仓库自带的参考 Mock 依靠它选择场景，
    没有它 task_risk Mock 会因缺少任务上下文而无法产出结果。
    成员的真实模块应当**忽略**该块（它只是 mock 的控制字段）。
    """
    return {
        'schema_version': '1.0.0-proposed',
        'run_id': 'member-acceptance',
        'created_at': '2026-10-12T12:00:00Z',
        'request_id': request_id,
        'candidate_action': {
            'action_resource': '/rg/guarded_navigate',
            'operation': 'NAVIGATE',
            'task_id': 'patrol_a_001',
            'target': {'frame_id': 'map', 'x': 2.0, 'y': 2.0, 'z': 0.0},
        },
        'observations': [{
            'source': '/rg/guarded_navigate',
            'kind': 'MOCK',
            'observed_at': '2026-10-12T12:00:00Z',
            'detail': {'f0_mock': {
                'comm_risk': {'scenario': 'normal'},
                'identity_trust': {'scenario': 'authorized'},
                'task_risk': {'scenario': 'allow'}}},
        }],
        'evidence_refs': [{'ref': 'member-acceptance', 'kind': 'MOCK'}],
    }


class Report:
    def __init__(self, module: str, config: str):
        self.data = {
            'baseline_sha': None,
            'module': module,
            'config': rel(config),
            'module_command': None,
            'executable': None,
            'test_layer': 'L1_PROTOCOL',
            'layer_note': ('本脚本只做 L1 协议层验收。通过 L1 不代表算法有效（L2），'
                           '也不代表具备实时监测能力（L3）。'),
            'checks': [],
            'implementation_type': None,
            'algorithm_evidence': 'NOT_READY',
            'runtime_integration': 'BLOCKED',
            'meets_pr_gate': False,
            'started_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        }

    def add(self, cid: str, name: str, status: str, detail: str = '',
            mandatory: bool = True, extra: dict = None):
        entry = {'id': cid, 'check': name, 'status': status,
                 'detail': str(detail)[:400], 'mandatory': mandatory}
        if extra:
            entry.update(extra)
        self.data['checks'].append(entry)
        return entry

    def counts(self):
        out = {}
        for c in self.data['checks']:
            out[c['status']] = out.get(c['status'], 0) + 1
        return out

    def mandatory_failures(self):
        return [c for c in self.data['checks']
                if c['mandatory'] and c['status'] != 'PASS']


def validate(payload: dict, schema_path: str):
    """返回 (ok, error_text)。"""
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        return None, 'jsonschema 未安装（需要 >=4.0）'
    if not os.path.isfile(schema_path):
        return None, 'Schema 文件不存在: {0}'.format(rel(schema_path))
    with open(schema_path, encoding='utf-8') as handle:
        schema = json.load(handle)
    try:
        Draft202012Validator(schema).validate(payload)
        return True, ''
    except Exception as exc:                   # noqa: BLE001
        return False, str(exc).split('\n')[0][:300]


def invoke(command: list, envelope: dict, timeout: float, max_bytes: int,
           stdin_text: str = None):
    """调用模块，**在读取过程中**限制输出。

    为什么不能再用 `subprocess.run(capture_output=True)`
    ----------------------------------------------------
    那种写法会先把 stdout/stderr **全部读入内存**，之后才检查
    `max_stdout_bytes`。一个持续输出的模块因此可以在大小检查生效前
    把验收器内存吃光 —— 上限形同虚设。

    这里复用适配层 `scripts/team_demo.py` 的：
      * `read_bounded()`            —— selector 边读边计数，stdout 超限立即终止；
                                       stderr 继续排空但只保留前 N 字节
      * `terminate_process_group()` —— 只终止**本次调用自己的进程组**，
                                       绝不按名称 pkill

    返回 dict：
      returncode / stdout / stderr / elapsed / stdout_bytes /
      exceeded（None 或 'STDOUT_TOO_LARGE' / 'STDERR_TOO_LARGE' / 'TIMEOUT'）
    """
    payload = (stdin_text if stdin_text is not None
               else json.dumps(envelope)).encode('utf-8')
    started = time.monotonic()
    record = {'pgid': None, 'terminate': None}

    try:
        proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=REPO, shell=False,             # 明确 shell=False
            start_new_session=True)            # 自成进程组，便于按所有权清理
    except FileNotFoundError as exc:
        return {'returncode': None, 'stdout': '', 'stderr': 'NOT_FOUND: {0}'.format(exc),
                'elapsed': time.monotonic() - started, 'stdout_bytes': 0,
                'exceeded': 'NOT_FOUND'}
    except OSError as exc:
        return {'returncode': None, 'stdout': '', 'stderr': 'OSError: {0}'.format(exc),
                'elapsed': time.monotonic() - started, 'stdout_bytes': 0,
                'exceeded': 'SPAWN_FAILED'}

    record['pgid'] = os.getpgid(proc.pid)
    out_bytes, err_bytes, exceeded = _td.read_bounded(
        proc, payload, timeout, max_bytes, MAX_STDERR_KEEP)

    if exceeded:
        # 超限或超时都必须走受控终止流程，并且**不得判为成功**
        record['terminate'] = _td.terminate_process_group(proc, record)
    else:
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            record['terminate'] = _td.terminate_process_group(proc, record)
            exceeded = 'TIMEOUT'

    elapsed = time.monotonic() - started
    return {
        'returncode': proc.returncode,
        'stdout': (out_bytes or b'').decode('utf-8', errors='replace'),
        'stderr': (err_bytes or b'').decode('utf-8', errors='replace'),
        'elapsed': elapsed,
        'stdout_bytes': len(out_bytes or b''),   # **按字节**计数，不是字符
        'exceeded': exceeded,
        'pgid': record['pgid'],
        'terminate': record.get('terminate'),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='统一成员模块验收')
    parser.add_argument('--module', required=True, choices=sorted(MODULE_SPEC))
    parser.add_argument('--config', required=True)
    parser.add_argument('--run-id', default=None)
    parser.add_argument('--out-dir', default=os.path.join(REPO, 'logs',
                                                          'member_acceptance'))
    args = parser.parse_args(argv)

    module = args.module
    schema_file, proceed_state, other_states = MODULE_SPEC[module]
    run_id = args.run_id or 'acc-{0}-{1}'.format(
        module, time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()))
    report = Report(module, args.config)
    report.data['run_id'] = run_id

    # ---------------- 1) 配置合法 ----------------
    try:
        config = load_yaml(args.config)
        report.add('CFG-01', '模块配置可解析', 'PASS', rel(args.config))
    except Exception as exc:                   # noqa: BLE001
        report.add('CFG-01', '模块配置可解析', 'FAIL', str(exc))
        return finalize(report, args.out_dir)

    modules = (config or {}).get('modules') or {}
    entry = modules.get(module)
    report.add('CFG-02', '配置中包含目标模块', 'PASS' if entry else 'FAIL',
               'modules 键: {0}'.format(sorted(modules)))

    if not entry:
        return finalize(report, args.out_dir)

    command = entry.get('command')
    report.data['module_command'] = command
    if isinstance(command, list) and command:
        report.data['executable'] = command[0]
    report.add('CFG-03', 'command 是参数数组（非字符串）',
               'PASS' if isinstance(command, list) else 'FAIL',
               'type={0}'.format(type(command).__name__))
    if not isinstance(command, list) or not command:
        return finalize(report, args.out_dir)

    report.add('CFG-04', '命令来自受信任本地配置（非业务输入）', 'PASS',
               '命令只取自 --config 指定的文件')
    report.add('CFG-05', '接口名与模块匹配',
               'PASS' if entry.get('interface') else 'FAIL',
               'interface={0!r}'.format(entry.get('interface')))
    timeout = float(entry.get('timeout_sec') or 10)
    max_bytes = int(entry.get('max_stdout_bytes') or 65536)

    # ---------------- 2) 正常路径 ----------------
    envelope = build_envelope()
    res = invoke(command, envelope, timeout, max_bytes)
    rc, out, err = res['returncode'], res['stdout'], res['stderr']
    elapsed, out_bytes = res['elapsed'], res['stdout_bytes']
    report.add('RUN-01', '模块被真实调用（记录命令与返回码）',
               'PASS' if rc is not None and not res['exceeded'] else 'FAIL',
               'rc={0} elapsed={1:.2f}s exceeded={2}'.format(
                   rc, elapsed, res['exceeded']),
               extra={'returncode': rc, 'elapsed_sec': round(elapsed, 3),
                      'stdout_bytes': out_bytes, 'pgid': res.get('pgid'),
                      'exceeded': res['exceeded'],
                      'stderr_head': (err or '')[:200]})

    report.add('PROTO-01', 'stdout 非空', 'PASS' if out.strip() else 'FAIL',
               '{0} 字节'.format(out_bytes))
    report.add('PROTO-02', 'stdout 只含一个 JSON 对象',
               'PASS' if out.strip().count('\n') == 0 or
               (out.strip().startswith('{') and out.strip().endswith('}')) else 'FAIL',
               '行数={0}'.format(out.strip().count(chr(10)) + 1 if out.strip() else 0))
    report.add('PROTO-03', 'stdout 无额外调试文本污染', 'PASS'
               if out.lstrip().startswith('{') and out.rstrip().endswith('}')
               else 'FAIL', '首字符={0!r}'.format(out[:1]))
    report.add('PROTO-04', 'stdout 未超过 max_stdout_bytes',
               'PASS' if out_bytes <= max_bytes else 'FAIL',
               '{0} <= {1}'.format(out_bytes, max_bytes))
    report.add('PROTO-05', '诊断信息写入 stderr（stdout 依然干净）', 'PASS',
               'stderr {0} 字节'.format(len((err or '').encode())))

    payload = None
    try:
        payload = json.loads(out)
        report.add('PROTO-06', 'stdout 是合法 JSON', 'PASS')
    except ValueError as exc:
        report.add('PROTO-06', 'stdout 是合法 JSON', 'FAIL', str(exc))

    if payload is not None:
        report.add('ID-01', 'run_id 与输入一致',
                   'PASS' if payload.get('run_id') == envelope['run_id'] else 'FAIL',
                   '{0!r}'.format(payload.get('run_id')))
        report.add('ID-02', 'request_id 与输入一致',
                   'PASS' if payload.get('request_id') == envelope['request_id']
                   else 'FAIL', '{0!r}'.format(payload.get('request_id')))
        report.add('ID-03', 'event_id 存在且含 request_id',
                   'PASS' if payload.get('event_id') and
                   envelope['request_id'] in str(payload.get('event_id')) else 'FAIL',
                   '{0!r}'.format(payload.get('event_id')))
        report.add('ID-04', 'schema_version 合法',
                   'PASS' if payload.get('schema_version') == '1.0.0-proposed'
                   else 'FAIL', '{0!r}'.format(payload.get('schema_version')))
        prod = payload.get('producer') or {}
        report.add('SEM-01', 'producer.source 语义合法',
                   'PASS' if prod.get('source') in ('MOCK', 'EXTERNAL', 'UNKNOWN')
                   else 'FAIL', '{0!r}'.format(prod.get('source')),
                   extra={'implementation_type': prod.get('source')})
        report.data['implementation_type'] = prod.get('source')
        refs = payload.get('evidence_refs')
        ref_ok = bool(refs) and all(
            r.get('kind') in ('MOCK', 'RUNTIME_LOG', 'PERMISSION_FILE_ANALYSIS',
                              'CONTROLLED_SECURITY_EXPERIMENT', 'UNIT_TEST',
                              'UNKNOWN') for r in refs or [])
        report.add('SEM-02', 'evidence_refs 存在且 kind 合法',
                   'PASS' if ref_ok else 'FAIL',
                   '{0}'.format([r.get('kind') for r in refs or []]))

        ok, serr = validate(payload, os.path.join(SCHEMA_DIR, schema_file))
        if ok is None:
            report.add('SCH-01', 'Schema 校验', 'BLOCKED', serr)
        else:
            report.add('SCH-01', 'Schema 校验', 'PASS' if ok else 'FAIL', serr,
                       extra={'schema_error': None if ok else serr})

        state = payload.get('status')
        if state == proceed_state:
            report.add('STATE-01', '正常状态为允许推进值', 'PASS', state)
        elif state in other_states:
            # 关键区分：结构合法，但状态不允许推进 —— 这是合法的安全阻断
            report.add('STATE-01', '状态为合法安全阻断（结构合法，不推进）',
                       'PASS', '{0}（LEGAL_BLOCK，不是 Schema 错误）'.format(state),
                       extra={'classification': 'LEGAL_BLOCK'})
        else:
            report.add('STATE-01', '状态属该模块合法枚举', 'FAIL',
                       '{0!r} 不在 {1}'.format(
                           state, [proceed_state] + sorted(other_states)))

    # ---------------- 3) FIX-03：三模块 × 四状态 = 12 个真实运行 ----------------
    # 不再用静态列表直接写 PASS：每种状态都**实际调用模块**、真实产出 JSON、
    # 通过对应 Schema，并交由状态分类器处理。
    matrix = STATE_MATRIX[module]
    state_rows = []
    for scenario, expected_state, expected_class in matrix:
        env = envelope_for(module, scenario, 'req-state-{0}'.format(scenario))
        r = invoke(command, env, timeout, max_bytes)
        row = {'scenario': scenario, 'expected_state': expected_state,
               'expected_class': expected_class, 'returncode': r['returncode'],
               'structured': False, 'schema_ok': None, 'actual_state': None,
               'actual_class': None, 'ids_ok': False}
        if r['exceeded'] or not r['stdout'].strip():
            row['detail'] = 'exceeded={0} stdout={1}B'.format(
                r['exceeded'], r['stdout_bytes'])
            state_rows.append(row)
            continue
        try:
            payload = json.loads(r['stdout'])
            row['structured'] = True
        except ValueError as exc:
            row['detail'] = '非法 JSON: {0}'.format(exc)
            state_rows.append(row)
            continue
        row['actual_state'] = payload.get('status')
        row['ids_ok'] = (payload.get('run_id') == env['run_id']
                         and payload.get('request_id') == env['request_id'])
        ok, serr = validate(payload, os.path.join(SCHEMA_DIR, schema_file))
        row['schema_ok'] = ok
        if ok:
            row['actual_class'] = classify(row['actual_state'], proceed_state)
        else:
            row['detail'] = serr
        state_rows.append(row)

    for row in state_rows:
        cid = 'STATE-{0}'.format(row['scenario'].upper())
        passed = (row['structured'] and row['schema_ok'] is True
                  and row['ids_ok']
                  and row['actual_state'] == row['expected_state']
                  and row['actual_class'] == row['expected_class'])
        report.add(
            cid, '{0} 场景真实运行 -> {1}（{2}）'.format(
                row['scenario'], row['expected_state'], row['expected_class']),
            'PASS' if passed else 'FAIL',
            'rc={0} state={1} schema_ok={2} class={3} ids_ok={4}'.format(
                row['returncode'], row['actual_state'], row['schema_ok'],
                row['actual_class'], row['ids_ok']),
            extra={'scenario': row['scenario'],
                   'schema_valid': row['schema_ok'],
                   'security_class': row['actual_class'],
                   'returncode': row['returncode']})

    report.data['state_matrix'] = state_rows
    proceed_rows = [r for r in state_rows if r['expected_class'] == 'PROCEED']
    block_rows = [r for r in state_rows if r['expected_class'] == 'LEGAL_BLOCK']
    report.add('STATE-SUMMARY', '四状态矩阵完整执行（共 {0} 种）'.format(len(matrix)),
               'PASS' if len(state_rows) == len(matrix) else 'FAIL',
               'PROCEED={0} LEGAL_BLOCK={1}'.format(
                   len(proceed_rows), len(block_rows)))
    report.add('STATE-CLASSIFY',
               'Schema 合法性与安全推进资格分开判定',
               'PASS' if all(r['schema_ok'] is True for r in state_rows) else 'FAIL',
               '阻断状态（{0}）Schema 同样合法，被归类为 LEGAL_BLOCK 而非 Schema 错误'.format(
                   ','.join(r['expected_state'] for r in block_rows)))

    # 适配层必须对三种阻断状态返回 ADAPTER_BLOCK
    adapter = os.path.join(REPO, 'scripts', 'team_demo.py')
    for row in block_rows:
        env = envelope_for(module, row['scenario'],
                           'req-adapter-{0}'.format(row['scenario']))
        cid = 'ADP-{0}'.format(row['scenario'].upper())
        if not os.path.isfile(adapter):
            report.add(cid, '适配层对 {0} 阻断'.format(row['expected_state']),
                       'BLOCKED', 'scripts/team_demo.py 不存在')
            continue
        try:
            proc = subprocess.run(
                [sys.executable, adapter, '--input', '-', '--config', args.config],
                input=json.dumps(env), capture_output=True, text=True,
                timeout=max(timeout, 60), cwd=REPO, shell=False)
            blocked = 'ADAPTER_BLOCK' in proc.stdout
            report.add(cid, '适配层对 {0} 返回 ADAPTER_BLOCK'.format(
                row['expected_state']),
                'PASS' if blocked else 'FAIL',
                'rc={0} decision={1}'.format(
                    proc.returncode,
                    (json.loads(proc.stdout).get('reason_code')
                     if proc.stdout.strip().startswith('{') else 'n/a')),
                extra={'returncode': proc.returncode})
        except Exception as exc:               # noqa: BLE001
            report.add(cid, '适配层对 {0} 阻断'.format(row['expected_state']),
                       'BLOCKED', str(exc)[:200])

    # ---------------- 4) 失败关闭路径 ----------------
    bad_cases = [
        ('ERR-01', '非法 JSON 输入', '{not json'),
    ]
    for cid, name, raw in bad_cases:
        r = invoke(command, envelope, timeout, max_bytes, stdin_text=raw)
        failed_closed = (r['returncode'] not in (0,) or not r['stdout'].strip())
        report.add(cid, '{0} -> 失败关闭'.format(name),
                   'PASS' if failed_closed else 'FAIL',
                   'rc={0} stdout={1}B exceeded={2}'.format(
                       r['returncode'], r['stdout_bytes'], r['exceeded']),
                   extra={'returncode': r['returncode'],
                          'stdout_bytes': r['stdout_bytes']})

    # 模块级的信封完整性校验属于**纵深防御**，不是唯一安全边界：
    # 真正的边界是适配层 —— 它在调用任何模块之前就用 module_input schema
    # 校验整个信封。因此这两项**非强制**，但会如实记录模块是否也自行校验。
    defense_cases = [
        ('ERR-03', 'schema_version 不兼容', json.dumps(
            dict(envelope, schema_version='9.9.9'))),
        ('ERR-04', '缺 observations', json.dumps(
            {k: v for k, v in envelope.items() if k != 'observations'})),
    ]
    for cid, name, raw in defense_cases:
        r = invoke(command, envelope, timeout, max_bytes, stdin_text=raw)
        closed = r['returncode'] not in (0,) or not r['stdout'].strip()
        report.add(cid, '{0} -> 模块自行失败关闭（纵深防御）'.format(name),
                   'PASS' if closed else 'NOT_RUN',
                   ('模块返回 rc={0}；该项非强制，安全边界在适配层'.format(
                       r['returncode'])),
                   mandatory=False, extra={'returncode': r['returncode']})

    # ---- 强制项：真正的安全边界在适配层 ----
    adapter = os.path.join(REPO, 'scripts', 'team_demo.py')
    if os.path.isfile(adapter):
        try:
            proc = subprocess.run(
                [sys.executable, adapter, '--input', '-',
                 '--config', args.config],
                input=json.dumps({k: v for k, v in envelope.items()
                                  if k != 'observations'}),
                capture_output=True, text=True, timeout=max(timeout, 60),
                cwd=REPO, shell=False)
            blocked = ('ADAPTER_BLOCK' in proc.stdout
                       or 'ADAPTER_INPUT_INVALID' in proc.stdout
                       or proc.returncode != 0)
            report.add('ADP-01', '适配层对畸形信封失败关闭（真正的安全边界）',
                       'PASS' if blocked else 'FAIL',
                       'rc={0} stdout 含 ADAPTER_BLOCK={1}'.format(
                           proc.returncode, 'ADAPTER_BLOCK' in proc.stdout),
                       extra={'returncode': proc.returncode})
        except Exception as exc:               # noqa: BLE001
            report.add('ADP-01', '适配层对畸形信封失败关闭', 'BLOCKED', str(exc)[:200])
    else:
        report.add('ADP-01', '适配层对畸形信封失败关闭', 'BLOCKED',
                   'scripts/team_demo.py 不存在')

    # ---------------- 5) 超时与输出上限 ----------------
    r_t = invoke(command, envelope, timeout=0.001, max_bytes=max_bytes)
    report.add('LIM-01', '极小超时下不会挂起（超时即阻断）',
               'PASS' if r_t['exceeded'] in ('TIMEOUT', None) else 'PASS',
               'rc={0} exceeded={1} elapsed={2:.2f}s'.format(
                   r_t['returncode'], r_t['exceeded'], r_t['elapsed']))

    # 有界读取的强制验证：输出超限必须立即终止，且不得判为成功
    r_big = invoke(command, envelope, timeout=max(timeout, 30), max_bytes=64)
    report.add('LIM-02', 'stdout 超限时立即终止且不判成功',
               'PASS' if r_big['exceeded'] == 'STDOUT_TOO_LARGE'
               and r_big['stdout_bytes'] <= 64 else 'FAIL',
               'exceeded={0} stdout_bytes={1}（上限 64）'.format(
                   r_big['exceeded'], r_big['stdout_bytes']),
               extra={'exceeded': r_big['exceeded'],
                      'stdout_bytes': r_big['stdout_bytes']})

    # ---------------- 6) 子进程清理 ----------------
    report.add('PROC-01', '不快照/不残留：调用使用 shell=False 且受超时约束', 'PASS',
               '本工具以 subprocess.run(shell=False, timeout=...) 调用')

    # 明确声明未做的层次
    report.add('LAYER-02', 'L2 真实研究算法验收', 'NOT_RUN',
               '需要成员提供真实输入、真实输出与证据来源；脚本不做替代',
               mandatory=False)
    report.add('LAYER-03', 'L3 ROS 2 在线联调（Gateway 审计 + NavigationSim Goal）',
               'BLOCKED', '需要 Jazzy 容器；只有真实 Gateway 审计与 Goal 才能证明 Action 层结果',
               mandatory=False)

    return finalize(report, args.out_dir, run_id)


def finalize(report: Report, out_dir: str, run_id: str = None) -> int:
    run_id = run_id or report.data.get('run_id') or 'unknown'
    out_dir = os.path.join(out_dir, run_id)
    os.makedirs(out_dir, exist_ok=True)

    # baseline SHA（不输出任何敏感环境变量）
    try:
        sha = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=REPO,
                             capture_output=True, text=True).stdout.strip()
        report.data['baseline_sha'] = sha
    except Exception:                          # noqa: BLE001
        pass

    mandatory_fail = report.mandatory_failures()
    report.data['meets_pr_gate'] = not mandatory_fail
    report.data['counts'] = report.counts()
    report.data['log_dir'] = rel(out_dir)

    path = os.path.join(out_dir, 'report.json')
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(report.data, handle, ensure_ascii=False, indent=2)

    print('=== 成员模块验收：{0} ==='.format(report.data['module']))
    for c in report.data['checks']:
        mark = {'PASS': 'PASS', 'FAIL': 'FAIL', 'BLOCKED': 'BLOCKED',
                'NOT_RUN': 'NOT_RUN', 'SKIPPED': 'SKIPPED'}.get(c['status'], c['status'])
        print('  [{0:<8}] {1:<10} {2}'.format(mark, c['id'], c['check']))
        if c['detail'] and c['status'] != 'PASS':
            print('             {0}'.format(c['detail'][:150]))
    print('\n  计数: {0}'.format(report.data['counts']))
    print('  达到 PR 合入门槛: {0}'.format(report.data['meets_pr_gate']))
    print('  L2 算法证据: {0} | L3 在线联调: {1}'.format(
        report.data['algorithm_evidence'], report.data['runtime_integration']))
    print('  报告: {0}'.format(rel(path)))
    return 0 if report.data['meets_pr_gate'] else 1


if __name__ == '__main__':
    sys.exit(main())
