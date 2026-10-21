"""M2 Writer GUID 序列化的越界读取回归（集成轮）。

背景
----
`src/m2_witness/m2_ingress_witness.cpp` 早期实现把 EntityId 当 12 字节遍历：

    for (size_t i = 0; i < 12; ++i) {
        std::snprintf(buf, sizeof(buf), "%02x", guid.entityId.value[i]);
    }

但 Fast DDS 的实际布局是：

    GuidPrefix_t::size == 12
    EntityId_t::size   == 4      <-- 只有 4 字节

因此 `i = 4..11` 会读到 `value[4..11]`，**越界 8 字节**，属于未定义行为。
这类**对象内越界**不会被 AddressSanitizer 捕获（它不跨越分配块边界），
实测 ASan 只报了内存泄漏、没有报这个越界，所以必须用确定性断言来守。

本测试做两件事：

1. **静态约束**：源码必须以 `EntityId_t::size` / `GuidPrefix_t::size` 为界，
   不得出现硬编码 `i < 12` 去遍历 `entityId.value`；
2. **证据约束**：已记录的真实事件里，writer GUID 的 entity 段必须是
   **8 个十六进制字符**（4 字节），不能是 24 个字符（那正是越界读的产物）。
"""
from __future__ import annotations

import json
import os
import re

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
INGRESS = os.path.join(REPO, 'src', 'm2_witness', 'm2_ingress_witness.cpp')
WITNESS = os.path.join(REPO, 'src', 'm2_witness', 'm2_identity_witness.cpp')


def read_source(path):
    with open(path, encoding='utf-8') as fh:
        return fh.read()


@pytest.mark.parametrize('path', [INGRESS, WITNESS])
def test_entity_id_iteration_uses_declared_size(path):
    """遍历 EntityId 必须以 EntityId_t::size 为界，不能硬编码 12。"""
    source = read_source(path)
    if 'entityId.value' not in source:
        pytest.skip('该文件不序列化 EntityId')

    # 找出所有引用 entityId.value[i] 的循环上界
    buggy = re.findall(
        r'for\s*\([^)]*i\s*<\s*12\s*;[^)]*\)\s*\{[^}]*entityId\.value',
        source, re.S)
    assert not buggy, (
        'EntityId_t 只有 4 字节；用 i < 12 遍历 entityId.value 会越界读取 8 字节。'
        '必须改用 rtps::EntityId_t::size。')
    assert 'rtps::EntityId_t::size' in source, (
        '应以 rtps::EntityId_t::size 作为上界，而不是字面量')


@pytest.mark.parametrize('path', [INGRESS, WITNESS])
def test_guid_prefix_iteration_uses_declared_size(path):
    """前缀同样用常量，避免硬编码。"""
    source = read_source(path)
    if 'prefix.value[i]' not in source and 'guidPrefix.value[i]' not in source:
        pytest.skip('该文件不序列化 GuidPrefix')
    assert 'rtps::GuidPrefix_t::size' in source


def _guid_part(guid_text, index):
    return guid_text.split('|')[index]


def test_recorded_writer_guid_has_four_byte_entity():
    """真实证据中的 writer GUID：entity 段必须是 8 个十六进制字符。"""
    root = os.path.join(REPO, 'artifacts', 'integration', 'three-real-limited')
    evidence = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if name.endswith('.jsonl'):
                evidence.append(os.path.join(dirpath, name))
    if not evidence:
        pytest.skip('尚无集成证据')

    checked = 0
    for path in evidence:
        with open(path, encoding='utf-8') as fh:
            for line in fh:
                line = line.strip()
                if not line.startswith('{'):
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                guid = record.get('writer_guid')
                if not guid or '|' not in guid:
                    continue
                entity = _guid_part(guid, 1)
                prefix = _guid_part(guid, 0)
                assert re.fullmatch(r'[0-9a-f]{8}', entity), (
                    f'EntityId 应为 4 字节/8 个十六进制字符，实际 {entity!r}'
                    f'（{path}）；24 个字符说明存在越界读取')
                assert prefix.count('.') == 11, (
                    f'GuidPrefix 应为 12 字节，实际 {prefix!r}')
                checked += 1
    assert checked > 0, '证据中存在 writer_guid 但未被检查'
