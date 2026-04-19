"""Deploy test: verifies MAGICMIRROR.md ships with workspace templates."""

from __future__ import annotations

from pathlib import Path

from setup_workspace import TEMPLATE_FILES, WORKSPACE_SRC, copy_workspace_files


class TestTemplateManifest:
    def test_magicmirror_md_is_listed(self) -> None:
        assert "MAGICMIRROR.md" in TEMPLATE_FILES

    def test_magicmirror_md_source_exists(self) -> None:
        assert (WORKSPACE_SRC / "MAGICMIRROR.md").exists()


class TestCopyWorkspaceFiles:
    def test_magicmirror_md_copied_to_target(self, tmp_path: Path) -> None:
        target = tmp_path / "workspace"
        copied = copy_workspace_files(target)
        assert "MAGICMIRROR.md" in copied
        assert (target / "MAGICMIRROR.md").exists()

    def test_magicmirror_md_contents_preserved(self, tmp_path: Path) -> None:
        target = tmp_path / "workspace"
        copy_workspace_files(target)
        copied = (target / "MAGICMIRROR.md").read_text(encoding="utf-8")
        source = (WORKSPACE_SRC / "MAGICMIRROR.md").read_text(encoding="utf-8")
        assert copied == source
