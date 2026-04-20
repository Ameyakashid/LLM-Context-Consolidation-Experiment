"""Deploy test: VOICE_INPUT.md ships byte-identically via TEMPLATE_FILES."""

from __future__ import annotations

from pathlib import Path

from setup_workspace import TEMPLATE_FILES, WORKSPACE_SRC, copy_workspace_files


class TestTemplateManifest:
    def test_voice_input_md_is_listed(self) -> None:
        assert "VOICE_INPUT.md" in TEMPLATE_FILES

    def test_voice_input_md_listed_exactly_once(self) -> None:
        assert TEMPLATE_FILES.count("VOICE_INPUT.md") == 1

    def test_voice_input_md_source_exists(self) -> None:
        assert (WORKSPACE_SRC / "VOICE_INPUT.md").is_file()


class TestCopyWorkspaceFiles:
    def test_voice_input_md_copied_to_target(self, tmp_path: Path) -> None:
        target = tmp_path / "workspace"
        copied = copy_workspace_files(target)
        assert "VOICE_INPUT.md" in copied
        assert (target / "VOICE_INPUT.md").is_file()

    def test_voice_input_md_contents_preserved(self, tmp_path: Path) -> None:
        target = tmp_path / "workspace"
        copy_workspace_files(target)
        copied = (target / "VOICE_INPUT.md").read_text(encoding="utf-8")
        source = (WORKSPACE_SRC / "VOICE_INPUT.md").read_text(encoding="utf-8")
        assert copied == source
