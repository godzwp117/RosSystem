#!/usr/bin/env python3
"""scripts/team_demo.py -- 三个研究模块的统一安全适配层（F0 阶段 D1）。

职责边界（重要）
----------------
本适配层只做一件事：**判断候选输入是否可以进入后续 Action 提交流程**。

    * 它**不**提交真实 ROS 2 Action（留待 D2）；
    * 它**不**做最终授权（那是 SecurityGateway 的职责）；
    * 它**不**创建任何指向执行端 /rg/nav_execute 的通道。

因此本层只有一个肯定结论：

    READY_FOR_GATEWAY_SUBMISSION   —— 候选输入检查通过，**不代表 Gateway 已允许**，
                                     更不代表下游已执行。

其余任何情况一律是本地阻断 `ADAPTER_BLOCK`。

失败关闭原则
------------
下列情况**一律**不得被转换为允许：
    模块缺失 / 无法启动 / 非零退出 / 超时 / stdout 为空或非单个 JSON 对象 /
    非法 UTF-8 / 超出输出上限 / 重复 JSON 键 / 非有限数值 / 非法时间戳 /
    Schema 校验失败 / Schema 版本不兼容 / request_id 或 run_id 不一致 /
    任务或候选操作不一致 / 事件标识重复 / 任一模块状态不是推进状态。

安全实现要点
------------
* 模块命令**只来自受信任的本地配置文件**，绝不从业务输入 JSON 中读取路径、
  命令、producer 或角色名来动态执行程序。
* 使用**参数数组**执行，`shell=False`，不做任何 Shell 字符串拼接。
* 每次调用建立唯一调用记录，记录 PID/PGID；超时或异常时只终止**本次调用自己的
  进程组**，并按名称执行 pkill 是禁止的。
* 始终回收本次创建的直接子进程，避免僵尸。
* 适配层日志与模块 stdout 严格分离：stdout 只输出最终结果 JSON。
* 适配层内部错误码独立定义，**不与 Gateway 的八个业务原因码混用**。
"""

from __future__ import annotations

import argparse
import errno
import json
import os
import signal
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if os.path.join(REPO_ROOT, 'scripts') not in sys.path:
    sys.path.insert(0, os.path.join(REPO_ROOT, 'scripts'))

import validate_team_contracts as vtc  # noqa: E402

ADAPTER_VERSION = '0.1.0'
CONTRACT_VERSION = vtc.CONTRACT_VERSION

# ---------------------------------------------------------------- 退出码
# 独立命名空间：与 Gateway 的八个业务原因码无关，避免任何混淆。
EXIT_READY = 0
EXIT_BLOCK = 10
EXIT_USAGE = 2
EXIT_INPUT_INVALID = 3
EXIT_CONFIG_INVALID = 4
EXIT_INTERNAL = 5

# ---------------------------------------------------------------- 本地错误码
REASON_OK = 'ADAPTER_OK'
REASON_INPUT_INVALID = 'ADAPTER_INPUT_INVALID'
REASON_CONFIG_INVALID = 'ADAPTER_CONFIG_INVALID'
REASON_MODULE_MISSING = 'ADAPTER_MODULE_MISSING'
REASON_SPAWN_FAILED = 'ADAPTER_MODULE_SPAWN_FAILED'
REASON_EXIT_NONZERO = 'ADAPTER_MODULE_EXIT_NONZERO'
REASON_TIMEOUT = 'ADAPTER_MODULE_TIMEOUT'
REASON_STDOUT_INVALID = 'ADAPTER_MODULE_STDOUT_INVALID'
REASON_ENCODING = 'ADAPTER_MODULE_STDOUT_ENCODING'
REASON_TOO_LARGE = 'ADAPTER_MODULE_STDOUT_TOO_LARGE'
REASON_SCHEMA_INVALID = 'ADAPTER_MODULE_SCHEMA_INVALID'
REASON_SCHEMA_VERSION = 'ADAPTER_MODULE_SCHEMA_VERSION'
REASON_NOT_PROCEED = 'ADAPTER_MODULE_STATUS_NOT_PROCEED'
REASON_CONSISTENCY_REQUEST_ID = 'ADAPTER_CONSISTENCY_REQUEST_ID'
REASON_CONSISTENCY_RUN_ID = 'ADAPTER_CONSISTENCY_RUN_ID'
REASON_CONSISTENCY_TASK_ID = 'ADAPTER_CONSISTENCY_TASK_ID'
REASON_CONSISTENCY_ACTION = 'ADAPTER_CONSISTENCY_ACTION'
REASON_CONSISTENCY_EVENT_ID = 'ADAPTER_CONSISTENCY_EVENT_ID'
REASON_CLEANUP_FAILED = 'ADAPTER_CLEANUP_FAILED'

# 唯一推进条件：三个接口必须分别处于下列状态
PROCEED_STATES = {
    'comm_risk': 'NORMAL',
    'identity_trust': 'AUTHORIZED',
    'task_risk': 'ALLOW_RECOMMENDED',
}

# 模块调用顺序固定，避免执行顺序影响结论
MODULE_ORDER = ('comm_risk', 'identity_trust', 'task_risk')

GUARDED_ACTION = '/rg/guarded_navigate'

DEFAULT_STDOUT_LIMIT = 65536
DEFAULT_TIMEOUT = 10.0


# ---------------------------------------------------------------- 工具
def now_iso() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def log_line(message: str, stream=sys.stderr) -> None:
    """诊断信息只写 stderr / 日志文件，绝不污染 stdout 的结果 JSON。"""
    stream.write('[adapter] {0}\n'.format(message))
    stream.flush()


class AdapterBlock(Exception):
    """本地阻断。携带独立错误码与人类可读说明。"""

    def __init__(self, reason_code: str, detail: str):
        super().__init__(detail)
        self.reason_code = reason_code
        self.detail = detail


# ---------------------------------------------------------------- 配置
def load_config(path: str) -> dict:
    import yaml

    if not os.path.isfile(path):
        raise AdapterBlock(REASON_CONFIG_INVALID, '配置文件不存在: {0}'.format(path))
    with open(path, 'r', encoding='utf-8') as handle:
        try:
            config = yaml.safe_load(handle)
        except Exception as exc:  # noqa: BLE001
            raise AdapterBlock(REASON_CONFIG_INVALID,
                               '配置解析失败: {0}'.format(exc)) from exc
    if not isinstance(config, dict):
        raise AdapterBlock(REASON_CONFIG_INVALID, '配置根节点必须是映射')

    modules = config.get('modules')
    if not isinstance(modules, dict):
        raise AdapterBlock(REASON_CONFIG_INVALID, '配置缺少 modules 段')

    for name in MODULE_ORDER:
        entry = modules.get(name)
        if not isinstance(entry, dict):
            raise AdapterBlock(REASON_CONFIG_INVALID,
                               '配置缺少模块定义: {0}'.format(name))
        command = entry.get('command')
        # 关键安全检查：命令必须是非空的字符串数组（参数数组），
        # 禁止字符串形式（会被 Shell 解释），也禁止从输入动态获取。
        if not isinstance(command, list) or not command or \
                not all(isinstance(part, str) and part for part in command):
            raise AdapterBlock(
                REASON_CONFIG_INVALID,
                '模块 {0} 的 command 必须是非空字符串数组（参数数组），'
                '不接受字符串形式'.format(name))
        interface = entry.get('interface')
        if interface not in vtc.SCHEMA_FILES or interface == 'module_input':
            raise AdapterBlock(REASON_CONFIG_INVALID,
                               '模块 {0} 的 interface 无效: {1!r}'.format(name, interface))
        timeout = entry.get('timeout_sec', DEFAULT_TIMEOUT)
        if not isinstance(timeout, (int, float)) or timeout <= 0:
            raise AdapterBlock(REASON_CONFIG_INVALID,
                               '模块 {0} 的 timeout_sec 必须为正数'.format(name))
        limit = entry.get('max_stdout_bytes', DEFAULT_STDOUT_LIMIT)
        if not isinstance(limit, int) or limit <= 0:
            raise AdapterBlock(REASON_CONFIG_INVALID,
                               '模块 {0} 的 max_stdout_bytes 必须为正整数'.format(name))
    return config


# ---------------------------------------------------------------- 严格解析
def parse_single_json_object(text: str, source: str):
    """严格解析 stdout：必须**恰好**一个 JSON 对象，无多余内容。

    覆盖的协议违规：
      * 空输出
      * 非 JSON 文本（含前置调试文本）
      * 连续两个 JSON 对象
      * 重复键（由 vtc.load_json_strict_text 拒绝）
      * 非有限数值字面量（同上）
    """
    stripped = text.strip()
    if not stripped:
        raise AdapterBlock(REASON_STDOUT_INVALID, '{0}: stdout 为空'.format(source))
    try:
        document, end = json.JSONDecoder(
            object_pairs_hook=vtc.reject_duplicate_keys,
            parse_constant=vtc.non_finite_constant).raw_decode(stripped)
    except ValueError as exc:
        raise AdapterBlock(REASON_STDOUT_INVALID,
                           '{0}: stdout 不是合法 JSON: {1}'.format(source, exc)) from exc
    remainder = stripped[end:].strip()
    if remainder:
        raise AdapterBlock(
            REASON_STDOUT_INVALID,
            '{0}: stdout 含多余内容（必须恰好一个 JSON 对象）: {1!r}'.format(
                source, remainder[:60]))
    if not isinstance(document, dict):
        raise AdapterBlock(REASON_STDOUT_INVALID,
                           '{0}: stdout 顶层必须是 JSON 对象'.format(source))
    return document


# ---------------------------------------------------------------- 进程调用
def invoke_module(name: str, entry: dict, envelope_text: str, workdir: str,
                  invocation_id: str, records: list):
    """调用一个模块进程，返回 (document, record)。

    进程生命周期管理：start_new_session=True 让子进程成为新会话/进程组组长，
    从而在超时或异常时只终止**本次调用自己的进程组**，不影响其他开发实例。
    """
    command = list(entry['command'])
    if entry.get('allow_fault_injection'):
        # 故障注入必须由**受信任的本地配置**显式开启；
        # 绝不能由业务输入 JSON 打开（输入无法影响命令行参数）
        command.append('--allow-fault-injection')

    timeout = float(entry.get('timeout_sec', DEFAULT_TIMEOUT))
    limit = int(entry.get('max_stdout_bytes', DEFAULT_STDOUT_LIMIT))
    interface = entry['interface']

    record = {
        'invocation_id': invocation_id,
        'module': name,
        'mode': entry.get('mode', 'mock'),
        'interface': interface,
        # 安全表示：不回显可能含敏感信息的环境，仅记录参数数组本身
        'command': command,
        'timeout_sec': timeout,
        'max_stdout_bytes': limit,
        'pid': None,
        'pgid': None,
        'exit_code': None,
        'duration_ms': None,
        'stdout_bytes': None,
        'status': None,
        'schema_ok': False,
        'cleanup': 'not_needed',
    }

    # 先登记调用记录：即使后续任何一步失败（模块缺失、超时、非零退出、
    # 解析失败、Schema 失败），该记录也必须留在结果里 —— 进程证据不能因为
    # 失败而消失，否则无法复核"到底哪个进程、什么时候、以什么退出码失败"。
    records.append(record)

    started = time.monotonic()
    try:
        # shell=False 且传数组：参数边界由内核保证，不发生 Shell 解释
        proc = subprocess.Popen(
            command, cwd=workdir, shell=False,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=True)
    except FileNotFoundError as exc:
        raise AdapterBlock(REASON_MODULE_MISSING,
                           '模块 {0} 的可执行文件不存在: {1}'.format(name, exc)) from exc
    except OSError as exc:
        raise AdapterBlock(REASON_SPAWN_FAILED,
                           '模块 {0} 无法启动: {1}'.format(name, exc)) from exc

    record['pid'] = proc.pid
    try:
        record['pgid'] = os.getpgid(proc.pid)
    except OSError:
        record['pgid'] = None

    try:
        out, err = proc.communicate(input=envelope_text.encode('utf-8'), timeout=timeout)
        record['exit_code'] = proc.returncode
        record['duration_ms'] = int((time.monotonic() - started) * 1000)
    except subprocess.TimeoutExpired:
        record['duration_ms'] = int((time.monotonic() - started) * 1000)
        record['cleanup'] = terminate_process_group(proc, record)
        raise AdapterBlock(
            REASON_TIMEOUT,
            '模块 {0} 超时（{1}s），已终止本次调用的进程组；'
            '本次调用不产生任何允许结论'.format(name, timeout)) from None

    record['stdout_bytes'] = len(out)
    if err:
        log_line('模块 {0} stderr: {1}'.format(
            name, err.decode('utf-8', 'replace').strip()[:400]))

    if proc.returncode != 0:
        raise AdapterBlock(
            REASON_EXIT_NONZERO,
            '模块 {0} 非零退出（exit={1}）'.format(name, proc.returncode))

    if len(out) > limit:
        raise AdapterBlock(
            REASON_TOO_LARGE,
            '模块 {0} 输出 {1} 字节，超过上限 {2}'.format(name, len(out), limit))

    try:
        text = out.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise AdapterBlock(REASON_ENCODING,
                           '模块 {0} 输出不是合法 UTF-8: {1}'.format(name, exc)) from exc

    document = parse_single_json_object(text, '模块 {0}'.format(name))

    version = document.get('schema_version')
    if version != CONTRACT_VERSION:
        raise AdapterBlock(
            REASON_SCHEMA_VERSION,
            '模块 {0} 的 schema_version={1!r} 与契约 {2!r} 不兼容'.format(
                name, version, CONTRACT_VERSION))

    errors = vtc.validate_document(document, vtc.load_schema(interface))
    if errors:
        raise AdapterBlock(
            REASON_SCHEMA_INVALID,
            '模块 {0} 输出不符合 {1}: {2}'.format(name, interface, '; '.join(errors[:3])))

    record['schema_ok'] = True
    record['status'] = document.get('status')
    return document, record


def terminate_process_group(proc, record: dict) -> str:
    """终止本次调用自己的进程组，并始终回收子进程。

    只操作本进程组：绝不按名称 pkill，也绝不停止 Docker 容器。
    即使清理失败，也要如实记录并保持阻断结论。
    """
    outcome = 'terminated'
    pgid = record.get('pgid')
    try:
        if pgid:
            os.killpg(pgid, signal.SIGTERM)
        else:
            proc.terminate()
    except ProcessLookupError:
        outcome = 'already_gone'
    except OSError as exc:
        outcome = 'term_failed:{0}'.format(errno.errorcode.get(exc.errno, exc.errno))
        log_line('进程组终止失败: {0}'.format(exc))

    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            if pgid:
                os.killpg(pgid, signal.SIGKILL)
            else:
                proc.kill()
            outcome += '+killed'
        except (ProcessLookupError, OSError) as exc:
            outcome += '+kill_failed:{0}'.format(exc)
            log_line('进程组强制终止失败: {0}'.format(exc))
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            outcome += '+unreaped'
            log_line('子进程未能回收（记录为清理失败）')
    # 关闭管道，避免资源泄漏
    for stream in (proc.stdin, proc.stdout, proc.stderr):
        try:
            if stream:
                stream.close()
        except OSError:
            pass
    return outcome


# ---------------------------------------------------------------- 一致性
def check_consistency(envelope: dict, outputs: dict) -> None:
    """跨模块关联检查（阶段 C 的语义规则在运行时的落实）。"""
    expected_request = envelope.get('request_id')
    expected_run = envelope.get('run_id')
    action = envelope.get('candidate_action') or {}
    expected_task = action.get('task_id')
    expected_action = action.get('action_resource')

    seen_events = {}
    for name in MODULE_ORDER:
        document = outputs[name]
        if document.get('request_id') != expected_request:
            raise AdapterBlock(
                REASON_CONSISTENCY_REQUEST_ID,
                '模块 {0} 的 request_id={1!r} 与输入 {2!r} 不一致（不得串单）'.format(
                    name, document.get('request_id'), expected_request))
        if document.get('run_id') != expected_run:
            raise AdapterBlock(
                REASON_CONSISTENCY_RUN_ID,
                '模块 {0} 的 run_id={1!r} 与输入 {2!r} 不一致'.format(
                    name, document.get('run_id'), expected_run))

        event_id = document.get('event_id')
        if event_id in seen_events:
            raise AdapterBlock(
                REASON_CONSISTENCY_EVENT_ID,
                'event_id 重复: {0!r} 同时出现在 {1} 与 {2}'.format(
                    event_id, seen_events[event_id], name))
        seen_events[event_id] = name

        if 'task_id' in document and document['task_id'] != expected_task:
            raise AdapterBlock(
                REASON_CONSISTENCY_TASK_ID,
                '模块 {0} 的 task_id={1!r} 与输入 {2!r} 不一致'.format(
                    name, document.get('task_id'), expected_task))

        candidate = document.get('candidate_action')
        if isinstance(candidate, dict):
            if candidate.get('action_resource') != expected_action:
                raise AdapterBlock(
                    REASON_CONSISTENCY_ACTION,
                    '模块 {0} 的 action_resource={1!r} 与输入 {2!r} 不一致'.format(
                        name, candidate.get('action_resource'), expected_action))


def check_action_boundary(envelope: dict) -> None:
    """纵深防御：候选操作只能指向准入入口，绝不允许指向执行端。"""
    action = envelope.get('candidate_action') or {}
    resource = action.get('action_resource')
    if resource != GUARDED_ACTION:
        raise AdapterBlock(
            REASON_INPUT_INVALID,
            '候选操作入口必须是 {0}，实际为 {1!r}；'
            '上游不得选择执行端资源'.format(GUARDED_ACTION, resource))


# ---------------------------------------------------------------- 主流程
def run(envelope_text: str, config_path: str, log_path: str, workdir: str) -> dict:
    invocation_id = uuid.uuid4().hex[:12]
    result = {
        'adapter_version': ADAPTER_VERSION,
        'contract_version': CONTRACT_VERSION,
        'invocation_id': invocation_id,
        'checked_at': now_iso(),
        'decision': 'ADAPTER_BLOCK',
        'reason_code': REASON_INPUT_INVALID,
        'detail': '',
        'run_id': None,
        'request_id': None,
        'modules': [],
        'note': ('本结果仅表示适配层的候选输入检查结论；'
                 'READY_FOR_GATEWAY_SUBMISSION 不代表 Gateway 已允许，'
                 '也不代表下游已执行。本层不提交真实 Action。'),
    }

    try:
        envelope = vtc.load_json_strict_text(envelope_text, '输入信封')
    except ValueError as exc:
        result['detail'] = '输入信封解析失败（重复键或非有限数值等）: {0}'.format(exc)
        return result

    result['run_id'] = envelope.get('run_id')
    result['request_id'] = envelope.get('request_id')

    try:
        errors = vtc.validate_document(envelope, vtc.load_schema('module_input'))
        if errors:
            raise AdapterBlock(REASON_INPUT_INVALID,
                               '输入信封不符合 module_input schema: {0}'.format(
                                   '; '.join(errors[:3])))
        check_action_boundary(envelope)

        config = load_config(config_path)
        modules = config['modules']

        outputs = {}
        for name in MODULE_ORDER:
            document, _record = invoke_module(
                name, modules[name], envelope_text, workdir, invocation_id,
                result['modules'])
            outputs[name] = document

        check_consistency(envelope, outputs)

        # 唯一推进条件：三个状态必须同时成立
        for name in MODULE_ORDER:
            status = outputs[name].get('status')
            if status != PROCEED_STATES[name]:
                raise AdapterBlock(
                    REASON_NOT_PROCEED,
                    '模块 {0} 状态为 {1!r}，不是允许推进的 {2!r}；'
                    '本地阻断，不进入提交流程'.format(
                        name, status, PROCEED_STATES[name]))

        result['decision'] = 'READY_FOR_GATEWAY_SUBMISSION'
        result['reason_code'] = REASON_OK
        result['detail'] = '三个模块状态均为推进状态且全部校验通过'
    except AdapterBlock as block:
        result['decision'] = 'ADAPTER_BLOCK'
        result['reason_code'] = block.reason_code
        result['detail'] = block.detail
    except Exception as exc:  # noqa: BLE001
        result['decision'] = 'ADAPTER_BLOCK'
        result['reason_code'] = 'ADAPTER_INTERNAL_ERROR'
        result['detail'] = '{0}: {1}'.format(type(exc).__name__, exc)

    if any(record.get('cleanup', '').endswith(('unreaped',)) or
           'failed' in record.get('cleanup', '') for record in result['modules']):
        result['decision'] = 'ADAPTER_BLOCK'
        result['reason_code'] = REASON_CLEANUP_FAILED
        result['detail'] = '进程清理失败，维持阻断结论'

    return result


def append_log(log_path: str, result: dict) -> None:
    try:
        directory = os.path.dirname(log_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(log_path, 'a', encoding='utf-8') as handle:
            handle.write(json.dumps(result, ensure_ascii=False) + '\n')
    except OSError as exc:
        log_line('写入适配层日志失败: {0}'.format(exc))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description='F0 模块安全适配层：只判定候选输入是否可进入后续提交流程')
    parser.add_argument('--config', default=os.path.join(
        REPO_ROOT, 'config', 'team_modules.example.yaml'),
        help='受信任的模块配置（模块命令只能来自此处）')
    parser.add_argument('--input', default='-',
                        help='输入信封 JSON 文件；- 表示从 stdin 读取')
    parser.add_argument('--log', default=os.path.join(
        REPO_ROOT, 'logs', 'team_adapter.jsonl'),
        help='适配层调用记录（JSONL，与模块 stdout 分离）')
    parser.add_argument('--workdir', default=REPO_ROOT,
                        help='模块进程的工作目录')
    args = parser.parse_args(argv)

    if args.input == '-':
        envelope_text = sys.stdin.read()
    else:
        try:
            with open(args.input, 'r', encoding='utf-8') as handle:
                envelope_text = handle.read()
        except OSError as exc:
            log_line('无法读取输入文件: {0}'.format(exc))
            print(json.dumps({'decision': 'ADAPTER_BLOCK',
                              'reason_code': REASON_INPUT_INVALID,
                              'detail': '无法读取输入文件: {0}'.format(exc)},
                             ensure_ascii=False))
            return EXIT_INPUT_INVALID

    try:
        result = run(envelope_text, args.config, args.log, args.workdir)
    except AdapterBlock as block:
        result = {'adapter_version': ADAPTER_VERSION, 'decision': 'ADAPTER_BLOCK',
                  'reason_code': block.reason_code, 'detail': block.detail,
                  'modules': []}

    append_log(args.log, result)

    # stdout 只输出最终结果 JSON：调用方（含未来 D2 集成）可安全解析
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if result['decision'] == 'READY_FOR_GATEWAY_SUBMISSION':
        return EXIT_READY
    if result['reason_code'] in (REASON_CONFIG_INVALID,):
        return EXIT_CONFIG_INVALID
    if result['reason_code'] in (REASON_INPUT_INVALID,):
        return EXIT_INPUT_INVALID
    return EXIT_BLOCK


if __name__ == '__main__':
    sys.exit(main())
