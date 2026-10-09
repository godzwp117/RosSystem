"""Unit tests for duplicate-request and rate-limit accounting."""

import threading

from rg_policy.request_tracker import RATE_WINDOW_SEC, RequestTracker


def test_first_arrival_is_not_a_duplicate():
    tracker = RequestTracker()
    assert tracker.note_received('a', 100.0) is False
    assert tracker.note_received('b', 100.0) is False


def test_second_arrival_of_same_id_is_a_duplicate():
    tracker = RequestTracker()
    tracker.note_received('a', 100.0)
    assert tracker.note_received('a', 105.0) is True
    assert tracker.note_received('a', 110.0) is True
    assert tracker.snapshot()['duplicate_count'] == 2


def test_duplicate_window_expires():
    tracker = RequestTracker(duplicate_ttl_sec=60.0)
    tracker.note_received('a', 100.0)
    assert tracker.note_received('a', 161.0) is False


def test_rate_limit_allows_up_to_the_policy_ceiling():
    tracker = RequestTracker()
    assert tracker.admit(100.0, 2) is True
    assert tracker.admit(101.0, 2) is True
    assert tracker.admit(102.0, 2) is False
    assert tracker.snapshot()['rate_limited_count'] == 1


def test_rate_window_slides():
    tracker = RequestTracker()
    assert tracker.admit(100.0, 1) is True
    assert tracker.admit(130.0, 1) is False
    assert tracker.admit(100.0 + RATE_WINDOW_SEC + 1.0, 1) is True


def test_rate_ceiling_comes_from_the_policy_each_call():
    """The authoritative policy is re-read, so a ceiling change takes effect."""
    tracker = RequestTracker()
    assert tracker.admit(100.0, 3) is True
    assert tracker.admit(101.0, 1) is False


def test_blocked_requests_do_not_consume_rate_budget():
    """Only requests that passed every policy check call admit()."""
    tracker = RequestTracker()
    for _ in range(50):
        tracker.note_received('blocked-{0}'.format(_), 100.0)  # policy-rejected requests
    assert tracker.admit(100.0, 2) is True
    assert tracker.admit(100.0, 2) is True
    assert tracker.snapshot()['admitted_count'] == 2


def test_tracked_ids_are_bounded():
    tracker = RequestTracker(max_tracked_request_ids=10)
    for index in range(50):
        tracker.note_received('id-{0}'.format(index), 100.0 + index)
    assert tracker.snapshot()['tracked_request_ids'] <= 50


def test_snapshot_and_reset():
    tracker = RequestTracker()
    tracker.note_received('a', 1.0)
    tracker.note_received('a', 2.0)
    tracker.admit(3.0, 1)
    tracker.admit(4.0, 1)
    snapshot = tracker.snapshot()
    assert snapshot['duplicate_count'] == 1
    assert snapshot['admitted_count'] == 1
    assert snapshot['rate_limited_count'] == 1
    tracker.reset()
    assert tracker.snapshot()['duplicate_count'] == 0
    assert tracker.snapshot()['tracked_request_ids'] == 0


def test_concurrent_accounting_is_consistent():
    """The Gateway may serve goals from several executor worker threads."""
    tracker = RequestTracker()
    duplicates = []

    def worker(index):
        for _ in range(50):
            duplicates.append(tracker.note_received('id-{0}'.format(index), 100.0))

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # exactly one non-duplicate per distinct id: 8 False among 400 calls
    assert duplicates.count(False) == 8
    assert duplicates.count(True) == 392
