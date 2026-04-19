"""Deploy test: verifies TASKWARRIOR.md ships with workspace templates."""

from __future__ import annotations

from pathlib import Path

from setup_workspace import TEMPLATE_FILES, WORKSPACE_SRC, copy_workspace_files


class TestTemplateManifest:
    def test_taskwarrior_md_is_listed(self) -> None:
        assert "TASKWARRIOR.md" in TEMPLATE_FILES

    def test_taskwarrior_md_source_exists(self) -> None:
        assert (WORKSPACE_SRC / "TASKWARRIOR.md").exists()


class TestCopyWorkspaceFiles:
    def test_taskwarrior_md_copied_to_target(self, tmp_path: Path) -> None:
        target = tmp_path / "workspace"
        copied = copy_workspace_files(target)
        assert "TASKWARRIOR.md" in copied
        assert (target / "TASKWARRIOR.md").exists()

    def test_taskwarrior_md_contents_preserved(self, tmp_path: Path) -> None:
        target = tmp_path / "workspace"
        copy_workspace_files(target)
        copied = (target / "TASKWARRIOR.md").read_text(encoding="utf-8")
        source = (WORKSPACE_SRC / "TASKWARRIOR.md").read_text(encoding="utf-8")
        assert copied == source


class TestTaskwarriorMdStructure:
    def test_has_nine_top_level_sections(self) -> None:
        source = (WORKSPACE_SRC / "TASKWARRIOR.md").read_text(encoding="utf-8")
        sections = [
            line for line in source.splitlines()
            if line.startswith("## ")
        ]
        expected = [
            "## TL;DR",
            "## Why",
            "## Prerequisites",
            "## First-time setup",
            "## Operation",
            "## Migration script",
            "## Rollback",
            "## Interaction with syncall",
            "## Troubleshooting",
        ]
        assert sections == expected

    def test_rollback_divergence_warning_is_prominent(self) -> None:
        source = (WORKSPACE_SRC / "TASKWARRIOR.md").read_text(encoding="utf-8")
        assert "Divergence warning" in source
        assert "flip-flop" in source
        assert "Pick a backend and stay there" in source
