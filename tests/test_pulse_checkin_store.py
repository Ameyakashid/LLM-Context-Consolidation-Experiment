"""Tests for ``PulseCheckinStore`` — adapter between the Pulse engine
and the existing ``CheckInScheduleStore``.

Covers:
* ``concern_id_to_checkin_type`` round-trip + rejection of unknown ids.
* ``CHECKIN_CONCERN_IDS`` identity with ``ALL_CHECKIN_TYPES``.
* ``PulseCheckinStore.next_fire_time`` — earliest enabled entry, disabled
  filter, retroactive "due-now" collapse to the injected clock.
* ``PulseCheckinStore.claim_due_concerns`` — staleness honoured both
  ways, naive-datetime rejected, adapter is idempotent (purity proof).
* A synthetic 24-hour sweep showing each of the four default check-ins
  fires exactly once in its window.
* ``advance_last_run`` delegates to ``record_fired``.
* Structural ``PulseStoreProtocol`` conformance via a typed sink.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, TypeVar
from zoneinfo import ZoneInfo

import pytest

from checkin_schedule import (
    ALL_CHECKIN_TYPES,
    CheckInScheduleStore,
    CheckInType,
)
from pulse_checkin_store import (
    CHECKIN_CONCERN_IDS,
    PulseCheckinStore,
    advance_last_run,
    concern_id_to_checkin_type,
)
from pulse_engine import PulseStoreProtocol
from pulse_schedule import ConcernId

LA = ZoneInfo("America/Los_Angeles")
UTC = timezone.utc

_T = TypeVar("_T")


def _run(coro: Coroutine[Any, Any, _T]) -> _T:
    return asyncio.run(coro)


def _frozen_now(moment: datetime):  # type: ignore[no-untyped-def]
    def provider() -> datetime:
        return moment

    return provider


def _make_store(tmp_path: Path) -> CheckInScheduleStore:
    return CheckInScheduleStore(tmp_path / "schedules.json")


class TestConcernIdMapping:
    def test_all_four_types_round_trip(self) -> None:
        for type_id in ALL_CHECKIN_TYPES:
            assert concern_id_to_checkin_type(type_id) == type_id

    def test_unknown_id_returns_none(self) -> None:
        assert concern_id_to_checkin_type("unknown_checkin") is None
        assert concern_id_to_checkin_type("") is None

    def test_concern_id_set_matches_all_checkin_types(self) -> None:
        assert CHECKIN_CONCERN_IDS == ALL_CHECKIN_TYPES


class TestNextFireTime:
    def test_returns_none_when_all_disabled(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        for type_id in ALL_CHECKIN_TYPES:
            store.set_enabled(type_id, False)  # type: ignore[arg-type]
        now = datetime(2026, 4, 19, 7, 0, tzinfo=UTC)
        adapter = PulseCheckinStore(store, LA, now_provider=_frozen_now(now))
        assert _run(adapter.next_fire_time()) is None

    def test_ignores_disabled_entries(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        # Keep only morning_motivation (08:00 local); disable the rest.
        for type_id in ("morning_plan", "afternoon_check", "evening_review"):
            store.set_enabled(type_id, False)
        # 2026-04-19 00:00 LA PDT == 07:00 UTC; next 08:00 LA == 15:00 UTC.
        now = datetime(2026, 4, 19, 7, 0, tzinfo=UTC)
        adapter = PulseCheckinStore(store, LA, now_provider=_frozen_now(now))
        result = _run(adapter.next_fire_time())
        assert result == datetime(2026, 4, 19, 15, 0, tzinfo=UTC)

    def test_returns_earliest_enabled_entry(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        # Defaults: morning_motivation 08:00 is earliest.
        now = datetime(2026, 4, 19, 6, 30, tzinfo=UTC)  # 23:30 LA previous day
        adapter = PulseCheckinStore(store, LA, now_provider=_frozen_now(now))
        result = _run(adapter.next_fire_time())
        assert result == datetime(2026, 4, 19, 15, 0, tzinfo=UTC)

    def test_retroactive_fire_collapses_to_now(self, tmp_path: Path) -> None:
        """09:30 LA after 08:00 morning_motivation (staleness 120 min)
        must fire *now*, not tomorrow at 08:00. This is the sub-03 parity
        gate — legacy ``SchedulingHook`` fires on every heartbeat poll.
        """
        store = _make_store(tmp_path)
        # Disable the other three so only morning_motivation matters.
        for type_id in ("morning_plan", "afternoon_check", "evening_review"):
            store.set_enabled(type_id, False)
        now_utc = datetime(2026, 4, 19, 16, 30, tzinfo=UTC)  # 09:30 LA
        adapter = PulseCheckinStore(store, LA, now_provider=_frozen_now(now_utc))
        result = _run(adapter.next_fire_time())
        assert result == now_utc

    def test_expired_staleness_returns_tomorrow_cron_slot(
        self, tmp_path: Path,
    ) -> None:
        """11:30 LA is past 08:00 + 120 min staleness → next fire is
        tomorrow 08:00 LA, not today."""
        store = _make_store(tmp_path)
        for type_id in ("morning_plan", "afternoon_check", "evening_review"):
            store.set_enabled(type_id, False)
        now_utc = datetime(2026, 4, 19, 18, 30, tzinfo=UTC)  # 11:30 LA
        adapter = PulseCheckinStore(store, LA, now_provider=_frozen_now(now_utc))
        result = _run(adapter.next_fire_time())
        assert result == datetime(2026, 4, 20, 15, 0, tzinfo=UTC)


class TestClaimDueConcerns:
    def test_rejects_naive_datetime(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        adapter = PulseCheckinStore(store, LA)
        with pytest.raises(ValueError, match="tz-aware"):
            _run(adapter.claim_due_concerns(datetime(2026, 4, 19, 8, 0)))

    def test_due_within_staleness_returned(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        for type_id in ("morning_plan", "afternoon_check", "evening_review"):
            store.set_enabled(type_id, False)
        # 09:30 LA → within 08:00 + 120 min window.
        now = datetime(2026, 4, 19, 16, 30, tzinfo=UTC)
        adapter = PulseCheckinStore(store, LA)
        result = _run(adapter.claim_due_concerns(now))
        assert result == ["morning_motivation"]

    def test_staleness_expired_excluded(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        for type_id in ("morning_plan", "afternoon_check", "evening_review"):
            store.set_enabled(type_id, False)
        # 11:30 LA → past 08:00 + 120 min → not returned.
        now = datetime(2026, 4, 19, 18, 30, tzinfo=UTC)
        adapter = PulseCheckinStore(store, LA)
        assert _run(adapter.claim_due_concerns(now)) == []

    def test_before_target_excluded(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        for type_id in ("morning_plan", "afternoon_check", "evening_review"):
            store.set_enabled(type_id, False)
        # 07:30 LA → before 08:00 → not yet due.
        now = datetime(2026, 4, 19, 14, 30, tzinfo=UTC)
        adapter = PulseCheckinStore(store, LA)
        assert _run(adapter.claim_due_concerns(now)) == []

    def test_is_pure_two_calls_same_result(self, tmp_path: Path) -> None:
        """Adapter purity (AC #3): calling twice with identical ``now``
        returns identical lists without reloading the store."""
        store = _make_store(tmp_path)
        now = datetime(2026, 4, 19, 16, 30, tzinfo=UTC)  # 09:30 LA
        adapter = PulseCheckinStore(store, LA)
        first = _run(adapter.claim_due_concerns(now))
        second = _run(adapter.claim_due_concerns(now))
        assert first == second
        # 09:30 LA → morning_motivation (08:00 +120 min) and morning_plan
        # (09:00 +120 min) are both within their staleness windows.
        assert first == ["morning_motivation", "morning_plan"]

    def test_last_run_today_excludes_entry(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        for type_id in ("morning_plan", "afternoon_check", "evening_review"):
            store.set_enabled(type_id, False)
        today_la = date(2026, 4, 19)
        store.record_fired("morning_motivation", today_la)
        now = datetime(2026, 4, 19, 16, 30, tzinfo=UTC)  # 09:30 LA
        adapter = PulseCheckinStore(store, LA)
        assert _run(adapter.claim_due_concerns(now)) == []

    def test_24h_sweep_each_checkin_fires_once(self, tmp_path: Path) -> None:
        """Walk a full local day in 15-minute steps. Each of the four
        default check-ins must be claim-due at *some* step and not
        duplicated if ``advance_last_run`` is called after the first fire.
        """
        store = _make_store(tmp_path)
        adapter = PulseCheckinStore(store, LA)
        start_local = datetime(2026, 4, 19, 0, 0, tzinfo=LA)
        step = timedelta(minutes=15)
        fires: dict[CheckInType, int] = {
            "morning_motivation": 0,
            "morning_plan": 0,
            "afternoon_check": 0,
            "evening_review": 0,
        }
        for step_index in range(96):  # 24 h / 15 min
            now = (start_local + step * step_index).astimezone(UTC)
            for concern in _run(adapter.claim_due_concerns(now)):
                fires[concern] += 1  # type: ignore[index]
                advance_last_run(store, concern, now.astimezone(LA).date())  # type: ignore[arg-type]
        assert fires == {
            "morning_motivation": 1,
            "morning_plan": 1,
            "afternoon_check": 1,
            "evening_review": 1,
        }


class TestAdvanceLastRun:
    def test_calls_record_fired(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        today = date(2026, 4, 19)
        advance_last_run(store, "morning_motivation", today)
        assert store.get_entry("morning_motivation").last_run_date == today

    def test_subsequent_claim_excludes_entry(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        for type_id in ("morning_plan", "afternoon_check", "evening_review"):
            store.set_enabled(type_id, False)
        now = datetime(2026, 4, 19, 16, 30, tzinfo=UTC)  # 09:30 LA
        adapter = PulseCheckinStore(store, LA)
        assert _run(adapter.claim_due_concerns(now)) == ["morning_motivation"]
        advance_last_run(store, "morning_motivation", date(2026, 4, 19))
        assert _run(adapter.claim_due_concerns(now)) == []


class TestProtocolConformance:
    def test_pulse_checkin_store_satisfies_pulse_store_protocol(
        self, tmp_path: Path,
    ) -> None:
        """Structural (non-runtime-checkable) Protocol conformance proof.

        The annotation binding triggers mypy's structural check. At
        runtime this is a no-op identity assignment — if any of the two
        awaitable methods is misnamed, mypy --strict rejects the line.
        """
        store = _make_store(tmp_path)
        adapter = PulseCheckinStore(store, LA)
        sink: PulseStoreProtocol = adapter
        assert sink is adapter


def test_returning_concern_ids_are_plain_strings(tmp_path: Path) -> None:
    """``ConcernId`` is aliased to ``str`` (pulse_schedule.py:23); the
    adapter's ``claim_due_concerns`` must not accidentally emit Enum or
    richer objects — Pulse's queue serialises via ``PulseEvent``."""
    store = _make_store(tmp_path)
    for type_id in ("morning_plan", "afternoon_check", "evening_review"):
        store.set_enabled(type_id, False)
    now = datetime(2026, 4, 19, 16, 30, tzinfo=UTC)
    adapter = PulseCheckinStore(store, LA)
    result: list[ConcernId] = _run(adapter.claim_due_concerns(now))
    assert all(isinstance(item, str) for item in result)
    assert result == ["morning_motivation"]


def test_naive_now_provider_raises(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    naive_provider = lambda: datetime(2026, 4, 19, 16, 30)  # noqa: E731
    adapter = PulseCheckinStore(store, LA, now_provider=naive_provider)
    with pytest.raises(ValueError, match="tz-aware UTC"):
        _run(adapter.next_fire_time())


def test_returns_time_in_utc(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    now = datetime(2026, 4, 19, 6, 0, tzinfo=UTC)  # 23:00 LA prev day
    adapter = PulseCheckinStore(store, LA, now_provider=_frozen_now(now))
    result = _run(adapter.next_fire_time())
    assert result is not None
    assert result.tzinfo is UTC


def test_custom_target_time_propagates_to_cron(tmp_path: Path) -> None:
    """Changing a check-in's ``target_time`` must move the next fire."""
    store = _make_store(tmp_path)
    for type_id in ("morning_plan", "afternoon_check", "evening_review"):
        store.set_enabled(type_id, False)
    store.set_time("morning_motivation", time(7, 15))
    # 05:00 UTC == 22:00 LA previous day; next 07:15 LA == 14:15 UTC.
    now = datetime(2026, 4, 19, 5, 0, tzinfo=UTC)
    adapter = PulseCheckinStore(store, LA, now_provider=_frozen_now(now))
    result = _run(adapter.next_fire_time())
    assert result == datetime(2026, 4, 19, 14, 15, tzinfo=UTC)
