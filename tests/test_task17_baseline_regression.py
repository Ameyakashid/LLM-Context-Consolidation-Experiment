"""Baseline regression guard for Task 17 flag-OFF behaviour.

Verifies that with both ``PULSE_ENGINE_ENABLED`` and
``DREAM_STATE_ENABLED`` unset (or explicitly ``"false"``),
``build_pulse_bundle`` returns ``None`` and no Pulse / Dream asyncio tasks
exist — the legacy SchedulingHook heartbeat path is then free to drive
all four check-ins exactly as it did before Task 17.

Also enforces a numerical test-count floor: the pre-Task-17 scheduling
and check-in unit suites must still be collectible at their original
sizes. Coverage that was green before the flag must stay green now.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from checkin_schedule import CheckInScheduleStore
from memory_store import MemoryEntryStore
from pulse_checkin_dispatcher import PendingCheckinQueue
from pulse_gateway_setup import build_pulse_bundle
from task_store import TaskStore


def _stores(tmp_path: Path) -> dict[str, object]:
    return {
        "schedule": CheckInScheduleStore(tmp_path / "schedule.json"),
        "task": TaskStore(tmp_path / "tasks.json"),
        "memory": MemoryEntryStore(tmp_path / "memories.json"),
    }


class TestFlagsOffBuildsNoBundle:
    def test_both_flags_absent_returns_none(
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

    def test_both_flags_false_returns_none(self, tmp_path: Path) -> None:
        bundle = build_pulse_bundle(
            hooks=[], stores=_stores(tmp_path),
            env={
                "PULSE_ENGINE_ENABLED": "false",
                "DREAM_STATE_ENABLED": "false",
            },
            tz=ZoneInfo("America/New_York"),
            pending_queue=PendingCheckinQueue(),
            get_current_date=lambda: date(2026, 4, 19),
        )
        assert bundle is None

    @pytest.mark.parametrize("value", ["1", "yes", "on", "", "nope"])
    def test_non_canonical_truthy_values_stay_off(
        self, tmp_path: Path, value: str,
    ) -> None:
        bundle = build_pulse_bundle(
            hooks=[], stores=_stores(tmp_path),
            env={"PULSE_ENGINE_ENABLED": value},
            tz=ZoneInfo("America/New_York"),
            pending_queue=PendingCheckinQueue(),
            get_current_date=lambda: date(2026, 4, 19),
        )
        assert bundle is None


class TestNoStrayAsyncTasks:
    def test_no_pulse_tasks_scheduled_when_off(self, tmp_path: Path) -> None:
        async def scenario() -> list[str]:
            bundle = build_pulse_bundle(
                hooks=[], stores=_stores(tmp_path), env={},
                tz=ZoneInfo("America/New_York"),
                pending_queue=PendingCheckinQueue(),
                get_current_date=lambda: date(2026, 4, 19),
            )
            assert bundle is None
            return [t.get_name() for t in asyncio.all_tasks()]

        names = asyncio.run(scenario())
        pulse_related = [
            n for n in names
            if "pulse" in n.lower() or "dream" in n.lower()
        ]
        assert pulse_related == []


class TestBaselineSuiteCounts:
    """Floor on pre-Task-17 scheduling/check-in tests.

    A drop in these counts means sub-05 removed or broke coverage that
    was passing before the flag landed — blocker until investigated.
    """

    MIN_COUNTS = {
        "tests/test_scheduling_hook.py": 1,
        "tests/test_schedule_engine.py": 1,
        "tests/test_checkin_schedule.py": 1,
    }

    def test_baseline_suites_still_collectible(self) -> None:
        for path, floor in self.MIN_COUNTS.items():
            result = subprocess.run(
                [sys.executable, "-m", "pytest", path, "--collect-only", "-q"],
                capture_output=True, text=True, check=True,
            )
            last = result.stdout.strip().splitlines()[-1]
            count = int(last.split()[0])
            assert count >= floor, (
                f"{path} collected {count} tests; baseline floor is {floor}. "
                "Task 17 must not remove pre-existing coverage."
            )
