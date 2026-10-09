"""Unit tests for the frozen audit event schema and the JSONL sink.

方案v1.2 §2.3: the three event types share ``event_id``; key fields must never be
silently defaulted; rejected requests must be traceable by ``request_id``.
"""

import json
import math
import os

import pytest

from rg_policy import reason_codes
from rg_policy.events import (
    DecisionEvent,
    EventWriter,
    ExecutionEvent,
    RosCommEvent,
    events_of_type,
    new_event_id,
    read_events,
    trace_by_event_id,
    utc_now_iso,
)

FROZEN_ROS_COMM_FIELDS = {
    'event_id', 'request_id', 'task_id', 'observed_via', 'resource',
    'frame_id', 'x', 'y', 'received_at',
}
FROZEN_DECISION_FIELDS = {
    'event_id', 'policy_version', 'decision', 'reason_code', 'decision_at',
}
FROZEN_EXECUTION_FIELDS = {
    'event_id', 'downstream_goal_id', 'success', 'status_code', 'finished_at',
}


def comm_event(**overrides):
    values = {
        'event_id': 'e' * 32,
        'request_id': 'req-1',
        'task_id': 'patrol_a_001',
        'observed_via': 'ros2_action',
        'resource': '/rg/guarded_navigate',
        'frame_id': 'map',
        'x': 1.5,
        'y': 2.5,
        'z': 0.0,
        'received_at': utc_now_iso(),
    }
    values.update(overrides)
    return RosCommEvent(**values)


def decision_event(**overrides):
    values = {
        'event_id': 'e' * 32,
        'request_id': 'req-1',
        'task_id': 'patrol_a_001',
        'policy_version': '1.0',
        'decision': reason_codes.DECISION_ALLOW,
        'reason_code': reason_codes.ALLOW_IN_POLICY,
        'detail': 'ok',
        'decision_at': utc_now_iso(),
    }
    values.update(overrides)
    return DecisionEvent(**values)


def execution_event(**overrides):
    values = {
        'event_id': 'e' * 32,
        'request_id': 'req-1',
        'task_id': 'patrol_a_001',
        'downstream_goal_id': 'a' * 32,
        'success': True,
        'status_code': reason_codes.EXECUTED,
        'detail': 'done',
        'finished_at': utc_now_iso(),
    }
    values.update(overrides)
    return ExecutionEvent(**values)


# ------------------------------------------------------------------- schema
def test_ros_comm_event_contains_every_frozen_field():
    payload = comm_event().to_dict()
    assert FROZEN_ROS_COMM_FIELDS <= set(payload)
    assert payload['event_type'] == 'RosCommEvent'


def test_decision_event_contains_every_frozen_field():
    payload = decision_event().to_dict()
    assert FROZEN_DECISION_FIELDS <= set(payload)
    assert payload['event_type'] == 'DecisionEvent'


def test_execution_event_contains_every_frozen_field():
    payload = execution_event().to_dict()
    assert FROZEN_EXECUTION_FIELDS <= set(payload)
    assert payload['event_type'] == 'ExecutionEvent'


def test_audit_events_carry_request_id_for_correlation():
    for event in (comm_event(), decision_event(), execution_event()):
        assert event.to_dict()['request_id'] == 'req-1'


# --------------------------------------------------------------- validation
@pytest.mark.parametrize('bad', ['', '   ', None])
def test_event_id_must_not_be_empty(bad):
    with pytest.raises(ValueError):
        comm_event(event_id=bad)


def test_decision_must_be_a_known_verdict():
    with pytest.raises(ValueError):
        decision_event(decision='MAYBE')


def test_reason_code_must_come_from_the_vocabulary():
    with pytest.raises(ValueError):
        decision_event(reason_code='MADE_UP_CODE')


def test_status_code_must_come_from_the_vocabulary():
    with pytest.raises(ValueError):
        execution_event(status_code='MADE_UP_STATUS')


def test_downstream_goal_id_requires_an_explicit_marker():
    """§2.3: no silent defaults -- 'no downstream goal' must be passed explicitly."""
    with pytest.raises(ValueError):
        execution_event(downstream_goal_id='')
    assert execution_event(
        downstream_goal_id=reason_codes.DOWNSTREAM_GOAL_ID_NONE).to_dict()[
            'downstream_goal_id'] == 'NONE'


def test_policy_version_requires_an_explicit_marker():
    with pytest.raises(ValueError):
        decision_event(policy_version='')
    assert decision_event(
        policy_version=reason_codes.POLICY_VERSION_UNKNOWN).to_dict()[
            'policy_version'] == 'UNKNOWN'


def test_malformed_client_input_is_still_recordable():
    """A bad request must be *loggable* -- empty task/frame are recorded, not rejected."""
    payload = comm_event(request_id='', task_id='', frame_id='').to_dict()
    assert payload['request_id'] == ''
    assert payload['task_id'] == ''
    assert payload['frame_id'] == ''


# ------------------------------------------------- non-finite target encoding
@pytest.mark.parametrize('bad,token', [
    (float('nan'), 'NaN'),
    (float('inf'), 'Infinity'),
    (float('-inf'), '-Infinity'),
])
def test_non_finite_targets_are_recorded_faithfully(bad, token):
    payload = comm_event(x=bad).to_dict()
    assert payload['x'] == token
    assert payload['target_finite'] is False


def test_finite_targets_are_recorded_as_numbers():
    payload = comm_event(x=1.5).to_dict()
    assert payload['x'] == 1.5
    assert payload['target_finite'] is True


def test_emitted_json_is_strict():
    """allow_nan=False must never be provoked: the file has to stay valid JSON."""
    record = comm_event(x=float('nan'), y=float('inf')).to_dict()
    line = json.dumps(record, allow_nan=False)
    assert json.loads(line)['x'] == 'NaN'


# ------------------------------------------------------------------- writer
def test_writer_appends_jsonl_and_round_trips(tmp_path):
    path = tmp_path / 'audit.jsonl'
    event_id = new_event_id()
    with EventWriter(str(path)) as writer:
        writer.write(comm_event(event_id=event_id))
        writer.write(decision_event(event_id=event_id, reason_code=reason_codes.OUT_OF_REGION,
                                    decision=reason_codes.DECISION_BLOCK))
        writer.write(execution_event(event_id=event_id))
    records = read_events(str(path))
    assert len(records) == 3
    assert [record['event_type'] for record in records] == [
        'RosCommEvent', 'DecisionEvent', 'ExecutionEvent']
    assert all(record['event_id'] == event_id for record in records)
    assert records[1]['reason_code'] == 'OUT_OF_REGION'


def test_writer_creates_parent_directories(tmp_path):
    path = tmp_path / 'nested' / 'deeper' / 'audit.jsonl'
    with EventWriter(str(path)) as writer:
        writer.write(comm_event())
    assert os.path.isfile(str(path))


def test_writer_flushes_so_a_running_test_can_count_records(tmp_path):
    path = tmp_path / 'audit.jsonl'
    writer = EventWriter(str(path))
    writer.write(comm_event())
    # no close(): an external reader must already see the record
    assert len(read_events(str(path))) == 1
    writer.close()
    assert writer.written == 1


def test_writer_rejects_non_event_objects(tmp_path):
    with EventWriter(str(tmp_path / 'audit.jsonl')) as writer:
        with pytest.raises(TypeError):
            writer.write({'not': 'an event'})


def test_write_after_close_raises(tmp_path):
    from rg_policy.events import AuditSinkError
    writer = EventWriter(str(tmp_path / 'audit.jsonl'))
    writer.close()
    with pytest.raises(AuditSinkError):
        writer.write(comm_event())


# --------------------------------------------------------------- traceability
def test_trace_by_event_id_groups_all_phases():
    shared = new_event_id()
    other = new_event_id()
    records = [
        comm_event(event_id=shared, request_id='r1').to_dict(),
        decision_event(event_id=shared, request_id='r1').to_dict(),
        execution_event(event_id=shared, request_id='r1').to_dict(),
        comm_event(event_id=other, request_id='r2').to_dict(),
        decision_event(event_id=other, request_id='r2', decision=reason_codes.DECISION_BLOCK,
                       reason_code=reason_codes.OUT_OF_REGION).to_dict(),
    ]
    grouped = trace_by_event_id(records)
    assert set(grouped) == {shared, other}
    assert set(grouped[shared]) >= {'RosCommEvent', 'DecisionEvent', 'ExecutionEvent'}
    assert 'ExecutionEvent' not in grouped[other]
    assert len(events_of_type(records, 'DecisionEvent')) == 2
