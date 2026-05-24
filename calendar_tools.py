"""Nanobot-ai tool wrappers for the vendored google-calendar MCP server.

Exposes three LLM-callable, read-only tools — ``get_upcoming_events``,
``list_events_in_window``, ``check_free_busy`` — that dispatch to the
nanobot-registered MCP wrappers ``mcp_google-calendar_list-events`` and
``mcp_google-calendar_get-freebusy``. The workspace config template
restricts ``enabledTools`` to just those two upstream tools so the five
write-capable upstream tools stay invisible to the LLM.

Registration: ``register_calendar_tools(registry, cache, client)`` is
called from ``custom_gateway.register_all_tools`` guarded on the
``GOOGLE_CALENDAR_ENABLED`` env flag.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.schema import (
    ArraySchema,
    IntegerSchema,
    StringSchema,
    tool_parameters_schema,
)

from calendar_cache import CalendarCache
from calendar_mcp_client import CalendarMCPClient

log = logging.getLogger(__name__)

CALENDAR_TOOL_NAMES: tuple[str, str, str] = (
    "get_upcoming_events",
    "list_events_in_window",
    "check_free_busy",
)

DEFAULT_CALENDAR_ID = "primary"
DEFAULT_HOURS_AHEAD = 12
MIN_HOURS_AHEAD = 1
MAX_HOURS_AHEAD = 168

NANOBOT_TIMEZONE_ENV = "NANOBOT_TIMEZONE"
DEFAULT_TIMEZONE = "UTC"

UPSTREAM_LIST_EVENTS = "list-events"
UPSTREAM_GET_FREEBUSY = "get-freebusy"


def resolve_user_timezone() -> ZoneInfo:
    """Return the user's configured timezone, falling back to UTC."""
    raw = os.environ.get(NANOBOT_TIMEZONE_ENV, DEFAULT_TIMEZONE).strip()
    name = raw or DEFAULT_TIMEZONE
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        log.warning(
            "Unknown timezone %r; falling back to %s",
            name,
            DEFAULT_TIMEZONE,
        )
        return ZoneInfo(DEFAULT_TIMEZONE)


def format_iso_for_mcp(value: datetime) -> str:
    """Render an ISO-8601 timestamp accepted by the upstream regex.

    Upstream rejects fractional seconds; strip microseconds before
    formatting. Offset or ``Z`` is preserved when ``value`` is tz-aware.
    """
    return value.replace(microsecond=0).isoformat()


def build_cache_key(tool_name: str, arguments: dict[str, Any]) -> str:
    """Return a canonical-JSON cache key stable across dict orderings."""
    payload = {"tool": tool_name, "args": arguments}
    return json.dumps(payload, sort_keys=True, default=str)


class _CalendarTool(Tool):
    """Shared cache+dispatch helpers for the three calendar tools."""

    def __init__(
        self, cache: CalendarCache, client: CalendarMCPClient
    ) -> None:
        self._cache = cache
        self._client = client

    @property
    def read_only(self) -> bool:
        return True

    async def _cached_dispatch(
        self,
        cache_key: str,
        upstream_tool: str,
        arguments: dict[str, Any],
    ) -> str:
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        result = await self._client.call(upstream_tool, arguments)
        self._cache.set(cache_key, result)
        return result


@tool_parameters(
    tool_parameters_schema(
        hours_ahead=IntegerSchema(
            description=(
                "How many hours to look ahead from now. "
                f"Defaults to {DEFAULT_HOURS_AHEAD}."
            ),
            minimum=MIN_HOURS_AHEAD,
            maximum=MAX_HOURS_AHEAD,
            nullable=True,
        ),
        calendar_id=StringSchema(
            "Google Calendar ID to query. Defaults to 'primary'.",
            nullable=True,
        ),
    )
)
class GetUpcomingEventsTool(_CalendarTool):
    @property
    def name(self) -> str:
        return "get_upcoming_events"

    @property
    def description(self) -> str:
        return (
            "List Google Calendar events between now and N hours ahead. "
            "Read-only — cannot create, update, or delete events."
        )

    async def execute(
        self,
        hours_ahead: int | None = None,
        calendar_id: str | None = None,
    ) -> str:
        hours = hours_ahead if hours_ahead is not None else DEFAULT_HOURS_AHEAD
        cal_id = calendar_id or DEFAULT_CALENDAR_ID
        tz = resolve_user_timezone()
        now = datetime.now(tz)
        arguments: dict[str, Any] = {
            "calendarId": cal_id,
            "timeMin": format_iso_for_mcp(now),
            "timeMax": format_iso_for_mcp(now + timedelta(hours=hours)),
            "timeZone": str(tz),
        }
        cache_key = build_cache_key(
            self.name,
            {"hours_ahead": hours, "calendar_id": cal_id},
        )
        return await self._cached_dispatch(
            cache_key, UPSTREAM_LIST_EVENTS, arguments
        )


@tool_parameters(
    tool_parameters_schema(
        start_iso=StringSchema(
            "Start of window in ISO 8601 "
            "(e.g. '2026-04-20T09:00:00'). No fractional seconds."
        ),
        end_iso=StringSchema(
            "End of window in ISO 8601. Must be after start_iso."
        ),
        calendar_ids=ArraySchema(
            StringSchema("A Google Calendar ID"),
            description=(
                "Calendar IDs to query. Defaults to ['primary'] when omitted."
            ),
            nullable=True,
        ),
        required=["start_iso", "end_iso"],
    )
)
class ListEventsInWindowTool(_CalendarTool):
    @property
    def name(self) -> str:
        return "list_events_in_window"

    @property
    def description(self) -> str:
        return (
            "List Google Calendar events between two explicit ISO 8601 "
            "timestamps. Read-only — use for day or week queries."
        )

    async def execute(
        self,
        start_iso: str,
        end_iso: str,
        calendar_ids: list[str] | None = None,
    ) -> str:
        ids = list(calendar_ids) if calendar_ids else [DEFAULT_CALENDAR_ID]
        calendar_arg: str | list[str] = ids[0] if len(ids) == 1 else ids
        arguments: dict[str, Any] = {
            "calendarId": calendar_arg,
            "timeMin": start_iso,
            "timeMax": end_iso,
        }
        cache_key = build_cache_key(
            self.name,
            {
                "start_iso": start_iso,
                "end_iso": end_iso,
                "calendar_ids": sorted(ids),
            },
        )
        return await self._cached_dispatch(
            cache_key, UPSTREAM_LIST_EVENTS, arguments
        )


@tool_parameters(
    tool_parameters_schema(
        start_iso=StringSchema(
            "Start of window in ISO 8601. Must be within 3 months of end_iso."
        ),
        end_iso=StringSchema(
            "End of window in ISO 8601. Must be after start_iso."
        ),
        calendar_ids=ArraySchema(
            StringSchema("A Google Calendar ID"),
            description=(
                "Calendar IDs to query. Defaults to ['primary'] when omitted."
            ),
            nullable=True,
        ),
        required=["start_iso", "end_iso"],
    )
)
class CheckFreeBusyTool(_CalendarTool):
    @property
    def name(self) -> str:
        return "check_free_busy"

    @property
    def description(self) -> str:
        return (
            "Check free/busy status across one or more calendars in an "
            "ISO 8601 window. Read-only — returns busy intervals only."
        )

    async def execute(
        self,
        start_iso: str,
        end_iso: str,
        calendar_ids: list[str] | None = None,
    ) -> str:
        ids = list(calendar_ids) if calendar_ids else [DEFAULT_CALENDAR_ID]
        arguments: dict[str, Any] = {
            "calendars": [{"id": cid} for cid in ids],
            "timeMin": start_iso,
            "timeMax": end_iso,
        }
        cache_key = build_cache_key(
            self.name,
            {
                "start_iso": start_iso,
                "end_iso": end_iso,
                "calendar_ids": sorted(ids),
            },
        )
        return await self._cached_dispatch(
            cache_key, UPSTREAM_GET_FREEBUSY, arguments
        )


def register_calendar_tools(
    registry: ToolRegistry,
    cache: CalendarCache,
    client: CalendarMCPClient,
) -> int:
    """Register the 3 calendar tools on the ToolRegistry.

    Returns the number of tools registered. Safe to call multiple times
    only if the registry de-duplicates by name (nanobot's does).
    """
    tools: list[Tool] = [
        GetUpcomingEventsTool(cache=cache, client=client),
        ListEventsInWindowTool(cache=cache, client=client),
        CheckFreeBusyTool(cache=cache, client=client),
    ]
    for tool in tools:
        registry.register(tool)
    count = len(tools)
    log.info(
        "Registered %d calendar tools: upcoming, window, freebusy",
        count,
    )
    return count
