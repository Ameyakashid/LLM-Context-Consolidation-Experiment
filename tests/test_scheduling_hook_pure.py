"""Tests for scheduling hook — pure formatting functions."""

from datetime import datetime, timezone

import pytest

from memory_store import MemoryEntry
from schedule_engine import CheckInContext, ScheduleAction
from scheduling_hook import (
    format_checkin_prompt,
    format_task_summary,
    inject_checkin_into_prompt,
)
from task_store import Task


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_task(
    title: str,
    status: str,
    priority: str,
    due_date: datetime | None,
) -> Task:
    now = datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc)
    return Task(
        id=title.lower().replace(" ", "_"),
        title=title,
        status=status,  # type: ignore[arg-type]
        priority=priority,  # type: ignore[arg-type]
        created_at=now,
        updated_at=now,
        due_date=due_date,
    )


def _make_memory(category: str, content: str) -> MemoryEntry:
    return MemoryEntry(
        id="abcdef1234567890abcdef1234567890",
        category=category,  # type: ignore[arg-type]
        content=content,
        created_at=datetime(2026, 4, 10, 8, 0, tzinfo=timezone.utc),
        metadata={},
    )


# ---------------------------------------------------------------------------
# format_task_summary
# ---------------------------------------------------------------------------

class TestFormatTaskSummary:

    def test_empty_context(self) -> None:
        ctx = CheckInContext(checkin_type="morning_motivation")
        assert format_task_summary(ctx) == []

    def test_pending_tasks(self) -> None:
        ctx = CheckInContext(
            checkin_type="morning_plan",
            pending_tasks=[
                _make_task("Fix bug", "pending", "high", None),
                _make_task("Write docs", "pending", "low", None),
            ],
        )
        lines = format_task_summary(ctx)
        assert len(lines) == 1
        assert "2 pending" in lines[0]
        assert "Fix bug" in lines[0]

    def test_in_progress_tasks(self) -> None:
        ctx = CheckInContext(
            checkin_type="afternoon_check",
            in_progress_tasks=[
                _make_task("API work", "in_progress", "medium", None),
            ],
        )
        lines = format_task_summary(ctx)
        assert len(lines) == 1
        assert "API work" in lines[0]

    def test_completed_and_overdue(self) -> None:
        ctx = CheckInContext(
            checkin_type="evening_review",
            completed_today_tasks=[
                _make_task("Done task", "done", "low", None),
            ],
            overdue_tasks=[
                _make_task("Late task", "pending", "high", None),
            ],
        )
        lines = format_task_summary(ctx)
        assert len(lines) == 2
        assert "1 completed" in lines[0]
        assert "1 overdue" in lines[1]

    def test_deadline_and_energy_memories(self) -> None:
        ctx = CheckInContext(
            checkin_type="morning_plan",
            deadline_memories=[_make_memory("deadline", "Report due Monday")],
            energy_memories=[_make_memory("energy_state", "Feeling drained")],
        )
        lines = format_task_summary(ctx)
        assert len(lines) == 2
        assert "1 upcoming deadlines" in lines[0]
        assert "Feeling drained" in lines[1]


# ---------------------------------------------------------------------------
# format_checkin_prompt
# ---------------------------------------------------------------------------

class TestFormatCheckinPrompt:

    def test_fire_action_with_context(self) -> None:
        action = ScheduleAction(
            action="fire", reason="baseline state — proceed normally"
        )
        ctx = CheckInContext(
            checkin_type="morning_plan",
            pending_tasks=[_make_task("Top task", "pending", "high", None)],
        )
        result = format_checkin_prompt("morning_plan", action, ctx)
        assert "Morning Plan" in result
        assert "fire" in result
        assert "Top task" in result
        assert "Deliver this check-in" in result

    def test_modify_action_includes_scope(self) -> None:
        action = ScheduleAction(
            action="modify",
            reason="avoidance — reduce task scope",
            modified_scope="reduced",
        )
        ctx = CheckInContext(checkin_type="afternoon_check")
        result = format_checkin_prompt("afternoon_check", action, ctx)
        assert "Modified scope: reduced" in result

    def test_empty_context_no_context_section(self) -> None:
        action = ScheduleAction(
            action="fire", reason="baseline state — proceed normally"
        )
        ctx = CheckInContext(checkin_type="morning_motivation")
        result = format_checkin_prompt("morning_motivation", action, ctx)
        assert "### Context" not in result


# ---------------------------------------------------------------------------
# inject_checkin_into_prompt
# ---------------------------------------------------------------------------

class TestInjectCheckinIntoPrompt:

    def test_appends_block(self) -> None:
        result = inject_checkin_into_prompt("System prompt.", "Check-in block.")
        assert result == "System prompt.\n\nCheck-in block."

    def test_empty_block_returns_original(self) -> None:
        result = inject_checkin_into_prompt("System prompt.", "")
        assert result == "System prompt."
