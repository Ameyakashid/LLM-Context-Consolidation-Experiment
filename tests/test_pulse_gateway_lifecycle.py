"""Gateway lifecycle tests for Pulse bundle wiring (Task 17 sub-03, AC#5).

Covers two surfaces:

* :class:`PulseBundle` directly — ``start`` spawns exactly two named
  asyncio tasks (``pulse-engine``, ``pulse-consumer``); ``stop`` drains
  both within the 5s budget without leaking cancel spam.
* :func:`build_pulse_bundle` flag gate — flag OFF returns ``None`` and
  allocates nothing; flag ON against a real workspace builds a bundle
  whose ``tasks()`` list is empty until ``start()`` runs.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from checkin_schedule import CheckInScheduleStore
from hook_adapter import HookAdapter
from memory_store import MemoryEntryStore
from pulse_checkin_dispatcher import PendingCheckinQueue
from pulse_gateway_setup import (
    PULSE_SHUTDOWN_TIMEOUT_S,
    PulseBundle,
    build_pulse_bundle,
)
from pulse_schedule import ConcernId, PulseEvent
from state_detection import load_state_config
from state_response_integration import StateResponseHook
from task_store import TaskStore


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

@dataclass
class StubPulse:
    """Stand-in for the real ``Pulse`` engine."""

    cancel: asyncio.Event

    async def run(self) -> None:
        await self.cancel.wait()


@dataclass
class StubDispatcher:
    events: list[PulseEvent] = field(default_factory=list)

    def dispatch(self, event: PulseEvent) -> None:
        self.events.append(event)


async def _dummy_llm(_prompt: str) -> str:
    return "baseline"


def _run(coro: object) -> object:
    return asyncio.run(coro)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# PulseBundle lifecycle
# ---------------------------------------------------------------------------

def _make_bundle() -> PulseBundle:
    cancel = asyncio.Event()
    return PulseBundle(
        cancel=cancel,
        event_queue=asyncio.Queue(),
        pending_queue=PendingCheckinQueue(),
        pulse=StubPulse(cancel=cancel),  # type: ignore[arg-type]
        dispatcher=StubDispatcher(),  # type: ignore[arg-type]
    )


class TestPulseBundleLifecycle:

    def test_start_spawns_exactly_two_tasks(self) -> None:
        async def body() -> tuple[int, set[str]]:
            bundle = _make_bundle()
            bundle.start()
            try:
                tasks = bundle.tasks()
                return len(tasks), {t.get_name() for t in tasks}
            finally:
                await bundle.stop()

        count, names = _run(body())  # type: ignore[misc]
        assert count == 2
        assert names == {"pulse-engine", "pulse-consumer"}

    def test_stop_drains_within_budget(self) -> None:
        async def body() -> tuple[float, list[bool]]:
            bundle = _make_bundle()
            bundle.start()
            loop = asyncio.get_running_loop()
            start = loop.time()
            await bundle.stop()
            elapsed = loop.time() - start
            return elapsed, [t.done() for t in bundle.tasks()]

        elapsed, done_flags = _run(body())  # type: ignore[misc]
        assert elapsed < PULSE_SHUTDOWN_TIMEOUT_S
        assert all(done_flags)

    def test_stop_before_start_is_noop(self) -> None:
        async def body() -> list[asyncio.Task[None]]:
            bundle = _make_bundle()
            await bundle.stop()
            return bundle.tasks()

        assert _run(body()) == []  # type: ignore[comparison-overlap]

    def test_start_twice_raises(self) -> None:
        async def body() -> None:
            bundle = _make_bundle()
            bundle.start()
            try:
                with pytest.raises(RuntimeError):
                    bundle.start()
            finally:
                await bundle.stop()

        _run(body())

    def test_consumer_dispatches_queued_event(self) -> None:
        async def body() -> list[PulseEvent]:
            cancel = asyncio.Event()
            dispatcher = StubDispatcher()
            bundle = PulseBundle(
                cancel=cancel,
                event_queue=asyncio.Queue(),
                pending_queue=PendingCheckinQueue(),
                pulse=StubPulse(cancel=cancel),  # type: ignore[arg-type]
                dispatcher=dispatcher,  # type: ignore[arg-type]
            )
            bundle.start()
            try:
                event = PulseEvent(
                    concern_id=ConcernId("morning_motivation"),
                    fired_at=datetime.now(),
                )
                await bundle.event_queue.put(event)
                for _ in range(50):
                    if dispatcher.events:
                        break
                    await asyncio.sleep(0.01)
                return list(dispatcher.events)
            finally:
                await bundle.stop()

        events = _run(body())  # type: ignore[misc]
        assert len(events) == 1
        assert events[0].concern_id == "morning_motivation"


# ---------------------------------------------------------------------------
# build_pulse_bundle flag gate
# ---------------------------------------------------------------------------

class TestBuildPulseBundleFlagGate:

    def _stores(self, tmp_path: Path) -> dict[str, object]:
        return {
            "schedule": CheckInScheduleStore(tmp_path / "schedule.json"),
            "task": TaskStore(tmp_path / "tasks.json"),
            "memory": MemoryEntryStore(tmp_path / "memories.json"),
        }

    def _state_hook(self) -> StateResponseHook:
        config = load_state_config(Path("workspace/states.yaml"))
        return StateResponseHook(config=config, llm_call=_dummy_llm)

    def test_flag_off_returns_none_and_logs_debug(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.DEBUG, logger="pulse_gateway_setup")
        bundle = build_pulse_bundle(
            hooks=[],
            stores=self._stores(tmp_path),
            env={},
            tz=ZoneInfo("America/New_York"),
            pending_queue=PendingCheckinQueue(),
            get_current_date=lambda: date(2026, 4, 10),
        )
        assert bundle is None
        messages = [r.getMessage() for r in caplog.records]
        assert any("Pulse engine disabled" in m for m in messages)

    def test_flag_on_returns_bundle_with_zero_tasks_pre_start(
        self, tmp_path: Path,
    ) -> None:
        hooks = [HookAdapter(hook=self._state_hook(), name="StateResponseHook")]
        bundle = build_pulse_bundle(
            hooks=hooks,
            stores=self._stores(tmp_path),
            env={"PULSE_ENGINE_ENABLED": "true"},
            tz=ZoneInfo("America/New_York"),
            pending_queue=PendingCheckinQueue(),
            get_current_date=lambda: date(2026, 4, 10),
        )
        assert bundle is not None
        assert bundle.tasks() == []

    def test_flag_on_missing_state_hook_raises(
        self, tmp_path: Path,
    ) -> None:
        with pytest.raises(RuntimeError, match="StateResponseHook not found"):
            build_pulse_bundle(
                hooks=[],
                stores=self._stores(tmp_path),
                env={"PULSE_ENGINE_ENABLED": "true"},
                tz=ZoneInfo("America/New_York"),
                pending_queue=PendingCheckinQueue(),
                get_current_date=lambda: date(2026, 4, 10),
            )

    def test_flag_on_missing_store_raises(self, tmp_path: Path) -> None:
        hooks = [HookAdapter(hook=self._state_hook(), name="StateResponseHook")]
        stores: dict[str, object] = {
            "schedule": CheckInScheduleStore(tmp_path / "schedule.json"),
            "task": TaskStore(tmp_path / "tasks.json"),
        }
        with pytest.raises(RuntimeError, match="memory"):
            build_pulse_bundle(
                hooks=hooks,
                stores=stores,
                env={"PULSE_ENGINE_ENABLED": "true"},
                tz=ZoneInfo("America/New_York"),
                pending_queue=PendingCheckinQueue(),
                get_current_date=lambda: date(2026, 4, 10),
            )
