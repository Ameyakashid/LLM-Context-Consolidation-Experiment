"""End-to-end orchestration tests for DreamEngine.run()."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from datetime import datetime, timezone
from pathlib import Path
from typing import TypeVar

import pytest

from dream_engine import DreamEngine
from dream_types import DreamRunResult, DreamState
from memory_store import MemoryEntryStore
from task_store import TaskStore

FIXED_NOW = datetime(2026, 4, 20, 3, 0, tzinfo=timezone.utc)

T = TypeVar("T")


def _run(coro: Coroutine[object, object, T]) -> T:
    return asyncio.run(coro)


def _clock() -> datetime:
    return FIXED_NOW


def _naive_clock() -> datetime:
    return datetime(2026, 4, 20, 3, 0)


def _build_engine(
    tmp_path: Path,
    llm_response: str,
    *,
    fail_with: Exception | None = None,
) -> tuple[DreamEngine, MemoryEntryStore]:
    memory = MemoryEntryStore(tmp_path / "memory.json")
    tasks = TaskStore(tmp_path / "tasks.json")

    async def llm(prompt: str, tokens: int) -> str:
        if fail_with is not None:
            raise fail_with
        return llm_response

    engine = DreamEngine(
        memory_store=memory,
        task_store=tasks,
        session_log_path=tmp_path / "sess.jsonl",
        llm_caller=llm,
        clock=_clock,
        prompt_template="unused",
    )
    return engine, memory


class TestInitialState:
    def test_engine_starts_idle(self, tmp_path: Path) -> None:
        engine, _ = _build_engine(tmp_path, "{}")
        assert engine.get_state() == DreamState.IDLE

    def test_naive_clock_rejected_at_construction(self, tmp_path: Path) -> None:
        memory = MemoryEntryStore(tmp_path / "memory.json")
        tasks = TaskStore(tmp_path / "tasks.json")

        async def llm(prompt: str, tokens: int) -> str:
            return "{}"

        with pytest.raises(ValueError, match="tz-aware"):
            DreamEngine(
                memory_store=memory,
                task_store=tasks,
                session_log_path=tmp_path / "x.jsonl",
                llm_caller=llm,
                clock=_naive_clock,
                prompt_template="unused",
            )


class TestHappyPath:
    def test_run_transitions_to_complete(self, tmp_path: Path) -> None:
        payload = (
            '{"insights": [{"category": "commitment", "content": "run done",'
            ' "metadata": {}, "supersedes_id": ""}],'
            ' "entries_to_resolve": []}'
        )
        engine, memory = _build_engine(tmp_path, payload)
        result: DreamRunResult = _run(engine.run())
        assert result.state == DreamState.COMPLETE
        assert engine.get_state() == DreamState.COMPLETE
        assert result.entries_created == 1
        assert result.entries_resolved == 0
        assert result.error is None
        assert len(memory.list_active_entries()) == 1

    def test_run_records_token_estimates(self, tmp_path: Path) -> None:
        engine, _ = _build_engine(
            tmp_path, '{"insights": [], "entries_to_resolve": []}',
        )
        result = _run(engine.run())
        assert result.prompt_tokens_est > 0
        assert result.completion_tokens >= 0


class TestSadPath:
    def test_malformed_response_marks_failed(self, tmp_path: Path) -> None:
        engine, _ = _build_engine(tmp_path, "not json!")
        result = _run(engine.run())
        assert result.state == DreamState.FAILED
        assert engine.get_state() == DreamState.FAILED
        assert result.error is not None
        assert "DreamParseError" in result.error

    def test_llm_exception_marks_failed(self, tmp_path: Path) -> None:
        engine, _ = _build_engine(
            tmp_path, "{}", fail_with=RuntimeError("network down"),
        )
        result = _run(engine.run())
        assert result.state == DreamState.FAILED
        assert result.error is not None
        assert "RuntimeError" in result.error
        assert "network down" in result.error


class TestStateTransitions:
    def test_cannot_run_twice_without_reset(self, tmp_path: Path) -> None:
        engine, _ = _build_engine(
            tmp_path, '{"insights": [], "entries_to_resolve": []}',
        )
        _run(engine.run())
        with pytest.raises(RuntimeError, match="state=IDLE"):
            _run(engine.run())

    def test_reset_state_allows_rerun(self, tmp_path: Path) -> None:
        engine, _ = _build_engine(
            tmp_path, '{"insights": [], "entries_to_resolve": []}',
        )
        _run(engine.run())
        engine.reset_state()
        assert engine.get_state() == DreamState.IDLE
        second = _run(engine.run())
        assert second.state == DreamState.COMPLETE

    def test_cannot_run_after_failure_without_reset(self, tmp_path: Path) -> None:
        engine, _ = _build_engine(tmp_path, "garbage")
        _run(engine.run())
        assert engine.get_state() == DreamState.FAILED
        with pytest.raises(RuntimeError, match="state=IDLE"):
            _run(engine.run())
