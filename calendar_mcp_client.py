"""Dispatcher from Python calendar tools to nanobot-registered MCP tools.

Nanobot auto-registers every tool exposed by the ``google-calendar`` MCP
server under names like ``mcp_google-calendar_list-events``. This client
resolves the wrapper at call time (MCP connects lazily on the first
agent iteration) and dispatches to it. On any unavailable/failure path
it returns a JSON-serialized structured error envelope instead of
raising, so the calling Tool can surface a stable contract to the LLM.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from nanobot.agent.tools.registry import ToolRegistry

log = logging.getLogger(__name__)

MCP_SERVER_NAME = "google-calendar"
MCP_FAILURE_PREFIX = "(MCP tool call "

ERROR_CALENDAR_UNAVAILABLE = "calendar_unavailable"
ERROR_CALENDAR_MCP_FAILURE = "calendar_mcp_failure"

UNAVAILABLE_DETAIL = (
    "The google-calendar MCP server is not registered in the tool "
    "registry. It may still be starting, the GOOGLE_CALENDAR_ENABLED "
    "flag may be off, or OAuth may not have completed. Run "
    "`npm run auth` inside mcp/google-calendar/ to re-authorize, or "
    "set GOOGLE_CALENDAR_ENABLED=false to disable calendar features."
)


def wrapped_tool_name(upstream_tool: str) -> str:
    """Return the flat name nanobot uses for an MCP tool."""
    return f"mcp_{MCP_SERVER_NAME}_{upstream_tool}"


def error_envelope(error_code: str, detail: str) -> str:
    """Return a JSON-serialized structured error envelope."""
    return json.dumps({"error": error_code, "detail": detail})


class CalendarMCPClient:
    """Resolves and dispatches calendar MCP tool calls at call time.

    Holds a reference to the ``ToolRegistry`` that nanobot populates with
    MCP wrappers on the first agent iteration. Each call resolves the
    wrapper by name, dispatches, and returns the upstream string on
    success or a structured error envelope on failure.

    The registry can be supplied lazily via ``set_registry`` so the client
    can be constructed before ``AgentLoop`` builds its ``ToolRegistry``
    (the pre-iteration hook chain needs a client reference at hook-
    creation time). ``call`` returns the unavailable envelope when no
    registry has been provided yet.
    """

    def __init__(self, registry: ToolRegistry | None = None) -> None:
        self._registry: ToolRegistry | None = registry

    def set_registry(self, registry: ToolRegistry) -> None:
        """Attach the live ``ToolRegistry`` after ``AgentLoop`` construction."""
        self._registry = registry

    async def call(
        self, upstream_tool: str, arguments: dict[str, Any]
    ) -> str:
        registry = self._registry
        if registry is None:
            log.warning(
                "Calendar MCP client has no registry yet — "
                "returning unavailable envelope",
            )
            return error_envelope(
                ERROR_CALENDAR_UNAVAILABLE, UNAVAILABLE_DETAIL
            )

        wrapped = wrapped_tool_name(upstream_tool)
        tool = registry.get(wrapped)
        if tool is None:
            log.warning(
                "Calendar MCP tool %r is not registered — "
                "returning unavailable envelope",
                wrapped,
            )
            return error_envelope(
                ERROR_CALENDAR_UNAVAILABLE, UNAVAILABLE_DETAIL
            )

        result = await tool.execute(**arguments)
        if not isinstance(result, str):
            return "" if result is None else str(result)
        if result.startswith(MCP_FAILURE_PREFIX):
            log.warning(
                "MCP dispatch for %r returned failure payload: %s",
                wrapped,
                result,
            )
            return error_envelope(ERROR_CALENDAR_MCP_FAILURE, result)
        return result
