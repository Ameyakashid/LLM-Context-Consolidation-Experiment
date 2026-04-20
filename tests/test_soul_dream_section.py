"""Byte-and-structure guard for the ``## Pulse + Dream`` addition to SOUL.md.

Keeps the sub-05 edit from drifting: the section heading must exist exactly
once, pre-existing headings must appear in the same order as before the
edit, and the total byte growth from the pre-edit baseline must be small
(≤ 1500 bytes) so the surrounding persona voice is not rewritten.
"""

from __future__ import annotations

from pathlib import Path

SOUL_PATH = Path(__file__).resolve().parent.parent / "workspace" / "SOUL.md"

# Byte baseline frozen immediately before each surgical SOUL.md addition lands.
# Bumped in Task 19/sub-03 when ``## Voice Input`` was inserted between
# ``## Pulse + Dream`` and ``## Calendar`` (see _build/tasks/19-whisper-voice-input/
# sub-03/19-03i.md). Future edits should bump with intent rather than drift.
PRE_EDIT_BYTES = 24885
MAX_BYTE_DELTA = 1500

EXPECTED_HEADING_ORDER = [
    "## Voice and Tone",
    "## Neuroaffirming Rules",
    "## ICNU Motivation Framework",
    "## Communication Style",
    "## Boundaries",
    "## Task Management",
    "## State-Aware Adaptation",
    "## Memory",
    "## Buffer System",
    "## Scheduled Check-Ins",
    "## Voice Output",
    "## Dashboard",
    "## Fire Tablet Display",
    "## Task Ledger",
    "## Pulse + Dream",
    "## Voice Input",
    "## Calendar",
    "## Disco Flavor Layer",
]


def _soul_text() -> str:
    return SOUL_PATH.read_text(encoding="utf-8")


def _soul_headings() -> list[str]:
    return [line for line in _soul_text().splitlines() if line.startswith("## ")]


class TestPulseDreamSection:
    def test_heading_present_exactly_once(self) -> None:
        headings = _soul_headings()
        assert headings.count("## Pulse + Dream") == 1

    def test_section_positioned_between_task_ledger_and_calendar(self) -> None:
        headings = _soul_headings()
        ledger = headings.index("## Task Ledger")
        pulse = headings.index("## Pulse + Dream")
        calendar = headings.index("## Calendar")
        assert ledger < pulse < calendar

    def test_all_preexisting_headings_preserved_in_order(self) -> None:
        assert _soul_headings() == EXPECTED_HEADING_ORDER


class TestPulseDreamContent:
    def test_points_readers_at_temm1e_pulse_md(self) -> None:
        assert "TEMM1E_PULSE.md" in _soul_text()

    def test_dream_state_metadata_source_documented(self) -> None:
        assert 'metadata.source == "dream_state"' in _soul_text()

    def test_legacy_and_pulse_mode_check_ins_indistinguishable(self) -> None:
        text = _soul_text().lower()
        assert "pulse-mode" in text
        assert "identical" in text


class TestByteBudget:
    def test_total_size_under_budget(self) -> None:
        size = SOUL_PATH.stat().st_size
        assert size <= PRE_EDIT_BYTES + MAX_BYTE_DELTA, (
            f"SOUL.md grew by {size - PRE_EDIT_BYTES} bytes; "
            f"budget is {MAX_BYTE_DELTA}. If the rewrite is intentional, "
            "bump PRE_EDIT_BYTES in this test."
        )
