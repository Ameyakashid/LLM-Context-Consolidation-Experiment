"""Lifecycle tests for magicmirror_launcher via an injected Popen stub."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any

import pytest

from magicmirror_launcher import (
    MagicMirrorProcess,
    launch_magicmirror,
)


class _StubPopen:
    """Popen stand-in that records constructor arguments."""

    instances: list["_StubPopen"] = []

    def __init__(self, argv: list[str], **kwargs: Any) -> None:
        self.argv = argv
        self.kwargs = kwargs
        self.pid = 4321
        self._terminated = False
        self._killed = False
        self.returncode = 0
        _StubPopen.instances.append(self)

    def poll(self) -> int | None:
        return self.returncode if self._terminated else None

    def terminate(self) -> None:
        self._terminated = True

    def wait(self, timeout: float | None = None) -> int:
        return self.returncode

    def kill(self) -> None:
        self._killed = True
        self._terminated = True


@pytest.fixture(autouse=True)
def _reset_stub_popen() -> None:
    _StubPopen.instances = []


def _make_config(tmp_path: Path) -> Path:
    config_dir = tmp_path / "magicmirror" / "config"
    config_dir.mkdir(parents=True)
    config_path = config_dir / "config.js"
    config_path.write_text("// rendered config\n", encoding="utf-8")
    return config_path


def test_flag_on_spawns_popen(tmp_path: Path) -> None:
    _make_config(tmp_path)
    handle = launch_magicmirror(
        tmp_path,
        {"MAGICMIRROR_AUTOSTART_ENABLED": "true"},
        popen=_StubPopen,  # type: ignore[arg-type]
    )
    assert handle is not None
    assert len(_StubPopen.instances) == 1


def test_flag_on_popen_argv_contains_magicmirror(tmp_path: Path) -> None:
    _make_config(tmp_path)
    launch_magicmirror(
        tmp_path,
        {"MAGICMIRROR_AUTOSTART_ENABLED": "true"},
        popen=_StubPopen,  # type: ignore[arg-type]
    )
    argv = _StubPopen.instances[0].argv
    assert argv[0] == "npm"
    assert argv[1] == "start"
    assert argv[2] == "--prefix"
    assert argv[3] == str(tmp_path / "magicmirror")


def test_flag_off_does_not_touch_popen(tmp_path: Path) -> None:
    handle = launch_magicmirror(
        tmp_path,
        {"MAGICMIRROR_AUTOSTART_ENABLED": "false"},
        popen=_StubPopen,  # type: ignore[arg-type]
    )
    assert handle is None
    assert _StubPopen.instances == []


def test_is_running_true_for_alive_child(tmp_path: Path) -> None:
    _make_config(tmp_path)
    handle = launch_magicmirror(
        tmp_path,
        {"MAGICMIRROR_AUTOSTART_ENABLED": "true"},
        popen=_StubPopen,  # type: ignore[arg-type]
    )
    assert handle is not None
    assert handle.is_running() is True


def test_stop_terminates_running_child(tmp_path: Path) -> None:
    _make_config(tmp_path)
    handle = launch_magicmirror(
        tmp_path,
        {"MAGICMIRROR_AUTOSTART_ENABLED": "true"},
        popen=_StubPopen,  # type: ignore[arg-type]
    )
    assert handle is not None
    handle.stop()
    stub = _StubPopen.instances[0]
    assert stub._terminated is True
    assert handle.is_running() is False


def test_stop_noop_when_child_already_exited(tmp_path: Path) -> None:
    _make_config(tmp_path)
    handle = launch_magicmirror(
        tmp_path,
        {"MAGICMIRROR_AUTOSTART_ENABLED": "true"},
        popen=_StubPopen,  # type: ignore[arg-type]
    )
    assert handle is not None
    stub = _StubPopen.instances[0]
    stub._terminated = True
    stub.returncode = 0
    handle.stop()
    assert stub._killed is False


def test_stop_kills_on_timeout(tmp_path: Path) -> None:
    class HangingPopen(_StubPopen):
        def wait(self, timeout: float | None = None) -> int:
            if not self._killed:
                raise subprocess.TimeoutExpired(
                    cmd=self.argv, timeout=timeout or 0
                )
            return 0

    _make_config(tmp_path)
    handle = launch_magicmirror(
        tmp_path,
        {"MAGICMIRROR_AUTOSTART_ENABLED": "true"},
        popen=HangingPopen,  # type: ignore[arg-type]
    )
    assert handle is not None
    handle.stop(timeout=0.01)
    stub = _StubPopen.instances[0]
    assert stub._killed is True


def test_stop_is_idempotent(tmp_path: Path) -> None:
    _make_config(tmp_path)
    handle = launch_magicmirror(
        tmp_path,
        {"MAGICMIRROR_AUTOSTART_ENABLED": "true"},
        popen=_StubPopen,  # type: ignore[arg-type]
    )
    assert handle is not None
    handle.stop()
    handle.stop()


def test_start_raises_after_stop(tmp_path: Path) -> None:
    _make_config(tmp_path)
    handle = launch_magicmirror(
        tmp_path,
        {"MAGICMIRROR_AUTOSTART_ENABLED": "true"},
        popen=_StubPopen,  # type: ignore[arg-type]
    )
    assert handle is not None
    handle.stop()
    with pytest.raises(RuntimeError, match="single-use"):
        handle.start()


def test_default_log_dir_is_repo_logs(tmp_path: Path) -> None:
    _make_config(tmp_path)
    launch_magicmirror(
        tmp_path,
        {"MAGICMIRROR_AUTOSTART_ENABLED": "true"},
        popen=_StubPopen,  # type: ignore[arg-type]
    )
    logs_dir = tmp_path / "logs"
    assert (logs_dir / "magicmirror.log").is_file()
    assert (logs_dir / "magicmirror.err").is_file()


def test_adhd_log_dir_override(tmp_path: Path) -> None:
    _make_config(tmp_path)
    custom_dir = tmp_path / "custom_logs"
    launch_magicmirror(
        tmp_path,
        {
            "MAGICMIRROR_AUTOSTART_ENABLED": "true",
            "ADHD_LOG_DIR": str(custom_dir),
        },
        popen=_StubPopen,  # type: ignore[arg-type]
    )
    assert (custom_dir / "magicmirror.log").is_file()
    assert (custom_dir / "magicmirror.err").is_file()


def test_adhd_log_dir_expands_tilde(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _make_config(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    launch_magicmirror(
        tmp_path,
        {
            "MAGICMIRROR_AUTOSTART_ENABLED": "true",
            "ADHD_LOG_DIR": "~/app_logs",
        },
        popen=_StubPopen,  # type: ignore[arg-type]
    )
    expanded = home / "app_logs"
    assert (expanded / "magicmirror.log").is_file()


def test_log_dir_unwritable_falls_back_to_devnull(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _make_config(tmp_path)
    original_mkdir = Path.mkdir

    def refuse_mkdir(self: Path, *args: Any, **kwargs: Any) -> None:
        if self.name.endswith("readonly_logs"):
            raise PermissionError(f"mocked read-only path: {self}")
        original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", refuse_mkdir)
    caplog.set_level(logging.WARNING, logger="magicmirror_launcher")
    handle = launch_magicmirror(
        tmp_path,
        {
            "MAGICMIRROR_AUTOSTART_ENABLED": "true",
            "ADHD_LOG_DIR": str(tmp_path / "readonly_logs"),
        },
        popen=_StubPopen,  # type: ignore[arg-type]
    )
    assert handle is not None
    stub = _StubPopen.instances[0]
    assert stub.kwargs["stdout"] == subprocess.DEVNULL
    assert stub.kwargs["stderr"] == subprocess.DEVNULL
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("unwritable" in r.getMessage().lower() for r in warnings)


def test_log_file_kwargs_passed_to_popen(tmp_path: Path) -> None:
    _make_config(tmp_path)
    launch_magicmirror(
        tmp_path,
        {"MAGICMIRROR_AUTOSTART_ENABLED": "true"},
        popen=_StubPopen,  # type: ignore[arg-type]
    )
    stub = _StubPopen.instances[0]
    stdout_stream = stub.kwargs["stdout"]
    stderr_stream = stub.kwargs["stderr"]
    assert stdout_stream is not subprocess.DEVNULL
    assert stderr_stream is not subprocess.DEVNULL
    assert hasattr(stdout_stream, "write")
    assert hasattr(stderr_stream, "write")


def test_magicmirror_process_rejects_double_start(tmp_path: Path) -> None:
    _make_config(tmp_path)
    handle = launch_magicmirror(
        tmp_path,
        {"MAGICMIRROR_AUTOSTART_ENABLED": "true"},
        popen=_StubPopen,  # type: ignore[arg-type]
    )
    assert handle is not None
    handle.start()
    assert len(_StubPopen.instances) == 1


def test_new_code_has_no_platform_branches() -> None:
    launcher = Path(__file__).resolve().parent.parent / "magicmirror_launcher.py"
    source = launcher.read_text(encoding="utf-8")
    assert "sys.platform" not in source
    assert "os.name" not in source


def test_launcher_file_line_budget() -> None:
    launcher = Path(__file__).resolve().parent.parent / "magicmirror_launcher.py"
    lines = launcher.read_text(encoding="utf-8").splitlines()
    assert len(lines) <= 300, f"magicmirror_launcher.py is {len(lines)} lines"


def test_process_wraps_popen_type(tmp_path: Path) -> None:
    _make_config(tmp_path)
    handle = launch_magicmirror(
        tmp_path,
        {"MAGICMIRROR_AUTOSTART_ENABLED": "true"},
        popen=_StubPopen,  # type: ignore[arg-type]
    )
    assert isinstance(handle, MagicMirrorProcess)
