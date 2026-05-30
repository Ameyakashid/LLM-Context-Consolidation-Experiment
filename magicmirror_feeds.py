"""Markdown/JSON feed renderers + atomic writers for the Cabinet display.

Pure renderers (``render_tasks_markdown``, ``render_state_buffers_markdown``,
``render_schedule_markdown``, ``render_voices_markdown``) turn the bot's
domain models plus a tz-aware ``now`` into the text the Cabinet frontend
polls; the ``write_*`` helpers write each feed atomically (tmp-file +
rename) into the Cabinet's ``feeds/`` dir.

Rendering is deliberately emoji-free — the same plain-text look that works
in chat works on the tablet.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta
from pathlib import Path

from buffer_store import Buffer
from checkin_schedule import CheckInEntry
from state_detection import StateName
from task_store import Task

log = logging.getLogger(__name__)

TASKS_FEED_FILENAME: str = "tasks.md"
STATE_BUFFERS_FEED_FILENAME: str = "state_buffers.md"
SCHEDULE_FEED_FILENAME: str = "schedule.md"
VOICES_FEED_FILENAME: str = "voices.md"
NEWS_FEED_FILENAME: str = "news.md"
FLASHCARDS_FEED_FILENAME: str = "flashcards.json"

_BLOCKED_TAG: str = "blocked"
_LOW_MARKER: str = " (low)"

_EMPTY_ACTIVE: str = "_No active tasks._"
_EMPTY_COMPLETED: str = "_None completed yet today._"
_EMPTY_BLOCKED: str = "_No blocked tasks._"
_EMPTY_BUFFERS: str = "_No active buffers._"
_EMPTY_SCHEDULE: str = "_No check-ins configured._"


# ---------------------------------------------------------------------------
# Tasks renderer
# ---------------------------------------------------------------------------

def _is_blocked(task: Task) -> bool:
    return _BLOCKED_TAG in task.tags


def _is_completed_today(task: Task, now: datetime) -> bool:
    if task.status != "done":
        return False
    return task.updated_at.date() == now.date()


def _active_sort_key(task: Task) -> tuple[int, datetime, str]:
    """Sort key: tasks with due date first (by due), then undated by title."""
    if task.due_date is None:
        return (1, datetime.max, task.title)
    due = task.due_date
    if due.tzinfo is not None:
        due = due.replace(tzinfo=None)
    return (0, due, task.title)


def _render_task_line(task: Task) -> str:
    line = f"- **{task.title}** ({task.priority})"
    if task.due_date is not None:
        line += f" — due {task.due_date.strftime('%Y-%m-%d %H:%M')}"
    return line


def _render_task_group(
    heading: str,
    tasks: list[Task],
    empty_marker: str,
) -> list[str]:
    lines = [heading, ""]
    if tasks:
        lines.extend(_render_task_line(task) for task in tasks)
    else:
        lines.append(empty_marker)
    return lines


def render_tasks_markdown(tasks: list[Task], now: datetime) -> str:
    """Render the ``tasks.md`` feed.

    Three groups, in order: active (pending or in_progress, not tagged
    ``blocked``), completed-today (status=done with today's ``updated_at``),
    and blocked (tag ``blocked``, any status). Active sorted by due date
    then title; blocked by title.
    """
    blocked = sorted(
        [task for task in tasks if _is_blocked(task)],
        key=lambda task: task.title,
    )
    active = sorted(
        [
            task for task in tasks
            if task.status in ("pending", "in_progress")
            and not _is_blocked(task)
        ],
        key=_active_sort_key,
    )
    completed = sorted(
        [
            task for task in tasks
            if _is_completed_today(task, now) and not _is_blocked(task)
        ],
        key=lambda task: task.updated_at,
    )
    sections: list[str] = []
    sections.extend(_render_task_group("## Active", active, _EMPTY_ACTIVE))
    sections.append("")
    sections.extend(
        _render_task_group("## Completed today", completed, _EMPTY_COMPLETED)
    )
    sections.append("")
    sections.extend(_render_task_group("## Blocked", blocked, _EMPTY_BLOCKED))
    return "\n".join(sections) + "\n"


# ---------------------------------------------------------------------------
# State + buffers renderer
# ---------------------------------------------------------------------------

def _render_buffer_line(buffer: Buffer) -> str:
    low = _LOW_MARKER if buffer.buffer_level <= buffer.alert_threshold else ""
    return (
        f"- **{buffer.name}**: "
        f"{buffer.buffer_level}/{buffer.buffer_capacity}{low}"
    )


def render_state_buffers_markdown(
    state: StateName,
    buffers: list[Buffer],
    now: datetime,
) -> str:
    """Render the ``state_buffers.md`` feed.

    ``now`` is accepted for signature symmetry with the other renderers and
    for future timestamping; the current output shape does not use it.
    """
    del now
    active = sorted(
        [buffer for buffer in buffers if buffer.status == "active"],
        key=lambda buffer: buffer.name,
    )
    lines: list[str] = [f"## Cognitive state: {state}", "", "## Buffers", ""]
    if active:
        lines.extend(_render_buffer_line(buffer) for buffer in active)
    else:
        lines.append(_EMPTY_BUFFERS)
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Schedule renderer
# ---------------------------------------------------------------------------

def _format_duration(delta: timedelta) -> str:
    total = int(delta.total_seconds())
    if total < 0:
        total = 0
    hours, remainder = divmod(total, 3600)
    minutes = remainder // 60
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _describe_next_due(entry: CheckInEntry, now_naive: datetime) -> str:
    today = now_naive.date()
    target_today = datetime.combine(today, entry.target_time)
    target_tomorrow = datetime.combine(
        today + timedelta(days=1), entry.target_time
    )

    if entry.last_run_date == today:
        return (
            "done today, next tomorrow in "
            f"{_format_duration(target_tomorrow - now_naive)}"
        )

    if now_naive < target_today:
        return f"due in {_format_duration(target_today - now_naive)}"

    elapsed = now_naive - target_today
    if elapsed <= timedelta(minutes=entry.staleness_minutes):
        return f"overdue {_format_duration(elapsed)}"

    return (
        "missed today, next tomorrow in "
        f"{_format_duration(target_tomorrow - now_naive)}"
    )


def _schedule_sort_key(entry: CheckInEntry) -> time:
    return entry.target_time


def render_schedule_markdown(
    schedules: list[CheckInEntry],
    now: datetime,
) -> str:
    """Render the ``schedule.md`` feed."""
    enabled = sorted(
        [entry for entry in schedules if entry.is_enabled],
        key=_schedule_sort_key,
    )
    lines: list[str] = ["## Check-in schedule", ""]
    if not enabled:
        lines.append(_EMPTY_SCHEDULE)
        return "\n".join(lines) + "\n"

    now_naive = now.replace(tzinfo=None) if now.tzinfo is not None else now
    for entry in enabled:
        target = entry.target_time.strftime("%H:%M")
        lines.append(
            f"- **{entry.display_name}** — target {target} — "
            f"{_describe_next_due(entry, now_naive)}"
        )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Voices renderer (Cabinet inner-voices feed)
# ---------------------------------------------------------------------------

def render_voices_markdown(voices: list[tuple[str, str]]) -> str:
    """Render the ``voices.md`` feed the Cabinet's voice strip reads.

    ``voices`` is a list of ``(who, line)`` pairs; ``who`` is upper-cased
    (LOGIC / EMPATHY / VOLITION drive the strip's colors). Empty lines are
    skipped. Returns ``""`` when there is nothing to show so the display
    falls back to its client-side auto-generated lines.
    """
    rows: list[str] = []
    for who, line in voices:
        text = (line or "").strip()
        if not text:
            continue
        rows.append(f"- {who.strip().upper()} — {text}")
    if not rows:
        return ""
    return "\n".join(["## Voices", "", *rows]) + "\n"


# ---------------------------------------------------------------------------
# Atomic writer
# ---------------------------------------------------------------------------

def _atomic_write(path: Path, content: str) -> None:
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(content, encoding="utf-8", newline="\n")
    tmp_path.replace(path)


def write_feeds(
    feed_dir: Path,
    tasks_md: str,
    state_buffers_md: str,
    schedule_md: str,
) -> None:
    """Write the three feed files atomically into ``feed_dir``.

    Each file is written to a sibling ``.tmp`` then renamed over the target
    via ``Path.replace`` (cross-platform ``os.replace``). A failure on one
    file leaves earlier files at their new content and later files
    untouched — the caller sees the exception and can re-run.
    """
    feed_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write(feed_dir / TASKS_FEED_FILENAME, tasks_md)
    _atomic_write(feed_dir / STATE_BUFFERS_FEED_FILENAME, state_buffers_md)
    _atomic_write(feed_dir / SCHEDULE_FEED_FILENAME, schedule_md)


def write_voices_feed(feed_dir: Path, voices_md: str) -> None:
    """Atomically write the ``voices.md`` feed into ``feed_dir``."""
    feed_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write(feed_dir / VOICES_FEED_FILENAME, voices_md)


def write_news_feed(feed_dir: Path, news_md: str) -> None:
    """Atomically write the ``news.md`` feed into ``feed_dir``."""
    feed_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write(feed_dir / NEWS_FEED_FILENAME, news_md)


def write_flashcards_feed(feed_dir: Path, flashcards_json: str) -> None:
    """Atomically write the ``flashcards.json`` pool into ``feed_dir``."""
    feed_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write(feed_dir / FLASHCARDS_FEED_FILENAME, flashcards_json)
