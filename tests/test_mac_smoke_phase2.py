"""Phase 2 flag cells + LaunchAgent rollback (Part A.3 + AC #13 of sub-05).

Module-skipped on non-Darwin hosts — the companion file
``tests/test_mac_smoke.py`` documents the sanctioned ``sys.platform``
branch. Shared subprocess driver lives in
``tests/_mac_smoke_harness.py`` so both files drive ``start.py`` the
same way.
"""

from __future__ import annotations

import sys

import pytest

if sys.platform != "darwin":
    pytest.skip(
        "tests/test_mac_smoke_phase2.py is Mac-only (AC #1 of sub-05)",
        allow_module_level=True,
    )

# ruff: noqa: E402
import re
import shutil
import subprocess
from pathlib import Path

from tests._mac_smoke_harness import (
    BASELINE_MARKERS,
    REPO_ROOT,
    TRACEBACK_SIGNAL,
    require_venv,
    run_until_markers,
    smoke_env,
    traceback_excerpt,
)

INSTALL_LAUNCHAGENT = REPO_ROOT / "scripts" / "install_launchagent.sh"
UNINSTALL_LAUNCHAGENT = REPO_ROOT / "scripts" / "uninstall_launchagent.sh"
PLIST_PATH = (
    Path.home() / "Library" / "LaunchAgents" / "com.adhdassistant.bot.plist"
)


def _assert_no_traceback(stdout: str) -> None:
    assert TRACEBACK_SIGNAL not in stdout, (
        f"Traceback in start.py output:\n{traceback_excerpt(stdout)}"
    )


class TestPhase2FlagCells:
    """One cell per Phase 2 adapter. Each flips a single flag."""

    def test_magicmirror_flag_on_logs_ready(self) -> None:
        require_venv()
        config_js = REPO_ROOT / "magicmirror" / "config" / "config.js"
        if not config_js.is_file():
            pytest.skip(
                "magicmirror/config/config.js missing; run "
                "setup_workspace with MAGICMIRROR_ENABLED=true first."
            )
        result = run_until_markers(
            BASELINE_MARKERS,
            env=smoke_env({"MAGICMIRROR_ENABLED": "true"}),
        )
        _assert_no_traceback(result.stdout)

    def test_magicmirror_autostart_spawns_child(self) -> None:
        require_venv()
        config_js = REPO_ROOT / "magicmirror" / "config" / "config.js"
        if not config_js.is_file():
            pytest.skip("magicmirror config missing; prerequisite not met.")
        result = run_until_markers(
            BASELINE_MARKERS + ("MagicMirror child spawned",),
            env=smoke_env({"MAGICMIRROR_AUTOSTART_ENABLED": "true"}),
        )
        assert "MagicMirror child spawned" in result.stdout

    def test_calendar_flag_on_registers_hook(self) -> None:
        require_venv()
        result = run_until_markers(
            BASELINE_MARKERS,
            env=smoke_env({"GOOGLE_CALENDAR_ENABLED": "true"}),
        )
        assert re.search(r"Custom gateway ready: [78] hooks", result.stdout), (
            "GOOGLE_CALENDAR_ENABLED=true must add CalendarContextHook; "
            "hook count should be 7 (baseline+calendar) or 8 (+disco)."
        )

    def test_taskwarrior_flag_on_selects_backend(self) -> None:
        require_venv()
        if shutil.which("task") is None:
            pytest.skip("Taskwarrior 'task' binary not on PATH.")
        result = run_until_markers(
            BASELINE_MARKERS,
            env=smoke_env({"TASKWARRIOR_ENABLED": "true"}),
        )
        _assert_no_traceback(result.stdout)

    def test_pulse_flag_on_starts_engine(self) -> None:
        require_venv()
        result = run_until_markers(
            BASELINE_MARKERS + ("Pulse engine started",),
            env=smoke_env({"PULSE_ENGINE_ENABLED": "true"}),
        )
        _assert_no_traceback(result.stdout)

    def test_dream_flag_on_instantiates_engine(self) -> None:
        require_venv()
        result = run_until_markers(
            BASELINE_MARKERS,
            env=smoke_env({
                "PULSE_ENGINE_ENABLED": "true",
                "DREAM_STATE_ENABLED": "true",
            }),
        )
        _assert_no_traceback(result.stdout)

    def test_syncall_flag_on_spawns_daemon(self) -> None:
        require_venv()
        result = run_until_markers(
            BASELINE_MARKERS + ("spawning syncall daemon",),
            env=smoke_env({"SYNCALL_ENABLED": "true"}),
        )
        assert "spawning syncall daemon" in result.stdout


class TestLaunchAgentRollback:
    """Install -> verify -> uninstall -> verify absent. AC #13 of sub-05."""

    def _requires_launchctl(self) -> None:
        if shutil.which("bash") is None:
            pytest.skip("bash not on PATH")
        if shutil.which("launchctl") is None:
            pytest.skip("launchctl not on PATH")

    def test_install_then_uninstall_leaves_no_residue(self) -> None:
        self._requires_launchctl()
        if PLIST_PATH.exists():
            pytest.skip(
                f"{PLIST_PATH} already present — refusing to clobber "
                "the user's real LaunchAgent."
            )
        try:
            install = subprocess.run(
                ["bash", str(INSTALL_LAUNCHAGENT)],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                timeout=60,
            )
            assert install.returncode == 0, (
                f"install_launchagent.sh exited {install.returncode}: "
                f"{install.stderr}"
            )
            assert PLIST_PATH.is_file()
            listed = subprocess.run(
                ["launchctl", "list"], capture_output=True, text=True,
            )
            assert "com.adhdassistant.bot" in listed.stdout
        finally:
            subprocess.run(
                ["bash", str(UNINSTALL_LAUNCHAGENT)],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                timeout=30,
            )
        assert not PLIST_PATH.exists(), (
            "uninstall_launchagent.sh left plist residue at "
            f"{PLIST_PATH} — AC #13 violation."
        )
        residual = subprocess.run(
            ["launchctl", "list"], capture_output=True, text=True,
        )
        assert "com.adhdassistant.bot" not in residual.stdout
