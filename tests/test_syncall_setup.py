"""Tests for syncall_setup helpers."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from syncall_setup import (
    SYNCALL_ENV_VARS,
    SyncallPaths,
    build_syncall,
    is_syncall_enabled,
    resolve_syncall_paths,
    write_repo_scoped_taskrc,
)


def test_is_syncall_enabled_true_variants() -> None:
    assert is_syncall_enabled({"SYNCALL_ENABLED": "true"})
    assert is_syncall_enabled({"SYNCALL_ENABLED": "TRUE"})
    assert is_syncall_enabled({"SYNCALL_ENABLED": "  true  "})


def test_is_syncall_enabled_false_variants() -> None:
    assert not is_syncall_enabled({})
    assert not is_syncall_enabled({"SYNCALL_ENABLED": "false"})
    assert not is_syncall_enabled({"SYNCALL_ENABLED": "0"})
    assert not is_syncall_enabled({"SYNCALL_ENABLED": ""})


def test_env_vars_catalog_contains_all_flags() -> None:
    expected = {
        "SYNCALL_ENABLED",
        "SYNCALL_GCAL_CALENDAR",
        "SYNCALL_COMBINATION_NAME",
        "SYNCALL_RESOLUTION_STRATEGY",
        "SYNCALL_POLL_SECONDS",
        "SYNCALL_OAUTH_PORT",
        "SYNCALL_VERBOSE",
    }
    assert expected.issubset(set(SYNCALL_ENV_VARS))


def test_resolve_syncall_paths_all_repo_scoped(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    tw_data_dir = tmp_path / "tw-data"
    env = {"GOOGLE_OAUTH_CREDENTIALS": "/some/abs/oauth.json"}
    paths = resolve_syncall_paths(env, repo_root, tw_data_dir)
    assert paths.cache_dir == repo_root / "workspace" / "data" / "syncall_cache"
    assert paths.xdg_config_home == paths.cache_dir
    assert paths.taskrc_path.parent == paths.cache_dir
    assert paths.tw_data_dir == tw_data_dir
    assert paths.log_path == repo_root / "workspace" / "data" / "syncall_daemon.log"
    assert paths.vendor_dir == repo_root / "vendor" / "syncall"
    assert paths.oauth_credentials == Path("/some/abs/oauth.json")


def test_resolve_syncall_paths_handles_missing_credentials(tmp_path: Path) -> None:
    paths = resolve_syncall_paths({}, tmp_path, tmp_path / "tw")
    assert paths.oauth_credentials == Path("")


def test_resolve_syncall_paths_expands_tilde_in_credentials(tmp_path: Path) -> None:
    env = {"GOOGLE_OAUTH_CREDENTIALS": "~/creds.json"}
    paths = resolve_syncall_paths(env, tmp_path, tmp_path / "tw")
    assert "~" not in str(paths.oauth_credentials)


def test_write_repo_scoped_taskrc_creates_file(tmp_path: Path) -> None:
    taskrc_path = tmp_path / "sub" / "taskrc"
    data_dir = tmp_path / "tw"
    write_repo_scoped_taskrc(taskrc_path, data_dir)
    assert taskrc_path.exists()
    body = taskrc_path.read_text(encoding="utf-8")
    assert f"data.location={data_dir.as_posix()}" in body
    assert "confirmation=off" in body


def test_write_repo_scoped_taskrc_overwrites_stale_file(tmp_path: Path) -> None:
    taskrc_path = tmp_path / "taskrc"
    taskrc_path.write_text("stale=yes\n", encoding="utf-8")
    write_repo_scoped_taskrc(taskrc_path, tmp_path / "tw")
    body = taskrc_path.read_text(encoding="utf-8")
    assert "stale=yes" not in body
    assert "data.location=" in body


def test_build_syncall_returns_none_when_flag_off(tmp_path: Path) -> None:
    env: dict[str, str] = {}
    result = build_syncall(env, tmp_path, tmp_path / "tw")
    assert result is None


def test_build_syncall_no_filesystem_when_flag_off(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    tw_data = tmp_path / "tw"
    build_syncall({}, repo_root, tw_data)
    assert not (repo_root / "workspace").exists()


def test_build_syncall_creates_cache_and_taskrc_when_flag_on(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    tw_data = tmp_path / "tw"
    tw_data.mkdir()
    env = {
        "SYNCALL_ENABLED": "true",
        "GOOGLE_OAUTH_CREDENTIALS": str(tmp_path / "nope.json"),
    }
    paths = build_syncall(env, repo_root, tw_data)
    assert paths is not None
    assert paths.cache_dir.is_dir()
    assert paths.taskrc_path.is_file()


def test_build_syncall_returns_resolved_paths_when_flag_on(tmp_path: Path) -> None:
    env = {
        "SYNCALL_ENABLED": "true",
        "GOOGLE_OAUTH_CREDENTIALS": "/abs/creds.json",
    }
    tw_data = tmp_path / "tw"
    tw_data.mkdir()
    paths = build_syncall(env, tmp_path, tw_data)
    assert isinstance(paths, SyncallPaths)
    assert paths.tw_data_dir == tw_data


@pytest.mark.skipif(sys.platform == "win32", reason="chmod 0700 no-ops on Windows")
def test_build_syncall_cache_dir_is_private_on_posix(tmp_path: Path) -> None:
    env = {
        "SYNCALL_ENABLED": "true",
        "GOOGLE_OAUTH_CREDENTIALS": "/abs/creds.json",
    }
    tw_data = tmp_path / "tw"
    tw_data.mkdir()
    paths = build_syncall(env, tmp_path, tw_data)
    assert paths is not None
    mode = paths.cache_dir.stat().st_mode & 0o777
    assert mode == 0o700


def test_build_syncall_warns_when_oauth_missing(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    missing = tmp_path / "does-not-exist.json"
    env = {
        "SYNCALL_ENABLED": "true",
        "GOOGLE_OAUTH_CREDENTIALS": str(missing),
    }
    tw_data = tmp_path / "tw"
    tw_data.mkdir()
    with caplog.at_level("WARNING"):
        build_syncall(env, tmp_path, tw_data)
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert any("GOOGLE_OAUTH_CREDENTIALS" in r.message for r in warnings)


def test_build_syncall_does_not_warn_when_oauth_file_exists(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    creds = tmp_path / "oauth.json"
    creds.write_text("{}", encoding="utf-8")
    tw_data = tmp_path / "tw"
    tw_data.mkdir()
    env = {
        "SYNCALL_ENABLED": "true",
        "GOOGLE_OAUTH_CREDENTIALS": str(creds),
    }
    with caplog.at_level("WARNING"):
        build_syncall(env, tmp_path, tw_data)
    warnings = [
        r for r in caplog.records
        if r.levelname == "WARNING" and "GOOGLE_OAUTH_CREDENTIALS" in r.message
    ]
    assert warnings == []


def test_os_environ_behaves_like_mapping_parameter() -> None:
    """resolve_syncall_paths accepts os.environ without crashing."""
    paths = resolve_syncall_paths(os.environ, Path("/tmp/repo"), Path("/tmp/tw"))
    assert paths.cache_dir.name == "syncall_cache"
