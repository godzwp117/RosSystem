#!/usr/bin/env python3
"""d1_independent_review.py -- D1 第一轮实现后的独立复核。

为什么单独做这一步
------------------
"Mock 开发完成、测试通过"不等于协议与安全行为已被独立验证。
本脚本**重新执行**四类复核，且以**真实适配层进程**的返回判定与退出码为准，
不阅读源代码后就下结论：

    复核一  进程调用协议（用故障注入替身逐项触发）
    复核二  安全失败行为（逐项确认不得得到 READY）
    复核三  真实替换能力（三种替身实际运行并证明加载的是替身）
    复核四  与原有安全边界一致（Git 差异与危险模式检查）

用法：
    python3 tests/integration/d1_independent_review.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ADAPTER = os.path.join(ROOT, 'scripts', 'team_demo.py')
EVIDENCE_DIR = os.path.join(ROOT, 'tests', 'evidence', 'd1_review')

PASS, FAIL, PARTIAL, BLOCKED, NOT_RUN = 'PASS', 'FAIL', 'PARTIAL', 'BLOCKED', 'NOT_RUN'


def sh(argv, **kwargs):
    return subprocess.run(argv, capture_output=True, text=True, cwd=ROOT, **kwargs)


def envelope(mock_control, *, request_id='req-review', run_id='run-review',
             observations_detail=None, target=None):
    return {
        'schema_version': '1.0.0-proposed',
        'run_id': run_id,
        'request_id': request_id,
        'created_at': '2026-10-10T12:00:00Z',
        'candidate_action': {
            'action_resource': '/rg/guarded_navigate',
            'operation': 'NAVIGATE',
            'task_id': 'patrol_a_001',
            'target': target or {'frame_id': 'map', 'x': 1.5, 'y': 1.5, 'z': 0.0},
        },
        'observations': [{
            'source': '/rg/guarded_navigate', 'kind': 'MOCK',
            'observed_at': '2026-10-10T12:00:00Z',
            'detail': observations_detail if observations_detail is not None
                      else {'f0_mock': mock_control},
        }],
        'evidence_refs': [{'ref': 'd1 review', 'kind': 'MOCK'}],
    }


def proceed(**per_module):
    control = {'comm_risk': {'scenario': 'normal'},
               'identity_trust': {'scenario': 'authorized'},
               'task_risk': {'scenario': 'allow'}}
    for module, value in per_module.items():
        control[module] = value
    return control


def make_config(tmp: str, *, doubles=False, faults=False, timeouts=None,
                name='team_modules') -> str:
    import yaml
    modules = {}
    # 注意：循环变量不能叫 name —— 那会遮蔽本函数的 name 参数，
    # 导致三条配置全部写到同一个文件（早期版本正是如此，产生假失败）。
    for module, interface in (('comm_risk', 'comm_risk_evidence'),
                              ('identity_trust', 'identity_trust_assessment'),
                              ('task_risk', 'task_risk_decision')):
        if doubles:
            command = ['python3',
                       'tests/fixtures/team_modules/{0}_double.py'.format(module)]
        else:
            command = ['python3', 'mock_modules/{0}_mock.py'.format(module)]
        modules[module] = {
            'mode': 'double' if doubles else 'mock',
            'interface': interface,
            'command': command,
            'timeout_sec': (timeouts or {}).get(module, 10),
            'max_stdout_bytes': 65536,
            'allow_fault_injection': faults,
        }
    # 每条配置必须用不同文件名：早期版本三条配置写到同一路径互相覆盖，
    # 导致"基线用例"实际跑的是替身配置，出现假失败。
    path = os.path.join(tmp, '{0}.yaml'.format(name))
    with open(path, 'w', encoding='utf-8') as handle:
        yaml.safe_dump({'adapter': {}, 'modules': modules}, handle, allow_unicode=True)
    return path


def call(tmp: str, document, config: str, *, timeout=180):
    """真实执行适配层，返回 (exit_code, result, stderr)。"""
    path = os.path.join(tmp, 'envelope.json')
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(document, handle, ensure_ascii=False)
    proc = sh([sys.executable, ADAPTER, '--input', path, '--config', config,
               '--log', os.path.join(tmp, 'review.jsonl'), '--workdir', ROOT],
              timeout=timeout)
    try:
        result = json.loads(proc.stdout)
    except ValueError:
        result = {'decision': 'UNPARSEABLE', 'raw': proc.stdout[:200]}
    return proc.returncode, result, proc.stderr


def main() -> int:
    os.makedirs(EVIDENCE_DIR, exist_ok=True)
    checks = []

    def record(area, item, status, detail):
        checks.append({'area': area, 'item': item, 'status': status,
                       'detail': str(detail)[:300]})
        print('  [{0:<7}] {1:<44} {2}'.format(status, item, str(detail)[:70]))

    def expect(area, item, code, result, want_decision, want_codes=()):
        ok = (code != 0 if want_decision == 'ADAPTER_BLOCK' else code == 0) and \
             result.get('decision') == want_decision and \
             (not want_codes or result.get('reason_code') in want_codes)
        record(area, item, PASS if ok else FAIL,
               'exit={0} decision={1} reason={2}'.format(
                   code, result.get('decision'), result.get('reason_code')))
        return ok

    with tempfile.TemporaryDirectory(prefix='d1review_') as tmp:
        cfg = make_config(tmp, name='baseline')
        cfg_fault = make_config(tmp, faults=True, timeouts={'comm_risk': 2},
                                name='with_faults')
        cfg_double = make_config(tmp, doubles=True, name='with_doubles')

        # ---------------------------------------------------------- 复核一
        print('\n=== 复核一：进程调用协议 ===')
        code, result, _ = call(tmp, envelope(proceed()), cfg)
        expect('protocol', 'P-01/02 正常输入输出', code, result,
               'READY_FOR_GATEWAY_SUBMISSION')
        record('protocol', 'P-01 记录 PID/PGID',
               PASS if all(m.get('pid') and m.get('pgid') for m in result['modules'])
               else FAIL, '三个模块均有 pid/pgid')

        for fault, label in (('debug_text', 'P-03 stdout 混入调试文本'),
                             ('two_objects', 'P-04 stdout 两个对象'),
                             ('empty', 'P-05 stdout 为空'),
                             ('invalid_json', 'P-05 非 JSON 输出'),
                             ('bad_encoding', 'P-07 非法 UTF-8'),
                             ('nan', 'P-08 NaN'),
                             ('infinity', 'P-08 Infinity'),
                             ('bad_timestamp', 'P-09 非法时间戳'),
                             ('oversize', 'P-10 超出输出上限'),
                             ('duplicate_key', 'P-15 重复 JSON 键')):
            ctrl = proceed()
            ctrl['fault'] = {'comm_risk': fault}
            c2, r2, _ = call(tmp, envelope(ctrl), cfg_fault)
            expect('protocol', label, c2, r2, 'ADAPTER_BLOCK')

        ctrl = proceed()
        ctrl['fault'] = {'comm_risk': 'timeout'}
        c3, r3, _ = call(tmp, envelope(ctrl), cfg_fault)
        expect('protocol', 'P-11 子进程超时', c3, r3, 'ADAPTER_BLOCK')
        mod = [m for m in r3.get('modules', []) if m['module'] == 'comm_risk']
        cleanup = mod[0]['cleanup'] if mod else 'missing'
        pid = mod[0]['pid'] if mod else None
        alive = sh(['ps', '-o', 'stat=', '-p', str(pid)]).stdout.strip() if pid else ''
        record('protocol', 'P-11 超时进程已清理且已回收',
               PASS if cleanup not in ('not_needed',) and 'unreaped' not in cleanup
               and (not alive or alive.startswith('Z')) else FAIL,
               'cleanup={0} state={1!r}'.format(cleanup, alive))

        cfg_space = make_config(tmp, name='space_probe')
        import yaml
        doc = yaml.safe_load(open(cfg_space, encoding='utf-8'))
        marker = os.path.join(tmp, 'shell-marker')
        doc['modules']['comm_risk']['command'] = [
            'python3', '-c', 'import sys,json;sys.stdin.read();print("{}")',
            'a b', '$(touch {0})'.format(marker)]
        space_path = os.path.join(tmp, 'space.yaml')
        with open(space_path, 'w', encoding='utf-8') as handle:
            yaml.safe_dump(doc, handle, allow_unicode=True)
        c4, r4, _ = call(tmp, envelope(proceed()), space_path)
        record('protocol', 'P-12 参数含空格/元字符不被 Shell 解释',
               PASS if not os.path.exists(marker) else FAIL,
               '标记文件未生成={0}'.format(not os.path.exists(marker)))

        # ---------------------------------------------------------- 复核二
        print('\n=== 复核二：安全失败行为 ===')
        cases = [
            ('S-02 通信 SUSPICIOUS', {'comm_risk': {'scenario': 'suspicious'}}),
            ('S-03 身份 DENIED', {'identity_trust': {'scenario': 'denied'}}),
            ('S-04 任务 BLOCK_RECOMMENDED', {'task_risk': {'scenario': 'block'}}),
            ('S-05 通信 UNKNOWN', {'comm_risk': {'scenario': 'unknown'}}),
            ('S-06 任务 ERROR', {'task_risk': {'scenario': 'error'}}),
            ('S-07 Schema 版本不兼容', {'comm_risk': {
                'scenario': 'normal', 'override': {'schema_version': '9.9.9'}}}),
            ('S-08 缺少必填字段', {'comm_risk': {
                'scenario': 'normal', 'drop': ['basis']}}),
            ('S-09 request_id 不一致', {'identity_trust': {
                'scenario': 'authorized', 'override': {'request_id': 'req-X'}}}),
            ('S-10 run_id 不一致', {'task_risk': {
                'scenario': 'allow', 'override': {'run_id': 'run-X'}}}),
            ('S-11 task_id 不一致', {'task_risk': {
                'scenario': 'allow', 'override': {'task_id': 'other'}}}),
            ('S-15 自报 gateway 不能覆盖拒绝', {'identity_trust': {
                'scenario': 'denied',
                'override': {'producer': {'name': 'gateway', 'source': 'EXTERNAL'}}}}),
        ]
        for label, control in cases:
            c, r, _ = call(tmp, envelope(proceed(**control)), cfg)
            expect('security', label, c, r, 'ADAPTER_BLOCK')

        ctrl = proceed()
        ctrl['fault'] = {'task_risk': 'exit_nonzero'}
        c, r, _ = call(tmp, envelope(ctrl), cfg_fault)
        expect('security', 'S-13 模块崩溃', c, r, 'ADAPTER_BLOCK')

        c, r, _ = call(tmp, envelope(proceed()), cfg)
        record('security', 'S-01 基线可推进（对照）',
               PASS if c == 0 else FAIL, 'exit={0}'.format(c))

        bad = envelope(proceed())
        bad['candidate_action']['action_resource'] = '/rg/nav_execute'
        c, r, _ = call(tmp, bad, cfg)
        expect('security', 'S-16 输入选择执行端被拒', c, r, 'ADAPTER_BLOCK',
               ('ADAPTER_INPUT_INVALID',))
        record('security', 'S-16 拒绝时不调用任何模块',
               PASS if r.get('modules') == [] else FAIL,
               'modules={0}'.format(len(r.get('modules', []))))

        ctrl = proceed()
        ctrl['fault'] = {'comm_risk': 'invalid_json'}
        c, r, _ = call(tmp, envelope(ctrl), cfg_fault)
        invoked = [m['module'] for m in r.get('modules', [])]
        record('security', 'S-18 首模块失败不继续调用',
               PASS if invoked == ['comm_risk'] else FAIL, '实际={0}'.format(invoked))

        c, r, _ = call(tmp, envelope(proceed()), cfg)
        record('security', 'S-17 失败后再次调用不受污染',
               PASS if c == 0 else FAIL, 'exit={0}'.format(c))

        # ---------------------------------------------------------- 复核三
        print('\n=== 复核三：真实替换能力 ===')
        c, r, _ = call(tmp, envelope(None, observations_detail={
            'comm': {'request_count': 3, 'baseline_count': 3},
            'identity': {'subject': 'planner_node',
                         'resource': '/rg/guarded_navigate',
                         'operation': 'SERVICE_REQUEST'}}), cfg_double)
        ok = c == 0 and all('tests/fixtures/team_modules' in ' '.join(m['command'])
                            for m in r.get('modules', []))
        record('replacement', '三个替身全部加载并链路通过', PASS if ok else FAIL,
               'exit={0}'.format(c))

        for module in ('comm_risk', 'identity_trust', 'task_risk'):
            doc = yaml.safe_load(open(cfg, encoding='utf-8'))
            doc['modules'][module]['command'] = [
                'python3', 'tests/fixtures/team_modules/{0}_double.py'.format(module)]
            mixed = os.path.join(tmp, 'mixed_{0}.yaml'.format(module))
            with open(mixed, 'w', encoding='utf-8') as handle:
                yaml.safe_dump(doc, handle, allow_unicode=True)
            c2, r2, _ = call(tmp, envelope(None, observations_detail={
                'comm': {'request_count': 3, 'baseline_count': 3},
                'identity': {'subject': 'planner_node',
                             'resource': '/rg/guarded_navigate',
                             'operation': 'SERVICE_REQUEST'}}), mixed)
            record('replacement', '单独替换 {0}'.format(module),
                   PASS if c2 == 0 else FAIL, 'exit={0}'.format(c2))

        c, r, _ = call(tmp, envelope(None, observations_detail={
            'comm': {'request_count': 100, 'baseline_count': 3},
            'identity': {'subject': 'planner_node',
                         'resource': '/rg/guarded_navigate',
                         'operation': 'SERVICE_REQUEST'}}), cfg_double)
        status = [m['status'] for m in r.get('modules', [])
                  if m['module'] == 'comm_risk']
        record('replacement', '替身按数据计算（非场景开关）',
               PASS if c != 0 and status and status[0] == 'SUSPICIOUS' else FAIL,
               'count=100/baseline=3 -> {0}'.format(status))

    # ---------------------------------------------------------- 复核五（H1~H3）
    print('\n=== 复核五：D1 安全加固（H1 输出限额 / H2 审计失败关闭 / H3 配置）===')
    with tempfile.TemporaryDirectory(prefix='h_review_') as htmp:
        hcfg = make_config(htmp, faults=True, timeouts={'comm_risk': 30},
                           name='h_faults')

        # H1：必须断言**具体原因码**，不接受"反正 BLOCK 了"
        growth = None
        c0, r0, _ = call(htmp, envelope(proceed()), hcfg)
        base_rss = r0.get('adapter_peak_rss_kb')
        for fault, label in (('flood_stdout', 'H1 stdout 洪泛'),
                             ('flood_both', 'H1 stdout+stderr 同时洪泛')):
            ctrl = proceed()
            ctrl['fault'] = {'comm_risk': fault}
            c2, r2, _ = call(htmp, envelope(ctrl), hcfg, timeout=300)
            reason = r2.get('reason_code')
            ok = (c2 != 0 and reason == 'ADAPTER_MODULE_STDOUT_TOO_LARGE')
            record('harden', label, PASS if ok else FAIL,
                   'exit={0} reason={1}'.format(c2, reason))
            if fault == 'flood_stdout' and base_rss:
                growth = r2.get('adapter_peak_rss_kb', 0) - base_rss

        ctrl = proceed()
        ctrl['fault'] = {'comm_risk': 'flood_stderr'}
        c3, r3, _ = call(htmp, envelope(ctrl), hcfg, timeout=300)
        mod = [m for m in r3.get('modules', []) if m['module'] == 'comm_risk']
        kept = mod[0].get('stderr_bytes_kept') if mod else None
        exited = mod[0].get('exit_code') if mod else None
        record('harden', 'H1 stderr 排空但保留有界',
               PASS if exited == 0 and kept is not None and kept <= 16384 else FAIL,
               'exit_code={0} stderr_kept={1}'.format(exited, kept))
        record('harden', 'H1 适配层峰值内存有界',
               PASS if growth is not None and growth < 32 * 1024 else FAIL,
               '峰值增长={0} KiB'.format(growth))

        # H2：审计写入失败不得返回 READY
        hcfg2 = make_config(htmp, name='h_audit')
        blocker = os.path.join(htmp, 'afile')
        open(blocker, 'w').write('x')
        audit_cases = {'路径是目录': htmp,
                       '父路径是普通文件': os.path.join(blocker, 'sub', 'log.jsonl'),
                       'ENOSPC(/dev/full)': '/dev/full',
                       '只读伪文件系统': '/proc/1/nonexistent_dir/log.jsonl'}
        for label, logp in audit_cases.items():
            path = os.path.join(htmp, 'e.json')
            with open(path, 'w', encoding='utf-8') as handle:
                json.dump(envelope(proceed()), handle, ensure_ascii=False)
            proc = sh([sys.executable, ADAPTER, '--input', path, '--config', hcfg2,
                       '--log', logp, '--workdir', ROOT], timeout=120)
            try:
                res = json.loads(proc.stdout)
            except ValueError:
                res = {}
            ok = (proc.returncode != 0
                  and res.get('reason_code') == 'ADAPTER_AUDIT_WRITE_FAILED'
                  and res.get('audit_written') is False)
            record('harden', 'H2 审计失败关闭: ' + label, PASS if ok else FAIL,
                   'exit={0} reason={1}'.format(proc.returncode, res.get('reason_code')))

        # H3：配置加固（抽关键几项，必须报 CONFIG_INVALID）
        import yaml as _yaml
        h3_cases = {
            'timeout 为布尔': ('timeout_sec', True),
            'timeout=0': ('timeout_sec', 0),
            'timeout 超上限': ('timeout_sec', 99999),
            'stdout 上限为布尔': ('max_stdout_bytes', True),
            'interface 错配': ('interface', 'identity_trust_assessment'),
            'mode 非法': ('mode', 'shell'),
            '故障开关为字符串': ('allow_fault_injection', 'false'),
            'command 为字符串': ('command', 'python3 x.py'),
        }
        for label, (field, value) in h3_cases.items():
            base_cfg = make_config(htmp, name='h3_base')
            doc = _yaml.safe_load(open(base_cfg, encoding='utf-8'))
            doc['modules']['comm_risk'][field] = value
            target = os.path.join(htmp, 'h3_' + str(abs(hash(label)) % 10000) + '.yaml')
            with open(target, 'w', encoding='utf-8') as handle:
                _yaml.safe_dump(doc, handle, allow_unicode=True)
            c4, r4, _ = call(htmp, envelope(proceed()), target)
            ok = c4 == 4 and r4.get('reason_code') == 'ADAPTER_CONFIG_INVALID'
            record('harden', 'H3 ' + label, PASS if ok else FAIL,
                   'exit={0} reason={1}'.format(c4, r4.get('reason_code')))

    # ---------------------------------------------------------- 复核四
    print('\n=== 复核四：与原有安全边界一致 ===')
    frozen = ['src/rg_interfaces/action/PatrolNavigate.action',
              'src/rg_policy/rg_policy/reason_codes.py',
              'src/rg_gateway/rg_gateway/security_gateway.py']
    base = '1cf64e77c5c5382e5fba63b91d9898c7f9a898f0'
    diff = sh(['git', 'diff', '--name-only', base, '--'] + frozen).stdout.strip()
    record('boundary', '冻结契约/原因码/Gateway 未改', PASS if not diff else FAIL,
           '差异={0!r}'.format(diff or '无'))

    m3 = sh(['bash', '-lc',
             'ls src/rg_policy/rg_policy/task_state.py '
             'src/rg_policy/rg_policy/state_store.py '
             'src/rg_interfaces/srv/SwitchTask.srv 2>/dev/null | wc -l']).stdout.strip()
    record('boundary', '未引入 M3 状态机', PASS if m3 == '0' else FAIL,
           'M3 文件数={0}'.format(m3))

    shell_true = sh(['bash', '-lc',
                     'grep -rn "shell=True" scripts/team_demo.py mock_modules/ '
                     'tests/fixtures/ 2>/dev/null | wc -l']).stdout.strip()
    record('boundary', '未使用 shell=True', PASS if shell_true == '0' else FAIL,
           '出现次数={0}'.format(shell_true))

    pkill_calls = sh(['bash', '-lc',
                      'grep -nE "(subprocess\\.(run|call|Popen)\\([^)]*pkill|'
                      'os\\.system\\([^)]*pkill)" scripts/team_demo.py | wc -l']
                     ).stdout.strip()
    record('boundary', '未按名称执行 pkill', PASS if pkill_calls == '0' else FAIL,
           '实际调用={0}'.format(pkill_calls))

    sros = sh(['git', 'diff', '--name-only', base, '--', 'security/']).stdout.strip()
    record('boundary', 'M2 DDS 权限未放宽', PASS if not sros else FAIL,
           'security/ 差异={0!r}'.format(sros or '无'))

    # 契约校验未被削弱
    contract = sh([sys.executable,
                   os.path.join(ROOT, 'scripts', 'validate_team_contracts.py'),
                   '--all', '--quiet'])
    record('boundary', '契约校验未被削弱', PASS if contract.returncode == 0 else FAIL,
           'exit={0}'.format(contract.returncode))

    # ---------------------------------------------------------- 汇总
    summary = {
        'reviewed_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'git_head': sh(['git', 'rev-parse', 'HEAD']).stdout.strip(),
        'baseline': base,
        'checks': checks,
        'by_status': {},
        'overall': None,
    }
    for check in checks:
        summary['by_status'][check['status']] = \
            summary['by_status'].get(check['status'], 0) + 1
    summary['overall'] = 'PASS' if summary['by_status'].get(FAIL, 0) == 0 else 'FAIL'

    with open(os.path.join(EVIDENCE_DIR, 'review_result.json'), 'w',
              encoding='utf-8') as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)

    print('\n=== 独立复核汇总 ===')
    for status, count in sorted(summary['by_status'].items()):
        print('  {0:<8} {1}'.format(status, count))
    print('  OVERALL: {0}'.format(summary['overall']))
    print('  evidence: {0}'.format(os.path.relpath(
        os.path.join(EVIDENCE_DIR, 'review_result.json'), ROOT)))
    return 0 if summary['overall'] == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
