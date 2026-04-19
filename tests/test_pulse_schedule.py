"""Tests for pulse_schedule — port of pulse.rs's `mod tests` plus extensions.

Covers: the three Rust-source tests (at, every, cron, after_recurring), JSON
round-trips for each variant, DST correctness across a known spring-forward
boundary, and invalid cron handling.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from pulse_schedule import (
    SCHEDULE_ADAPTER,
    PulseEvent,
    ScheduleAt,
    ScheduleCron,
    ScheduleEvery,
    next_fire_after,
    next_fire_time,
)

LA = ZoneInfo("America/Los_Angeles")
UTC = timezone.utc


def test_cron_expression_parses_via_croniter() -> None:
    """Replaces Rust `cron5_to_cron7_conversion` test. The helper is omitted
    (croniter accepts 5-field input); verify the 5-field form is accepted end
    to end through next_fire_time."""
    result = next_fire_time(ScheduleCron(cron_expr="*/5 * * * *"), LA)
    assert result is not None
    assert result.tzinfo is UTC


def test_next_fire_time_at_future_returns_datetime() -> None:
    future = datetime.now(UTC) + timedelta(hours=1)
    assert next_fire_time(ScheduleAt(at_utc=future), LA) == future


def test_next_fire_time_at_past_returns_none() -> None:
    past = datetime.now(UTC) - timedelta(hours=1)
    assert next_fire_time(ScheduleAt(at_utc=past), LA) is None


def test_next_fire_time_every_returns_now_plus_interval() -> None:
    before = datetime.now(UTC)
    result = next_fire_time(ScheduleEvery(every_seconds=300), LA)
    after = datetime.now(UTC)
    assert result is not None
    assert before + timedelta(seconds=300) <= result <= after + timedelta(seconds=300)


def test_next_fire_time_cron_valid_returns_future() -> None:
    before = datetime.now(UTC)
    result = next_fire_time(ScheduleCron(cron_expr="*/5 * * * *"), LA)
    assert result is not None
    assert result > before


def test_next_fire_time_cron_invalid_returns_none() -> None:
    assert next_fire_time(ScheduleCron(cron_expr="not a cron"), LA) is None


def test_next_fire_after_every_advances_from_base() -> None:
    base = datetime(2026, 4, 19, 12, 0, tzinfo=UTC)
    assert next_fire_after(ScheduleEvery(every_seconds=60), base, ZoneInfo("UTC")) == (
        base + timedelta(seconds=60)
    )


def test_next_fire_after_at_returns_none() -> None:
    base = datetime(2026, 4, 19, 12, 0, tzinfo=UTC)
    assert next_fire_after(ScheduleAt(at_utc=base), base, ZoneInfo("UTC")) is None


def test_next_fire_after_cron_returns_strictly_after_base() -> None:
    base = datetime(2026, 4, 19, 0, 0, tzinfo=UTC)
    result = next_fire_after(ScheduleCron(cron_expr="0 0 * * *"), base, ZoneInfo("UTC"))
    assert result == datetime(2026, 4, 20, 0, 0, tzinfo=UTC)


def test_next_fire_after_cron_invalid_returns_none() -> None:
    base = datetime(2026, 4, 19, 12, 0, tzinfo=UTC)
    assert next_fire_after(ScheduleCron(cron_expr="garbage"), base, LA) is None


def test_next_fire_after_naive_datetime_raises() -> None:
    naive = datetime(2026, 4, 19, 12, 0)
    with pytest.raises(ValueError, match="tz-aware"):
        next_fire_after(ScheduleEvery(every_seconds=60), naive, ZoneInfo("UTC"))


def test_cron_dst_spring_forward_skips_invalid_wall_clock() -> None:
    """2026-03-08 02:00 America/Los_Angeles does not exist (clocks jump to
    03:00 PDT). Cron `0 2 * * *` must advance to 03:00 PDT that day = 10:00
    UTC. Matches Rust `chrono_tz` behaviour."""
    base = datetime(2026, 3, 8, 1, 30, tzinfo=LA)
    result = next_fire_after(ScheduleCron(cron_expr="0 2 * * *"), base, LA)
    assert result == datetime(2026, 3, 8, 10, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    "schedule",
    [
        ScheduleAt(at_utc=datetime(2026, 5, 1, 12, 0, tzinfo=UTC)),
        ScheduleEvery(every_seconds=300),
        ScheduleCron(cron_expr="*/5 * * * *"),
    ],
)
def test_schedule_json_round_trip(
    schedule: ScheduleAt | ScheduleEvery | ScheduleCron,
) -> None:
    raw = SCHEDULE_ADAPTER.dump_python(schedule, mode="json")
    restored = SCHEDULE_ADAPTER.validate_python(raw)
    assert restored == schedule
    # JSON-string path too
    as_json = json.dumps(raw)
    assert SCHEDULE_ADAPTER.validate_json(as_json) == schedule


def test_schedule_discriminator_dispatches_by_kind() -> None:
    payload = {"kind": "every", "every_seconds": 120}
    restored = SCHEDULE_ADAPTER.validate_python(payload)
    assert isinstance(restored, ScheduleEvery)
    assert restored.every_seconds == 120


def test_pulse_event_concern_due_holds_id() -> None:
    event = PulseEvent(concern_id="concern-123")
    assert event.concern_id == "concern-123"
    assert event.kind == "concern_due"


def test_pulse_event_is_frozen() -> None:
    event = PulseEvent(concern_id="x")
    with pytest.raises(ValidationError):
        event.concern_id = "y"


def test_schedule_at_is_frozen() -> None:
    schedule = ScheduleAt(at_utc=datetime.now(UTC))
    with pytest.raises(ValidationError):
        schedule.at_utc = datetime.now(UTC)


def test_schedule_every_rejects_zero_seconds() -> None:
    with pytest.raises(ValidationError):
        ScheduleEvery(every_seconds=0)
