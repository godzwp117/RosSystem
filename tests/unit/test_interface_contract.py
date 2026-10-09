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
    """Task requirement 10: no keys/private material in the source tree."""
    forbidden_suffixes = ('.pem', '.key', '.p12', '.pfx', '.crt', '.csr', '.der')
    offenders = []
    for dirpath, dirnames, filenames in os.walk(WORKSPACE_ROOT):
        dirnames[:] = [name for name in dirnames
                       if name not in {'build', 'install', 'log', 'evidence', '.git',
                                       '__pycache__'}]
        for filename in filenames:
            if filename.lower().endswith(forbidden_suffixes):
                offenders.append(os.path.relpath(os.path.join(dirpath, filename),
                                                 WORKSPACE_ROOT))
    assert not offenders, 'key-like files present: {0}'.format(offenders)
