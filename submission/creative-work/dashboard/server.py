#!/usr/bin/env python3
"""server.py -- RosSystem 跨层安全决策可视化控制台（本地只读 + 白名单运行）。

安全边界
========
* 只监听 `127.0.0.1`（可用 `--host` 显式改，但默认不外网可达）；
* **不实现任何安全判断**：F0/Gateway/DDS 的结论全部来自真实证据文件；
* 运行接口走白名单（见 `run_controller.py`），前端不能提交任意命令；
* 静态文件只从 `static/` 目录提供，路径做规范化校验。

API
---
    GET  /api/health              服务与运行环境状态
    GET  /api/runs                可用证据 run 列表
    GET  /api/run?path=...        装载某个 run 的跨层事实
    GET  /api/replay              历史回放快照
    POST /api/run/start           {mode, run_id} 启动白名单实验
    POST /api/run/stop            停止本次启动的实验
    GET  /api/run/status          当前运行状态 + 日志尾部
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import evidence_loader as ev  # noqa: E402
from run_controller import ALLOWED_MODES, RunController  # noqa: E402

STATIC_DIR = os.path.join(HERE, 'static')
REPO_ROOT = ev.REPO_ROOT
CONTROLLER = RunController()


def runtime_status():
    """真实的环境探测：不假设宿主机有 ROS 2。

    P0 修复：旧实现只做 shutil.which('docker')，并把工作空间位置算成
    PACKAGE_ROOT/install —— 完整作品包实际是 runtime/install，于是"已构建"
    也会被判成未构建（假阴性）。作品里本来就有完整探测模块
    dashboard/docker_runtime.py，却从未被 import；这里改为复用同一套探测，
    避免出现两套不一致的判断。
    """
    import docker_runtime as dr
    info = dr.probe(os.path.dirname(HERE))
    workspace_built = os.path.exists(
        os.path.join(REPO_ROOT, 'install/setup.bash'))
    online_possible = bool(info['online_possible'] and workspace_built)
    reasons = list(info['blocked_reasons'])
    if not workspace_built:
        reasons.append('工作空间未构建（install/setup.bash 不存在）')
    return {
        'docker_available': info['docker_daemon'],
        'ros_jazzy_installed_on_host': os.path.isdir('/opt/ros/jazzy'),
        'workspace_built': workspace_built,
        'online_possible': online_possible,
        'online_blocked_reasons': [] if online_possible else reasons,
        'probe': info,
        'note': info['note'],
    }


def build_replay_view():
    """把回放快照映射成与在线事实**同构**的视图模型。

    字段缺失一律为 None（前端显示 NOT_OBSERVED），绝不填 0 或 PASS。
    """
    replay = ev.load_replay()
    if not isinstance(replay, dict):
        return None
    return {
        'contract': replay.get('contract', 'rosystem-replay-snapshot/1'),
        'mode': 'REPLAY',
        'run_id': replay.get('run_id'),
        'tested_code_sha': replay.get('tested_code_sha'),
        'evidence_source': replay.get('evidence_source'),
        'replay_notice': replay.get('replay_notice'),
        'm3': replay.get('m3'),
        'controlled': replay.get('controlled'),
        'three_real': replay.get('three_real'),
        'dds_enforce': replay.get('dds_enforce'),
        'timeout_comparison': replay.get('timeout_comparison') or [],
        'semantics': replay.get('semantics'),
        'modules': replay.get('modules'),
    }


class Handler(BaseHTTPRequestHandler):
    server_version = 'RosSystemDashboard/1.0'

    def log_message(self, fmt, *args):
        sys.stderr.write('[dash] ' + (fmt % args) + '\n')

    # ---------------------------------------------------------------- 工具
    def _send(self, code, body, content_type='application/json; charset=utf-8'):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False, indent=2)
        data = body.encode('utf-8') if isinstance(body, str) else body
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def _static(self, rel):
        target = os.path.abspath(os.path.join(STATIC_DIR, rel))
        if not target.startswith(os.path.abspath(STATIC_DIR) + os.sep):
            return self._send(403, {'error': '路径越界'})
        if not os.path.isfile(target):
            return self._send(404, {'error': 'not found'})
        ctype = {
            '.html': 'text/html; charset=utf-8',
            '.js': 'application/javascript; charset=utf-8',
            '.css': 'text/css; charset=utf-8',
        }.get(os.path.splitext(target)[1], 'application/octet-stream')
        with open(target, 'rb') as fh:
            self._send(200, fh.read(), ctype)

    # ---------------------------------------------------------------- GET
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path in ('/', '/index.html'):
            return self._static('index.html')
        if path.startswith('/static/'):
            return self._static(path[len('/static/'):])

        if path == '/api/health':
            return self._send(200, {
                'service': 'RosSystem dashboard',
                'runtime': runtime_status(),
                'controller': CONTROLLER.status(),
                'allowed_modes': sorted(ALLOWED_MODES),
            })

        if path == '/api/research':
            research = ev.load_research_evidence()
            if research is None:
                return self._send(404, {'error': '研究证据快照不存在或格式非法'})
            return self._send(200, research)

        if path == '/api/runs':
            return self._send(200, {'runs': ev.list_runs()})

        if path == '/api/run':
            qs = parse_qs(parsed.query)
            target = (qs.get('path') or [''])[0]
            if not target:
                return self._send(400, {'error': '缺少 path 参数'})
            # P0-4：绝对路径 / `..` / 软链接逃逸 / 根外访问统一拒绝
            try:
                resolved = ev.resolve_evidence_dir(target)
            except ev.UnsafePath as exc:
                return self._send(403, {'error': '路径不被允许: %s' % exc})
            facts = ev.load_run(resolved)
            if facts is None:
                return self._send(404, {'error': '未找到该证据目录'})
            return self._send(200, facts)

        if path == '/api/replay':
            # P0-1：直接返回**统一视图模型**。前端不再需要拼仓库相对路径，
            # 解包后的作品包也能完整回放。
            view = build_replay_view()
            if view is None:
                return self._send(404, {'error': '回放快照不存在'})
            return self._send(200, view)

        if path == '/api/run/status':
            state = CONTROLLER.status()
            state['log_tail'] = CONTROLLER.log_tail()
            return self._send(200, state)

        return self._send(404, {'error': 'unknown endpoint'})

    # ---------------------------------------------------------------- POST
    def do_POST(self):
        # 只接受同源 JSON；拒绝跨站表单与其他来源，防止外部网页驱动本地控制台。
        ctype = (self.headers.get('Content-Type') or '').split(';')[0].strip().lower()
        if ctype != 'application/json':
            return self._send(415, {'error': 'Content-Type 必须是 application/json'})
        origin = self.headers.get('Origin')
        if origin and not origin.startswith(('http://127.0.0.1', 'http://localhost')):
            return self._send(403, {'error': '拒绝跨站请求'})
        parsed = urlparse(self.path)
        length = int(self.headers.get('Content-Length') or 0)
        if length > 8192:
            return self._send(413, {'error': '请求体过大'})
        try:
            payload = json.loads(self.rfile.read(length) or b'{}')
        except ValueError:
            return self._send(400, {'error': '非法 JSON'})
        if not isinstance(payload, dict):
            return self._send(400, {'error': '请求体必须是 JSON 对象'})

        if parsed.path == '/api/run/start':
            mode = payload.get('mode')
            # P0 修复：在线不可用时后端必须拒绝，而不是只在 UI 层禁用按钮。
            # 旧实现会把请求交给 run_controller，最终以 127 神秘失败。
            rt = runtime_status()
            if not rt['online_possible']:
                return self._send(409, {
                    'ok': False,
                    'error': '在线实验不可用：' + '；'.join(rt['online_blocked_reasons']),
                    'runtime': rt,
                })
            result = CONTROLLER.start(mode, payload.get('run_id'))
            return self._send(200 if result.get('ok') else 400, result)

        if parsed.path == '/api/run/stop':
            result = CONTROLLER.stop()
            return self._send(200 if result.get('ok') else 400, result)

        return self._send(404, {'error': 'unknown endpoint'})


def main(argv=None):
    parser = argparse.ArgumentParser(description='RosSystem 决策控制台')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8787)
    args = parser.parse_args(argv)

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f'RosSystem dashboard: http://{args.host}:{args.port}/', flush=True)
    rt = runtime_status()
    print(f"在线模式可用: {rt['online_possible']}  原因: {rt['online_blocked_reasons']}",
          flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nstopped', flush=True)
    finally:
        server.server_close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
