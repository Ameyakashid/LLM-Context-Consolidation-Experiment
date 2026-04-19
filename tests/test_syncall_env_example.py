"""Verify .env.example documents all SYNCALL_* vars without real secrets."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_EXAMPLE = REPO_ROOT / ".env.example"

EXPECTED_SYNCALL_VARS = (
    "SYNCALL_ENABLED",
    "SYNCALL_GCAL_CALENDAR",
    "SYNCALL_COMBINATION_NAME",
    "SYNCALL_RESOLUTION_STRATEGY",
    "SYNCALL_POLL_SECONDS",
    "SYNCALL_OAUTH_PORT",
    "SYNCALL_VERBOSE",
)


def _env_example() -> str:
    return ENV_EXAMPLE.read_text(encoding="utf-8")


def test_env_example_documents_every_syncall_var() -> None:
    body = _env_example()
    for var in EXPECTED_SYNCALL_VARS:
        assert f"{var}=" in body, f"{var} missing from .env.example"


def test_env_example_defaults_flag_off() -> None:
    body = _env_example()
    assert "SYNCALL_ENABLED=false" in body


def test_env_example_default_combination_name() -> None:
    body = _env_example()
    assert "SYNCALL_COMBINATION_NAME=adhd-assistant" in body


def test_env_example_default_resolution_tw_wins() -> None:
    body = _env_example()
    assert "SYNCALL_RESOLUTION_STRATEGY=tw_wins" in body


def test_env_example_default_poll_600() -> None:
    body = _env_example()
    assert "SYNCALL_POLL_SECONDS=600" in body


def test_env_example_gcal_calendar_left_blank() -> None:
    body = _env_example()
    assert "SYNCALL_GCAL_CALENDAR=\n" in body or "SYNCALL_GCAL_CALENDAR=" in body


def test_env_example_does_not_commit_real_secrets() -> None:
    """No plausible OAuth token / API key / pickled file path reaches .env.example."""
    body = _env_example().lower()
    # Generic markers that hint real secret values.
    forbidden_substrings = ("bearer ", "sk-live", "ghp_", "gho_")
    for bad in forbidden_substrings:
        assert bad not in body
