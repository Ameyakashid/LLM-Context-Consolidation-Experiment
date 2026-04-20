"""Static structural tests for install_mac.sh.

These tests never invoke brew/npm/python3.11 for real. They only:
  * parse the script with `bash -n`
  * grep for the phrases the acceptance criteria list
  * confirm the file stays under the 300-line cap

The live smoke (brew install, npm install, venv creation) belongs to
sub-05, which runs on Mac hardware.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "install_mac.sh"


def _read_script() -> str:
    return SCRIPT_PATH.read_text(encoding="utf-8")


class TestScriptFile:
    def test_script_exists(self) -> None:
        assert SCRIPT_PATH.is_file(), (
            f"install_mac.sh missing at {SCRIPT_PATH}. "
            f"Sub-01 must land it at the repo root."
        )

    def test_under_line_cap(self) -> None:
        line_count = len(_read_script().splitlines())
        assert line_count < 300, (
            f"install_mac.sh has {line_count} lines; "
            f"acceptance #16 caps it at 300."
        )

    def test_bash_syntax_valid(self) -> None:
        bash = shutil.which("bash")
        if bash is None:
            pytest.skip("bash not on PATH; skip parse-check")
        result = subprocess.run(
            [bash, "-n", str(SCRIPT_PATH)],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert result.returncode == 0, (
            f"bash -n exited {result.returncode}. stderr: {result.stderr}"
        )


class TestShebangAndStrictMode:
    def test_shebang_first_line(self) -> None:
        first_line = _read_script().splitlines()[0]
        assert first_line == "#!/usr/bin/env bash", (
            f"Expected `#!/usr/bin/env bash`, got {first_line!r}."
        )

    def test_strict_mode_within_first_ten_lines(self) -> None:
        head = _read_script().splitlines()[:10]
        assert any("set -euo pipefail" in line for line in head), (
            "`set -euo pipefail` must appear within the first 10 lines."
        )


class TestHomebrewPackages:
    def test_idempotent_brew_idiom_present(self) -> None:
        text = _read_script()
        assert "brew list" in text
        assert "|| brew install" in text, (
            "Acceptance #4 wants the `brew list ... || brew install` idiom."
        )

    def test_all_five_packages_listed(self) -> None:
        text = _read_script()
        for pkg in ("python@3.11", "node", "task", "git", "ffmpeg"):
            assert pkg in text, f"brew package {pkg!r} not present in script"

    def test_brew_presence_check(self) -> None:
        text = _read_script()
        assert "command -v brew" in text or "/opt/homebrew/bin/brew" in text, (
            "Script must detect Homebrew before calling `brew install`."
        )


class TestPythonVenvAndDeps:
    def test_venv_creation_command(self) -> None:
        text = _read_script()
        assert "python3.11 -m venv .venv" in text

    def test_venv_creation_is_guarded(self) -> None:
        text = _read_script()
        assert "[[ -d .venv ]]" in text or "[[ -x .venv/bin" in text, (
            "Acceptance #5: venv creation must be guarded on directory "
            "or binary existence."
        )

    def test_pip_installs_runtime_requirements(self) -> None:
        text = _read_script()
        assert "pip install -r requirements.txt" in text

    def test_pip_installs_dev_requirements(self) -> None:
        text = _read_script()
        assert "pip install -r requirements-dev.txt" in text


class TestMagicMirror:
    def test_core_install_uses_ignore_scripts(self) -> None:
        text = _read_script()
        assert "cd magicmirror" in text
        assert "npm install --ignore-scripts" in text

    def test_module_install_loop_or_enumerated(self) -> None:
        text = _read_script()
        assert "magicmirror/modules/MMM-" in text, (
            "Either a glob `magicmirror/modules/MMM-*` loop or three "
            "explicit `cd magicmirror/modules/MMM-...` lines must appear."
        )


class TestMCPServer:
    def test_google_calendar_mcp_cd(self) -> None:
        text = _read_script()
        assert "cd mcp/google-calendar" in text

    def test_mcp_build_steps(self) -> None:
        text = _read_script()
        assert "npm install" in text
        assert "npm run build" in text


class TestAppleSiliconBanner:
    def test_arch_detected_and_arm64_mentioned(self) -> None:
        text = _read_script()
        assert "uname -m" in text
        assert "arm64" in text


class TestNoSudo:
    def test_zero_sudo(self) -> None:
        text = _read_script()
        assert "sudo" not in text, (
            "Acceptance #11: no sudo in install_mac.sh."
        )


class TestErrorHandling:
    def test_trap_declared(self) -> None:
        text = _read_script()
        assert "trap" in text, "Acceptance #12: trap must report failing phase."


class TestCompletionBanner:
    def test_final_banner(self) -> None:
        text = _read_script()
        assert "=== Install complete ===" in text


class TestRepoRootAnchoring:
    def test_script_cds_to_own_dir(self) -> None:
        text = _read_script()
        assert 'cd "$(dirname "$0")"' in text, (
            "Script must anchor itself at the repo root before running."
        )
