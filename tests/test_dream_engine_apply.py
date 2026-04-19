"""Apply-phase tests — Dream output writes to MemoryEntryStore correctly."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from dream_engine import DreamEngine
from dream_types import (
    DREAM_METADATA_SOURCE,
    CandidateInsight,
    DreamConsolidationOutput,
)
from memory_store import MemoryEntryStore
from task_store import TaskStore

FIXED_NOW = datetime(2026, 4, 20, 3, 0, tzinfo=timezone.utc)


def _clock() -> datetime:
    return FIXED_NOW


def _make_engine(tmp_path: Path) -> tuple[DreamEngine, MemoryEntryStore]:
    memory = MemoryEntryStore(tmp_path / "memory.json")
    tasks = TaskStore(tmp_path / "tasks.json")

    async def stub_llm(prompt: str, tokens: int) -> str:
        return "{}"

    engine = DreamEngine(
        memory_store=memory,
        task_store=tasks,
        session_log_path=tmp_path / "sess.jsonl",
        llm_caller=stub_llm,
        clock=_clock,
        prompt_template="unused",
    )
    return engine, memory


def _output(
    insights: list[CandidateInsight] | None = None,
    resolves: list[str] | None = None,
) -> DreamConsolidationOutput:
    return DreamConsolidationOutput(
        insights=insights or [],
        resolves=resolves or [],
        dropped=[],
    )


class TestApplyCreatesEntries:
    def test_single_insight_written(self, tmp_path: Path) -> None:
        engine, memory = _make_engine(tmp_path)
        output = _output(insights=[CandidateInsight(
            category="commitment",
            content="finish the report",
            metadata={"confidence": "high"},
            supersedes_id="",
        )])
        created, resolved = engine._apply(output)
        assert created == 1
        assert resolved == 0
        entries = memory.list_active_entries()
        assert len(entries) == 1
        assert entries[0].content == "finish the report"

    def test_dream_metadata_stamped(self, tmp_path: Path) -> None:
        engine, memory = _make_engine(tmp_path)
        output = _output(insights=[CandidateInsight(
            category="commitment",
            content="ship it",
            metadata={"confidence": "high"},
            supersedes_id="",
        )])
        engine._apply(output)
        entry = memory.list_active_entries()[0]
        assert entry.metadata["source"] == DREAM_METADATA_SOURCE
        assert entry.metadata["run_at"] == FIXED_NOW.isoformat()
        assert entry.metadata["confidence"] == "high"

    def test_supersedes_id_preserved(self, tmp_path: Path) -> None:
        engine, memory = _make_engine(tmp_path)
        output = _output(insights=[CandidateInsight(
            category="commitment",
            content="follow up",
            metadata={},
            supersedes_id="old-abc",
        )])
        engine._apply(output)
        entry = memory.list_active_entries()[0]
        assert entry.metadata["supersedes"] == "old-abc"


class TestApplyIdempotent:
    def test_duplicate_insight_not_rewritten(self, tmp_path: Path) -> None:
        engine, memory = _make_engine(tmp_path)
        output = _output(insights=[CandidateInsight(
            category="commitment",
            content="the same thing",
            metadata={},
            supersedes_id="",
        )])
        first_created, _ = engine._apply(output)
        second_created, _ = engine._apply(output)
        assert first_created == 1
        assert second_created == 0
        assert len(memory.list_active_entries()) == 1

    def test_different_category_with_same_content_inserted(self, tmp_path: Path) -> None:
        engine, memory = _make_engine(tmp_path)
        output = _output(insights=[
            CandidateInsight(
                category="commitment", content="check in",
                metadata={}, supersedes_id="",
            ),
            CandidateInsight(
                category="blocker", content="check in",
                metadata={}, supersedes_id="",
            ),
        ])
        created, _ = engine._apply(output)
        assert created == 2
        assert len(memory.list_active_entries()) == 2


class TestApplyResolves:
    def test_resolve_known_id(self, tmp_path: Path) -> None:
        engine, memory = _make_engine(tmp_path)
        existing = memory.create_entry("blocker", "ugh", {})
        created, resolved = engine._apply(_output(resolves=[existing.id]))
        assert created == 0
        assert resolved == 1
        refreshed = memory.get_entry(existing.id)
        assert refreshed.resolved_at is not None

    def test_resolve_unknown_id_skipped(self, tmp_path: Path) -> None:
        engine, _ = _make_engine(tmp_path)
        created, resolved = engine._apply(_output(resolves=["nonexistent"]))
        assert created == 0
        assert resolved == 0


class TestApplyIntegration:
    def test_full_output_round_trip(self, tmp_path: Path) -> None:
        engine, memory = _make_engine(tmp_path)
        existing = memory.create_entry("blocker", "stuck on audio", {})
        output = _output(
            insights=[CandidateInsight(
                category="energy_state",
                content="afternoons are low focus",
                metadata={},
                supersedes_id="",
            )],
            resolves=[existing.id],
        )
        created, resolved = engine._apply(output)
        assert created == 1
        assert resolved == 1
        actives = memory.list_active_entries()
        assert len(actives) == 1
        assert actives[0].category == "energy_state"


def test_apply_via_run_preserves_metadata(tmp_path: Path) -> None:
    """Sanity check that .run() produces the same metadata surface."""
    memory = MemoryEntryStore(tmp_path / "memory.json")
    tasks = TaskStore(tmp_path / "tasks.json")

    async def fake_llm(prompt: str, tokens: int) -> str:
        return (
            '{"insights": [{"category": "commitment", "content": "done run",'
            ' "metadata": {}, "supersedes_id": ""}],'
            ' "entries_to_resolve": []}'
        )

    engine = DreamEngine(
        memory_store=memory,
        task_store=tasks,
        session_log_path=tmp_path / "sess.jsonl",
        llm_caller=fake_llm,
        clock=_clock,
        prompt_template="unused",
    )
    result = asyncio.run(engine.run())
    assert result.entries_created == 1
    assert memory.list_active_entries()[0].metadata["source"] == DREAM_METADATA_SOURCE
