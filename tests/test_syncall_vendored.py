"""Structural checks on the vendor/syncall drop."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
VENDOR_DIR = REPO_ROOT / "vendor" / "syncall"


def test_vendor_dir_exists() -> None:
    assert VENDOR_DIR.is_dir(), f"expected vendored tree at {VENDOR_DIR}"


def test_vendor_source_file_exists() -> None:
    assert (VENDOR_DIR / ".vendor-source.md").is_file()


def test_vendor_source_has_required_fields() -> None:
    body = (VENDOR_DIR / ".vendor-source.md").read_text(encoding="utf-8")
    assert "Upstream:" in body
    assert "Commit:" in body
    assert "Vendored:" in body
    assert "Stripped from the drop" in body


def test_license_preserved() -> None:
    assert (VENDOR_DIR / "LICENSE").is_file()


def test_upstream_dirs_are_stripped() -> None:
    for forbidden in (".git", ".github", "docs", "tests", "misc", "completions"):
        assert not (VENDOR_DIR / forbidden).exists(), (
            f"vendor/syncall/{forbidden} should be stripped"
        )


def test_syncall_package_is_importable_from_vendor() -> None:
    pytest.importorskip("bubop", reason="bubop is a syncall transitive dep")
    spec = importlib.util.find_spec("syncall")
    assert spec is not None
    assert spec.origin is not None
    assert str(VENDOR_DIR) in spec.origin


def test_syncall_scripts_tw_gcal_sync_module_resolves() -> None:
    pytest.importorskip("bubop")
    pytest.importorskip("click")
    spec = importlib.util.find_spec("syncall.scripts.tw_gcal_sync")
    assert spec is not None
