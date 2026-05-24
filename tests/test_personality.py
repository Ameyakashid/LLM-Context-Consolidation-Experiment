"""Tests for SOUL.md and USER.md personality content."""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SOUL_PATH = REPO_ROOT / "workspace" / "SOUL.md"
USER_PATH = REPO_ROOT / "workspace" / "USER.md"


@pytest.fixture(scope="module")
def soul_content() -> str:
    return SOUL_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def user_content() -> str:
    return USER_PATH.read_text(encoding="utf-8")


class TestSoulRequiredSections:
    """SOUL.md must contain all required section headings."""

    REQUIRED_HEADINGS = [
        "Voice and Tone",
        "Neuroaffirming Rules",
        "ICNU Motivation Framework",
        "Communication Style",
        "Boundaries",
        "State-Aware Adaptation",
        "Disco Flavor Layer",
    ]

    @pytest.mark.parametrize("heading", REQUIRED_HEADINGS)
    def test_soul_has_required_heading(
        self, soul_content: str, heading: str
    ) -> None:
        pattern = rf"^##\s+{re.escape(heading)}"
        assert re.search(pattern, soul_content, re.MULTILINE), (
            f"SOUL.md missing required section: '## {heading}'"
        )


class TestSoulBannedPatterns:
    """SOUL.md must document banned phrases in the Never Say section."""

    BANNED_ROOTS = [
        "you should",
        "just do it",
        "just focus",
        "it's easy",
        "it's simple",
        "why didn't you",
        "why can't you",
        "you forgot again",
        "try harder",
        "I already told you",
        "all you have to do",
    ]

    @pytest.mark.parametrize("phrase", BANNED_ROOTS)
    def test_banned_phrase_documented(
        self, soul_content: str, phrase: str
    ) -> None:
        assert phrase.lower() in soul_content.lower(), (
            f"SOUL.md does not document banned phrase: '{phrase}'"
        )


class TestSoulNoBannedPatternsInAlternatives:
    """The 'Say This Instead' section must not accidentally use banned language."""

    def test_alternatives_section_clean(self, soul_content: str) -> None:
        alternatives_match = re.search(
            r"### Say This Instead\n(.*?)(?=\n##|\Z)",
            soul_content,
            re.DOTALL,
        )
        assert alternatives_match, "SOUL.md missing '### Say This Instead' section"
        alternatives_text = alternatives_match.group(1).lower()

        banned_as_instruction = [
            r"(?<!not\s\")you should(?!\")",
            r"(?<!not\s\")just do it(?!\")",
            r"(?<!not\s\")try harder(?!\")",
        ]
        for pattern in banned_as_instruction:
            matches = re.findall(pattern, alternatives_text)
            assert not matches, (
                f"SOUL.md alternatives section uses banned phrase matching: {pattern}"
            )


class TestSoulIcnuFramework:
    """SOUL.md must define all four ICNU motivation channels."""

    ICNU_CHANNELS = ["Interest", "Challenge", "Novelty", "Urgency"]

    @pytest.mark.parametrize("channel", ICNU_CHANNELS)
    def test_icnu_channel_present(
        self, soul_content: str, channel: str
    ) -> None:
        assert f"**{channel}**" in soul_content, (
            f"SOUL.md missing ICNU channel: {channel}"
        )


class TestUserRequiredSections:
    """USER.md must contain AUDHD-relevant section headings."""

    REQUIRED_HEADINGS = [
        "Executive Function Challenges",
        "Time Blindness",
        "Rejection Sensitivity",
        "Hyperfocus Patterns",
        "AUDHD-Specific Considerations",
    ]

    @pytest.mark.parametrize("heading", REQUIRED_HEADINGS)
    def test_user_has_required_heading(
        self, user_content: str, heading: str
    ) -> None:
        pattern = rf"^##\s+{re.escape(heading)}"
        assert re.search(pattern, user_content, re.MULTILINE), (
            f"USER.md missing required section: '## {heading}'"
        )


class TestUserAudhdContent:
    """USER.md must reference AUDHD and key executive function topics."""

    def test_mentions_audhd(self, user_content: str) -> None:
        assert "AUDHD" in user_content, (
            "USER.md must mention AUDHD (ADHD + autism)"
        )

    def test_mentions_initiation(self, user_content: str) -> None:
        assert "initiation" in user_content.lower(), (
            "USER.md must address task initiation difficulty"
        )

    def test_mentions_working_memory(self, user_content: str) -> None:
        assert "working memory" in user_content.lower(), (
            "USER.md must address working memory challenges"
        )

    def test_mentions_time_blindness(self, user_content: str) -> None:
        assert "time blindness" in user_content.lower(), (
            "USER.md must address time blindness"
        )

    def test_mentions_rejection_sensitivity(self, user_content: str) -> None:
        assert "rejection sensitivity" in user_content.lower(), (
            "USER.md must address rejection sensitivity"
        )

    def test_mentions_sensory(self, user_content: str) -> None:
        assert "sensory" in user_content.lower(), (
            "USER.md must address sensory considerations for autism"
        )


class TestNoBannedLanguageInUserMd:
    """USER.md itself must not use banned neuroaffirming language."""

    BANNED_PHRASES = [
        "you should",
        "just focus",
        "it's easy",
        "it's simple",
        "try harder",
        "normal people",
    ]

    @pytest.mark.parametrize("phrase", BANNED_PHRASES)
    def test_user_md_avoids_banned_phrase(
        self, user_content: str, phrase: str
    ) -> None:
        assert phrase.lower() not in user_content.lower(), (
            f"USER.md uses banned phrase: '{phrase}'"
        )
