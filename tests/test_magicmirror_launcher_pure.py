"""Pure-function tests for magicmirror_launcher: no Popen stubs needed."""

from __future__ import annotations

from pathlib import Path

import pytest

from magicmirror_launcher import (
    build_magicmirror_command,
    is_magicmirror_autostart_enabled,
    launch_magicmirror,
)


def test_build_magicmirror_command_shape() -> None:
    argv = build_magicmirror_command(Path("/repo"))
    assert argv[:3] == ["npm", "start", "--prefix"]
    assert argv[3] == str(Path("/repo") / "magicmirror")


def test_build_magicmirror_command_is_pure() -> None:
    root = Path("/some/repo")
    first = build_magicmirror_command(root)
    second = build_magicmirror_command(root)
    assert first == second
    assert first is not second


def test_build_magicmirror_command_no_shell_metachars() -> None:
    argv = build_magicmirror_command(Path("/weird path with spaces"))
    joined = " ".join(argv)
    for metachar in ("&&", "||", "|", ";", "$(", "`"):
        assert metachar not in joined


def test_autostart_enabled_true_literal() -> None:
    assert is_magicmirror_autostart_enabled({"MAGICMIRROR_AUTOSTART_ENABLED": "true"}) is True


def test_autostart_enabled_case_insensitive() -> None:
    for value in ("True", "TRUE", "tRuE"):
        assert is_magicmirror_autostart_enabled(
            {"MAGICMIRROR_AUTOSTART_ENABLED": value}
        ) is True


def test_autostart_enabled_whitespace_stripped() -> None:
    assert is_magicmirror_autostart_enabled(
        {"MAGICMIRROR_AUTOSTART_ENABLED": "  true  "}
    ) is True


@pytest.mark.parametrize("value", ["false", "False", "FALSE", "1", "yes", "on", ""])
def test_autostart_disabled_for_non_true_values(value: str) -> None:
    assert is_magicmirror_autostart_enabled(
        {"MAGICMIRROR_AUTOSTART_ENABLED": value}
    ) is False


def test_autostart_disabled_when_missing() -> None:
    assert is_magicmirror_autostart_enabled({}) is False


def test_autostart_is_pure() -> None:
    env = {"MAGICMIRROR_AUTOSTART_ENABLED": "true"}
    assert is_magicmirror_autostart_enabled(env) is True
    assert is_magicmirror_autostart_enabled(env) is True
    assert env == {"MAGICMIRROR_AUTOSTART_ENABLED": "true"}


def test_launch_magicmirror_flag_off_returns_none(tmp_path: Path) -> None:
    result = launch_magicmirror(tmp_path, {})
    assert result is None


def test_launch_magicmirror_flag_off_ignores_missing_config(tmp_path: Path) -> None:
    result = launch_magicmirror(
        tmp_path,
        {"MAGICMIRROR_AUTOSTART_ENABLED": "false"},
    )
    assert result is None


def test_launch_magicmirror_missing_config_raises(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError) as excinfo:
        launch_magicmirror(
            tmp_path,
            {"MAGICMIRROR_AUTOSTART_ENABLED": "true"},
        )
    message = str(excinfo.value)
    assert "config.js" in message
    assert "setup_workspace()" in message


def test_launch_magicmirror_missing_config_references_expected_path(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError) as excinfo:
        launch_magicmirror(
            tmp_path,
            {"MAGICMIRROR_AUTOSTART_ENABLED": "true"},
        )
    expected_path = tmp_path / "magicmirror" / "config" / "config.js"
    assert str(expected_path) in str(excinfo.value)
