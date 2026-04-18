"""Verify pytest configuration, guard conftest, and test-runner setup.

These tests enforce the stabilization-phase invariants from Task 12 sub-01:
repo-local pytest config pinning scope and import paths, a root conftest
guarding the nanobot import, a declared dev-dependency file, and
Testing documentation in README.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_pytest_ini_exists() -> None:
    assert (REPO_ROOT / "pytest.ini").is_file()


def test_pytest_ini_scopes_collection_to_tests_dir() -> None:
    content = _read(REPO_ROOT / "pytest.ini")
    assert "testpaths" in content
    assert "tests" in content


def test_pytest_ini_puts_repo_root_on_pythonpath() -> None:
    content = _read(REPO_ROOT / "pytest.ini")
    assert "pythonpath" in content


def test_pytest_ini_excludes_references_and_venv_from_recursion() -> None:
    content = _read(REPO_ROOT / "pytest.ini")
    assert "norecursedirs" in content
    assert "references" in content
    assert ".venv" in content


def test_conftest_exists_at_repo_root() -> None:
    assert (REPO_ROOT / "conftest.py").is_file()


def test_conftest_guards_nanobot_import() -> None:
    content = _read(REPO_ROOT / "conftest.py")
    assert "nanobot" in content
    assert "ImportError" in content or "import_module" in content


def test_requirements_dev_declares_pytest() -> None:
    path = REPO_ROOT / "requirements-dev.txt"
    assert path.is_file()
    content = _read(path)
    assert "pytest" in content


def test_requirements_dev_includes_runtime_requirements() -> None:
    content = _read(REPO_ROOT / "requirements-dev.txt")
    assert "-r requirements.txt" in content


def test_readme_has_testing_section() -> None:
    content = _read(REPO_ROOT / "README.md")
    assert "## Testing" in content


def test_readme_testing_section_covers_both_platforms() -> None:
    content = _read(REPO_ROOT / "README.md")
    testing_index = content.find("## Testing")
    assert testing_index != -1
    section = content[testing_index : testing_index + 2000]
    assert ".venv/Scripts" in section
    assert ".venv/bin" in section


def test_gitignore_covers_nested_pycache() -> None:
    content = _read(REPO_ROOT / ".gitignore")
    assert "__pycache__/" in content
