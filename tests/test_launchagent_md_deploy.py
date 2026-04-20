"""Deploy test: verifies LAUNCHAGENT.md ships with workspace templates."""

from __future__ import annotations

from pathlib import Path

from setup_workspace import TEMPLATE_FILES, WORKSPACE_SRC, copy_workspace_files


class TestTemplateManifest:
    def test_launchagent_md_is_listed(self) -> None:
        assert "LAUNCHAGENT.md" in TEMPLATE_FILES

    def test_launchagent_md_listed_exactly_once(self) -> None:
        assert TEMPLATE_FILES.count("LAUNCHAGENT.md") == 1

    def test_launchagent_md_source_exists(self) -> None:
        assert (WORKSPACE_SRC / "LAUNCHAGENT.md").is_file()


class TestCopyWorkspaceFiles:
    def test_launchagent_md_copied_to_target(self, tmp_path: Path) -> None:
        target = tmp_path / "workspace"
        copied = copy_workspace_files(target)
        assert "LAUNCHAGENT.md" in copied
        assert (target / "LAUNCHAGENT.md").is_file()

    def test_launchagent_md_contents_preserved(self, tmp_path: Path) -> None:
        target = tmp_path / "workspace"
        copy_workspace_files(target)
        copied = (target / "LAUNCHAGENT.md").read_text(encoding="utf-8")
        source = (WORKSPACE_SRC / "LAUNCHAGENT.md").read_text(encoding="utf-8")
        assert copied == source
