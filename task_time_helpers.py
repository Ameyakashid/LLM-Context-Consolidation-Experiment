"""Formatting and time-parsing helpers for task_tools.

Hosts the pure helpers that sit between the LLM-facing task tools and
the TaskStore: human-readable task formatting, ISO 8601 parsing, and
timezone-aware natural-language due-date resolution. Split out of
task_tools.py so both files stay under the 300-line cap.
"""

import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from nl_time_parser import ParseResult, parse_time_phrase
from task_store import Task


def format_task(task: Task) -> str:
    lines = [
        f"[{task.id[:8]}] {task.title}",
        f"  Status: {task.status} | Priority: {task.priority}",
    ]
    if task.description:
        lines.append(f"  Description: {task.description}")
    if task.due_date:
        lines.append(f"  Due: {task.due_date.isoformat()}")
    if task.tags:
        lines.append(f"  Tags: {', '.join(task.tags)}")
    return "\n".join(lines)


def format_task_list(tasks: list[Task]) -> str:
    if not tasks:
        return "No tasks found."
    return "\n\n".join(format_task(t) for t in tasks)


def parse_iso_date(value: str) -> datetime:
    """Parse an ISO 8601 date string into a timezone-aware datetime.

    Naive inputs (no offset) default to UTC — machine-safe but ambiguous;
    natural-language inputs use the user's configured timezone instead.
    """
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError(
            f"Invalid date format: '{value}'. "
            "Expected ISO 8601 format (e.g. '2025-12-31' or '2025-12-31T14:00:00Z')."
        ) from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def get_user_timezone() -> ZoneInfo:
    """Resolve the user's configured IANA timezone from NANOBOT_TIMEZONE.

    Falls back to UTC when unset — unambiguous default for deployments
    that haven't configured the env var yet. ZoneInfoNotFoundError from
    an unknown IANA name propagates with its original message.
    """
    tz_name = os.environ.get("NANOBOT_TIMEZONE", "UTC")
    return ZoneInfo(tz_name)


def resolve_due_date(value: str, now: datetime) -> datetime:
    """Resolve a due-date string via ISO 8601 first, natural language second.

    Passes through tz-aware ISO 8601 on success. On ISO failure, falls back
    to `parse_time_phrase`. `None` from the NL parser (no recognisable time
    tokens) becomes a ValueError whose message is sub-03's parse contract.
    """
    if now.tzinfo is None:
        raise ValueError("resolve_due_date requires tz-aware 'now'")
    try:
        return parse_iso_date(value)
    except ValueError:
        pass
    result: ParseResult | None = parse_time_phrase(value, now)
    if result is None:
        raise ValueError(
            f"could not parse time phrase '{value}'. "
            "Expected ISO 8601 (e.g. '2025-12-31') or natural-language phrase "
            "(e.g. 'tomorrow at 6pm', 'in 2 hours', 'next Friday')."
        )
    return result.when
