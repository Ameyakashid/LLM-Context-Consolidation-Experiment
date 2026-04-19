"""Golden-text tests for the MagicMirror markdown-feed renderers.

Atomic-write and feed-dir tests live in ``test_magicmirror_feeds_write.py``.
"""

from __future__ import annotations

import textwrap
from datetime import date, datetime, time, timezone

from buffer_store import Buffer
from checkin_schedule import CheckInEntry
from magicmirror_feeds import (
    render_schedule_markdown,
    render_state_buffers_markdown,
    render_tasks_markdown,
)
from task_store import Task

_UTC = timezone.utc


def _make_task(
    title: str,
    status: str = "pending",
    priority: str = "medium",
    due_date: datetime | None = None,
    tags: list[str] | None = None,
    updated_at: datetime | None = None,
) -> Task:
    created = datetime(2026, 4, 18, 8, 0, tzinfo=_UTC)
    return Task(
        id=f"id-{title.lower().replace(' ', '-')}",
        title=title,
        description=None,
        status=status,  # type: ignore[arg-type]
        priority=priority,  # type: ignore[arg-type]
        created_at=created,
        updated_at=updated_at or created,
        due_date=due_date,
        tags=list(tags or []),
    )


def _make_buffer(
    name: str,
    level: int,
    capacity: int,
    threshold: int,
    status: str = "active",
) -> Buffer:
    created = datetime(2026, 4, 1, 0, 0, tzinfo=_UTC)
    return Buffer(
        id=f"buf-{name.lower().replace(' ', '-')}",
        name=name,
        buffer_level=level,
        buffer_capacity=capacity,
        recurrence_interval_days=7,
        next_due_date=date(2026, 4, 25),
        alert_threshold=threshold,
        status=status,  # type: ignore[arg-type]
        created_at=created,
        updated_at=created,
    )


def _make_checkin(
    type_id: str,
    target: time,
    display: str,
    staleness: int = 120,
    is_enabled: bool = True,
    last_run_date: date | None = None,
) -> CheckInEntry:
    return CheckInEntry(
        type_id=type_id,  # type: ignore[arg-type]
        display_name=display,
        target_time=target,
        staleness_minutes=staleness,
        is_enabled=is_enabled,
        last_run_date=last_run_date,
    )


class TestRenderTasksMarkdown:
    def test_full_grouping_golden(self) -> None:
        now = datetime(2026, 4, 19, 15, 0, tzinfo=_UTC)
        tasks = [
            _make_task(
                "Write report",
                status="pending",
                priority="high",
                due_date=datetime(2026, 4, 20, 17, 0, tzinfo=_UTC),
            ),
            _make_task(
                "Groceries",
                status="in_progress",
                priority="medium",
                due_date=datetime(2026, 4, 19, 18, 0, tzinfo=_UTC),
            ),
            _make_task(
                "Read book",
                status="done",
                priority="low",
                updated_at=datetime(2026, 4, 19, 11, 30, tzinfo=_UTC),
            ),
            _make_task(
                "Stalled refactor",
                status="pending",
                priority="high",
                tags=["blocked"],
            ),
        ]
        output = render_tasks_markdown(tasks, now)
        expected = textwrap.dedent("""\
            ## Active

            - **Groceries** (medium) — due 2026-04-19 18:00
            - **Write report** (high) — due 2026-04-20 17:00

            ## Completed today

            - **Read book** (low)

            ## Blocked

            - **Stalled refactor** (high)
            """)
        assert output == expected

    def test_empty_groups_emit_placeholders(self) -> None:
        now = datetime(2026, 4, 19, 15, 0, tzinfo=_UTC)
        output = render_tasks_markdown([], now)
        assert "_No active tasks._" in output
        assert "_None completed yet today._" in output
        assert "_No blocked tasks._" in output

    def test_completed_tasks_from_prior_day_not_listed(self) -> None:
        now = datetime(2026, 4, 19, 10, 0, tzinfo=_UTC)
        tasks = [
            _make_task(
                "Done yesterday",
                status="done",
                updated_at=datetime(2026, 4, 18, 21, 0, tzinfo=_UTC),
            ),
        ]
        output = render_tasks_markdown(tasks, now)
        assert "Done yesterday" not in output
        assert "_None completed yet today._" in output

    def test_pure_same_inputs_same_output(self) -> None:
        now = datetime(2026, 4, 19, 15, 0, tzinfo=_UTC)
        tasks = [_make_task("One"), _make_task("Two")]
        assert render_tasks_markdown(tasks, now) == render_tasks_markdown(
            tasks, now
        )

    def test_blocked_tag_excludes_from_active_group(self) -> None:
        now = datetime(2026, 4, 19, 15, 0, tzinfo=_UTC)
        tasks = [
            _make_task("Pending work", status="pending"),
            _make_task("Waiting on Bob", status="pending", tags=["blocked"]),
        ]
        output = render_tasks_markdown(tasks, now)
        active_section, _, rest = output.partition("## Completed today")
        blocked_section = rest.partition("## Blocked")[2]
        assert "Pending work" in active_section
        assert "Waiting on Bob" not in active_section
        assert "Waiting on Bob" in blocked_section


class TestRenderStateBuffersMarkdown:
    def test_golden(self) -> None:
        now = datetime(2026, 4, 19, 15, 0, tzinfo=_UTC)
        buffers = [
            _make_buffer("dog food", level=2, capacity=10, threshold=3),
            _make_buffer("laundry pods", level=8, capacity=10, threshold=3),
            _make_buffer("archived item", level=0, capacity=5,
                         threshold=1, status="archived"),
        ]
        output = render_state_buffers_markdown("focus", buffers, now)
        expected = textwrap.dedent("""\
            ## Cognitive state: focus

            ## Buffers

            - **dog food**: 2/10 (low)
            - **laundry pods**: 8/10
            """)
        assert output == expected

    def test_at_threshold_flags_low(self) -> None:
        now = datetime(2026, 4, 19, 15, 0, tzinfo=_UTC)
        buffers = [_make_buffer("coffee", level=3, capacity=10, threshold=3)]
        output = render_state_buffers_markdown("baseline", buffers, now)
        assert "3/10 (low)" in output

    def test_empty_buffers_emit_placeholder(self) -> None:
        now = datetime(2026, 4, 19, 15, 0, tzinfo=_UTC)
        output = render_state_buffers_markdown("baseline", [], now)
        assert "_No active buffers._" in output

    def test_state_header_included(self) -> None:
        now = datetime(2026, 4, 19, 15, 0, tzinfo=_UTC)
        output = render_state_buffers_markdown("overwhelm", [], now)
        assert "## Cognitive state: overwhelm" in output


class TestRenderScheduleMarkdown:
    def test_golden_with_future_and_past(self) -> None:
        now = datetime(2026, 4, 19, 10, 45, tzinfo=_UTC)
        schedules = [
            _make_checkin("morning_plan", time(9, 0), "Morning Plan"),
            _make_checkin("afternoon_check", time(14, 0), "Afternoon Check"),
            _make_checkin(
                "evening_review", time(20, 0), "Evening Review",
                is_enabled=False,
            ),
        ]
        output = render_schedule_markdown(schedules, now)
        expected = textwrap.dedent("""\
            ## Check-in schedule

            - **Morning Plan** — target 09:00 — overdue 1h 45m
            - **Afternoon Check** — target 14:00 — due in 3h 15m
            """)
        assert output == expected

    def test_done_today_shows_tomorrow(self) -> None:
        now = datetime(2026, 4, 19, 10, 0, tzinfo=_UTC)
        schedules = [
            _make_checkin(
                "morning_plan", time(9, 0), "Morning Plan",
                last_run_date=date(2026, 4, 19),
            ),
        ]
        output = render_schedule_markdown(schedules, now)
        assert "done today" in output
        assert "tomorrow" in output

    def test_past_staleness_shows_missed(self) -> None:
        now = datetime(2026, 4, 19, 13, 0, tzinfo=_UTC)
        schedules = [
            _make_checkin(
                "morning_plan", time(9, 0), "Morning Plan",
                staleness=120,
            ),
        ]
        output = render_schedule_markdown(schedules, now)
        assert "missed today" in output

    def test_empty_schedule_emits_placeholder(self) -> None:
        now = datetime(2026, 4, 19, 10, 0, tzinfo=_UTC)
        output = render_schedule_markdown([], now)
        assert "_No check-ins configured._" in output

    def test_all_disabled_emits_placeholder(self) -> None:
        now = datetime(2026, 4, 19, 10, 0, tzinfo=_UTC)
        schedules = [
            _make_checkin(
                "morning_plan", time(9, 0), "Morning Plan", is_enabled=False,
            ),
        ]
        output = render_schedule_markdown(schedules, now)
        assert "_No check-ins configured._" in output
