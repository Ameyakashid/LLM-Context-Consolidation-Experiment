"""Tests for disco_engine.py — prompt building and response parsing."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from disco_config import DiscoConfig, DiscoVoice
from disco_engine import (
    DiscoComment,
    build_voice_prompt,
    parse_voice_response,
)


def _make_voice(
    display_name: str,
    description: str,
    tone: str,
    speaks_when: list[str],
    example_lines: list[str],
) -> DiscoVoice:
    return DiscoVoice(
        display_name=display_name,
        description=description,
        tone=tone,
        speaks_when=speaks_when,
        example_lines=example_lines,
    )


@pytest.fixture()
def voices() -> dict[str, DiscoVoice]:
    return {
        "volition": _make_voice(
            display_name="VOLITION",
            description="Hold yourself together.",
            tone="Firm, grounded.",
            speaks_when=["avoidance", "overwhelm", "rsd"],
            example_lines=["You've done harder things.", "Do it tired."],
        ),
        "empathy": _make_voice(
            display_name="EMPATHY",
            description="Understand others.",
            tone="Warm, perceptive.",
            speaks_when=["rsd", "overwhelm", "avoidance"],
            example_lines=["Something's weighing on you."],
        ),
        "logic": _make_voice(
            display_name="LOGIC",
            description="Analyze everything.",
            tone="Analytical, precise.",
            speaks_when=["avoidance", "overwhelm"],
            example_lines=["The task is 30 minutes."],
        ),
        "inland_empire": _make_voice(
            display_name="INLAND EMPIRE",
            description="Gut feelings and dreams.",
            tone="Poetic, surreal.",
            speaks_when=["avoidance", "rsd"],
            example_lines=["The task isn't heavy."],
        ),
    }


@pytest.fixture()
def context() -> dict[str, str]:
    return {
        "user_message": "I can't start this task",
        "main_response": "Let's break it into steps.",
        "cognitive_state": "avoidance",
        "task_context": "Task: Write report, due tomorrow",
    }


class TestBuildVoicePrompt:
    def test_contains_identity(
        self, voices: dict[str, DiscoVoice], context: dict[str, str]
    ) -> None:
        prompt = build_voice_prompt(
            voice=voices["volition"], context=context, prior_comments=[],
            available_voices=["empathy", "logic", "inland_empire"], is_final=False,
        )
        assert "VOLITION" in prompt
        assert "Hold yourself together." in prompt
        assert "Firm, grounded." in prompt

    def test_contains_context(
        self, voices: dict[str, DiscoVoice], context: dict[str, str]
    ) -> None:
        prompt = build_voice_prompt(
            voice=voices["volition"], context=context, prior_comments=[],
            available_voices=["empathy", "logic"], is_final=False,
        )
        assert "I can't start this task" in prompt
        assert "Let's break it into steps." in prompt
        assert "avoidance" in prompt
        assert "Write report, due tomorrow" in prompt

    def test_contains_example_lines(
        self, voices: dict[str, DiscoVoice], context: dict[str, str]
    ) -> None:
        prompt = build_voice_prompt(
            voice=voices["volition"], context=context, prior_comments=[],
            available_voices=["empathy"], is_final=False,
        )
        assert "You've done harder things." in prompt
        assert "Do it tired." in prompt

    def test_contains_prior_comments(
        self, voices: dict[str, DiscoVoice], context: dict[str, str]
    ) -> None:
        prior = [DiscoComment(
            voice_name="volition", comment="Hold on.",
            difficulty="Medium", outcome="Success", next_voice="empathy",
        )]
        prompt = build_voice_prompt(
            voice=voices["empathy"], context=context, prior_comments=prior,
            available_voices=["logic", "inland_empire"], is_final=False,
        )
        assert "Previous voices have spoken" in prompt
        assert "VOLITION said:" in prompt
        assert "Hold on." in prompt

    def test_no_prior_comments_section_when_empty(
        self, voices: dict[str, DiscoVoice], context: dict[str, str]
    ) -> None:
        prompt = build_voice_prompt(
            voice=voices["volition"], context=context, prior_comments=[],
            available_voices=["empathy"], is_final=False,
        )
        assert "Previous voices have spoken" not in prompt

    def test_available_voices_listed(
        self, voices: dict[str, DiscoVoice], context: dict[str, str]
    ) -> None:
        prompt = build_voice_prompt(
            voice=voices["volition"], context=context, prior_comments=[],
            available_voices=["empathy", "logic", "inland_empire"], is_final=False,
        )
        assert "empathy" in prompt
        assert "logic" in prompt
        assert "inland_empire" in prompt
        assert "next_voice" in prompt

    def test_final_voice_no_next_voice(
        self, voices: dict[str, DiscoVoice], context: dict[str, str]
    ) -> None:
        prompt = build_voice_prompt(
            voice=voices["logic"], context=context, prior_comments=[],
            available_voices=[], is_final=True,
        )
        assert "next_voice" not in prompt

    def test_requests_json_format(
        self, voices: dict[str, DiscoVoice], context: dict[str, str]
    ) -> None:
        prompt = build_voice_prompt(
            voice=voices["volition"], context=context, prior_comments=[],
            available_voices=["empathy"], is_final=False,
        )
        assert "JSON" in prompt
        assert '"comment"' in prompt
        assert '"difficulty"' in prompt
        assert '"outcome"' in prompt


class TestParseVoiceResponse:
    def test_valid_json_non_final(self) -> None:
        raw = json.dumps({
            "comment": "You've done harder things.",
            "difficulty": "Medium", "outcome": "Success", "next_voice": "empathy",
        })
        result = parse_voice_response(raw_response=raw, voice_name="volition", is_final=False)
        assert result.voice_name == "volition"
        assert result.comment == "You've done harder things."
        assert result.difficulty == "Medium"
        assert result.outcome == "Success"
        assert result.next_voice == "empathy"

    def test_valid_json_final(self) -> None:
        raw = json.dumps({
            "comment": "The task is 30 minutes.", "difficulty": "Easy", "outcome": "Success",
        })
        result = parse_voice_response(raw_response=raw, voice_name="logic", is_final=True)
        assert result.voice_name == "logic"
        assert result.next_voice is None

    def test_final_ignores_next_voice(self) -> None:
        raw = json.dumps({
            "comment": "Something.", "difficulty": "Medium",
            "outcome": "Success", "next_voice": "empathy",
        })
        result = parse_voice_response(raw_response=raw, voice_name="logic", is_final=True)
        assert result.next_voice is None

    def test_malformed_json_raises(self) -> None:
        with pytest.raises(ValueError, match="malformed JSON"):
            parse_voice_response(raw_response="not json", voice_name="volition", is_final=False)

    def test_missing_comment_raises(self) -> None:
        raw = json.dumps({"difficulty": "Medium", "outcome": "Success"})
        with pytest.raises(ValueError, match="missing 'comment'"):
            parse_voice_response(raw_response=raw, voice_name="volition", is_final=False)

    def test_missing_difficulty_raises(self) -> None:
        raw = json.dumps({"comment": "Hello.", "outcome": "Success"})
        with pytest.raises(ValueError, match="missing 'difficulty'"):
            parse_voice_response(raw_response=raw, voice_name="volition", is_final=False)

    def test_missing_outcome_raises(self) -> None:
        raw = json.dumps({"comment": "Hello.", "difficulty": "Medium"})
        with pytest.raises(ValueError, match="missing 'outcome'"):
            parse_voice_response(raw_response=raw, voice_name="volition", is_final=False)

    def test_non_final_missing_next_voice_returns_none(self) -> None:
        raw = json.dumps({"comment": "Hello.", "difficulty": "Medium", "outcome": "Success"})
        result = parse_voice_response(raw_response=raw, voice_name="volition", is_final=False)
        assert result.next_voice is None

    def test_frozen_dataclass(self) -> None:
        raw = json.dumps({"comment": "Test.", "difficulty": "Easy", "outcome": "Success"})
        result = parse_voice_response(raw_response=raw, voice_name="logic", is_final=True)
        with pytest.raises(AttributeError):
            result.comment = "modified"  # type: ignore[misc]
