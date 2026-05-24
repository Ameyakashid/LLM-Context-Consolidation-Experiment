"""Tests for register_calendar_tools and CALENDAR_TOOL_NAMES."""

from __future__ import annotations

from typing import Any

import pytest

from nanobot.agent.tools.registry import ToolRegistry

from calendar_cache import CalendarCache
from calendar_mcp_client import CalendarMCPClient
from calendar_tools import CALENDAR_TOOL_NAMES, register_calendar_tools


class _FakeClient(CalendarMCPClient):
    def __init__(self) -> None:  # type: ignore[super-init-not-called]
        pass

    async def call(
        self, upstream_tool: str, arguments: dict[str, Any]
    ) -> str:
        return "{}"


@pytest.fixture()
def cache() -> CalendarCache:
    return CalendarCache()


class TestRegisterCalendarTools:
    def test_registers_three_tools(self, cache: CalendarCache) -> None:
        registry = ToolRegistry()
        count = register_calendar_tools(registry, cache, _FakeClient())
        assert count == 3
        assert len(registry) == 3
        for tool_name in CALENDAR_TOOL_NAMES:
            assert registry.has(tool_name)

    def test_calendar_tool_names_match_registered(
        self, cache: CalendarCache
    ) -> None:
        registry = ToolRegistry()
        register_calendar_tools(registry, cache, _FakeClient())
        assert set(registry.tool_names) == set(CALENDAR_TOOL_NAMES)

    def test_definitions_are_valid_openai_function_schemas(
        self, cache: CalendarCache
    ) -> None:
        registry = ToolRegistry()
        register_calendar_tools(registry, cache, _FakeClient())
        definitions = registry.get_definitions()
        assert len(definitions) == 3
        for defn in definitions:
            assert defn["type"] == "function"
            func = defn["function"]
            assert func["name"] in CALENDAR_TOOL_NAMES
            assert func["parameters"]["type"] == "object"

    def test_no_write_tool_names_registered(
        self, cache: CalendarCache
    ) -> None:
        registry = ToolRegistry()
        register_calendar_tools(registry, cache, _FakeClient())
        for forbidden in (
            "create_event",
            "create-event",
            "update_event",
            "update-event",
            "delete_event",
            "delete-event",
            "respond_to_event",
            "respond-to-event",
        ):
            assert not registry.has(forbidden)

    def test_calendar_tool_names_is_tuple_of_three(self) -> None:
        assert isinstance(CALENDAR_TOOL_NAMES, tuple)
        assert len(CALENDAR_TOOL_NAMES) == 3
