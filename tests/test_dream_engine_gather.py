"""Gather-phase tests for the Dream engine."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from dream_helpers import gather_consolidation_context
from dream_types import DREAM_METADATA_SOURCE
from memory_store import MemoryEntryStore
from task_store import TaskStore

FIXED_NOW = datetime(2026, 4, 20, 3, 0, tzinfo=timezone.utc)


def _clock() -> datetime:
    return FIXED_NOW


def _make_stores(tmp_path: Path) -> tuple[MemoryEntryStore, TaskStore]:
    memory = MemoryEntryStore(tmp_path / "memory.json")
    tasks = TaskStore(tmp_path / "tasks.json")
    return memory, tasks


class TestGatherEmptyStores:
    def test_empty_returns_empty_bundle(self, tmp_path: Path) -> None:
        memory, tasks = _make_stores(tmp_path)
        bundle = gather_consolidation_context(
            memory, tasks, tmp_path / "session_log.jsonl", _clock,
        )
        assert bundle.recent_memories == []
        assert bundle.resolved_memories == []
        assert bundle.recent_tasks == []
        assert bundle.session_excerpts == []
        assert bundle.current_energy_state is None

    def test_missing_session_log_returns_empty_excerpts(
        self, tmp_path: Path,
    ) -> None:
        memory, tasks = _make_stores(tmp_path)
        bundle = gather_consolidation_context(
            memory, tasks, tmp_path / "absent.jsonl", _clock,
        )
        assert bundle.session_excerpts == []


class TestGatherWindowFilter:
    def test_entry_inside_window_is_recent(self, tmp_path: Path) -> None:
        memory, tasks = _make_stores(tmp_path)
        memory.create_entry("commitment", "finish the report", {})
        bundle = gather_consolidation_context(
            memory, tasks, tmp_path / "sess.jsonl", _clock,
        )
        assert len(bundle.recent_memories) == 1
        assert bundle.recent_memories[0].content == "finish the report"

    def test_entry_outside_window_is_filtered(self, tmp_path: Path) -> None:
        memory, tasks = _make_stores(tmp_path)
        memory.create_entry("commitment", "old one", {})
        # Override created_at manually to fall outside 24h window.
        old_entry = next(iter(memory._entries.values()))
        memory._entries[old_entry.id] = old_entry.model_copy(
            update={"created_at": FIXED_NOW - timedelta(hours=48)},
        )
        bundle = gather_consolidation_context(
            memory, tasks, tmp_path / "sess.jsonl", _clock,
        )
        assert bundle.recent_memories == []

    def test_resolved_inside_window_is_captured(self, tmp_path: Path) -> None:
        memory, tasks = _make_stores(tmp_path)
        entry = memory.create_entry("blocker", "bluescreen", {})
        memory.resolve_entry(entry.id)
        bundle = gather_consolidation_context(
            memory, tasks, tmp_path / "sess.jsonl", _clock,
        )
        assert len(bundle.resolved_memories) == 1
        assert bundle.resolved_memories[0].id == entry.id


class TestGatherSelfFeedbackFilter:
    def test_dream_generated_entry_excluded(self, tmp_path: Path) -> None:
        memory, tasks = _make_stores(tmp_path)
        memory.create_entry(
            "energy_state", "low battery",
            {"source": DREAM_METADATA_SOURCE, "run_at": FIXED_NOW.isoformat()},
        )
        memory.create_entry("energy_state", "wide awake", {})
        bundle = gather_consolidation_context(
            memory, tasks, tmp_path / "sess.jsonl", _clock,
        )
        assert len(bundle.recent_memories) == 1
        assert bundle.recent_memories[0].content == "wide awake"


class TestGatherEnergyState:
    def test_current_energy_state_picks_active_entry(
        self, tmp_path: Path,
    ) -> None:
        memory, tasks = _make_stores(tmp_path)
        memory.create_entry("energy_state", "low after lunch", {})
        bundle = gather_consolidation_context(
            memory, tasks, tmp_path / "sess.jsonl", _clock,
        )
        assert bundle.current_energy_state == "low after lunch"

    def test_no_energy_entry_returns_none(self, tmp_path: Path) -> None:
        memory, tasks = _make_stores(tmp_path)
        memory.create_entry("commitment", "walk the dog", {})
        bundle = gather_consolidation_context(
            memory, tasks, tmp_path / "sess.jsonl", _clock,
        )
        assert bundle.current_energy_state is None


class TestGatherTasks:
    def test_recent_task_included(self, tmp_path: Path) -> None:
        memory, tasks = _make_stores(tmp_path)
        tasks.create_task(
            title="finish dream tests", priority="medium",
            description=None, due_date=None, tags=[],
        )
        bundle = gather_consolidation_context(
            memory, tasks, tmp_path / "sess.jsonl", _clock,
        )
        assert len(bundle.recent_tasks) == 1
        assert bundle.recent_tasks[0].title == "finish dream tests"

    def test_old_task_filtered(self, tmp_path: Path) -> None:
        memory, tasks = _make_stores(tmp_path)
        task = tasks.create_task(
            title="ancient", priority="low", description=None,
            due_date=None, tags=[],
        )
        # Push updated_at outside the 24h window.
        old = task.model_copy(update={"updated_at": FIXED_NOW - timedelta(hours=72)})
        tasks._tasks[task.id] = old
        bundle = gather_consolidation_context(
            memory, tasks, tmp_path / "sess.jsonl", _clock,
        )
        assert bundle.recent_tasks == []


class TestGatherSessionLog:
    def test_valid_jsonl_read_and_filtered(self, tmp_path: Path) -> None:
        memory, tasks = _make_stores(tmp_path)
        log = tmp_path / "sess.jsonl"
        recent_ts = (FIXED_NOW - timedelta(hours=2)).isoformat()
        old_ts = (FIXED_NOW - timedelta(hours=48)).isoformat()
        log.write_text(
            "\n".join([
                f'{{"timestamp": "{recent_ts}", "content": "today chat"}}',
                f'{{"timestamp": "{old_ts}", "content": "older chat"}}',
                '',  # blank line
                'not json',  # malformed
                '{"timestamp": "broken", "content": "x"}',  # bad iso
            ]),
            encoding="utf-8",
        )
        bundle = gather_consolidation_context(memory, tasks, log, _clock)
        assert bundle.session_excerpts == ["today chat"]


class TestGatherClockValidation:
    def test_naive_clock_raises(self, tmp_path: Path) -> None:
        memory, tasks = _make_stores(tmp_path)
        def naive() -> datetime:
            return datetime(2026, 4, 20, 3, 0)
        with pytest.raises(ValueError, match="tz-aware"):
            gather_consolidation_context(
                memory, tasks, tmp_path / "x.jsonl", naive,
            )

    def test_custom_window_honored(self, tmp_path: Path) -> None:
        memory, tasks = _make_stores(tmp_path)
        memory.create_entry("commitment", "recent", {})
        entry = next(iter(memory._entries.values()))
        memory._entries[entry.id] = entry.model_copy(
            update={"created_at": FIXED_NOW - timedelta(hours=10)},
        )
        bundle = gather_consolidation_context(
            memory, tasks, tmp_path / "x.jsonl", _clock, window_hours=6,
        )
        assert bundle.recent_memories == []
        wide = gather_consolidation_context(
            memory, tasks, tmp_path / "x.jsonl", _clock, window_hours=24,
        )
        assert len(wide.recent_memories) == 1
