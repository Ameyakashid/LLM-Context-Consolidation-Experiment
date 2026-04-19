"""Pure tests for CLI-arg assembly."""

from __future__ import annotations

import pytest

from syncall_args import (
    SYNCALL_RESOLUTION_ALIASES,
    SYNCALL_VALID_RESOLUTION_STRATEGIES,
    SyncallArgsConfig,
    build_syncall_args,
    read_syncall_args_config,
    resolve_resolution_strategy,
    resolve_verbosity_tokens,
)


def _full_env() -> dict[str, str]:
    return {
        "SYNCALL_GCAL_CALENDAR": "ADHD-Assistant",
        "GOOGLE_OAUTH_CREDENTIALS": "/abs/path/oauth.json",
        "SYNCALL_COMBINATION_NAME": "adhd-assistant",
        "SYNCALL_RESOLUTION_STRATEGY": "tw_wins",
        "SYNCALL_OAUTH_PORT": "8080",
        "SYNCALL_VERBOSE": "1",
    }


def test_resolve_resolution_strategy_accepts_upstream_name() -> None:
    for name in SYNCALL_VALID_RESOLUTION_STRATEGIES:
        assert resolve_resolution_strategy(name) == name


def test_resolve_resolution_strategy_translates_friendly_aliases() -> None:
    for alias, canonical in SYNCALL_RESOLUTION_ALIASES.items():
        assert resolve_resolution_strategy(alias) == canonical


def test_resolve_resolution_strategy_defaults_on_empty() -> None:
    assert resolve_resolution_strategy("") == "AlwaysSecondRS"
    assert resolve_resolution_strategy("   ") == "AlwaysSecondRS"


def test_resolve_resolution_strategy_rejects_unknown_value() -> None:
    with pytest.raises(ValueError) as ctx:
        resolve_resolution_strategy("FirstWriteWins")
    message = str(ctx.value)
    assert "FirstWriteWins" in message
    assert "AlwaysSecondRS" in message
    assert "tw_wins" in message


def test_resolve_verbosity_tokens_returns_dash_v_per_level() -> None:
    assert resolve_verbosity_tokens(0) == []
    assert resolve_verbosity_tokens(1) == ["-v"]
    assert resolve_verbosity_tokens(2) == ["-v", "-v"]
    assert resolve_verbosity_tokens(3) == ["-v", "-v", "-v"]


def test_resolve_verbosity_tokens_clamps_high_values() -> None:
    assert resolve_verbosity_tokens(10) == ["-v", "-v", "-v"]


def test_resolve_verbosity_tokens_negative_returns_empty() -> None:
    assert resolve_verbosity_tokens(-1) == []


def test_read_syncall_args_config_parses_all_fields() -> None:
    config = read_syncall_args_config(_full_env())
    assert config.gcal_calendar == "ADHD-Assistant"
    assert config.google_secret_path == "/abs/path/oauth.json"
    assert config.combination_savename == "adhd-assistant"
    assert config.resolution_strategy == "AlwaysSecondRS"
    assert config.oauth_port == 8080
    assert config.verbose == 1
    assert config.tw_filter == ""


def test_read_syncall_args_config_applies_defaults_for_optional_vars() -> None:
    env = {
        "SYNCALL_GCAL_CALENDAR": "Tasks",
        "GOOGLE_OAUTH_CREDENTIALS": "/x.json",
    }
    config = read_syncall_args_config(env)
    assert config.combination_savename == "adhd-assistant"
    assert config.resolution_strategy == "AlwaysSecondRS"
    assert config.oauth_port == 8080
    assert config.verbose == 1


def test_read_syncall_args_config_rejects_missing_calendar() -> None:
    env = {"GOOGLE_OAUTH_CREDENTIALS": "/x.json"}
    with pytest.raises(ValueError, match="SYNCALL_GCAL_CALENDAR"):
        read_syncall_args_config(env)


def test_read_syncall_args_config_rejects_missing_credentials() -> None:
    env = {"SYNCALL_GCAL_CALENDAR": "Tasks"}
    with pytest.raises(ValueError, match="GOOGLE_OAUTH_CREDENTIALS"):
        read_syncall_args_config(env)


def test_read_syncall_args_config_rejects_non_integer_port() -> None:
    env = _full_env() | {"SYNCALL_OAUTH_PORT": "notaport"}
    with pytest.raises(ValueError, match="SYNCALL_OAUTH_PORT"):
        read_syncall_args_config(env)


def test_build_syncall_args_contains_required_flags() -> None:
    config = SyncallArgsConfig(
        gcal_calendar="Tasks",
        google_secret_path="/x.json",
        combination_savename="adhd-assistant",
        resolution_strategy="AlwaysSecondRS",
        oauth_port=8080,
        verbose=0,
        tw_filter="",
    )
    args = build_syncall_args(config)
    assert "--gcal-calendar" in args
    assert "Tasks" in args
    assert "--google-secret" in args
    assert "/x.json" in args
    assert "--resolution-strategy" in args
    assert "AlwaysSecondRS" in args
    assert "--custom-combination-savename" in args
    assert "adhd-assistant" in args
    assert "--oauth-port" in args
    assert "8080" in args


def test_build_syncall_args_never_includes_confirm() -> None:
    config = SyncallArgsConfig(
        gcal_calendar="Tasks",
        google_secret_path="/x.json",
        combination_savename="adhd-assistant",
        resolution_strategy="AlwaysSecondRS",
        oauth_port=8080,
        verbose=3,
        tw_filter="-migrated",
    )
    args = build_syncall_args(config)
    assert "--confirm" not in args


def test_build_syncall_args_appends_tw_filter_when_present() -> None:
    config = SyncallArgsConfig(
        gcal_calendar="Tasks",
        google_secret_path="/x.json",
        combination_savename="adhd-assistant",
        resolution_strategy="AlwaysSecondRS",
        oauth_port=8080,
        verbose=0,
        tw_filter="project:work",
    )
    args = build_syncall_args(config)
    assert "--tw-filter" in args
    assert "project:work" in args
    assert "--sync-all-tw-tasks" not in args


def test_build_syncall_args_falls_back_to_sync_all_when_no_filter() -> None:
    config = SyncallArgsConfig(
        gcal_calendar="Tasks",
        google_secret_path="/x.json",
        combination_savename="adhd-assistant",
        resolution_strategy="AlwaysSecondRS",
        oauth_port=8080,
        verbose=0,
        tw_filter="",
    )
    args = build_syncall_args(config)
    assert "--sync-all-tw-tasks" in args
    assert "--tw-filter" not in args


def test_build_syncall_args_emits_verbose_tokens() -> None:
    config = SyncallArgsConfig(
        gcal_calendar="Tasks",
        google_secret_path="/x.json",
        combination_savename="adhd-assistant",
        resolution_strategy="AlwaysSecondRS",
        oauth_port=8080,
        verbose=2,
        tw_filter="",
    )
    args = build_syncall_args(config)
    assert args.count("-v") == 2
