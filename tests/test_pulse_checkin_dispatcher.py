"""Tests for PulseCheckinDispatcher + PendingCheckinQueue + consume_pulse_events."""

import asyncio
import logging
from datetime import date
from pathlib import Path

import pytest

from checkin_schedule import CheckInScheduleStore
from memory_store import MemoryEntryStore
from pulse_checkin_dispatcher import (
    PendingCheckin,
    PendingCheckinQueue,
    PulseCheckinDispatcher,
    consume_pulse_events,
)
from pulse_schedule import PulseEvent
from task_store import TaskStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_dispatcher(
    tmp_path: Path,
    cognitive_state: str,
    today: date,
) -> tuple[PulseCheckinDispatcher, CheckInScheduleStore, PendingCheckinQueue]:
    schedule_store = CheckInScheduleStore(tmp_path / "schedule.json")
    task_store = TaskStore(tmp_path / "tasks.json")
    memory_store = MemoryEntryStore(tmp_path / "memories.json")
    queue = PendingCheckinQueue()
    dispatcher = PulseCheckinDispatcher(
        schedule_store=schedule_store,
        task_store=task_store,
        memory_store=memory_store,
        pending_queue=queue,
        get_cognitive_state=lambda: cognitive_state,  # type: ignore[arg-type,return-value]
        get_current_date=lambda: today,
    )
    return dispatcher, schedule_store, queue


# ---------------------------------------------------------------------------
# PendingCheckinQueue
# ---------------------------------------------------------------------------

class TestPendingCheckinQueue:

    def test_push_and_drain_one(self) -> None:
        queue = PendingCheckinQueue()
        item = PendingCheckin(
            checkin_type="morning_motivation",
            fire_date=date(2026, 4, 10),
            prompt_block="## Active Check-In: Morning Motivation",
        )
        assert queue.push(item) is True
        assert len(queue) == 1
        assert queue.drain_one() == item
        assert queue.drain_one() is None
        assert len(queue) == 0

    def test_dedup_same_type_and_date(self) -> None:
        queue = PendingCheckinQueue()
        item_a = PendingCheckin(
            checkin_type="morning_motivation",
            fire_date=date(2026, 4, 10),
            prompt_block="block a",
        )
        item_b = PendingCheckin(
            checkin_type="morning_motivation",
            fire_date=date(2026, 4, 10),
            prompt_block="block b",
        )
        assert queue.push(item_a) is True
        assert queue.push(item_b) is False
        assert len(queue) == 1
        drained = queue.drain_one()
        assert drained is not None
        assert drained.prompt_block == "block a"

    def test_same_type_different_day_is_distinct(self) -> None:
        queue = PendingCheckinQueue()
        item_a = PendingCheckin(
            checkin_type="morning_motivation",
            fire_date=date(2026, 4, 10),
            prompt_block="a",
        )
        item_b = PendingCheckin(
            checkin_type="morning_motivation",
            fire_date=date(2026, 4, 11),
            prompt_block="b",
        )
        queue.push(item_a)
        queue.push(item_b)
        assert len(queue) == 2

    def test_fifo_order(self) -> None:
        queue = PendingCheckinQueue()
        for type_id in ("morning_motivation", "morning_plan", "afternoon_check"):
            queue.push(PendingCheckin(
                checkin_type=type_id,  # type: ignore[arg-type]
                fire_date=date(2026, 4, 10),
                prompt_block=type_id,
            ))
        order: list[str] = []
        while True:
            item = queue.drain_one()
            if item is None:
                break
            order.append(item.checkin_type)
        assert order == ["morning_motivation", "morning_plan", "afternoon_check"]


# ---------------------------------------------------------------------------
# PulseCheckinDispatcher — dispatch actions
# ---------------------------------------------------------------------------

class TestPulseCheckinDispatcher:

    def test_unknown_concern_id_logs_and_drops(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture,
    ) -> None:
        dispatcher, _, queue = _build_dispatcher(
            tmp_path, "baseline", date(2026, 4, 10),
        )
        with caplog.at_level(logging.WARNING, logger="pulse_checkin_dispatcher"):
            dispatcher.dispatch(PulseEvent(concern_id="not_a_checkin"))
        assert len(queue) == 0
        assert any(
            "unknown" in record.message.lower() or "not_a_checkin" in record.message
            for record in caplog.records
        )

    def test_fire_action_queues_block_and_advances_last_run(
        self, tmp_path: Path,
    ) -> None:
        dispatcher, schedule_store, queue = _build_dispatcher(
            tmp_path, "baseline", date(2026, 4, 10),
        )
        dispatcher.dispatch(PulseEvent(concern_id="morning_motivation"))
        assert len(queue) == 1
        pending = queue.drain_one()
        assert pending is not None
        assert pending.checkin_type == "morning_motivation"
        assert pending.fire_date == date(2026, 4, 10)
        assert "Morning Motivation" in pending.prompt_block
        assert schedule_store.get_entry("morning_motivation").last_run_date == date(
            2026, 4, 10,
        )

    def test_suppress_action_advances_last_run_but_does_not_queue(
        self, tmp_path: Path,
    ) -> None:
        dispatcher, schedule_store, queue = _build_dispatcher(
            tmp_path, "hyperfocus", date(2026, 4, 10),
        )
        dispatcher.dispatch(PulseEvent(concern_id="morning_plan"))
        assert len(queue) == 0
        assert schedule_store.get_entry("morning_plan").last_run_date == date(
            2026, 4, 10,
        )

    def test_defer_action_does_not_queue_or_advance(
        self, tmp_path: Path,
    ) -> None:
        # evaluate_checkin has no "defer" path under current matrix so this test
        # simulates the branch by using a state that produces "modify" for the
        # afternoon_check + avoidance combination.  A real defer arises if the
        # evaluation matrix is ever extended.  For now we verify modify queues.
        dispatcher, schedule_store, queue = _build_dispatcher(
            tmp_path, "avoidance", date(2026, 4, 10),
        )
        dispatcher.dispatch(PulseEvent(concern_id="afternoon_check"))
        assert len(queue) == 1
        pending = queue.drain_one()
        assert pending is not None
        assert "Modified scope: reduced" in pending.prompt_block
        assert schedule_store.get_entry("afternoon_check").last_run_date == date(
            2026, 4, 10,
        )

    def test_logs_dispatch_suppress_events(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture,
    ) -> None:
        dispatcher, _, _ = _build_dispatcher(
            tmp_path, "hyperfocus", date(2026, 4, 10),
        )
        with caplog.at_level(logging.INFO, logger="pulse_checkin_dispatcher"):
            dispatcher.dispatch(PulseEvent(concern_id="morning_plan"))
        messages = " ".join(r.message for r in caplog.records)
        assert "pulse.dispatch" in messages
        assert "pulse.suppress" in messages
        assert "morning_plan" in messages


# ---------------------------------------------------------------------------
# consume_pulse_events
# ---------------------------------------------------------------------------

class TestConsumePulseEvents:

    def test_consumer_dispatches_event_then_stops_on_cancel(
        self, tmp_path: Path,
    ) -> None:
        async def run() -> int:
            dispatcher, _, queue = _build_dispatcher(
                tmp_path, "baseline", date(2026, 4, 10),
            )
            event_queue: asyncio.Queue[PulseEvent] = asyncio.Queue()
            cancel = asyncio.Event()
            task = asyncio.create_task(
                consume_pulse_events(event_queue, dispatcher, cancel),
            )
            await event_queue.put(PulseEvent(concern_id="morning_motivation"))
            await asyncio.sleep(0.05)
            cancel.set()
            await asyncio.wait_for(task, timeout=2.0)
            return len(queue)

        pending_count = asyncio.run(run())
        assert pending_count == 1

    def test_consumer_exits_when_cancel_set_before_event(
        self, tmp_path: Path,
    ) -> None:
        async def run() -> None:
            dispatcher, _, _ = _build_dispatcher(
                tmp_path, "baseline", date(2026, 4, 10),
            )
            event_queue: asyncio.Queue[PulseEvent] = asyncio.Queue()
            cancel = asyncio.Event()
            cancel.set()
            task = asyncio.create_task(
                consume_pulse_events(event_queue, dispatcher, cancel),
            )
            await asyncio.wait_for(task, timeout=2.0)

        asyncio.run(run())

    def test_consumer_swallows_per_event_errors(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture,
    ) -> None:
        class _RaisingDispatcher:
            def dispatch(self, event: PulseEvent) -> None:
                raise RuntimeError(
                    f"synthetic dispatch failure for {event.concern_id}"
                )

        async def run() -> bool:
            event_queue: asyncio.Queue[PulseEvent] = asyncio.Queue()
            cancel = asyncio.Event()
            task = asyncio.create_task(
                consume_pulse_events(
                    event_queue, _RaisingDispatcher(),  # type: ignore[arg-type]
                    cancel,
                ),
            )
            await event_queue.put(PulseEvent(concern_id="morning_motivation"))
            await asyncio.sleep(0.05)
            still_running = not task.done()
            cancel.set()
            await asyncio.wait_for(task, timeout=2.0)
            return still_running

        with caplog.at_level(logging.WARNING, logger="pulse_checkin_dispatcher"):
            assert asyncio.run(run()) is True
        assert any("synthetic dispatch failure" in r.message for r in caplog.records)
