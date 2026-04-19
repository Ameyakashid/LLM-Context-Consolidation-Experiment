"""Pulse async timer engine.

Ported from `references/temm1e/crates/temm1e-perpetuum/src/pulse.rs` lines 22-123.

Async primitives translation table (tokio → asyncio):

    tokio::select! { ... }                  → asyncio.wait(FIRST_COMPLETED)
    tokio::sync::mpsc::channel(64)          → asyncio.Queue(maxsize=64)
    tokio::sync::Notify                     → asyncio.Event (set + clear)
    tokio_util::sync::CancellationToken     → asyncio.Event (passed in)
    tokio::time::sleep                      → asyncio.sleep
    tokio::time::timeout                    → asyncio.wait_for

Deviations from source are documented inline and in the `17-01i.md` report.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Protocol

from pulse_schedule import ConcernId, PulseEvent

logger = logging.getLogger(__name__)

CHANNEL_MAX_SIZE = 64
STORE_QUERY_TIMEOUT_S = 10.0
IDLE_POLL_SECONDS = 60.0


class PulseStoreProtocol(Protocol):
    """Contract Pulse depends on. Sub-02 provides a concrete adapter.

    Mirrors the two awaitable methods of Rust's `Store` that `Pulse` uses
    (see pulse.rs:70 and pulse.rs:98). `next_fire_time` may return None when
    nothing is scheduled; `claim_due_concerns` returns the IDs to fire and is
    expected to mark them as claimed atomically.
    """

    async def next_fire_time(self) -> datetime | None: ...

    async def claim_due_concerns(self, now: datetime) -> list[ConcernId]: ...


class Pulse:
    """Timer engine: sleep until next due concern, fire all due, repeat.

    Construct with `Pulse.create(store, cancel)` which also returns the
    consumer `asyncio.Queue[PulseEvent]` (mirrors Rust's `(Pulse, Receiver)`
    tuple return from `Pulse::new`, pulse.rs:30).
    """

    def __init__(
        self,
        store: PulseStoreProtocol,
        concern_tx: asyncio.Queue[PulseEvent],
        cancel: asyncio.Event,
    ) -> None:
        self._store = store
        self._concern_tx = concern_tx
        self._cancel = cancel
        self._schedule_changed = asyncio.Event()

    @classmethod
    def create(
        cls,
        store: PulseStoreProtocol,
        cancel: asyncio.Event,
    ) -> tuple["Pulse", asyncio.Queue[PulseEvent]]:
        concern_tx: asyncio.Queue[PulseEvent] = asyncio.Queue(maxsize=CHANNEL_MAX_SIZE)
        return cls(store, concern_tx, cancel), concern_tx

    def schedule_notifier(self) -> asyncio.Event:
        """Returns the event that external callers set to wake the loop.

        Mirrors Rust `Pulse::schedule_notifier` (pulse.rs:42) returning the
        shared `Arc<Notify>`. asyncio has no Notify analogue — the Event is
        `set()` by the caller and `.clear()`ed by the loop after each wake.
        """
        return self._schedule_changed

    async def run(self) -> None:
        logger.info("Pulse timer engine started")
        while True:
            cancel_task = asyncio.create_task(
                self._cancel.wait(), name="pulse-cancel"
            )
            sleep_task = asyncio.create_task(
                self._sleep_until_next(), name="pulse-sleep"
            )
            notify_task = asyncio.create_task(
                self._schedule_changed.wait(), name="pulse-schedule-changed"
            )
            done, pending = await asyncio.wait(
                {cancel_task, sleep_task, notify_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            await _cancel_pending(pending)
            _reraise_task_errors(done)

            if cancel_task in done:
                logger.info("Pulse shutting down")
                return
            if notify_task in done:
                logger.debug("Schedule changed, recomputing")
                self._schedule_changed.clear()
                continue
            await self._fire_due_concerns()

    async def _sleep_until_next(self) -> None:
        fire_at = await self._query_next_fire_time()
        if fire_at is None:
            await asyncio.sleep(IDLE_POLL_SECONDS)
            return
        until = (fire_at - datetime.now(timezone.utc)).total_seconds()
        if until <= 0:
            return
        await asyncio.sleep(until)

    async def _query_next_fire_time(self) -> datetime | None:
        try:
            return await asyncio.wait_for(
                self._store.next_fire_time(),
                timeout=STORE_QUERY_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Pulse store.next_fire_time() timed out after %.1fs; "
                "treating as no-schedule",
                STORE_QUERY_TIMEOUT_S,
            )
            return None

    async def _fire_due_concerns(self) -> None:
        try:
            due = await self._store.claim_due_concerns(datetime.now(timezone.utc))
        except Exception as exc:
            # Mirrors Rust's logged swallow (pulse.rs:100-103): a store failure
            # must not tear down the pulse loop. Narrow exception type comes
            # from the store adapter in sub-02.
            logger.error(
                "Pulse store.claim_due_concerns() failed: %s; "
                "loop continues, retry on next tick",
                exc,
            )
            return
        if not due:
            return
        for concern_id in due:
            await self._concern_tx.put(PulseEvent(concern_id=concern_id))


async def _cancel_pending(tasks: Iterable[asyncio.Task[object]]) -> None:
    materialised = list(tasks)
    for task in materialised:
        task.cancel()
    for task in materialised:
        try:
            await task
        except asyncio.CancelledError:
            pass


def _reraise_task_errors(tasks: Iterable[asyncio.Task[object]]) -> None:
    for task in tasks:
        if task.cancelled():
            continue
        exc = task.exception()
        if exc is not None:
            raise exc


__all__ = [
    "CHANNEL_MAX_SIZE",
    "IDLE_POLL_SECONDS",
    "Pulse",
    "PulseStoreProtocol",
    "STORE_QUERY_TIMEOUT_S",
]
