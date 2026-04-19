"""24-hour parity sweep: flag-ON vs flag-OFF must fire identical blocks.

Acceptance criterion #2 for Task 17 sub-03: for every heartbeat tick over
a 24-hour window, the set of ``(checkin_type, fire_date)`` pairs emitted
by the two paths must match, and each matched pair must produce a
**byte-identical prompt block** — Path C's whole reason for existing.

The simulation drives both paths off the same wall clock and the same
schedule/task/memory state; the only variable is the flag.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from checkin_schedule import CheckInScheduleStore
from memory_store import MemoryEntryStore
from pulse_checkin_dispatcher import (
    PendingCheckinQueue,
    PulseCheckinDispatcher,
)
from pulse_checkin_store import PulseCheckinStore
from pulse_schedule import PulseEvent
from scheduling_hook import SchedulingHook
from task_store import TaskStore

TICK_MINUTES = 30
DAY_TICKS = 24 * 60 // TICK_MINUTES  # 48


@dataclass
class Fire:
    checkin_type: str
    fire_date: date
    block: str


@dataclass
class MockCtx:
    messages: list[dict[str, str]] = field(default_factory=list)


def _run(coro: object) -> object:
    return asyncio.run(coro)  # type: ignore[arg-type]


def _tick_times(day: date) -> list[datetime]:
    base = datetime.combine(day, time(0, 0), tzinfo=timezone.utc)
    return [base + timedelta(minutes=TICK_MINUTES * i) for i in range(DAY_TICKS)]


def _make_legacy_hook(
    schedule_store: CheckInScheduleStore,
    task_store: TaskStore,
    memory_store: MemoryEntryStore,
    current_date: date,
    current_time: time,
) -> SchedulingHook:
    return SchedulingHook(
        schedule_store=schedule_store,
        task_store=task_store,
        memory_store=memory_store,
        is_scheduled_session=lambda: True,
        get_cognitive_state=lambda: "baseline",
        get_current_date=lambda: current_date,
        get_current_time=lambda: current_time,
    )


def _make_pulse_hook(
    schedule_store: CheckInScheduleStore,
    task_store: TaskStore,
    memory_store: MemoryEntryStore,
    queue: PendingCheckinQueue,
    current_date: date,
    current_time: time,
) -> SchedulingHook:
    return SchedulingHook(
        schedule_store=schedule_store,
        task_store=task_store,
        memory_store=memory_store,
        is_scheduled_session=lambda: True,
        get_cognitive_state=lambda: "baseline",
        get_current_date=lambda: current_date,
        get_current_time=lambda: current_time,
        pulse_mode=True,
        pending_queue=queue,
    )


def _simulate_legacy(tmp_path: Path, day: date) -> list[Fire]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    schedule_store = CheckInScheduleStore(tmp_path / "sched_legacy.json")
    task_store = TaskStore(tmp_path / "tasks_legacy.json")
    memory_store = MemoryEntryStore(tmp_path / "mem_legacy.json")
    fires: list[Fire] = []

    for tick in _tick_times(day):
        local = tick.astimezone(ZoneInfo("UTC"))
        hook = _make_legacy_hook(
            schedule_store, task_store, memory_store,
            current_date=local.date(),
            current_time=local.time().replace(tzinfo=None),
        )
        ctx = MockCtx(messages=[
            {"role": "system", "content": "PROMPT"},
            {"role": "user", "content": "heartbeat"},
        ])
        _run(hook.before_iteration(ctx))
        content = ctx.messages[0]["content"]
        if content == "PROMPT":
            continue
        fires.append(Fire(
            checkin_type=_extract_type(content),
            fire_date=local.date(),
            block=content.removeprefix("PROMPT\n\n"),
        ))
    return fires


def _simulate_pulse(tmp_path: Path, day: date) -> list[Fire]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    schedule_store = CheckInScheduleStore(tmp_path / "sched_pulse.json")
    task_store = TaskStore(tmp_path / "tasks_pulse.json")
    memory_store = MemoryEntryStore(tmp_path / "mem_pulse.json")
    tz = ZoneInfo("UTC")
    checkin_store = PulseCheckinStore(store=schedule_store, tz=tz)
    queue = PendingCheckinQueue()
    dispatcher = PulseCheckinDispatcher(
        schedule_store=schedule_store,
        task_store=task_store,
        memory_store=memory_store,
        pending_queue=queue,
        get_cognitive_state=lambda: "baseline",
        get_current_date=lambda: day,
    )
    fires: list[Fire] = []

    for tick in _tick_times(day):
        concerns = _run(checkin_store.claim_due_concerns(tick))
        for concern_id in concerns:  # type: ignore[union-attr]
            dispatcher.dispatch(PulseEvent(
                concern_id=concern_id, fired_at=tick,
            ))
        local = tick.astimezone(tz)
        hook = _make_pulse_hook(
            schedule_store, task_store, memory_store, queue,
            current_date=local.date(),
            current_time=local.time().replace(tzinfo=None),
        )
        ctx = MockCtx(messages=[
            {"role": "system", "content": "PROMPT"},
            {"role": "user", "content": "heartbeat"},
        ])
        _run(hook.before_iteration(ctx))
        content = ctx.messages[0]["content"]
        if content == "PROMPT":
            continue
        fires.append(Fire(
            checkin_type=_extract_type(content),
            fire_date=local.date(),
            block=content.removeprefix("PROMPT\n\n"),
        ))
    return fires


def _extract_type(content: str) -> str:
    for line in content.splitlines():
        if line.startswith("## Active Check-In:"):
            display = line.split(":", 1)[1].strip()
            return {
                "Morning Motivation": "morning_motivation",
                "Morning Plan": "morning_plan",
                "Afternoon Check": "afternoon_check",
                "Evening Review": "evening_review",
            }[display]
    raise AssertionError(f"no check-in header in content: {content[:80]}")


# ---------------------------------------------------------------------------
# Parity assertions
# ---------------------------------------------------------------------------

class TestPulseLegacyParity:

    def test_fires_same_checkin_pairs_across_24h(
        self, tmp_path: Path,
    ) -> None:
        day = date(2026, 4, 15)
        legacy = _simulate_legacy(tmp_path / "legacy", day)
        pulse = _simulate_pulse(tmp_path / "pulse", day)

        legacy_pairs = {(f.checkin_type, f.fire_date) for f in legacy}
        pulse_pairs = {(f.checkin_type, f.fire_date) for f in pulse}

        assert legacy_pairs == pulse_pairs
        # All 4 defaults fire in a 24h baseline window.
        assert legacy_pairs == {
            ("morning_motivation", day),
            ("morning_plan", day),
            ("afternoon_check", day),
            ("evening_review", day),
        }

    def test_prompt_blocks_byte_identical_per_type(
        self, tmp_path: Path,
    ) -> None:
        day = date(2026, 4, 15)
        legacy = _simulate_legacy(tmp_path / "legacy", day)
        pulse = _simulate_pulse(tmp_path / "pulse", day)

        legacy_by_type = {f.checkin_type: f.block for f in legacy}
        pulse_by_type = {f.checkin_type: f.block for f in pulse}

        assert legacy_by_type.keys() == pulse_by_type.keys()
        for checkin_type, block in legacy_by_type.items():
            assert pulse_by_type[checkin_type] == block, (
                f"prompt block diverged for {checkin_type}:\n"
                f"--- legacy ---\n{block}\n--- pulse ---\n"
                f"{pulse_by_type[checkin_type]}"
            )

    def test_each_checkin_fires_exactly_once_per_day(
        self, tmp_path: Path,
    ) -> None:
        day = date(2026, 4, 15)
        pulse = _simulate_pulse(tmp_path, day)
        counts: dict[str, int] = {}
        for f in pulse:
            counts[f.checkin_type] = counts.get(f.checkin_type, 0) + 1
        assert all(n == 1 for n in counts.values()), counts
