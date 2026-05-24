"""Deploy test: verifies CALENDAR.md ships with workspace templates."""

from __future__ import annotations

from pathlib import Path

from setup_workspace import TEMPLATE_FILES, WORKSPACE_SRC, copy_workspace_files


class TestTemplateManifest:
    def test_calendar_md_is_listed(self) -> None:
        assert "CALENDAR.md" in TEMPLATE_FILES

    def test_calendar_md_source_exists(self) -> None:
        assert (WORKSPACE_SRC / "CALENDAR.md").exists()


class TestCopyWorkspaceFiles:
    def test_calendar_md_copied_to_target(self, tmp_path: Path) -> None:
        target = tmp_path / "workspace"
        copied = copy_workspace_files(target)
        assert "CALENDAR.md" in copied
        assert (target / "CALENDAR.md").exists()

    def test_calendar_md_contents_preserved(self, tmp_path: Path) -> None:
        target = tmp_path / "workspace"
        copy_workspace_files(target)
        copied = (target / "CALENDAR.md").read_text(encoding="utf-8")
        source = (WORKSPACE_SRC / "CALENDAR.md").read_text(encoding="utf-8")
        assert copied == source
