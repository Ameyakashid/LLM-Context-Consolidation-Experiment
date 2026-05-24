"""Tests for scheduling hook — hook lifecycle tests."""

import asyncio
from dataclasses import dataclass, field
from datetime import date, time
from pathlib import Path

import pytest

from checkin_schedule import CheckInScheduleStore
from memory_store import MemoryEntryStore
from scheduling_hook import SchedulingHook
from task_store import TaskStore

SYSTEM_PROMPT = "# Soul\n\nYou are an assistant.\n\n## Scheduled Check-Ins\n\nGuidance here."


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@dataclass
class MockHookContext:
    messages: list[dict[str, str]] = field(default_factory=list)


def _run(coro: object) -> object:
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# SchedulingHook
# ---------------------------------------------------------------------------

class TestSchedulingHook:

    def _make_hook(
        self,
        tmp_path: Path,
        is_scheduled: bool,
        cognitive_state: str,
        current_date: date,
        current_time: time,
    ) -> SchedulingHook:
        schedule_store = CheckInScheduleStore(
            tmp_path / "schedule.json"
        )
        task_store = TaskStore(tmp_path / "tasks.json")
        memory_store = MemoryEntryStore(tmp_path / "memories.json")
        return SchedulingHook(
            schedule_store=schedule_store,
            task_store=task_store,
            memory_store=memory_store,
            is_scheduled_session=lambda: is_scheduled,
            get_cognitive_state=lambda: cognitive_state,
            get_current_date=lambda: current_date,
            get_current_time=lambda: current_time,
        )

    def test_fires_due_checkin(self, tmp_path: Path) -> None:
        hook = self._make_hook(
            tmp_path,
            is_scheduled=True,
            cognitive_state="baseline",
            current_date=date(2026, 4, 10),
            current_time=time(8, 15),
        )
        ctx = MockHookContext(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": "heartbeat task"},
            ]
        )
        _run(hook.before_iteration(ctx))
        assert "Morning Motivation" in ctx.messages[0]["content"]

    def test_skips_non_scheduled_session(self, tmp_path: Path) -> None:
        hook = self._make_hook(
            tmp_path,
            is_scheduled=False,
            cognitive_state="baseline",
            current_date=date(2026, 4, 10),
            current_time=time(8, 15),
        )
        ctx = MockHookContext(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": "user message"},
            ]
        )
        _run(hook.before_iteration(ctx))
        assert ctx.messages[0]["content"] == SYSTEM_PROMPT

    def test_skips_when_nothing_due(self, tmp_path: Path) -> None:
        hook = self._make_hook(
            tmp_path,
            is_scheduled=True,
            cognitive_state="baseline",
            current_date=date(2026, 4, 10),
            current_time=time(6, 0),
        )
        ctx = MockHookContext(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": "heartbeat task"},
            ]
        )
        _run(hook.before_iteration(ctx))
        assert ctx.messages[0]["content"] == SYSTEM_PROMPT

    def test_suppresses_during_hyperfocus(self, tmp_path: Path) -> None:
        hook = self._make_hook(
            tmp_path,
            is_scheduled=True,
            cognitive_state="hyperfocus",
            current_date=date(2026, 4, 10),
            current_time=time(9, 30),
        )
        ctx = MockHookContext(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": "heartbeat task"},
            ]
        )
        _run(hook.before_iteration(ctx))
        # morning_plan at 09:30 should be suppressed during hyperfocus
        assert "Morning Plan" not in ctx.messages[0]["content"]

    def test_suppress_records_fired(self, tmp_path: Path) -> None:
        hook = self._make_hook(
            tmp_path,
            is_scheduled=True,
            cognitive_state="hyperfocus",
            current_date=date(2026, 4, 10),
            current_time=time(8, 15),
        )
        ctx = MockHookContext(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": "heartbeat"},
            ]
        )
        _run(hook.before_iteration(ctx))
        # morning_motivation at 08:15 during hyperfocus → suppress + record
        entry = hook._schedule_store.get_entry("morning_motivation")
        assert entry.last_run_date == date(2026, 4, 10)

    def test_modify_includes_scope(self, tmp_path: Path) -> None:
        hook = self._make_hook(
            tmp_path,
            is_scheduled=True,
            cognitive_state="avoidance",
            current_date=date(2026, 4, 10),
            current_time=time(9, 30),
        )
        # Pre-fire morning_motivation so morning_plan is the first due
        hook._schedule_store.record_fired(
            "morning_motivation", date(2026, 4, 10)
        )
        ctx = MockHookContext(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": "heartbeat"},
            ]
        )
        _run(hook.before_iteration(ctx))
        # morning_plan + avoidance = modify with reduced scope
        assert "Modified scope: reduced" in ctx.messages[0]["content"]

    def test_records_fired_after_fire(self, tmp_path: Path) -> None:
        hook = self._make_hook(
            tmp_path,
            is_scheduled=True,
            cognitive_state="baseline",
            current_date=date(2026, 4, 10),
            current_time=time(8, 15),
        )
        ctx = MockHookContext(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": "heartbeat"},
            ]
        )
        _run(hook.before_iteration(ctx))
        entry = hook._schedule_store.get_entry("morning_motivation")
        assert entry.last_run_date == date(2026, 4, 10)

    def test_does_not_fire_same_checkin_twice(self, tmp_path: Path) -> None:
        hook = self._make_hook(
            tmp_path,
            is_scheduled=True,
            cognitive_state="baseline",
            current_date=date(2026, 4, 10),
            current_time=time(8, 15),
        )
        ctx1 = MockHookContext(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": "heartbeat"},
            ]
        )
        _run(hook.before_iteration(ctx1))
        assert "Morning Motivation" in ctx1.messages[0]["content"]

        # Second tick at same time — morning_motivation already fired
        ctx2 = MockHookContext(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": "heartbeat"},
            ]
        )
        _run(hook.before_iteration(ctx2))
        assert "Morning Motivation" not in ctx2.messages[0]["content"]

    def test_empty_messages_no_crash(self, tmp_path: Path) -> None:
        hook = self._make_hook(
            tmp_path,
            is_scheduled=True,
            cognitive_state="baseline",
            current_date=date(2026, 4, 10),
            current_time=time(8, 15),
        )
        ctx = MockHookContext(messages=[])
        _run(hook.before_iteration(ctx))

    def test_no_system_message_no_crash(self, tmp_path: Path) -> None:
        hook = self._make_hook(
            tmp_path,
            is_scheduled=True,
            cognitive_state="baseline",
            current_date=date(2026, 4, 10),
            current_time=time(8, 15),
        )
        ctx = MockHookContext(
            messages=[{"role": "user", "content": "heartbeat"}]
        )
        _run(hook.before_iteration(ctx))

    def test_processes_only_first_due_checkin(self, tmp_path: Path) -> None:
        hook = self._make_hook(
            tmp_path,
            is_scheduled=True,
            cognitive_state="baseline",
            current_date=date(2026, 4, 10),
            current_time=time(9, 30),
        )
        ctx = MockHookContext(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": "heartbeat"},
            ]
        )
        _run(hook.before_iteration(ctx))
        content = ctx.messages[0]["content"]
        # At 09:30 both morning_motivation (08:00) and morning_plan (09:00) are due
        # Only one should be injected
        active_count = content.count("## Active Check-In:")
        assert active_count == 1
