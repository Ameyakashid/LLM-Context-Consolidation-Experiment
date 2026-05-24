"""Hook-lifecycle tests for CalendarContextHook.

These exercise the class orchestration: guards (messages empty,
not-scheduled, non-morning-checkin, disallowed state), cache hit
short-circuit, error-envelope → unavailable block, success path,
and the 1/hour rate-limited error log.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from calendar_cache import CalendarCache
from calendar_hook import (
    CALENDAR_HEADING,
    FREE_DAY_LINE,
    UNAVAILABLE_LINE,
    CalendarContextHook,
)
from calendar_mcp_client import CalendarMCPClient
from state_detection import StateName


def run(coro: Any) -> Any:
    return asyncio.run(coro)


@dataclass
class FakeContext:
    messages: list[dict[str, str]] = field(default_factory=list)


class FakeClient(CalendarMCPClient):
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


def _now() -> datetime:
    return datetime(2026, 4, 20, 7, 0, 0, tzinfo=ZoneInfo("UTC"))


def _make_hook(
    cache: CalendarCache,
    client: CalendarMCPClient,
    *,
    scheduled: bool = True,
    state: StateName = "baseline",
    now: datetime | None = None,
) -> CalendarContextHook:
    current = now if now is not None else _now()
    return CalendarContextHook(
        cache=cache,
        client=client,
        is_scheduled_session=lambda: scheduled,
        get_cognitive_state=lambda: state,
        get_current_datetime=lambda: current,
    )


def _morning_prompt() -> str:
    return (
        "# Nanobot heartbeat\n\n"
        "## Active Check-In: Morning Motivation\nBody here"
    )


class TestGuardConditions:
    def test_empty_messages_no_fetch(self, cache: CalendarCache, utc_env: None) -> None:
        client = FakeClient()
        hook = _make_hook(cache, client)
        ctx = FakeContext(messages=[])
        run(hook.before_iteration(ctx))
        assert client.calls == []

    def test_unscheduled_session_no_fetch(self, cache: CalendarCache, utc_env: None) -> None:
        client = FakeClient()
        hook = _make_hook(cache, client, scheduled=False)
        ctx = FakeContext(messages=[{"role": "system", "content": _morning_prompt()}])
        run(hook.before_iteration(ctx))
        assert client.calls == []

    def test_non_system_first_message_no_fetch(self, cache: CalendarCache, utc_env: None) -> None:
        client = FakeClient()
        hook = _make_hook(cache, client)
        ctx = FakeContext(messages=[{"role": "user", "content": _morning_prompt()}])
        run(hook.before_iteration(ctx))
        assert client.calls == []

    def test_no_checkin_heading_no_fetch(self, cache: CalendarCache, utc_env: None) -> None:
        client = FakeClient()
        hook = _make_hook(cache, client)
        ctx = FakeContext(messages=[{"role": "system", "content": "# System\nno checkin"}])
        run(hook.before_iteration(ctx))
        assert client.calls == []

    def test_afternoon_checkin_no_fetch(self, cache: CalendarCache, utc_env: None) -> None:
        client = FakeClient()
        hook = _make_hook(cache, client)
        ctx = FakeContext(messages=[{
            "role": "system",
            "content": "## Active Check-In: Afternoon Check\nbody",
        }])
        run(hook.before_iteration(ctx))
        assert client.calls == []

    def test_hyperfocus_blocks_fetch(self, cache: CalendarCache, utc_env: None) -> None:
        client = FakeClient()
        hook = _make_hook(cache, client, state="hyperfocus")
        ctx = FakeContext(messages=[{"role": "system", "content": _morning_prompt()}])
        run(hook.before_iteration(ctx))
        assert client.calls == []

    def test_overwhelm_blocks_fetch(self, cache: CalendarCache, utc_env: None) -> None:
        client = FakeClient()
        hook = _make_hook(cache, client, state="overwhelm")
        ctx = FakeContext(messages=[{"role": "system", "content": _morning_prompt()}])
        run(hook.before_iteration(ctx))
        assert client.calls == []


class TestSuccessPath:
    def test_injects_free_day_block(self, cache: CalendarCache, utc_env: None) -> None:
        client = FakeClient(payload='{"events": []}')
        hook = _make_hook(cache, client)
        ctx = FakeContext(messages=[{"role": "system", "content": _morning_prompt()}])
        run(hook.before_iteration(ctx))
        content = ctx.messages[0]["content"]
        assert CALENDAR_HEADING in content
        assert FREE_DAY_LINE in content

    def test_injects_formatted_events(self, cache: CalendarCache, utc_env: None) -> None:
        payload = json.dumps({
            "events": [
                {
                    "summary": "Standup",
                    "start": {"dateTime": "2026-04-20T09:00:00+00:00"},
                },
            ],
        })
        client = FakeClient(payload=payload)
        hook = _make_hook(cache, client)
        ctx = FakeContext(messages=[{"role": "system", "content": _morning_prompt()}])
        run(hook.before_iteration(ctx))
        content = ctx.messages[0]["content"]
        assert "- 09:00 Standup" in content

    def test_morning_plan_also_triggers(self, cache: CalendarCache, utc_env: None) -> None:
        client = FakeClient()
        hook = _make_hook(cache, client)
        ctx = FakeContext(messages=[{
            "role": "system",
            "content": "## Active Check-In: Morning Plan\nbody",
        }])
        run(hook.before_iteration(ctx))
        assert len(client.calls) == 1
        assert CALENDAR_HEADING in ctx.messages[0]["content"]


class TestCacheBehaviour:
    def test_cache_hit_skips_client(self, cache: CalendarCache, utc_env: None) -> None:
        client = FakeClient(payload='{"events": []}')
        hook = _make_hook(cache, client)
        ctx1 = FakeContext(messages=[{"role": "system", "content": _morning_prompt()}])
        ctx2 = FakeContext(messages=[{"role": "system", "content": _morning_prompt()}])
        run(hook.before_iteration(ctx1))
        run(hook.before_iteration(ctx2))
        assert len(client.calls) == 1


class TestErrorHandling:
    def test_unavailable_envelope_injects_marker(self, cache: CalendarCache, utc_env: None) -> None:
        envelope = json.dumps({"error": "calendar_unavailable", "detail": "no auth"})
        client = FakeClient(payload=envelope)
        hook = _make_hook(cache, client)
        ctx = FakeContext(messages=[{"role": "system", "content": _morning_prompt()}])
        run(hook.before_iteration(ctx))
        assert UNAVAILABLE_LINE in ctx.messages[0]["content"]

    def test_malformed_payload_injects_marker(self, cache: CalendarCache, utc_env: None) -> None:
        client = FakeClient(payload="not json at all")
        hook = _make_hook(cache, client)
        ctx = FakeContext(messages=[{"role": "system", "content": _morning_prompt()}])
        run(hook.before_iteration(ctx))
        assert UNAVAILABLE_LINE in ctx.messages[0]["content"]

    def test_rate_limited_warning_only_once_per_hour(
        self,
        cache: CalendarCache,
        utc_env: None,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        envelope = json.dumps({"error": "calendar_unavailable", "detail": "x"})
        client = FakeClient(payload=envelope)
        t0 = datetime(2026, 4, 20, 7, 0, 0, tzinfo=ZoneInfo("UTC"))
        current = {"t": t0}
        hook = CalendarContextHook(
            cache=cache,
            client=client,
            is_scheduled_session=lambda: True,
            get_cognitive_state=lambda: "baseline",
            get_current_datetime=lambda: current["t"],
        )

        caplog.set_level("WARNING", logger="calendar_hook")
        ctx1 = FakeContext(messages=[{"role": "system", "content": _morning_prompt()}])
        run(hook.before_iteration(ctx1))
        current["t"] = t0 + timedelta(minutes=30)
        cache.clear()
        ctx2 = FakeContext(messages=[{"role": "system", "content": _morning_prompt()}])
        run(hook.before_iteration(ctx2))

        fetch_failures = [
            r for r in caplog.records
            if "Calendar fetch failed" in r.getMessage()
        ]
        assert len(fetch_failures) == 1

    def test_rate_limit_allows_second_after_hour(
        self,
        cache: CalendarCache,
        utc_env: None,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        envelope = json.dumps({"error": "calendar_unavailable", "detail": "x"})
        client = FakeClient(payload=envelope)
        t0 = datetime(2026, 4, 20, 7, 0, 0, tzinfo=ZoneInfo("UTC"))
        current = {"t": t0}
        hook = CalendarContextHook(
            cache=cache,
            client=client,
            is_scheduled_session=lambda: True,
            get_cognitive_state=lambda: "baseline",
            get_current_datetime=lambda: current["t"],
        )

        caplog.set_level("WARNING", logger="calendar_hook")
        ctx1 = FakeContext(messages=[{"role": "system", "content": _morning_prompt()}])
        run(hook.before_iteration(ctx1))
        current["t"] = t0 + timedelta(hours=1, seconds=1)
        cache.clear()
        ctx2 = FakeContext(messages=[{"role": "system", "content": _morning_prompt()}])
        run(hook.before_iteration(ctx2))

        fetch_failures = [
            r for r in caplog.records
            if "Calendar fetch failed" in r.getMessage()
        ]
        assert len(fetch_failures) == 2

    def test_exception_in_process_is_swallowed(self, cache: CalendarCache, utc_env: None) -> None:
        class ExplodingClient(CalendarMCPClient):
            async def call(
                self, upstream_tool: str, arguments: dict[str, Any]
            ) -> str:
                raise RuntimeError("boom")

        hook = _make_hook(cache, ExplodingClient())
        ctx = FakeContext(messages=[{"role": "system", "content": _morning_prompt()}])
        run(hook.before_iteration(ctx))
        assert CALENDAR_HEADING not in ctx.messages[0]["content"]
