"""Tests for CalendarMCPClient dispatch behaviour."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.registry import ToolRegistry

from calendar_mcp_client import (
    ERROR_CALENDAR_MCP_FAILURE,
    ERROR_CALENDAR_UNAVAILABLE,
    CalendarMCPClient,
    error_envelope,
    wrapped_tool_name,
)


def run(coro: Any) -> Any:
    return asyncio.run(coro)


@tool_parameters(
    {
        "type": "object",
        "properties": {},
        "additionalProperties": True,
    }
)
class _FakeMCPTool(Tool):
    """Stand-in for nanobot's MCPToolWrapper with a programmable payload."""

    def __init__(self, name: str, payload: str) -> None:
        self._name = name
        self._payload = payload
        self.calls: list[dict[str, Any]] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "fake MCP tool"

    async def execute(self, **kwargs: Any) -> str:
        self.calls.append(kwargs)
        return self._payload


class TestWrappedToolName:
    def test_list_events(self) -> None:
        assert wrapped_tool_name("list-events") == "mcp_google-calendar_list-events"

    def test_get_freebusy(self) -> None:
        assert wrapped_tool_name("get-freebusy") == "mcp_google-calendar_get-freebusy"


class TestErrorEnvelope:
    def test_contains_code_and_detail(self) -> None:
        payload = error_envelope("some_code", "some detail")
        parsed = json.loads(payload)
        assert parsed == {"error": "some_code", "detail": "some detail"}


class TestCalendarMCPClient:
    def test_dispatch_returns_upstream_string_verbatim(self) -> None:
        registry = ToolRegistry()
        upstream_payload = '{"events":[{"summary":"standup"}]}'
        fake = _FakeMCPTool(
            name="mcp_google-calendar_list-events",
            payload=upstream_payload,
        )
        registry.register(fake)
        client = CalendarMCPClient(registry=registry)

        result = run(client.call("list-events", {"calendarId": "primary"}))
        assert result == upstream_payload
        assert fake.calls == [{"calendarId": "primary"}]

    def test_missing_wrapper_returns_unavailable_envelope(self) -> None:
        registry = ToolRegistry()
        client = CalendarMCPClient(registry=registry)
        result = run(client.call("list-events", {"calendarId": "primary"}))
        parsed = json.loads(result)
        assert parsed["error"] == ERROR_CALENDAR_UNAVAILABLE
        assert "MCP server" in parsed["detail"]

    def test_mcp_failure_payload_wrapped_in_envelope(self) -> None:
        registry = ToolRegistry()
        fake = _FakeMCPTool(
            name="mcp_google-calendar_list-events",
            payload="(MCP tool call failed: TimeoutError)",
        )
        registry.register(fake)
        client = CalendarMCPClient(registry=registry)

        result = run(client.call("list-events", {"calendarId": "primary"}))
        parsed = json.loads(result)
        assert parsed["error"] == ERROR_CALENDAR_MCP_FAILURE
        assert "MCP tool call failed" in parsed["detail"]

    def test_non_string_result_coerced(self) -> None:
        class _NumericTool(Tool):
            @property
            def name(self) -> str:
                return "mcp_google-calendar_list-events"

            @property
            def description(self) -> str:
                return ""

            @property
            def parameters(self) -> dict[str, Any]:
                return {"type": "object", "properties": {}}

            async def execute(self, **kwargs: Any) -> int:
                return 42

        registry = ToolRegistry()
        registry.register(_NumericTool())
        client = CalendarMCPClient(registry=registry)
        result = run(client.call("list-events", {}))
        assert result == "42"

    def test_none_result_coerced_to_empty_string(self) -> None:
        class _NoneTool(Tool):
            @property
            def name(self) -> str:
                return "mcp_google-calendar_list-events"

            @property
            def description(self) -> str:
                return ""

            @property
            def parameters(self) -> dict[str, Any]:
                return {"type": "object", "properties": {}}

            async def execute(self, **kwargs: Any) -> None:
                return None

        registry = ToolRegistry()
        registry.register(_NoneTool())
        client = CalendarMCPClient(registry=registry)
        result = run(client.call("list-events", {}))
        assert result == ""
