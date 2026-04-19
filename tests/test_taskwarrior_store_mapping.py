"""Pure-function tests for the tasklib↔Pydantic mappers in
``taskwarrior_store``. No Taskwarrior CLI required — everything runs
against an in-memory stub that mimics tasklib's ``__getitem__`` + tag
semantics."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from task_store import Task
from taskwarrior_store import (
    _STARTED_TAG,
    _ours_status_from_tw,
    _user_tags_from_tw,
    apply_our_task_to_tw_task,
    tw_task_to_our_task,
)


# ---------------------------------------------------------------------------
# Minimal tasklib-Task stub
# ---------------------------------------------------------------------------

@dataclass
class _StubAnnotation:
    description: str

    def __getitem__(self, key: str) -> str:
        if key == "description":
            return self.description
        raise KeyError(key)


@dataclass
class _StubTWTask:
    """Implements the __getitem__/__setitem__ surface of tasklib.Task that
    the mappers use. No save/delete/done semantics — those are exercised
    by the real-binary tests."""

    data: dict[str, Any] = field(default_factory=dict)

    def __getitem__(self, key: str) -> Any:
        return self.data.get(key)

    def __setitem__(self, key: str, value: Any) -> None:
        self.data[key] = value


def _make_stub(
    *,
    uuid: str = "11111111-2222-3333-4444-555555555555",
    description: str = "Test task",
    status: str = "pending",
    priority: str = "M",
    tags: set[str] | None = None,
    annotations: list[_StubAnnotation] | None = None,
    entry: datetime | None = None,
    modified: datetime | None = None,
    due: datetime | None = None,
) -> _StubTWTask:
    reference_time = datetime(2026, 4, 19, 12, 0, tzinfo=timezone.utc)
    return _StubTWTask(
        data={
            "uuid": uuid,
            "description": description,
            "status": status,
            "priority": priority,
            "tags": tags if tags is not None else set(),
            "annotations": annotations or [],
            "entry": entry or reference_time,
            "modified": modified or reference_time,
            "due": due,
        }
    )


# ---------------------------------------------------------------------------
# tw_task_to_our_task
# ---------------------------------------------------------------------------

class TestTwToOurs:
    def test_basic_pending_task(self) -> None:
        task = tw_task_to_our_task(_make_stub())
        assert task.title == "Test task"
        assert task.status == "pending"
        assert task.priority == "medium"
        assert task.description is None
        assert task.tags == []

    def test_completed_status(self) -> None:
        task = tw_task_to_our_task(_make_stub(status="completed"))
        assert task.status == "done"

    def test_in_progress_from_started_tag(self) -> None:
        task = tw_task_to_our_task(_make_stub(tags={_STARTED_TAG}))
        assert task.status == "in_progress"

    def test_completed_wins_over_started_tag(self) -> None:
        task = tw_task_to_our_task(
            _make_stub(status="completed", tags={_STARTED_TAG})
        )
        assert task.status == "done"

    def test_started_tag_stripped_from_user_tags(self) -> None:
        task = tw_task_to_our_task(
            _make_stub(tags={_STARTED_TAG, "work", "urgent"})
        )
        assert task.tags == ["urgent", "work"]

    def test_priority_mapping(self) -> None:
        for tw_value, ours in (("L", "low"), ("M", "medium"), ("H", "high")):
            task = tw_task_to_our_task(_make_stub(priority=tw_value))
            assert task.priority == ours

    def test_unknown_priority_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown Taskwarrior priority"):
            tw_task_to_our_task(_make_stub(priority="X"))

    def test_empty_priority_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown Taskwarrior priority"):
            tw_task_to_our_task(_make_stub(priority=""))

    def test_first_annotation_becomes_description(self) -> None:
        ann = _StubAnnotation("the body")
        task = tw_task_to_our_task(_make_stub(annotations=[ann]))
        assert task.description == "the body"

    def test_datetime_normalized_to_utc(self) -> None:
        ny = ZoneInfo("America/New_York")
        ny_entry = datetime(2026, 4, 19, 8, 0, tzinfo=ny)
        task = tw_task_to_our_task(_make_stub(entry=ny_entry))
        assert task.created_at.utcoffset() == datetime.now(timezone.utc).utcoffset()
        assert task.created_at == ny_entry

    def test_naive_datetime_raises(self) -> None:
        naive = datetime(2026, 4, 19, 8, 0)
        with pytest.raises(ValueError, match="naive datetime"):
            tw_task_to_our_task(_make_stub(entry=naive))

    def test_due_date_preserved(self) -> None:
        due = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
        task = tw_task_to_our_task(_make_stub(due=due))
        assert task.due_date == due

    def test_none_due_date(self) -> None:
        task = tw_task_to_our_task(_make_stub(due=None))
        assert task.due_date is None


# ---------------------------------------------------------------------------
# apply_our_task_to_tw_task
# ---------------------------------------------------------------------------

class TestOursToTw:
    def _our_task(self, **overrides: Any) -> Task:
        base: dict[str, Any] = {
            "id": "11111111-2222-3333-4444-555555555555",
            "title": "Ours",
            "description": None,
            "status": "pending",
            "priority": "medium",
            "created_at": datetime(2026, 4, 19, tzinfo=timezone.utc),
            "updated_at": datetime(2026, 4, 19, tzinfo=timezone.utc),
            "due_date": None,
            "tags": [],
        }
        base.update(overrides)
        return Task(**base)

    def test_writes_description_priority_due_tags(self) -> None:
        due = datetime(2026, 6, 15, tzinfo=timezone.utc)
        ours = self._our_task(title="Write tests", priority="high", due_date=due, tags=["a"])
        stub = _StubTWTask()
        apply_our_task_to_tw_task(ours, stub)
        assert stub["description"] == "Write tests"
        assert stub["priority"] == "H"
        assert stub["due"] == due
        assert stub["tags"] == {"a"}

    def test_in_progress_adds_started_tag(self) -> None:
        ours = self._our_task(status="in_progress", tags=["work"])
        stub = _StubTWTask()
        apply_our_task_to_tw_task(ours, stub)
        assert stub["tags"] == {"work", _STARTED_TAG}

    def test_pending_omits_started_tag(self) -> None:
        ours = self._our_task(status="pending", tags=["work"])
        stub = _StubTWTask()
        apply_our_task_to_tw_task(ours, stub)
        assert stub["tags"] == {"work"}

    def test_done_omits_started_tag(self) -> None:
        ours = self._our_task(status="done", tags=["work"])
        stub = _StubTWTask()
        apply_our_task_to_tw_task(ours, stub)
        assert stub["tags"] == {"work"}


# ---------------------------------------------------------------------------
# Micro-helpers
# ---------------------------------------------------------------------------

class TestOursStatusFromTw:
    def test_completed(self) -> None:
        assert _ours_status_from_tw("completed", set()) == "done"

    def test_pending_without_started(self) -> None:
        assert _ours_status_from_tw("pending", {"foo"}) == "pending"

    def test_pending_with_started(self) -> None:
        assert _ours_status_from_tw("pending", {_STARTED_TAG}) == "in_progress"


class TestUserTagsFromTw:
    def test_strips_started(self) -> None:
        assert _user_tags_from_tw({_STARTED_TAG, "b", "a"}) == ["a", "b"]

    def test_no_started(self) -> None:
        assert _user_tags_from_tw({"b", "a"}) == ["a", "b"]

    def test_empty(self) -> None:
        assert _user_tags_from_tw(set()) == []
