"""Tests for the Google Calendar MCP setup slice.

Covers the four public surfaces added by task 14/sub-01:
  * ``is_gcal_enabled`` flag parsing
  * ``strip_gcal_mcp_server`` config mutation
  * ``build_google_calendar_mcp`` short-circuit + npm freshness check
  * Vendored tree byte-identity with ``references/google-calendar-mcp``
"""

import hashlib
import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from gcal_setup import (
    build_google_calendar_mcp,
    is_gcal_enabled,
    strip_gcal_mcp_server,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestIsGcalEnabled:
    def test_true_when_env_true(self) -> None:
        assert is_gcal_enabled({"GOOGLE_CALENDAR_ENABLED": "true"})

    def test_false_when_env_false(self) -> None:
        assert not is_gcal_enabled({"GOOGLE_CALENDAR_ENABLED": "false"})

    def test_false_when_missing(self) -> None:
        assert not is_gcal_enabled({})

    def test_case_insensitive_true(self) -> None:
        assert is_gcal_enabled({"GOOGLE_CALENDAR_ENABLED": "TRUE"})
        assert is_gcal_enabled({"GOOGLE_CALENDAR_ENABLED": "True"})

    def test_whitespace_tolerated(self) -> None:
        assert is_gcal_enabled({"GOOGLE_CALENDAR_ENABLED": "  true  "})

    def test_non_truthy_values_false(self) -> None:
        assert not is_gcal_enabled({"GOOGLE_CALENDAR_ENABLED": "1"})
        assert not is_gcal_enabled({"GOOGLE_CALENDAR_ENABLED": "yes"})
        assert not is_gcal_enabled({"GOOGLE_CALENDAR_ENABLED": ""})


class TestStripGcalMcpServer:
    def test_removes_google_calendar_entry(self) -> None:
        config: dict[str, object] = {
            "tools": {
                "web": {"enable": True},
                "mcpServers": {
                    "google-calendar": {"command": "node"},
                },
            },
        }
        result = strip_gcal_mcp_server(config)
        tools = result["tools"]
        assert isinstance(tools, dict)
        assert "mcpServers" not in tools
        assert tools["web"] == {"enable": True}

    def test_preserves_other_mcp_servers(self) -> None:
        config: dict[str, object] = {
            "tools": {
                "mcpServers": {
                    "google-calendar": {"command": "node"},
                    "other-server": {"command": "python"},
                },
            },
        }
        result = strip_gcal_mcp_server(config)
        tools = result["tools"]
        assert isinstance(tools, dict)
        mcp = tools["mcpServers"]
        assert isinstance(mcp, dict)
        assert "google-calendar" not in mcp
        assert mcp["other-server"] == {"command": "python"}

    def test_does_not_mutate_input(self) -> None:
        config: dict[str, object] = {
            "tools": {
                "mcpServers": {
                    "google-calendar": {"command": "node"},
                },
            },
        }
        strip_gcal_mcp_server(config)
        tools = config["tools"]
        assert isinstance(tools, dict)
        assert "mcpServers" in tools


class TestBuildGoogleCalendarMcpFlagOff:
    def test_short_circuits_without_npm_when_disabled(
        self, tmp_path: Path
    ) -> None:
        # Even if the vendored dir is missing, a disabled flag must no-op.
        missing_dir = tmp_path / "does-not-exist"
        data_dir = tmp_path / "data"
        with patch("gcal_setup.shutil.which") as which_mock, patch(
            "gcal_setup.subprocess.run"
        ) as run_mock:
            build_google_calendar_mcp(missing_dir, False, data_dir)
            which_mock.assert_not_called()
            run_mock.assert_not_called()
        assert not data_dir.exists()


class TestBuildGoogleCalendarMcpNpmMissing:
    def test_raises_actionable_error_when_npm_absent(
        self, tmp_path: Path
    ) -> None:
        mcp_dir = tmp_path / "mcp" / "google-calendar"
        mcp_dir.mkdir(parents=True)
        (mcp_dir / "package.json").write_text("{}", encoding="utf-8")
        data_dir = tmp_path / "data"
        with patch("gcal_setup.shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="npm not found on PATH"):
                build_google_calendar_mcp(mcp_dir, True, data_dir)


class TestBuildGoogleCalendarMcpFreshness:
    def _make_vendor(self, tmp_path: Path) -> tuple[Path, Path]:
        mcp_dir = tmp_path / "mcp" / "google-calendar"
        (mcp_dir / "build").mkdir(parents=True)
        (mcp_dir / "package.json").write_text(
            '{"name": "test"}', encoding="utf-8"
        )
        data_dir = tmp_path / "data"
        return mcp_dir, data_dir

    def test_skips_npm_when_build_is_fresh(self, tmp_path: Path) -> None:
        mcp_dir, data_dir = self._make_vendor(tmp_path)
        build_entry = mcp_dir / "build" / "index.js"
        build_entry.write_text("// built", encoding="utf-8")
        package_json = mcp_dir / "package.json"
        future_mtime = package_json.stat().st_mtime + 10
        os.utime(build_entry, (future_mtime, future_mtime))
        with patch(
            "gcal_setup.shutil.which", return_value="/usr/bin/npm"
        ), patch("gcal_setup.subprocess.run") as run_mock:
            build_google_calendar_mcp(mcp_dir, True, data_dir)
            run_mock.assert_not_called()
        assert data_dir.exists()

    def test_runs_npm_install_and_build_when_stale(
        self, tmp_path: Path
    ) -> None:
        mcp_dir, data_dir = self._make_vendor(tmp_path)
        mock_result = MagicMock(stdout="", stderr="")
        with patch(
            "gcal_setup.shutil.which", return_value="/usr/bin/npm"
        ), patch(
            "gcal_setup.subprocess.run", return_value=mock_result
        ) as run_mock:
            build_google_calendar_mcp(mcp_dir, True, data_dir)
        assert run_mock.call_count == 2
        first_call = run_mock.call_args_list[0]
        second_call = run_mock.call_args_list[1]
        assert first_call.args[0] == ["/usr/bin/npm", "install"]
        assert second_call.args[0] == ["/usr/bin/npm", "run", "build"]
        assert first_call.kwargs["cwd"] == mcp_dir
        assert first_call.kwargs["check"] is True
        assert first_call.kwargs["text"] is True
        assert data_dir.exists()

    def test_runs_npm_when_package_json_newer_than_build(
        self, tmp_path: Path
    ) -> None:
        mcp_dir, data_dir = self._make_vendor(tmp_path)
        build_entry = mcp_dir / "build" / "index.js"
        build_entry.write_text("// old", encoding="utf-8")
        package_json = mcp_dir / "package.json"
        build_mtime = build_entry.stat().st_mtime
        os.utime(package_json, (build_mtime + 100, build_mtime + 100))
        mock_result = MagicMock(stdout="", stderr="")
        with patch(
            "gcal_setup.shutil.which", return_value="/usr/bin/npm"
        ), patch(
            "gcal_setup.subprocess.run", return_value=mock_result
        ) as run_mock:
            build_google_calendar_mcp(mcp_dir, True, data_dir)
        assert run_mock.call_count == 2


class TestBuildGoogleCalendarMcpNpmFailure:
    def test_wraps_called_process_error(self, tmp_path: Path) -> None:
        mcp_dir = tmp_path / "mcp" / "google-calendar"
        mcp_dir.mkdir(parents=True)
        (mcp_dir / "package.json").write_text("{}", encoding="utf-8")
        data_dir = tmp_path / "data"
        exc = subprocess.CalledProcessError(
            returncode=1, cmd=["npm", "install"], stderr="boom"
        )
        with patch(
            "gcal_setup.shutil.which", return_value="/usr/bin/npm"
        ), patch("gcal_setup.subprocess.run", side_effect=exc):
            with pytest.raises(RuntimeError, match="npm install failed"):
                build_google_calendar_mcp(mcp_dir, True, data_dir)

    def test_missing_vendor_directory_raises(self, tmp_path: Path) -> None:
        missing = tmp_path / "nowhere"
        data_dir = tmp_path / "data"
        with pytest.raises(FileNotFoundError, match="Vendored MCP directory"):
            build_google_calendar_mcp(missing, True, data_dir)


class TestVendorByteIdentity:
    """Package.json must match the references/ upstream drop byte-for-byte."""

    def test_package_json_matches_upstream(self) -> None:
        vendored = REPO_ROOT / "mcp" / "google-calendar" / "package.json"
        upstream = (
            REPO_ROOT / "references" / "google-calendar-mcp" / "package.json"
        )
        assert vendored.exists()
        assert upstream.exists()
        vendored_hash = hashlib.sha256(vendored.read_bytes()).hexdigest()
        upstream_hash = hashlib.sha256(upstream.read_bytes()).hexdigest()
        assert vendored_hash == upstream_hash

    def test_vendor_source_file_records_pin(self) -> None:
        pin = REPO_ROOT / "mcp" / "google-calendar" / ".vendor-source.md"
        assert pin.exists()
        text = pin.read_text(encoding="utf-8")
        assert "0f2c9c5d7d96b63e424f035cca3269f857f3b0e1" in text
        assert "2.6.1" in text
        assert "github.com/nspady/google-calendar-mcp" in text

    def test_stripped_metadata_absent(self) -> None:
        vendored = REPO_ROOT / "mcp" / "google-calendar"
        for stripped in (".git", ".github", ".claude"):
            assert not (vendored / stripped).exists(), (
                f"Expected {stripped} to be stripped from vendored drop"
            )


class TestGitignoreProtections:
    def _gitignore_lines(self) -> list[str]:
        content = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        return [line.strip() for line in content.splitlines()]

    def test_node_modules_ignored(self) -> None:
        assert "mcp/google-calendar/node_modules/" in self._gitignore_lines()

    def test_build_ignored(self) -> None:
        assert "mcp/google-calendar/build/" in self._gitignore_lines()

    def test_real_oauth_keys_ignored(self) -> None:
        assert "gcp-oauth.keys.json" in self._gitignore_lines()
        assert "gcp-oauth.keys.*.json" in self._gitignore_lines()

    def test_example_oauth_keys_negated(self) -> None:
        assert "!gcp-oauth.keys.example.json" in self._gitignore_lines()


class TestEnvExampleEntries:
    def _env_example_text(self) -> str:
        return (REPO_ROOT / ".env.example").read_text(encoding="utf-8")

    def test_feature_flag_documented(self) -> None:
        text = self._env_example_text()
        assert "GOOGLE_CALENDAR_ENABLED=" in text

    def test_credentials_path_documented(self) -> None:
        assert "GOOGLE_OAUTH_CREDENTIALS=" in self._env_example_text()

    def test_token_path_documented(self) -> None:
        assert "GOOGLE_CALENDAR_MCP_TOKEN_PATH=" in self._env_example_text()

    def test_repo_root_documented(self) -> None:
        assert "ADHD_REPO_ROOT=" in self._env_example_text()


def test_setup_workspace_re_exports_gcal_helpers() -> None:
    """setup_workspace imports from gcal_setup — loose coupling check."""
    import setup_workspace as sw

    assert sw.build_google_calendar_mcp is build_google_calendar_mcp
    assert sw.is_gcal_enabled is is_gcal_enabled
    assert sw.strip_gcal_mcp_server is strip_gcal_mcp_server
