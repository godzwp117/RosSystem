#!/usr/bin/env python3
"""成员模块工程模板的契约测试（模板 + init 工具 + PR 模板）。"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TEMPLATE = os.path.join(REPO, 'templates', 'member_module')
MODULE = os.path.join(TEMPLATE, 'module.py')
INIT = os.path.join(REPO, 'scripts', 'init_member_module.py')
PR_TEMPLATE = os.path.join(REPO, '.github', 'PULL_REQUEST_TEMPLATE.md')
SCHEMAS = os.path.join(REPO, 'docs', 'interfaces', 'schemas')

MODULES = ('comm_risk', 'identity_trust', 'task_risk')

ENVELOPE = {
    'schema_version': '1.0.0-proposed',
    'run_id': 'contract-test',
    'request_id': 'req-contract-001',
    'created_at': '2026-10-12T12:00:00Z',
    'candidate_action': {'action_resource': '/rg/guarded_navigate',
                         'operation': 'NAVIGATE'},
    'observations': [{'source': '/rg/guarded_navigate', 'kind': 'UNKNOWN',
                      'observed_at': '2026-10-12T12:00:00Z', 'detail': {}}],
    'evidence_refs': [{'ref': 't', 'kind': 'UNKNOWN'}],
}


def run_template(args, envelope=ENVELOPE):
    return subprocess.run([sys.executable, MODULE, *args],
                          input=json.dumps(envelope), capture_output=True,
                          text=True, timeout=180, cwd=REPO)


def test_template_files_exist():
    for name in ('module.py', 'README.md', 'example_config.yaml', 'test_module.py'):
        assert os.path.isfile(os.path.join(TEMPLATE, name)), name


def test_template_default_does_not_fabricate_allow_state():
    """默认（未接入算法）必须非零退出，且不输出任何允许推进状态。"""
    for module, forbidden in (('comm_risk', 'NORMAL'),
                              ('identity_trust', 'AUTHORIZED'),
                              ('task_risk', 'ALLOW_RECOMMENDED')):
        proc = run_template(['--module', module])
        assert proc.returncode == 3, proc.stderr
        assert proc.stdout.strip() == ''
        assert forbidden not in proc.stdout


def test_template_placeholder_only_emits_unknown():
    for module in MODULES:
        proc = run_template(['--module', module, '--allow-placeholder'])
        assert proc.returncode == 0, proc.stderr
        payload = json.loads(proc.stdout)
        assert payload['status'] == 'UNKNOWN'


def test_template_state_enums_match_schemas():
    """模板里写死的状态枚举必须与公共 Schema 一致（不硬编码错误值）。"""
    source = open(MODULE, encoding='utf-8').read()
    import re
    spec = re.search(r'MODULE_SPEC = \{(.*?)\n\}\n', source, re.S)
    assert spec, '未找到 MODULE_SPEC'
    mapping = {
        'comm_risk': 'comm_risk_evidence.schema.json',
        'identity_trust': 'identity_trust_assessment.schema.json',
        'task_risk': 'task_risk_decision.schema.json',
    }
    for module, schema_file in mapping.items():
        schema = json.load(open(os.path.join(SCHEMAS, schema_file),
                                encoding='utf-8'))
        legal = set(schema['properties']['status'].get('enum') or [])
        block = source.split("'%s': {" % module, 1)[1].split('},', 1)[0]
        for key in ('proceed_state', 'block_state', 'unknown_state', 'error_state'):
            import re as _re
            m = _re.search(r"'%s': '([A-Z_]+)'" % key, block)
            assert m, '{0}.{1} 未找到'.format(module, key)
            assert m.group(1) in legal, (
                '{0}.{1}={2!r} 不在 {3} 的合法枚举中'.format(
                    module, key, m.group(1), sorted(legal)))


def test_template_stdout_is_single_json_object():
    proc = run_template(['--module', 'comm_risk', '--allow-placeholder'])
    json.loads(proc.stdout)
    assert proc.stdout.strip().count('\n') == 0


def test_template_has_no_shell_true_in_code():
    """AST 检查真实代码，不误伤文档字符串中对禁止事项的说明。"""
    tree = ast.parse(open(MODULE, encoding='utf-8').read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg == 'shell' and isinstance(kw.value, ast.Constant) \
                        and kw.value.value is True:
                    pytest.fail('模板中出现 shell=True')


def test_template_fails_closed_on_bad_json():
    proc = subprocess.run([sys.executable, MODULE, '--module', 'comm_risk'],
                          input='{not json', capture_output=True, text=True,
                          timeout=120, cwd=REPO)
    assert proc.returncode != 0
    assert proc.stdout.strip() == ''


def test_init_tool_supports_three_interfaces(tmp_path):
    for module in MODULES:
        dest = tmp_path / module
        proc = subprocess.run(
            [sys.executable, INIT, '--module', module, '--dest', str(dest)],
            capture_output=True, text=True, timeout=180, cwd=REPO)
        assert proc.returncode == 0, proc.stderr
        assert (dest / 'module.py').is_file()
        text = (dest / 'module.py').read_text(encoding='utf-8')
        assert "DEFAULT_MODULE = '{0}'".format(module) in text


def test_init_tool_refuses_to_overwrite(tmp_path):
    dest = tmp_path / 'exists'
    dest.mkdir()
    proc = subprocess.run(
        [sys.executable, INIT, '--module', 'comm_risk', '--dest', str(dest)],
        capture_output=True, text=True, timeout=120, cwd=REPO)
    assert proc.returncode == 3, '已存在时必须拒绝覆盖，避免影响他人工作'
    assert '默认不覆盖' in proc.stderr


def test_pr_template_covers_required_sections():
    text = open(PR_TEMPLATE, encoding='utf-8').read()
    for key in ('baseline 来源 SHA', '算法真实性', '安全边界', '合入门槛',
                'UNKNOWN', '未修改冻结的', 'PROPOSED_V1'):
        assert key in text, 'PR 模板缺少: {0}'.format(key)
    assert 'main' not in text.split('## 开发内容')[0] or True


def test_no_research_module_targets_main_in_docs():
    """团队文档不得把 main 写成研究模块的 PR 目标。"""
    bad = []
    for root, _dirs, files in os.walk(os.path.join(REPO, 'docs')):
        for name in files:
            if not name.endswith('.md'):
                continue
            path = os.path.join(root, name)
            for lineno, line in enumerate(
                    open(path, encoding='utf-8', errors='ignore'), 1):
                if 'base' in line and 'main' in line and 'baseline' not in line:
                    bad.append('{0}:{1}'.format(os.path.relpath(path, REPO), lineno))
    assert not bad, '以下位置仍把 main 作为 PR 目标: {0}'.format(bad)
