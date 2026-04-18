"""End-to-end integration tests for NL time parsing through task tools.

Exercises CreateTaskTool/UpdateTaskTool → TaskStore → resolve_due_date
→ parse_time_phrase with realistic conversational due_date phrases.
Complements tests/test_task_tools_nl_time.py (helper-level units) and
tests/test_nl_time_parser.py (parser-level units).

`datetime.now` inside task_tools is monkeypatched via a datetime
subclass so weekday-sensitive scenarios (Friday-on-Friday, self-
correcting input, next-Friday-from-Tuesday) are deterministic on any
day of the week.
"""

import asyncio
from collections.abc import Coroutine
from datetime import datetime, timedelta, tzinfo
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

import pytest

import task_tools
from task_store import TaskStore
from task_tools import CreateTaskTool, UpdateTaskTool


UTC = ZoneInfo("UTC")
PINNED_TUESDAY = datetime(2025, 4, 15, 10, 0, tzinfo=UTC)
PINNED_FRIDAY = datetime(2025, 4, 18, 10, 0, tzinfo=UTC)
PINNED_SATURDAY = datetime(2025, 4, 19, 10, 0, tzinfo=UTC)


def _make_frozen(pinned: datetime) -> type[datetime]:
    class _FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> datetime:  # type: ignore[override]
            return pinned.astimezone(tz) if tz is not None else pinned

    return _FrozenDateTime


@pytest.fixture()
def storage_path(tmp_path: Path) -> Path:
    return tmp_path / "tasks.json"


@pytest.fixture()
def store(storage_path: Path) -> TaskStore:
    return TaskStore(storage_path)


@pytest.fixture()
def utc_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NANOBOT_TIMEZONE", "UTC")


@pytest.fixture()
def freeze_now(monkeypatch: pytest.MonkeyPatch) -> Callable[[datetime], None]:
    def _freeze(pinned: datetime) -> None:
        monkeypatch.setattr(task_tools, "datetime", _make_frozen(pinned))

    return _freeze


def run(coro: Coroutine[object, object, str]) -> str:
    return asyncio.run(coro)


class TestCreateNLHappyPath:
    def test_tomorrow_at_precise_hour_advances_one_day(
        self,
        store: TaskStore,
        utc_env: None,
        freeze_now: Callable[[datetime], None],
    ) -> None:
        freeze_now(PINNED_TUESDAY)
        tool = CreateTaskTool(store=store)
        result = run(
            tool.execute(title="Call dentist", priority="medium", due_date="tomorrow at 18:00")
        )
        assert "Task created:" in result
        due = store.list_tasks()[0].due_date
        assert due == (PINNED_TUESDAY + timedelta(days=1)).replace(hour=18, minute=0)

    def test_next_friday_from_tuesday_is_three_days_out(
        self,
        store: TaskStore,
        utc_env: None,
        freeze_now: Callable[[datetime], None],
    ) -> None:
        freeze_now(PINNED_TUESDAY)
        tool = CreateTaskTool(store=store)
        run(tool.execute(title="Weekly review", priority="low", due_date="next Friday"))
        due = store.list_tasks()[0].due_date
        assert due is not None
        assert due.weekday() == 4
        assert due.date() == (PINNED_TUESDAY + timedelta(days=3)).date()

    def test_in_two_hours_is_precise_offset(
        self,
        store: TaskStore,
        utc_env: None,
        freeze_now: Callable[[datetime], None],
    ) -> None:
        freeze_now(PINNED_TUESDAY)
        tool = CreateTaskTool(store=store)
        run(tool.execute(title="Meeting prep", priority="high", due_date="in 2 hours"))
        due = store.list_tasks()[0].due_date
        assert due == PINNED_TUESDAY + timedelta(hours=2)

    def test_in_thirty_minutes_is_precise_offset(
        self,
        store: TaskStore,
        utc_env: None,
        freeze_now: Callable[[datetime], None],
    ) -> None:
        freeze_now(PINNED_TUESDAY)
        tool = CreateTaskTool(store=store)
        run(tool.execute(title="Stretch break", priority="low", due_date="in 30 minutes"))
        due = store.list_tasks()[0].due_date
        assert due == PINNED_TUESDAY + timedelta(minutes=30)

    def test_at_fourteen_hundred_sets_same_day_hour(
        self,
        store: TaskStore,
        utc_env: None,
        freeze_now: Callable[[datetime], None],
    ) -> None:
        freeze_now(PINNED_TUESDAY)
        tool = CreateTaskTool(store=store)
        run(tool.execute(title="Lunch walk", priority="low", due_date="at 14:00"))
        due = store.list_tasks()[0].due_date
        assert due == PINNED_TUESDAY.replace(hour=14, minute=0)

    def test_next_monday_at_9am_suffix_unparsed_keeps_now_hour(
        self,
        store: TaskStore,
        utc_env: None,
        freeze_now: Callable[[datetime], None],
    ) -> None:
        # The parser does not recognise am/pm suffixes. Documented
        # behaviour: weekday advances, but hour stays at `now.hour`.
        freeze_now(PINNED_TUESDAY)
        tool = CreateTaskTool(store=store)
        run(
            tool.execute(title="Sprint kickoff", priority="medium", due_date="next monday at 9am")
        )
        due = store.list_tasks()[0].due_date
        assert due is not None
        assert due.weekday() == 0
        assert due.hour == PINNED_TUESDAY.hour


class TestIsoRegression:
    def test_iso_datetime_with_z_suffix_still_works(
        self,
        store: TaskStore,
        utc_env: None,
        freeze_now: Callable[[datetime], None],
    ) -> None:
        freeze_now(PINNED_TUESDAY)
        tool = CreateTaskTool(store=store)
        run(tool.execute(title="Plan trip", priority="medium", due_date="2026-05-01T14:00:00Z"))
        due = store.list_tasks()[0].due_date
        assert due is not None
        assert (due.year, due.month, due.day, due.hour) == (2026, 5, 1, 14)
        assert due.tzinfo is not None


class TestMixedSequence:
    def test_iso_then_nl_then_no_due_date_all_land_correctly(
        self,
        store: TaskStore,
        utc_env: None,
        freeze_now: Callable[[datetime], None],
    ) -> None:
        freeze_now(PINNED_TUESDAY)
        tool = CreateTaskTool(store=store)
        run(tool.execute(title="A", priority="low", due_date="2026-01-15"))
        run(tool.execute(title="B", priority="medium", due_date="in 2 hours"))
        run(tool.execute(title="C", priority="high"))
        tasks_by_title = {t.title: t for t in store.list_tasks()}
        assert len(tasks_by_title) == 3
        assert tasks_by_title["A"].due_date is not None
        assert tasks_by_title["A"].due_date.year == 2026
        assert tasks_by_title["B"].due_date == PINNED_TUESDAY + timedelta(hours=2)
        assert tasks_by_title["C"].due_date is None


class TestUpdateFlow:
    def test_update_nl_due_date_preserves_other_fields(
        self,
        store: TaskStore,
        utc_env: None,
        freeze_now: Callable[[datetime], None],
    ) -> None:
        freeze_now(PINNED_TUESDAY)
        create = CreateTaskTool(store=store)
        update = UpdateTaskTool(store=store)
        run(
            create.execute(
                title="Ship feature", priority="high", due_date="tomorrow", tags=["work"]
            )
        )
        created = store.list_tasks()[0]
        run(update.execute(task_id=created.id, due_date="next Friday"))
        updated = store.get_task(created.id)
        assert updated.title == created.title
        assert updated.priority == created.priority
        assert updated.tags == created.tags
        assert updated.due_date is not None
        assert updated.due_date.weekday() == 4
        assert updated.due_date.date() == (PINNED_TUESDAY + timedelta(days=3)).date()


class TestSelfCorrectingInput:
    def test_tomorrow_no_actually_friday_from_saturday_is_following_friday(
        self,
        store: TaskStore,
        utc_env: None,
        freeze_now: Callable[[datetime], None],
    ) -> None:
        # Token stream overwrites state: "tomorrow" advances to Sunday,
        # then "friday" walks forward to the following Friday.
        freeze_now(PINNED_SATURDAY)
        tool = CreateTaskTool(store=store)
        run(
            tool.execute(
                title="Submit report",
                priority="medium",
                due_date="tomorrow no actually friday",
            )
        )
        due = store.list_tasks()[0].due_date
        assert due is not None
        assert due.weekday() == 4
        assert due.date() == (PINNED_SATURDAY + timedelta(days=6)).date()


class TestClarificationTriggers:
    def test_unparseable_phrase_errors_and_store_stays_empty(
        self,
        store: TaskStore,
        utc_env: None,
        freeze_now: Callable[[datetime], None],
    ) -> None:
        freeze_now(PINNED_TUESDAY)
        tool = CreateTaskTool(store=store)
        result = run(
            tool.execute(
                title="Blocked", priority="low", due_date="some time maybe later"
            )
        )
        assert result.startswith("Error: ")
        assert "could not parse time phrase" in result
        assert len(store.list_tasks()) == 0

    def test_empty_string_errors_and_store_stays_empty(
        self,
        store: TaskStore,
        utc_env: None,
        freeze_now: Callable[[datetime], None],
    ) -> None:
        freeze_now(PINNED_TUESDAY)
        tool = CreateTaskTool(store=store)
        result = run(tool.execute(title="Blank", priority="low", due_date=""))
        assert result.startswith("Error: ")
        assert "could not parse time phrase" in result
        assert len(store.list_tasks()) == 0


class TestAmbiguityOnFriday:
    def test_friday_on_friday_resolves_same_day(
        self,
        store: TaskStore,
        utc_env: None,
        freeze_now: Callable[[datetime], None],
    ) -> None:
        # Locks current parser behaviour: both "Friday" and "next Friday"
        # produce the same-day Friday when `now` is a Friday. The SOUL.md
        # clarification guidance (added in this subtask) is the user-
        # facing mitigation, not a parser change.
        freeze_now(PINNED_FRIDAY)
        tool = CreateTaskTool(store=store)
        run(tool.execute(title="Wrap-up", priority="low", due_date="Friday"))
        due = store.list_tasks()[0].due_date
        assert due is not None
        assert due.date() == PINNED_FRIDAY.date()
