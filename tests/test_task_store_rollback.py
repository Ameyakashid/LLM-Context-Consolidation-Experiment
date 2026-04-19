"""Phase-2 rollback safety: ``TASKWARRIOR_ENABLED=false`` must stay clean.

Locks the AC #11 constraint — with both feature flags off, the bot's
task-store wiring is byte-identical to the pre-Task-16 state. Flipping
the flag back on returns the Taskwarrior backend (skip-gated on the
``task`` CLI).
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

from task_store import TaskStore
from task_store_factory import build_task_store
from taskwarrior_setup import is_taskwarrior_enabled


def _write_tasks_json(path: Path, title: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    payload: dict[str, object] = {
        "tasks": [
            {
                "id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "title": title,
                "description": None,
                "status": "pending",
                "priority": "medium",
                "created_at": now,
                "updated_at": now,
                "due_date": None,
                "tags": [],
            },
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


class TestFlagOffRoutesToJsonBackend:
    def test_missing_flag_returns_json(self, tmp_path: Path) -> None:
        store = build_task_store(env={}, repo_root=tmp_path)
        assert isinstance(store, TaskStore)

    def test_explicit_false_returns_json(self, tmp_path: Path) -> None:
        store = build_task_store(
            env={"TASKWARRIOR_ENABLED": "false"}, repo_root=tmp_path,
        )
        assert isinstance(store, TaskStore)

    def test_syncall_defaults_off(self) -> None:
        assert is_taskwarrior_enabled({}) is False


class TestMigrationLeavesJsonReadable:
    def test_post_migration_json_still_parses(self, tmp_path: Path) -> None:
        json_path = tmp_path / "workspace" / "data" / "tasks.json"
        _write_tasks_json(json_path, "pre-migration row")

        store = build_task_store(env={}, repo_root=tmp_path)
        tasks = store.list_tasks()
        titles = [task.title for task in tasks]
        assert "pre-migration row" in titles

    def test_flag_off_after_migration_serves_json_rows(
        self, tmp_path: Path,
    ) -> None:
        json_path = tmp_path / "workspace" / "data" / "tasks.json"
        _write_tasks_json(json_path, "lives in json")

        store = build_task_store(
            env={"TASKWARRIOR_ENABLED": "false"}, repo_root=tmp_path,
        )
        assert isinstance(store, TaskStore)
        titles = [task.title for task in store.list_tasks()]
        assert titles == ["lives in json"]


class TestFlagOnRoutesToTaskwarrior:
    @pytest.mark.skipif(
        shutil.which("task") is None,
        reason="Taskwarrior CLI not installed",
    )
    def test_true_returns_taskwarrior_store(self, tmp_path: Path) -> None:
        pytest.importorskip("tasklib")
        from taskwarrior_store import TaskwarriorStore

        store = build_task_store(
            env={
                "TASKWARRIOR_ENABLED": "true",
                "TASKWARRIOR_DATA_DIR": str(tmp_path / "tw"),
            },
            repo_root=tmp_path,
        )
        assert isinstance(store, TaskwarriorStore)
