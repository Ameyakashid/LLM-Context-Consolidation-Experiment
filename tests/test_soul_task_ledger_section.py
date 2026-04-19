"""SOUL.md gains a surgical ``## Task Ledger`` subsection in sub-04.

Locks content + placement so the bot's prompt gets the awareness hint
without any other SOUL.md section shifting position.
"""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SOUL_MD_PATH = REPO_ROOT / "workspace" / "SOUL.md"


def _section_headings(markdown: str) -> list[str]:
    return [
        line for line in markdown.splitlines()
        if line.startswith("## ")
    ]


def _extract_section(markdown: str, heading: str) -> str:
    """Return the body of the section under ``heading``, up to the next ``## ``."""
    lines = markdown.splitlines()
    start: int | None = None
    for index, line in enumerate(lines):
        if line == heading:
            start = index + 1
            break
    if start is None:
        raise AssertionError(
            f"SOUL.md missing heading {heading!r}. "
            "The ## Task Ledger insertion in sub-04 must not drop it."
        )
    end = len(lines)
    for index in range(start, len(lines)):
        if lines[index].startswith("## "):
            end = index
            break
    return "\n".join(lines[start:end])


class TestTaskLedgerSectionPresent:
    def test_section_heading_exists(self) -> None:
        text = SOUL_MD_PATH.read_text(encoding="utf-8")
        assert "## Task Ledger" in _section_headings(text)

    def test_section_is_between_fire_tablet_and_calendar(self) -> None:
        headings = _section_headings(SOUL_MD_PATH.read_text(encoding="utf-8"))
        ftd_index = headings.index("## Fire Tablet Display")
        ledger_index = headings.index("## Task Ledger")
        calendar_index = headings.index("## Calendar")
        assert ftd_index < ledger_index < calendar_index


class TestTaskLedgerSectionContent:
    def _body(self) -> str:
        return _extract_section(
            SOUL_MD_PATH.read_text(encoding="utf-8"), "## Task Ledger",
        )

    def test_mentions_both_backends(self) -> None:
        body = self._body()
        assert "Taskwarrior" in body
        assert "JSON" in body

    def test_points_at_docs(self) -> None:
        body = self._body()
        assert "TASKWARRIOR.md" in body
        assert "SYNCALL.md" in body

    def test_length_within_expected_range(self) -> None:
        body = self._body()
        non_empty_lines = [
            line for line in body.splitlines() if line.strip()
        ]
        assert 4 <= len(non_empty_lines) <= 20
