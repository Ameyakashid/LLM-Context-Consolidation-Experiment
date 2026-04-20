"""Structural tests for deploy/com.adhdassistant.bot.plist.template.

The template ships unrendered — `${REPO_ROOT}`, `${HOME}`, `${ADHD_LOG_DIR}`,
`${NANOBOT_TIMEZONE}`, and `${EXTRA_ENV_ENTRIES}` are substituted by
scripts/install_launchagent.sh at install time. These tests verify the
rendered result parses as a well-formed plist and carries the keys the
acceptance criteria pin.

No live `launchctl` invocation happens here — registering a live service
against the test runner's login account would be an observable side
effect. AC #14.
"""

from __future__ import annotations

import plistlib
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import cast

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = REPO_ROOT / "deploy" / "com.adhdassistant.bot.plist.template"

DUMMY_REPO_ROOT = "/tmp/adhd-repo"
DUMMY_HOME = "/Users/testuser"
DUMMY_LOG_DIR = "/Users/testuser/Library/Logs/adhd-assistant"
DUMMY_TIMEZONE = "America/New_York"
DUMMY_EXTRA_ENTRIES = (
    "    <key>PULSE_ENGINE_ENABLED</key><string>false</string>\n"
    "    <key>MAGICMIRROR_ENABLED</key><string>true</string>"
)


def _read_template() -> str:
    return TEMPLATE_PATH.read_text(encoding="utf-8")


def _render(extra_entries: str = DUMMY_EXTRA_ENTRIES) -> str:
    return (
        _read_template()
        .replace("${REPO_ROOT}", DUMMY_REPO_ROOT)
        .replace("${HOME}", DUMMY_HOME)
        .replace("${ADHD_LOG_DIR}", DUMMY_LOG_DIR)
        .replace("${NANOBOT_TIMEZONE}", DUMMY_TIMEZONE)
        .replace("${EXTRA_ENV_ENTRIES}", extra_entries)
    )


def _parse() -> dict[str, object]:
    return cast(dict[str, object], plistlib.loads(_render().encode("utf-8")))


def _parse_list(key: str) -> list[object]:
    value = _parse()[key]
    assert isinstance(value, list)
    return cast(list[object], value)


def _parse_dict(key: str) -> dict[str, object]:
    value = _parse()[key]
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


def _parse_str(key: str) -> str:
    value = _parse()[key]
    assert isinstance(value, str)
    return value


def _parse_int(key: str) -> int:
    value = _parse()[key]
    assert isinstance(value, int) and not isinstance(value, bool)
    return value


class TestTemplateFile:
    def test_template_exists(self) -> None:
        assert TEMPLATE_PATH.is_file(), (
            f"Plist template missing at {TEMPLATE_PATH}."
        )

    def test_under_line_cap(self) -> None:
        line_count = len(_read_template().splitlines())
        assert line_count <= 120, (
            f"Plist template has {line_count} lines; AC #16 caps at 120."
        )

    def test_header_lists_every_placeholder(self) -> None:
        header = _read_template().split("<plist", 1)[0]
        for placeholder in (
            "${REPO_ROOT}", "${HOME}", "${ADHD_LOG_DIR}",
            "${NANOBOT_TIMEZONE}", "${EXTRA_ENV_ENTRIES}",
        ):
            assert placeholder in header, (
                f"Header XML comment must document {placeholder}."
            )


class TestXmlWellFormed:
    def test_xml_parses_after_substitution(self) -> None:
        ET.fromstring(_render())

    def test_xml_parses_with_empty_extra_entries(self) -> None:
        ET.fromstring(_render(extra_entries=""))

    def test_plistlib_parses_after_substitution(self) -> None:
        parsed = _parse()
        assert isinstance(parsed, dict)


class TestRequiredKeys:
    REQUIRED = (
        "Label", "ProgramArguments", "WorkingDirectory",
        "EnvironmentVariables", "StandardOutPath", "StandardErrorPath",
        "RunAtLoad", "KeepAlive", "ThrottleInterval", "ProcessType",
    )

    def test_every_required_key_present(self) -> None:
        parsed = _parse()
        for key in self.REQUIRED:
            assert key in parsed, f"Missing required plist key: {key!r}"


class TestLabel:
    def test_label_value(self) -> None:
        assert _parse()["Label"] == "com.adhdassistant.bot"


class TestProgramArguments:
    def test_two_element_list(self) -> None:
        args = _parse_list("ProgramArguments")
        assert len(args) == 2

    def test_python_interpreter_absolute(self) -> None:
        first = _parse_list("ProgramArguments")[0]
        assert isinstance(first, str)
        assert first.startswith("/")
        assert first.endswith(".venv/bin/python")

    def test_entrypoint_absolute(self) -> None:
        second = _parse_list("ProgramArguments")[1]
        assert isinstance(second, str)
        assert second.startswith("/")
        assert second.endswith("start.py")


class TestWorkingDirectory:
    def test_is_absolute(self) -> None:
        cwd = _parse_str("WorkingDirectory")
        assert cwd.startswith("/")


class TestEnvironmentVariables:
    def test_dict_type(self) -> None:
        _parse_dict("EnvironmentVariables")

    def test_core_keys_present(self) -> None:
        env = _parse_dict("EnvironmentVariables")
        for key in ("HOME", "PATH", "LANG", "ADHD_LOG_DIR", "NANOBOT_TIMEZONE"):
            assert key in env, f"EnvironmentVariables missing {key!r}"

    def test_path_includes_homebrew(self) -> None:
        env = _parse_dict("EnvironmentVariables")
        path_value = env["PATH"]
        assert isinstance(path_value, str)
        assert "/opt/homebrew/bin" in path_value

    def test_extra_entries_merged(self) -> None:
        env = _parse_dict("EnvironmentVariables")
        assert env.get("PULSE_ENGINE_ENABLED") == "false"
        assert env.get("MAGICMIRROR_ENABLED") == "true"


class TestLogPaths:
    def test_stdout_under_log_dir(self) -> None:
        assert _parse_str("StandardOutPath") == f"{DUMMY_LOG_DIR}/bot.out.log"

    def test_stderr_under_log_dir(self) -> None:
        assert _parse_str("StandardErrorPath") == f"{DUMMY_LOG_DIR}/bot.err.log"


class TestRunAtLoad:
    def test_true(self) -> None:
        assert _parse()["RunAtLoad"] is True


class TestKeepAlive:
    def test_is_dict_not_bare_bool(self) -> None:
        _parse_dict("KeepAlive")

    def test_successful_exit_false(self) -> None:
        assert _parse_dict("KeepAlive").get("SuccessfulExit") is False


class TestThrottleInterval:
    def test_is_int(self) -> None:
        _parse_int("ThrottleInterval")

    def test_at_least_thirty(self) -> None:
        assert _parse_int("ThrottleInterval") >= 30


class TestProcessType:
    def test_interactive(self) -> None:
        assert _parse_str("ProcessType") == "Interactive"


class TestNoLaunchctlInvocation:
    def test_test_source_has_no_launchctl_subprocess(self) -> None:
        """This test file itself must never shell out to launchctl."""
        source = Path(__file__).read_text(encoding="utf-8")
        assert not re.search(r"subprocess\.[A-Za-z_]+\([^)]*launchctl", source)
