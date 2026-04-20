"""Deploy test: verifies INSTALL_MAC.md ships with workspace templates."""

from __future__ import annotations

from pathlib import Path

from setup_workspace import TEMPLATE_FILES, WORKSPACE_SRC, copy_workspace_files


class TestTemplateManifest:
    def test_install_mac_md_is_listed(self) -> None:
        assert "INSTALL_MAC.md" in TEMPLATE_FILES

    def test_install_mac_md_source_exists(self) -> None:
        assert (WORKSPACE_SRC / "INSTALL_MAC.md").is_file()


class TestCopyWorkspaceFiles:
    def test_install_mac_md_copied_to_target(self, tmp_path: Path) -> None:
        target = tmp_path / "workspace"
        copied = copy_workspace_files(target)
        assert "INSTALL_MAC.md" in copied
        assert (target / "INSTALL_MAC.md").is_file()

    def test_install_mac_md_contents_preserved(self, tmp_path: Path) -> None:
        target = tmp_path / "workspace"
        copy_workspace_files(target)
        copied = (target / "INSTALL_MAC.md").read_text(encoding="utf-8")
        source = (WORKSPACE_SRC / "INSTALL_MAC.md").read_text(encoding="utf-8")
        assert copied == source
