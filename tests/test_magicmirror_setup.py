"""Tests for the MagicMirror² build-helper surface.

Covers:
  * ``is_magicmirror_enabled`` flag parsing
  * ``detect_node_npm`` missing-npm error
  * ``build_magicmirror`` short-circuit + per-package freshness + argv
  * exported constants + setup_workspace re-export identity

Vendor-integrity, template rendering, gitignore, and .env.example checks
live in ``test_magicmirror_config_template.py`` to keep this file under
the 300-line cap.
"""

import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from magicmirror_setup import (
    MAGICMIRROR_WEBHOOK_TEMPLATE_NAMES,
    MODULE_NAMES,
    build_magicmirror,
    detect_node_npm,
    is_magicmirror_enabled,
)


def _make_vendor_tree(tmp_path: Path) -> Path:
    """Create a minimal magicmirror/ tree at ``tmp_path``. Returns repo root."""
    repo_root = tmp_path / "repo"
    mm = repo_root / "magicmirror"
    mm.mkdir(parents=True)
    (mm / "package.json").write_text('{"name": "magicmirror"}', encoding="utf-8")
    modules_dir = mm / "modules"
    for name in MODULE_NAMES:
        pkg = modules_dir / name
        pkg.mkdir(parents=True)
        (pkg / "package.json").write_text(
            f'{{"name": "{name}"}}', encoding="utf-8"
        )
    return repo_root


class TestIsMagicmirrorEnabled:
    def test_true_when_env_true(self) -> None:
        assert is_magicmirror_enabled({"MAGICMIRROR_ENABLED": "true"})

    def test_false_when_env_false(self) -> None:
        assert not is_magicmirror_enabled({"MAGICMIRROR_ENABLED": "false"})

    def test_false_when_missing(self) -> None:
        assert not is_magicmirror_enabled({})

    def test_case_insensitive_true(self) -> None:
        assert is_magicmirror_enabled({"MAGICMIRROR_ENABLED": "TRUE"})
        assert is_magicmirror_enabled({"MAGICMIRROR_ENABLED": "True"})

    def test_whitespace_tolerated(self) -> None:
        assert is_magicmirror_enabled({"MAGICMIRROR_ENABLED": "  true  "})

    def test_non_truthy_values_false(self) -> None:
        assert not is_magicmirror_enabled({"MAGICMIRROR_ENABLED": "1"})
        assert not is_magicmirror_enabled({"MAGICMIRROR_ENABLED": "yes"})
        assert not is_magicmirror_enabled({"MAGICMIRROR_ENABLED": ""})


class TestDetectNodeNpm:
    def test_returns_path_when_present(self) -> None:
        with patch(
            "magicmirror_setup.shutil.which", return_value="/usr/bin/npm"
        ):
            assert detect_node_npm() == "/usr/bin/npm"

    def test_raises_actionable_error_when_missing(self) -> None:
        with patch("magicmirror_setup.shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="npm not found on PATH"):
                detect_node_npm()


class TestBuildMagicmirrorFlagOff:
    def test_short_circuits_without_npm_when_disabled(
        self, tmp_path: Path
    ) -> None:
        # Even with no vendored tree, a disabled flag must no-op.
        with patch("magicmirror_setup.shutil.which") as which_mock, patch(
            "magicmirror_setup.subprocess.run"
        ) as run_mock:
            build_magicmirror(tmp_path / "missing", False)
            which_mock.assert_not_called()
            run_mock.assert_not_called()


class TestBuildMagicmirrorNpmMissing:
    def test_raises_when_npm_absent(self, tmp_path: Path) -> None:
        repo_root = _make_vendor_tree(tmp_path)
        with patch("magicmirror_setup.shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="npm not found on PATH"):
                build_magicmirror(repo_root, True)


class TestBuildMagicmirrorMissingVendor:
    def test_raises_when_magicmirror_dir_absent(self, tmp_path: Path) -> None:
        with pytest.raises(
            FileNotFoundError, match="Vendored MagicMirror directory"
        ):
            build_magicmirror(tmp_path / "empty-repo", True)


class TestBuildMagicmirrorFreshness:
    def test_runs_install_on_all_four_when_stale(self, tmp_path: Path) -> None:
        repo_root = _make_vendor_tree(tmp_path)
        mock_result = MagicMock(stdout="", stderr="")
        with patch(
            "magicmirror_setup.shutil.which", return_value="/usr/bin/npm"
        ), patch(
            "magicmirror_setup.subprocess.run", return_value=mock_result
        ) as run_mock:
            build_magicmirror(repo_root, True)
        assert run_mock.call_count == 4

    def test_core_install_passes_ignore_scripts(self, tmp_path: Path) -> None:
        repo_root = _make_vendor_tree(tmp_path)
        mock_result = MagicMock(stdout="", stderr="")
        with patch(
            "magicmirror_setup.shutil.which", return_value="/usr/bin/npm"
        ), patch(
            "magicmirror_setup.subprocess.run", return_value=mock_result
        ) as run_mock:
            build_magicmirror(repo_root, True)
        first_call = run_mock.call_args_list[0]
        assert first_call.args[0] == [
            "/usr/bin/npm",
            "install",
            "--ignore-scripts",
        ]
        assert first_call.kwargs["cwd"] == repo_root / "magicmirror"

    def test_module_installs_do_not_pass_ignore_scripts(
        self, tmp_path: Path
    ) -> None:
        repo_root = _make_vendor_tree(tmp_path)
        mock_result = MagicMock(stdout="", stderr="")
        with patch(
            "magicmirror_setup.shutil.which", return_value="/usr/bin/npm"
        ), patch(
            "magicmirror_setup.subprocess.run", return_value=mock_result
        ) as run_mock:
            build_magicmirror(repo_root, True)
        for call in run_mock.call_args_list[1:]:
            assert call.args[0] == ["/usr/bin/npm", "install"]

    def test_skips_package_when_node_modules_fresh(
        self, tmp_path: Path
    ) -> None:
        repo_root = _make_vendor_tree(tmp_path)
        mm = repo_root / "magicmirror"
        (mm / "node_modules").mkdir()
        lock = mm / "package-lock.json"
        lock.write_text("{}", encoding="utf-8")
        nm_mtime = (mm / "node_modules").stat().st_mtime
        os.utime(lock, (nm_mtime - 100, nm_mtime - 100))
        mock_result = MagicMock(stdout="", stderr="")
        with patch(
            "magicmirror_setup.shutil.which", return_value="/usr/bin/npm"
        ), patch(
            "magicmirror_setup.subprocess.run", return_value=mock_result
        ) as run_mock:
            build_magicmirror(repo_root, True)
        assert run_mock.call_count == 3
        for call in run_mock.call_args_list:
            assert call.kwargs["cwd"] != mm

    def test_re_runs_install_when_lock_newer(self, tmp_path: Path) -> None:
        repo_root = _make_vendor_tree(tmp_path)
        mm = repo_root / "magicmirror"
        (mm / "node_modules").mkdir()
        lock = mm / "package-lock.json"
        lock.write_text("{}", encoding="utf-8")
        nm_mtime = (mm / "node_modules").stat().st_mtime
        os.utime(lock, (nm_mtime + 100, nm_mtime + 100))
        mock_result = MagicMock(stdout="", stderr="")
        with patch(
            "magicmirror_setup.shutil.which", return_value="/usr/bin/npm"
        ), patch(
            "magicmirror_setup.subprocess.run", return_value=mock_result
        ) as run_mock:
            build_magicmirror(repo_root, True)
        assert run_mock.call_count == 4


class TestBuildMagicmirrorNpmFailure:
    def test_wraps_called_process_error(self, tmp_path: Path) -> None:
        repo_root = _make_vendor_tree(tmp_path)
        exc = subprocess.CalledProcessError(
            returncode=1,
            cmd=["npm", "install", "--ignore-scripts"],
            stderr="boom",
        )
        with patch(
            "magicmirror_setup.shutil.which", return_value="/usr/bin/npm"
        ), patch("magicmirror_setup.subprocess.run", side_effect=exc):
            with pytest.raises(
                RuntimeError, match="npm install --ignore-scripts failed"
            ):
                build_magicmirror(repo_root, True)


class TestExportedConstants:
    def test_webhook_template_names_tuple(self) -> None:
        assert MAGICMIRROR_WEBHOOK_TEMPLATE_NAMES == (
            "state_change",
            "buffer_alert",
            "missed_checkin",
        )
        assert isinstance(MAGICMIRROR_WEBHOOK_TEMPLATE_NAMES, tuple)

    def test_module_names_tuple(self) -> None:
        assert MODULE_NAMES == (
            "MMM-WebHookAlerts",
            "MMM-Markdown",
            "MMM-pages",
        )


def test_setup_workspace_re_exports_magicmirror_helpers() -> None:
    """setup_workspace imports from magicmirror_setup — loose coupling check."""
    import magicmirror_setup
    import setup_workspace as sw

    assert sw.build_magicmirror is magicmirror_setup.build_magicmirror
    assert sw.is_magicmirror_enabled is magicmirror_setup.is_magicmirror_enabled
    assert (
        sw.render_magicmirror_config is magicmirror_setup.render_magicmirror_config
    )
    assert (
        sw.MAGICMIRROR_WEBHOOK_TEMPLATE_NAMES
        is magicmirror_setup.MAGICMIRROR_WEBHOOK_TEMPLATE_NAMES
    )
