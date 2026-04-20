"""Assert the macOS-path block is present in .env.example, commented out,
and that no pre-existing env-var default was moved by sub-02."""

from __future__ import annotations

from pathlib import Path

import pytest

ENV_EXAMPLE = Path(__file__).resolve().parent.parent / ".env.example"


@pytest.fixture(scope="module")
def env_example_text() -> str:
    return ENV_EXAMPLE.read_text(encoding="utf-8")


class TestMacBlockBannerAndMembership:
    def test_mac_banner_present(self, env_example_text: str) -> None:
        assert (
            "# === macOS Conventional Paths (uncomment on Mac) ==="
            in env_example_text
        )

    def test_mac_block_end_marker_present(self, env_example_text: str) -> None:
        assert "# === end macOS block ===" in env_example_text


class TestMacBlockLinesAreCommented:
    @pytest.mark.parametrize(
        "expected_line",
        [
            "# ADHD_DATA_DIR=~/Library/Application Support/adhd-assistant/data",
            "# TASKWARRIOR_DATA_DIR=~/Library/Application Support/adhd-assistant/taskwarrior",
            "# DASHBOARD_DATA_DIR=~/Library/Application Support/adhd-assistant/data",
            "# GOOGLE_OAUTH_CREDENTIALS=~/Library/Application Support/adhd-assistant/oauth/gcp-oauth.keys.json",
            "# GOOGLE_CALENDAR_MCP_TOKEN_PATH=~/Library/Application Support/adhd-assistant/oauth/mcp-token.json",
            "# ADHD_LOG_DIR=~/Library/Logs/adhd-assistant",
        ],
    )
    def test_line_present_and_commented(
        self, env_example_text: str, expected_line: str,
    ) -> None:
        assert expected_line in env_example_text


class TestExistingDefaultsUnchanged:
    @pytest.mark.parametrize(
        "preserved_line",
        [
            "ADHD_DATA_DIR=data",
            "ADHD_STATES_PATH=workspace/states.yaml",
            "DASHBOARD_DATA_DIR=data",
            "TASKWARRIOR_DATA_DIR=",
            "GOOGLE_OAUTH_CREDENTIALS=",
            "GOOGLE_CALENDAR_MCP_TOKEN_PATH=",
        ],
    )
    def test_existing_default_still_present(
        self, env_example_text: str, preserved_line: str,
    ) -> None:
        assert preserved_line in env_example_text
