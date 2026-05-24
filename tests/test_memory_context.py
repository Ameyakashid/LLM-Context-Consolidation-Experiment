"""Unit tests for memory_context.py — formatting and hook behavior."""

import asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import ClassVar

import pytest

from memory_store import MemoryEntry, MemoryEntryStore
from memory_context import (
    ACTIVE_MEMORIES_HEADING,
    DEFAULT_MAX_INJECTED_ENTRIES,
    LONG_TERM_MEMORY_HEADING,
    MemoryContextHook,
    format_memory_entries,
    format_single_entry,
    inject_memories_into_prompt,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _entry(
    category: str,
    content: str,
    metadata: dict[str, str] | None = None,
    minutes_ago: int = 0,
) -> MemoryEntry:
    """Build a MemoryEntry with a controlled timestamp."""
    return MemoryEntry(
        id="abcdef1234567890abcdef1234567890",
        category=category,  # type: ignore[arg-type]
        content=content,
        created_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
        metadata=metadata or {},
    )


class FakeHookContext:
    """Minimal HookContext implementation for tests."""

    def __init__(self, messages: list[dict[str, str]]) -> None:
        self._messages = messages

    @property
    def messages(self) -> list[dict[str, str]]:
        return self._messages


# ---------------------------------------------------------------------------
# format_single_entry
# ---------------------------------------------------------------------------

class TestFormatSingleEntry:

    def test_entry_without_metadata(self) -> None:
        entry = _entry("commitment", "Will finish the report")
        result = format_single_entry(entry)
        assert result == "- [commitment] Will finish the report"

    def test_entry_with_metadata(self) -> None:
        entry = _entry("deadline", "Presentation due", metadata={"due_date": "2026-04-14"})
        result = format_single_entry(entry)
        assert result == "- [deadline] Presentation due (due_date=2026-04-14)"

    def test_entry_with_multiple_metadata_keys(self) -> None:
        entry = _entry(
            "blocker",
            "Waiting on CI",
            metadata={"task_id": "abc123", "source": "standup"},
        )
        result = format_single_entry(entry)
        assert "- [blocker] Waiting on CI (" in result
        assert "task_id=abc123" in result
        assert "source=standup" in result


# ---------------------------------------------------------------------------
# format_memory_entries
# ---------------------------------------------------------------------------

class TestFormatMemoryEntries:

    def test_empty_list_returns_empty_string(self) -> None:
        assert format_memory_entries([]) == ""

    def test_single_entry(self) -> None:
        result = format_memory_entries([_entry("commitment", "Do the thing")])
        assert ACTIVE_MEMORIES_HEADING in result
        assert "- [commitment] Do the thing" in result

    def test_multiple_entries_sorted_by_recency(self) -> None:
        older = _entry("blocker", "Old blocker", minutes_ago=10)
        newer = _entry("deadline", "New deadline", minutes_ago=1)
        result = format_memory_entries([older, newer])
        lines = result.split("\n")
        entry_lines = [l for l in lines if l.startswith("- ")]
        assert "deadline" in entry_lines[0]
        assert "blocker" in entry_lines[1]

    def test_includes_section_heading(self) -> None:
        result = format_memory_entries([_entry("commitment", "X")])
        assert result.startswith(ACTIVE_MEMORIES_HEADING)


# ---------------------------------------------------------------------------
# inject_memories_into_prompt
# ---------------------------------------------------------------------------

class TestInjectMemoriesIntoPrompt:

    SYSTEM_WITH_LTM: ClassVar[str] = (
        "# Identity\n\nYou are a bot.\n\n"
        "## Long-term Memory\n\nSome long-term stuff.\n\n"
        "---\n\n## Skills"
    )

    def test_inject_after_long_term_memory(self) -> None:
        block = "## Active Memories\n\n- [commitment] Do it"
        result = inject_memories_into_prompt(self.SYSTEM_WITH_LTM, block)
        assert "## Active Memories" in result
        # Should appear before the --- separator
        ltm_idx = result.index("## Long-term Memory")
        active_idx = result.index("## Active Memories")
        separator_idx = result.index("---")
        assert ltm_idx < active_idx < separator_idx

    def test_fallback_when_heading_missing(self) -> None:
        system = "# Identity\n\nYou are a bot."
        block = "## Active Memories\n\n- [commitment] Do it"
        result = inject_memories_into_prompt(system, block)
        assert result.endswith(block)

    def test_no_injection_when_block_empty(self) -> None:
        result = inject_memories_into_prompt(self.SYSTEM_WITH_LTM, "")
        assert result == self.SYSTEM_WITH_LTM


# ---------------------------------------------------------------------------
# MemoryContextHook
# ---------------------------------------------------------------------------

class TestMemoryContextHook:

    def _run(self, coro):  # noqa: ANN001, ANN202
        return asyncio.run(coro)

    def test_injects_entries_into_system_prompt(self, tmp_path: Path) -> None:
        store = MemoryEntryStore(storage_path=tmp_path / "mem.json")
        store.create_entry(
            category="commitment",
            content="Finish report",
            metadata={},
        )
        hook = MemoryContextHook(store=store, max_entries=DEFAULT_MAX_INJECTED_ENTRIES)
        ctx = FakeHookContext([
            {"role": "system", "content": "## Long-term Memory\n\nStuff.\n\n---"},
            {"role": "user", "content": "Hello"},
        ])
        self._run(hook.before_iteration(ctx))
        assert "## Active Memories" in ctx.messages[0]["content"]
        assert "Finish report" in ctx.messages[0]["content"]

    def test_no_injection_when_no_active_entries(self, tmp_path: Path) -> None:
        store = MemoryEntryStore(storage_path=tmp_path / "mem.json")
        hook = MemoryContextHook(store=store, max_entries=DEFAULT_MAX_INJECTED_ENTRIES)
        original_content = "## Long-term Memory\n\nStuff."
        ctx = FakeHookContext([
            {"role": "system", "content": original_content},
        ])
        self._run(hook.before_iteration(ctx))
        assert ctx.messages[0]["content"] == original_content

    def test_truncates_to_max_entries(self, tmp_path: Path) -> None:
        store = MemoryEntryStore(storage_path=tmp_path / "mem.json")
        for i in range(10):
            store.create_entry(
                category="commitment",
                content=f"Item {i}",
                metadata={},
            )
        hook = MemoryContextHook(store=store, max_entries=3)
        ctx = FakeHookContext([
            {"role": "system", "content": "## Long-term Memory\n\n---"},
        ])
        self._run(hook.before_iteration(ctx))
        content = ctx.messages[0]["content"]
        entry_lines = [l for l in content.split("\n") if l.startswith("- [")]
        assert len(entry_lines) == 3

    def test_handles_empty_messages_list(self, tmp_path: Path) -> None:
        store = MemoryEntryStore(storage_path=tmp_path / "mem.json")
        hook = MemoryContextHook(store=store, max_entries=DEFAULT_MAX_INJECTED_ENTRIES)
        ctx = FakeHookContext([])
        self._run(hook.before_iteration(ctx))
        assert ctx.messages == []

    def test_handles_non_system_first_message(self, tmp_path: Path) -> None:
        store = MemoryEntryStore(storage_path=tmp_path / "mem.json")
        store.create_entry(category="commitment", content="X", metadata={})
        hook = MemoryContextHook(store=store, max_entries=DEFAULT_MAX_INJECTED_ENTRIES)
        ctx = FakeHookContext([{"role": "user", "content": "Hi"}])
        self._run(hook.before_iteration(ctx))
        assert ctx.messages[0]["content"] == "Hi"

    def test_handles_store_read_failure_gracefully(self, tmp_path: Path) -> None:
        store = MemoryEntryStore(storage_path=tmp_path / "mem.json")
        # Corrupt the internal state to force an error
        store._entries = None  # type: ignore[assignment]
        hook = MemoryContextHook(store=store, max_entries=DEFAULT_MAX_INJECTED_ENTRIES)
        ctx = FakeHookContext([
            {"role": "system", "content": "Original content"},
        ])
        # Should not raise — graceful fallback
        self._run(hook.before_iteration(ctx))
        assert ctx.messages[0]["content"] == "Original content"
