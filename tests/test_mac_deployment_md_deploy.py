"""Deploy test: MAC_DEPLOYMENT.md ships byte-identically via TEMPLATE_FILES."""

from __future__ import annotations

from pathlib import Path

from setup_workspace import TEMPLATE_FILES, WORKSPACE_SRC, copy_workspace_files


class TestTemplateManifest:
    def test_mac_deployment_md_is_listed(self) -> None:
        assert "MAC_DEPLOYMENT.md" in TEMPLATE_FILES

    def test_mac_deployment_md_listed_exactly_once(self) -> None:
        assert TEMPLATE_FILES.count("MAC_DEPLOYMENT.md") == 1

    def test_mac_deployment_md_source_exists(self) -> None:
        assert (WORKSPACE_SRC / "MAC_DEPLOYMENT.md").is_file()


class TestCopyWorkspaceFiles:
    def test_mac_deployment_md_copied_to_target(self, tmp_path: Path) -> None:
        target = tmp_path / "workspace"
        copied = copy_workspace_files(target)
        assert "MAC_DEPLOYMENT.md" in copied
        assert (target / "MAC_DEPLOYMENT.md").is_file()

    def test_mac_deployment_md_contents_preserved(self, tmp_path: Path) -> None:
        target = tmp_path / "workspace"
        copy_workspace_files(target)
        copied = (target / "MAC_DEPLOYMENT.md").read_text(encoding="utf-8")
        source = (WORKSPACE_SRC / "MAC_DEPLOYMENT.md").read_text(encoding="utf-8")
        assert copied == source
