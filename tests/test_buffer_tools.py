"""Tests for nanobot-ai buffer tool wrappers.

Tests cover happy paths, error paths, and registration via async
execute() with a real BufferStore backed by a temp file.
"""

import asyncio
from datetime import date, timedelta
from pathlib import Path

import pytest

from nanobot.agent.tools.registry import ToolRegistry

from buffer_store import BufferStore
from buffer_tools import (
    CreateBufferTool,
    GetBufferStatusTool,
    ListBuffersTool,
    ManualDecrementTool,
    RefillBufferTool,
    register_buffer_tools,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def storage_path(tmp_path: Path) -> Path:
    return tmp_path / "buffers.json"


@pytest.fixture()
def store(storage_path: Path) -> BufferStore:
    return BufferStore(storage_path)


def run(coro):  # noqa: ANN001, ANN201
    """Run an async coroutine synchronously for testing."""
    return asyncio.run(coro)


def _create_buffer(store: BufferStore):  # noqa: ANN201
    """Helper to create a standard test buffer."""
    return store.create_buffer(
        name="Rent",
        buffer_level=3,
        buffer_capacity=4,
        recurrence_interval_days=30,
        next_due_date=date.today() + timedelta(days=15),
        alert_threshold=1,
    )



class TestCreateBufferTool:
    def test_create_with_defaults(self, store: BufferStore) -> None:
        tool = CreateBufferTool(store=store)
        result = run(tool.execute(
            name="Rent",
            capacity=4,
            recurrence_interval_days=30,
            next_due_date="2026-05-01",
        ))
        assert "Buffer created:" in result
        assert "Rent" in result
        buffer = store.list_buffers()[0]
        assert buffer.buffer_level == 4
        assert buffer.alert_threshold == 1

    def test_create_with_explicit_level(self, store: BufferStore) -> None:
        tool = CreateBufferTool(store=store)
        result = run(tool.execute(
            name="Meds",
            capacity=3,
            recurrence_interval_days=7,
            next_due_date="2026-05-01",
            buffer_level=2,
        ))
        assert "Meds" in result
        buffer = store.list_buffers()[0]
        assert buffer.buffer_level == 2

    def test_create_with_explicit_threshold(self, store: BufferStore) -> None:
        tool = CreateBufferTool(store=store)
        run(tool.execute(
            name="Test",
            capacity=5,
            recurrence_interval_days=14,
            next_due_date="2026-05-01",
            alert_threshold=2,
        ))
        buffer = store.list_buffers()[0]
        assert buffer.alert_threshold == 2

    def test_create_invalid_date(self, store: BufferStore) -> None:
        tool = CreateBufferTool(store=store)
        result = run(tool.execute(
            name="Bad",
            capacity=4,
            recurrence_interval_days=30,
            next_due_date="not-a-date",
        ))
        assert result.startswith("Error:")
        assert "Invalid date format" in result
        assert len(store.list_buffers()) == 0

    def test_create_level_exceeds_capacity(self, store: BufferStore) -> None:
        tool = CreateBufferTool(store=store)
        result = run(tool.execute(
            name="Over",
            capacity=3,
            recurrence_interval_days=7,
            next_due_date="2026-05-01",
            buffer_level=5,
        ))
        assert result.startswith("Error:")
        assert len(store.list_buffers()) == 0

    def test_tool_name(self, store: BufferStore) -> None:
        assert CreateBufferTool(store=store).name == "create_buffer"

    def test_schema_has_required_fields(self, store: BufferStore) -> None:
        tool = CreateBufferTool(store=store)
        schema = tool.parameters
        assert "name" in schema["required"]
        assert "capacity" in schema["required"]
        assert "recurrence_interval_days" in schema["required"]
        assert "next_due_date" in schema["required"]


# ---------------------------------------------------------------------------
# ListBuffersTool tests
# ---------------------------------------------------------------------------

class TestListBuffersTool:
    def test_list_empty(self, store: BufferStore) -> None:
        tool = ListBuffersTool(store=store)
        result = run(tool.execute())
        assert result == "No buffers found."

    def test_list_active_default(self, store: BufferStore) -> None:
        _create_buffer(store)
        tool = ListBuffersTool(store=store)
        result = run(tool.execute())
        assert "Rent" in result

    def test_list_by_status(self, store: BufferStore) -> None:
        from buffer_store import BufferUpdate
        buffer = _create_buffer(store)
        store.update_buffer(buffer.id, BufferUpdate(status="paused"))
        store.create_buffer("Active", 2, 3, 7, date.today(), 1)
        tool = ListBuffersTool(store=store)
        result = run(tool.execute(status="paused"))
        assert "Rent" in result
        assert "Active" not in result

    def test_is_read_only(self, store: BufferStore) -> None:
        assert ListBuffersTool(store=store).read_only is True

    def test_tool_name(self, store: BufferStore) -> None:
        assert ListBuffersTool(store=store).name == "list_buffers"


# ---------------------------------------------------------------------------
# GetBufferStatusTool tests
# ---------------------------------------------------------------------------

class TestGetBufferStatusTool:
    def test_get_existing(self, store: BufferStore) -> None:
        buffer = _create_buffer(store)
        tool = GetBufferStatusTool(store=store)
        result = run(tool.execute(buffer_id=buffer.id))
        assert "Rent" in result
        assert buffer.id[:8] in result
        assert "3/4" in result

    def test_get_missing(self, store: BufferStore) -> None:
        tool = GetBufferStatusTool(store=store)
        result = run(tool.execute(buffer_id="nonexistent"))
        assert result.startswith("Error:")
        assert "not found" in result
        assert "list_buffers" in result

    def test_is_read_only(self, store: BufferStore) -> None:
        assert GetBufferStatusTool(store=store).read_only is True

    def test_tool_name(self, store: BufferStore) -> None:
        assert GetBufferStatusTool(store=store).name == "get_buffer_status"


# ---------------------------------------------------------------------------
# RefillBufferTool tests
# ---------------------------------------------------------------------------

class TestRefillBufferTool:
    def test_refill(self, store: BufferStore) -> None:
        buffer = store.create_buffer("Fill", 1, 4, 7, date.today(), 1)
        tool = RefillBufferTool(store=store)
        result = run(tool.execute(buffer_id=buffer.id, units=2))
        assert "Buffer refilled:" in result
        assert "3/4" in result

    def test_refill_capped_at_capacity(self, store: BufferStore) -> None:
        buffer = store.create_buffer("Cap", 3, 4, 7, date.today(), 1)
        tool = RefillBufferTool(store=store)
        result = run(tool.execute(buffer_id=buffer.id, units=10))
        assert "4/4" in result

    def test_refill_missing_buffer(self, store: BufferStore) -> None:
        tool = RefillBufferTool(store=store)
        result = run(tool.execute(buffer_id="nonexistent", units=1))
        assert result.startswith("Error:")
        assert "not found" in result

    def test_refill_zero_units(self, store: BufferStore) -> None:
        buffer = _create_buffer(store)
        tool = RefillBufferTool(store=store)
        result = run(tool.execute(buffer_id=buffer.id, units=0))
        assert result.startswith("Error:")

    def test_tool_name(self, store: BufferStore) -> None:
        assert RefillBufferTool(store=store).name == "refill_buffer"

    def test_schema_requires_fields(self, store: BufferStore) -> None:
        tool = RefillBufferTool(store=store)
        assert "buffer_id" in tool.parameters["required"]
        assert "units" in tool.parameters["required"]


# ---------------------------------------------------------------------------
# ManualDecrementTool tests
# ---------------------------------------------------------------------------

class TestManualDecrementTool:
    def test_decrement(self, store: BufferStore) -> None:
        buffer = _create_buffer(store)
        tool = ManualDecrementTool(store=store)
        result = run(tool.execute(buffer_id=buffer.id))
        assert "Buffer decremented:" in result
        assert "2/4" in result

    def test_decrement_at_zero(self, store: BufferStore) -> None:
        buffer = store.create_buffer("Empty", 0, 4, 7, date.today(), 1)
        tool = ManualDecrementTool(store=store)
        result = run(tool.execute(buffer_id=buffer.id))
        assert result.startswith("Error:")

    def test_decrement_missing_buffer(self, store: BufferStore) -> None:
        tool = ManualDecrementTool(store=store)
        result = run(tool.execute(buffer_id="nonexistent"))
        assert result.startswith("Error:")
        assert "not found" in result

    def test_tool_name(self, store: BufferStore) -> None:
        assert ManualDecrementTool(store=store).name == "manual_decrement"

    def test_schema_requires_buffer_id(self, store: BufferStore) -> None:
        tool = ManualDecrementTool(store=store)
        assert "buffer_id" in tool.parameters["required"]


# ---------------------------------------------------------------------------
# Registration tests
# ---------------------------------------------------------------------------

class TestRegisterBufferTools:
    def test_registers_all_five_tools(self, store: BufferStore) -> None:
        registry = ToolRegistry()
        count = register_buffer_tools(registry, store)
        assert count == 5
        assert len(registry) == 5
        for tool_name in ["create_buffer", "list_buffers", "get_buffer_status", "refill_buffer", "manual_decrement"]:
            assert registry.has(tool_name), f"Missing tool: {tool_name}"

    def test_tools_produce_valid_schemas(self, store: BufferStore) -> None:
        registry = ToolRegistry()
        register_buffer_tools(registry, store)
        definitions = registry.get_definitions()
        assert len(definitions) == 5
        for defn in definitions:
            assert defn["type"] == "function"
            func = defn["function"]
            assert "name" in func
            assert "description" in func
            assert "parameters" in func
            assert func["parameters"]["type"] == "object"

    def test_execute_via_registry(self, store: BufferStore) -> None:
        registry = ToolRegistry()
        register_buffer_tools(registry, store)
        result = run(registry.execute("create_buffer", {
            "name": "Via registry",
            "capacity": 4,
            "recurrence_interval_days": 30,
            "next_due_date": "2026-05-01",
        }))
        assert "Buffer created:" in result
        assert "Via registry" in result
