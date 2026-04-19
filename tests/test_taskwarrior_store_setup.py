"""Tests for the Taskwarrior setup flag-gating in ``taskwarrior_setup``
and ``setup_workspace``. No Taskwarrior CLI needed."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from taskwarrior_setup import (
    build_taskwarrior,
    is_taskwarrior_enabled,
    resolve_taskwarrior_data_dir,
    taskwarrior_data_dir_is_empty,
    warn_if_migration_needed,
)


class TestIsTaskwarriorEnabled:
    def test_true_lowercase(self) -> None:
        assert is_taskwarrior_enabled({"TASKWARRIOR_ENABLED": "true"}) is True

    def test_true_uppercase(self) -> None:
        assert is_taskwarrior_enabled({"TASKWARRIOR_ENABLED": "TRUE"}) is True

    def test_true_mixed_case(self) -> None:
        assert is_taskwarrior_enabled({"TASKWARRIOR_ENABLED": "True"}) is True

    def test_false_default(self) -> None:
        assert is_taskwarrior_enabled({}) is False

    def test_false_explicit(self) -> None:
        assert is_taskwarrior_enabled({"TASKWARRIOR_ENABLED": "false"}) is False

    def test_empty_treated_as_false(self) -> None:
        assert is_taskwarrior_enabled({"TASKWARRIOR_ENABLED": ""}) is False

    def test_whitespace_tolerated(self) -> None:
        assert is_taskwarrior_enabled({"TASKWARRIOR_ENABLED": "  true  "}) is True


class TestResolveDataDir:
    def test_uses_default_when_unset(self, tmp_path: Path) -> None:
        default = tmp_path / "workspace" / "data" / "taskwarrior"
        assert resolve_taskwarrior_data_dir({}, default) == default

    def test_uses_default_when_blank(self, tmp_path: Path) -> None:
        default = tmp_path / "default"
        result = resolve_taskwarrior_data_dir(
            {"TASKWARRIOR_DATA_DIR": "   "}, default
        )
        assert result == default

    def test_env_override_wins(self, tmp_path: Path) -> None:
        override = tmp_path / "custom"
        result = resolve_taskwarrior_data_dir(
            {"TASKWARRIOR_DATA_DIR": str(override)}, tmp_path / "default"
        )
        assert result == override

    def test_tilde_expanded(self, tmp_path: Path) -> None:
        result = resolve_taskwarrior_data_dir(
            {"TASKWARRIOR_DATA_DIR": "~/tw-data"}, tmp_path / "default"
        )
        assert not str(result).startswith("~")


class TestBuildTaskwarrior:
    def test_disabled_skips_dir_creation(self, tmp_path: Path) -> None:
        target = tmp_path / "tw"
        build_taskwarrior(target, enabled=False, platform="linux")
        assert not target.exists()

    def test_enabled_creates_dir(self, tmp_path: Path) -> None:
        target = tmp_path / "tw"
        build_taskwarrior(target, enabled=True, platform="linux")
        assert target.is_dir()

    def test_enabled_is_idempotent(self, tmp_path: Path) -> None:
        target = tmp_path / "tw"
        build_taskwarrior(target, enabled=True, platform="linux")
        build_taskwarrior(target, enabled=True, platform="linux")
        assert target.is_dir()

    def test_warns_when_binary_missing(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setattr("taskwarrior_setup.shutil.which", lambda _: None)
        target = tmp_path / "tw"
        with caplog.at_level(logging.WARNING, logger="taskwarrior_setup"):
            build_taskwarrior(target, enabled=True, platform="windows")
        assert "choco install task" in caplog.text

    def test_darwin_hint(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setattr("taskwarrior_setup.shutil.which", lambda _: None)
        with caplog.at_level(logging.WARNING, logger="taskwarrior_setup"):
            build_taskwarrior(tmp_path / "tw", enabled=True, platform="darwin")
        assert "brew install task" in caplog.text

    def test_unknown_platform_falls_back_to_linux_hint(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setattr("taskwarrior_setup.shutil.which", lambda _: None)
        with caplog.at_level(logging.WARNING, logger="taskwarrior_setup"):
            build_taskwarrior(tmp_path / "tw", enabled=True, platform="plan9")
        assert "apt install taskwarrior" in caplog.text

    def test_no_warning_when_binary_present(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setattr(
            "taskwarrior_setup.shutil.which",
            lambda _: "/usr/bin/task",
        )
        with caplog.at_level(logging.WARNING, logger="taskwarrior_setup"):
            build_taskwarrior(tmp_path / "tw", enabled=True, platform="linux")
        assert "not on PATH" not in caplog.text


class TestTaskwarriorDataDirIsEmpty:
    def test_missing_dir_is_empty(self, tmp_path: Path) -> None:
        assert taskwarrior_data_dir_is_empty(tmp_path / "nothing") is True

    def test_empty_dir_is_empty(self, tmp_path: Path) -> None:
        target = tmp_path / "tw"
        target.mkdir()
        assert taskwarrior_data_dir_is_empty(target) is True

    def test_pending_with_content_not_empty(self, tmp_path: Path) -> None:
        target = tmp_path / "tw"
        target.mkdir()
        (target / "pending.data").write_text("[task]\n", encoding="utf-8")
        assert taskwarrior_data_dir_is_empty(target) is False

    def test_zero_byte_pending_still_empty(self, tmp_path: Path) -> None:
        target = tmp_path / "tw"
        target.mkdir()
        (target / "pending.data").write_text("", encoding="utf-8")
        assert taskwarrior_data_dir_is_empty(target) is True


class TestWarnIfMigrationNeeded:
    def test_disabled_emits_no_warning(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        json_path = tmp_path / "tasks.json"
        json_path.write_text("{}", encoding="utf-8")
        result = warn_if_migration_needed(
            enabled=False, json_path=json_path, tw_data_dir=tmp_path / "tw",
        )
        assert result is False

    def test_missing_json_emits_no_warning(
        self, tmp_path: Path,
    ) -> None:
        result = warn_if_migration_needed(
            enabled=True,
            json_path=tmp_path / "nothing.json",
            tw_data_dir=tmp_path / "tw",
        )
        assert result is False

    def test_non_empty_tw_data_dir_emits_no_warning(
        self, tmp_path: Path,
    ) -> None:
        json_path = tmp_path / "tasks.json"
        json_path.write_text("{}", encoding="utf-8")
        tw_dir = tmp_path / "tw"
        tw_dir.mkdir()
        (tw_dir / "pending.data").write_text("[x]\n", encoding="utf-8")

        result = warn_if_migration_needed(
            enabled=True, json_path=json_path, tw_data_dir=tw_dir,
        )
        assert result is False

    def test_all_conditions_met_emits_warning(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        json_path = tmp_path / "tasks.json"
        json_path.write_text("{}", encoding="utf-8")
        with caplog.at_level(logging.WARNING, logger="taskwarrior_setup"):
            result = warn_if_migration_needed(
                enabled=True,
                json_path=json_path,
                tw_data_dir=tmp_path / "empty_tw",
            )
        assert result is True
        assert "migrate_json_to_taskwarrior" in caplog.text
