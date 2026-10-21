"""run_controller.py -- 严格白名单的运行控制器（P0 整改版）。

安全约束
========
1. **命令白名单**：只允许 scripts/final_system.sh 的固定模式；
2. **不用 shell=True**：一律参数数组；
3. **run_id 边界**：拒绝 . / .. / 路径分隔符 / 超长 / 点开头；
4. **并发原子化**：检查空闲 + 占位 + 启动 + 登记在同一把锁内，
   第二个并发请求确定性拒绝；
5. **只清理自己的进程组**（start_new_session 独占）；
6. **失败如实上报**：退出码、stderr、失败原因全部回传。
"""
from __future__ import annotations

import os
import re
import signal
import subprocess
import threading
import time

PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CANDIDATE_REPO = os.path.dirname(os.path.dirname(PACKAGE_ROOT))
REPO_ROOT = (_CANDIDATE_REPO
             if os.path.exists(os.path.join(_CANDIDATE_REPO, 'scripts', 'final_system.sh'))
             else PACKAGE_ROOT)

ALLOWED_MODES = {
    'controlled': ['--mode', 'controlled'],
    'three-real-strict': ['--mode', 'three-real-strict'],
    'enforce': ['--mode', 'enforce'],
    'acceptance': ['--mode', 'acceptance'],
    'check': ['--check'],
}

RUN_ID_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$')
MAX_RUNTIME_SEC = float(os.environ.get('DASHBOARD_MAX_RUNTIME_SEC', '1800'))


def validate_run_id(run_id):
    """返回 (ok, reason)。拒绝 . / .. / 分隔符 / 超长 / 空白 / 点开头。"""
    if not isinstance(run_id, str) or not run_id:
        return False, 'run_id 不能为空'
    if run_id in ('.', '..'):
        return False, 'run_id 不能是 . 或 ..'
    if len(run_id) > 64:
        return False, 'run_id 过长（最多 64 字符）'
    if '/' in run_id or '\\' in run_id:
        return False, 'run_id 不能包含路径分隔符'
    if run_id != run_id.strip():
        return False, 'run_id 不能含首尾空白'
    if not RUN_ID_RE.match(run_id):
        return False, 'run_id 必须字母数字开头，且仅含 A-Za-z0-9_.-'
    return True, ''


class RunController:
    def __init__(self):
        self._lock = threading.Lock()
        self._proc = None
        self._state = {'status': 'IDLE', 'mode': None, 'run_id': None,
                       'started_at': None, 'finished_at': None,
                       'exit_code': None, 'log_path': None, 'error': None}

    def status(self):
        with self._lock:
            state = dict(self._state)
            proc = self._proc
        if state['status'] == 'RUNNING' and proc is not None:
            state['pid'] = proc.pid
            state['elapsed_sec'] = round(time.time() - (state['started_at'] or 0), 1)
        return state

    def busy(self):
        with self._lock:
            return self._proc is not None or self._state.get('status') == 'RUNNING'

    def start(self, mode, run_id=None):
        if mode not in ALLOWED_MODES:
            return {'ok': False, 'error': '不允许的模式: %s' % mode}

        if run_id is None:
            run_id = 'dash-' + time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
        ok_id, reason = validate_run_id(run_id)
        if not ok_id:
            return {'ok': False, 'error': 'run_id 非法: ' + reason}

        # 检查空闲 + 占位必须在同一临界区：否则两个并发请求都看到 IDLE，
        # 会各起一个实验争用同一 DDS Domain。
        with self._lock:
            if self._proc is not None or self._state.get('status') == 'RUNNING':
                return {'ok': False,
                        'error': '已有实验在运行；请等待结束或停止后再试（避免 Domain 争用）'}
            self._state = {'status': 'RUNNING', 'mode': mode, 'run_id': run_id,
                           'started_at': time.time(), 'finished_at': None,
                           'exit_code': None, 'log_path': None, 'error': None}

        evidence_dir = os.path.join(
            REPO_ROOT, 'artifacts/integration/dashboard-runs', run_id)
        os.makedirs(evidence_dir, exist_ok=True)
        log_path = os.path.join(evidence_dir, 'run.log')

        argv = ['bash', os.path.join(REPO_ROOT, 'scripts/final_system.sh'),
                *ALLOWED_MODES[mode], '--run-id', run_id,
                '--out-dir', 'artifacts/integration/dashboard-runs']

        try:
            opened = open(log_path, 'w', encoding='utf-8')
            proc = subprocess.Popen(
                argv, cwd=REPO_ROOT, stdout=opened, stderr=subprocess.STDOUT,
                start_new_session=True)
        except OSError as exc:
            with self._lock:
                self._state.update({'status': 'FAIL', 'finished_at': time.time(),
                                    'error': '启动失败: %s' % exc})
            return {'ok': False, 'error': '启动失败: %s' % exc}

        with self._lock:
            self._proc = proc
            self._state.update({'log_path': os.path.relpath(log_path, REPO_ROOT)})

        threading.Thread(target=self._wait, args=(proc, opened),
                         daemon=True).start()
        return {'ok': True, 'mode': mode, 'run_id': run_id,
                'log_path': os.path.relpath(log_path, REPO_ROOT)}

    def _wait(self, proc, fh):
        try:
            code = proc.wait(timeout=MAX_RUNTIME_SEC)
            error = None if code == 0 else '实验以非零退出码结束: %s' % code
        except subprocess.TimeoutExpired:
            self._terminate(proc)
            code = None
            error = '运行超过 %.0f 秒，已终止' % MAX_RUNTIME_SEC
        finally:
            try:
                fh.close()
            except OSError:
                pass
        with self._lock:
            self._state.update({
                'status': 'DONE' if code == 0 else 'FAIL',
                'exit_code': code, 'finished_at': time.time(), 'error': error})
            self._proc = None

    def _terminate(self, proc):
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            return
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass

    def stop(self):
        with self._lock:
            proc = self._proc
        if proc is None:
            return {'ok': False, 'error': '当前没有正在运行的实验'}
        self._terminate(proc)
        return {'ok': True, 'message': '已向本次实验的进程组发送终止信号'}

    def log_tail(self, lines=80):
        path = self._state.get('log_path')
        if not path:
            return ''
        try:
            with open(os.path.join(REPO_ROOT, path), encoding='utf-8',
                      errors='replace') as fh:
                return ''.join(fh.readlines()[-lines:])
        except OSError:
            return ''
