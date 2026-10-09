"""Unit tests for the authoritative TaskPolicy loader and schema validator.

Covers 方案v1.2 §2.2 (trusted local policy) and the fail-closed requirement:
every load/schema failure must raise a PolicyError so the Gateway can BLOCK.
"""

import os
import time

import pytest

from conftest import DEFAULT_POLICY_PATH, SCENARIO_CONFIG_DIR
from rg_policy import reason_codes
from rg_policy.task_policy import (
    PolicyMissingError,
    PolicyProvider,
    PolicySchemaError,
    load_task_policy,
    parse_task_policy,
)

VALID_DOCUMENT = {
    'task_id': 'patrol_a_001',
    'policy_version': '1.0',
    'active': True,
    'coordinate_frame': 'map',
    'allowed_region': {'x_min': 0.0, 'x_max': 4.0, 'y_min': 0.0, 'y_max': 4.0},
    'max_requests_per_minute': 10,
}


def _document(**overrides):
    document = {key: (dict(value) if isinstance(value, dict) else value)
                for key, value in VALID_DOCUMENT.items()}
    for key, value in overrides.items():
        if value is Ellipsis:
            document.pop(key, None)
        else:
            document[key] = value
    return document


# ---------------------------------------------------------------- happy path
def test_authoritative_policy_loads_with_expected_values():
    policy = load_task_policy(DEFAULT_POLICY_PATH)
    assert policy.task_id == 'patrol_a_001'
    assert policy.policy_version == '1.0'
    assert policy.active is True
    assert policy.coordinate_frame == 'map'
    assert (policy.region.x_min, policy.region.x_max) == (0.0, 4.0)
    assert (policy.region.y_min, policy.region.y_max) == (0.0, 4.0)
    assert policy.max_requests_per_minute == 10
    assert policy.source_path == DEFAULT_POLICY_PATH
    assert policy.loaded_at.endswith('Z')


def test_region_containment_is_inclusive():
    policy = load_task_policy(DEFAULT_POLICY_PATH)
    assert policy.region.contains(0.0, 0.0)
    assert policy.region.contains(4.0, 4.0)
    assert policy.region.contains(2.0, 3.999)
    assert not policy.region.contains(4.0001, 2.0)
    assert not policy.region.contains(-0.0001, 2.0)


def test_extra_fields_are_recorded_not_fatal():
    policy = parse_task_policy(_document(future_field='x'), '/tmp/x.yaml')
    assert policy.extra_fields == ('future_field',)


def test_inactive_policy_still_loads():
    """Inactivity is a *policy* fact; evaluate() turns it into POLICY_MISSING."""
    policy = parse_task_policy(_document(active=False), '/tmp/x.yaml')
    assert policy.active is False


# ------------------------------------------------------------ missing / error
def test_missing_file_raises_policy_missing():
    with pytest.raises(PolicyMissingError) as excinfo:
        load_task_policy(os.path.join(SCENARIO_CONFIG_DIR, 'task_policy_does_not_exist.yaml'))
    assert excinfo.value.reason_code == reason_codes.POLICY_MISSING


def test_empty_path_raises_policy_missing():
    with pytest.raises(PolicyMissingError):
        load_task_policy('')


def test_unparseable_yaml_raises_policy_schema_error(tmp_path):
    broken = tmp_path / 'broken.yaml'
    broken.write_text('task_id: [unclosed\n', encoding='utf-8')
    with pytest.raises(PolicySchemaError):
        load_task_policy(str(broken))


def test_non_mapping_root_is_rejected(tmp_path):
    not_a_mapping = tmp_path / 'list.yaml'
    not_a_mapping.write_text('- a\n- b\n', encoding='utf-8')
    with pytest.raises(PolicySchemaError):
        load_task_policy(str(not_a_mapping))


@pytest.mark.parametrize('field', [
    'task_id', 'policy_version', 'active', 'coordinate_frame',
    'allowed_region', 'max_requests_per_minute',
])
def test_each_required_field_is_mandatory(field):
    """Required fields are never silently defaulted."""
    with pytest.raises(PolicySchemaError) as excinfo:
        parse_task_policy(_document(**{field: Ellipsis}), '/tmp/x.yaml')
    assert field in str(excinfo.value)


@pytest.mark.parametrize('field', ['x_min', 'x_max', 'y_min', 'y_max'])
def test_each_region_field_is_mandatory(field):
    region = dict(VALID_DOCUMENT['allowed_region'])
    region.pop(field)
    with pytest.raises(PolicySchemaError) as excinfo:
        parse_task_policy(_document(allowed_region=region), '/tmp/x.yaml')
    assert field in str(excinfo.value)


@pytest.mark.parametrize('field', ['task_id', 'policy_version', 'coordinate_frame'])
@pytest.mark.parametrize('bad', ['', '   ', 5])
def test_string_fields_must_be_non_empty_strings(field, bad):
    with pytest.raises(PolicySchemaError):
        parse_task_policy(_document(**{field: bad}), '/tmp/x.yaml')


@pytest.mark.parametrize('bad', ['true', 1, None])
def test_active_must_be_a_real_boolean(bad):
    with pytest.raises(PolicySchemaError):
        parse_task_policy(_document(active=bad), '/tmp/x.yaml')


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), '-inf', '10', True, None])
@pytest.mark.parametrize('field', ['max_requests_per_minute'])
def test_max_rate_must_be_a_finite_number(field, bad):
    with pytest.raises(PolicySchemaError):
        parse_task_policy(_document(**{field: bad}), '/tmp/x.yaml')


def test_max_rate_must_be_positive():
    with pytest.raises(PolicySchemaError):
        parse_task_policy(_document(max_requests_per_minute=0), '/tmp/x.yaml')


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), 'four', None, True])
def test_region_bounds_must_be_finite_numbers(bad):
    region = dict(VALID_DOCUMENT['allowed_region'])
    region['x_max'] = bad
    with pytest.raises(PolicySchemaError):
        parse_task_policy(_document(allowed_region=region), '/tmp/x.yaml')


def test_region_min_greater_than_max_is_rejected():
    with pytest.raises(PolicySchemaError):
        parse_task_policy(
            _document(allowed_region={'x_min': 5.0, 'x_max': 4.0, 'y_min': 0.0, 'y_max': 1.0}),
            '/tmp/x.yaml')


def test_regression_fixture_files_are_rejected():
    """The shipped malformed fixtures must fail to load."""
    for name in ('task_policy_missing_field.yaml', 'task_policy_nonfinite_region.yaml'):
        with pytest.raises(PolicySchemaError):
            load_task_policy(os.path.join(SCENARIO_CONFIG_DIR, name))


# ---------------------------------------------------------------- provider
def test_provider_reloads_on_mtime_change_and_fails_closed_when_removed(tmp_path):
    path = tmp_path / 'policy.yaml'
    path.write_text(
        'task_id: patrol_a_001\npolicy_version: "1.0"\nactive: true\n'
        'coordinate_frame: map\n'
        'allowed_region: {x_min: 0.0, x_max: 4.0, y_min: 0.0, y_max: 4.0}\n'
        'max_requests_per_minute: 10\n', encoding='utf-8')

    provider = PolicyProvider(str(path))
    policy, error = provider.current()
    assert error is None and policy.policy_version == '1.0'
    first_reloads = provider.reload_count

    # unchanged file -> cached, no extra load
    policy_again, _ = provider.current()
    assert policy_again.policy_version == '1.0'
    assert provider.reload_count == first_reloads

    # replaced content -> hot reload without restart
    time.sleep(0.01)
    path.write_text(
        'task_id: patrol_a_001\npolicy_version: "2.0"\nactive: true\n'
        'coordinate_frame: map\n'
        'allowed_region: {x_min: 0.0, x_max: 4.0, y_min: 0.0, y_max: 4.0}\n'
        'max_requests_per_minute: 10\n', encoding='utf-8')
    os.utime(str(path))
    policy_new, error_new = provider.current()
    assert error_new is None and policy_new.policy_version == '2.0'

    # removed file -> (None, PolicyError): the caller must BLOCK
    path.unlink()
    policy_none, error_missing = provider.current()
    assert policy_none is None
    assert isinstance(error_missing, PolicyMissingError)

    # restored -> recovers
    path.write_text(
        'task_id: patrol_a_001\npolicy_version: "3.0"\nactive: true\n'
        'coordinate_frame: map\n'
        'allowed_region: {x_min: 0.0, x_max: 4.0, y_min: 0.0, y_max: 4.0}\n'
        'max_requests_per_minute: 10\n', encoding='utf-8')
    policy_restored, error_restored = provider.current()
    assert error_restored is None and policy_restored.policy_version == '3.0'


def test_provider_never_raises_for_missing_file(tmp_path):
    provider = PolicyProvider(str(tmp_path / 'nope.yaml'))
    policy, error = provider.current()
    assert policy is None
    assert isinstance(error, PolicyMissingError)
