"""evidence_loader.py -- 只读地装载**真实**实验证据，供控制台展示。

设计原则
========
1. **只读**：本模块不写任何证据文件，也不修改历史证据。
2. **有据可查**：每个数字都带来源路径与 run_id，前端不得凭空生成。
3. **禁止伪造**：找不到证据就返回 `None` 并让上层显示 UNAVAILABLE，
   绝不用默认值把缺失伪装成 0 或 PASS。

两种数据源
----------
* **在线**：`artifacts/integration/final-submission-closeout/<run_id>/`
  由 `scripts/final_system.sh --mode acceptance` 真实产生。
* **回放**：`submission/creative-work/replay/replay_manifest.json`
  从已归档证据中提取的**只读快照**，不含 ROS 运行。
"""
from __future__ import annotations

import json
import os

#: 作品包根目录（dashboard/ 的上一级）——解包后也能正确定位 replay/
PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 仓库根目录：仅当处于完整仓库布局时成立（含 scripts/final_system.sh）。
#: 解包成独立作品包时回退到 PACKAGE_ROOT，避免把路径算到文件系统根。
# PACKAGE_ROOT = <repo>/submission/creative-work，故仓库根为它的两级父目录
_CANDIDATE_REPO = os.path.dirname(os.path.dirname(PACKAGE_ROOT))
REPO_ROOT = (_CANDIDATE_REPO
             if os.path.exists(os.path.join(_CANDIDATE_REPO, 'scripts', 'final_system.sh'))
             else PACKAGE_ROOT)

#: 允许扫描的证据根（白名单，防止路径穿越）
EVIDENCE_ROOTS = (
    'artifacts/integration/final-submission-closeout',
    'artifacts/integration/final-acceptance-hardening',
    'artifacts/integration/final-deliverable-2026-10-22',
)

#: 视为"当前封版"的证据根（在线模式优先读这里）
PRIMARY_ROOT = 'artifacts/integration/final-submission-closeout'


def _safe_join(root, *parts):
    """把 parts 拼到 root 下，并确保结果仍在 root 内（防路径穿越）。"""
    base = os.path.abspath(root)
    target = os.path.abspath(os.path.join(base, *parts))
    if not target.startswith(base + os.sep) and target != base:
        raise ValueError('路径越界')
    return target


class UnsafePath(ValueError):
    """调用方传入的证据路径不在允许范围内。"""


def _allowed_roots():
    """所有允许读取的*真实*根目录（realpath 之后）。含包内 replay 目录。"""
    roots = []
    for rel in EVIDENCE_ROOTS:
        path = os.path.join(REPO_ROOT, rel)
        if os.path.isdir(path):
            roots.append(os.path.realpath(path))
    replay_root = os.path.join(PACKAGE_ROOT, 'replay')
    if os.path.isdir(replay_root):
        roots.append(os.path.realpath(replay_root))
    return roots


def resolve_evidence_dir(requested):
    """把用户传入的 path 解析为**受控**的证据目录。

    安全要求（P0-4）
    ----------------
    1. 拒绝绝对路径；
    2. 拒绝 `..` 与 `.` 段；
    3. 解析后必须落在允许的根目录内；
    4. 用 `realpath` 解析符号链接后再判定一次 —— 防止软链接逃逸；
    5. 只允许目录。

    违规统一抛 `UnsafePath`，由上层返回 400/403。
    """
    if not isinstance(requested, str) or not requested.strip():
        raise UnsafePath('path 不能为空')
    if os.path.isabs(requested):
        raise UnsafePath('不允许绝对路径')
    parts = [seg for seg in requested.replace('\\', '/').split('/') if seg]
    if any(seg in ('.', '..') for seg in parts):
        raise UnsafePath('路径中不允许 . 或 .. 段')

    target = os.path.realpath(os.path.join(REPO_ROOT, *parts))
    for root in _allowed_roots():
        if target == root or target.startswith(root + os.sep):
            if os.path.isdir(target):
                return target
            raise UnsafePath('目标不是目录')
    raise UnsafePath('路径不在允许的证据根内')


def _read_json(path):
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _read_jsonl(path):
    try:
        with open(path, encoding='utf-8') as fh:
            return [json.loads(line) for line in fh if line.strip()]
    except (OSError, ValueError):
        return None


def list_runs():
    """列出所有可用的证据 run（在线 + 回放）。"""
    runs = []
    for root in EVIDENCE_ROOTS:
        base = os.path.join(REPO_ROOT, root)
        if not os.path.isdir(base):
            continue
        for name in sorted(os.listdir(base), reverse=True):
            path = os.path.join(base, name)
            if not os.path.isdir(path):
                continue
            tested = _read_json(os.path.join(path, 'tested_commit.json')) or {}
            runs.append({
                'run_id': name,
                'kind': 'ONLINE_EVIDENCE' if root == PRIMARY_ROOT else 'ARCHIVED_EVIDENCE',
                'root': root,
                'path': os.path.join(root, name),
                'tested_code_sha': tested.get('tested_code_sha')
                                   or tested.get('hardened_tested_code_sha')
                                   or tested.get('final_tested_code_sha'),
            })
    replay = load_replay()
    if isinstance(replay, dict):
        runs.append({
            'run_id': replay.get('run_id', 'REPLAY'),
            'kind': 'REPLAY_SNAPSHOT',
            'root': 'submission/creative-work/replay',
            'path': 'submission/creative-work/replay/replay_manifest.json',
            'tested_code_sha': replay.get('tested_code_sha'),
        })
    return runs


def load_run(run_path):
    """装载一个 run 的跨层事实。返回 dict；缺失项为 None，不填默认值。"""
    base = run_path if os.path.isabs(run_path) else os.path.join(REPO_ROOT, run_path)
    if not os.path.isdir(base):
        return None

    facts = {
        'run_path': os.path.relpath(base, REPO_ROOT),
        'tested_commit': _read_json(os.path.join(base, 'tested_commit.json')),
        'summary': _text(os.path.join(base, 'summary.txt')),
        'm3': None,
        'controlled': None,
        'three_real': None,
        'dds_enforce': None,
        'timeout_audit': None,
    }

    merged = os.path.join(base, 'm3_online', 'merged')
    verification = _read_json(os.path.join(merged, 'verification.json'))
    if isinstance(verification, dict):
        facts['m3'] = {
            'verdict': verification.get('verdict'),
            'checks': verification.get('checks'),
            'failures': verification.get('failures'),
            'claims_checked': verification.get('claims_checked'),
            'scenarios_verified': verification.get('scenarios_verified'),
            'scenarios': verification.get('scenarios') or [],
            'source': os.path.relpath(
                os.path.join(merged, 'verification.json'), REPO_ROOT),
        }

    controlled = _read_json(os.path.join(
        base, 'controlled_online', 'controlled_verification.json'))
    if isinstance(controlled, dict):
        facts['controlled'] = {
            'verdict': controlled.get('verdict'),
            'checks': controlled.get('checks'),
            'failures': controlled.get('failures'),
            'facts': controlled.get('facts'),
            'source': os.path.relpath(os.path.join(
                base, 'controlled_online', 'controlled_verification.json'), REPO_ROOT),
        }

    three = _read_json(os.path.join(base, 'three_real', 'f0.json'))
    if isinstance(three, dict):
        facts['three_real'] = {
            'decision': three.get('decision'),
            'reason_code': three.get('reason_code'),
            'modules': [
                {'module': m.get('module'), 'mode': m.get('mode'),
                 'status': m.get('status'), 'schema_ok': m.get('schema_ok'),
                 'exit_code': m.get('exit_code')}
                for m in (three.get('modules') or [])],
            'source': os.path.relpath(
                os.path.join(base, 'three_real', 'f0.json'), REPO_ROOT),
        }

    ta = _read_json(os.path.join(base, 'timeout_audit', 'timeout_outcome_audit.json'))
    if isinstance(ta, dict):
        facts['timeout_audit'] = {
            'scenario': ta.get('scenario'),
            'planner_outcome': ta.get('planner_outcome'),
            'gateway_arrivals': ta.get('gateway_arrivals'),
            'gateway_decisions': ta.get('gateway_decisions'),
            'navsim_goals': ta.get('navsim_goals'),
            'semantics': ta.get('semantics'),
            'source': os.path.relpath(os.path.join(
                base, 'timeout_audit', 'timeout_outcome_audit.json'), REPO_ROOT),
        }

    dds_dir = os.path.join(base, 'dds_enforce')
    if os.path.isdir(dds_dir):
        log = _text(os.path.join(dds_dir, 'sros2_check.log')) or ''
        import re
        m = re.search(r'SROS2 SUMMARY \((\d+) passed / (\d+) total\)', log)
        facts['dds_enforce'] = {
            'passed': int(m.group(1)) if m else None,
            'total': int(m.group(2)) if m else None,
            'source': os.path.relpath(dds_dir, REPO_ROOT),
        }

    # 回放快照直接带 facts
    replay = _read_json(os.path.join(base, 'replay_manifest.json'))
    if isinstance(replay, dict):
        facts['replay'] = replay
    return facts


def _text(path):
    try:
        with open(path, encoding='utf-8') as fh:
            return fh.read()
    except OSError:
        return None


def load_replay():
    """回放快照：包内优先，其次仓库路径。"""
    for candidate in (os.path.join(PACKAGE_ROOT, 'replay', 'replay_manifest.json'),
                      os.path.join(REPO_ROOT, 'submission/creative-work/replay',
                                   'replay_manifest.json')):
        data = _read_json(candidate)
        if isinstance(data, dict):
            return data
    return None
