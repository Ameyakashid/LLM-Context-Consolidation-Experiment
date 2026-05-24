"""Integration: SchedulingHook + CalendarContextHook in chain order.

Verifies that when the scheduling hook fires morning_motivation and
writes its Active Check-In heading, the calendar hook — running
immediately after in the same pre-iteration chain — detects the
heading and appends ``### Today's Calendar``.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from calendar_cache import CalendarCache
from calendar_hook import CALENDAR_HEADING, CalendarContextHook
from calendar_mcp_client import CalendarMCPClient
from checkin_schedule import CheckInScheduleStore
from memory_store import MemoryEntryStore
from scheduling_hook import SchedulingHook
from task_store import TaskStore


SYSTEM_PROMPT = (
    "# Soul\n\nYou are an assistant.\n\n"
    "## Scheduled Check-Ins\n\nGuidance here."
)


@dataclass
class MockContext:
    messages: list[dict[str, str]] = field(default_factory=list)


class FakeClient(CalendarMCPClient):
    def __init__(self, payload: str) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._payload = payload

    async def call(
        self, upstream_tool: str, arguments: dict[str, Any]
    ) -> str:
        self.calls.append((upstream_tool, dict(arguments)))
        return self._payload


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _make_scheduling_hook(tmp_path: Path) -> SchedulingHook:
    return SchedulingHook(
        schedule_store=CheckInScheduleStore(tmp_path / "schedule.json"),
        task_store=TaskStore(tmp_path / "tasks.json"),
        memory_store=MemoryEntryStore(tmp_path / "memories.json"),
        is_scheduled_session=lambda: True,
        get_cognitive_state=lambda: "baseline",
        get_current_date=lambda: date(2026, 4, 10),
        get_current_time=lambda: time(8, 15),
    )


def _make_calendar_hook(
    client: CalendarMCPClient,
    cache: CalendarCache,
    state: str = "baseline",
) -> CalendarContextHook:
    return CalendarContextHook(
        cache=cache,
        client=client,
        is_scheduled_session=lambda: True,
        get_cognitive_state=lambda: state,  # type: ignore[arg-type,return-value]
        get_current_datetime=lambda: datetime(
            2026, 4, 10, 8, 15, tzinfo=ZoneInfo("UTC")
        ),
    )


@pytest.fixture()
def utc_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NANOBOT_TIMEZONE", "UTC")


class TestSchedulingThenCalendarInjection:
    def test_morning_checkin_gets_calendar_block(
        self, tmp_path: Path, utc_env: None
    ) -> None:
        sched = _make_scheduling_hook(tmp_path)
        payload = json.dumps({
            "events": [
                {
                    "summary": "Standup",
                    "start": {"dateTime": "2026-04-10T09:00:00+00:00"},
                },
            ],
        })
        client = FakeClient(payload=payload)
        cal = _make_calendar_hook(client, CalendarCache())

        ctx = MockContext(messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "heartbeat"},
        ])
        _run(sched.before_iteration(ctx))
        _run(cal.before_iteration(ctx))

        content = ctx.messages[0]["content"]
        assert "Morning Motivation" in content
        assert CALENDAR_HEADING in content
        assert "09:00 Standup" in content

    def test_calendar_block_after_checkin_heading(
        self, tmp_path: Path, utc_env: None
    ) -> None:
        sched = _make_scheduling_hook(tmp_path)
        client = FakeClient(payload='{"events": []}')
        cal = _make_calendar_hook(client, CalendarCache())

        ctx = MockContext(messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
        ])
        _run(sched.before_iteration(ctx))
        _run(cal.before_iteration(ctx))

        content = ctx.messages[0]["content"]
        checkin_idx = content.index("Morning Motivation")
        calendar_idx = content.index(CALENDAR_HEADING)
        assert checkin_idx < calendar_idx

    def test_calendar_hook_noop_when_scheduling_did_not_fire(
        self, tmp_path: Path, utc_env: None
    ) -> None:
        sched = SchedulingHook(
            schedule_store=CheckInScheduleStore(tmp_path / "schedule.json"),
            task_store=TaskStore(tmp_path / "tasks.json"),
            memory_store=MemoryEntryStore(tmp_path / "memories.json"),
            is_scheduled_session=lambda: True,
            get_cognitive_state=lambda: "baseline",
            get_current_date=lambda: date(2026, 4, 10),
            get_current_time=lambda: time(15, 0),
        )
        client = FakeClient(payload='{"events": []}')
        cal = _make_calendar_hook(client, CalendarCache())

        ctx = MockContext(messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
        ])
        _run(sched.before_iteration(ctx))
        _run(cal.before_iteration(ctx))

        assert CALENDAR_HEADING not in ctx.messages[0]["content"]
        assert client.calls == []

    def test_hyperfocus_blocks_calendar_even_with_heading(
        self, tmp_path: Path, utc_env: None
    ) -> None:
        sched = _make_scheduling_hook(tmp_path)
        client = FakeClient(payload='{"events": []}')
        cal = _make_calendar_hook(client, CalendarCache(), state="hyperfocus")

        ctx = MockContext(messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
        ])
        _run(sched.before_iteration(ctx))
        _run(cal.before_iteration(ctx))

        content = ctx.messages[0]["content"]
        assert "Morning Motivation" in content
        assert CALENDAR_HEADING not in content
        assert client.calls == []


class TestSharedCacheWithTool:
    def test_hook_and_tool_share_cache_entry(
        self, tmp_path: Path, utc_env: None
    ) -> None:
        from calendar_tools import GetUpcomingEventsTool

        client = FakeClient(payload='{"events": []}')
        cache = CalendarCache()
        tool = GetUpcomingEventsTool(cache=cache, client=client)
        cal = _make_calendar_hook(client, cache)
        _run(tool.execute(hours_ahead=14))
        assert len(client.calls) == 1

        sched = _make_scheduling_hook(tmp_path)
        ctx = MockContext(messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
        ])
        _run(sched.before_iteration(ctx))
        _run(cal.before_iteration(ctx))
        assert len(client.calls) == 1
