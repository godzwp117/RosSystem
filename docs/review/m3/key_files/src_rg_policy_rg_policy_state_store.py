"""M3 任务状态持久化：临时文件写入 → flush/fsync → 原子替换 → 目录 fsync。

边界与诚实声明（对应 C9）
-------------------------
* 本模块保证**单个状态文件**的原子替换：读者要么看到旧内容，要么看到新内容，
  不会看到写了一半的文件。
* 它**不**声称状态文件与审计 JSONL 之间具备跨文件原子性 —— 那是两个文件、两次写入。
  因此提交顺序被明确固定为：**先持久化状态（权威记录），再写审计事件**。
  恢复规则：以状态文件为准；若审计事件缺失，则审计链存在缺口，可通过
  `transition_audit_failures` 与日志发现，但不会被误当成"切换没有发生"。
* digest 只能证明内容关联或检测意外变化，**不是数字签名**，也无法抵御拥有该文件
  写权限的恶意主体。拥有写权限者可以把状态改成任意合法阶段。
"""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any, Dict, Mapping, Optional, Tuple

from .task_policy import PolicySchemaError
from .task_state import (
    ActiveTaskSnapshot, STATE_ACTIVE, STATE_SCHEMA_VERSION, TASK_STATES,
)

STATE_FILENAME = 'task_state.json'


class StateStoreError(Exception):
    """状态文件不可用（损坏、不可写、字段非法）。"""


def _fsync_dir(path: str) -> None:
    """对目录做 fsync，确保 rename 本身已落盘（否则掉电后可能丢目录项）。"""
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


class TaskStateStore:
    """原子、可校验的任务状态存储。"""

    def __init__(self, path: str):
        self.path = os.path.abspath(path)
        self.directory = os.path.dirname(self.path) or '.'
        self.commit_count = 0
        self.load_count = 0

    # ------------------------------------------------------------ 读取
    def load(self) -> Tuple[Optional[ActiveTaskSnapshot], Dict[str, str], str]:
        """返回 (snapshot, used_transition_ids, state)。

        * 文件不存在 -> (None, {}, ACTIVE)：由调用方按可信配置的初始阶段冷启动。
          这是**确定性且保守**的选择，不是"恢复旧权限"。
        * 文件损坏/字段非法 -> 抛 StateStoreError，由调用方进入 RECOVERY_REQUIRED。
        """
        if not os.path.isfile(self.path):
            return None, {}, STATE_ACTIVE
        self.load_count += 1
        try:
            with open(self.path, 'r', encoding='utf-8') as handle:
                document = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise StateStoreError('状态文件无法读取或解析: {0}'.format(exc)) from exc
        if not isinstance(document, Mapping):
            raise StateStoreError('状态文件根节点必须是对象')
        version = str(document.get('state_schema_version', ''))
        if version != STATE_SCHEMA_VERSION:
            raise StateStoreError(
                '状态文件 schema 版本不匹配（期望 {0}，实际 {1}）'.format(
                    STATE_SCHEMA_VERSION, version or '(缺失)'))
        snapshot_raw = document.get('snapshot')
        if not isinstance(snapshot_raw, Mapping):
            raise StateStoreError('状态文件缺少 snapshot')
        # from_dict 内部会重算 digest 并与声明值比对，篡改会被拒绝。
        # 这里把快照层的 PolicySchemaError 统一包装成 StateStoreError，
        # 让调用方只需要处理一种"存储不可信"的异常。
        try:
            snapshot = ActiveTaskSnapshot.from_dict(snapshot_raw)
        except PolicySchemaError as exc:
            raise StateStoreError('快照内容不可信: {0}'.format(exc)) from exc
        used = document.get('used_transition_ids') or {}
        if not isinstance(used, Mapping):
            raise StateStoreError('used_transition_ids 必须是对象')
        state = str(document.get('state', STATE_ACTIVE))
        if state not in TASK_STATES:
            raise StateStoreError('未知状态值: {0!r}'.format(state))
        return snapshot, {str(k): str(v) for k, v in used.items()}, state

    # ------------------------------------------------------------ 写入
    def commit(self, plan: Any, state_machine: Any) -> Tuple[bool, str]:
        """把"切换后"的状态原子写盘。成功返回 (True, detail)，失败返回 (False, 原因)。

        写入顺序：临时文件 → fsync(文件) → os.replace(原子) → fsync(目录)。
        任何一步失败都会清理临时文件并保持旧状态文件不变。
        """
        snapshot = ActiveTaskSnapshot.from_phase(plan.target, plan.next_epoch)
        used = dict(state_machine.used_transition_ids)
        used[plan.transition_id] = snapshot.policy_digest
        document = {
            'state_schema_version': STATE_SCHEMA_VERSION,
            'state': STATE_ACTIVE,
            'snapshot': snapshot.as_dict(),
            'used_transition_ids': used,
            'last_transition_id': plan.transition_id,
            'committed_at': _utc_now(),
        }
        os.makedirs(self.directory, exist_ok=True)
        tmp_path = None
        try:
            fd, tmp_path = tempfile.mkstemp(prefix='.task_state_', suffix='.tmp',
                                            dir=self.directory)
            with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                json.dump(document, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, self.path)
            tmp_path = None
            _fsync_dir(self.directory)
        except OSError as exc:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            return False, '状态写入失败: {0}'.format(exc)
        self.commit_count += 1
        return True, 'committed epoch={0}'.format(snapshot.policy_epoch)


def _utc_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
