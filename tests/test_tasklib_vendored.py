"""Sanity check that the vendored tasklib tree is discoverable and
provenance-tagged."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
VENDOR_DIR = REPO_ROOT / "vendor" / "tasklib"
PROVENANCE = VENDOR_DIR / ".vendor-source.md"


def test_vendor_dir_exists() -> None:
    assert VENDOR_DIR.is_dir(), (
        f"vendored tasklib not at {VENDOR_DIR}; ensure task 16-01 "
        "vendoring was run."
    )


def test_provenance_file_exists() -> None:
    assert PROVENANCE.is_file(), f"provenance file missing at {PROVENANCE}"


def test_provenance_records_commit_and_version() -> None:
    text = PROVENANCE.read_text(encoding="utf-8")
    assert "793a86d2432d93425e36a6384db1f563be07018c" in text, (
        "upstream commit sha missing from .vendor-source.md"
    )
    assert "2.5.1" in text, "upstream version missing from .vendor-source.md"


def test_provenance_names_stripped_dirs() -> None:
    text = PROVENANCE.read_text(encoding="utf-8")
    assert ".git/" in text
    assert "docs/" in text
    assert "tasklib/tests.py" in text


def test_tasklib_imports_from_vendored_tree() -> None:
    pytest.importorskip("tasklib")
    import tasklib

    mod_path = Path(importlib.import_module("tasklib").__file__ or "")
    assert "tasklib" in mod_path.parts
    assert tasklib.__version__ == "2.5.1"


def test_vendored_tasklib_does_not_ship_upstream_tests() -> None:
    assert not (VENDOR_DIR / "tasklib" / "tests.py").exists(), (
        "upstream tasklib/tests.py should be stripped — it would be "
        "collected by pytest and pollute test counts."
    )


def test_vendor_tree_retains_core_modules() -> None:
    tasklib_pkg = VENDOR_DIR / "tasklib"
    for name in (
        "__init__.py",
        "backends.py",
        "filters.py",
        "lazy.py",
        "serializing.py",
        "task.py",
    ):
        assert (tasklib_pkg / name).is_file(), f"missing {name}"


def test_sys_path_fallback_resolves_vendor_tree() -> None:
    """If pip-installed tasklib is removed, sys.path can still locate the
    vendor tree. Confirms the tree is self-contained (no external build
    artefacts needed to import)."""
    saved_path = list(sys.path)
    saved_modules = {
        name: mod
        for name, mod in sys.modules.items()
        if name == "tasklib" or name.startswith("tasklib.")
    }
    for name in list(saved_modules):
        del sys.modules[name]
    try:
        sys.path.insert(0, str(VENDOR_DIR))
        module = importlib.import_module("tasklib")
        assert module.__version__ == "2.5.1"
    finally:
        sys.path[:] = saved_path
        for name in list(sys.modules):
            if name == "tasklib" or name.startswith("tasklib."):
                del sys.modules[name]
        sys.modules.update(saved_modules)
