"""MagicMirror² auto-launch supervisor.

Provides a flag-gated way for ``start.py`` to spawn and reap
MagicMirror² as a supervised child process, reusing the subprocess
lifecycle posture that ``spawn_syncall_daemon`` / ``stop_syncall_daemon``
established for the syncall daemon.

The flag is ``MAGICMIRROR_AUTOSTART_ENABLED`` (default false). This flag
is **orthogonal** to ``MAGICMIRROR_ENABLED`` — the latter controls
setup-time install and config rendering; this one controls runtime
autostart. A user can have the display installed but choose to launch
``npm start`` themselves when they want the mirror up.
"""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import IO

log = logging.getLogger(__name__)

MAGICMIRROR_STOP_TIMEOUT_S = 10.0
MAGICMIRROR_KILL_TIMEOUT_S = 5.0

_LOG_FILENAME = "magicmirror.log"
_ERR_FILENAME = "magicmirror.err"


def is_magicmirror_autostart_enabled(env: Mapping[str, str]) -> bool:
    """Return True when the user opted into the in-process mirror launcher.

    Matches the case-insensitive whitespace-stripped ``== "true"``
    convention used by ``is_magicmirror_enabled``,
    ``is_pulse_engine_enabled``, ``is_syncall_enabled``, and
    ``is_gcal_enabled``.
    """
    return env.get("MAGICMIRROR_AUTOSTART_ENABLED", "false").strip().lower() == "true"


def build_magicmirror_command(repo_root: Path) -> list[str]:
    """Return the argv for ``npm start`` under ``<repo>/magicmirror``.

    The list form is required by code-rules: no ``shell=True``, no
    string interpolation. The ``--prefix`` flag is npm's documented way
    to run a script in a different working directory without a ``cd``.
    """
    return ["npm", "start", "--prefix", str(repo_root / "magicmirror")]


def _resolve_log_dir(repo_root: Path, env: Mapping[str, str]) -> Path:
    override = env.get("ADHD_LOG_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    return repo_root / "logs"


def _open_log_streams(log_dir: Path) -> tuple[IO[bytes], IO[bytes]] | None:
    """Open the two log files in append-binary mode.

    Returns ``None`` when the directory cannot be created or the files
    cannot be opened, so the caller can fall back to ``DEVNULL``.
    """
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log.debug("mkdir failed for %s: %s", log_dir, exc)
        return None
    try:
        stdout = (log_dir / _LOG_FILENAME).open("ab")
    except OSError as exc:
        log.debug("open %s failed: %s", log_dir / _LOG_FILENAME, exc)
        return None
    try:
        stderr = (log_dir / _ERR_FILENAME).open("ab")
    except OSError as exc:
        stdout.close()
        log.debug("open %s failed: %s", log_dir / _ERR_FILENAME, exc)
        return None
    return stdout, stderr


class MagicMirrorProcess:
    """Single-use supervised wrapper around a MagicMirror child process.

    Lifecycle: construct → ``start()`` (at most once while alive; no-op
    if already running) → ``stop()`` (SIGTERM with timeout, SIGKILL
    fallback). After ``stop()`` the instance is spent; calling
    ``start()`` again raises ``RuntimeError``.
    """

    def __init__(
        self,
        argv: list[str],
        popen_factory: type[subprocess.Popen[bytes]],
        stdout: IO[bytes] | int,
        stderr: IO[bytes] | int,
        cwd: Path,
    ) -> None:
        self._argv = argv
        self._popen_factory = popen_factory
        self._stdout: IO[bytes] | int = stdout
        self._stderr: IO[bytes] | int = stderr
        self._cwd = cwd
        self._proc: subprocess.Popen[bytes] | None = None
        self._stopped = False

    def start(self) -> None:
        if self._stopped:
            raise RuntimeError(
                "MagicMirrorProcess.start called after stop; "
                "wrappers are single-use."
            )
        if self._proc is not None:
            return
        try:
            self._proc = self._popen_factory(
                self._argv,
                stdout=self._stdout,
                stderr=self._stderr,
                cwd=str(self._cwd),
            )
        except OSError:
            self._close_streams()
            raise

    def stop(self, timeout: float = MAGICMIRROR_STOP_TIMEOUT_S) -> None:
        proc = self._proc
        self._stopped = True
        if proc is None:
            self._close_streams()
            return
        if proc.poll() is not None:
            log.info(
                "MagicMirror child already exited with code %d",
                proc.returncode,
            )
            self._close_streams()
            return
        log.info("Stopping MagicMirror child (PID %s)", getattr(proc, "pid", "?"))
        proc.terminate()
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            log.warning(
                "MagicMirror did not exit within %.1fs; sending kill",
                timeout,
            )
            proc.kill()
            try:
                proc.wait(timeout=MAGICMIRROR_KILL_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                log.error(
                    "MagicMirror child still alive after kill; giving up"
                )
        finally:
            self._close_streams()

    def is_running(self) -> bool:
        if self._proc is None:
            return False
        return self._proc.poll() is None

    def _close_streams(self) -> None:
        for stream in (self._stdout, self._stderr):
            if isinstance(stream, int):
                continue
            try:
                stream.close()
            except OSError:
                log.debug("failed to close MagicMirror log stream", exc_info=True)


def launch_magicmirror(
    repo_root: Path,
    env: Mapping[str, str],
    popen: type[subprocess.Popen[bytes]] = subprocess.Popen,  # type: ignore[assignment]
) -> MagicMirrorProcess | None:
    """Flag-gated factory for a running ``MagicMirrorProcess``.

    Returns ``None`` when ``MAGICMIRROR_AUTOSTART_ENABLED`` is not the
    string ``"true"`` (case-insensitive). Raises ``RuntimeError`` when
    the flag is on but ``magicmirror/config/config.js`` is missing (the
    user needs to run ``setup_workspace()`` first, which renders the
    config from its template).
    """
    if not is_magicmirror_autostart_enabled(env):
        return None
    config_path = repo_root / "magicmirror" / "config" / "config.js"
    if not config_path.is_file():
        raise RuntimeError(
            f"MagicMirror config missing at {config_path} — "
            "rendered config.js not found. Run setup_workspace() "
            "first (it executes render_magicmirror_config)."
        )
    log_dir = _resolve_log_dir(repo_root, env)
    streams = _open_log_streams(log_dir)
    stdout: IO[bytes] | int
    stderr: IO[bytes] | int
    if streams is None:
        log.warning(
            "MagicMirror log directory %s unwritable; "
            "routing child output to DEVNULL",
            log_dir,
        )
        stdout = subprocess.DEVNULL
        stderr = subprocess.DEVNULL
    else:
        stdout, stderr = streams
    process = MagicMirrorProcess(
        argv=build_magicmirror_command(repo_root),
        popen_factory=popen,
        stdout=stdout,
        stderr=stderr,
        cwd=repo_root,
    )
    process.start()
    log.info(
        "MAGICMIRROR_AUTOSTART_ENABLED=true — MagicMirror child spawned"
    )
    return process
