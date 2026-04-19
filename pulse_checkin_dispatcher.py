"""Pulse-driven check-in dispatcher + pending queue + consumer coroutine.

Wires the Pulse engine (sub-01) into the legacy check-in injection path
through a Path-C design: the dispatcher consumes ``PulseEvent`` values,
translates each concern id to a ``CheckInType``, evaluates the action
against the current cognitive state, and either advances ``last_run``
(suppress) or enqueues a formatted prompt block onto a
``PendingCheckinQueue`` that ``SchedulingHook`` drains on the next
heartbeat tick (fire/modify).

Why Path C over ``agent.process_direct`` (Path A)
-------------------------------------------------
Path A spawns a new session-scoped turn at fire time; Path C preserves
the *exact* legacy turn shape (``messages[0]["content"]`` mutated inside
the live heartbeat iteration), so the 24-hour parity gate in AC#2 is
byte-identical — the LLM sees the same system block regardless of flag.
``agent.process_direct`` (Path A) also requires duplicating
``_pick_heartbeat_target`` out of ``gateway_runner`` and introduces a
new session key (``"pulse"``) that sub-04's Dream engine would then have
to consume separately.  Path B (``bus.publish_inbound``) was rejected in
the research report because nanobot's pending-queue semantics expect a
user/assistant message, not a system-prompt suffix.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Protocol, cast

from checkin_schedule import CheckInScheduleStore, CheckInType
from memory_store import MemoryEntryStore
from pulse_checkin_store import advance_last_run, concern_id_to_checkin_type
from pulse_schedule import PulseEvent
from schedule_engine import (
    ScheduleAction,
    assemble_checkin_context,
    evaluate_checkin,
)
from scheduling_hook import format_checkin_prompt
from state_detection import StateName
from task_store import TaskStore, TaskStoreProtocol

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PendingCheckin:
    """A fully-formatted check-in block awaiting hook drain."""

    checkin_type: CheckInType
    fire_date: date
    prompt_block: str


class PendingCheckinQueue:
    """FIFO of check-ins fired by Pulse but not yet injected by the hook.

    Dedup key is ``(checkin_type, fire_date)``: the Pulse engine can
    re-emit the same concern if the consumer crashes mid-dispatch and
    restart picks it up from ``claim_due_concerns`` before
    ``record_fired`` has committed.  Idempotency at the queue boundary
    removes that class of bug.
    """

    def __init__(self) -> None:
        self._pending: list[PendingCheckin] = []
        self._seen: set[tuple[str, date]] = set()

    def push(self, pending: PendingCheckin) -> bool:
        """Enqueue ``pending``.  Returns False if an equivalent key is seen."""
        key = (pending.checkin_type, pending.fire_date)
        if key in self._seen:
            return False
        self._seen.add(key)
        self._pending.append(pending)
        return True

    def drain_one(self) -> PendingCheckin | None:
        """Pop the head of the queue, or None if empty."""
        if not self._pending:
            return None
        return self._pending.pop(0)

    def __len__(self) -> int:
        return len(self._pending)


class PulseCheckinDispatcher:
    """Converts a ``PulseEvent`` into a queued injection or a suppress record.

    Design rules:
    * Unknown concern ids are logged and dropped (not a crash).
    * ``suppress`` always calls ``advance_last_run`` so the concern does
      not re-fire the same day (legacy-parity).
    * ``defer`` logs only — no queue push, no ``advance_last_run``.
    * ``fire``/``modify`` assemble context, format the prompt block,
      push onto the queue, and advance ``last_run``.
    """

    def __init__(
        self,
        schedule_store: CheckInScheduleStore,
        task_store: TaskStoreProtocol,
        memory_store: MemoryEntryStore,
        pending_queue: PendingCheckinQueue,
        get_cognitive_state: Callable[[], StateName],
        get_current_date: Callable[[], date],
    ) -> None:
        self._schedule_store = schedule_store
        self._task_store = task_store
        self._memory_store = memory_store
        self._pending_queue = pending_queue
        self._get_cognitive_state = get_cognitive_state
        self._get_current_date = get_current_date

    def dispatch(self, event: PulseEvent) -> None:
        checkin_type = concern_id_to_checkin_type(event.concern_id)
        if checkin_type is None:
            log.warning(
                "pulse.dispatch rejected unknown concern_id=%s",
                event.concern_id,
            )
            return

        state = self._get_cognitive_state()
        action = evaluate_checkin(checkin_type, state)
        today = self._get_current_date()
        log.info(
            "pulse.dispatch concern_id=%s action=%s state=%s",
            event.concern_id, action.action, state,
        )

        if action.action == "suppress":
            log.info(
                "pulse.suppress concern_id=%s reason=%s",
                event.concern_id, action.reason,
            )
            advance_last_run(self._schedule_store, checkin_type, today)
            return

        if action.action == "defer":
            return

        self._queue_fire_or_modify(checkin_type, action, today)

    def _queue_fire_or_modify(
        self,
        checkin_type: CheckInType,
        action: ScheduleAction,
        today: date,
    ) -> None:
        context = assemble_checkin_context(
            checkin_type,
            cast(TaskStore, self._task_store),
            self._memory_store,
            today,
        )
        prompt_block = format_checkin_prompt(checkin_type, action, context)
        self._pending_queue.push(PendingCheckin(
            checkin_type=checkin_type,
            fire_date=today,
            prompt_block=prompt_block,
        ))
        advance_last_run(self._schedule_store, checkin_type, today)


class _DispatcherProtocol(Protocol):
    """Structural protocol for test doubles."""

    def dispatch(self, event: PulseEvent) -> None: ...


async def consume_pulse_events(
    event_queue: asyncio.Queue[PulseEvent],
    dispatcher: _DispatcherProtocol,
    cancel: asyncio.Event,
) -> None:
    """Drain ``event_queue`` onto ``dispatcher`` until ``cancel`` fires.

    Per-event dispatch errors are caught and logged so one broken event
    cannot starve the rest of the loop.  The cancel race uses
    ``asyncio.wait(FIRST_COMPLETED)`` so shutdown latency is bounded by
    the caller's ``timeout`` on the surrounding ``asyncio.wait_for``.
    """
    log.info("pulse consumer started")
    try:
        while not cancel.is_set():
            get_task = asyncio.create_task(
                event_queue.get(), name="pulse-consumer-get",
            )
            cancel_task = asyncio.create_task(
                cancel.wait(), name="pulse-consumer-cancel",
            )
            done, pending = await asyncio.wait(
                {get_task, cancel_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            await _cancel_tasks(pending)
            if cancel_task in done:
                break
            event = get_task.result()
            try:
                dispatcher.dispatch(event)
            except Exception as exc:
                log.warning(
                    "pulse.dispatch failed for concern_id=%s: %s",
                    event.concern_id, exc,
                )
    finally:
        log.info("pulse consumer stopped")


async def _cancel_tasks(tasks: set[asyncio.Task[object]]) -> None:
    for task in tasks:
        task.cancel()
    for task in tasks:
        try:
            await task
        except asyncio.CancelledError:
            pass


__all__ = [
    "PendingCheckin",
    "PendingCheckinQueue",
    "PulseCheckinDispatcher",
    "consume_pulse_events",
]
