"""Contract-level tests for :class:`TaskwarriorStore`.

These do not need the ``task`` CLI — they verify signature parity with
:class:`task_store.TaskStore` and the missing-binary error path via
monkeypatched ``shutil.which``. They always run, even on CI boxes without
Taskwarrior.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

pytest.importorskip("tasklib")

from task_store import TaskStore  # noqa: E402
from taskwarrior_store import TaskwarriorStore  # noqa: E402


PUBLIC_METHODS = (
    "create_task",
    "get_task",
    "list_tasks",
    "list_tasks_by_status",
    "update_task",
    "mark_complete",
    "delete_task",
    "reload",
)


class TestSignatureParity:
    @staticmethod
    def _sig(cls: type, method: str) -> inspect.Signature:
        return inspect.signature(getattr(cls, method), eval_str=True)

    @pytest.mark.parametrize("method", PUBLIC_METHODS)
    def test_parameters_match(self, method: str) -> None:
        ours = self._sig(TaskwarriorStore, method)
        theirs = self._sig(TaskStore, method)
        assert ours.parameters == theirs.parameters, (
            f"{method} parameters differ: "
            f"TaskwarriorStore={ours}, TaskStore={theirs}"
        )

    @pytest.mark.parametrize("method", PUBLIC_METHODS)
    def test_return_annotation_matches(self, method: str) -> None:
        ours = self._sig(TaskwarriorStore, method)
        theirs = self._sig(TaskStore, method)
        assert ours.return_annotation == theirs.return_annotation, (
            f"{method} return type differs: "
            f"TaskwarriorStore={ours.return_annotation}, "
            f"TaskStore={theirs.return_annotation}"
        )


class TestMissingBinaryError:
    def test_missing_binary_raises_runtime_error(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("taskwarrior_store.shutil.which", lambda _: None)
        with pytest.raises(RuntimeError, match="Taskwarrior CLI"):
            TaskwarriorStore(tmp_path / "tw")

    def test_missing_binary_error_names_install_command(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("taskwarrior_store.shutil.which", lambda _: None)
        with pytest.raises(RuntimeError) as exc_info:
            TaskwarriorStore(tmp_path / "tw")
        message = str(exc_info.value)
        assert any(
            hint in message
            for hint in ("choco install", "brew install", "apt install")
        ), f"install hint missing from error: {message!r}"

    def test_missing_binary_does_not_create_data_dir(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("taskwarrior_store.shutil.which", lambda _: None)
        target = tmp_path / "tw"
        with pytest.raises(RuntimeError):
            TaskwarriorStore(target)
        assert not target.exists()
