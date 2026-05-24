"""Tests for scheduling hook — SOUL.md and HEARTBEAT.md workspace content."""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SOUL_PATH = REPO_ROOT / "workspace" / "SOUL.md"
HEARTBEAT_PATH = REPO_ROOT / "workspace" / "HEARTBEAT.md"


# ---------------------------------------------------------------------------
# SOUL.md content
# ---------------------------------------------------------------------------

class TestSoulCheckinSection:

    @pytest.fixture(scope="class")
    def soul_content(self) -> str:
        return SOUL_PATH.read_text(encoding="utf-8")

    def test_has_scheduled_checkins_heading(self, soul_content: str) -> None:
        assert "## Scheduled Check-Ins" in soul_content

    @pytest.mark.parametrize("checkin_heading", [
        "### Morning Motivation (08:00)",
        "### Morning Plan (09:00)",
        "### Afternoon Check (14:00)",
        "### Evening Review (20:00)",
    ])
    def test_has_checkin_type_heading(
        self, soul_content: str, checkin_heading: str
    ) -> None:
        assert checkin_heading in soul_content

    def test_morning_motivation_mentions_icnu(self, soul_content: str) -> None:
        section = self._extract("Morning Motivation", soul_content)
        assert "icnu" in section.lower()

    def test_morning_plan_mentions_one_thing(self, soul_content: str) -> None:
        section = self._extract("Morning Plan", soul_content)
        assert "one thing" in section.lower()

    def test_afternoon_check_mentions_energy(self, soul_content: str) -> None:
        section = self._extract("Afternoon Check", soul_content)
        assert "energy" in section.lower()

    def test_evening_review_mentions_went_well(self, soul_content: str) -> None:
        section = self._extract("Evening Review", soul_content)
        assert "went well" in section.lower()

    def test_evening_review_mentions_closure(self, soul_content: str) -> None:
        section = self._extract("Evening Review", soul_content)
        assert "closure" in section.lower() or "wrap up" in section.lower()

    def _extract(self, heading: str, content: str) -> str:
        marker = f"### {heading}"
        start = content.find(marker)
        if start == -1:
            return ""
        start += len(marker)
        next_h3 = content.find("\n### ", start)
        next_h2 = content.find("\n## ", start)
        ends = [e for e in [next_h3, next_h2] if e != -1]
        end = min(ends) if ends else len(content)
        return content[start:end]


# ---------------------------------------------------------------------------
# HEARTBEAT.md content
# ---------------------------------------------------------------------------

class TestHeartbeatContent:

    @pytest.fixture(scope="class")
    def heartbeat_content(self) -> str:
        return HEARTBEAT_PATH.read_text(encoding="utf-8")

    @pytest.mark.parametrize("section", [
        "Morning Motivation",
        "Morning Plan",
        "Afternoon Check",
        "Evening Review",
    ])
    def test_has_all_checkin_sections(
        self, heartbeat_content: str, section: str
    ) -> None:
        assert f"## {section}" in heartbeat_content

    def test_mentions_scheduling_engine(self, heartbeat_content: str) -> None:
        assert "scheduling engine" in heartbeat_content.lower()
