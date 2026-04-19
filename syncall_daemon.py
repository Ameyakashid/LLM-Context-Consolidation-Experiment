"""Syncall long-running daemon.

Polls ``tw_gcal_sync`` once per ``SYNCALL_POLL_SECONDS`` (default 600),
each tick as a fresh subprocess. Design motivation: ``tw_gcal_sync`` is a
one-shot script upstream — it returns 0 after a single sync cycle. This
daemon owns the loop, signal handling, and log rollup so ``start.py`` can
supervise it like the other long-running subsystems.

Entry point: ``python -m syncall_daemon`` or ``syncall_daemon.main()``.
``start.py`` spawns this via ``subprocess.Popen`` when ``SYNCALL_ENABLED=true``.
"""

from __future__ import annotations

import logging
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import FrameType
from typing import Callable, Mapping

from syncall_args import (
    SyncallArgsConfig,
    build_syncall_args,
    read_syncall_args_config,
)
from syncall_setup import (
    SyncallPaths,
    is_syncall_enabled,
    resolve_syncall_paths,
    write_repo_scoped_taskrc,
)
from taskwarrior_setup import resolve_taskwarrior_data_dir

log = logging.getLogger("syncall_daemon")

DEFAULT_POLL_SECONDS = 600
EXIT_PREFLIGHT_FAIL = 2
EXIT_DISABLED = 0
EXIT_OK = 0

SleepFn = Callable[[float], None]


def _resolve_repo_root() -> Path:
    override = os.environ.get("ADHD_REPO_ROOT", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parent


def _ensure_vendor_on_syspath(vendor_dir: Path) -> None:
    """Prepend ``vendor/syncall`` to ``sys.path`` so ``import syncall`` works.

    See ``vendor/syncall/.vendor-source.md`` for why we do not pip-install.
    Idempotent.
    """
    vendor_str = str(vendor_dir)
    if vendor_str not in sys.path:
        sys.path.insert(0, vendor_str)


def _preflight(paths: SyncallPaths) -> int:
    """Return 0 when all daemon prerequisites are satisfied, else non-zero.

    Failures are logged at WARNING with remediation, never silently.
    """
    if shutil.which("task") is None:
        log.warning(
            "Pre-flight FAIL: 'task' binary not on PATH. Install Taskwarrior "
            "first: brew install task (macOS), choco install task (Windows), "
            "apt install taskwarrior (Debian/Ubuntu).",
        )
        return EXIT_PREFLIGHT_FAIL
    _ensure_vendor_on_syspath(paths.vendor_dir)
    try:
        import syncall  # type: ignore[import-not-found]  # noqa: F401
    except ImportError as err:
        log.warning(
            "Pre-flight FAIL: could not import syncall from %s (%s). "
            "Verify vendor/syncall/ exists and transitive deps in "
            "requirements.txt are installed.",
            paths.vendor_dir, err,
        )
        return EXIT_PREFLIGHT_FAIL
    if paths.oauth_credentials == Path("") or not paths.oauth_credentials.exists():
        log.warning(
            "Pre-flight FAIL: GOOGLE_OAUTH_CREDENTIALS points at missing "
            "file %s. Download the desktop OAuth client JSON from Google "
            "Cloud Console and point GOOGLE_OAUTH_CREDENTIALS at it.",
            paths.oauth_credentials or "<unset>",
        )
        return EXIT_PREFLIGHT_FAIL
    return 0


def _resolve_poll_seconds(env: Mapping[str, str]) -> int:
    raw = env.get("SYNCALL_POLL_SECONDS", "").strip()
    if not raw:
        return DEFAULT_POLL_SECONDS
    try:
        value = int(raw)
    except ValueError as err:
        raise ValueError(
            f"SYNCALL_POLL_SECONDS={raw!r} is not a valid integer. "
            f"Leave blank to use the default {DEFAULT_POLL_SECONDS}."
        ) from err
    if value < 60:
        raise ValueError(
            f"SYNCALL_POLL_SECONDS={value} is below the 60-second minimum. "
            f"Under-60 polling risks Google Calendar API rate-limit "
            f"rejections and offers no user-visible latency benefit."
        )
    return value


def build_subprocess_env(
    base_env: Mapping[str, str], paths: SyncallPaths,
) -> dict[str, str]:
    """Return the env dict for the ``tw_gcal_sync`` subprocess.

    Layered onto the caller's env: ``TASKRC`` + ``TASKDATA`` redirect the
    TW CLI to the repo-scoped data dir; ``XDG_CONFIG_HOME`` scopes syncall's
    combinations YAML + serdes pickles to ``workspace/data/syncall_cache/``
    rather than ``~/.config/syncall/``. ``PYTHONPATH`` lets the child
    import syncall from the vendor tree.
    """
    env = dict(base_env)
    existing_pythonpath = env.get("PYTHONPATH", "")
    vendor = str(paths.vendor_dir)
    if existing_pythonpath:
        env["PYTHONPATH"] = vendor + os.pathsep + existing_pythonpath
    else:
        env["PYTHONPATH"] = vendor
    env["TASKRC"] = str(paths.taskrc_path)
    env["TASKDATA"] = str(paths.tw_data_dir)
    env["XDG_CONFIG_HOME"] = str(paths.xdg_config_home)
    return env


def run_sync_once(
    args: list[str],
    sub_env: dict[str, str],
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> tuple[int, float]:
    """Invoke ``tw_gcal_sync`` once. Return (returncode, elapsed_seconds).

    Never raises on non-zero exit — the daemon loop logs and continues.
    ``runner`` is injectable for tests.
    """
    cmd = [sys.executable, "-m", "syncall.scripts.tw_gcal_sync", *args]
    started = time.monotonic()
    try:
        result = runner(
            cmd,
            env=sub_env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
    except OSError as err:
        elapsed = time.monotonic() - started
        log.warning("sync FAILED: could not spawn subprocess (%s)", err)
        return (-1, elapsed)
    elapsed = time.monotonic() - started
    stderr_tail = (result.stderr or "").strip().splitlines()[-5:]
    if result.returncode == 0:
        log.info("sync OK in %.1fs", elapsed)
    else:
        log.warning(
            "sync FAILED code=%d in %.1fs. stderr tail: %s",
            result.returncode, elapsed, " | ".join(stderr_tail) or "(empty)",
        )
    return (result.returncode, elapsed)


def _install_signal_handlers(exit_event: threading.Event) -> None:
    def _handler(_signum: int, _frame: FrameType | None) -> None:
        log.info("Shutdown signal received; finishing current tick then exiting.")
        exit_event.set()
    signal.signal(signal.SIGINT, _handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handler)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _handler)


def _sleep_interruptible(
    poll_seconds: int,
    exit_event: threading.Event,
    sleep_fn: SleepFn,
) -> None:
    """Sleep ``poll_seconds``, waking early when ``exit_event`` is set.

    ``sleep_fn`` is injectable for tests that want to skip real sleeping.
    When the caller passes ``time.sleep``, we loop in 1-second slices so
    a signal flips the exit flag and interrupts the wait promptly.
    """
    if sleep_fn is time.sleep:
        slept = 0.0
        slice_s = 1.0
        while slept < poll_seconds and not exit_event.is_set():
            sleep_fn(slice_s)
            slept += slice_s
        return
    sleep_fn(poll_seconds)


def _run_loop(
    config: SyncallArgsConfig,
    paths: SyncallPaths,
    base_env: Mapping[str, str],
    poll_seconds: int,
    exit_event: threading.Event,
    sleep_fn: SleepFn,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> int:
    args = build_syncall_args(config)
    sub_env = build_subprocess_env(base_env, paths)
    log.info("Starting syncall daemon (poll=%ds)", poll_seconds)
    while not exit_event.is_set():
        run_sync_once(args, sub_env, runner=runner)
        if exit_event.is_set():
            break
        _sleep_interruptible(poll_seconds, exit_event, sleep_fn)
    log.info("Syncall daemon exiting cleanly.")
    return EXIT_OK


def main(
    env: Mapping[str, str] | None = None,
    sleep_fn: SleepFn | None = None,
    exit_event: threading.Event | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    install_signals: bool = True,
) -> int:
    """Daemon entry point. Returns a process exit code.

    All impure inputs (env, sleep, exit event, subprocess runner) are
    injectable so tests can drive one tick without real I/O.
    """
    effective_env: Mapping[str, str] = env if env is not None else os.environ
    effective_sleep: SleepFn = sleep_fn if sleep_fn is not None else time.sleep
    effective_exit = exit_event if exit_event is not None else threading.Event()
    effective_runner = runner if runner is not None else subprocess.run
    if not is_syncall_enabled(effective_env):
        log.info("SYNCALL_ENABLED=false — daemon exiting.")
        return EXIT_DISABLED
    repo_root = _resolve_repo_root()
    tw_default = repo_root / "workspace" / "data" / "taskwarrior"
    tw_data_dir = resolve_taskwarrior_data_dir(dict(effective_env), tw_default)
    paths = resolve_syncall_paths(effective_env, repo_root, tw_data_dir)
    tw_data_dir.mkdir(parents=True, exist_ok=True)
    paths.cache_dir.mkdir(parents=True, exist_ok=True)
    write_repo_scoped_taskrc(paths.taskrc_path, paths.tw_data_dir)
    preflight_code = _preflight(paths)
    if preflight_code != 0:
        return preflight_code
    try:
        config = read_syncall_args_config(effective_env)
        poll_seconds = _resolve_poll_seconds(effective_env)
    except ValueError as err:
        log.warning("Config error: %s", err)
        return EXIT_PREFLIGHT_FAIL
    if install_signals:
        _install_signal_handlers(effective_exit)
    return _run_loop(
        config=config,
        paths=paths,
        base_env=effective_env,
        poll_seconds=poll_seconds,
        exit_event=effective_exit,
        sleep_fn=effective_sleep,
        runner=effective_runner,
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    sys.exit(main())
