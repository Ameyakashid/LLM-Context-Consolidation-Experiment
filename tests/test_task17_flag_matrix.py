"""Four-cell flag matrix for Task 17 (Pulse × Dream).

Drives ``build_pulse_bundle`` with every combination of
``PULSE_ENGINE_ENABLED`` and ``DREAM_STATE_ENABLED`` and asserts the
returned bundle, dispatcher wiring, and log lines match the spec.

Cells
-----
1. (Pulse=OFF, Dream=OFF) — returns None, DEBUG ``"Pulse engine disabled"``.
2. (Pulse=ON,  Dream=OFF) — bundle non-None, ``dream_engine`` is None.
3. (Pulse=OFF, Dream=ON)  — returns None, WARN log about dependency.
4. (Pulse=ON,  Dream=ON)  — bundle non-None, ``dream_engine`` is set.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from checkin_schedule import CheckInScheduleStore
from hook_adapter import HookAdapter
from memory_store import MemoryEntryStore
from pulse_checkin_dispatcher import PendingCheckinQueue
from pulse_gateway_setup import build_pulse_bundle
from state_detection import load_state_config
from state_response_integration import StateResponseHook
from task_store import TaskStore


async def _dummy_llm(_prompt: str) -> str:
    return "baseline"


async def _dream_llm(_prompt: str, _max_tokens: int) -> str:
    return '{"insights": [], "entries_to_resolve": []}'


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


def _dream_kwargs(tmp_path: Path) -> dict[str, object]:
    template = (
        Path("workspace/templates/DREAM.md").read_text(encoding="utf-8")
    )
    return {
        "data_dir": tmp_path / "data",
        "dream_prompt_template": template,
        "dream_llm_caller": _dream_llm,
        "dream_clock": lambda: datetime.now(timezone.utc),
    }


class TestFlagMatrix:
    def test_cell_1_pulse_off_dream_off(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.DEBUG, logger="pulse_gateway_setup")
        bundle = build_pulse_bundle(
            hooks=[], stores=_stores(tmp_path), env={},
            tz=ZoneInfo("America/New_York"),
            pending_queue=PendingCheckinQueue(),
            get_current_date=lambda: date(2026, 4, 19),
        )
        assert bundle is None
        msgs = [r.getMessage() for r in caplog.records]
        assert any("Pulse engine disabled" in m for m in msgs)

    def test_cell_2_pulse_on_dream_off(self, tmp_path: Path) -> None:
        bundle = build_pulse_bundle(
            hooks=_state_hooks(),  # type: ignore[arg-type]
            stores=_stores(tmp_path),
            env={"PULSE_ENGINE_ENABLED": "true"},
            tz=ZoneInfo("America/New_York"),
            pending_queue=PendingCheckinQueue(),
            get_current_date=lambda: date(2026, 4, 19),
        )
        assert bundle is not None
        assert bundle.dream_engine is None
        assert bundle.dispatcher.active_dream_task is None

    def test_cell_3_pulse_off_dream_on_warns(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.WARNING, logger="pulse_gateway_setup")
        bundle = build_pulse_bundle(
            hooks=[], stores=_stores(tmp_path),
            env={"DREAM_STATE_ENABLED": "true"},
            tz=ZoneInfo("America/New_York"),
            pending_queue=PendingCheckinQueue(),
            get_current_date=lambda: date(2026, 4, 19),
        )
        assert bundle is None
        msgs = [r.getMessage() for r in caplog.records]
        assert any(
            "DREAM_STATE_ENABLED" in m and "PULSE_ENGINE_ENABLED" in m
            for m in msgs
        )

    def test_cell_4_pulse_on_dream_on(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.INFO, logger="pulse_gateway_setup")
        bundle = build_pulse_bundle(
            hooks=_state_hooks(),  # type: ignore[arg-type]
            stores=_stores(tmp_path),
            env={
                "PULSE_ENGINE_ENABLED": "true",
                "DREAM_STATE_ENABLED": "true",
            },
            tz=ZoneInfo("America/New_York"),
            pending_queue=PendingCheckinQueue(),
            get_current_date=lambda: date(2026, 4, 19),
            **_dream_kwargs(tmp_path),
        )
        assert bundle is not None
        assert bundle.dream_engine is not None
        msgs = [r.getMessage() for r in caplog.records]
        assert any("dream=True" in m for m in msgs)

    def test_cell_4_missing_dream_kwargs_raises(self, tmp_path: Path) -> None:
        with pytest.raises(RuntimeError, match="data_dir"):
            build_pulse_bundle(
                hooks=_state_hooks(),  # type: ignore[arg-type]
                stores=_stores(tmp_path),
                env={
                    "PULSE_ENGINE_ENABLED": "true",
                    "DREAM_STATE_ENABLED": "true",
                },
                tz=ZoneInfo("America/New_York"),
                pending_queue=PendingCheckinQueue(),
                get_current_date=lambda: date(2026, 4, 19),
            )
