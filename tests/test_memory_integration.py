"""Integration tests — memory store + context hook working together."""

import asyncio
from pathlib import Path

import pytest

from memory_store import MemoryEntryStore
from memory_context import (
    DEFAULT_MAX_INJECTED_ENTRIES,
    MemoryContextHook,
)

try:
    from memory_tools import DismissMemoryTool, SaveMemoryTool
    HAS_NANOBOT = True
except ImportError:
    HAS_NANOBOT = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeHookContext:
    """Minimal HookContext for integration tests."""

    def __init__(self, messages: list[dict[str, str]]) -> None:
        self._messages = messages

    @property
    def messages(self) -> list[dict[str, str]]:
        return self._messages


def _system_prompt() -> str:
    return (
        "# Identity\n\nYou are a bot.\n\n"
        "## Long-term Memory\n\nPersisted notes.\n\n"
        "---\n\n## Skills\n\nNone."
    )


def _run(coro):  # noqa: ANN001, ANN202
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestMemoryIntegration:

    def test_store_entries_appear_in_hook_prompt(self, tmp_path: Path) -> None:
        store = MemoryEntryStore(storage_path=tmp_path / "mem.json")
        store.create_entry(category="commitment", content="Review PR by noon", metadata={})
        store.create_entry(category="blocker", content="Waiting on API key", metadata={"source": "standup"})

        hook = MemoryContextHook(store=store, max_entries=DEFAULT_MAX_INJECTED_ENTRIES)
        ctx = FakeHookContext([{"role": "system", "content": _system_prompt()}])
        _run(hook.before_iteration(ctx))

        content = ctx.messages[0]["content"]
        assert "## Active Memories" in content
        assert "Review PR by noon" in content
        assert "Waiting on API key" in content
        assert "source=standup" in content

    def test_resolved_entries_excluded_from_injection(self, tmp_path: Path) -> None:
        store = MemoryEntryStore(storage_path=tmp_path / "mem.json")
        store.create_entry(category="commitment", content="Active one", metadata={})
        resolved = store.create_entry(category="deadline", content="Done one", metadata={})
        store.resolve_entry(resolved.id)

        hook = MemoryContextHook(store=store, max_entries=DEFAULT_MAX_INJECTED_ENTRIES)
        ctx = FakeHookContext([{"role": "system", "content": _system_prompt()}])
        _run(hook.before_iteration(ctx))

        content = ctx.messages[0]["content"]
        assert "Active one" in content
        assert "Done one" not in content

    @pytest.mark.skipif(not HAS_NANOBOT, reason="nanobot not installed")
    def test_tools_and_context_round_trip(self, tmp_path: Path) -> None:
        store = MemoryEntryStore(storage_path=tmp_path / "mem.json")
        save_tool = SaveMemoryTool(store=store)  # type: ignore[name-defined]
        dismiss_tool = DismissMemoryTool(store=store)  # type: ignore[name-defined]
        hook = MemoryContextHook(store=store, max_entries=DEFAULT_MAX_INJECTED_ENTRIES)

        # Save via tool
        result = _run(save_tool.execute(
            category="blocker",
            content="CI pipeline broken",
            metadata=None,
        ))
        assert "CI pipeline broken" in result

        # Verify it appears in hook output
        ctx = FakeHookContext([{"role": "system", "content": _system_prompt()}])
        _run(hook.before_iteration(ctx))
        assert "CI pipeline broken" in ctx.messages[0]["content"]

        # Dismiss via tool
        entry_id = store.list_active_entries()[0].id
        dismiss_result = _run(dismiss_tool.execute(entry_id=entry_id))
        assert "dismissed" in dismiss_result.lower()

        # Verify dismissed entry gone from hook output
        ctx2 = FakeHookContext([{"role": "system", "content": _system_prompt()}])
        _run(hook.before_iteration(ctx2))
        assert "CI pipeline broken" not in ctx2.messages[0]["content"]

    def test_store_and_hook_round_trip_without_tools(self, tmp_path: Path) -> None:
        """Same as tools round-trip but uses store directly — always runs."""
        store = MemoryEntryStore(storage_path=tmp_path / "mem.json")
        hook = MemoryContextHook(store=store, max_entries=DEFAULT_MAX_INJECTED_ENTRIES)

        entry = store.create_entry(category="blocker", content="CI broken", metadata={})

        ctx = FakeHookContext([{"role": "system", "content": _system_prompt()}])
        _run(hook.before_iteration(ctx))
        assert "CI broken" in ctx.messages[0]["content"]

        store.resolve_entry(entry.id)

        ctx2 = FakeHookContext([{"role": "system", "content": _system_prompt()}])
        _run(hook.before_iteration(ctx2))
        assert "CI broken" not in ctx2.messages[0]["content"]

    def test_category_ordering_in_context(self, tmp_path: Path) -> None:
        store = MemoryEntryStore(storage_path=tmp_path / "mem.json")
        categories = ["commitment", "deadline", "blocker", "energy_state", "context_switch"]
        for cat in categories:
            store.create_entry(category=cat, content=f"Entry for {cat}", metadata={})

        hook = MemoryContextHook(store=store, max_entries=DEFAULT_MAX_INJECTED_ENTRIES)
        ctx = FakeHookContext([{"role": "system", "content": _system_prompt()}])
        _run(hook.before_iteration(ctx))

        content = ctx.messages[0]["content"]
        for cat in categories:
            assert f"[{cat}]" in content

    def test_max_entries_truncation_integration(self, tmp_path: Path) -> None:
        store = MemoryEntryStore(storage_path=tmp_path / "mem.json")
        for i in range(25):
            store.create_entry(category="commitment", content=f"Entry {i}", metadata={})

        hook = MemoryContextHook(store=store, max_entries=20)
        ctx = FakeHookContext([{"role": "system", "content": _system_prompt()}])
        _run(hook.before_iteration(ctx))

        content = ctx.messages[0]["content"]
        entry_lines = [l for l in content.split("\n") if l.startswith("- [")]
        assert len(entry_lines) == 20
