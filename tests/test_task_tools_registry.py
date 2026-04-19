"""Tests for register_task_tools — registry wiring and execution."""

import asyncio
from pathlib import Path

import pytest

from nanobot.agent.tools.registry import ToolRegistry

from task_store import TaskStore
from task_tools import register_task_tools


@pytest.fixture()
def store(tmp_path: Path) -> TaskStore:
    return TaskStore(tmp_path / "tasks.json")


def run(coro):  # noqa: ANN001, ANN201
    return asyncio.run(coro)


class TestRegisterTaskTools:
    def test_registers_all_five_tools(self, store: TaskStore) -> None:
        registry = ToolRegistry()
        count = register_task_tools(registry, store)
        assert count == 5
        assert len(registry) == 5
        for name in ["create_task", "list_tasks", "get_task", "update_task", "complete_task"]:
            assert registry.has(name), f"Missing tool: {name}"

    def test_tools_produce_valid_schemas(self, store: TaskStore) -> None:
        registry = ToolRegistry()
        register_task_tools(registry, store)
        definitions = registry.get_definitions()
        assert len(definitions) == 5
        for defn in definitions:
            assert defn["type"] == "function"
            func = defn["function"]
            assert "name" in func
            assert "description" in func
            assert "parameters" in func
            assert func["parameters"]["type"] == "object"

    def test_execute_via_registry(self, store: TaskStore) -> None:
        registry = ToolRegistry()
        register_task_tools(registry, store)
        result = run(registry.execute("create_task", {"title": "Via registry", "priority": "low"}))
        assert "Task created:" in result
        assert "Via registry" in result
