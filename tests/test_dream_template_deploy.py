"""Deploy test: verifies DREAM.md ships with workspace templates."""

from __future__ import annotations

from pathlib import Path

from setup_workspace import TEMPLATE_FILES, WORKSPACE_SRC, copy_workspace_files

DREAM_REL = "templates/DREAM.md"


class TestTemplateManifest:
    def test_dream_md_is_listed(self) -> None:
        assert DREAM_REL in TEMPLATE_FILES

    def test_dream_md_source_exists(self) -> None:
        assert (WORKSPACE_SRC / "templates" / "DREAM.md").exists()


class TestCopyWorkspaceFiles:
    def test_dream_md_copied_to_target(self, tmp_path: Path) -> None:
        target = tmp_path / "workspace"
        copied = copy_workspace_files(target)
        assert DREAM_REL in copied
        assert (target / "templates" / "DREAM.md").exists()

    def test_dream_md_contents_preserved(self, tmp_path: Path) -> None:
        target = tmp_path / "workspace"
        copy_workspace_files(target)
        copied = (target / "templates" / "DREAM.md").read_text(encoding="utf-8")
        source = (WORKSPACE_SRC / "templates" / "DREAM.md").read_text(
            encoding="utf-8",
        )
        assert copied == source
