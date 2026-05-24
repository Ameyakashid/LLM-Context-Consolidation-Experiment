"""Deploy test: verifies TEMM1E_PULSE.md ships with workspace templates."""

from __future__ import annotations

from pathlib import Path

from setup_workspace import TEMPLATE_FILES, WORKSPACE_SRC, copy_workspace_files


class TestTemplateManifest:
    def test_temm1e_pulse_md_is_listed(self) -> None:
        assert "TEMM1E_PULSE.md" in TEMPLATE_FILES

    def test_temm1e_pulse_md_source_exists(self) -> None:
        assert (WORKSPACE_SRC / "TEMM1E_PULSE.md").exists()


class TestCopyWorkspaceFiles:
    def test_temm1e_pulse_md_copied_to_target(self, tmp_path: Path) -> None:
        target = tmp_path / "workspace"
        copied = copy_workspace_files(target)
        assert "TEMM1E_PULSE.md" in copied
        assert (target / "TEMM1E_PULSE.md").exists()

    def test_temm1e_pulse_md_contents_preserved(self, tmp_path: Path) -> None:
        target = tmp_path / "workspace"
        copy_workspace_files(target)
        copied = (target / "TEMM1E_PULSE.md").read_text(encoding="utf-8")
        source = (WORKSPACE_SRC / "TEMM1E_PULSE.md").read_text(encoding="utf-8")
        assert copied == source


class TestTemm1ePulseMdStructure:
    def test_has_expected_top_level_sections(self) -> None:
        source = (WORKSPACE_SRC / "TEMM1E_PULSE.md").read_text(encoding="utf-8")
        sections = [
            line for line in source.splitlines()
            if line.startswith("## ")
        ]
        expected = [
            "## TL;DR",
            "## Why TEMM1E",
            "## Feature flags",
            "## Rollback",
            "## Dream State explained",
            "## Divergence warning",
            "## Troubleshooting",
        ]
        assert sections == expected

    def test_divergence_warning_is_prominent(self) -> None:
        source = (WORKSPACE_SRC / "TEMM1E_PULSE.md").read_text(encoding="utf-8")
        assert "Divergence warning" in source
        assert "flip-flop" in source
        assert "Pick a backend and stay" in source

    def test_both_flags_documented(self) -> None:
        source = (WORKSPACE_SRC / "TEMM1E_PULSE.md").read_text(encoding="utf-8")
        assert "PULSE_ENGINE_ENABLED" in source
        assert "DREAM_STATE_ENABLED" in source
        assert "DREAM_STATE_CRON" in source

    def test_dream_requires_pulse_rule_stated(self) -> None:
        source = (WORKSPACE_SRC / "TEMM1E_PULSE.md").read_text(encoding="utf-8")
        assert "Dream requires Pulse" in source
