"""Tests for the 3 calendar Tool wrappers.

Injects a fake CalendarMCPClient so nothing hits the real subprocess.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from calendar_cache import CalendarCache
from calendar_mcp_client import CalendarMCPClient
from calendar_tools import (
    DEFAULT_CALENDAR_ID,
    DEFAULT_HOURS_AHEAD,
    CheckFreeBusyTool,
    GetUpcomingEventsTool,
    ListEventsInWindowTool,
    build_cache_key,
    format_iso_for_mcp,
    resolve_user_timezone,
)


def run(coro: Any) -> Any:
    return asyncio.run(coro)


class FakeCalendarClient(CalendarMCPClient):
    """In-memory stand-in for CalendarMCPClient."""

    def __init__(self, payload: str = '{"events":[]}') -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._payload = payload

    async def call(
        self, upstream_tool: str, arguments: dict[str, Any]
    ) -> str:
        self.calls.append((upstream_tool, dict(arguments)))
        return self._payload


@pytest.fixture()
def cache() -> CalendarCache:
    return CalendarCache(ttl_seconds=60, max_entries=16)


@pytest.fixture()
def utc_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NANOBOT_TIMEZONE", "UTC")


class TestFormatIsoForMcp:
    def test_strips_microseconds(self) -> None:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        dt = datetime(2026, 4, 20, 9, 30, 15, 123456, tzinfo=ZoneInfo("UTC"))
        rendered = format_iso_for_mcp(dt)
        assert "." not in rendered
        assert rendered.startswith("2026-04-20T09:30:15")


class TestResolveUserTimezone:
    def test_default_is_utc(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NANOBOT_TIMEZONE", raising=False)
        assert str(resolve_user_timezone()) == "UTC"

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NANOBOT_TIMEZONE", "America/New_York")
        assert str(resolve_user_timezone()) == "America/New_York"

    def test_unknown_timezone_falls_back(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NANOBOT_TIMEZONE", "Not/A_Real_TZ")
        assert str(resolve_user_timezone()) == "UTC"


class TestBuildCacheKey:
    def test_stable_across_dict_order(self) -> None:
        k1 = build_cache_key("tool", {"a": 1, "b": 2})
        k2 = build_cache_key("tool", {"b": 2, "a": 1})
        assert k1 == k2

    def test_different_tools_different_keys(self) -> None:
        k1 = build_cache_key("tool_a", {"x": 1})
        k2 = build_cache_key("tool_b", {"x": 1})
        assert k1 != k2


class TestGetUpcomingEventsTool:
    def test_name_and_read_only(self, cache: CalendarCache) -> None:
        tool = GetUpcomingEventsTool(cache=cache, client=FakeCalendarClient())
        assert tool.name == "get_upcoming_events"
        assert tool.read_only is True

    def test_dispatches_list_events(
        self, cache: CalendarCache, utc_env: None
    ) -> None:
        client = FakeCalendarClient(payload='{"events":[{"summary":"standup"}]}')
        tool = GetUpcomingEventsTool(cache=cache, client=client)
        result = run(tool.execute())
        assert "standup" in result
        assert len(client.calls) == 1
        upstream, args = client.calls[0]
        assert upstream == "list-events"
        assert args["calendarId"] == DEFAULT_CALENDAR_ID
        assert "timeMin" in args
        assert "timeMax" in args
        assert args["timeZone"] == "UTC"

    def test_custom_hours_ahead(
        self, cache: CalendarCache, utc_env: None
    ) -> None:
        from datetime import datetime
        client = FakeCalendarClient()
        tool = GetUpcomingEventsTool(cache=cache, client=client)
        run(tool.execute(hours_ahead=24))
        _, args = client.calls[0]
        time_min = datetime.fromisoformat(args["timeMin"])
        time_max = datetime.fromisoformat(args["timeMax"])
        delta = time_max - time_min
        assert delta.total_seconds() == 24 * 3600

    def test_custom_calendar_id(
        self, cache: CalendarCache, utc_env: None
    ) -> None:
        client = FakeCalendarClient()
        tool = GetUpcomingEventsTool(cache=cache, client=client)
        run(tool.execute(calendar_id="work@example.com"))
        _, args = client.calls[0]
        assert args["calendarId"] == "work@example.com"

    def test_cache_hit_skips_client(
        self, cache: CalendarCache, utc_env: None
    ) -> None:
        client = FakeCalendarClient(payload="first")
        tool = GetUpcomingEventsTool(cache=cache, client=client)
        first = run(tool.execute(hours_ahead=6))
        second = run(tool.execute(hours_ahead=6))
        assert first == second == "first"
        assert len(client.calls) == 1

    def test_different_hours_ahead_different_cache_keys(
        self, cache: CalendarCache, utc_env: None
    ) -> None:
        client = FakeCalendarClient(payload="x")
        tool = GetUpcomingEventsTool(cache=cache, client=client)
        run(tool.execute(hours_ahead=6))
        run(tool.execute(hours_ahead=12))
        assert len(client.calls) == 2

    def test_default_hours_matches_constant(self) -> None:
        assert DEFAULT_HOURS_AHEAD == 12


class TestListEventsInWindowTool:
    def test_name_and_read_only(self, cache: CalendarCache) -> None:
        tool = ListEventsInWindowTool(cache=cache, client=FakeCalendarClient())
        assert tool.name == "list_events_in_window"
        assert tool.read_only is True

    def test_dispatches_with_default_calendar(
        self, cache: CalendarCache
    ) -> None:
        client = FakeCalendarClient(payload='{"events":[]}')
        tool = ListEventsInWindowTool(cache=cache, client=client)
        run(
            tool.execute(
                start_iso="2026-04-20T09:00:00",
                end_iso="2026-04-20T17:00:00",
            )
        )
        upstream, args = client.calls[0]
        assert upstream == "list-events"
        assert args["calendarId"] == DEFAULT_CALENDAR_ID
        assert args["timeMin"] == "2026-04-20T09:00:00"
        assert args["timeMax"] == "2026-04-20T17:00:00"

    def test_single_calendar_id_passed_as_string(
        self, cache: CalendarCache
    ) -> None:
        client = FakeCalendarClient()
        tool = ListEventsInWindowTool(cache=cache, client=client)
        run(
            tool.execute(
                start_iso="2026-04-20T00:00:00",
                end_iso="2026-04-21T00:00:00",
                calendar_ids=["work@example.com"],
            )
        )
        _, args = client.calls[0]
        assert args["calendarId"] == "work@example.com"

    def test_multiple_calendar_ids_passed_as_list(
        self, cache: CalendarCache
    ) -> None:
        client = FakeCalendarClient()
        tool = ListEventsInWindowTool(cache=cache, client=client)
        run(
            tool.execute(
                start_iso="2026-04-20T00:00:00",
                end_iso="2026-04-21T00:00:00",
                calendar_ids=["primary", "work@example.com"],
            )
        )
        _, args = client.calls[0]
        assert args["calendarId"] == ["primary", "work@example.com"]

    def test_cache_hit_is_order_insensitive_for_calendar_ids(
        self, cache: CalendarCache
    ) -> None:
        client = FakeCalendarClient(payload="first")
        tool = ListEventsInWindowTool(cache=cache, client=client)
        run(
            tool.execute(
                start_iso="2026-04-20T00:00:00",
                end_iso="2026-04-21T00:00:00",
                calendar_ids=["a", "b"],
            )
        )
        run(
            tool.execute(
                start_iso="2026-04-20T00:00:00",
                end_iso="2026-04-21T00:00:00",
                calendar_ids=["b", "a"],
            )
        )
        assert len(client.calls) == 1


class TestCheckFreeBusyTool:
    def test_name_and_read_only(self, cache: CalendarCache) -> None:
        tool = CheckFreeBusyTool(cache=cache, client=FakeCalendarClient())
        assert tool.name == "check_free_busy"
        assert tool.read_only is True

    def test_dispatches_with_calendars_shape(
        self, cache: CalendarCache
    ) -> None:
        client = FakeCalendarClient(payload='{"busy":[]}')
        tool = CheckFreeBusyTool(cache=cache, client=client)
        run(
            tool.execute(
                start_iso="2026-04-20T09:00:00",
                end_iso="2026-04-20T17:00:00",
            )
        )
        upstream, args = client.calls[0]
        assert upstream == "get-freebusy"
        assert args["calendars"] == [{"id": DEFAULT_CALENDAR_ID}]
        assert args["timeMin"] == "2026-04-20T09:00:00"
        assert args["timeMax"] == "2026-04-20T17:00:00"

    def test_multiple_calendars_expanded(self, cache: CalendarCache) -> None:
        client = FakeCalendarClient()
        tool = CheckFreeBusyTool(cache=cache, client=client)
        run(
            tool.execute(
                start_iso="2026-04-20T00:00:00",
                end_iso="2026-04-21T00:00:00",
                calendar_ids=["primary", "work@example.com"],
            )
        )
        _, args = client.calls[0]
        assert args["calendars"] == [
            {"id": "primary"},
            {"id": "work@example.com"},
        ]


class TestErrorEnvelopePassThrough:
    def test_unavailable_envelope_returned_verbatim(
        self, cache: CalendarCache, utc_env: None
    ) -> None:
        envelope = json.dumps(
            {"error": "calendar_unavailable", "detail": "fake"}
        )
        client = FakeCalendarClient(payload=envelope)
        tool = GetUpcomingEventsTool(cache=cache, client=client)
        result = run(tool.execute())
        assert result == envelope
        parsed = json.loads(result)
        assert parsed["error"] == "calendar_unavailable"


