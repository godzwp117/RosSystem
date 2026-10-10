#!/usr/bin/env python3
"""mock_modules/_protocol.py -- 三个 Mock 共用的进程级协议助手。

协议（与 docs/interfaces/CONTRACT_VERSION.md 第 6 节一致）：
    stdin  : 一个 JSON 对象（ModuleInputEnvelope）
    stdout : 一个 JSON 对象（对应接口的输出），**不得混入任何调试文本**
    stderr : 诊断信息
    退出码 : 0 表示进程正常执行（不代表业务结论为允许）；非 0 表示进程异常

故障注入
--------
为了让适配层的失败关闭行为可被真实测试，Mock 支持注入协议层故障
（非法 JSON、两个对象、空输出、非零退出、超时、NaN、重复键、非法时间戳、
超长输出、非法 UTF-8）。

**故障注入必须显式开启**：只有传入 `--allow-fault-injection` 才会生效。
未开启时若输入要求注入故障，Mock 会拒绝执行并返回退出码 2 —— 这样故障注入
不可能在生产/联调配置下被意外触发。

本模块只服务于 Mock，不包含任何适配层业务逻辑。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

EXIT_OK = 0
EXIT_INPUT_ERROR = 2
EXIT_INTERNAL_ERROR = 3

# 输入信封中用于控制 Mock 行为的保留键（放在 observations[].detail 下）
CONTROL_KEY = 'f0_mock'

VALID_SCENARIOS = ('default', 'normal', 'suspicious', 'unknown', 'error',
                   'authorized', 'denied', 'allow', 'block')


def parse_args(description: str):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument('--allow-fault-injection', action='store_true',
                        help='允许输入触发协议层故障注入（仅供测试使用）')
    return parser.parse_args()


def read_input():
    """从 stdin 读取一个 JSON 对象。

    这里使用与 scripts/validate_team_contracts.py 相同的严格解析规则：
    拒绝重复键与非有限数值字面量。Mock 侧严格解析可以尽早发现输入问题，
    但适配层**仍会独立再解析一次**——Mock 的解析结果不构成对适配层的保证。
    """
    text = sys.stdin.read()
    if not text.strip():
        raise ValueError('stdin 为空，未收到输入信封')

    def _reject_duplicates(pairs):
        seen = {}
        for key, value in pairs:
            if key in seen:
                raise ValueError('重复的 JSON 键: {0!r}'.format(key))
            seen[key] = value
        return seen

    def _reject_non_finite(name):
        raise ValueError('非有限数值字面量不是合法 JSON: {0}'.format(name))

    return json.loads(text, object_pairs_hook=_reject_duplicates,
                      parse_constant=_reject_non_finite)


# 三个模块各自的场景词汇不同（通信看行为、身份看授权、任务看建议），
# 因此控制块按模块名分别指定，避免把一套词表强加给三个接口。
MODULES = ('comm_risk', 'identity_trust', 'task_risk')


def raw_control(envelope):
    """取出输入信封中原始的 Mock 控制块（测试用）。"""
    for observation in envelope.get('observations', []) or []:
        detail = observation.get('detail') if isinstance(observation, dict) else None
        if isinstance(detail, dict) and isinstance(detail.get(CONTROL_KEY), dict):
            return detail[CONTROL_KEY]
    return {}


def control_for(envelope, module: str) -> dict:
    """组装某个模块的控制参数（测试用）。

    控制块结构：

        "f0_mock": {
            "scenario": "..." | {"<module>": "..."},   # 可全局或按模块
            "fault":    "..." | {"<module>": "..."},   # 同上
            "<module>": { "scenario": "...", ... }     # 模块专属参数
        }

    这样每个 Mock 只关心自己那套场景词，不会因为别的模块的词而拒绝执行。
    """
    raw = raw_control(envelope)
    control = {}

    scenario = raw.get('scenario')
    if isinstance(scenario, str):
        control['scenario'] = scenario
    elif isinstance(scenario, dict) and module in scenario:
        control['scenario'] = scenario[module]

    specific = raw.get(module)
    if isinstance(specific, dict):
        control.update(specific)

    # fault 的优先级：模块专属 > 顶层按模块字典 > 顶层标量。
    # 早期版本在 update(specific) 之后又执行 `control['fault'] = raw.get('fault')`，
    # 当只有模块专属 fault 时会把已设好的值**覆盖成 None**，
    # 使故障注入静默失效 —— 而失效方向是"失败开放"：
    # 模块表现正常、适配层给出 READY、请求照常进入 Gateway。
    # 对安全测试脚手架而言这是最危险的失效模式，必须显式保证不被覆盖。
    fault = None
    top_fault = raw.get('fault')
    if isinstance(top_fault, str):
        fault = top_fault
    elif isinstance(top_fault, dict):
        fault = top_fault.get(module)
    if isinstance(specific, dict) and 'fault' in specific:
        fault = specific['fault']
    control['fault'] = fault

    return control


def emit(document):
    """输出唯一的 JSON 对象到 stdout（紧凑、单行、无额外文本）。"""
    json.dump(document, sys.stdout, ensure_ascii=False, separators=(',', ':'))
    sys.stdout.write('\n')
    sys.stdout.flush()


def note(message):
    """诊断信息只写 stderr，绝不污染 stdout。"""
    sys.stderr.write('[mock] {0}\n'.format(message))
    sys.stderr.flush()


def apply_fault_injection(fault, allowed: bool) -> bool:
    """按需注入协议层故障。返回 True 表示已处理（调用方应立即结束）。

    未开启 `--allow-fault-injection` 时拒绝执行故障请求。
    """
    if not fault:
        return False
    if not allowed:
        note('输入要求故障注入 {0!r}，但未开启 --allow-fault-injection；拒绝执行'
             .format(fault))
        sys.exit(EXIT_INPUT_ERROR)

    note('注入故障: {0}'.format(fault))

    if fault == 'invalid_json':
        sys.stdout.write('{ this is not json ')
        sys.stdout.flush()
        sys.exit(EXIT_OK)
    if fault == 'debug_text':
        sys.stdout.write('DEBUG: starting module\n')
        sys.stdout.write('{"status": "NORMAL"}\n')
        sys.stdout.flush()
        sys.exit(EXIT_OK)
    if fault == 'two_objects':
        sys.stdout.write('{"status": "NORMAL"}\n{"status": "NORMAL"}\n')
        sys.stdout.flush()
        sys.exit(EXIT_OK)
    if fault == 'empty':
        sys.exit(EXIT_OK)
    if fault == 'exit_nonzero':
        note('模拟模块异常退出')
        sys.exit(EXIT_INTERNAL_ERROR + 4)   # 7
    if fault == 'timeout':
        note('模拟模块超时（睡眠）')
        time.sleep(float(os.environ.get('F0_MOCK_SLEEP_SEC', '30')))
        sys.exit(EXIT_OK)
    if fault == 'bad_encoding':
        sys.stdout.buffer.write(b'{"status": "\xff\xfe invalid utf8"}')
        sys.stdout.buffer.flush()
        sys.exit(EXIT_OK)
    if fault in ('flood_stdout', 'flood_stderr', 'flood_both'):
        # 持续洪泛：用于验证适配层是否真的在**读取过程中**限流。
        # 旧实现用 communicate() 会先把全部输出读进内存，本故障可使其内存无界增长；
        # 新实现应在首次超过 stdout 上限时立即终止本进程。
        total = int(os.environ.get('F0_MOCK_FLOOD_BYTES', str(64 * 1024 * 1024)))
        chunk = b'x' * 65536
        written = 0
        target_out = fault in ('flood_stdout', 'flood_both')
        target_err = fault in ('flood_stderr', 'flood_both')
        try:
            while written < total:
                if target_out:
                    sys.stdout.buffer.write(chunk)
                    sys.stdout.buffer.flush()
                if target_err:
                    sys.stderr.buffer.write(chunk)
                    sys.stderr.buffer.flush()
                written += len(chunk)
        except (BrokenPipeError, OSError):
            # 适配层已终止本次调用（这正是预期行为）
            pass
        sys.exit(EXIT_OK)
    if fault == 'oversize':
        # 输出超过适配层大小上限的内容
        sys.stdout.write('{"padding": "' + ('x' * 200000) + '"}\n')
        sys.stdout.flush()
        sys.exit(EXIT_OK)
    if fault in ('nan', 'infinity'):
        literal = 'NaN' if fault == 'nan' else 'Infinity'
        sys.stdout.write('{"schema_version": "1.0.0-proposed", "value": %s}\n' % literal)
        sys.stdout.flush()
        sys.exit(EXIT_OK)
    if fault == 'duplicate_key':
        sys.stdout.write('{"schema_version": "1.0.0-proposed", '
                         '"schema_version": "9.9.9"}\n')
        sys.stdout.flush()
        sys.exit(EXIT_OK)
    if fault == 'bad_timestamp':
        sys.stdout.write('{"schema_version": "1.0.0-proposed", '
                         '"observed_at": "2026-10-10 12:00:05"}\n')
        sys.stdout.flush()
        sys.exit(EXIT_OK)

    note('未知的故障类型: {0!r}'.format(fault))
    sys.exit(EXIT_INPUT_ERROR)


def apply_overrides(document, control):
    """按控制块覆写输出字段（**仅供测试构造异常用例**）。

    用于真实地产生"结构合法但关联不一致""版本不兼容""缺少必填字段"
    "自报高权限 producer"等用例，从而让适配层的失败关闭行为可以被真实验证，
    而不是靠阅读代码推断。

    覆写只能由输入信封中的 `f0_mock` 控制块触发；它**不会**放宽任何 Schema 约束
    —— 被覆写后的输出仍要经过适配层的完整校验，该拒绝的照样拒绝。
    """
    overrides = control.get('override')
    if isinstance(overrides, dict):
        document.update(overrides)
    drop = control.get('drop')
    if isinstance(drop, list):
        for key in drop:
            document.pop(key, None)
    return document


def epoch_now_iso():
    """固定时间基准，保证同一输入重复运行结果稳定。

    刻意不使用当前时间：Mock 输出若随时间变化，就无法用固定期望值断言，
    也会让"重复运行结果一致"这条要求不可验证。
    """
    return '2026-10-10T12:00:05Z'


def require(envelope, key):
    value = envelope.get(key)
    if value in (None, ''):
        raise ValueError('输入信封缺少必需字段: {0}'.format(key))
    return value


def candidate_target(envelope):
    action = envelope.get('candidate_action') or {}
    target = action.get('target') or {}
    return {
        'frame_id': str(target.get('frame_id', 'map')),
        'x': float(target.get('x', 0.0)),
        'y': float(target.get('y', 0.0)),
        'z': float(target.get('z', 0.0)),
    }
