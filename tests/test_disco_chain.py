"""Tests for disco_engine.py — chain execution and output formatting."""

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from disco_config import DiscoConfig, DiscoVoice
from disco_engine import DiscoComment, LLMCallable, format_disco_output, run_disco_chain


_STATES = ["avoidance", "overwhelm", "rsd"]


def _v(display_name: str, speaks_when: list[str]) -> DiscoVoice:
    return DiscoVoice(
        display_name=display_name, description=f"{display_name} desc.",
        tone=f"{display_name} tone.", speaks_when=speaks_when,
        example_lines=[f"{display_name} example."],
    )


@pytest.fixture()
def voices() -> dict[str, DiscoVoice]:
    return {
        "volition": _v("VOLITION", _STATES),
        "empathy": _v("EMPATHY", _STATES),
        "logic": _v("LOGIC", ["avoidance", "overwhelm"]),
        "inland_empire": _v("INLAND EMPIRE", ["avoidance", "rsd"]),
    }


@pytest.fixture()
def config(voices: dict[str, DiscoVoice]) -> DiscoConfig:
    return DiscoConfig(
        enabled=True, activation_states=["avoidance", "overwhelm", "rsd"],
        skip_intents=["list_tasks"], model="anthropic/claude-3-haiku",
        max_voices=3, first_voice="volition", voices=voices,
    )


_CTX = {
    "user_message": "I can't start this task",
    "main_response": "Let's break it into steps.",
    "cognitive_state": "avoidance",
    "task_context": "Task: Write report, due tomorrow",
}


def _resp(comment: str, difficulty: str, outcome: str, next_voice: str | None = None) -> str:
    data: dict[str, str] = {"comment": comment, "difficulty": difficulty, "outcome": outcome}
    if next_voice is not None:
        data["next_voice"] = next_voice
    return json.dumps(data)


def _run(config: DiscoConfig, llm_call: LLMCallable) -> list[DiscoComment]:
    return asyncio.run(run_disco_chain(
        main_response=_CTX["main_response"], user_message=_CTX["user_message"],
        cognitive_state=_CTX["cognitive_state"], task_context=_CTX["task_context"],
        config=config, llm_call=llm_call,
    ))


class TestRunDiscoChain:
    def test_produces_3_comments(self, config: DiscoConfig) -> None:
        call_count = 0

        async def mock_llm(prompt: str) -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _resp("Hold on.", "Medium", "Success", "empathy")
            if call_count == 2:
                return _resp("Feel it.", "Easy", "Success", "logic")
            return _resp("30 minutes.", "Trivial", "Success")

        result = _run(config, mock_llm)
        assert len(result) == 3
        assert call_count == 3

    def test_starts_with_volition(self, config: DiscoConfig) -> None:
        async def mock_llm(prompt: str) -> str:
            return _resp("Test.", "Medium", "Success", "empathy")

        result = _run(config, mock_llm)
        assert result[0].voice_name == "volition"

    def test_voice_selection_follows_chain(self, config: DiscoConfig) -> None:
        call_count = 0

        async def mock_llm(prompt: str) -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _resp("First.", "Medium", "Success", "logic")
            if call_count == 2:
                return _resp("Second.", "Easy", "Success", "inland_empire")
            return _resp("Third.", "Heroic", "Failure")

        result = _run(config, mock_llm)
        assert [c.voice_name for c in result] == ["volition", "logic", "inland_empire"]

    def test_failure_mid_chain_returns_partial(self, config: DiscoConfig) -> None:
        call_count = 0

        async def mock_llm(prompt: str) -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _resp("First.", "Medium", "Success", "empathy")
            raise RuntimeError("LLM provider down")

        result = _run(config, mock_llm)
        assert len(result) == 1
        assert result[0].voice_name == "volition"

    def test_failure_on_first_returns_empty(self, config: DiscoConfig) -> None:
        async def mock_llm(prompt: str) -> str:
            raise RuntimeError("LLM provider down")

        assert len(_run(config, mock_llm)) == 0

    def test_invalid_next_voice_fallback(self, config: DiscoConfig) -> None:
        call_count = 0

        async def mock_llm(prompt: str) -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _resp("First.", "Medium", "Success", "nonexistent_voice")
            if call_count == 2:
                return _resp("Second.", "Easy", "Success", "logic")
            return _resp("Third.", "Trivial", "Success")

        result = _run(config, mock_llm)
        assert len(result) == 3
        assert result[1].voice_name == "empathy"

    def test_malformed_json_stops_chain(self, config: DiscoConfig) -> None:
        call_count = 0

        async def mock_llm(prompt: str) -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _resp("First.", "Medium", "Success", "empathy")
            return "This is not valid JSON {{{broken"

        assert len(_run(config, mock_llm)) == 1

    def test_already_spoken_voice_fallback(self, config: DiscoConfig) -> None:
        call_count = 0

        async def mock_llm(prompt: str) -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _resp("First.", "Medium", "Success", "empathy")
            if call_count == 2:
                return _resp("Second.", "Easy", "Success", "volition")
            return _resp("Third.", "Trivial", "Success")

        result = _run(config, mock_llm)
        assert len(result) == 3
        assert result[2].voice_name != "volition"
        assert result[2].voice_name != "empathy"


class TestFormatDiscoOutput:
    def test_single_comment(self, config: DiscoConfig) -> None:
        comments = [DiscoComment(
            voice_name="volition", comment="Hold on.",
            difficulty="Medium", outcome="Success", next_voice="empathy",
        )]
        result = format_disco_output(comments=comments, config=config)
        assert result == '*VOLITION [Medium: Success] \u2014 "Hold on."*'

    def test_full_chain(self, config: DiscoConfig) -> None:
        comments = [
            DiscoComment(voice_name="volition", comment="Hold on.",
                         difficulty="Medium", outcome="Success", next_voice="empathy"),
            DiscoComment(voice_name="empathy", comment="Feel it.",
                         difficulty="Easy", outcome="Success", next_voice="logic"),
            DiscoComment(voice_name="logic", comment="30 minutes.",
                         difficulty="Trivial", outcome="Success", next_voice=None),
        ]
        result = format_disco_output(comments=comments, config=config)
        lines = result.split("\n")
        assert len(lines) == 3
        assert "VOLITION" in lines[0]
        assert "EMPATHY" in lines[1]
        assert "LOGIC" in lines[2]

    def test_empty_list(self, config: DiscoConfig) -> None:
        assert format_disco_output(comments=[], config=config) == ""

    def test_uses_display_name(self, config: DiscoConfig) -> None:
        comments = [DiscoComment(
            voice_name="inland_empire", comment="Dreams.",
            difficulty="Heroic", outcome="Failure", next_voice=None,
        )]
        result = format_disco_output(comments=comments, config=config)
        assert "INLAND EMPIRE" in result
        assert "inland_empire" not in result

    def test_skips_empty_comment(self, config: DiscoConfig) -> None:
        comments = [DiscoComment(
            voice_name="volition", comment="",
            difficulty="Medium", outcome="Success", next_voice=None,
        )]
        assert format_disco_output(comments=comments, config=config) == ""

    def test_format_uses_em_dash(self, config: DiscoConfig) -> None:
        comments = [DiscoComment(
            voice_name="volition", comment="Test.",
            difficulty="Easy", outcome="Success", next_voice=None,
        )]
        result = format_disco_output(comments=comments, config=config)
        assert "\u2014" in result
