"""Static structural tests for the LaunchAgent install/uninstall/status scripts.

Never invokes `launchctl` — registering a live service against the test
runner's login would be an observable side effect (AC #14). Only:
  * parses each script with `bash -n`
  * greps for required phrases the acceptance criteria list
  * confirms line-count caps.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
INSTALL_SCRIPT = SCRIPTS_DIR / "install_launchagent.sh"
UNINSTALL_SCRIPT = SCRIPTS_DIR / "uninstall_launchagent.sh"
STATUS_SCRIPT = SCRIPTS_DIR / "launchagent_status.sh"

ALL_SCRIPTS = (INSTALL_SCRIPT, UNINSTALL_SCRIPT, STATUS_SCRIPT)


def _read(script_path: Path) -> str:
    return script_path.read_text(encoding="utf-8")


def _bash_parse(script_path: Path) -> None:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash not on PATH; skip parse-check")
    result = subprocess.run(
        [bash, "-n", str(script_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, (
        f"bash -n on {script_path.name} exited {result.returncode}. "
        f"stderr: {result.stderr}"
    )


class TestFilesExist:
    def test_install_exists(self) -> None:
        assert INSTALL_SCRIPT.is_file()

    def test_uninstall_exists(self) -> None:
        assert UNINSTALL_SCRIPT.is_file()

    def test_status_exists(self) -> None:
        assert STATUS_SCRIPT.is_file()


class TestLineCountCaps:
    def test_install_under_cap(self) -> None:
        lines = len(_read(INSTALL_SCRIPT).splitlines())
        assert lines <= 200, f"install_launchagent.sh has {lines} lines (cap 200)"

    def test_uninstall_under_cap(self) -> None:
        lines = len(_read(UNINSTALL_SCRIPT).splitlines())
        assert lines <= 80, f"uninstall_launchagent.sh has {lines} lines (cap 80)"

    def test_status_under_cap(self) -> None:
        lines = len(_read(STATUS_SCRIPT).splitlines())
        assert lines <= 80, f"launchagent_status.sh has {lines} lines (cap 80)"


class TestBashSyntax:
    def test_install_parses(self) -> None:
        _bash_parse(INSTALL_SCRIPT)

    def test_uninstall_parses(self) -> None:
        _bash_parse(UNINSTALL_SCRIPT)

    def test_status_parses(self) -> None:
        _bash_parse(STATUS_SCRIPT)


class TestShebangAndStrictMode:
    def test_shebangs(self) -> None:
        for script in ALL_SCRIPTS:
            first_line = _read(script).splitlines()[0]
            assert first_line == "#!/usr/bin/env bash", (
                f"{script.name} shebang is {first_line!r}"
            )

    def test_strict_mode_within_first_ten_lines(self) -> None:
        for script in ALL_SCRIPTS:
            head = _read(script).splitlines()[:10]
            assert any("set -euo pipefail" in line for line in head), (
                f"{script.name} missing `set -euo pipefail` in first 10 lines"
            )


class TestNoSudo:
    def test_zero_sudo_across_scripts(self) -> None:
        for script in ALL_SCRIPTS:
            text = _read(script)
            assert "sudo" not in text, f"{script.name} contains sudo (AC #8)"


class TestInstallScriptBody:
    def test_unload_before_load_idempotent(self) -> None:
        text = _read(INSTALL_SCRIPT)
        unload_pos = text.find("launchctl unload")
        load_pos = text.find("launchctl load")
        assert unload_pos != -1, "install must call launchctl unload"
        assert load_pos != -1, "install must call launchctl load"
        assert unload_pos < load_pos, (
            "AC #6: idempotent install requires unload before load"
        )

    def test_unload_tolerates_missing_plist(self) -> None:
        text = _read(INSTALL_SCRIPT)
        assert "launchctl unload" in text
        assert "2>/dev/null" in text
        assert "|| true" in text

    def test_launchctl_load_uses_dash_w(self) -> None:
        assert "launchctl load -w" in _read(INSTALL_SCRIPT)

    def test_verifies_with_launchctl_list(self) -> None:
        text = _read(INSTALL_SCRIPT)
        assert re.search(r"launchctl list.*com\.adhdassistant\.bot", text)

    def test_mkdir_log_dir(self) -> None:
        assert "mkdir -p" in _read(INSTALL_SCRIPT)

    def test_placeholder_substitution_present(self) -> None:
        text = _read(INSTALL_SCRIPT)
        assert "sed" in text
        assert "${REPO_ROOT}" in text or "\\${REPO_ROOT}" in text

    def test_tilde_expansion_idiom(self) -> None:
        text = _read(INSTALL_SCRIPT)
        assert "#\\~/$HOME" in text or "#~/$HOME" in text, (
            "install must expand tildes in ADHD_LOG_DIR before mkdir/sed; "
            "launchd does NOT expand ~ in plist paths."
        )

    def test_reads_env_file(self) -> None:
        text = _read(INSTALL_SCRIPT)
        assert ".env" in text

    def test_falls_back_when_env_missing(self) -> None:
        text = _read(INSTALL_SCRIPT)
        assert "$REPO_ROOT/logs" in text or "${REPO_ROOT}/logs" in text

    def test_completion_banner(self) -> None:
        text = _read(INSTALL_SCRIPT)
        assert "uninstall_launchagent.sh" in text
        assert "bot.err.log" in text

    def test_target_plist_path(self) -> None:
        text = _read(INSTALL_SCRIPT)
        assert "~/Library/LaunchAgents/com.adhdassistant.bot.plist" in text or (
            "Library/LaunchAgents/com.adhdassistant.bot.plist" in text
        )

    def test_trap_on_err(self) -> None:
        assert "trap" in _read(INSTALL_SCRIPT)


class TestUninstallScriptBody:
    def test_unload_tolerates_missing(self) -> None:
        text = _read(UNINSTALL_SCRIPT)
        assert "launchctl unload" in text
        assert "|| true" in text

    def test_rm_f_not_plain_rm(self) -> None:
        text = _read(UNINSTALL_SCRIPT)
        assert "rm -f" in text, "AC #7: use rm -f so missing plist is tolerated"

    def test_mentions_data_dir(self) -> None:
        text = _read(UNINSTALL_SCRIPT)
        assert "adhd-assistant" in text


class TestStatusScriptBody:
    def test_queries_launchctl(self) -> None:
        text = _read(STATUS_SCRIPT)
        assert "launchctl list" in text
        assert "com.adhdassistant.bot" in text

    def test_tails_logs(self) -> None:
        text = _read(STATUS_SCRIPT)
        assert "tail" in text
        assert "bot.err.log" in text
        assert "bot.out.log" in text


class TestFeatureFlagWhitelist:
    """The install script whitelists known feature-flag keys from .env
    and bakes them into the plist's EnvironmentVariables dict (research
    plan §4.11 approach 1). This test pins the whitelist so `.env.example`
    growing a new flag doesn't silently degrade the LaunchAgent."""

    WHITELIST_KEYS = (
        "PULSE_ENGINE_ENABLED",
        "DREAM_STATE_ENABLED",
        "VOICE_AUTO_ENABLED",
        "VOICE_DISCO_ENABLED",
        "GOOGLE_CALENDAR_ENABLED",
        "MAGICMIRROR_ENABLED",
        "MAGICMIRROR_AUTOSTART_ENABLED",
        "TASKWARRIOR_ENABLED",
        "SYNCALL_ENABLED",
        "ADHD_DATA_DIR",
        "DASHBOARD_DATA_DIR",
        "TASKWARRIOR_DATA_DIR",
        "DREAM_STATE_CRON",
    )

    def test_every_whitelist_key_named(self) -> None:
        text = _read(INSTALL_SCRIPT)
        for key in self.WHITELIST_KEYS:
            assert key in text, (
                f"install_launchagent.sh whitelist missing {key!r}"
            )

    def test_no_secret_keys_leaked(self) -> None:
        text = _read(INSTALL_SCRIPT)
        for secret in (
            "OPENROUTER_API_KEY",
            "TELEGRAM_BOT_TOKEN",
            "TELEGRAM_USER_ID",
        ):
            assert secret not in text, (
                f"install script must not read/inject {secret!r} — "
                f"secrets live in ~/.nanobot/config.json, not the plist."
            )


class TestNoLiveLaunchctl:
    """AC #14: tests must never call launchctl via subprocess."""

    def test_this_file_has_no_launchctl_subprocess(self) -> None:
        source = Path(__file__).read_text(encoding="utf-8")
        assert not re.search(r"subprocess\.[A-Za-z_]+\([^)]*launchctl", source)
