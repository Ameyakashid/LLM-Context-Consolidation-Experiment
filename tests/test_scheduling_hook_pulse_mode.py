"""Pulse-mode branch tests for ``SchedulingHook`` (Task 17 sub-03).

When ``pulse_mode=True`` and a ``PendingCheckinQueue`` is supplied, the
hook delegates firing to the Pulse dispatcher and only drains pre-formatted
prompt blocks.  These tests verify the drain path in isolation: the hook
must not touch ``schedule_store.get_due`` or ``record_fired``, it must not
evaluate cognitive state, and it must inject at most one pending block per
heartbeat tick.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import date, time
from pathlib import Path

from checkin_schedule import CheckInScheduleStore
from memory_store import MemoryEntryStore
from pulse_checkin_dispatcher import PendingCheckin, PendingCheckinQueue
from scheduling_hook import SchedulingHook
from task_store import TaskStore

SYSTEM_PROMPT = "# Soul\n\nYou are an assistant."


@dataclass
class MockHookContext:
    messages: list[dict[str, str]] = field(default_factory=list)


def _run(coro: object) -> object:
    return asyncio.run(coro)


def _make_hook(
    tmp_path: Path,
    pending_queue: PendingCheckinQueue | None,
    pulse_mode: bool,
    is_scheduled: bool = True,
    current_time: time = time(8, 15),
) -> SchedulingHook:
    schedule_store = CheckInScheduleStore(tmp_path / "schedule.json")
    task_store = TaskStore(tmp_path / "tasks.json")
    memory_store = MemoryEntryStore(tmp_path / "memories.json")
    return SchedulingHook(
        schedule_store=schedule_store,
        task_store=task_store,
        memory_store=memory_store,
        is_scheduled_session=lambda: is_scheduled,
        get_cognitive_state=lambda: "baseline",
        get_current_date=lambda: date(2026, 4, 10),
        get_current_time=lambda: current_time,
        pulse_mode=pulse_mode,
        pending_queue=pending_queue,
    )


def _pending(fire_date: date = date(2026, 4, 10)) -> PendingCheckin:
    return PendingCheckin(
        checkin_type="morning_motivation",
        fire_date=fire_date,
        prompt_block="## Active Check-In: Morning Motivation\n\nInject me.",
    )


class TestPulseModeDrain:

    def test_injects_single_pending_block(self, tmp_path: Path) -> None:
        queue = PendingCheckinQueue()
        queue.push(_pending())
        hook = _make_hook(tmp_path, queue, pulse_mode=True)
        ctx = MockHookContext(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": "heartbeat"},
            ]
        )

        _run(hook.before_iteration(ctx))

        assert "Active Check-In: Morning Motivation" in ctx.messages[0]["content"]
        assert len(queue) == 0

    def test_empty_queue_leaves_prompt_unchanged(
        self, tmp_path: Path,
    ) -> None:
        queue = PendingCheckinQueue()
        hook = _make_hook(tmp_path, queue, pulse_mode=True)
        ctx = MockHookContext(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": "heartbeat"},
            ]
        )

        _run(hook.before_iteration(ctx))

        assert ctx.messages[0]["content"] == SYSTEM_PROMPT

    def test_drains_only_one_per_tick(self, tmp_path: Path) -> None:
        queue = PendingCheckinQueue()
        queue.push(PendingCheckin(
            checkin_type="morning_motivation",
            fire_date=date(2026, 4, 10),
            prompt_block="BLOCK_ONE",
        ))
        queue.push(PendingCheckin(
            checkin_type="morning_plan",
            fire_date=date(2026, 4, 10),
            prompt_block="BLOCK_TWO",
        ))
        hook = _make_hook(tmp_path, queue, pulse_mode=True)
        ctx = MockHookContext(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": "heartbeat"},
            ]
        )

        _run(hook.before_iteration(ctx))

        content = ctx.messages[0]["content"]
        assert "BLOCK_ONE" in content
        assert "BLOCK_TWO" not in content
        assert len(queue) == 1

    def test_ignores_legacy_due_checkins(self, tmp_path: Path) -> None:
        # At 08:15 morning_motivation is legacy-due.  In pulse_mode the
        # hook must NOT call get_due / record_fired — only drain the
        # queue.  Empty queue + legacy-eligible clock = unchanged prompt.
        queue = PendingCheckinQueue()
        hook = _make_hook(
            tmp_path, queue, pulse_mode=True, current_time=time(8, 15),
        )
        ctx = MockHookContext(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": "heartbeat"},
            ]
        )

        _run(hook.before_iteration(ctx))

        assert "Morning Motivation" not in ctx.messages[0]["content"]
        entry = hook._schedule_store.get_entry("morning_motivation")
        assert entry.last_run_date is None

    def test_skips_when_not_scheduled_session(self, tmp_path: Path) -> None:
        queue = PendingCheckinQueue()
        queue.push(_pending())
        hook = _make_hook(
            tmp_path, queue, pulse_mode=True, is_scheduled=False,
        )
        ctx = MockHookContext(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": "user turn"},
            ]
        )

        _run(hook.before_iteration(ctx))

        # Non-heartbeat sessions must not drain the queue.
        assert ctx.messages[0]["content"] == SYSTEM_PROMPT
        assert len(queue) == 1

    def test_pulse_mode_without_queue_no_crash(self, tmp_path: Path) -> None:
        hook = _make_hook(tmp_path, pending_queue=None, pulse_mode=True)
        ctx = MockHookContext(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": "heartbeat"},
            ]
        )

        _run(hook.before_iteration(ctx))

        assert ctx.messages[0]["content"] == SYSTEM_PROMPT

    def test_flag_off_falls_back_to_legacy(self, tmp_path: Path) -> None:
        # pulse_mode=False keeps the legacy branch active; with the default
        # schedule at 12:00 morning_motivation (08:00) is long past due and
        # still eligible to fire (last_run_date is None).
        hook = _make_hook(tmp_path, pending_queue=None, pulse_mode=False)
        ctx = MockHookContext(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": "heartbeat"},
            ]
        )

        _run(hook.before_iteration(ctx))

        assert "Active Check-In" in ctx.messages[0]["content"]
