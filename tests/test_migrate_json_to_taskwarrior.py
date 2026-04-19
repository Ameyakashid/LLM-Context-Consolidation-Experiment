"""End-to-end migration: tasks.json → TaskwarriorStore, with round-trip diff.

Skipped at collection time when the ``task`` CLI is absent — the
migration script wraps the real tasklib/TW subprocess stack and cannot
be meaningfully unit-tested without the binary.
"""

from __future__ import annotations

import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

if shutil.which("task") is None:
    pytest.skip(
        "Taskwarrior CLI not installed — skipping migration script tests.",
        allow_module_level=True,
    )

pytest.importorskip("tasklib")

# Make the scripts package importable.
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR.parent))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from task_store import TaskStore  # noqa: E402
from taskwarrior_store import TaskwarriorStore  # noqa: E402

import migrate_json_to_taskwarrior as migration  # noqa: E402

FIXTURE_NOW = datetime(2026, 4, 19, 10, 0, 0, tzinfo=timezone.utc)


@pytest.fixture()
def source_store(tmp_path: Path) -> TaskStore:
    store = TaskStore(storage_path=tmp_path / "tasks.json")
    store.create_task(
        title="Full fields task",
        priority="high",
        description="All optional fields present.",
        due_date=FIXTURE_NOW,
        tags=["home", "urgent"],
    )
    store.create_task(
        title="Minimal",
        priority="low",
        description=None,
        due_date=None,
        tags=[],
    )
    in_progress_task = store.create_task(
        title="In progress work",
        priority="medium",
        description="Work started.",
        due_date=FIXTURE_NOW,
        tags=["focus"],
    )
    from task_store import TaskUpdate
    store.update_task(
        in_progress_task.id, TaskUpdate(status="in_progress"),
    )
    return store


@pytest.fixture()
def tw_data_dir(tmp_path: Path) -> Path:
    return tmp_path / "taskwarrior"


class TestEndToEndMigration:
    def test_three_tasks_migrate_cleanly(
        self, source_store: TaskStore, tw_data_dir: Path, tmp_path: Path,
    ) -> None:
        exit_code = migration.main([
            "--source", str(tmp_path / "tasks.json"),
            "--data-dir", str(tw_data_dir),
        ])
        assert exit_code == migration.EXIT_OK

        target = TaskwarriorStore(data_dir=tw_data_dir)
        migrated = target.list_tasks()
        titles = {t.title for t in migrated}
        assert titles == {"Full fields task", "Minimal", "In progress work"}

    def test_every_task_carries_migrated_tag(
        self, source_store: TaskStore, tw_data_dir: Path, tmp_path: Path,
    ) -> None:
        migration.main([
            "--source", str(tmp_path / "tasks.json"),
            "--data-dir", str(tw_data_dir),
        ])
        target = TaskwarriorStore(data_dir=tw_data_dir)
        for task in target.list_tasks():
            assert any(
                tag.startswith(migration.MIGRATED_TAG_PREFIX)
                for tag in task.tags
            )

    def test_in_progress_status_round_trips(
        self, source_store: TaskStore, tw_data_dir: Path, tmp_path: Path,
    ) -> None:
        migration.main([
            "--source", str(tmp_path / "tasks.json"),
            "--data-dir", str(tw_data_dir),
        ])
        target = TaskwarriorStore(data_dir=tw_data_dir)
        in_progress = [
            t for t in target.list_tasks()
            if t.title == "In progress work"
        ]
        assert len(in_progress) == 1
        assert in_progress[0].status == "in_progress"

    def test_tags_and_due_date_preserved(
        self, source_store: TaskStore, tw_data_dir: Path, tmp_path: Path,
    ) -> None:
        migration.main([
            "--source", str(tmp_path / "tasks.json"),
            "--data-dir", str(tw_data_dir),
        ])
        target = TaskwarriorStore(data_dir=tw_data_dir)
        full = next(t for t in target.list_tasks() if t.title == "Full fields task")
        user_tags = {
            tag for tag in full.tags
            if not tag.startswith(migration.MIGRATED_TAG_PREFIX)
        }
        assert user_tags == {"home", "urgent"}
        assert full.due_date is not None
        assert full.due_date == FIXTURE_NOW


class TestIdempotency:
    def test_second_run_skips_all(
        self, source_store: TaskStore, tw_data_dir: Path, tmp_path: Path,
    ) -> None:
        first_exit = migration.main([
            "--source", str(tmp_path / "tasks.json"),
            "--data-dir", str(tw_data_dir),
        ])
        assert first_exit == migration.EXIT_OK
        target = TaskwarriorStore(data_dir=tw_data_dir)
        count_after_first = len(target.list_tasks())

        second_exit = migration.main([
            "--source", str(tmp_path / "tasks.json"),
            "--data-dir", str(tw_data_dir),
        ])
        assert second_exit == migration.EXIT_OK
        target_2 = TaskwarriorStore(data_dir=tw_data_dir)
        assert len(target_2.list_tasks()) == count_after_first


class TestDryRun:
    def test_dry_run_does_not_write(
        self, source_store: TaskStore, tw_data_dir: Path, tmp_path: Path,
    ) -> None:
        exit_code = migration.main([
            "--source", str(tmp_path / "tasks.json"),
            "--data-dir", str(tw_data_dir),
            "--dry-run",
        ])
        assert exit_code == migration.EXIT_OK
        target = TaskwarriorStore(data_dir=tw_data_dir)
        assert target.list_tasks() == []


class TestReversibility:
    def test_source_json_unmodified_after_success(
        self, source_store: TaskStore, tw_data_dir: Path, tmp_path: Path,
    ) -> None:
        source_path = tmp_path / "tasks.json"
        content_before = source_path.read_text(encoding="utf-8")
        migration.main([
            "--source", str(source_path),
            "--data-dir", str(tw_data_dir),
        ])
        assert source_path.read_text(encoding="utf-8") == content_before


class TestPreflightErrors:
    def test_missing_source_exits_preflight(
        self, tmp_path: Path,
    ) -> None:
        exit_code = migration.main([
            "--source", str(tmp_path / "missing.json"),
            "--data-dir", str(tmp_path / "tw"),
        ])
        assert exit_code == migration.EXIT_PREFLIGHT

    def test_corrupt_source_exits_preflight(
        self, tmp_path: Path,
    ) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        exit_code = migration.main([
            "--source", str(bad),
            "--data-dir", str(tmp_path / "tw"),
        ])
        assert exit_code == migration.EXIT_PREFLIGHT


class TestUnrelatedTasksRefusal:
    def test_unrelated_tasks_without_force_refuses(
        self, source_store: TaskStore, tw_data_dir: Path, tmp_path: Path,
    ) -> None:
        pre_populated = TaskwarriorStore(data_dir=tw_data_dir)
        pre_populated.create_task(
            "Pre-existing", "medium", None, None, ["user_tag"],
        )

        exit_code = migration.main([
            "--source", str(tmp_path / "tasks.json"),
            "--data-dir", str(tw_data_dir),
        ])
        assert exit_code == migration.EXIT_FORCE_REFUSED

    def test_force_flag_overrides_refusal(
        self, source_store: TaskStore, tw_data_dir: Path, tmp_path: Path,
    ) -> None:
        pre_populated = TaskwarriorStore(data_dir=tw_data_dir)
        pre_populated.create_task(
            "Pre-existing", "medium", None, None, ["user_tag"],
        )

        exit_code = migration.main([
            "--source", str(tmp_path / "tasks.json"),
            "--data-dir", str(tw_data_dir),
            "--force",
        ])
        assert exit_code == migration.EXIT_OK
