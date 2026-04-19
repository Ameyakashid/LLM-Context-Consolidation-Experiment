"""Tests for nanobot-ai memory tool wrappers.

Each tool is tested via its async execute() method with a real
MemoryEntryStore backed by a temp file. Tests cover happy paths
and error paths.
"""

import asyncio
from pathlib import Path

import pytest

from nanobot.agent.tools.registry import ToolRegistry

from memory_store import MemoryEntryStore
from memory_tools import (
    DismissMemoryTool,
    ListMemoriesTool,
    SaveMemoryTool,
    format_memory_entry,
    format_memory_list,
    register_memory_tools,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def storage_path(tmp_path: Path) -> Path:
    return tmp_path / "memories.json"


@pytest.fixture()
def store(storage_path: Path) -> MemoryEntryStore:
    return MemoryEntryStore(storage_path)


def run(coro):  # noqa: ANN001, ANN201
    """Run an async coroutine synchronously for testing."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Pure helper tests
# ---------------------------------------------------------------------------

class TestFormatMemoryEntry:
    def test_minimal_entry(self, store: MemoryEntryStore) -> None:
        entry = store.create_entry("commitment", "Call dentist", {})
        result = format_memory_entry(entry)
        assert entry.id[:8] in result
        assert "commitment" in result
        assert "Call dentist" in result
        assert "Created:" in result
        assert "Metadata:" not in result

    def test_entry_with_metadata(self, store: MemoryEntryStore) -> None:
        entry = store.create_entry("deadline", "Submit report", {"due_date": "2026-04-15"})
        result = format_memory_entry(entry)
        assert "deadline" in result
        assert "Submit report" in result
        assert "Metadata:" in result
        assert "due_date=2026-04-15" in result

    def test_resolved_entry_shows_resolved_at(self, store: MemoryEntryStore) -> None:
        entry = store.create_entry("blocker", "Waiting on API key", {})
        resolved = store.resolve_entry(entry.id)
        result = format_memory_entry(resolved)
        assert "Resolved:" in result


class TestFormatMemoryList:
    def test_empty_list(self) -> None:
        assert format_memory_list([]) == "No active memories."

    def test_multiple_entries(self, store: MemoryEntryStore) -> None:
        store.create_entry("commitment", "Entry A", {})
        store.create_entry("blocker", "Entry B", {})
        result = format_memory_list(store.list_active_entries())
        assert "Entry A" in result
        assert "Entry B" in result


# ---------------------------------------------------------------------------
# SaveMemoryTool tests
# ---------------------------------------------------------------------------

class TestSaveMemoryTool:
    def test_save_commitment(self, store: MemoryEntryStore) -> None:
        tool = SaveMemoryTool(store=store)
        result = run(tool.execute(category="commitment", content="Call dentist"))
        assert "Memory saved:" in result
        assert "commitment" in result
        assert "Call dentist" in result
        assert len(store.list_active_entries()) == 1

    def test_save_deadline(self, store: MemoryEntryStore) -> None:
        tool = SaveMemoryTool(store=store)
        result = run(tool.execute(category="deadline", content="Report due Friday"))
        assert "deadline" in result
        assert "Report due Friday" in result

    def test_save_blocker(self, store: MemoryEntryStore) -> None:
        tool = SaveMemoryTool(store=store)
        result = run(tool.execute(category="blocker", content="Waiting on API key"))
        assert "blocker" in result

    def test_save_energy_state(self, store: MemoryEntryStore) -> None:
        tool = SaveMemoryTool(store=store)
        result = run(tool.execute(category="energy_state", content="Low energy after lunch"))
        assert "energy_state" in result

    def test_save_context_switch(self, store: MemoryEntryStore) -> None:
        tool = SaveMemoryTool(store=store)
        result = run(tool.execute(category="context_switch", content="Switched from coding to email"))
        assert "context_switch" in result

    def test_save_with_metadata(self, store: MemoryEntryStore) -> None:
        tool = SaveMemoryTool(store=store)
        result = run(tool.execute(
            category="deadline",
            content="Submit report",
            metadata={"due_date": "2026-04-15", "source": "manager"},
        ))
        assert "Metadata:" in result
        assert "due_date=2026-04-15" in result
        assert "source=manager" in result

    def test_tool_name(self, store: MemoryEntryStore) -> None:
        assert SaveMemoryTool(store=store).name == "save_memory"

    def test_schema_has_required_fields(self, store: MemoryEntryStore) -> None:
        tool = SaveMemoryTool(store=store)
        schema = tool.parameters
        assert "category" in schema["properties"]
        assert "content" in schema["properties"]
        assert "category" in schema["required"]
        assert "content" in schema["required"]


# ---------------------------------------------------------------------------
# ListMemoriesTool tests
# ---------------------------------------------------------------------------

class TestListMemoriesTool:
    def test_list_empty(self, store: MemoryEntryStore) -> None:
        tool = ListMemoriesTool(store=store)
        result = run(tool.execute())
        assert result == "No active memories."

    def test_list_all_active(self, store: MemoryEntryStore) -> None:
        store.create_entry("commitment", "Entry A", {})
        store.create_entry("blocker", "Entry B", {})
        tool = ListMemoriesTool(store=store)
        result = run(tool.execute())
        assert "Entry A" in result
        assert "Entry B" in result

    def test_list_by_category(self, store: MemoryEntryStore) -> None:
        store.create_entry("commitment", "Keep this", {})
        store.create_entry("blocker", "Filter me out", {})
        tool = ListMemoriesTool(store=store)
        result = run(tool.execute(category="commitment"))
        assert "Keep this" in result
        assert "Filter me out" not in result

    def test_list_excludes_resolved(self, store: MemoryEntryStore) -> None:
        entry = store.create_entry("commitment", "Resolved one", {})
        store.resolve_entry(entry.id)
        store.create_entry("commitment", "Active one", {})
        tool = ListMemoriesTool(store=store)
        result = run(tool.execute())
        assert "Active one" in result
        assert "Resolved one" not in result

    def test_is_read_only(self, store: MemoryEntryStore) -> None:
        assert ListMemoriesTool(store=store).read_only is True

    def test_tool_name(self, store: MemoryEntryStore) -> None:
        assert ListMemoriesTool(store=store).name == "list_memories"


# ---------------------------------------------------------------------------
# DismissMemoryTool tests
# ---------------------------------------------------------------------------

class TestDismissMemoryTool:
    def test_dismiss_existing(self, store: MemoryEntryStore) -> None:
        entry = store.create_entry("blocker", "Unblock me", {})
        tool = DismissMemoryTool(store=store)
        result = run(tool.execute(entry_id=entry.id))
        assert "Memory dismissed:" in result
        assert "Unblock me" in result
        assert "Resolved:" in result
        assert len(store.list_active_entries()) == 0

    def test_dismiss_missing_returns_error(self, store: MemoryEntryStore) -> None:
        tool = DismissMemoryTool(store=store)
        result = run(tool.execute(entry_id="nonexistent"))
        assert result.startswith("Error:")
        assert "not found" in result
        assert "list_memories" in result

    def test_tool_name(self, store: MemoryEntryStore) -> None:
        assert DismissMemoryTool(store=store).name == "dismiss_memory"

    def test_schema_requires_entry_id(self, store: MemoryEntryStore) -> None:
        tool = DismissMemoryTool(store=store)
        assert "entry_id" in tool.parameters["required"]


# ---------------------------------------------------------------------------
# Registration tests
# ---------------------------------------------------------------------------

class TestRegisterMemoryTools:
    def test_registers_all_three_tools(self, store: MemoryEntryStore) -> None:
        registry = ToolRegistry()
        count = register_memory_tools(registry, store)
        assert count == 3
        assert len(registry) == 3
        for tool_name in ["save_memory", "list_memories", "dismiss_memory"]:
            assert registry.has(tool_name), f"Missing tool: {tool_name}"

    def test_tools_produce_valid_schemas(self, store: MemoryEntryStore) -> None:
        registry = ToolRegistry()
        register_memory_tools(registry, store)
        definitions = registry.get_definitions()
        assert len(definitions) == 3
        for defn in definitions:
            assert defn["type"] == "function"
            func = defn["function"]
            assert "name" in func
            assert "description" in func
            assert "parameters" in func
            assert func["parameters"]["type"] == "object"

    def test_execute_via_registry(self, store: MemoryEntryStore) -> None:
        registry = ToolRegistry()
        register_memory_tools(registry, store)
        result = run(registry.execute(
            "save_memory",
            {"category": "commitment", "content": "Via registry"},
        ))
        assert "Memory saved:" in result
        assert "Via registry" in result
