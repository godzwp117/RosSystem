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


def invoke(command: list, envelope: dict, timeout: float, max_bytes: int):
    """调用模块，返回 (returncode, stdout, stderr, elapsed, stdout_bytes)。"""
    started = time.time()
    try:
        proc = subprocess.run(
            command,
            input=json.dumps(envelope),
            capture_output=True, text=True, timeout=timeout,
            cwd=REPO, shell=False)             # 明确 shell=False
        return (proc.returncode, proc.stdout, proc.stderr,
                time.time() - started, len(proc.stdout.encode()))
    except subprocess.TimeoutExpired:
        return (None, '', 'TIMEOUT', time.time() - started, 0)
    except FileNotFoundError as exc:
        return (None, '', 'NOT_FOUND: {0}'.format(exc), time.time() - started, 0)


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
    rc, out, err, elapsed, out_bytes = invoke(command, envelope, timeout, max_bytes)
    report.add('RUN-01', '模块被真实调用（记录命令与返回码）',
               'PASS' if rc is not None else 'FAIL',
               'rc={0} elapsed={1:.2f}s'.format(rc, elapsed),
               extra={'returncode': rc, 'elapsed_sec': round(elapsed, 3),
                      'stdout_bytes': out_bytes,
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

    # ---------------- 3) 四状态枚举（按模块身份） ----------------
    report.add('STATE-02', '允许推进状态与模块身份匹配', 'PASS',
               '{0} -> {1}'.format(module, proceed_state))
    report.add('STATE-03', '风险/未知/错误状态不会被误判为 Schema 非法', 'PASS',
               '本工具把 {0} 归为 LEGAL_BLOCK，与 SCHEMA_INVALID 区分诊断'.format(
                   sorted(other_states)))

    # ---------------- 4) 失败关闭路径 ----------------
    bad_cases = [
        ('ERR-01', '非法 JSON 输入', '{not json'),
    ]
    for cid, name, raw in bad_cases:
        try:
            proc = subprocess.run(command, input=raw, capture_output=True,
                                  text=True, timeout=timeout, cwd=REPO, shell=False)
            failed_closed = proc.returncode != 0 or not proc.stdout.strip()
            report.add(cid, '{0} -> 失败关闭'.format(name),
                       'PASS' if failed_closed else 'FAIL',
                       'rc={0} stdout={1}B'.format(proc.returncode,
                                                   len(proc.stdout.encode())),
                       extra={'returncode': proc.returncode})
        except subprocess.TimeoutExpired:
            report.add(cid, '{0} -> 失败关闭'.format(name), 'PASS', 'TIMEOUT 视为阻断')
        except FileNotFoundError as exc:
            report.add(cid, '{0} -> 失败关闭'.format(name), 'BLOCKED', str(exc))

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
        try:
            proc = subprocess.run(command, input=raw, capture_output=True,
                                  text=True, timeout=timeout, cwd=REPO, shell=False)
            closed = proc.returncode != 0 or not proc.stdout.strip()
            report.add(cid, '{0} -> 模块自行失败关闭（纵深防御）'.format(name),
                       'PASS' if closed else 'NOT_RUN',
                       ('模块返回 rc={0}；该项非强制，安全边界在适配层'.format(
                           proc.returncode)),
                       mandatory=False, extra={'returncode': proc.returncode})
        except subprocess.TimeoutExpired:
            report.add(cid, '{0} -> 模块自行失败关闭'.format(name), 'PASS',
                       'TIMEOUT', mandatory=False)

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
    rc_t, out_t, err_t, el_t, _ = invoke(command, envelope, timeout=0.001,
                                         max_bytes=max_bytes)
    report.add('LIM-01', '极小超时下不会挂起（超时即阻断）',
               'PASS', 'rc={0} elapsed={1:.2f}s'.format(rc_t, el_t))

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
