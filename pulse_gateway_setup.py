"""Pulse engine + consumer lifecycle for ``run_gateway``.

``build_pulse_bundle`` constructs a ``PulseBundle`` when
``PULSE_ENGINE_ENABLED`` is on (returns None otherwise) and extends
the store with a Dream concern when ``DREAM_STATE_ENABLED`` is also on.
Dream without Pulse logs WARN and still returns None.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from nanobot.agent.hook import AgentHook

from checkin_schedule import CheckInScheduleStore
from dream_engine import DreamEngine
from memory_store import MemoryEntryStore
from pulse_checkin_dispatcher import (
    PendingCheckinQueue,
    PulseCheckinDispatcher,
    consume_pulse_events,
)
from pulse_checkin_store import PulseCheckinStore, is_pulse_engine_enabled
from pulse_engine import Pulse, PulseStoreProtocol
from pulse_schedule import PulseEvent
from pulse_system_concerns import (
    DEFAULT_DREAM_CRON,
    DreamConcernStore,
    CompositePulseStore,
    is_dream_state_enabled,
)
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

    ``dream_engine`` is non-None when both ``PULSE_ENGINE_ENABLED`` and
    ``DREAM_STATE_ENABLED`` are set — kept as a field so the flag-matrix
    test can assert wiring presence without reaching into the dispatcher.
    """

    cancel: asyncio.Event
    event_queue: asyncio.Queue[PulseEvent]
    pending_queue: PendingCheckinQueue
    pulse: Pulse
    dispatcher: PulseCheckinDispatcher
    dream_engine: DreamEngine | None = None
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
        dream_task = getattr(self.dispatcher, "active_dream_task", None)
        if dream_task is not None and not dream_task.done():
            await _drain_task(dream_task, timeout)

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
    *,
    data_dir: Path | None = None,
    dream_prompt_template: str | None = None,
    dream_llm_caller: Callable[[str, int], Awaitable[str]] | None = None,
    dream_clock: Callable[[], datetime] | None = None,
) -> PulseBundle | None:
    """Construct a PulseBundle when ``PULSE_ENGINE_ENABLED``; else None.

    Dream wiring is activated when ``DREAM_STATE_ENABLED`` is also set
    and the four Dream-specific parameters are all provided. Otherwise
    the bundle runs with check-ins only and ``dream_engine`` is None.

    When Dream is requested but Pulse is OFF, a WARN is logged and the
    function returns None — Dream cannot run without the Pulse loop.

    The caller owns ``pending_queue`` because ``SchedulingHook`` drains
    it while the dispatcher pushes onto it.  ``hooks`` is scanned for
    ``StateResponseHook`` so the dispatcher shares the same cognitive
    state source as the hook chain.
    """
    pulse_on = is_pulse_engine_enabled(env)
    dream_on = is_dream_state_enabled(env)
    if dream_on and not pulse_on:
        log.warning(
            "DREAM_STATE_ENABLED=true but PULSE_ENGINE_ENABLED is not true; "
            "Dream requires Pulse. Dream disabled.",
        )
    if not pulse_on:
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
    dream_engine: DreamEngine | None = None
    dream_last_run_path: Path | None = None
    store_for_pulse: PulseStoreProtocol = checkin_store

    if dream_on:
        dream_engine, dream_last_run_path, store_for_pulse = _build_dream_wiring(
            checkin_store=checkin_store,
            memory_store=memory_store,
            task_store=task_store,
            env=env,
            tz=tz,
            data_dir=data_dir,
            prompt_template=dream_prompt_template,
            llm_caller=dream_llm_caller,
            clock=dream_clock,
        )

    cancel = asyncio.Event()
    pulse, event_queue = Pulse.create(store=store_for_pulse, cancel=cancel)
    dispatcher = PulseCheckinDispatcher(
        schedule_store=schedule_store,
        task_store=task_store,
        memory_store=memory_store,
        pending_queue=pending_queue,
        get_cognitive_state=state_accessor,
        get_current_date=get_current_date,
        dream_engine=dream_engine,
        dream_last_run_path=dream_last_run_path,
    )

    enabled_count = sum(
        1 for entry in schedule_store.list_entries() if entry.is_enabled
    )
    log.info(
        "pulse.start concern_count=%d tz=%s flag=True dream=%s",
        enabled_count, tz.key, dream_engine is not None,
    )
    return PulseBundle(
        cancel=cancel,
        event_queue=event_queue,
        pending_queue=pending_queue,
        pulse=pulse,
        dispatcher=dispatcher,
        dream_engine=dream_engine,
    )


def _build_dream_wiring(
    *,
    checkin_store: PulseCheckinStore,
    memory_store: MemoryEntryStore,
    task_store: TaskStoreProtocol,
    env: Mapping[str, str],
    tz: ZoneInfo,
    data_dir: Path | None,
    prompt_template: str | None,
    llm_caller: Callable[[str, int], Awaitable[str]] | None,
    clock: Callable[[], datetime] | None,
) -> tuple[DreamEngine, Path, PulseStoreProtocol]:
    if (
        data_dir is None or prompt_template is None
        or llm_caller is None or clock is None
    ):
        raise RuntimeError(
            "build_pulse_bundle: DREAM_STATE_ENABLED=true requires "
            "data_dir, dream_prompt_template, dream_llm_caller, and "
            "dream_clock from the caller."
        )
    last_run_path = data_dir / "dream_last_run.json"
    cron_expr = env.get("DREAM_STATE_CRON", DEFAULT_DREAM_CRON).strip()
    engine = DreamEngine(
        memory_store=memory_store, task_store=task_store,
        session_log_path=data_dir / "dream_sessions.jsonl",
        llm_caller=llm_caller, clock=clock, prompt_template=prompt_template,
    )
    dream_store = DreamConcernStore(
        cron_expr=cron_expr, tz=tz, last_run_path=last_run_path,
    )
    return engine, last_run_path, CompositePulseStore([checkin_store, dream_store])


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
