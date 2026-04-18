"""Tests for NL-aware due-date resolution in task tools.

Covers resolve_due_date, get_user_timezone, and the CreateTaskTool /
UpdateTaskTool integration points that route through them. Mirrors the
tmp_path + asyncio.run fixture pattern from test_task_tools.py.

NOTE: nl_time_parser does not recognise am/pm suffixes ('6pm'); precise
hour tests use 24-hour form ('18:00'). The 'tomorrow at 6pm' SOUL.md
example relies on the LLM rewriting am/pm upstream, or falls through to
the current-hour-on-tomorrow behavior. Widening the parser is sub-03+.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pytest

from task_store import TaskStore
from task_time_helpers import get_user_timezone, resolve_due_date
from task_tools import CreateTaskTool, UpdateTaskTool


LA = ZoneInfo("America/Los_Angeles")


@pytest.fixture()
def storage_path(tmp_path: Path) -> Path:
    return tmp_path / "tasks.json"


@pytest.fixture()
def store(storage_path: Path) -> TaskStore:
    return TaskStore(storage_path)


@pytest.fixture()
def now_la() -> datetime:
    return datetime(2025, 4, 15, 9, 30, tzinfo=LA)


def run(coro):  # noqa: ANN001, ANN201
    return asyncio.run(coro)


class TestResolveDueDate:
    def test_iso_date_only_preserves_tz(self, now_la: datetime) -> None:
        result = resolve_due_date("2025-12-31", now_la)
        assert result.year == 2025
        assert result.month == 12
        assert result.day == 31
        assert result.tzinfo is not None

    def test_iso_datetime_with_tz(self, now_la: datetime) -> None:
        result = resolve_due_date("2025-06-15T14:00:00Z", now_la)
        assert result.year == 2025
        assert result.month == 6
        assert result.hour == 14
        assert result.tzinfo is not None

    def test_tomorrow_advances_one_day(self, now_la: datetime) -> None:
        result = resolve_due_date("tomorrow", now_la)
        expected = now_la + timedelta(days=1)
        assert result.date() == expected.date()
        assert result.tzinfo == now_la.tzinfo

    def test_tomorrow_at_precise_hour(self, now_la: datetime) -> None:
        result = resolve_due_date("tomorrow at 18:00", now_la)
        assert result.date() == (now_la + timedelta(days=1)).date()
        assert result.hour == 18
        assert result.minute == 0
        assert result.tzinfo == now_la.tzinfo

    def test_in_two_hours_precise_offset(self, now_la: datetime) -> None:
        result = resolve_due_date("in 2 hours", now_la)
        assert result == now_la + timedelta(hours=2)

    def test_next_friday_returns_future_friday(self, now_la: datetime) -> None:
        result = resolve_due_date("next friday", now_la)
        assert result.weekday() == 4
        assert result.date() >= now_la.date()

    def test_unparseable_phrase_raises_value_error(self, now_la: datetime) -> None:
        with pytest.raises(ValueError, match="could not parse time phrase"):
            resolve_due_date("call mum", now_la)

    def test_gibberish_raises_value_error(self, now_la: datetime) -> None:
        with pytest.raises(ValueError, match="could not parse time phrase"):
            resolve_due_date("gibberish xyz", now_la)

    def test_error_message_includes_input_value(self, now_la: datetime) -> None:
        with pytest.raises(ValueError, match="'call mum'"):
            resolve_due_date("call mum", now_la)

    def test_error_message_lists_accepted_formats(self, now_la: datetime) -> None:
        with pytest.raises(ValueError, match="ISO 8601"):
            resolve_due_date("call mum", now_la)
        with pytest.raises(ValueError, match="natural-language"):
            resolve_due_date("call mum", now_la)

    def test_naive_now_raises_value_error(self) -> None:
        naive = datetime(2025, 4, 15, 9, 30)
        with pytest.raises(ValueError, match="tz-aware"):
            resolve_due_date("tomorrow", naive)

    def test_iso_branch_short_circuits_nl(self, now_la: datetime) -> None:
        result = resolve_due_date("2025-12-31", now_la)
        assert result.year == 2025
        assert result.hour == 0


class TestGetUserTimezone:
    def test_unset_defaults_to_utc(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NANOBOT_TIMEZONE", raising=False)
        assert get_user_timezone() == ZoneInfo("UTC")

    def test_reads_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NANOBOT_TIMEZONE", "America/Los_Angeles")
        assert get_user_timezone() == ZoneInfo("America/Los_Angeles")

    def test_unknown_tz_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NANOBOT_TIMEZONE", "Mars/Phobos")
        with pytest.raises(ZoneInfoNotFoundError):
            get_user_timezone()


class TestCreateTaskToolNL:
    def test_create_with_iso_date_still_works(
        self, store: TaskStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NANOBOT_TIMEZONE", "UTC")
        tool = CreateTaskTool(store=store)
        result = run(tool.execute(title="Plan trip", priority="medium", due_date="2025-12-31"))
        assert "Task created:" in result
        assert store.list_tasks()[0].due_date is not None

    def test_create_with_nl_phrase_stores_task(
        self, store: TaskStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NANOBOT_TIMEZONE", "America/Los_Angeles")
        tool = CreateTaskTool(store=store)
        result = run(tool.execute(
            title="Call doctor", priority="medium", due_date="tomorrow at 18:00"
        ))
        assert "Task created:" in result
        created = store.list_tasks()[0]
        assert created.due_date is not None
        assert created.due_date.hour == 18
        assert created.due_date.tzinfo is not None
        assert created.due_date.utcoffset() == datetime.now(LA).utcoffset()

    def test_create_with_unparseable_phrase_returns_error(
        self, store: TaskStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NANOBOT_TIMEZONE", "UTC")
        tool = CreateTaskTool(store=store)
        result = run(tool.execute(title="Blocked", priority="low", due_date="call mum"))
        assert result.startswith("Error:")
        assert "could not parse time phrase" in result
        assert len(store.list_tasks()) == 0

    def test_schema_description_mentions_both_formats(self, store: TaskStore) -> None:
        tool = CreateTaskTool(store=store)
        due_date_description = tool.parameters["properties"]["due_date"]["description"]
        assert "ISO 8601" in due_date_description
        assert "natural-language" in due_date_description


class TestUpdateTaskToolNL:
    def test_update_with_nl_phrase(
        self, store: TaskStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NANOBOT_TIMEZONE", "America/Los_Angeles")
        task = store.create_task("Review PR", "low", None, None, [])
        tool = UpdateTaskTool(store=store)
        result = run(tool.execute(task_id=task.id, due_date="next friday"))
        assert "Task updated:" in result
        updated = store.get_task(task.id)
        assert updated.due_date is not None
        assert updated.due_date.weekday() == 4

    def test_update_with_none_leaves_existing_due_date(
        self, store: TaskStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NANOBOT_TIMEZONE", "UTC")
        original_due = datetime(2025, 6, 1, tzinfo=timezone.utc)
        task = store.create_task("With due", "low", None, original_due, [])
        tool = UpdateTaskTool(store=store)
        result = run(tool.execute(task_id=task.id, due_date=None, title="Renamed"))
        assert "Task updated:" in result
        assert store.get_task(task.id).due_date == original_due
        assert store.get_task(task.id).title == "Renamed"

    def test_update_with_unparseable_phrase_returns_error(
        self, store: TaskStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NANOBOT_TIMEZONE", "UTC")
        task = store.create_task("Dated", "low", None, None, [])
        tool = UpdateTaskTool(store=store)
        result = run(tool.execute(task_id=task.id, due_date="absolute nonsense"))
        assert result.startswith("Error:")
        assert "could not parse time phrase" in result

    def test_schema_description_mentions_both_formats(self, store: TaskStore) -> None:
        tool = UpdateTaskTool(store=store)
        due_date_description = tool.parameters["properties"]["due_date"]["description"]
        assert "ISO 8601" in due_date_description
        assert "natural-language" in due_date_description
