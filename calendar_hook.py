"""Calendar-context hook for nanobot-ai heartbeat sessions.

Runs after ``SchedulingHook`` in the pre-iteration chain. When the
system prompt already shows an Active Check-In heading for
``morning_motivation`` or ``morning_plan``, this hook fetches today's
events from the vendored google-calendar MCP server (via the shared
``CalendarCache`` + ``CalendarMCPClient``) and appends a
``### Today's Calendar`` block. All other turns pay zero MCP cost.
On OAuth or MCP failure, injects a short "calendar unavailable" marker
for the LLM to surface to the user. WARNING logs are rate-limited to
one per hour per hook instance.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable

from calendar_cache import CalendarCache
from calendar_mcp_client import CalendarMCPClient
from calendar_tools import (
    DEFAULT_CALENDAR_ID,
    UPSTREAM_LIST_EVENTS,
    build_cache_key,
    format_iso_for_mcp,
    resolve_user_timezone,
)
from hook_context import HookContext
from scheduling_hook import CHECKIN_DISPLAY_NAMES
from state_detection import StateName

log = logging.getLogger(__name__)

CALENDAR_CHECKIN_TRIGGERS: tuple[str, str] = (
    "morning_motivation", "morning_plan",
)
CALENDAR_HEADING = "### Today's Calendar"
FREE_DAY_LINE = "(nothing scheduled — free day)"
UNAVAILABLE_LINE = (
    "[Calendar unavailable — the user's Google authorization has "
    "expired. Tell them (briefly) and point them to /calendar_auth "
    "or the steps in CALENDAR.md.]"
)
MORNING_FETCH_HOURS_AHEAD = 14
MAX_EVENTS_DISPLAYED = 8
ALLOWED_STATES: frozenset[str] = frozenset(
    {"baseline", "focus", "avoidance", "rsd"}
)
ERROR_LOG_INTERVAL = timedelta(hours=1)
ERROR_LOG_PAYLOAD_LIMIT = 200
CACHE_TOOL_KEY = "get_upcoming_events"


@dataclass(frozen=True)
class CalendarEvent:
    """Minimal display-ready event for the formatter."""

    summary: str
    start_display: str
    location: str | None


def detect_morning_checkin(system_content: str) -> bool:
    """Return True when the prompt carries a morning-check-in heading."""
    for type_id in CALENDAR_CHECKIN_TRIGGERS:
        heading = f"## Active Check-In: {CHECKIN_DISPLAY_NAMES[type_id]}"
        if heading in system_content:
            return True
    return False


def is_state_allowed(state: StateName) -> bool:
    """Return True when the cognitive state permits calendar injection."""
    return state in ALLOWED_STATES


def is_error_envelope(payload: str) -> bool:
    """Return True when the payload is a sub-02 structured error envelope."""
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return False
    return isinstance(parsed, dict) and "error" in parsed


def _format_start_display(start_obj: dict[str, Any]) -> str:
    """Render a StructuredEvent.start into 24h ``HH:MM`` or ``all day``."""
    date_time = start_obj.get("dateTime")
    if isinstance(date_time, str) and date_time:
        try:
            parsed = datetime.fromisoformat(date_time.replace("Z", "+00:00"))
        except ValueError:
            return "(unknown)"
        return parsed.strftime("%H:%M")
    if isinstance(start_obj.get("date"), str):
        return "all day"
    return "(unknown)"


def _extract_event(raw: dict[str, Any]) -> CalendarEvent:
    """Convert one upstream StructuredEvent dict into a CalendarEvent."""
    summary_raw = raw.get("summary")
    summary = (
        summary_raw if isinstance(summary_raw, str) and summary_raw
        else "(no title)"
    )
    location_raw = raw.get("location")
    location = (
        location_raw if isinstance(location_raw, str) and location_raw
        else None
    )
    start = raw.get("start")
    start_display = (
        _format_start_display(start) if isinstance(start, dict)
        else "(unknown)"
    )
    return CalendarEvent(
        summary=summary, start_display=start_display, location=location,
    )


def parse_events_from_mcp_payload(
    payload: str,
) -> list[CalendarEvent] | None:
    """Parse a ``ListEventsResponse`` payload into CalendarEvent list.

    Returns ``None`` when the payload is not a success envelope (error
    envelope, malformed JSON, or missing ``events`` key).
    """
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict) or "error" in parsed:
        return None
    events_raw = parsed.get("events")
    if not isinstance(events_raw, list):
        return None
    return [_extract_event(item) for item in events_raw if isinstance(item, dict)]


def _format_event_line(event: CalendarEvent) -> str:
    """Render one CalendarEvent as a short dash line."""
    if event.start_display == "all day":
        head = f"- all day: {event.summary}"
    else:
        head = f"- {event.start_display} {event.summary}"
    return f"{head} ({event.location})" if event.location else head


def format_calendar_block(events: list[CalendarEvent]) -> str:
    """Format CalendarEvents into the ``### Today's Calendar`` block.

    Returns a "free day" line when the list is empty. Truncates to
    ``MAX_EVENTS_DISPLAYED`` items with no overflow indicator — morning
    check-ins stay visually light.
    """
    if not events:
        return f"{CALENDAR_HEADING}\n{FREE_DAY_LINE}"
    visible = events[:MAX_EVENTS_DISPLAYED]
    lines = [CALENDAR_HEADING]
    lines.extend(_format_event_line(evt) for evt in visible)
    return "\n".join(lines)


def format_unavailable_block() -> str:
    """Return the ``### Today's Calendar`` block for the OAuth-failure path."""
    return f"{CALENDAR_HEADING}\n{UNAVAILABLE_LINE}"


def inject_calendar_block(system_content: str, block: str) -> str:
    """Append the calendar block to the system prompt."""
    if not block:
        return system_content
    return system_content + "\n\n" + block


def should_log_error(
    last_log_at: datetime | None, now: datetime,
) -> bool:
    """Return True when the caller may emit the next rate-limited WARNING."""
    if last_log_at is None:
        return True
    return (now - last_log_at) >= ERROR_LOG_INTERVAL


class CalendarContextHook:
    """Injects today's calendar into morning check-in system prompts.

    Fourth in the pre-iteration chain (after ``SchedulingHook``, before
    ``BufferHook``). Relies on ``SchedulingHook`` having already written
    an ``## Active Check-In:`` heading; if none is present, this hook
    returns unchanged. ``get_current_datetime`` must return a tz-aware
    ``datetime`` — both the MCP window and the rate-limiter use it.
    """

    def __init__(
        self,
        cache: CalendarCache,
        client: CalendarMCPClient,
        is_scheduled_session: Callable[[], bool],
        get_cognitive_state: Callable[[], StateName],
        get_current_datetime: Callable[[], datetime],
        hours_ahead: int = MORNING_FETCH_HOURS_AHEAD,
    ) -> None:
        self._cache = cache
        self._client = client
        self._is_scheduled_session = is_scheduled_session
        self._get_cognitive_state = get_cognitive_state
        self._get_current_datetime = get_current_datetime
        self._hours_ahead = hours_ahead
        self._last_error_log_at: datetime | None = None

    async def before_iteration(self, context: HookContext) -> None:
        """Fetch events and inject the calendar block, swallowing errors."""
        try:
            await self._process(context)
        except Exception as exc:
            log.warning("Calendar hook failed: %s", exc)

    async def _process(self, context: HookContext) -> None:
        messages = context.messages
        if not messages:
            return
        if not self._is_scheduled_session():
            return
        if messages[0].get("role") != "system":
            return

        system_content = messages[0]["content"]
        if not detect_morning_checkin(system_content):
            return

        state = self._get_cognitive_state()
        if not is_state_allowed(state):
            log.info("Calendar injection skipped (state=%s)", state)
            return

        payload = await self._fetch_events_payload()
        block = self._build_block(payload)
        messages[0] = {
            **messages[0],
            "content": inject_calendar_block(system_content, block),
        }
        log.info("Injected calendar block (state=%s)", state)

    async def _fetch_events_payload(self) -> str:
        tz = resolve_user_timezone()
        now = self._get_current_datetime()
        arguments: dict[str, Any] = {
            "calendarId": DEFAULT_CALENDAR_ID,
            "timeMin": format_iso_for_mcp(now),
            "timeMax": format_iso_for_mcp(
                now + timedelta(hours=self._hours_ahead)
            ),
            "timeZone": str(tz),
        }
        cache_key = build_cache_key(
            CACHE_TOOL_KEY,
            {
                "hours_ahead": self._hours_ahead,
                "calendar_id": DEFAULT_CALENDAR_ID,
            },
        )
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        result = await self._client.call(UPSTREAM_LIST_EVENTS, arguments)
        self._cache.set(cache_key, result)
        return result

    def _build_block(self, payload: str) -> str:
        if is_error_envelope(payload):
            self._maybe_log_error(payload)
            return format_unavailable_block()
        events = parse_events_from_mcp_payload(payload)
        if events is None:
            self._maybe_log_error(payload)
            return format_unavailable_block()
        return format_calendar_block(events)

    def _maybe_log_error(self, payload: str) -> None:
        now = self._get_current_datetime()
        if not should_log_error(self._last_error_log_at, now):
            return
        log.warning(
            "Calendar fetch failed (rate-limited 1/hr): %s",
            payload[:ERROR_LOG_PAYLOAD_LIMIT],
        )
        self._last_error_log_at = now
