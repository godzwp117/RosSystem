"""Unit tests for the pure admission decision ``policy_engine.evaluate``.

方案v1.2 §3.3 requires ``evaluate(request, policy)`` to be a pure Python function.
These tests pin the full rule table, the documented precedence order, and purity.
"""

import math

import pytest

from rg_policy import reason_codes
from rg_policy.policy_engine import Decision, NavRequest, evaluate
from rg_policy.task_policy import load_task_policy, parse_task_policy
from conftest import DEFAULT_POLICY_PATH

POLICY = load_task_policy(DEFAULT_POLICY_PATH)
INACTIVE_POLICY = parse_task_policy({
    'task_id': 'patrol_a_001',
    'policy_version': '1.0-inactive',
    'active': False,
    'coordinate_frame': 'map',
    'allowed_region': {'x_min': 0.0, 'x_max': 4.0, 'y_min': 0.0, 'y_max': 4.0},
    'max_requests_per_minute': 10,
}, '/tmp/inactive.yaml')


def request(**overrides):
    values = {
        'request_id': 'req-1',
        'task_id': 'patrol_a_001',
        'frame_id': 'map',
        'x': 1.5,
        'y': 1.5,
        'z': 0.0,
    }
    values.update(overrides)
    return NavRequest(**values)


# ------------------------------------------------------------------ ALLOW
@pytest.mark.parametrize('x,y', [
    (0.0, 0.0), (4.0, 4.0), (0.0, 4.0), (4.0, 0.0), (2.0, 2.0), (3.999, 0.001),
])
def test_in_region_targets_are_allowed(x, y):
    decision = evaluate(request(x=x, y=y), POLICY)
    assert decision.allowed
    assert decision.reason_code == reason_codes.ALLOW_IN_POLICY
    assert decision.policy_version == '1.0'


def test_z_is_not_region_constrained():
    """The frozen policy region is 2-D; z only has to be finite."""
    assert evaluate(request(z=1234.5), POLICY).allowed


# --------------------------------------------------------------- BLOCK rules
@pytest.mark.parametrize('x,y', [
    (9.0, 9.0), (-0.001, 2.0), (2.0, -0.001), (4.001, 2.0), (2.0, 4.001), (1e6, 1e6),
])
def test_out_of_region_targets_are_blocked(x, y):
    decision = evaluate(request(x=x, y=y), POLICY)
    assert not decision.allowed
    assert decision.reason_code == reason_codes.OUT_OF_REGION


def test_task_id_mismatch_is_blocked():
    decision = evaluate(request(task_id='patrol_b_042'), POLICY)
    assert decision.reason_code == reason_codes.TASK_MISMATCH


@pytest.mark.parametrize('bad_task', ['', '   ', 'PATROL_A_001', 'patrol_a_001 '])
def test_empty_or_nonmatching_task_id_is_blocked(bad_task):
    decision = evaluate(request(task_id=bad_task), POLICY)
    assert decision.reason_code == reason_codes.TASK_MISMATCH


@pytest.mark.parametrize('bad_frame', ['camera_link', '', '   ', 'MAP', 'odom'])
def test_invalid_frame_id_is_blocked(bad_frame):
    decision = evaluate(request(frame_id=bad_frame), POLICY)
    assert not decision.allowed
    assert decision.reason_code == reason_codes.INVALID_TARGET


@pytest.mark.parametrize('bad_id', ['', '   ', None])
def test_missing_request_id_is_blocked(bad_id):
    decision = evaluate(request(request_id=bad_id), POLICY)
    assert not decision.allowed
    assert decision.reason_code == reason_codes.INVALID_TARGET


@pytest.mark.parametrize('component', ['x', 'y', 'z'])
@pytest.mark.parametrize('bad', [float('nan'), float('inf'), float('-inf')])
def test_non_finite_target_components_are_blocked(component, bad):
    decision = evaluate(request(**{component: bad}), POLICY)
    assert not decision.allowed
    assert decision.reason_code == reason_codes.INVALID_TARGET
    assert component in decision.detail


def test_non_numeric_target_component_is_blocked():
    decision = evaluate(request(x='1.5'), POLICY)
    assert decision.reason_code == reason_codes.INVALID_TARGET


# --------------------------------------------------- policy absence / inactivity
def test_missing_policy_is_blocked():
    decision = evaluate(request(), None)
    assert not decision.allowed
    assert decision.reason_code == reason_codes.POLICY_MISSING
    assert decision.policy_version == reason_codes.POLICY_VERSION_UNKNOWN


def test_inactive_policy_is_blocked():
    decision = evaluate(request(), INACTIVE_POLICY)
    assert not decision.allowed
    assert decision.reason_code == reason_codes.POLICY_MISSING
    assert 'active: false' in decision.detail


# ------------------------------------------------------------- precedence
def test_policy_check_precedes_every_request_check():
    """No policy => POLICY_MISSING even for a request that is also invalid."""
    decision = evaluate(request(x=float('nan'), task_id='nope', frame_id='nope'), None)
    assert decision.reason_code == reason_codes.POLICY_MISSING


def test_task_check_precedes_frame_check():
    decision = evaluate(request(task_id='nope', frame_id='nope'), POLICY)
    assert decision.reason_code == reason_codes.TASK_MISMATCH


def test_frame_check_precedes_finiteness_check():
    decision = evaluate(request(frame_id='nope', x=float('nan')), POLICY)
    assert decision.reason_code == reason_codes.INVALID_TARGET
    assert 'frame_id' in decision.detail


def test_finiteness_check_precedes_region_check():
    """NaN must be reported as INVALID_TARGET, never as OUT_OF_REGION."""
    decision = evaluate(request(x=float('nan'), y=9.0), POLICY)
    assert decision.reason_code == reason_codes.INVALID_TARGET


# ------------------------------------------------------------------ purity
def test_evaluate_is_pure_and_repeatable():
    req = request()
    first = evaluate(req, POLICY)
    second = evaluate(req, POLICY)
    assert first == second
    assert isinstance(first, Decision)
    assert POLICY.region.contains(1.5, 1.5)  # policy object unchanged


def test_evaluate_does_not_mutate_policy_or_request():
    req = request(x=9.0)
    before = POLICY.as_dict()
    evaluate(req, POLICY)
    evaluate(req, None)
    assert POLICY.as_dict() == before
    assert req.as_dict()['x'] == 9.0


def test_decision_serialisation_exposes_reason_code_and_version():
    payload = evaluate(request(x=9.0), POLICY).as_dict()
    assert payload['decision'] == reason_codes.DECISION_BLOCK
    assert payload['reason_code'] == reason_codes.OUT_OF_REGION
    assert payload['policy_version'] == '1.0'


def test_every_reason_code_is_reachable():
    """Sanity: the block codes exercised here come from the frozen vocabulary."""
    produced = {
        evaluate(request(x=9.0), POLICY).reason_code,
        evaluate(request(task_id='x'), POLICY).reason_code,
        evaluate(request(frame_id='x'), POLICY).reason_code,
        evaluate(request(), None).reason_code,
        evaluate(request(), POLICY).reason_code,
    }
    assert produced <= set(reason_codes.DECISION_REASON_CODES)
