"""CRUD parity tests for :class:`taskwarrior_store.TaskwarriorStore`.

Each ``TestTaskStore*`` test in ``tests/test_task_store.py`` has a
behavioural mirror here, executed against a real ``task`` CLI binary in a
per-test ``tmp_path`` data dir. The module skips at collection time when
the CLI is not installed so CI boxes without Taskwarrior still pass.
"""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

if shutil.which("task") is None:
    pytest.skip(
        "Taskwarrior CLI ('task') not installed — skipping CRUD parity "
        "tests. Install with 'choco install task' (Windows), 'brew "
        "install task' (macOS), or 'apt install taskwarrior' (Debian).",
        allow_module_level=True,
    )

pytest.importorskip("tasklib")

from task_store import TaskUpdate  # noqa: E402
from taskwarrior_store import TaskwarriorStore  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "taskwarrior"


@pytest.fixture()
def store(data_dir: Path) -> TaskwarriorStore:
    return TaskwarriorStore(data_dir)


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

class TestTaskwarriorStoreCreate:
    def test_create_returns_task(self, store: TaskwarriorStore) -> None:
        task = store.create_task("Buy milk", "low", None, None, [])
        assert task.title == "Buy milk"
        assert task.status == "pending"
        assert task.priority == "low"

    def test_create_persists_to_disk(
        self, store: TaskwarriorStore, data_dir: Path
    ) -> None:
        store.create_task("Persisted", "medium", None, None, [])
        assert (data_dir / "pending.data").exists()

    def test_create_multiple_tasks(self, store: TaskwarriorStore) -> None:
        store.create_task("A", "low", None, None, [])
        store.create_task("B", "high", None, None, [])
        assert len(store.list_tasks()) == 2

    def test_create_with_description_stores_annotation(
        self, store: TaskwarriorStore
    ) -> None:
        task = store.create_task("title", "low", "the body", None, [])
        assert task.description == "the body"

    def test_create_with_tags(self, store: TaskwarriorStore) -> None:
        task = store.create_task("tagged", "low", None, None, ["foo", "bar"])
        assert set(task.tags) == {"foo", "bar"}


# ---------------------------------------------------------------------------
# Get
# ---------------------------------------------------------------------------

class TestTaskwarriorStoreGet:
    def test_get_existing_task(self, store: TaskwarriorStore) -> None:
        created = store.create_task("Find me", "low", None, None, [])
        found = store.get_task(created.id)
        assert found.title == "Find me"
        assert found.id == created.id

    def test_get_nonexistent_raises(self, store: TaskwarriorStore) -> None:
        with pytest.raises(KeyError, match="Task not found"):
            store.get_task("00000000-0000-0000-0000-000000000000")


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

class TestTaskwarriorStoreList:
    def test_list_empty_store(self, store: TaskwarriorStore) -> None:
        assert store.list_tasks() == []

    def test_list_by_status_pending_and_done(
        self, store: TaskwarriorStore
    ) -> None:
        store.create_task("Pending", "low", None, None, [])
        task_b = store.create_task("Also pending", "low", None, None, [])
        store.mark_complete(task_b.id)

        pending = store.list_tasks_by_status("pending")
        done = store.list_tasks_by_status("done")
        assert len(pending) == 1
        assert len(done) == 1
        assert pending[0].title == "Pending"
        assert done[0].title == "Also pending"

    def test_in_progress_tag_maps_correctly(
        self, store: TaskwarriorStore
    ) -> None:
        task = store.create_task("Active", "medium", None, None, [])
        store.update_task(task.id, TaskUpdate(status="in_progress"))

        in_prog = store.list_tasks_by_status("in_progress")
        pending = store.list_tasks_by_status("pending")
        assert len(in_prog) == 1
        assert in_prog[0].title == "Active"
        assert pending == []

    def test_list_excludes_deleted(self, store: TaskwarriorStore) -> None:
        t = store.create_task("Gone", "low", None, None, [])
        store.delete_task(t.id)
        assert store.list_tasks() == []
        assert store.list_tasks_by_status("pending") == []
        assert store.list_tasks_by_status("done") == []
        assert store.list_tasks_by_status("in_progress") == []


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

class TestTaskwarriorStoreUpdate:
    def test_update_changes_fields(self, store: TaskwarriorStore) -> None:
        task = store.create_task("Old title", "low", None, None, [])
        updated = store.update_task(task.id, TaskUpdate(title="New title"))
        assert updated.title == "New title"
        assert updated.priority == "low"

    def test_update_nonexistent_raises(
        self, store: TaskwarriorStore
    ) -> None:
        with pytest.raises(KeyError, match="Task not found"):
            store.update_task(
                "00000000-0000-0000-0000-000000000000",
                TaskUpdate(title="x"),
            )

    def test_mark_complete_sets_done(self, store: TaskwarriorStore) -> None:
        task = store.create_task("Finish me", "high", None, None, [])
        completed = store.mark_complete(task.id)
        assert completed.status == "done"

    def test_update_bumps_updated_at(self, store: TaskwarriorStore) -> None:
        task = store.create_task("Timestamped", "low", None, None, [])
        updated = store.update_task(task.id, TaskUpdate(priority="high"))
        assert updated.updated_at >= task.updated_at

    def test_update_description_replaces_annotation(
        self, store: TaskwarriorStore
    ) -> None:
        task = store.create_task("t", "low", "first", None, [])
        updated = store.update_task(
            task.id, TaskUpdate(description="second")
        )
        assert updated.description == "second"

    def test_update_description_to_none_clears(
        self, store: TaskwarriorStore
    ) -> None:
        task = store.create_task("t", "low", "initial", None, [])
        updated = store.update_task(task.id, TaskUpdate(description=None))
        assert updated.description is None

    def test_update_adds_description_when_absent(
        self, store: TaskwarriorStore
    ) -> None:
        task = store.create_task("t", "low", None, None, [])
        updated = store.update_task(task.id, TaskUpdate(description="added"))
        assert updated.description == "added"

    def test_update_tags_replaces(self, store: TaskwarriorStore) -> None:
        task = store.create_task("tagged", "low", None, None, ["a"])
        updated = store.update_task(task.id, TaskUpdate(tags=["b", "c"]))
        assert set(updated.tags) == {"b", "c"}

    def test_update_due_date_round_trip(
        self, store: TaskwarriorStore
    ) -> None:
        task = store.create_task("due", "low", None, None, [])
        due = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
        updated = store.update_task(task.id, TaskUpdate(due_date=due))
        assert updated.due_date == due


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

class TestTaskwarriorStoreDelete:
    def test_delete_removes_task(self, store: TaskwarriorStore) -> None:
        task = store.create_task("Delete me", "low", None, None, [])
        deleted = store.delete_task(task.id)
        assert deleted.id == task.id
        assert len(store.list_tasks()) == 0

    def test_delete_nonexistent_raises(
        self, store: TaskwarriorStore
    ) -> None:
        with pytest.raises(KeyError, match="Cannot delete"):
            store.delete_task("00000000-0000-0000-0000-000000000000")

    def test_delete_persists(self, data_dir: Path) -> None:
        store = TaskwarriorStore(data_dir)
        task = store.create_task("Gone soon", "low", None, None, [])
        store.delete_task(task.id)
        fresh = TaskwarriorStore(data_dir)
        assert len(fresh.list_tasks()) == 0


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

class TestTaskwarriorStorePersistenceRoundTrip:
    def test_tasks_survive_restart(self, data_dir: Path) -> None:
        store = TaskwarriorStore(data_dir)
        due = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
        store.create_task("Survive", "high", "important", due, ["critical"])

        fresh = TaskwarriorStore(data_dir)
        tasks = fresh.list_tasks()
        assert len(tasks) == 1
        assert tasks[0].title == "Survive"
        assert tasks[0].description == "important"
        assert tasks[0].due_date == due
        assert tasks[0].tags == ["critical"]

    def test_empty_store_initializes_cleanly(self, data_dir: Path) -> None:
        store = TaskwarriorStore(data_dir)
        assert store.list_tasks() == []

    def test_multiple_tasks_round_trip(self, data_dir: Path) -> None:
        store = TaskwarriorStore(data_dir)
        store.create_task("A", "low", None, None, ["a"])
        store.create_task("B", "medium", None, None, ["b"])
        store.create_task("C", "high", None, None, ["c"])

        fresh = TaskwarriorStore(data_dir)
        assert len(fresh.list_tasks()) == 3

    def test_reload_picks_up_external_changes(self, data_dir: Path) -> None:
        store = TaskwarriorStore(data_dir)
        store.create_task("Original", "low", None, None, [])
        other = TaskwarriorStore(data_dir)
        other.create_task("External", "high", None, None, [])
        store.reload()
        assert len(store.list_tasks()) == 2


# ---------------------------------------------------------------------------
# Priority round-trip matrix
# ---------------------------------------------------------------------------

class TestTaskwarriorPriorityRoundTrip:
    @pytest.mark.parametrize("priority", ["low", "medium", "high"])
    def test_priority_round_trip_through_create(
        self, store: TaskwarriorStore, priority: str
    ) -> None:
        task = store.create_task("p", priority, None, None, [])  # type: ignore[arg-type]
        fetched = store.get_task(task.id)
        assert fetched.priority == priority

    @pytest.mark.parametrize("priority", ["low", "medium", "high"])
    def test_priority_round_trip_through_update(
        self, store: TaskwarriorStore, priority: str
    ) -> None:
        task = store.create_task("p", "medium", None, None, [])
        store.update_task(task.id, TaskUpdate(priority=priority))  # type: ignore[arg-type]
        fetched = store.get_task(task.id)
        assert fetched.priority == priority


