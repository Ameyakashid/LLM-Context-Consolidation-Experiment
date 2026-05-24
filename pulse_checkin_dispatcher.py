"""Pulse-driven check-in dispatcher + pending queue + consumer coroutine.

Wires the Pulse engine (sub-01) into the legacy check-in injection path
through a Path-C design: the dispatcher consumes ``PulseEvent`` values,
translates each concern id to a ``CheckInType``, evaluates the action
against the current cognitive state, and either advances ``last_run``
(suppress) or enqueues a formatted prompt block onto a
``PendingCheckinQueue`` that ``SchedulingHook`` drains on the next
heartbeat tick (fire/modify).

Path C preserves the exact legacy turn shape (``messages[0]["content"]``
mutated inside the live heartbeat iteration), so the 24-hour parity
gate in AC#2 is byte-identical. Sub-05 additionally wires a Dream branch
that spawns ``DreamEngine.run()`` as a background task on the
``"dream_state"`` concern id, preserving the sync ``dispatch`` surface.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Protocol, cast

from checkin_schedule import CheckInScheduleStore, CheckInType
from dream_engine import DreamEngine
from dream_types import DreamState
from memory_store import MemoryEntryStore
from pulse_checkin_store import advance_last_run, concern_id_to_checkin_type
from pulse_schedule import PulseEvent
from pulse_system_concerns import DREAM_CONCERN_ID, write_last_run
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
        *,
        dream_engine: DreamEngine | None = None,
        dream_last_run_path: Path | None = None,
        now_utc_provider: Callable[[], datetime] | None = None,
    ) -> None:
        if dream_engine is not None and dream_last_run_path is None:
            raise ValueError(
                "PulseCheckinDispatcher requires dream_last_run_path when "
                "dream_engine is set so successful runs can be persisted."
            )
        self._schedule_store = schedule_store
        self._task_store = task_store
        self._memory_store = memory_store
        self._pending_queue = pending_queue
        self._get_cognitive_state = get_cognitive_state
        self._get_current_date = get_current_date
        self._dream_engine = dream_engine
        self._dream_last_run_path = dream_last_run_path
        self._now_utc = now_utc_provider or _default_now_utc
        self._active_dream_task: asyncio.Task[None] | None = None

    @property
    def active_dream_task(self) -> asyncio.Task[None] | None:
        return self._active_dream_task

    def dispatch(self, event: PulseEvent) -> None:
        if event.concern_id == DREAM_CONCERN_ID:
            self._dispatch_dream_concern(event)
            return
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

    def _dispatch_dream_concern(self, event: PulseEvent) -> None:
        if self._dream_engine is None or self._dream_last_run_path is None:
            log.warning(
                "pulse.dispatch received concern_id=%s but Dream engine is "
                "not configured; dropping event.",
                event.concern_id,
            )
            return
        if self._active_dream_task is not None and not self._active_dream_task.done():
            log.info("dream.skip reason=task_in_flight")
            return
        engine = self._dream_engine
        if engine.get_state() == DreamState.RUNNING:
            log.info("dream.skip reason=engine_state_running")
            return
        if engine.get_state() != DreamState.IDLE:
            log.info(
                "dream.reset prior_state=%s", engine.get_state().value,
            )
            engine.reset_state()
        self._active_dream_task = asyncio.create_task(
            self._run_dream_once(engine, self._dream_last_run_path),
            name="dream-run",
        )

    async def _run_dream_once(
        self, engine: DreamEngine, last_run_path: Path,
    ) -> None:
        try:
            result = await engine.run()
        except Exception as exc:
            log.error(
                "dream.run crashed: %s: %s", type(exc).__name__, exc,
            )
            return
        write_last_run(last_run_path, self._now_utc())
        log.info(
            "dream.complete state=%s created=%d resolved=%d "
            "prompt_tokens=%d completion_tokens=%d error=%s",
            result.state.value, result.entries_created,
            result.entries_resolved, result.prompt_tokens_est,
            result.completion_tokens, result.error,
        )


def _default_now_utc() -> datetime:
    return datetime.now(timezone.utc)


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
