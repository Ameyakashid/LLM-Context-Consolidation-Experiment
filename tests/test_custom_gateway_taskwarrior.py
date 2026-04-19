"""Flag-on/flag-off end-to-end: create_stores picks the right backend.

The factory construction site is ``custom_gateway.create_stores``; this
file exercises it with both flag values. When the ``task`` CLI is
missing, the flag-on case is skipped because constructing
``TaskwarriorStore`` would raise ``RuntimeError`` (by design — no silent
fallback).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from custom_gateway import create_stores
from task_store import TaskStore, TaskStoreProtocol


class TestFlagOffReturnsJson:
    def test_stores_task_is_json_backend(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        stores = create_stores(
            data_dir, repo_root=tmp_path, env={},
        )
        assert isinstance(stores["task"], TaskStore)

    def test_stores_task_satisfies_protocol(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        stores = create_stores(
            data_dir, repo_root=tmp_path, env={"TASKWARRIOR_ENABLED": "false"},
        )
        assert isinstance(stores["task"], TaskStoreProtocol)


@pytest.mark.skipif(
    shutil.which("task") is None,
    reason="Taskwarrior CLI not installed",
)
class TestFlagOnReturnsTaskwarrior:
    def test_stores_task_is_taskwarrior_backend(self, tmp_path: Path) -> None:
        pytest.importorskip("tasklib")
        from taskwarrior_store import TaskwarriorStore

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        tw_dir = tmp_path / "custom_tw"
        stores = create_stores(
            data_dir,
            repo_root=tmp_path,
            env={
                "TASKWARRIOR_ENABLED": "true",
                "TASKWARRIOR_DATA_DIR": str(tw_dir),
            },
        )
        assert isinstance(stores["task"], TaskwarriorStore)
