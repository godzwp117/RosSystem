"""Interface-contract tests: the frozen Action definition and resource names.

方案v1.2 §2.2 freezes ``rg_interfaces/action/PatrolNavigate.action``; §2.1 freezes
the topic/Action names. These tests read the source of truth directly so that a
silent field rename or reorder fails the suite rather than the integration run.
"""

import os
import re

import pytest

from conftest import ACTION_FILE, WORKSPACE_ROOT

# Frozen contract (compare with 方案v1.2 §2.2).
EXPECTED_GOAL = [
    ('string', 'request_id'),
    ('string', 'task_id'),
    ('geometry_msgs/PoseStamped', 'target'),
]
EXPECTED_RESULT = [
    ('bool', 'success'),
    ('string', 'status_code'),
    ('string', 'detail'),
]
EXPECTED_FEEDBACK = [
    ('float32', 'progress'),
    ('string', 'phase'),
]

FROZEN_NAMES = {
    'topic_task_info': '/rg/task_info',
    'action_guarded_navigate': '/rg/guarded_navigate',
    'action_nav_execute': '/rg/nav_execute',
}


def _parse_action_file(path):
    """Return {'goal': [(type, name), ...], 'result': [...], 'feedback': [...]}."""
    with open(path, 'r', encoding='utf-8') as handle:
        lines = handle.readlines()

    sections = {'goal': [], 'result': [], 'feedback': []}
    order = ['goal', 'result', 'feedback']
    index = 0
    for raw in lines:
        line = raw.split('#', 1)[0].strip()
        if not line:
            continue
        if set(line) == {'-'}:
            index += 1
            continue
        parts = line.split()
        if len(parts) != 2:
            raise AssertionError('unparseable action line: {0!r}'.format(raw))
        sections[order[index]].append((parts[0], parts[1]))
    return sections


def test_action_file_exists():
    assert os.path.isfile(ACTION_FILE), ACTION_FILE


def test_goal_fields_are_frozen():
    assert _parse_action_file(ACTION_FILE)['goal'] == EXPECTED_GOAL


def test_result_fields_are_frozen():
    assert _parse_action_file(ACTION_FILE)['result'] == EXPECTED_RESULT


def test_feedback_fields_are_frozen():
    assert _parse_action_file(ACTION_FILE)['feedback'] == EXPECTED_FEEDBACK


def test_action_file_has_exactly_two_separators():
    with open(ACTION_FILE, 'r', encoding='utf-8') as handle:
        text = handle.read()
    separators = [line for line in text.splitlines() if line.strip() == '---']
    assert len(separators) == 2

    # client-side note required by §2.2 (GoalRejected is possible, correlate by request_id)
    assert 'request_id' in text


def test_generated_interface_matches_the_action_file():
    """If rg_interfaces is built, the generated Python type must agree.

    rosidl reports the IDL spelling (``boolean``/``float``) while the ``.action``
    source uses ``bool``/``float32``; those normalisations are the only allowed
    differences.
    """
    action_module = pytest.importorskip(
        'rg_interfaces.action', reason='rg_interfaces is not on the PYTHONPATH')
    patrol = action_module.PatrolNavigate

    rosidl_spelling = {'boolean': 'bool', 'float': 'float32'}

    def normalise(fields):
        return [(rosidl_spelling.get(type_name, type_name), name)
                for type_name, name in fields]

    def as_tuples(field_types):
        return [(type_name, name) for name, type_name in field_types.items()]

    assert normalise(as_tuples(patrol.Goal.get_fields_and_field_types())) == EXPECTED_GOAL
    assert normalise(
        as_tuples(patrol.Result.get_fields_and_field_types())) == EXPECTED_RESULT
    assert normalise(
        as_tuples(patrol.Feedback.get_fields_and_field_types())) == EXPECTED_FEEDBACK


def test_frozen_resource_names_are_used_in_source():
    files = {
        'topic_task_info': os.path.join(
            WORKSPACE_ROOT, 'src', 'rg_demo_nodes', 'rg_demo_nodes', 'operator_node.py'),
        'action_guarded_navigate': os.path.join(
            WORKSPACE_ROOT, 'src', 'rg_demo_nodes', 'rg_demo_nodes', 'planner_node.py'),
        'action_nav_execute': os.path.join(
            WORKSPACE_ROOT, 'src', 'rg_demo_nodes', 'rg_demo_nodes', 'navigation_sim.py'),
    }
    for name, path in files.items():
        with open(path, 'r', encoding='utf-8') as handle:
            text = handle.read()
        assert FROZEN_NAMES[name] in text, '{0} missing from {1}'.format(
            FROZEN_NAMES[name], os.path.relpath(path, WORKSPACE_ROOT))


def test_planner_egress_is_not_configurable():
    """The Planner must not be pointable at any resource other than the gateway."""
    path = os.path.join(WORKSPACE_ROOT, 'src', 'rg_demo_nodes', 'rg_demo_nodes',
                        'planner_node.py')
    with open(path, 'r', encoding='utf-8') as handle:
        text = handle.read()
    assert "GUARDED_NAVIGATE_ACTION = '/rg/guarded_navigate'" in text
    assert not re.search(r"declare_parameter\(\s*'action_name'", text)
    assert not re.search(r"declare_parameter\(\s*'action'", text)


def test_gateway_action_names_and_defaults():
    gateway = pytest.importorskip(
        'rg_gateway.security_gateway', reason='rg_gateway is not on the PYTHONPATH')
    assert gateway.DEFAULT_UPSTREAM_ACTION == FROZEN_NAMES['action_guarded_navigate']
    assert gateway.DEFAULT_DOWNSTREAM_ACTION == FROZEN_NAMES['action_nav_execute']
    assert gateway.EXECUTOR_THREADS >= 2, 'blocking execute_callback needs >= 2 workers'


def test_reason_code_vocabulary_is_frozen():
    from rg_policy import reason_codes
    assert reason_codes.DECISION_REASON_CODES == (
        'ALLOW_IN_POLICY', 'TASK_MISMATCH', 'INVALID_TARGET', 'OUT_OF_REGION',
        'POLICY_MISSING', 'DUPLICATE_REQUEST', 'RATE_LIMIT', 'EXECUTION_TIMEOUT',
    )
    # the only documented addition, kept outside the frozen tuple
    assert reason_codes.AUDIT_UNAVAILABLE not in reason_codes.DECISION_REASON_CODES
    assert reason_codes.AUDIT_UNAVAILABLE in reason_codes.ACCEPTED_DECISION_REASON_CODES


def test_policy_schema_fields_are_frozen():
    from rg_policy.task_policy import REGION_FIELDS, REQUIRED_FIELDS
    assert REQUIRED_FIELDS == (
        'task_id', 'policy_version', 'active', 'coordinate_frame',
        'allowed_region', 'max_requests_per_minute',
    )
    assert REGION_FIELDS == ('x_min', 'x_max', 'y_min', 'y_max')


def test_authoritative_policy_matches_the_documented_example():
    """config/task_policy.yaml must be the §2.2 example, not something wider."""
    from rg_policy.task_policy import load_task_policy
    policy = load_task_policy(os.path.join(WORKSPACE_ROOT, 'config', 'task_policy.yaml'))
    assert policy.task_id == 'patrol_a_001'
    assert policy.policy_version == '1.0'
    assert policy.active is True
    assert policy.coordinate_frame == 'map'
    assert policy.region.as_dict() == {'x_min': 0.0, 'x_max': 4.0, 'y_min': 0.0, 'y_max': 4.0}
    assert policy.max_requests_per_minute == 10


def test_rg_policy_is_ros_free():
    """Architectural guarantee: the decision core must not depend on the middleware.

    方案v1.2 §3.3 requires the admission logic to be a plain, testable Python
    function; if rg_policy ever imported rclpy the unit tests would need a ROS
    context and the security logic would become untestable in isolation.
    """
    policy_root = os.path.join(WORKSPACE_ROOT, 'src', 'rg_policy', 'rg_policy')
    offenders = []
    for filename in sorted(os.listdir(policy_root)):
        if not filename.endswith('.py'):
            continue
        with open(os.path.join(policy_root, filename), 'r', encoding='utf-8') as handle:
            for number, line in enumerate(handle, start=1):
                stripped = line.strip()
                if stripped.startswith(('import rclpy', 'from rclpy')):
                    offenders.append('{0}:{1}'.format(filename, number))
    assert not offenders, 'rg_policy must not import rclpy: {0}'.format(offenders)


def test_no_key_material_is_committed():
    """禁止把密钥材料提交到源码（任务 U1 §10 / M2 C4）。

    M2 之后 `security/keystore/` 会成为**运行时**密钥库（SROS 2 私钥、证书、权限签名），
    因此"磁盘上不存在 .pem"已不再是正确判据。正确且更强的判据是：

    1. 任何密钥类文件都不得被 git 跟踪（`git ls-files`）—— 这才是"不提交源码"的含义；
    2. 密钥材料只允许出现在明确指定的排除目录（`security/keystore/`、`security/enclaves/`）内，
       源码树的其他位置一律不允许；
    3. 这些排除目录必须真的被 `.gitignore` 排除，否则第 1 条只是碰巧成立。

    这样既不放过"误提交私钥"，也不会因为正常的运行时密钥库而误报。
    """
    import subprocess

    key_dir_prefixes = ('security/keystore', 'security/enclaves')
    forbidden_suffixes = ('.pem', '.key', '.p12', '.pfx', '.crt', '.csr', '.der', '.srl')

    # --- 1) 任何被 git 跟踪的密钥类文件都是违规 ---
    tracked = subprocess.run(['git', 'ls-files'], cwd=WORKSPACE_ROOT,
                             capture_output=True, text=True, check=False).stdout.splitlines()
    tracked_keys = [path for path in tracked if path.lower().endswith(forbidden_suffixes)]
    assert not tracked_keys, '密钥类文件被纳入版本控制: {0}'.format(tracked_keys)

    # --- 2) 源码树里密钥材料只能出现在排除目录内 ---
    offenders = []
    for dirpath, dirnames, filenames in os.walk(WORKSPACE_ROOT):
        dirnames[:] = [name for name in dirnames
                       if name not in {'build', 'install', 'log', 'evidence', '.git',
                                       '__pycache__'}]
        for filename in filenames:
            if not filename.lower().endswith(forbidden_suffixes):
                continue
            rel = os.path.relpath(os.path.join(dirpath, filename), WORKSPACE_ROOT)
            if not rel.replace(os.sep, '/').startswith(key_dir_prefixes):
                offenders.append(rel)
    assert not offenders, '排除目录之外出现密钥类文件: {0}'.format(offenders)

    # --- 3) 排除目录必须真的被 .gitignore 覆盖 ---
    ignore_text = ''
    ignore_path = os.path.join(WORKSPACE_ROOT, '.gitignore')
    if os.path.isfile(ignore_path):
        with open(ignore_path, 'r', encoding='utf-8') as handle:
            ignore_text = handle.read()
    for pattern in ('/security/keystore/', '/security/enclaves/'):
        assert pattern in ignore_text, '.gitignore 缺少密钥目录排除规则: {0}'.format(pattern)

    # --- 4) 真被 git 忽略时才允许存在（防止 ignore 规则被写错方向）---
    if os.path.isdir(os.path.join(WORKSPACE_ROOT, 'security', 'keystore')):
        check = subprocess.run(
            ['git', 'check-ignore', '-q', 'security/keystore/private/ca.key.pem'],
            cwd=WORKSPACE_ROOT, check=False).returncode
        assert check == 0, 'security/keystore 未被 git 忽略，存在误提交风险'
