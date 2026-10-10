"""T14 断言逻辑的反向验证（工作包 A1）。

为什么需要这个文件
------------------
T14 首版存在 `os.path.isfile(item_audit) or True` 这样的恒真断言：
无论文件是否存在都通过，等于没有检查。仅仅删掉 `or True` 并不足以说明问题解决——
必须证明**当证据真的缺失或串扰时，测试确实会失败**。

本文件用真实的证据读取函数 `_instance_evidence` 和真实的交叉检查逻辑，
构造"文件缺失""请求串扰""审计缺该 request_id"三种情形，断言它们都会被判为失败。
"""

from __future__ import annotations

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, 'tests', 'integration'))

import team_handoff_check as thc  # noqa: E402


class FakeInstance:
    """只提供 _instance_evidence 需要的路径属性。"""

    def __init__(self, audit_path, navsim_path):
        self.audit_path = audit_path
        self.navsim_path = navsim_path


def write_jsonl(path, records):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + '\n')


def decision(request_id, decision='ALLOW', reason='ALLOW_IN_POLICY'):
    return {'event_type': 'DecisionEvent', 'request_id': request_id,
            'decision': decision, 'reason_code': reason}


def goal(request_id):
    return {'request_id': request_id, 'goal_id': 'g-' + request_id}


def test_missing_audit_file_is_not_silently_accepted(tmp_path):
    """审计文件不存在时必须如实反映，不能被 `or True` 之类兜底掩盖。"""
    instance = FakeInstance(str(tmp_path / 'nope' / 'audit.jsonl'),
                            str(tmp_path / 'nope' / 'navsim.jsonl'))
    evidence = thc._instance_evidence(instance, 'req-x', 'a')
    assert evidence['audit_exists'] is False
    assert evidence['navsim_exists'] is False
    assert evidence['decision_count'] == 0
    # 关键：这是"失败"而不是"通过"
    assert not (evidence['audit_exists'] and evidence['decision_count'] >= 1)


def test_present_audit_with_matching_request_is_accepted(tmp_path):
    """正例对照：文件存在且含本实例 request_id 时才算通过。"""
    audit = str(tmp_path / 'audit.jsonl')
    navsim = str(tmp_path / 'navsim.jsonl')
    write_jsonl(audit, [decision('req-a')])
    write_jsonl(navsim, [goal('req-a')])
    evidence = thc._instance_evidence(FakeInstance(audit, navsim), 'req-a', 'a')
    assert evidence['audit_exists'] is True
    assert evidence['decision_count'] == 1
    assert evidence['decision'] == 'ALLOW'
    assert evidence['goal_count'] == 1


def test_cross_instance_request_id_is_detected(tmp_path):
    """串扰检测：另一实例的 request_id 出现在本实例日志中必须可被发现。"""
    audit = str(tmp_path / 'audit.jsonl')
    navsim = str(tmp_path / 'navsim.jsonl')
    # 本实例日志里混入了 B 的 request_id —— 这正是"串扰"
    write_jsonl(audit, [decision('req-a'), decision('req-b')])
    write_jsonl(navsim, [goal('req-a'), goal('req-b')])

    records = thc.read_jsonl(audit)
    foreign = thc.decisions_for(records, 'req-b')
    assert len(foreign) == 1, '串扰必须能被检出'

    goals = thc.read_jsonl(navsim)
    assert len(thc.navsim_goals_for(goals, 'req-b')) == 1

    # 而 T14 的断言要求 foreign == 0，因此该情形会被判为 FAIL
    assert not (len(foreign) == 0), '构造的串扰情形应当使 T14 断言失败'


def test_audit_without_our_request_id_fails_the_assertion(tmp_path):
    """审计文件存在但不含本实例 request_id —— 也必须判为失败。"""
    audit = str(tmp_path / 'audit.jsonl')
    write_jsonl(audit, [decision('req-someone-else')])
    evidence = thc._instance_evidence(FakeInstance(audit, str(tmp_path / 'n.jsonl')),
                                      'req-mine', 'a')
    assert evidence['audit_exists'] is True
    assert evidence['decision_count'] == 0
    assert not (evidence['decision_count'] >= 1)


def test_malformed_audit_lines_are_counted(tmp_path):
    """坏行必须能被统计出来，而不是静默跳过造成"看起来正常"。"""
    audit = str(tmp_path / 'audit.jsonl')
    os.makedirs(os.path.dirname(audit), exist_ok=True)
    with open(audit, 'w', encoding='utf-8') as handle:
        handle.write(json.dumps(decision('req-a')) + '\n')
        handle.write('{ this is not json\n')
    evidence = thc._instance_evidence(FakeInstance(audit, str(tmp_path / 'n.jsonl')),
                                      'req-a', 'a')
    assert evidence['audit_parse_errors'] == 1, '坏行必须被计数'
    assert evidence['decision_count'] == 1


def test_no_tautological_assertions_remain_in_source():
    """源码中不得再出现恒真断言（`X or True` / `assert True`）。

    用 AST 而非文本匹配：文本匹配会把注释与文档字符串里的说明文字误判为代码
    （本测试首次运行就撞上了这个假阳性）。AST 只看真实语法结构，不受文字影响。
    """
    import ast

    path = os.path.join(ROOT, 'tests', 'integration', 'team_handoff_check.py')
    tree = ast.parse(open(path, encoding='utf-8').read())
    offenders = []
    for node in ast.walk(tree):
        # `A or True` —— 恒真
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            for value in node.values:
                if isinstance(value, ast.Constant) and value.value is True:
                    offenders.append(('or True', getattr(node, 'lineno', '?')))
        # `assert True` —— 恒真
        if isinstance(node, ast.Assert):
            test = node.test
            if isinstance(test, ast.Constant) and test.value is True:
                offenders.append(('assert True', getattr(node, 'lineno', '?')))
    assert not offenders, '仍存在恒真断言: {0}'.format(offenders)


def test_scenario_all_covers_every_declared_scenario():
    """--scenario all 必须覆盖 SCENARIO_TABLE 中的全部场景。"""
    assert list(thc.SCENARIO_TABLE) == ['T{0:02d}'.format(i) for i in range(1, 16)]
    source = open(os.path.join(ROOT, 'tests', 'integration',
                               'team_handoff_check.py'), encoding='utf-8').read()
    assert 'selected = list(SCENARIO_TABLE)' in source, \
        'all 分支必须直接取用 SCENARIO_TABLE，避免手工列表再次遗漏'


def test_replacement_scenarios_map_to_distinct_modules():
    """T09/T10/T11 必须映射到三个不同模块，不能共用同一实现冒充三项。"""
    source = open(os.path.join(ROOT, 'tests', 'integration',
                               'team_handoff_check.py'), encoding='utf-8').read()
    for case_id, module in (('T09', 'comm_risk'), ('T10', 'identity_trust'),
                            ('T11', 'task_risk')):
        marker = "'{0}': '{1}'".format(case_id, module)
        assert marker in source, '缺少独立映射: {0}'.format(marker)
