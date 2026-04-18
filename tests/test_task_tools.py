"""Tests for nanobot-ai task tool wrappers.

Each tool is tested via its async execute() method with a real TaskStore
backed by a temp file. Tests cover happy paths and error paths.
Registry-wiring tests live in test_task_tools_registry.py.
"""

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

from task_store import TaskStore
from task_tools import (
    CompleteTaskTool,
    CreateTaskTool,
    GetTaskTool,
    ListTasksTool,
    UpdateTaskTool,
    format_task,
    format_task_list,
    parse_iso_date,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def storage_path(tmp_path: Path) -> Path:
    return tmp_path / "tasks.json"


@pytest.fixture()
def store(storage_path: Path) -> TaskStore:
    return TaskStore(storage_path)


def run(coro):  # noqa: ANN001, ANN201
    """Run an async coroutine synchronously for testing."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Pure helper tests
# ---------------------------------------------------------------------------

class TestFormatTask:
    def test_minimal_task(self, store: TaskStore) -> None:
        task = store.create_task("Buy milk", "low", None, None, [])
        result = format_task(task)
        assert "Buy milk" in result
        assert "low" in result
        assert "pending" in result

    def test_full_task(self, store: TaskStore) -> None:
        due = datetime(2025, 12, 31, tzinfo=timezone.utc)
        task = store.create_task("Ship it", "high", "Deploy v2", due, ["release", "urgent"])
        result = format_task(task)
        assert "Ship it" in result
        assert "Deploy v2" in result
        assert "2025-12-31" in result
        assert "release" in result
        assert "urgent" in result


class TestFormatTaskList:
    def test_empty_list(self) -> None:
        assert format_task_list([]) == "No tasks found."

    def test_multiple_tasks(self, store: TaskStore) -> None:
        store.create_task("Task A", "low", None, None, [])
        store.create_task("Task B", "high", None, None, [])
        result = format_task_list(store.list_tasks())
        assert "Task A" in result
        assert "Task B" in result


class TestParseIsoDate:
    def test_date_only(self) -> None:
        result = parse_iso_date("2025-12-31")
        assert result.year == 2025
        assert result.month == 12
        assert result.day == 31
        assert result.tzinfo == timezone.utc

    def test_datetime_with_tz(self) -> None:
        result = parse_iso_date("2025-06-15T10:30:00+00:00")
        assert result.hour == 10
        assert result.minute == 30

    def test_invalid_format_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid date format"):
            parse_iso_date("not-a-date")


# ---------------------------------------------------------------------------
# CreateTaskTool tests
# ---------------------------------------------------------------------------

class TestCreateTaskTool:
    def test_create_minimal(self, store: TaskStore) -> None:
        tool = CreateTaskTool(store=store)
        result = run(tool.execute(title="Buy milk", priority="low"))
        assert "Task created:" in result
        assert "Buy milk" in result
        assert len(store.list_tasks()) == 1

    def test_create_full(self, store: TaskStore) -> None:
        tool = CreateTaskTool(store=store)
        result = run(tool.execute(
            title="Deploy",
            priority="high",
            description="Push to prod",
            due_date="2025-12-31",
            tags=["release"],
        ))
        assert "Deploy" in result
        assert "Push to prod" in result
        task = store.list_tasks()[0]
        assert task.due_date is not None
        assert task.tags == ["release"]

    def test_create_invalid_date(self, store: TaskStore) -> None:
        tool = CreateTaskTool(store=store)
        result = run(tool.execute(title="Bad date", priority="low", due_date="nope"))
        assert result.startswith("Error:")
        assert "could not parse time phrase" in result
        assert len(store.list_tasks()) == 0

    def test_tool_name(self, store: TaskStore) -> None:
        assert CreateTaskTool(store=store).name == "create_task"

    def test_schema_has_required_fields(self, store: TaskStore) -> None:
        tool = CreateTaskTool(store=store)
        schema = tool.parameters
        assert "title" in schema["properties"]
        assert "priority" in schema["properties"]
        assert "title" in schema["required"]
        assert "priority" in schema["required"]


# ---------------------------------------------------------------------------
# ListTasksTool tests
# ---------------------------------------------------------------------------

class TestListTasksTool:
    def test_list_empty(self, store: TaskStore) -> None:
        tool = ListTasksTool(store=store)
        result = run(tool.execute())
        assert result == "No tasks found."

    def test_list_all(self, store: TaskStore) -> None:
        store.create_task("A", "low", None, None, [])
        store.create_task("B", "high", None, None, [])
        tool = ListTasksTool(store=store)
        result = run(tool.execute())
        assert "A" in result
        assert "B" in result

    def test_list_by_status(self, store: TaskStore) -> None:
        store.create_task("Pending one", "low", None, None, [])
        task = store.create_task("Done one", "low", None, None, [])
        store.mark_complete(task.id)
        tool = ListTasksTool(store=store)
        result = run(tool.execute(status="done"))
        assert "Done one" in result
        assert "Pending one" not in result

    def test_is_read_only(self, store: TaskStore) -> None:
        assert ListTasksTool(store=store).read_only is True

    def test_tool_name(self, store: TaskStore) -> None:
        assert ListTasksTool(store=store).name == "list_tasks"


# ---------------------------------------------------------------------------
# GetTaskTool tests
# ---------------------------------------------------------------------------

class TestGetTaskTool:
    def test_get_existing(self, store: TaskStore) -> None:
        task = store.create_task("Find me", "medium", None, None, [])
        tool = GetTaskTool(store=store)
        result = run(tool.execute(task_id=task.id))
        assert "Find me" in result
        assert task.id[:8] in result

    def test_get_missing(self, store: TaskStore) -> None:
        tool = GetTaskTool(store=store)
        result = run(tool.execute(task_id="nonexistent"))
        assert result.startswith("Error:")
        assert "not found" in result

    def test_is_read_only(self, store: TaskStore) -> None:
        assert GetTaskTool(store=store).read_only is True

    def test_tool_name(self, store: TaskStore) -> None:
        assert GetTaskTool(store=store).name == "get_task"


# ---------------------------------------------------------------------------
# UpdateTaskTool tests
# ---------------------------------------------------------------------------

class TestUpdateTaskTool:
    def test_update_title(self, store: TaskStore) -> None:
        task = store.create_task("Old title", "low", None, None, [])
        tool = UpdateTaskTool(store=store)
        result = run(tool.execute(task_id=task.id, title="New title"))
        assert "Task updated:" in result
        assert "New title" in result

    def test_update_status(self, store: TaskStore) -> None:
        task = store.create_task("WIP", "low", None, None, [])
        tool = UpdateTaskTool(store=store)
        result = run(tool.execute(task_id=task.id, status="in_progress"))
        assert "in_progress" in result

    def test_update_due_date(self, store: TaskStore) -> None:
        task = store.create_task("Dated", "low", None, None, [])
        tool = UpdateTaskTool(store=store)
        result = run(tool.execute(task_id=task.id, due_date="2025-06-15"))
        assert "2025-06-15" in result

    def test_update_invalid_date(self, store: TaskStore) -> None:
        task = store.create_task("Dated", "low", None, None, [])
        tool = UpdateTaskTool(store=store)
        result = run(tool.execute(task_id=task.id, due_date="bad"))
        assert result.startswith("Error:")

    def test_update_missing_task(self, store: TaskStore) -> None:
        tool = UpdateTaskTool(store=store)
        result = run(tool.execute(task_id="nonexistent", title="Nope"))
        assert result.startswith("Error:")
        assert "not found" in result

    def test_tool_name(self, store: TaskStore) -> None:
        assert UpdateTaskTool(store=store).name == "update_task"

    def test_schema_requires_task_id(self, store: TaskStore) -> None:
        tool = UpdateTaskTool(store=store)
        assert "task_id" in tool.parameters["required"]


# ---------------------------------------------------------------------------
# CompleteTaskTool tests
# ---------------------------------------------------------------------------

class TestCompleteTaskTool:
    def test_complete_existing(self, store: TaskStore) -> None:
        task = store.create_task("Finish me", "high", None, None, [])
        tool = CompleteTaskTool(store=store)
        result = run(tool.execute(task_id=task.id))
        assert "Task completed:" in result
        assert "done" in result
        assert store.get_task(task.id).status == "done"

    def test_complete_missing(self, store: TaskStore) -> None:
        tool = CompleteTaskTool(store=store)
        result = run(tool.execute(task_id="nonexistent"))
        assert result.startswith("Error:")
        assert "not found" in result

    def test_tool_name(self, store: TaskStore) -> None:
        assert CompleteTaskTool(store=store).name == "complete_task"
