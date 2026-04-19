"""Pulse engine + consumer lifecycle for ``run_gateway``.

Builds and owns the Pulse background tasks so ``gateway_runner`` stays
thin.  A ``PulseBundle`` groups the cancel event, event queue, pending
queue, engine, dispatcher, and the two asyncio tasks; ``build_pulse_bundle``
constructs the bundle when the ``PULSE_ENGINE_ENABLED`` flag is on and
returns None otherwise.

Flag-off semantics: ``build_pulse_bundle`` returns None and only emits a
single DEBUG log line.  No ``PulseCheckinStore`` is constructed, no
tasks are created, and no clocks are started.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date
from zoneinfo import ZoneInfo

from nanobot.agent.hook import AgentHook

from checkin_schedule import CheckInScheduleStore
from memory_store import MemoryEntryStore
from pulse_checkin_dispatcher import (
    PendingCheckinQueue,
    PulseCheckinDispatcher,
    consume_pulse_events,
)
from pulse_checkin_store import PulseCheckinStore, is_pulse_engine_enabled
from pulse_engine import Pulse
from pulse_schedule import PulseEvent
from state_detection import StateName
from state_response_integration import StateResponseHook
from task_store import TaskStoreProtocol

log = logging.getLogger(__name__)

PULSE_SHUTDOWN_TIMEOUT_S = 5.0


@dataclass
class PulseBundle:
    """Lifecycle container for the Pulse background stack.

    The two tasks (``pulse_task``, ``consumer_task``) are spawned by
    :meth:`start` and reaped by :meth:`stop`.  The bundle is single-use:
    calling ``start`` twice raises.
    """

    cancel: asyncio.Event
    event_queue: asyncio.Queue[PulseEvent]
    pending_queue: PendingCheckinQueue
    pulse: Pulse
    dispatcher: PulseCheckinDispatcher
    _pulse_task: asyncio.Task[None] | None = field(default=None)
    _consumer_task: asyncio.Task[None] | None = field(default=None)

    def start(self) -> None:
        if self._pulse_task is not None or self._consumer_task is not None:
            raise RuntimeError(
                "PulseBundle.start called twice; bundles are single-use."
            )
        self._pulse_task = asyncio.create_task(
            self.pulse.run(), name="pulse-engine",
        )
        self._consumer_task = asyncio.create_task(
            consume_pulse_events(
                self.event_queue, self.dispatcher, self.cancel,
            ),
            name="pulse-consumer",
        )

    async def stop(self, timeout: float = PULSE_SHUTDOWN_TIMEOUT_S) -> None:
        if self._pulse_task is None or self._consumer_task is None:
            return
        self.cancel.set()
        log.info("pulse.stop reason=cancelled")
        await _drain_task(self._pulse_task, timeout)
        await _drain_task(self._consumer_task, timeout)

    def tasks(self) -> list[asyncio.Task[None]]:
        return [
            t for t in (self._pulse_task, self._consumer_task)
            if t is not None
        ]


def build_pulse_bundle(
    hooks: list[AgentHook],
    stores: Mapping[str, object],
    env: Mapping[str, str],
    tz: ZoneInfo,
    pending_queue: PendingCheckinQueue,
    get_current_date: Callable[[], date],
) -> PulseBundle | None:
    """Construct a PulseBundle when the flag is on; else return None.

    The caller owns ``pending_queue`` because ``SchedulingHook`` needs
    the same instance — the hook drains it, the dispatcher pushes onto
    it.  ``hooks`` is scanned for the ``StateResponseHook`` so the
    dispatcher shares the same cognitive-state source as the hook chain.
    """
    if not is_pulse_engine_enabled(env):
        log.debug("Pulse engine disabled")
        return None

    state_accessor = _derive_state_accessor(hooks)
    schedule_store: CheckInScheduleStore = _require_store(
        stores, "schedule", CheckInScheduleStore,
    )
    task_store: TaskStoreProtocol = _require_store_protocol(stores, "task")
    memory_store: MemoryEntryStore = _require_store(
        stores, "memory", MemoryEntryStore,
    )

    checkin_store = PulseCheckinStore(store=schedule_store, tz=tz)
    cancel = asyncio.Event()
    pulse, event_queue = Pulse.create(store=checkin_store, cancel=cancel)
    dispatcher = PulseCheckinDispatcher(
        schedule_store=schedule_store,
        task_store=task_store,
        memory_store=memory_store,
        pending_queue=pending_queue,
        get_cognitive_state=state_accessor,
        get_current_date=get_current_date,
    )

    enabled_count = sum(
        1 for entry in schedule_store.list_entries() if entry.is_enabled
    )
    log.info(
        "pulse.start concern_count=%d tz=%s flag=True",
        enabled_count, tz.key,
    )
    return PulseBundle(
        cancel=cancel,
        event_queue=event_queue,
        pending_queue=pending_queue,
        pulse=pulse,
        dispatcher=dispatcher,
    )


def _derive_state_accessor(
    hooks: list[AgentHook],
) -> Callable[[], StateName]:
    for hook in hooks:
        wrapped = getattr(hook, "wrapped", None)
        if isinstance(wrapped, StateResponseHook):
            state_hook = wrapped

            def accessor() -> StateName:
                return state_hook.current_state  # type: ignore[return-value]

            return accessor
    raise RuntimeError(
        "PulseBundle build failed: StateResponseHook not found in hook "
        "chain. Construct hooks via hook_factory.create_hooks before "
        "calling build_pulse_bundle."
    )


def _require_store[T](
    stores: Mapping[str, object], key: str, expected: type[T],
) -> T:
    value = stores.get(key)
    if not isinstance(value, expected):
        raise RuntimeError(
            f"PulseBundle build failed: stores[{key!r}] must be a "
            f"{expected.__name__}; got {type(value).__name__}."
        )
    return value


def _require_store_protocol(
    stores: Mapping[str, object], key: str,
) -> TaskStoreProtocol:
    value = stores.get(key)
    if value is None:
        raise RuntimeError(
            f"PulseBundle build failed: stores[{key!r}] is missing."
        )
    return value  # type: ignore[return-value]


async def _drain_task(
    task: asyncio.Task[None], timeout: float,
) -> None:
    try:
        await asyncio.wait_for(task, timeout=timeout)
    except asyncio.TimeoutError:
        log.warning(
            "pulse task %s did not stop in %.1fs; cancelling forcibly",
            task.get_name(), timeout,
        )
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    except asyncio.CancelledError:
        pass


__all__ = [
    "PULSE_SHUTDOWN_TIMEOUT_S",
    "PulseBundle",
    "build_pulse_bundle",
]
