"""Async tests for Pulse — port of the five scenarios in 17-01r.md §4b.

Uses the repo's existing asyncio-run helper pattern (no pytest-asyncio).
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from datetime import datetime, timedelta, timezone
from typing import Any, TypeVar

import pytest

import pulse_engine
from pulse_engine import Pulse
from pulse_schedule import ConcernId, PulseEvent

UTC = timezone.utc
_SCENARIO_TIMEOUT_S = 3.0

_T = TypeVar("_T")


def _run(coro: Coroutine[Any, Any, _T]) -> _T:
    return asyncio.run(asyncio.wait_for(coro, timeout=_SCENARIO_TIMEOUT_S))


class FakePulseStore:
    """Configurable in-memory PulseStoreProtocol impl.

    `next_time_sequence` is popped once per call; final value sticks.
    `due_sequence` behaves the same for claim_due_concerns returns.
    `next_time_delay_s` optionally delays the next_fire_time response (used
    for the store-timeout scenario).
    """

    def __init__(
        self,
        next_time_sequence: list[datetime | None],
        due_sequence: list[list[ConcernId]],
        next_time_delay_s: float = 0.0,
    ) -> None:
        self._next_times = list(next_time_sequence)
        self._dues = list(due_sequence)
        self._delay = next_time_delay_s
        self.next_fire_time_calls = 0
        self.claim_due_calls = 0
        self.claim_due_args: list[datetime] = []

    async def next_fire_time(self) -> datetime | None:
        self.next_fire_time_calls += 1
        if self._delay > 0:
            await asyncio.sleep(self._delay)
        if len(self._next_times) > 1:
            return self._next_times.pop(0)
        return self._next_times[0] if self._next_times else None

    async def claim_due_concerns(self, now: datetime) -> list[ConcernId]:
        self.claim_due_calls += 1
        self.claim_due_args.append(now)
        if len(self._dues) > 1:
            return self._dues.pop(0)
        return list(self._dues[0]) if self._dues else []


class RaisingStore:
    """Store whose claim_due_concerns raises — verifies error swallow."""

    def __init__(self) -> None:
        self.next_fire_time_calls = 0
        self.claim_due_calls = 0

    async def next_fire_time(self) -> datetime | None:
        self.next_fire_time_calls += 1
        return datetime.now(UTC) - timedelta(seconds=1)

    async def claim_due_concerns(self, now: datetime) -> list[ConcernId]:
        self.claim_due_calls += 1
        raise RuntimeError("simulated store failure")


def test_cancel_event_set_before_run_returns_immediately() -> None:
    async def scenario() -> float:
        store = FakePulseStore(next_time_sequence=[None], due_sequence=[[]])
        cancel = asyncio.Event()
        cancel.set()
        pulse, _queue = Pulse.create(store, cancel)
        loop = asyncio.get_running_loop()
        start = loop.time()
        await pulse.run()
        return loop.time() - start

    elapsed = _run(scenario())
    assert elapsed < 1.0


def test_cancel_event_set_mid_run_stops_loop() -> None:
    async def scenario() -> None:
        store = FakePulseStore(
            next_time_sequence=[datetime.now(UTC) + timedelta(hours=1)],
            due_sequence=[[]],
        )
        cancel = asyncio.Event()
        pulse, _queue = Pulse.create(store, cancel)
        task = asyncio.create_task(pulse.run())
        await asyncio.sleep(0.05)
        cancel.set()
        await asyncio.wait_for(task, timeout=1.0)

    _run(scenario())


def test_no_concerns_polls_on_idle_cadence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pulse_engine, "IDLE_POLL_SECONDS", 0.02)

    async def scenario() -> int:
        store = FakePulseStore(next_time_sequence=[None], due_sequence=[[]])
        cancel = asyncio.Event()
        pulse, _queue = Pulse.create(store, cancel)
        task = asyncio.create_task(pulse.run())
        await asyncio.sleep(0.15)
        cancel.set()
        await asyncio.wait_for(task, timeout=1.0)
        return store.next_fire_time_calls

    calls = _run(scenario())
    assert calls >= 3


def test_due_concern_emits_pulse_event() -> None:
    past = datetime.now(UTC) - timedelta(seconds=1)

    async def scenario() -> PulseEvent:
        store = FakePulseStore(
            next_time_sequence=[past, None],
            due_sequence=[["concern-a"], []],
        )
        cancel = asyncio.Event()
        pulse, queue = Pulse.create(store, cancel)
        task = asyncio.create_task(pulse.run())
        event = await asyncio.wait_for(queue.get(), timeout=1.0)
        cancel.set()
        await asyncio.wait_for(task, timeout=1.0)
        return event

    event = _run(scenario())
    assert event.concern_id == "concern-a"
    assert event.kind == "concern_due"


def test_schedule_change_wakes_loop_without_firing() -> None:
    far_future = datetime.now(UTC) + timedelta(hours=1)

    async def scenario() -> tuple[int, int]:
        store = FakePulseStore(next_time_sequence=[far_future], due_sequence=[[]])
        cancel = asyncio.Event()
        pulse, _queue = Pulse.create(store, cancel)
        task = asyncio.create_task(pulse.run())
        await asyncio.sleep(0.05)
        calls_before = store.next_fire_time_calls
        pulse.schedule_notifier().set()
        await asyncio.sleep(0.05)
        cancel.set()
        await asyncio.wait_for(task, timeout=1.0)
        return calls_before, store.next_fire_time_calls

    before, after = _run(scenario())
    assert before >= 1
    assert after > before


def test_store_next_fire_time_timeout_does_not_tear_down_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pulse_engine, "STORE_QUERY_TIMEOUT_S", 0.03)
    monkeypatch.setattr(pulse_engine, "IDLE_POLL_SECONDS", 0.01)

    async def scenario() -> int:
        store = FakePulseStore(
            next_time_sequence=[None],
            due_sequence=[[]],
            next_time_delay_s=0.5,
        )
        cancel = asyncio.Event()
        pulse, _queue = Pulse.create(store, cancel)
        task = asyncio.create_task(pulse.run())
        await asyncio.sleep(0.2)
        cancel.set()
        await asyncio.wait_for(task, timeout=1.0)
        return store.next_fire_time_calls

    calls = _run(scenario())
    assert calls >= 2


def test_claim_due_concerns_exception_is_swallowed_and_loop_survives() -> None:
    async def scenario() -> tuple[int, int]:
        store = RaisingStore()
        cancel = asyncio.Event()
        pulse, _queue = Pulse.create(store, cancel)
        task = asyncio.create_task(pulse.run())
        await asyncio.sleep(0.05)
        cancel.set()
        await asyncio.wait_for(task, timeout=1.0)
        return store.next_fire_time_calls, store.claim_due_calls

    nft, cdc = _run(scenario())
    assert nft >= 1
    assert cdc >= 1


def test_schedule_notifier_returns_same_event_across_calls() -> None:
    store = FakePulseStore(next_time_sequence=[None], due_sequence=[[]])
    cancel = asyncio.Event()
    pulse, _queue = Pulse.create(store, cancel)
    first = pulse.schedule_notifier()
    second = pulse.schedule_notifier()
    assert first is second


def test_create_returns_queue_with_configured_max_size() -> None:
    store = FakePulseStore(next_time_sequence=[None], due_sequence=[[]])
    cancel = asyncio.Event()
    _pulse, queue = Pulse.create(store, cancel)
    assert queue.maxsize == pulse_engine.CHANNEL_MAX_SIZE
    assert pulse_engine.CHANNEL_MAX_SIZE == 64
