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
import resource
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
REASON_AUDIT_WRITE_FAILED = 'ADAPTER_AUDIT_WRITE_FAILED'
REASON_INPUT_TOO_LARGE = 'ADAPTER_INPUT_TOO_LARGE'

# 唯一推进条件：三个接口必须分别处于下列状态
PROCEED_STATES = {
    'comm_risk': 'NORMAL',
    'identity_trust': 'AUTHORIZED',
    'task_risk': 'ALLOW_RECOMMENDED',
}

# 模块调用顺序固定，避免执行顺序影响结论
MODULE_ORDER = ('comm_risk', 'identity_trust', 'task_risk')

GUARDED_ACTION = '/rg/guarded_navigate'

# ---------------------------------------------------------------- 在线模式
# 只有显式 --online 才会启动 Planner。默认保持 D1 的纯离线判定行为。
ONLINE_PLANNER_NOT_STARTED = 'PLANNER_NOT_STARTED'
ONLINE_NO_ACTION_SERVER = 'PLANNER_NO_ACTION_SERVER'
ONLINE_GOAL_NOT_ACCEPTED = 'PLANNER_GOAL_NOT_ACCEPTED'
ONLINE_GOAL_ACCEPTANCE_TIMEOUT = 'PLANNER_GOAL_ACCEPTANCE_TIMEOUT'
ONLINE_RESULT_TIMEOUT = 'PLANNER_RESULT_TIMEOUT'
ONLINE_RESULT_RECEIVED = 'PLANNER_RESULT_RECEIVED'
ONLINE_SPAWN_FAILED = 'PLANNER_SPAWN_FAILED'

PLANNER_OUTCOME_MAP = {
    'NO_ACTION_SERVER': ONLINE_NO_ACTION_SERVER,
    'GOAL_REJECTED': ONLINE_GOAL_NOT_ACCEPTED,
    'GOAL_ACCEPTANCE_TIMEOUT': ONLINE_GOAL_ACCEPTANCE_TIMEOUT,
    'RESULT_TIMEOUT': ONLINE_RESULT_TIMEOUT,
    'RESULT': ONLINE_RESULT_RECEIVED,
}

DEFAULT_STDOUT_LIMIT = 65536
DEFAULT_STDERR_LIMIT = 16384
DEFAULT_TIMEOUT = 10.0
# 输入信封与服务端参数的合理上限（防止配置写出明显失真的值）
MAX_TIMEOUT_SEC = 3600.0
MAX_OUTPUT_LIMIT = 16 * 1024 * 1024
MAX_STDERR_LIMIT = 1024 * 1024
MAX_INPUT_BYTES = 1024 * 1024

# 每个模块位置只接受对应的接口，避免"位置与接口不匹配"的错配配置
EXPECTED_INTERFACE = {
    'comm_risk': 'comm_risk_evidence',
    'identity_trust': 'identity_trust_assessment',
    'task_risk': 'task_risk_decision',
}
ALLOWED_MODES = ('mock', 'external', 'double')


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
        # 位置与接口必须匹配：防止把身份模块的输出当成通信证据使用
        if interface != EXPECTED_INTERFACE[name]:
            raise AdapterBlock(
                REASON_CONFIG_INVALID,
                '模块 {0} 的 interface 应为 {1!r}，配置为 {2!r}；'
                '位置与接口错配会把一种证据当成另一种证据使用'.format(
                    name, EXPECTED_INTERFACE[name], interface))

        mode = entry.get('mode', 'mock')
        if mode not in ALLOWED_MODES:
            raise AdapterBlock(REASON_CONFIG_INVALID,
                               '模块 {0} 的 mode 无效: {1!r}（可选 {2}）'.format(
                                   name, mode, list(ALLOWED_MODES)))

        # 故障注入开关必须是真正的布尔值：字符串 'false' 会被当成真值，
        # 从而在"看起来关掉了"的配置里意外开启故障注入。
        fault_flag = entry.get('allow_fault_injection', False)
        if not isinstance(fault_flag, bool):
            raise AdapterBlock(
                REASON_CONFIG_INVALID,
                '模块 {0} 的 allow_fault_injection 必须是布尔值（当前 {1!r}）；'
                '字符串会被当作真值，导致故障注入被意外开启'.format(name, fault_flag))

        timeout = _require_number(name, 'timeout_sec', entry.get('timeout_sec',
                                                                DEFAULT_TIMEOUT),
                                  0.0, MAX_TIMEOUT_SEC, integer=False)
        limit = _require_number(name, 'max_stdout_bytes',
                                entry.get('max_stdout_bytes', DEFAULT_STDOUT_LIMIT),
                                0, MAX_OUTPUT_LIMIT, integer=True)
        _require_number(name, 'max_stderr_bytes',
                        entry.get('max_stderr_bytes', DEFAULT_STDERR_LIMIT),
                        0, MAX_STDERR_LIMIT, integer=True)
    return config


def _require_number(module: str, field: str, value, low, high, *, integer: bool):
    """校验数值型配置：拒绝布尔、非有限数值与越界值。

    为什么必须显式拒绝布尔：Python 中 `True == 1`，`isinstance(True, int)` 为真。
    若不排除布尔，`timeout_sec: true` 会被当成 1 秒静默接受。
    为什么要拒绝 NaN/Infinity：它们能通过 `> 0` 之外的任何朴素比较，
    会让超时逻辑永远不触发或立即触发。
    """
    if isinstance(value, bool):
        raise AdapterBlock(REASON_CONFIG_INVALID,
                           '模块 {0} 的 {1} 不能是布尔值（当前 {2!r}）'.format(
                               module, field, value))
    if integer:
        if not isinstance(value, int):
            raise AdapterBlock(REASON_CONFIG_INVALID,
                               '模块 {0} 的 {1} 必须是整数（当前 {2!r}）'.format(
                                   module, field, value))
    else:
        if not isinstance(value, (int, float)):
            raise AdapterBlock(REASON_CONFIG_INVALID,
                               '模块 {0} 的 {1} 必须是数值（当前 {2!r}）'.format(
                                   module, field, value))
        if value != value or value in (float('inf'), float('-inf')):
            raise AdapterBlock(REASON_CONFIG_INVALID,
                               '模块 {0} 的 {1} 必须是有限数值（当前 {2!r}）'.format(
                                   module, field, value))
    if value <= low or value > high:
        raise AdapterBlock(
            REASON_CONFIG_INVALID,
            '模块 {0} 的 {1} 必须在 ({2}, {3}] 范围内（当前 {4!r}）'.format(
                module, field, low, high, value))
    return value


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
def read_bounded(proc, stdin_bytes: bytes, timeout: float,
                 max_stdout: int, max_stderr: int):
    """在读取过程中限制子进程输出，而不是读完再检查。

    为什么必须这样做
    ----------------
    `subprocess.communicate()` 会先把 stdout/stderr **全部读入内存**，
    然后调用方才有机会检查长度。一个持续输出的模块因此可以在大小检查生效前
    就把适配层的内存吃光 —— `max_stdout_bytes` 形同虚设。

    本函数用 selector 边读边计数：
      * stdout 超过 max_stdout        -> 立即终止并报 STDOUT_TOO_LARGE
      * stderr 超过 max_stderr        -> **继续排空但只保留前 max_stderr 字节**
                                         （排空是必要的，否则子进程会因管道写满而阻塞）
      * 总时长超过 timeout            -> 立即终止并报 TIMEOUT
      * 输入无法写入（子进程提前退出）-> 记录但不视为模块成功

    返回 (stdout_bytes, stderr_bytes, exceeded) ，其中 exceeded 为 None 或原因标签。
    调用方负责在 exceeded 非空时终止进程组。
    """
    import selectors

    deadline = time.monotonic() + timeout
    out_chunks = []
    err_chunks = []
    out_size = 0
    err_size = 0          # 实际接收量（用于判断是否需要继续排空）
    err_kept = 0          # 实际保留量
    exceeded = None

    stdin_data = stdin_bytes
    selector = selectors.DefaultSelector()
    try:
        for stream, label in ((proc.stdout, 'stdout'), (proc.stderr, 'stderr')):
            if stream is not None:
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, label)
    except (OSError, ValueError) as exc:
        exceeded = 'SETUP_FAILED:{0}'.format(exc)
        return b'', b'', exceeded

    open_streams = 2
    try:
        while open_streams > 0:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                exceeded = 'TIMEOUT'
                break

            # 先尽力写 stdin（非阻塞写同样可能因管道满而阻塞，因此限量写）
            if stdin_data:
                try:
                    written = os.write(proc.stdin.fileno(), stdin_data)
                    stdin_data = stdin_data[written:]
                except BlockingIOError:
                    pass
                except (BrokenPipeError, OSError, ValueError):
                    # 子进程提前关闭 stdin：不是致命错误，继续读取输出
                    stdin_data = b''
                if not stdin_data:
                    try:
                        proc.stdin.close()
                    except (OSError, ValueError):
                        pass

            for key, _events in selector.select(timeout=min(0.2, max(remaining, 0.01))):
                stream = key.fileobj
                label = key.data
                try:
                    chunk = stream.read(65536)
                except (BlockingIOError, InterruptedError):
                    continue
                except (OSError, ValueError):
                    chunk = b''
                if not chunk:
                    selector.unregister(stream)
                    open_streams -= 1
                    continue
                if label == 'stdout':
                    out_size += len(chunk)
                    if out_size > max_stdout:
                        # 关键：一旦超限立即停止，不再继续缓冲
                        exceeded = 'STDOUT_TOO_LARGE'
                        out_chunks.append(chunk[:max(0, max_stdout - (out_size - len(chunk)))])
                        break
                    out_chunks.append(chunk)
                else:
                    err_size += len(chunk)
                    if err_kept < max_stderr:
                        keep = chunk[:max_stderr - err_kept]
                        err_chunks.append(keep)
                        err_kept += len(keep)
                    # 超限的 stderr 只丢弃不保留，但仍持续排空
            if exceeded:
                break
    finally:
        try:
            selector.close()
        except Exception:  # noqa: BLE001
            pass
        if stdin_data:
            try:
                proc.stdin.close()
            except (OSError, ValueError):
                pass

    return b''.join(out_chunks), b''.join(err_chunks), exceeded


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

    stdin_bytes = envelope_text.encode('utf-8')
    if len(stdin_bytes) > MAX_INPUT_BYTES:
        record['cleanup'] = terminate_process_group(proc, record)
        raise AdapterBlock(
            REASON_INPUT_TOO_LARGE,
            '模块 {0} 的输入 {1} 字节超过上限 {2}'.format(
                name, len(stdin_bytes), MAX_INPUT_BYTES))

    stderr_limit = int(entry.get('max_stderr_bytes', DEFAULT_STDERR_LIMIT))
    out, err, exceeded = read_bounded(proc, stdin_bytes, timeout, limit, stderr_limit)
    record['duration_ms'] = int((time.monotonic() - started) * 1000)
    record['stderr_bytes_kept'] = len(err)

    if exceeded == 'TIMEOUT':
        record['cleanup'] = terminate_process_group(proc, record)
        raise AdapterBlock(
            REASON_TIMEOUT,
            '模块 {0} 超时（{1}s），已终止本次调用的进程组；'
            '本次调用不产生任何允许结论'.format(name, timeout))
    if exceeded == 'STDOUT_TOO_LARGE':
        # 超限即终止：不等待子进程把剩余数据写完，也不把剩余输出读进内存
        record['cleanup'] = terminate_process_group(proc, record)
        record['stdout_bytes'] = len(out)
        raise AdapterBlock(
            REASON_TOO_LARGE,
            '模块 {0} 的 stdout 超过上限 {1} 字节（读取过程中即终止，'
            '未完整缓冲）'.format(name, limit))
    if exceeded:
        record['cleanup'] = terminate_process_group(proc, record)
        raise AdapterBlock(
            REASON_INTERNAL if exceeded.startswith('SETUP_FAILED') else REASON_STDOUT_INVALID,
            '模块 {0} 输出读取异常: {1}'.format(name, exceeded))

    # 正常路径：等待退出并回收
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        record['cleanup'] = terminate_process_group(proc, record)
        raise AdapterBlock(
            REASON_TIMEOUT,
            '模块 {0} 在输出关闭后仍未退出，已终止本次调用的进程组'.format(name))
    record['exit_code'] = proc.returncode
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
def build_planner_argv(planner_command, envelope: dict) -> list:
    """从**同一份已校验的内存对象**构造 Planner 参数。

    安全要点
    --------
    * 只做字段映射，不重定义业务语义：
      candidate_action.task_id / request_id / target.{frame_id,x,y,z}
      对应 PatrolNavigate.Goal 的 task_id / request_id / target(PoseStamped)。
    * 参数来自已经通过 Schema 校验与一致性校验的 `envelope` 对象本身，
      **不重新读取输入文件** —— 否则文件可能在"校验通过"与"提交"之间被改写
      （TOCTOU），出现"校验的是 A、提交的是 B"。
    * 不使用任何可被外部伪造的 READY 令牌：推进资格由本进程内的判定结果决定。
    * z 缺失时保持 Planner 自身的默认值语义（不虚构位置）。
    """
    action = envelope.get('candidate_action') or {}
    target = action.get('target') or {}
    argv = list(planner_command) + [
        '--ros-args',
        '-p', 'task_id:={0}'.format(action.get('task_id')),
        '-p', 'request_id:={0}'.format(envelope.get('request_id')),
        '-p', 'frame_id:={0}'.format(target.get('frame_id')),
        '-p', 'target_x:={0}'.format(float(target.get('x', 0.0))),
        '-p', 'target_y:={0}'.format(float(target.get('y', 0.0))),
    ]
    if 'z' in target and target.get('z') is not None:
        argv += ['-p', 'target_z:={0}'.format(float(target['z']))]
    return argv


def submit_online(planner_command, envelope: dict, planner_timeout: float,
                  online_log: dict) -> dict:
    """启动已有 Planner，解析其真实返回。

    本函数**不判断** Gateway 是否允许：Planner 进程返回码为 0 并不代表 Gateway ALLOW。
    最终判定必须结合 Gateway 的 DecisionEvent（由验收脚本读取审计日志核对）。
    这里只如实记录 Planner 的 outcome / status_code / success。
    """
    argv = build_planner_argv(planner_command, envelope)
    online_log['planner_command'] = argv
    online_log['planner_timeout_sec'] = planner_timeout

    started = time.monotonic()
    try:
        proc = subprocess.Popen(argv, cwd=online_log.get('workdir', REPO_ROOT),
                                shell=False, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                start_new_session=True)
    except FileNotFoundError as exc:
        online_log['outcome'] = ONLINE_PLANNER_NOT_STARTED
        online_log['detail'] = 'Planner 可执行文件不存在: {0}'.format(exc)
        return online_log
    except OSError as exc:
        online_log['outcome'] = ONLINE_SPAWN_FAILED
        online_log['detail'] = 'Planner 无法启动: {0}'.format(exc)
        return online_log

    online_log['planner_pid'] = proc.pid
    try:
        online_log['planner_pgid'] = os.getpgid(proc.pid)
    except OSError:
        online_log['planner_pgid'] = None

    record = {'pid': proc.pid, 'pgid': online_log.get('planner_pgid')}
    out, err, exceeded = read_bounded(proc, b'', planner_timeout,
                                      256 * 1024, DEFAULT_STDERR_LIMIT)
    online_log['duration_ms'] = int((time.monotonic() - started) * 1000)
    online_log['stderr_tail'] = err.decode('utf-8', 'replace')[-800:]

    if exceeded == 'TIMEOUT':
        online_log['cleanup'] = terminate_process_group(proc, record)
        online_log['outcome'] = ONLINE_RESULT_TIMEOUT
        online_log['detail'] = (
            'Planner 在 {0}s 内未给出终态。**该请求可能已经到达 Gateway，'
            '甚至已到达下游执行端**；不自动重试、不新建 request_id、'
            '不记为 Gateway BLOCK。请依据 Gateway 审计记录核对。'.format(planner_timeout))
        return online_log

    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        online_log['cleanup'] = terminate_process_group(proc, record)
    online_log['planner_exit_code'] = proc.returncode

    payload = None
    for line in out.decode('utf-8', 'replace').splitlines():
        if line.startswith('PLANNER_RESULT '):
            try:
                payload = json.loads(line[len('PLANNER_RESULT '):])
            except ValueError:
                payload = None
    if payload is None:
        online_log['outcome'] = ONLINE_RESULT_TIMEOUT
        online_log['detail'] = 'Planner 未输出可解析的 PLANNER_RESULT'
        return online_log

    online_log['planner_result'] = payload
    outcome = str(payload.get('outcome', 'UNKNOWN'))
    online_log['outcome'] = PLANNER_OUTCOME_MAP.get(outcome, 'PLANNER_' + outcome)
    online_log['detail'] = str(payload.get('detail', ''))
    # 原样保留业务字段，不做任何"等价改写"
    for field in ('status_code', 'success', 'goal_id', 'goal_status', 'accepted'):
        if field in payload:
            online_log[field] = payload[field]
    return online_log


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
def run(envelope_text: str, config_path: str, log_path: str, workdir: str,
        online: dict = None) -> dict:
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
        # 自报峰值内存：用于证明有界读取确实生效（无界缓冲会让该值随模块输出增长）
        'adapter_peak_rss_kb': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
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

    result['adapter_peak_rss_kb'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    # H2：审计记录是推进的前置条件。顺序很重要 —— 先写审计，再据其成败决定结论。
    ok, detail = append_log(log_path, result)
    result['audit_written'] = bool(ok)
    if not ok:
        result['audit_error'] = detail
        if result['decision'] == 'READY_FOR_GATEWAY_SUBMISSION':
            result['decision'] = 'ADAPTER_BLOCK'
            result['reason_code'] = REASON_AUDIT_WRITE_FAILED
            result['detail'] = (
                '适配层审计记录写入失败（{0}）；'
                '缺少必要审计证据时不得进入后续提交流程'.format(detail))
        return result

    # 写回一条"已记录"的结果，便于事后核对本次调用确已入账
    append_log(log_path, {
        'invocation_id': invocation_id,
        'audit_confirm': True,
        'decision': result['decision'],
        'reason_code': result['reason_code'],
        'run_id': result.get('run_id'),
        'request_id': result.get('request_id'),
    })

    # ---------------------------------------------------------- 在线提交
    # 顺序不可颠倒：只有适配判定为 READY **且**审计已成功落库之后，
    # 才允许把候选请求交给 Planner。审计失败路径在上方已 return，不会到达这里。
    online = online or {}
    result['online'] = {'enabled': bool(online.get('enabled'))}
    if not online.get('enabled'):
        return result

    if result['decision'] != 'READY_FOR_GATEWAY_SUBMISSION':
        result['online'].update({
            'submitted': False,
            'outcome': 'NOT_SUBMITTED_ADAPTER_BLOCK',
            'detail': '适配层未通过推进条件，因此不启动 Planner、不发送任何 Goal',
        })
        append_log(log_path, {'invocation_id': invocation_id,
                              'online': result['online']})
        return result

    # envelope 是上面已通过 Schema 与一致性校验的**同一个内存对象**，
    # 不从文件重读，避免 TOCTOU。
    online_log = {'enabled': True, 'submitted': True, 'workdir': workdir,
                  'run_id': envelope.get('run_id'),
                  'request_id': envelope.get('request_id')}
    submit_online(list(online.get('planner_command') or []), envelope,
                  float(online.get('planner_timeout_sec', 30.0)), online_log)
    result['online'] = online_log
    append_log(log_path, {'invocation_id': invocation_id, 'online': online_log})
    return result


def append_log(log_path: str, result: dict):
    """写入适配层审计记录，返回 (ok, detail)。

    H2：审计可靠性是安全边界的一部分。
    一旦本函数失败，调用方**必须**把 READY 降级为阻断 —— 否则会出现
    "需要留存适配证据的请求却没有证据，却照样进入 Gateway"的情况。
    这里只如实报告失败，绝不伪造"已经写入成功"。
    """
    try:
        directory = os.path.dirname(log_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        if os.path.isdir(log_path):
            raise IsADirectoryError('日志路径是一个目录: {0}'.format(log_path))
        with open(log_path, 'a', encoding='utf-8') as handle:
            handle.write(json.dumps(result, ensure_ascii=False) + '\n')
            handle.flush()
            os.fsync(handle.fileno())
        return True, ''
    except (OSError, ValueError, TypeError) as exc:
        detail = '{0}: {1}'.format(type(exc).__name__, exc)
        log_line('写入适配层审计记录失败: {0}'.format(detail))
        return False, detail


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
    parser.add_argument('--online', action='store_true',
                        help='在线模式：适配判定为 READY 且审计落库后，'
                             '启动已有 Planner 提交到 /rg/guarded_navigate。'
                             '默认关闭，保持纯离线判定。')
    parser.add_argument('--planner-timeout', type=float, default=30.0,
                        help='在线提交的独立超时（与模块超时不是同一概念）')
    args = parser.parse_args(argv)

    # workdir 只能来自受信任的本地命令行参数，且必须是绝对路径下真实存在的目录。
    # 绝不从业务输入 JSON 读取（输入无法影响模块的工作目录）。
    if not os.path.isabs(args.workdir) or not os.path.isdir(args.workdir):
        log_line('workdir 必须是存在的绝对路径: {0!r}'.format(args.workdir))
        print(json.dumps({'decision': 'ADAPTER_BLOCK',
                          'reason_code': REASON_CONFIG_INVALID,
                          'detail': 'workdir 必须是存在的绝对路径: {0!r}'.format(
                              args.workdir)}, ensure_ascii=False))
        return EXIT_CONFIG_INVALID

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

    online = {'enabled': False}
    if args.online:
        try:
            _cfg = load_config(args.config)
        except AdapterBlock as block:
            print(json.dumps({'decision': 'ADAPTER_BLOCK',
                              'reason_code': block.reason_code,
                              'detail': block.detail}, ensure_ascii=False))
            return EXIT_CONFIG_INVALID
        planner_command = (_cfg.get('adapter') or {}).get('planner_command')
        if not isinstance(planner_command, list) or not planner_command or \
                not all(isinstance(part, str) and part for part in planner_command):
            log_line('在线模式需要 adapter.planner_command（非空字符串数组）')
            print(json.dumps({'decision': 'ADAPTER_BLOCK',
                              'reason_code': REASON_CONFIG_INVALID,
                              'detail': '在线模式需要 adapter.planner_command，'
                                        '且必须是参数数组'}, ensure_ascii=False))
            return EXIT_CONFIG_INVALID
        online = {'enabled': True, 'planner_command': planner_command,
                  'planner_timeout_sec': args.planner_timeout}

    try:
        result = run(envelope_text, args.config, args.log, args.workdir, online)
    except AdapterBlock as block:
        result = {'adapter_version': ADAPTER_VERSION, 'decision': 'ADAPTER_BLOCK',
                  'reason_code': block.reason_code, 'detail': block.detail,
                  'modules': []}

    # 审计记录已在 run() 内完成（含失败降级）；此处不再重复写入。

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
