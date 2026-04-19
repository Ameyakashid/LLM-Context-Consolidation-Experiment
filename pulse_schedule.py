"""Pulse schedule data model and next-fire computation.

Ported from `references/temm1e/crates/temm1e-perpetuum/src/types.rs` lines 47-77
(Schedule enum + duration_secs serde) and `pulse.rs` lines 126-175
(next_fire_time, next_fire_after).

JSON tagging: internally-tagged with a `kind` discriminator
(e.g. `{"kind": "at", "at_utc": "..."}`). Rust serde's default is externally-
tagged (`{"At": "..."}`); this port deliberately diverges because the schedules
are persisted only by Python code and the Pydantic-native discriminator is the
cleaner idiom.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal, Union
from zoneinfo import ZoneInfo

from croniter import CroniterBadCronError, croniter  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

ConcernId = str


class PulseEvent(BaseModel):
    """Event emitted by Pulse when a concern comes due.

    Mirrors Rust `pub enum PulseEvent { ConcernDue(ConcernId) }` (pulse.rs:14).
    Only one variant exists; future variants add sibling classes with distinct
    `kind` literals.
    """

    model_config = ConfigDict(frozen=True)

    kind: Literal["concern_due"] = "concern_due"
    concern_id: ConcernId


class ScheduleAt(BaseModel):
    """One-shot fire at an absolute UTC time (Rust `Schedule::At`)."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["at"] = "at"
    at_utc: datetime


class ScheduleEvery(BaseModel):
    """Fire every N seconds (Rust `Schedule::Every`)."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["every"] = "every"
    every_seconds: int = Field(gt=0)


class ScheduleCron(BaseModel):
    """5-field cron expression, evaluated in the target timezone.

    Rust `Schedule::Cron(String)`. Rust internally prepends the seconds column
    and appends the year column to feed the `cron` crate (see
    `pulse.rs::cron5_to_cron7` at line 130); this port skips that helper
    because `croniter` accepts 5-field expressions natively.
    """

    model_config = ConfigDict(frozen=True)

    kind: Literal["cron"] = "cron"
    cron_expr: str


Schedule = Annotated[
    Union[ScheduleAt, ScheduleEvery, ScheduleCron],
    Field(discriminator="kind"),
]

SCHEDULE_ADAPTER: TypeAdapter[Schedule] = TypeAdapter(Schedule)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _cron_next_strictly_after(
    expr: str, base: datetime, tz: ZoneInfo
) -> datetime | None:
    base_in_tz = base.astimezone(tz)
    try:
        iterator = croniter(expr, start_time=base_in_tz)
        next_local = iterator.get_next(datetime)
    except (CroniterBadCronError, ValueError):
        return None
    if not isinstance(next_local, datetime):
        raise TypeError(
            f"croniter.get_next(datetime) returned non-datetime {type(next_local).__name__}"
        )
    return next_local.astimezone(timezone.utc)


def next_fire_time(
    schedule: ScheduleAt | ScheduleEvery | ScheduleCron, tz: ZoneInfo
) -> datetime | None:
    """Next UTC fire time for `schedule` (Rust `next_fire_time`, pulse.rs:135).

    `At`: returns the stored time if still in the future, else `None`.
    `Every`: returns now + interval.
    `Cron`: first upcoming wall-clock slot in `tz`, converted to UTC.
    Invalid cron expressions return `None` (mirrors Rust swallowing the
    `from_str` error via `.ok()?`).
    """
    now = _now_utc()
    if isinstance(schedule, ScheduleAt):
        return schedule.at_utc if schedule.at_utc > now else None
    if isinstance(schedule, ScheduleEvery):
        return now + timedelta(seconds=schedule.every_seconds)
    if isinstance(schedule, ScheduleCron):
        return _cron_next_strictly_after(schedule.cron_expr, now, tz)
    raise TypeError(f"unknown Schedule variant: {type(schedule).__name__}")


def next_fire_after(
    schedule: ScheduleAt | ScheduleEvery | ScheduleCron,
    after: datetime,
    tz: ZoneInfo,
) -> datetime | None:
    """Next fire strictly after `after` (Rust `next_fire_after`, pulse.rs:157).

    `At`: always `None` (one-shot has no next).
    `Every`: returns `after + interval`.
    `Cron`: first slot strictly after `after` in `tz`, converted to UTC.
    `after` must be tz-aware — a naive datetime is a programmer error at this
    boundary.
    """
    if after.tzinfo is None:
        raise ValueError(
            "next_fire_after requires a tz-aware datetime for `after`; "
            f"got naive {after!r}. Pass a datetime with an explicit tzinfo."
        )
    if isinstance(schedule, ScheduleAt):
        return None
    if isinstance(schedule, ScheduleEvery):
        return after + timedelta(seconds=schedule.every_seconds)
    if isinstance(schedule, ScheduleCron):
        return _cron_next_strictly_after(schedule.cron_expr, after, tz)
    raise TypeError(f"unknown Schedule variant: {type(schedule).__name__}")


__all__ = [
    "ConcernId",
    "PulseEvent",
    "Schedule",
    "ScheduleAt",
    "ScheduleCron",
    "ScheduleEvery",
    "SCHEDULE_ADAPTER",
    "next_fire_after",
    "next_fire_time",
]
