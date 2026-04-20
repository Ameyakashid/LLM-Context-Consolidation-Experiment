"""Shared subprocess driver for the Mac smoke test pair.

Used by ``tests/test_mac_smoke.py`` (baseline + shutdown) and
``tests/test_mac_smoke_phase2.py`` (flag cells + rollback). Spawns
``start.py`` under the repo's ``.venv`` interpreter, tails stdout+stderr
for marker substrings within a 60-second watchdog, sends SIGINT, and
asserts graceful shutdown within 15 s.

This is a test harness, not production code — the single-responsibility
caveat in code-rules applies: it would be writable in 10 lines if the
behavior were trivial, but the marker-match-with-watchdog-and-SIGINT
loop is non-trivial and duplicating it between two test files would be
worse than a shared private helper.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
VENV_PYTHON = REPO_ROOT / ".venv" / "bin" / "python"
START_SCRIPT = REPO_ROOT / "start.py"

BOOT_WINDOW_S = 60.0
SHUTDOWN_DEADLINE_S = 15.0
POLL_INTERVAL_S = 0.25

BASELINE_MARKERS: tuple[str, ...] = (
    "Starting custom gateway",
    "Custom gateway ready: 6 hooks",
    "Dashboard API listening on 0.0.0.0:8085",
    "Registered 5 task tools",
    "Registered 5 buffer tools",
    "Registered 3 memory tools",
    "Registered 1 voice tool",
)

TRACEBACK_SIGNAL = "Traceback (most recent call last):"

FAKE_CREDENTIALS: dict[str, str] = {
    "OPENROUTER_API_KEY": "sk-or-v1-smoke-test-fake-key",
    "TELEGRAM_BOT_TOKEN": "000000:SMOKEfaketoken",
    "TELEGRAM_USER_ID": "99",
}


@dataclass
class SmokeResult:
    """Captured output and timing from one bounded ``start.py`` run."""

    stdout: str
    return_code: int
    boot_seconds: float
    shutdown_seconds: float
    markers_seen: dict[str, bool] = field(default_factory=dict)


def require_venv() -> None:
    """Skip the calling test if the Mac venv interpreter is missing."""
    if not VENV_PYTHON.is_file():
        pytest.skip(
            f"Mac venv python not present at {VENV_PYTHON}; run "
            "bash install_mac.sh first (MAC_DEPLOYMENT.md prerequisite)."
        )


def smoke_env(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """Merge the current process env with fake credentials and overrides."""
    env = dict(os.environ)
    env.update(FAKE_CREDENTIALS)
    if extra:
        env.update(extra)
    return env


def run_until_markers(
    markers: tuple[str, ...],
    env: Mapping[str, str],
    boot_window_s: float = BOOT_WINDOW_S,
) -> SmokeResult:
    """Spawn start.py, watch for marker substrings, then SIGINT and join."""
    require_venv()
    start_time = time.monotonic()
    proc = subprocess.Popen(
        [str(VENV_PYTHON), str(START_SCRIPT)],
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=dict(env),
    )
    captured: list[str] = []
    markers_seen: dict[str, bool] = {marker: False for marker in markers}
    stream = proc.stdout
    assert stream is not None
    try:
        while time.monotonic() - start_time < boot_window_s:
            if proc.poll() is not None:
                break
            line = stream.readline().decode("utf-8", errors="replace")
            if not line:
                time.sleep(POLL_INTERVAL_S)
                continue
            captured.append(line)
            for marker in markers:
                if not markers_seen[marker] and marker in line:
                    markers_seen[marker] = True
            if all(markers_seen.values()):
                break
        boot_seconds = time.monotonic() - start_time
        shutdown_start = time.monotonic()
        if proc.poll() is None:
            proc.send_signal(signal.SIGINT)
            try:
                remainder = proc.communicate(timeout=SHUTDOWN_DEADLINE_S)[0]
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate(timeout=5)
                raise AssertionError(
                    "start.py did not shut down within "
                    f"{SHUTDOWN_DEADLINE_S:.0f}s of SIGINT"
                ) from None
            if remainder:
                captured.append(remainder.decode("utf-8", errors="replace"))
        shutdown_seconds = time.monotonic() - shutdown_start
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
    return SmokeResult(
        stdout="".join(captured),
        return_code=proc.returncode if proc.returncode is not None else -1,
        boot_seconds=boot_seconds,
        shutdown_seconds=shutdown_seconds,
        markers_seen=markers_seen,
    )


def traceback_excerpt(text: str) -> str:
    """Return the first 1500 chars starting at the first traceback header."""
    idx = text.find(TRACEBACK_SIGNAL)
    if idx == -1:
        return ""
    return text[idx : idx + 1500]
