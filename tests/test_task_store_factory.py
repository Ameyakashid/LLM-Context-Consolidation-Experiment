"""Tests for ``task_store_factory.build_task_store``.

Flag on/off/missing branches, path override honoured, returned object
satisfies the Protocol, lazy import of ``TaskwarriorStore`` doesn't
fire on the JSON path, missing binary propagates unswallowed.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from task_store import TaskStore, TaskStoreProtocol
from task_store_factory import (
    build_task_store,
    default_json_tasks_path,
    default_taskwarrior_data_dir,
)


class TestFlagResolution:
    def test_flag_missing_returns_json(self, tmp_path: Path) -> None:
        store = build_task_store(env={}, repo_root=tmp_path)
        assert isinstance(store, TaskStore)

    def test_flag_false_returns_json(self, tmp_path: Path) -> None:
        store = build_task_store(
            env={"TASKWARRIOR_ENABLED": "false"}, repo_root=tmp_path,
        )
        assert isinstance(store, TaskStore)

    def test_flag_empty_returns_json(self, tmp_path: Path) -> None:
        store = build_task_store(
            env={"TASKWARRIOR_ENABLED": ""}, repo_root=tmp_path,
        )
        assert isinstance(store, TaskStore)

    def test_flag_nontrue_value_returns_json(self, tmp_path: Path) -> None:
        store = build_task_store(
            env={"TASKWARRIOR_ENABLED": "1"}, repo_root=tmp_path,
        )
        assert isinstance(store, TaskStore)


class TestJsonPathResolution:
    def test_default_json_path_under_workspace_data(
        self, tmp_path: Path,
    ) -> None:
        expected = tmp_path / "workspace" / "data" / "tasks.json"
        assert default_json_tasks_path(tmp_path) == expected

    def test_json_parent_dir_created(self, tmp_path: Path) -> None:
        build_task_store(env={}, repo_root=tmp_path)
        assert (tmp_path / "workspace" / "data").is_dir()

    def test_returned_store_satisfies_protocol(self, tmp_path: Path) -> None:
        store = build_task_store(env={}, repo_root=tmp_path)
        assert isinstance(store, TaskStoreProtocol)


class TestTaskwarriorDataDirResolution:
    def test_default_taskwarrior_dir_under_workspace_data(
        self, tmp_path: Path,
    ) -> None:
        expected = tmp_path / "workspace" / "data" / "taskwarrior"
        assert default_taskwarrior_data_dir(tmp_path) == expected


class TestTaskwarriorBranch:
    @pytest.mark.skipif(
        shutil.which("task") is None,
        reason="Taskwarrior CLI not installed",
    )
    def test_flag_on_returns_taskwarrior_store(self, tmp_path: Path) -> None:
        pytest.importorskip("tasklib")
        from taskwarrior_store import TaskwarriorStore
        store = build_task_store(
            env={"TASKWARRIOR_ENABLED": "true"}, repo_root=tmp_path,
        )
        assert isinstance(store, TaskwarriorStore)

    @pytest.mark.skipif(
        shutil.which("task") is None,
        reason="Taskwarrior CLI not installed",
    )
    def test_taskwarrior_data_dir_env_override(self, tmp_path: Path) -> None:
        pytest.importorskip("tasklib")
        override_dir = tmp_path / "custom_tw"
        build_task_store(
            env={
                "TASKWARRIOR_ENABLED": "true",
                "TASKWARRIOR_DATA_DIR": str(override_dir),
            },
            repo_root=tmp_path,
        )
        assert override_dir.is_dir()

    def test_missing_binary_raises_unswallowed(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        pytest.importorskip("tasklib")
        monkeypatch.setattr("taskwarrior_store.shutil.which", lambda _: None)
        with pytest.raises(RuntimeError, match="Taskwarrior CLI"):
            build_task_store(
                env={"TASKWARRIOR_ENABLED": "true"}, repo_root=tmp_path,
            )


class TestLazyTaskwarriorImport:
    def test_json_path_does_not_import_taskwarrior_store(
        self, tmp_path: Path,
    ) -> None:
        script = (
            "import sys\n"
            f"sys.path.insert(0, {str(Path(__file__).resolve().parent.parent)!r})\n"
            "import task_store_factory\n"
            "from pathlib import Path\n"
            f"task_store_factory.build_task_store(env={{}}, repo_root=Path({str(tmp_path)!r}))\n"
            "print('tasklib-loaded=' + str('tasklib' in sys.modules))\n"
            "print('tw-loaded=' + str('taskwarrior_store' in sys.modules))\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, check=True,
        )
        assert "tasklib-loaded=False" in result.stdout
        assert "tw-loaded=False" in result.stdout
