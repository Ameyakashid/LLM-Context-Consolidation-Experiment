"""Tests for syncall_daemon: preflight, env assembly, signal handling, loop."""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

import syncall_daemon


def _make_paths(tmp_path: Path) -> syncall_daemon.SyncallPaths:
    from syncall_setup import SyncallPaths
    cache = tmp_path / "cache"
    cache.mkdir()
    return SyncallPaths(
        oauth_credentials=tmp_path / "creds.json",
        cache_dir=cache,
        xdg_config_home=cache,
        taskrc_path=cache / "taskrc",
        tw_data_dir=tmp_path / "tw-data",
        log_path=tmp_path / "syncall_daemon.log",
        vendor_dir=tmp_path / "vendor",
    )


def test_resolve_poll_seconds_default() -> None:
    assert syncall_daemon._resolve_poll_seconds({}) == 600


def test_resolve_poll_seconds_accepts_custom_value() -> None:
    assert syncall_daemon._resolve_poll_seconds({"SYNCALL_POLL_SECONDS": "300"}) == 300


def test_resolve_poll_seconds_rejects_non_integer() -> None:
    with pytest.raises(ValueError, match="SYNCALL_POLL_SECONDS"):
        syncall_daemon._resolve_poll_seconds({"SYNCALL_POLL_SECONDS": "lots"})


def test_resolve_poll_seconds_rejects_under_minimum() -> None:
    with pytest.raises(ValueError, match="60-second minimum"):
        syncall_daemon._resolve_poll_seconds({"SYNCALL_POLL_SECONDS": "30"})


def test_build_subprocess_env_overlays_expected_keys(tmp_path: Path) -> None:
    paths = _make_paths(tmp_path)
    base = {"EXISTING": "1", "PYTHONPATH": "/other/path"}
    env = syncall_daemon.build_subprocess_env(base, paths)
    assert env["EXISTING"] == "1"
    assert env["TASKRC"] == str(paths.taskrc_path)
    assert env["TASKDATA"] == str(paths.tw_data_dir)
    assert env["XDG_CONFIG_HOME"] == str(paths.xdg_config_home)
    assert str(paths.vendor_dir) in env["PYTHONPATH"]
    assert "/other/path" in env["PYTHONPATH"]


def test_build_subprocess_env_prepends_vendor_when_pythonpath_absent(tmp_path: Path) -> None:
    paths = _make_paths(tmp_path)
    env = syncall_daemon.build_subprocess_env({}, paths)
    assert env["PYTHONPATH"] == str(paths.vendor_dir)


def test_run_sync_once_returns_zero_on_success() -> None:
    called: dict[str, Any] = {}

    def fake_runner(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        called["cmd"] = cmd
        return subprocess.CompletedProcess(
            args=cmd, returncode=0, stdout="ok", stderr="",
        )

    code, elapsed = syncall_daemon.run_sync_once(
        ["--gcal-calendar", "T"], {"X": "1"}, runner=fake_runner,
    )
    assert code == 0
    assert elapsed >= 0
    assert "tw_gcal_sync" in " ".join(called["cmd"])


def test_run_sync_once_logs_warning_on_nonzero(caplog: pytest.LogCaptureFixture) -> None:
    def failing_runner(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=cmd, returncode=1, stdout="", stderr="boom",
        )

    with caplog.at_level("WARNING"):
        code, _ = syncall_daemon.run_sync_once([], {}, runner=failing_runner)
    assert code == 1
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert any("FAILED code=1" in r.message for r in warnings)


def test_run_sync_once_tolerates_oserror() -> None:
    def boom(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise OSError("exec not found")

    code, _ = syncall_daemon.run_sync_once([], {}, runner=boom)
    assert code == -1


def test_preflight_fails_without_task_binary(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    paths = _make_paths(tmp_path)
    with patch("shutil.which", return_value=None):
        with caplog.at_level("WARNING"):
            code = syncall_daemon._preflight(paths)
    assert code == syncall_daemon.EXIT_PREFLIGHT_FAIL
    assert any("'task' binary" in r.message for r in caplog.records)


def test_preflight_fails_without_oauth_file(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    paths = _make_paths(tmp_path)
    with patch("shutil.which", return_value="/usr/bin/task"):
        with caplog.at_level("WARNING"):
            code = syncall_daemon._preflight(paths)
    assert code == syncall_daemon.EXIT_PREFLIGHT_FAIL
    assert any("GOOGLE_OAUTH_CREDENTIALS" in r.message for r in caplog.records)


def test_main_returns_zero_when_flag_off() -> None:
    code = syncall_daemon.main(env={}, install_signals=False)
    assert code == syncall_daemon.EXIT_DISABLED


def test_main_returns_preflight_fail_on_missing_task(tmp_path: Path) -> None:
    creds = tmp_path / "creds.json"
    creds.write_text("{}", encoding="utf-8")
    env = {
        "SYNCALL_ENABLED": "true",
        "SYNCALL_GCAL_CALENDAR": "T",
        "GOOGLE_OAUTH_CREDENTIALS": str(creds),
        "ADHD_REPO_ROOT": str(tmp_path),
    }
    with patch("shutil.which", return_value=None):
        code = syncall_daemon.main(env=env, install_signals=False)
    assert code == syncall_daemon.EXIT_PREFLIGHT_FAIL


def test_main_runs_one_cycle_and_exits_when_event_set(tmp_path: Path) -> None:
    creds = tmp_path / "creds.json"
    creds.write_text("{}", encoding="utf-8")
    env = {
        "SYNCALL_ENABLED": "true",
        "SYNCALL_GCAL_CALENDAR": "T",
        "GOOGLE_OAUTH_CREDENTIALS": str(creds),
        "SYNCALL_POLL_SECONDS": "600",
        "ADHD_REPO_ROOT": str(tmp_path),
    }
    exit_event = threading.Event()
    call_count = {"n": 0}

    def flip_then_exit(
        cmd: list[str], **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        call_count["n"] += 1
        exit_event.set()
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    # Make preflight succeed: task binary present, syncall importable.
    with patch("shutil.which", return_value="/usr/bin/task"):
        with patch("syncall_daemon._ensure_vendor_on_syspath"):
            with patch("syncall_daemon.importlib", create=True):
                # syncall import succeeds because we pre-imported it via sys.path
                code = syncall_daemon.main(
                    env=env,
                    sleep_fn=lambda _s: None,
                    exit_event=exit_event,
                    runner=flip_then_exit,
                    install_signals=False,
                )
    assert code == syncall_daemon.EXIT_OK
    assert call_count["n"] == 1


def test_signal_handler_sets_exit_event() -> None:
    exit_event = threading.Event()
    syncall_daemon._install_signal_handlers(exit_event)
    import signal
    # Directly invoke the registered handler instead of sending a real
    # signal (os.kill behaves weirdly on Windows in pytest).
    handler = signal.getsignal(signal.SIGINT)
    assert callable(handler)
    handler(signal.SIGINT, None)
    assert exit_event.is_set()


def test_sleep_interruptible_returns_fast_when_event_set() -> None:
    exit_event = threading.Event()
    exit_event.set()
    call_count = {"n": 0}

    def track_sleep(seconds: float) -> None:
        call_count["n"] += 1

    syncall_daemon._sleep_interruptible(600, exit_event, track_sleep)
    # Non-time.sleep callers are called exactly once with full duration
    assert call_count["n"] == 1


def test_sleep_interruptible_stops_early_with_time_sleep() -> None:
    import time
    exit_event = threading.Event()
    call_count = {"n": 0}

    def fake_time_sleep(_seconds: float) -> None:
        call_count["n"] += 1
        if call_count["n"] >= 3:
            exit_event.set()

    # Patch the module attribute so the "sleep_fn is time.sleep" branch triggers
    with patch.object(syncall_daemon.time, "sleep", fake_time_sleep):
        syncall_daemon._sleep_interruptible(600, exit_event, syncall_daemon.time.sleep)
    assert call_count["n"] == 3
