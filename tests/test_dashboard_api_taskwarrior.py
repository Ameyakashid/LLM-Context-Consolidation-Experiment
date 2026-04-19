"""/tasks endpoint round-trips data through whichever backend is active.

Flag-off uses the JSON store pointed at the repo's workspace/data/tasks.json
via the factory (we monkeypatch ``_repo_root`` so the test writes to a
tmp tree). Flag-on only runs when the ``task`` CLI is installed.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import dashboard_api
from task_store import TaskStore


@pytest.fixture()
def tmp_repo_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> Path:
    monkeypatch.setattr(dashboard_api, "_repo_root", lambda: tmp_path)
    monkeypatch.delenv("TASKWARRIOR_ENABLED", raising=False)
    return tmp_path


class TestHandleTasksJsonBackend:
    def test_empty_store_returns_empty_tasks_list(
        self, tmp_repo_root: Path,
    ) -> None:
        result = dashboard_api.handle_tasks(tmp_repo_root / "data")
        assert result == {"tasks": []}

    def test_returns_active_tasks(self, tmp_repo_root: Path) -> None:
        tasks_path = tmp_repo_root / "workspace" / "data" / "tasks.json"
        tasks_path.parent.mkdir(parents=True, exist_ok=True)
        store = TaskStore(storage_path=tasks_path)
        store.create_task("Active A", "low", None, None, [])
        store.create_task("Active B", "high", None, None, [])
        done = store.create_task("Done X", "medium", None, None, [])
        store.mark_complete(done.id)

        result = dashboard_api.handle_tasks(tmp_repo_root / "data")
        titles = [t["title"] for t in result["tasks"]]  # type: ignore[index]
        assert set(titles) == {"Active A", "Active B"}


@pytest.mark.skipif(
    shutil.which("task") is None,
    reason="Taskwarrior CLI not installed",
)
class TestHandleTasksTaskwarriorBackend:
    def test_taskwarrior_backend_serves_tasks(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        pytest.importorskip("tasklib")
        from taskwarrior_store import TaskwarriorStore

        tw_dir = tmp_path / "tw"
        monkeypatch.setattr(dashboard_api, "_repo_root", lambda: tmp_path)
        monkeypatch.setenv("TASKWARRIOR_ENABLED", "true")
        monkeypatch.setenv("TASKWARRIOR_DATA_DIR", str(tw_dir))

        store = TaskwarriorStore(data_dir=tw_dir)
        store.create_task("TW Task", "medium", None, None, [])

        result = dashboard_api.handle_tasks(tmp_path / "data")
        titles = [t["title"] for t in result["tasks"]]  # type: ignore[index]
        assert "TW Task" in titles
