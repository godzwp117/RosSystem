"""run_controller.py -- 严格白名单的运行控制器。

安全约束
========
1. **命令白名单**：只允许调用 `scripts/final_system.sh` 的固定模式，
   用户不能提交任意 shell 命令，也不拼接字符串到 shell。
2. **不用 shell=True**：一律 `subprocess.Popen([...])` 传参数数组。
3. **run_id 校验**：只允许 `[A-Za-z0-9_.-]{1,64}`，防止路径注入。
4. **并发限制**：同一时刻只允许一个实验运行（离线/在线共用一把锁），
   避免两个实验争用同一个 DDS Domain。
5. **只清理自己启动的进程**：记录 PID/PGID，结束只对自己的进程组发信号。
6. **失败如实上报**：退出码、stdout/stderr、失败原因全部回传前端。

本控制器**不实现任何安全判断**，只负责触发既有入口并回收结果。
"""
from __future__ import annotations

import os
import re
import signal
import subprocess
import threading
import time

PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# PACKAGE_ROOT = <repo>/submission/creative-work，故仓库根为它的两级父目录
_CANDIDATE_REPO = os.path.dirname(os.path.dirname(PACKAGE_ROOT))
#: 只有完整仓库才有 final_system.sh；独立作品包里解析到包根（在线功能自然不可用）
REPO_ROOT = (_CANDIDATE_REPO
             if os.path.exists(os.path.join(_CANDIDATE_REPO, 'scripts', 'final_system.sh'))
             else PACKAGE_ROOT)

#: 允许的模式 -> final_system.sh 参数
ALLOWED_MODES = {
    'controlled': ['--mode', 'controlled'],
    'three-real-strict': ['--mode', 'three-real-strict'],
    'enforce': ['--mode', 'enforce'],
    'acceptance': ['--mode', 'acceptance'],
    'check': ['--check'],
}

RUN_ID_RE = re.compile(r'^[A-Za-z0-9_.-]{1,64}$')

#: 单次运行的最长时限（秒）；超时会被终止并标记 TIMEOUT
MAX_RUNTIME_SEC = float(os.environ.get('DASHBOARD_MAX_RUNTIME_SEC', '1800'))


class RunController:
    def __init__(self):
        self._lock = threading.Lock()
        self._proc = None
        self._state = {'status': 'IDLE', 'mode': None, 'run_id': None,
                       'started_at': None, 'finished_at': None,
                       'exit_code': None, 'log_path': None, 'error': None}
        self._log_fh = None

    # ---------------------------------------------------------------- 状态
    def status(self):
        with self._lock:
            state = dict(self._state)
        if state['status'] == 'RUNNING' and self._proc is not None:
            state['pid'] = self._proc.pid
            state['elapsed_sec'] = round(time.time() - (state['started_at'] or 0), 1)
        return state

    def busy(self):
        return self._state['status'] == 'RUNNING'

    # ---------------------------------------------------------------- 启动
    def start(self, mode, run_id=None):
        if mode not in ALLOWED_MODES:
            return {'ok': False, 'error': f'不允许的模式: {mode}'}

        if run_id is None:
            run_id = 'dash-' + time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
        if not RUN_ID_RE.match(run_id):
            return {'ok': False, 'error': 'run_id 非法（仅允许字母数字 _ . -，长度 1-64）'}

        if self.busy():
            return {'ok': False,
                    'error': '已有实验在运行；请等待结束或停止后再试（避免 Domain 争用）'}

        evidence_dir = os.path.join(
            REPO_ROOT, 'artifacts/integration/dashboard-runs', run_id)
        os.makedirs(evidence_dir, exist_ok=True)
        log_path = os.path.join(evidence_dir, 'run.log')

        argv = ['bash', os.path.join(REPO_ROOT, 'scripts/final_system.sh'),
                *ALLOWED_MODES[mode], '--run-id', run_id,
                '--out-dir', 'artifacts/integration/dashboard-runs']

        opened = open(log_path, 'w', encoding='utf-8')
        try:
            proc = subprocess.Popen(
                argv, cwd=REPO_ROOT, stdout=opened, stderr=subprocess.STDOUT,
                start_new_session=True)  # 独立进程组，便于只杀自己
        except OSError as exc:
            opened.close()
            return {'ok': False, 'error': f'启动失败: {exc}'}

        with self._lock:
            self._proc = proc
            self._log_fh = opened
            self._state = {'status': 'RUNNING', 'mode': mode, 'run_id': run_id,
                           'started_at': time.time(), 'finished_at': None,
                           'exit_code': None,
                           'log_path': os.path.relpath(log_path, REPO_ROOT),
                           'error': None}
        threading.Thread(target=self._wait, args=(proc, opened),
                         daemon=True).start()
        return {'ok': True, 'mode': mode, 'run_id': run_id,
                'log_path': os.path.relpath(log_path, REPO_ROOT)}

    def _wait(self, proc, fh):
        try:
            code = proc.wait(timeout=MAX_RUNTIME_SEC)
            error = None if code == 0 else f'实验以非零退出码结束: {code}'
        except subprocess.TimeoutExpired:
            self._terminate(proc)
            code = None
            error = f'运行超过 {MAX_RUNTIME_SEC:.0f} 秒，已终止'
        finally:
            try:
                fh.close()
            except OSError:
                pass
        with self._lock:
            self._state.update({
                'status': 'FAIL' if (code not in (0,) ) else 'DONE',
                'exit_code': code,
                'finished_at': time.time(),
                'error': error,
            })
            self._proc = None
            self._log_fh = None

    def _terminate(self, proc):
        """只终止本控制器启动的进程组。"""
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
        if not self.busy() or self._proc is None:
            return {'ok': False, 'error': '当前没有正在运行的实验'}
        self._terminate(self._proc)
        return {'ok': True, 'message': '已向本次实验的进程组发送终止信号'}

    def log_tail(self, lines=80):
        path = self._state.get('log_path')
        if not path:
            return ''
        full = os.path.join(REPO_ROOT, path)
        try:
            with open(full, encoding='utf-8', errors='replace') as fh:
                content = fh.readlines()
            return ''.join(content[-lines:])
        except OSError:
            return ''
