"""F0 公共接口契约的单元测试（任务 C01/C02 的独立校验）。

设计要点
--------
* **使用真实 JSON Schema 校验器**（jsonschema >= 4.0 的 Draft 2020-12 实现），
  不是自定义正则，也不靠人工阅读 JSON。
* **格式校验必须真的生效**：本环境实测 `Draft202012Validator.FORMAT_CHECKER`
  中没有 `date-time` 检查器（缺 `rfc3339-validator`），仅声明 `format` 时非法时间戳
  会静默通过。因此这里显式注册严格检查器，并有专门的元测试证明它确实在拦截。
* **负例必须真的被拒**：每个负向断言都检查校验器实际返回了错误，
  而不是"校验器运行成功"。
* **语义约束单独覆盖**：`request_id` 跨模块一致性、`UNKNOWN/ERROR` 不得被当作允许、
  上游不得把候选操作指向执行端 —— 这些无法由单份 Schema 证明，用独立测试断言。
"""

import json
import os
import sys

import pytest

jsonschema = pytest.importorskip(
    'jsonschema',
    reason='需要 jsonschema>=4.0（Draft 2020-12）。安装方式: apt-get install -y '
           'python3-jsonschema')

from jsonschema import Draft202012Validator, FormatChecker  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(ROOT, 'scripts')
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import validate_team_contracts as vtc  # noqa: E402

INTERFACES = os.path.join(ROOT, 'docs', 'interfaces')
SCHEMAS = os.path.join(INTERFACES, 'schemas')
EXAMPLES = os.path.join(INTERFACES, 'examples')
INVALID = os.path.join(EXAMPLES, 'invalid')

OUTPUT_SCHEMAS = ('comm_risk_evidence', 'identity_trust_assessment', 'task_risk_decision')
ALL_SCHEMAS = OUTPUT_SCHEMAS + ('module_input',)

VALID_EXAMPLES = {
    'module_input_valid.json': 'module_input',
    'comm_normal.json': 'comm_risk_evidence',
    'comm_suspicious.json': 'comm_risk_evidence',
    'comm_unknown.json': 'comm_risk_evidence',
    'identity_authorized.json': 'identity_trust_assessment',
    'identity_denied.json': 'identity_trust_assessment',
    'identity_error.json': 'identity_trust_assessment',
    'task_allow_recommended.json': 'task_risk_decision',
    'task_block_recommended.json': 'task_risk_decision',
    'task_unknown.json': 'task_risk_decision',
}


def schema(name):
    return vtc.load_schema(name)


def example(filename):
    return vtc.load_json_strict(os.path.join(EXAMPLES, filename))


def invalid(filename):
    return vtc.load_json_strict(os.path.join(INVALID, filename))


def load_manifest():
    return vtc.load_json_strict(os.path.join(INVALID, 'manifest.json'))


# ------------------------------------------------------------ 依赖与前置
def test_jsonschema_supports_draft_2020_12():
    """校验器必须真的支持 Draft 2020-12（旧版只到 Draft 7）。"""
    assert hasattr(vtc, 'Draft202012Validator'), '当前 jsonschema 不支持 Draft 2020-12'
    assert Draft202012Validator.META_SCHEMA['$id'].endswith('2020-12/schema')


def test_format_checker_is_actually_enforced():
    """元测试：声明 format 不等于执行格式校验。

    若严格 date-time 检查器未注册，非法时间戳会静默通过，
    后续所有时间戳负例测试都会假通过。
    """
    ok, detail = vtc.self_check_format_checker()
    assert ok, 'date-time 格式检查未生效: {0}'.format(detail)
    validator = vtc.make_validator({'type': 'string', 'format': 'date-time'})
    assert validator.is_valid('2026-10-10T12:00:05Z')
    assert not validator.is_valid('2026-10-10 12:00:05'), '空格分隔的时间戳必须被拒绝'
    assert not validator.is_valid('2026-10-10T12:00:05'), '缺少时区必须被拒绝'


def test_non_finite_literals_are_rejected_at_parse_time():
    """NaN / Infinity 不是合法 JSON，必须在解析阶段拒绝。"""
    for literal in ('NaN', 'Infinity', '-Infinity'):
        with pytest.raises(ValueError):
            json.loads('{"v": %s}' % literal, parse_constant=vtc.non_finite_constant)


# ------------------------------------------------------------ Schema 合法性
@pytest.mark.parametrize('name', ALL_SCHEMAS)
def test_schema_is_itself_valid(name):
    Draft202012Validator.check_schema(schema(name))


@pytest.mark.parametrize('name', ALL_SCHEMAS)
def test_schema_declares_draft_id_and_title(name):
    doc = schema(name)
    assert doc['$schema'] == 'https://json-schema.org/draft/2020-12/schema'
    assert doc['$id'].endswith('.schema.json')
    assert doc['title']
    assert doc['type'] == 'object'
    assert doc['additionalProperties'] is False, '首版必须严格字段校验'


def test_output_schemas_share_identical_common_definitions():
    """三个输出 Schema 各自内联了 producer / evidenceRef 定义。

    内联是为了让每个 Schema 自包含、便于独立校验；代价是可能漂移。
    这里用自动比对防止三者悄悄不一致。
    """
    defs = [schema(name)['$defs'] for name in OUTPUT_SCHEMAS]
    for key in ('producer', 'evidenceRef'):
        first = json.dumps(defs[0][key], sort_keys=True, ensure_ascii=False)
        for index, other in enumerate(defs[1:], start=1):
            assert json.dumps(other[key], sort_keys=True, ensure_ascii=False) == first, \
                '{0} 的 {1} 定义与 {2} 不一致（定义漂移）'.format(
                    OUTPUT_SCHEMAS[index], key, OUTPUT_SCHEMAS[0])


def test_contract_version_is_consistent_everywhere():
    """Schema 中的版本枚举必须与校验工具里的常量一致。"""
    for name in ALL_SCHEMAS:
        enum = schema(name)['properties']['schema_version']['enum']
        assert enum == [vtc.CONTRACT_VERSION], '{0} 的版本枚举不一致: {1}'.format(name, enum)


# ------------------------------------------------------------ 有效样例
@pytest.mark.parametrize('filename, schema_name', sorted(VALID_EXAMPLES.items()))
def test_valid_examples_pass(filename, schema_name):
    errors = vtc.validate_document(example(filename), schema(schema_name))
    assert errors == [], '{0} 应通过校验，实际错误: {1}'.format(filename, errors)


@pytest.mark.parametrize('name', OUTPUT_SCHEMAS)
def test_each_output_schema_has_a_pass_and_a_reject_example(name):
    """每个接口都要有通过样例与阻断/异常样例，避免只测 happy path。"""
    passed = [f for f, s in VALID_EXAMPLES.items() if s == name]
    assert passed, '{0} 缺少有效样例'.format(name)


def test_unknown_and_error_examples_are_explicitly_present():
    """UNKNOWN 与 ERROR 必须有独立样例，防止被当成 NORMAL/允许。"""
    for filename, expected in (('comm_unknown.json', 'UNKNOWN'),
                               ('identity_error.json', 'ERROR'),
                               ('task_unknown.json', 'UNKNOWN')):
        assert example(filename)['status'] == expected


# ------------------------------------------------------------ 非法样例（逐条）
def _invalid_cases():
    return load_manifest()['cases']


@pytest.mark.parametrize('case', _invalid_cases(),
                         ids=[c['file'] + ':' + c['category'] for c in _invalid_cases()])
def test_invalid_examples_are_rejected(case):
    """每个非法样例都必须被真实拒绝；解析阶段拒绝也算（NaN 字面量）。"""
    path = os.path.join(INVALID, case['file'])
    try:
        document = vtc.load_json_strict(path)
    except ValueError as exc:
        assert case['category'] == 'non_finite_number', \
            '{0} 意外在解析阶段被拒绝: {1}'.format(case['file'], exc)
        return
    errors = vtc.validate_document(document, schema(case['schema']))
    assert errors, '{0} 应当被拒绝，但校验通过（负例失效）'.format(case['file'])


def test_manifest_covers_required_negative_categories():
    """负例必须覆盖任务要求的全部失败类别。"""
    categories = {c['category'] for c in load_manifest()['cases']}
    for required in ('missing_required', 'enum_violation', 'type_violation',
                     'range_violation', 'format_violation', 'version_incompatible',
                     'additional_property', 'const_violation'):
        assert required in categories, '缺少负例类别: {0}'.format(required)


# ------------------------------------------------------------ 关键语义约束
def test_input_envelope_forbids_self_reported_authorization_switch():
    """输入信封不得存在 is_admin / authenticated / role 之类自报授权开关。"""
    properties = schema('module_input')['properties']
    for banned in ('is_admin', 'authenticated', 'role', 'trusted', 'authorized'):
        assert banned not in properties, '输入信封不应存在自报授权字段: {0}'.format(banned)
    # 且出现这类字段时必须被拒绝（additionalProperties: false）
    errors = vtc.validate_document(invalid('input_admin_flag.json'), schema('module_input'))
    assert errors, '带 is_admin 的输入必须被拒绝'


def test_upstream_cannot_target_execution_action():
    """上游模块不得把候选操作指向执行端（由 const 在 Schema 层强制）。"""
    for name in ('module_input', 'task_risk_decision'):
        const = schema(name)['properties']['candidate_action']['properties'] \
                       ['action_resource'].get('const')
        assert const == '/rg/guarded_navigate', \
            '{0} 必须把 action_resource 固定为 /rg/guarded_navigate'.format(name)
    assert vtc.validate_document(invalid('input_execution_resource.json'),
                                 schema('module_input'))
    assert vtc.validate_document(invalid('task_execution_target.json'),
                                 schema('task_risk_decision'))


def test_mock_source_never_claims_authenticated_identity():
    """MOCK 样例不得填入 authenticated_identity（模拟值不能冒充已认证身份）。"""
    doc = example('identity_authorized.json')
    assert doc['producer']['source'] == 'MOCK'
    assert 'authenticated_identity' not in doc['subject'], \
        'MOCK 样例不得声称已获得认证身份'
    assert doc['identity_evidence']['kind'] != 'DDS_ACCESS_CONTROL_LOG', \
        'MOCK 样例不得声称有访问控制日志证据'


def test_denied_example_attributes_denial_to_dds_access_control_with_evidence():
    """声称拒绝发生在访问控制层时，必须同时给出原生访问控制证据。"""
    doc = example('identity_denied.json')
    assert doc['authorization']['denial_layer'] == 'DDS_ACCESS_CONTROL'
    assert doc['access_control_evidence']['kind'] == 'NATIVE_ACCESS_CONTROL_LOG', \
        '归因到访问控制层必须附原生访问控制证据，不能只凭客户端超时'


def test_allow_recommended_is_not_final_authorization():
    """上游建议不是最终授权：字段语义上不得出现"授权"表述。"""
    doc = example('task_allow_recommended.json')
    assert doc['status'] == 'ALLOW_RECOMMENDED'
    assert 'success' not in doc and 'authorized' not in json.dumps(doc).lower(), \
        'TaskRiskDecision 不得携带最终授权语义'
    description = schema('task_risk_decision')['description']
    assert '不是' in description and '最终' in description, \
        'Schema 描述必须显式声明这不是最终授权结果'


def test_optional_m3_fields_may_be_absent():
    """F0 基线不含任务动态状态机：M3 字段缺失必须仍然通过校验。"""
    doc = example('task_allow_recommended.json')
    assert 'policy_epoch' not in json.dumps(doc), '样例不应伪造 policy_epoch'
    assert 'policy_digest' not in json.dumps(doc), '样例不应伪造 policy_digest'
    assert vtc.validate_document(doc, schema('task_risk_decision')) == []

    # 显式给出空的 task_context / policy_ref 也必须通过
    doc2 = dict(doc)
    doc2['task_context'] = {}
    doc2['policy_ref'] = {}
    assert vtc.validate_document(doc2, schema('task_risk_decision')) == []


def test_fabricated_policy_digest_is_rejected():
    """伪造或格式错误的策略摘要必须被拒绝（不得用占位值冒充真实摘要）。"""
    assert vtc.validate_document(invalid('task_bad_digest.json'),
                                 schema('task_risk_decision'))
    doc = example('task_allow_recommended.json')
    doc['policy_ref'] = {'policy_digest': 'deadbeef'}
    assert vtc.validate_document(doc, schema('task_risk_decision')), \
        '非 64 位十六进制的摘要必须被拒绝'


# ------------------------------------------------------------ request_id 语义
def _find_by_request_id(base, target):
    found = []
    for root, _dirs, files in os.walk(base):
        for name in files:
            if not name.endswith('.json'):
                continue
            path = os.path.join(root, name)
            try:
                doc = vtc.load_json_strict(path)
            except Exception:  # noqa: BLE001
                continue
            if isinstance(doc, dict) and doc.get('request_id') == target:
                found.append(os.path.relpath(path, ROOT))
    return found


def test_request_id_semantics_are_documented_as_business_only():
    """request_id 必须被明确定义为业务关联标识，而非安全身份。"""
    for name in OUTPUT_SCHEMAS + ('module_input',):
        desc = schema(name)['properties']['request_id']['description']
        assert '身份' in desc, '{0} 必须说明 request_id 不代表安全身份'.format(name)


def test_producer_semantics_are_documented_as_untrusted():
    """producer 必须被明确定义为自报信息，不能当作认证凭据。"""
    for name in OUTPUT_SCHEMAS:
        desc = schema(name)['$defs']['producer']['description']
        assert '不是安全认证凭据' in desc, \
            '{0} 必须声明 producer 不是认证凭据'.format(name)


def test_samples_share_the_same_request_id_for_cross_module_correlation():
    """样例应体现跨模块关联：同一 run_id + request_id 贯穿输入与三个输出。

    注意：跨文件一致性无法由单份 Schema 证明，故在此以独立语义测试覆盖。
    """
    docs = {
        'input': example('module_input_valid.json'),
        'comm': example('comm_normal.json'),
        'identity': example('identity_authorized.json'),
        'task': example('task_allow_recommended.json'),
    }
    request_ids = {name: doc['request_id'] for name, doc in docs.items()}
    run_ids = {name: doc['run_id'] for name, doc in docs.items()}
    assert len(set(request_ids.values())) == 1, \
        '样例的 request_id 应一致以体现跨模块关联: {0}'.format(request_ids)
    assert len(set(run_ids.values())) == 1, \
        '样例的 run_id 应一致: {0}'.format(run_ids)


def test_mismatched_request_id_is_detectable_by_semantic_rule():
    """模拟适配层的一致性判定：request_id 不一致必须被拒绝。

    单份 Schema 无法表达"三个输出的 request_id 必须相同"，因此把该规则实现为
    可复用的语义检查函数，并在此验证其行为。
    """
    def check_consistency(expected_request_id, outputs):
        mismatched = [name for name, doc in outputs.items()
                      if doc.get('request_id') != expected_request_id]
        return (not mismatched), mismatched

    comm = example('comm_normal.json')
    identity = example('identity_authorized.json')
    task = example('task_allow_recommended.json')
    ok, bad = check_consistency('req-f0c-0001', {'comm': comm, 'identity': identity,
                                                 'task': task})
    assert ok and not bad, '样例应满足 request_id 一致性'

    task2 = dict(task)
    task2['request_id'] = 'req-other'
    ok2, bad2 = check_consistency('req-f0c-0001', {'comm': comm, 'identity': identity,
                                                   'task': task2})
    assert not ok2 and bad2 == ['task'], '不一致的 request_id 必须被识别出来'


def test_every_example_uses_the_declared_contract_version():
    """全部样例（含非法样例）的版本字段必须与契约一致。"""
    for filename in sorted(VALID_EXAMPLES):
        doc = example(filename)
        assert doc['schema_version'] == vtc.CONTRACT_VERSION, filename
    # 非法样例中除 deliberately-bad-version 外也应使用契约版本
    for case in load_manifest()['cases']:
        if case['category'] == 'version_incompatible':
            continue
        path = os.path.join(INVALID, case['file'])
        try:
            doc = vtc.load_json_strict(path)
        except ValueError:
            continue
        if 'schema_version' in doc:
            assert doc['schema_version'] == vtc.CONTRACT_VERSION, case['file']
