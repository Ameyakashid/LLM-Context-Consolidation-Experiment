"""Tests for magicmirror_hook pure helpers.

Covers the six pure predicates/formatters: build_webhook_base_url,
is_checkin_missed, format_state_change_message,
format_buffer_alert_message, format_missed_checkin_message,
should_log_error, collect_alertable_buffers.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from buffer_store import Buffer
from checkin_schedule import CheckInEntry
from magicmirror_hook import (
    ERROR_LOG_INTERVAL,
    build_webhook_base_url,
    collect_alertable_buffers,
    format_buffer_alert_message,
    format_missed_checkin_message,
    format_state_change_message,
    is_checkin_missed,
    should_log_error,
)


def _buffer(
    name: str = "rent",
    level: int = 2,
    capacity: int = 4,
    threshold: int = 2,
) -> Buffer:
    now = datetime(2026, 4, 19, 10, 0)
    return Buffer(
        id=f"b-{name}",
        name=name,
        buffer_level=level,
        buffer_capacity=capacity,
        recurrence_interval_days=30,
        next_due_date=date(2026, 5, 1),
        alert_threshold=threshold,
        status="active",
        created_at=now,
        updated_at=now,
    )


def _entry(
    hour: int = 8,
    minute: int = 0,
    staleness: int = 120,
    enabled: bool = True,
    last_run: date | None = None,
) -> CheckInEntry:
    return CheckInEntry(
        type_id="morning_motivation",
        display_name="Morning Motivation",
        target_time=time(hour, minute),
        staleness_minutes=staleness,
        is_enabled=enabled,
        last_run_date=last_run,
    )


class TestBuildWebhookBaseUrl:

    def test_assembles_http_scheme(self) -> None:
        assert build_webhook_base_url("127.0.0.1", "8080") == (
            "http://127.0.0.1:8080"
        )

    def test_accepts_localhost(self) -> None:
        assert build_webhook_base_url("localhost", "9090") == (
            "http://localhost:9090"
        )


class TestIsCheckinMissed:

    def test_disabled_entry_never_missed(self) -> None:
        entry = _entry(enabled=False)
        today = date(2026, 4, 19)
        now = datetime(2026, 4, 19, 14, 0)
        assert not is_checkin_missed(entry, today, now)

    def test_already_ran_today_is_not_missed(self) -> None:
        today = date(2026, 4, 19)
        entry = _entry(last_run=today)
        now = datetime(2026, 4, 19, 14, 0)
        assert not is_checkin_missed(entry, today, now)

    def test_within_staleness_window_is_not_missed(self) -> None:
        entry = _entry(hour=8, staleness=120)
        today = date(2026, 4, 19)
        now = datetime(2026, 4, 19, 9, 30)
        assert not is_checkin_missed(entry, today, now)

    def test_past_staleness_window_is_missed(self) -> None:
        entry = _entry(hour=8, staleness=120)
        today = date(2026, 4, 19)
        now = datetime(2026, 4, 19, 10, 1)
        assert is_checkin_missed(entry, today, now)

    def test_tz_aware_now_is_stripped_before_compare(self) -> None:
        entry = _entry(hour=8, staleness=120)
        today = date(2026, 4, 19)
        tz = ZoneInfo("America/New_York")
        now = datetime(2026, 4, 19, 10, 1, tzinfo=tz)
        assert is_checkin_missed(entry, today, now)


class TestFormatMessages:

    def test_state_change_message(self) -> None:
        assert format_state_change_message("flow", "crashed") == (
            "Cognitive state: flow → crashed."
        )

    def test_buffer_alert_message(self) -> None:
        assert format_buffer_alert_message(_buffer("rent", 1, 4)) == (
            "rent is at 1 of 4. Refill soon."
        )

    def test_missed_checkin_message(self) -> None:
        entry = _entry(hour=8, minute=30)
        assert format_missed_checkin_message(entry) == (
            "Morning Motivation was due at 08:30 and did not fire."
        )


class TestShouldLogError:

    def test_first_call_is_allowed(self) -> None:
        assert should_log_error(None, datetime(2026, 4, 19, 10, 0))

    def test_within_interval_is_rate_limited(self) -> None:
        last = datetime(2026, 4, 19, 10, 0)
        now = last + ERROR_LOG_INTERVAL - timedelta(seconds=1)
        assert not should_log_error(last, now)

    def test_after_interval_is_allowed(self) -> None:
        last = datetime(2026, 4, 19, 10, 0)
        now = last + ERROR_LOG_INTERVAL + timedelta(seconds=1)
        assert should_log_error(last, now)


class TestCollectAlertableBuffers:

    def test_filters_below_threshold(self) -> None:
        low = _buffer("a", level=1, threshold=2)
        high = _buffer("b", level=3, threshold=2)
        equal = _buffer("c", level=2, threshold=2)
        result = collect_alertable_buffers([high, low, equal])
        assert [b.name for b in result] == ["a", "c"]

    def test_empty_input_returns_empty(self) -> None:
        assert collect_alertable_buffers([]) == []
