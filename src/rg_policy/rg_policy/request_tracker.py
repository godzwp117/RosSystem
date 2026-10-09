"""Synchronous duplicate-request and rate-limit accounting.

These two rules depend on *time* and on *previous requests*, so they cannot live
in the pure ``policy_engine.evaluate``. The Gateway composes them in this order:

    evaluate(request, policy)  ->  DUPLICATE_REQUEST  ->  RATE_LIMIT

The clock is injected (``now``) so unit tests are deterministic and no test needs
to sleep.

Semantics
---------
* ``note_received`` is called once per received Goal, *before* policy evaluation.
  It records the ``request_id`` arrival time and reports whether the same id was
  already seen inside ``duplicate_ttl_sec``. A duplicate is reported at its
  position in the validation sequence, but the arrival is always recorded.
* ``admit`` is called only for requests that already passed every policy check.
  It answers "is this request within the sliding-window rate limit?" and, if so,
  counts it. Blocked requests never consume rate budget, so a burst of rejected
  requests cannot mask a later legitimate one.

The rate window is fixed at 60 s because the policy field is
``max_requests_per_minute``.
"""

from __future__ import annotations

import threading
from collections import deque
from typing import Any, Deque, Dict, Optional

RATE_WINDOW_SEC = 60.0
DEFAULT_DUPLICATE_TTL_SEC = 600.0
DEFAULT_MAX_TRACKED_REQUEST_IDS = 20000


class RequestTracker:
    def __init__(
        self,
        duplicate_ttl_sec: float = DEFAULT_DUPLICATE_TTL_SEC,
        rate_window_sec: float = RATE_WINDOW_SEC,
        max_tracked_request_ids: int = DEFAULT_MAX_TRACKED_REQUEST_IDS,
    ):
        self._duplicate_ttl_sec = float(duplicate_ttl_sec)
        self._rate_window_sec = float(rate_window_sec)
        self._max_tracked = int(max_tracked_request_ids)
        self._lock = threading.Lock()
        self._first_seen: Dict[str, float] = {}
        self._recent: Deque[float] = deque()
        self._duplicate_count = 0
        self._rate_limited_count = 0
        self._admitted_count = 0

    # -- internals ---------------------------------------------------------
    def _prune_locked(self, now: float) -> None:
        cutoff = now - self._duplicate_ttl_sec
        if len(self._first_seen) > self._max_tracked:
            # Bounded memory: drop the oldest half by arrival time.
            for key, _ in sorted(self._first_seen.items(), key=lambda kv: kv[1])[
                    : len(self._first_seen) // 2]:
                del self._first_seen[key]
        for key in [k for k, seen in self._first_seen.items() if seen < cutoff]:
            del self._first_seen[key]
        rate_cutoff = now - self._rate_window_sec
        while self._recent and self._recent[0] < rate_cutoff:
            self._recent.popleft()

    # -- public API --------------------------------------------------------
    def note_received(self, request_id: str, now: float) -> bool:
        """Record arrival; return True when this id was already seen (duplicate)."""
        with self._lock:
            self._prune_locked(now)
            duplicate = request_id in self._first_seen
            if not duplicate:
                self._first_seen[request_id] = now
            else:
                self._duplicate_count += 1
            return duplicate

    def admit(self, now: float, max_requests_per_minute: float) -> bool:
        """Rate-limit check for an otherwise-valid request. Counts it when allowed."""
        with self._lock:
            self._prune_locked(now)
            if len(self._recent) >= int(max_requests_per_minute):
                self._rate_limited_count += 1
                return False
            self._recent.append(now)
            self._admitted_count += 1
            return True

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                'tracked_request_ids': len(self._first_seen),
                'requests_in_rate_window': len(self._recent),
                'duplicate_count': self._duplicate_count,
                'rate_limited_count': self._rate_limited_count,
                'admitted_count': self._admitted_count,
                'duplicate_ttl_sec': self._duplicate_ttl_sec,
                'rate_window_sec': self._rate_window_sec,
            }

    def reset(self) -> None:
        with self._lock:
            self._first_seen.clear()
            self._recent.clear()
            self._duplicate_count = 0
            self._rate_limited_count = 0
            self._admitted_count = 0

    # -- introspection helpers used by unit tests --------------------------
    def seen_ids(self) -> Optional[list]:
        with self._lock:
            return sorted(self._first_seen)
