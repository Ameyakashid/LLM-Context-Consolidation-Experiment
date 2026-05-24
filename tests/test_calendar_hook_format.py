"""Pure-function tests for calendar_hook formatters + parsers.

All tests in this module hit stateless helpers — no hook instance,
no cache, no client. Guarantees formatter/parser stability across
edits to the orchestration layer.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from calendar_hook import (
    ALLOWED_STATES,
    CALENDAR_CHECKIN_TRIGGERS,
    CALENDAR_HEADING,
    FREE_DAY_LINE,
    MAX_EVENTS_DISPLAYED,
    UNAVAILABLE_LINE,
    CalendarEvent,
    detect_morning_checkin,
    format_calendar_block,
    format_unavailable_block,
    inject_calendar_block,
    is_error_envelope,
    is_state_allowed,
    parse_events_from_mcp_payload,
    should_log_error,
)


class TestDetectMorningCheckin:
    def test_detects_motivation_heading(self) -> None:
        content = "# System\n\n## Active Check-In: Morning Motivation\nBody"
        assert detect_morning_checkin(content) is True

    def test_detects_plan_heading(self) -> None:
        content = "## Active Check-In: Morning Plan\nBody"
        assert detect_morning_checkin(content) is True

    def test_ignores_afternoon_heading(self) -> None:
        content = "## Active Check-In: Afternoon Check\nBody"
        assert detect_morning_checkin(content) is False

    def test_ignores_evening_heading(self) -> None:
        content = "## Active Check-In: Evening Review\nBody"
        assert detect_morning_checkin(content) is False

    def test_no_heading_returns_false(self) -> None:
        assert detect_morning_checkin("# System\nno checkin here") is False

    def test_triggers_tuple_is_the_two_morning_ids(self) -> None:
        assert set(CALENDAR_CHECKIN_TRIGGERS) == {
            "morning_motivation", "morning_plan",
        }


class TestIsStateAllowed:
    def test_baseline_allowed(self) -> None:
        assert is_state_allowed("baseline") is True

    def test_focus_allowed(self) -> None:
        assert is_state_allowed("focus") is True

    def test_avoidance_allowed(self) -> None:
        assert is_state_allowed("avoidance") is True

    def test_rsd_allowed(self) -> None:
        assert is_state_allowed("rsd") is True

    def test_hyperfocus_blocked(self) -> None:
        assert is_state_allowed("hyperfocus") is False

    def test_overwhelm_blocked(self) -> None:
        assert is_state_allowed("overwhelm") is False

    def test_allowed_set_excludes_hyperfocus_and_overwhelm(self) -> None:
        assert "hyperfocus" not in ALLOWED_STATES
        assert "overwhelm" not in ALLOWED_STATES


class TestIsErrorEnvelope:
    def test_unavailable_envelope_true(self) -> None:
        payload = json.dumps({"error": "calendar_unavailable", "detail": "x"})
        assert is_error_envelope(payload) is True

    def test_mcp_failure_envelope_true(self) -> None:
        payload = json.dumps({"error": "calendar_mcp_failure", "detail": "y"})
        assert is_error_envelope(payload) is True

    def test_success_payload_false(self) -> None:
        payload = json.dumps({"events": [], "totalCount": 0})
        assert is_error_envelope(payload) is False

    def test_malformed_json_false(self) -> None:
        assert is_error_envelope("not json at all") is False

    def test_empty_string_false(self) -> None:
        assert is_error_envelope("") is False


class TestParseEventsFromMcpPayload:
    def test_empty_events_list(self) -> None:
        parsed = parse_events_from_mcp_payload('{"events": []}')
        assert parsed == []

    def test_single_timed_event(self) -> None:
        payload = json.dumps({
            "events": [
                {
                    "summary": "Standup",
                    "start": {"dateTime": "2026-04-20T09:00:00+00:00"},
                    "location": "Zoom",
                },
            ],
        })
        parsed = parse_events_from_mcp_payload(payload)
        assert parsed is not None
        assert len(parsed) == 1
        assert parsed[0].summary == "Standup"
        assert parsed[0].start_display == "09:00"
        assert parsed[0].location == "Zoom"

    def test_all_day_event(self) -> None:
        payload = json.dumps({
            "events": [{"summary": "Holiday", "start": {"date": "2026-04-20"}}],
        })
        parsed = parse_events_from_mcp_payload(payload)
        assert parsed is not None
        assert parsed[0].start_display == "all day"
        assert parsed[0].location is None

    def test_missing_summary_falls_back(self) -> None:
        payload = json.dumps({
            "events": [{"start": {"dateTime": "2026-04-20T09:00:00+00:00"}}],
        })
        parsed = parse_events_from_mcp_payload(payload)
        assert parsed is not None
        assert parsed[0].summary == "(no title)"

    def test_missing_start_block(self) -> None:
        payload = json.dumps({"events": [{"summary": "Mystery"}]})
        parsed = parse_events_from_mcp_payload(payload)
        assert parsed is not None
        assert parsed[0].start_display == "(unknown)"

    def test_malformed_start_datetime(self) -> None:
        payload = json.dumps({
            "events": [
                {"summary": "Broken", "start": {"dateTime": "not-a-date"}},
            ],
        })
        parsed = parse_events_from_mcp_payload(payload)
        assert parsed is not None
        assert parsed[0].start_display == "(unknown)"

    def test_trailing_z_parsed(self) -> None:
        payload = json.dumps({
            "events": [
                {"summary": "UTC event", "start": {"dateTime": "2026-04-20T13:30:00Z"}},
            ],
        })
        parsed = parse_events_from_mcp_payload(payload)
        assert parsed is not None
        assert parsed[0].start_display == "13:30"

    def test_error_envelope_returns_none(self) -> None:
        payload = json.dumps({"error": "calendar_unavailable", "detail": "x"})
        assert parse_events_from_mcp_payload(payload) is None

    def test_malformed_json_returns_none(self) -> None:
        assert parse_events_from_mcp_payload("not json") is None

    def test_missing_events_key_returns_none(self) -> None:
        assert parse_events_from_mcp_payload('{"totalCount": 0}') is None

    def test_non_dict_items_ignored(self) -> None:
        payload = json.dumps({"events": ["not a dict", None, {"summary": "ok"}]})
        parsed = parse_events_from_mcp_payload(payload)
        assert parsed is not None
        assert len(parsed) == 1
        assert parsed[0].summary == "ok"


class TestFormatCalendarBlock:
    def test_empty_list_is_free_day(self) -> None:
        block = format_calendar_block([])
        assert block == f"{CALENDAR_HEADING}\n{FREE_DAY_LINE}"

    def test_single_timed_event(self) -> None:
        events = [CalendarEvent(
            summary="Standup", start_display="09:00", location=None,
        )]
        block = format_calendar_block(events)
        assert block == f"{CALENDAR_HEADING}\n- 09:00 Standup"

    def test_event_with_location(self) -> None:
        events = [CalendarEvent(
            summary="Coffee", start_display="10:30", location="Downtown",
        )]
        assert "(Downtown)" in format_calendar_block(events)

    def test_all_day_event_shape(self) -> None:
        events = [CalendarEvent(
            summary="Holiday", start_display="all day", location=None,
        )]
        assert "- all day: Holiday" in format_calendar_block(events)

    def test_truncates_to_max_events(self) -> None:
        events = [
            CalendarEvent(
                summary=f"Event {i}",
                start_display=f"{9 + i:02d}:00",
                location=None,
            )
            for i in range(MAX_EVENTS_DISPLAYED + 3)
        ]
        block = format_calendar_block(events)
        lines = block.splitlines()
        assert len(lines) == MAX_EVENTS_DISPLAYED + 1

    def test_starts_with_heading(self) -> None:
        block = format_calendar_block([])
        assert block.startswith(CALENDAR_HEADING)


class TestFormatUnavailableBlock:
    def test_contains_heading_and_unavailable_line(self) -> None:
        block = format_unavailable_block()
        assert block.startswith(CALENDAR_HEADING)
        assert UNAVAILABLE_LINE in block

    def test_mentions_calendar_md(self) -> None:
        assert "CALENDAR.md" in format_unavailable_block()


class TestInjectCalendarBlock:
    def test_appends_with_double_newline(self) -> None:
        result = inject_calendar_block("# System\n\nBody", CALENDAR_HEADING)
        assert result == f"# System\n\nBody\n\n{CALENDAR_HEADING}"

    def test_empty_block_returns_unchanged(self) -> None:
        assert inject_calendar_block("original", "") == "original"


class TestShouldLogError:
    def test_first_time_always_logs(self) -> None:
        now = datetime(2026, 4, 20, 9, 0, 0, tzinfo=ZoneInfo("UTC"))
        assert should_log_error(None, now) is True

    def test_suppresses_within_hour(self) -> None:
        base = datetime(2026, 4, 20, 9, 0, 0, tzinfo=ZoneInfo("UTC"))
        later = base + timedelta(minutes=30)
        assert should_log_error(base, later) is False

    def test_allows_after_hour(self) -> None:
        base = datetime(2026, 4, 20, 9, 0, 0, tzinfo=ZoneInfo("UTC"))
        later = base + timedelta(hours=1, seconds=1)
        assert should_log_error(base, later) is True

    def test_exactly_one_hour_allows(self) -> None:
        base = datetime(2026, 4, 20, 9, 0, 0, tzinfo=ZoneInfo("UTC"))
        later = base + timedelta(hours=1)
        assert should_log_error(base, later) is True
