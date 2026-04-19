"""Verify setup_workspace.py wiring for syncall."""

from __future__ import annotations

from pathlib import Path

import setup_workspace


def test_template_files_includes_syncall_md() -> None:
    assert "SYNCALL.md" in setup_workspace.TEMPLATE_FILES


def test_workspace_syncall_template_exists() -> None:
    repo_root = Path(setup_workspace.__file__).resolve().parent
    template = repo_root / "workspace" / "SYNCALL.md"
    assert template.is_file()


def test_syncall_md_documents_conflict_policy() -> None:
    repo_root = Path(setup_workspace.__file__).resolve().parent
    body = (repo_root / "workspace" / "SYNCALL.md").read_text(encoding="utf-8")
    assert "Taskwarrior wins" in body or "tw_wins" in body


def test_syncall_md_documents_poll_cadence() -> None:
    repo_root = Path(setup_workspace.__file__).resolve().parent
    body = (repo_root / "workspace" / "SYNCALL.md").read_text(encoding="utf-8")
    assert "10 minutes" in body or "600" in body


def test_syncall_md_documents_first_run_oauth_ritual() -> None:
    repo_root = Path(setup_workspace.__file__).resolve().parent
    body = (repo_root / "workspace" / "SYNCALL.md").read_text(encoding="utf-8")
    assert "OAuth" in body
    assert "tw_gcal_sync" in body


def test_syncall_md_documents_new_gcal_event_behavior() -> None:
    repo_root = Path(setup_workspace.__file__).resolve().parent
    body = (repo_root / "workspace" / "SYNCALL.md").read_text(encoding="utf-8")
    assert "implicit task creation" in body.lower() or "calendar" in body.lower()


def test_setup_workspace_exports_syncall_helpers() -> None:
    assert "build_syncall" in setup_workspace.__all__
    assert "is_syncall_enabled" in setup_workspace.__all__
