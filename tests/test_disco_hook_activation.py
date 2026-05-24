"""Tests for disco_hook.py: activation (prepending) and error handling."""

import os
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import patch

from disco_config import DiscoConfig, DiscoVoice
from disco_hook import DISCO_SEPARATOR, DiscoHook


# ---------------------------------------------------------------------------
# Shared helpers (duplicated from test_disco_hook.py for independence)
# ---------------------------------------------------------------------------

def _make_voice(
    display_name: str,
    speaks_when: list[str],
) -> DiscoVoice:
    return DiscoVoice(
        display_name=display_name,
        description="test voice",
        tone="test tone",
        speaks_when=speaks_when,
        example_lines=["test line"],
    )


def _make_config() -> DiscoConfig:
    return DiscoConfig(
        enabled=True,
        activation_states=["avoidance", "overwhelm", "rsd"],
        skip_intents=["list_tasks"],
        model="test/model",
        max_voices=3,
        first_voice="volition",
        voices={
            "volition": _make_voice("VOLITION", ["avoidance", "overwhelm", "rsd"]),
            "empathy": _make_voice("EMPATHY", ["rsd", "overwhelm", "avoidance"]),
            "logic": _make_voice("LOGIC", ["avoidance", "overwhelm"]),
        },
    )


@dataclass
class FakeHookContext:
    """Mimics AgentHookContext for testing finalize_content."""
    iteration: int = 1
    messages: list[dict[str, Any]] = field(default_factory=list)
    response: object = None
    usage: dict[str, int] = field(default_factory=dict)
    tool_calls: list[object] = field(default_factory=list)
    tool_results: list[object] = field(default_factory=list)
    tool_events: list[dict[str, str]] = field(default_factory=list)
    final_content: str | None = None
    stop_reason: str | None = None
    error: str | None = None


def _make_context_with_state(
    state: str,
    user_msg: str = "I can't start this task",
) -> FakeHookContext:
    system_content = (
        "# Soul\n\n## State-Aware Adaptation\n\n"
        f"[Current cognitive state: {state}]\n"
    )
    return FakeHookContext(
        messages=[
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_msg},
        ]
    )


class FakeLLMCall:
    """Returns canned JSON responses for each voice in the chain."""

    def __init__(self) -> None:
        self._call_count = 0

    async def __call__(self, prompt: str) -> str:
        self._call_count += 1
        if self._call_count == 1:
            return '{"comment": "Hold on.", "difficulty": "Medium", "outcome": "Success", "next_voice": "empathy"}'
        if self._call_count == 2:
            return '{"comment": "Feeling stuck.", "difficulty": "Easy", "outcome": "Success", "next_voice": "logic"}'
        return '{"comment": "Break it down.", "difficulty": "Trivial", "outcome": "Success"}'


# ---------------------------------------------------------------------------
# DiscoHook activation tests (disco SHOULD run and prepend output)
# ---------------------------------------------------------------------------

class TestDiscoHookActivation:
    """Tests where disco SHOULD activate and prepend output."""

    def test_avoidance_prepends_disco(self) -> None:
        config = _make_config()
        hook = DiscoHook(
            config=config,
            llm_call=FakeLLMCall(),
            get_cognitive_state=lambda: "avoidance",
        )
        ctx = _make_context_with_state("avoidance")
        with patch.dict(os.environ, {"VOICE_DISCO_ENABLED": "true"}):
            result = hook.finalize_content(ctx, "Main response here")  # type: ignore[arg-type]

        assert result is not None
        assert "Main response here" in result
        assert result.index("VOLITION") < result.index("Main response here")
        assert DISCO_SEPARATOR in result

    def test_overwhelm_prepends_disco(self) -> None:
        config = _make_config()
        hook = DiscoHook(
            config=config,
            llm_call=FakeLLMCall(),
            get_cognitive_state=lambda: "overwhelm",
        )
        ctx = _make_context_with_state("overwhelm")
        with patch.dict(os.environ, {"VOICE_DISCO_ENABLED": "true"}):
            result = hook.finalize_content(ctx, "Calm response")  # type: ignore[arg-type]

        assert result is not None
        assert "Calm response" in result
        assert "VOLITION" in result

    def test_rsd_prepends_disco(self) -> None:
        config = _make_config()
        hook = DiscoHook(
            config=config,
            llm_call=FakeLLMCall(),
            get_cognitive_state=lambda: "rsd",
        )
        ctx = _make_context_with_state("rsd")
        with patch.dict(os.environ, {"VOICE_DISCO_ENABLED": "true"}):
            result = hook.finalize_content(ctx, "Validating response")  # type: ignore[arg-type]

        assert result is not None
        assert "Validating response" in result
        assert "VOLITION" in result

    def test_main_response_not_modified(self) -> None:
        """The original response text is preserved exactly after the separator."""
        config = _make_config()
        hook = DiscoHook(
            config=config,
            llm_call=FakeLLMCall(),
            get_cognitive_state=lambda: "avoidance",
        )
        ctx = _make_context_with_state("avoidance")
        original = "This is the exact main response."
        with patch.dict(os.environ, {"VOICE_DISCO_ENABLED": "true"}):
            result = hook.finalize_content(ctx, original)  # type: ignore[arg-type]

        assert result is not None
        parts = result.split(DISCO_SEPARATOR)
        assert len(parts) == 2
        assert parts[1] == original

    def test_three_voices_in_output(self) -> None:
        config = _make_config()
        hook = DiscoHook(
            config=config,
            llm_call=FakeLLMCall(),
            get_cognitive_state=lambda: "avoidance",
        )
        ctx = _make_context_with_state("avoidance")
        with patch.dict(os.environ, {"VOICE_DISCO_ENABLED": "true"}):
            result = hook.finalize_content(ctx, "Response")  # type: ignore[arg-type]

        assert result is not None
        disco_part = result.split(DISCO_SEPARATOR)[0]
        assert "VOLITION" in disco_part
        assert "EMPATHY" in disco_part
        assert "LOGIC" in disco_part


# ---------------------------------------------------------------------------
# Error handling tests
# ---------------------------------------------------------------------------

class TestDiscoHookErrorHandling:
    """Tests that LLM failures return original content."""

    def test_llm_failure_returns_original(self) -> None:
        config = _make_config()

        async def failing_llm(prompt: str) -> str:
            raise RuntimeError("API error")

        hook = DiscoHook(
            config=config,
            llm_call=failing_llm,
            get_cognitive_state=lambda: "avoidance",
        )
        ctx = _make_context_with_state("avoidance")
        with patch.dict(os.environ, {"VOICE_DISCO_ENABLED": "true"}):
            result = hook.finalize_content(ctx, "Safe response")  # type: ignore[arg-type]

        assert result == "Safe response"
