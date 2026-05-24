"""Simulated-day integration for Pulse + Dream.

Drives ``build_pulse_bundle`` with both flags ON, then dispatches the
five concern events Pulse would emit across one day — four check-ins
at 08:00 / 09:00 / 14:00 / 20:00 and one Dream run at 03:00 — and
asserts:

* Each check-in produces a ``PendingCheckin`` on the queue.
* The Dream run writes ``MemoryEntry`` rows tagged
  ``metadata.source = "dream_state"``.
* ``llm_caller`` is invoked exactly once (the Dream run).
* ``dream_last_run.json`` is written after success so a same-day reboot
  skips re-firing.
* The Dream-authored memories are visible to
  ``MemoryContextHook.before_iteration`` on the following agent tick.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Coroutine
from datetime import date, datetime, timezone
from pathlib import Path
from typing import TypeVar
from zoneinfo import ZoneInfo

from checkin_schedule import CheckInScheduleStore
from hook_adapter import HookAdapter
from memory_context import MemoryContextHook
from memory_store import MemoryEntryStore
from pulse_checkin_dispatcher import PendingCheckinQueue
from pulse_gateway_setup import build_pulse_bundle
from pulse_schedule import PulseEvent
from state_detection import load_state_config
from state_response_integration import StateResponseHook
from task_store import TaskStore

T = TypeVar("T")

FIXED_UTC = datetime(2026, 4, 20, 7, 0, tzinfo=timezone.utc)

DREAM_LLM_JSON = (
    '{"insights": ['
    '{"category": "commitment", "content": "Ship sub-05 tomorrow"},'
    '{"category": "energy_state", "content": "Evening focus is solid"}'
    '], "entries_to_resolve": []}'
)


def _run(coro: Coroutine[object, object, T]) -> T:
    return asyncio.run(coro)


async def _dummy_llm(_prompt: str) -> str:
    return "baseline"


def _state_hooks() -> list[object]:
    config = load_state_config(Path("workspace/states.yaml"))
    hook = StateResponseHook(config=config, llm_call=_dummy_llm)
    return [HookAdapter(hook=hook, name="StateResponseHook")]


def _stores(tmp_path: Path) -> dict[str, object]:
    return {
        "schedule": CheckInScheduleStore(tmp_path / "schedule.json"),
        "task": TaskStore(tmp_path / "tasks.json"),
        "memory": MemoryEntryStore(tmp_path / "memories.json"),
    }


class _CountingLLM:
    def __init__(self, response: str) -> None:
        self._response = response
        self.calls = 0

    async def __call__(self, _prompt: str, _max_tokens: int) -> str:
        self.calls += 1
        return self._response


def _build_bundle(
    tmp_path: Path, stores: dict[str, object], llm: _CountingLLM,
):
    template = Path("workspace/templates/DREAM.md").read_text(encoding="utf-8")
    return build_pulse_bundle(
        hooks=_state_hooks(),  # type: ignore[arg-type]
        stores=stores,
        env={
            "PULSE_ENGINE_ENABLED": "true",
            "DREAM_STATE_ENABLED": "true",
        },
        tz=ZoneInfo("America/New_York"),
        pending_queue=PendingCheckinQueue(),
        get_current_date=lambda: date(2026, 4, 20),
        data_dir=tmp_path / "data",
        dream_prompt_template=template,
        dream_llm_caller=llm,
        dream_clock=lambda: FIXED_UTC,
    )


class TestSimulatedDay:
    def test_four_checkins_queue_and_dream_writes_memories(
        self, tmp_path: Path,
    ) -> None:
        stores = _stores(tmp_path)
        llm = _CountingLLM(DREAM_LLM_JSON)
        bundle = _build_bundle(tmp_path, stores, llm)
        assert bundle is not None

        day_events = [
            PulseEvent(concern_id="morning_motivation"),
            PulseEvent(concern_id="morning_plan"),
            PulseEvent(concern_id="afternoon_check"),
            PulseEvent(concern_id="evening_review"),
            PulseEvent(concern_id="dream_state"),
        ]

        async def drive() -> None:
            for event in day_events:
                bundle.dispatcher.dispatch(event)
            dream_task = bundle.dispatcher.active_dream_task
            assert dream_task is not None
            await dream_task

        _run(drive())

        memory_store = stores["memory"]
        assert isinstance(memory_store, MemoryEntryStore)
        dream_entries = [
            e for e in memory_store.list_active_entries()
            if e.metadata.get("source") == "dream_state"
        ]
        assert len(dream_entries) == 2
        categories = {e.category for e in dream_entries}
        assert categories == {"commitment", "energy_state"}

        assert llm.calls == 1

    def test_dream_last_run_persisted_after_success(
        self, tmp_path: Path,
    ) -> None:
        stores = _stores(tmp_path)
        llm = _CountingLLM(DREAM_LLM_JSON)
        bundle = _build_bundle(tmp_path, stores, llm)
        assert bundle is not None

        async def drive() -> None:
            bundle.dispatcher.dispatch(PulseEvent(concern_id="dream_state"))
            task = bundle.dispatcher.active_dream_task
            assert task is not None
            await task

        _run(drive())
        last_run_path = tmp_path / "data" / "dream_last_run.json"
        assert last_run_path.exists()
        payload = json.loads(last_run_path.read_text(encoding="utf-8"))
        assert "last_run_utc" in payload
        parsed = datetime.fromisoformat(payload["last_run_utc"])
        assert parsed.tzinfo is not None


class TestMemoryContextPicksUpDreamMemories:
    def test_dream_rows_surface_in_next_system_prompt(
        self, tmp_path: Path,
    ) -> None:
        stores = _stores(tmp_path)
        llm = _CountingLLM(DREAM_LLM_JSON)
        bundle = _build_bundle(tmp_path, stores, llm)
        assert bundle is not None

        async def drive() -> None:
            bundle.dispatcher.dispatch(PulseEvent(concern_id="dream_state"))
            task = bundle.dispatcher.active_dream_task
            assert task is not None
            await task

        _run(drive())

        memory_store = stores["memory"]
        assert isinstance(memory_store, MemoryEntryStore)
        hook = MemoryContextHook(store=memory_store, max_entries=50)

        class _Ctx:
            def __init__(self) -> None:
                self.messages: list[dict[str, str]] = [
                    {"role": "system", "content": "base"},
                ]

        ctx = _Ctx()
        _run(hook.before_iteration(ctx))

        prompt = ctx.messages[0]["content"]
        assert "Ship sub-05 tomorrow" in prompt
        assert "Evening focus is solid" in prompt


class TestPendingQueueDrainedByDispatch:
    def test_four_pending_blocks_after_four_checkin_events(
        self, tmp_path: Path,
    ) -> None:
        stores = _stores(tmp_path)
        llm = _CountingLLM(DREAM_LLM_JSON)
        queue = PendingCheckinQueue()
        template = Path(
            "workspace/templates/DREAM.md",
        ).read_text(encoding="utf-8")
        bundle = build_pulse_bundle(
            hooks=_state_hooks(),  # type: ignore[arg-type]
            stores=stores,
            env={
                "PULSE_ENGINE_ENABLED": "true",
                "DREAM_STATE_ENABLED": "true",
            },
            tz=ZoneInfo("America/New_York"),
            pending_queue=queue,
            get_current_date=lambda: date(2026, 4, 20),
            data_dir=tmp_path / "data",
            dream_prompt_template=template,
            dream_llm_caller=llm,
            dream_clock=lambda: FIXED_UTC,
        )
        assert bundle is not None

        for cid in (
            "morning_motivation", "morning_plan",
            "afternoon_check", "evening_review",
        ):
            bundle.dispatcher.dispatch(PulseEvent(concern_id=cid))

        drained = []
        while True:
            item = queue.drain_one()
            if item is None:
                break
            drained.append(item)
        types = [p.checkin_type for p in drained]
        assert sorted(types) == [
            "afternoon_check", "evening_review",
            "morning_motivation", "morning_plan",
        ]
