"""Tests for check-in schedule — models, serialization, and due-check logic.

Store persistence tests live in test_checkin_schedule_store.py.
"""

from datetime import date, time

import pytest

from checkin_schedule import (
    ALL_CHECKIN_TYPES,
    CheckInEntry,
    build_default_entries,
    deserialize_schedule,
    get_due_checkins,
    is_checkin_due,
    mark_checkin_fired,
    serialize_schedule,
    update_entry_enabled,
    update_entry_time,
)


# ---------------------------------------------------------------------------
# Model validation tests
# ---------------------------------------------------------------------------

class TestCheckInEntryModel:
    """Verify Pydantic model constraints and defaults."""

    def test_creates_valid_entry(self) -> None:
        entry = CheckInEntry(
            type_id="morning_plan",
            display_name="Morning Plan",
            target_time=time(9, 0),
            staleness_minutes=120,
            is_enabled=True,
        )
        assert entry.type_id == "morning_plan"
        assert entry.last_run_date is None

    def test_last_run_date_defaults_to_none(self) -> None:
        entry = CheckInEntry(
            type_id="evening_review",
            display_name="Evening Review",
            target_time=time(20, 0),
            staleness_minutes=120,
            is_enabled=True,
        )
        assert entry.last_run_date is None

    def test_rejects_invalid_type_id(self) -> None:
        with pytest.raises(ValueError):
            CheckInEntry(
                type_id="nonexistent",  # type: ignore[arg-type]
                display_name="Bad",
                target_time=time(8, 0),
                staleness_minutes=120,
                is_enabled=True,
            )

    def test_accepts_last_run_date(self) -> None:
        entry = CheckInEntry(
            type_id="afternoon_check",
            display_name="Afternoon Check",
            target_time=time(14, 0),
            staleness_minutes=120,
            is_enabled=True,
            last_run_date=date(2026, 4, 10),
        )
        assert entry.last_run_date == date(2026, 4, 10)


# ---------------------------------------------------------------------------
# Default entries
# ---------------------------------------------------------------------------

class TestBuildDefaultEntries:
    """Verify default entry construction."""

    def test_returns_four_entries(self) -> None:
        entries = build_default_entries()
        assert len(entries) == 4

    def test_covers_all_types(self) -> None:
        entries = build_default_entries()
        type_ids = {e.type_id for e in entries}
        assert type_ids == ALL_CHECKIN_TYPES

    def test_all_enabled_by_default(self) -> None:
        entries = build_default_entries()
        assert all(e.is_enabled for e in entries)

    def test_no_last_run_date(self) -> None:
        entries = build_default_entries()
        assert all(e.last_run_date is None for e in entries)


# ---------------------------------------------------------------------------
# Serialization round-trip
# ---------------------------------------------------------------------------

class TestSerialization:
    """Verify JSON serialization and deserialization."""

    def test_round_trip(self) -> None:
        entries = build_default_entries()
        raw = serialize_schedule(entries)
        restored = deserialize_schedule(raw)
        assert len(restored) == len(entries)
        for original, loaded in zip(entries, restored):
            assert original.type_id == loaded.type_id
            assert original.target_time == loaded.target_time

    def test_round_trip_with_last_run_date(self) -> None:
        entries = [mark_checkin_fired(build_default_entries()[0], date(2026, 4, 10))]
        raw = serialize_schedule(entries)
        restored = deserialize_schedule(raw)
        assert restored[0].last_run_date == date(2026, 4, 10)

    def test_deserialize_rejects_missing_key(self) -> None:
        with pytest.raises(ValueError, match="checkins"):
            deserialize_schedule('{"schedules": []}')

    def test_deserialize_rejects_non_dict(self) -> None:
        with pytest.raises(ValueError, match="checkins"):
            deserialize_schedule('[1, 2, 3]')


# ---------------------------------------------------------------------------
# Pure helper tests
# ---------------------------------------------------------------------------

class TestPureHelpers:
    """Verify immutable update functions."""

    def test_mark_checkin_fired_sets_date(self) -> None:
        entry = build_default_entries()[0]
        fired = mark_checkin_fired(entry, date(2026, 4, 10))
        assert fired.last_run_date == date(2026, 4, 10)
        assert entry.last_run_date is None

    def test_update_entry_time(self) -> None:
        entry = build_default_entries()[0]
        updated = update_entry_time(entry, time(7, 30))
        assert updated.target_time == time(7, 30)
        assert entry.target_time == time(8, 0)

    def test_update_entry_enabled(self) -> None:
        entry = build_default_entries()[0]
        disabled = update_entry_enabled(entry, False)
        assert not disabled.is_enabled
        assert entry.is_enabled


# ---------------------------------------------------------------------------
# Due-check logic
# ---------------------------------------------------------------------------

def _make_entry(
    type_id: str,
    target_time: time,
    staleness_minutes: int,
    is_enabled: bool,
    last_run_date: date | None,
) -> CheckInEntry:
    return CheckInEntry(
        type_id=type_id,  # type: ignore[arg-type]
        display_name="Test",
        target_time=target_time,
        staleness_minutes=staleness_minutes,
        is_enabled=is_enabled,
        last_run_date=last_run_date,
    )


class TestIsCheckinDue:
    """Verify single-entry due-check logic."""

    def test_due_at_target_time(self) -> None:
        entry = _make_entry("morning_plan", time(9, 0), 120, True, None)
        assert is_checkin_due(entry, date(2026, 4, 10), time(9, 0))

    def test_due_shortly_after_target(self) -> None:
        entry = _make_entry("morning_plan", time(9, 0), 120, True, None)
        assert is_checkin_due(entry, date(2026, 4, 10), time(9, 30))

    def test_not_due_before_target(self) -> None:
        entry = _make_entry("morning_plan", time(9, 0), 120, True, None)
        assert not is_checkin_due(entry, date(2026, 4, 10), time(8, 59))

    def test_not_due_when_disabled(self) -> None:
        entry = _make_entry("morning_plan", time(9, 0), 120, False, None)
        assert not is_checkin_due(entry, date(2026, 4, 10), time(9, 30))

    def test_not_due_when_already_fired_today(self) -> None:
        entry = _make_entry("morning_plan", time(9, 0), 120, True, date(2026, 4, 10))
        assert not is_checkin_due(entry, date(2026, 4, 10), time(9, 30))

    def test_due_when_fired_yesterday(self) -> None:
        entry = _make_entry("morning_plan", time(9, 0), 120, True, date(2026, 4, 9))
        assert is_checkin_due(entry, date(2026, 4, 10), time(9, 30))

    def test_not_due_when_stale(self) -> None:
        entry = _make_entry("morning_plan", time(9, 0), 120, True, None)
        assert not is_checkin_due(entry, date(2026, 4, 10), time(11, 1))

    def test_due_at_staleness_boundary(self) -> None:
        entry = _make_entry("morning_plan", time(9, 0), 120, True, None)
        assert is_checkin_due(entry, date(2026, 4, 10), time(11, 0))

    def test_not_due_one_minute_past_staleness(self) -> None:
        entry = _make_entry("morning_plan", time(9, 0), 60, True, None)
        assert not is_checkin_due(entry, date(2026, 4, 10), time(10, 1))

    def test_evening_due_at_target(self) -> None:
        entry = _make_entry("evening_review", time(20, 0), 120, True, None)
        assert is_checkin_due(entry, date(2026, 4, 10), time(20, 0))


class TestGetDueCheckins:
    """Verify multi-entry due-check filtering."""

    def test_returns_multiple_due(self) -> None:
        entries = [
            _make_entry("morning_motivation", time(8, 0), 120, True, None),
            _make_entry("morning_plan", time(9, 0), 120, True, None),
        ]
        due = get_due_checkins(entries, date(2026, 4, 10), time(9, 30))
        assert len(due) == 2

    def test_filters_already_fired(self) -> None:
        entries = [
            _make_entry("morning_motivation", time(8, 0), 120, True, date(2026, 4, 10)),
            _make_entry("morning_plan", time(9, 0), 120, True, None),
        ]
        due = get_due_checkins(entries, date(2026, 4, 10), time(9, 30))
        assert len(due) == 1
        assert due[0].type_id == "morning_plan"

    def test_returns_empty_when_none_due(self) -> None:
        entries = [
            _make_entry("morning_motivation", time(8, 0), 120, True, date(2026, 4, 10)),
            _make_entry("morning_plan", time(9, 0), 120, True, date(2026, 4, 10)),
        ]
        due = get_due_checkins(entries, date(2026, 4, 10), time(9, 30))
        assert due == []

    def test_only_non_stale_due_on_late_evening(self) -> None:
        entries = build_default_entries()
        due = get_due_checkins(entries, date(2026, 4, 10), time(21, 0))
        assert len(due) == 1
        assert due[0].type_id == "evening_review"

    def test_filters_disabled(self) -> None:
        entries = [
            _make_entry("morning_motivation", time(8, 0), 120, True, None),
            _make_entry("morning_plan", time(9, 0), 120, False, None),
        ]
        due = get_due_checkins(entries, date(2026, 4, 10), time(9, 30))
        assert len(due) == 1
        assert due[0].type_id == "morning_motivation"
