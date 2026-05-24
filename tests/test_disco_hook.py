"""Tests for disco_hook.py: pure functions and passthrough (no-activation) cases."""

import os
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import patch

from disco_config import DiscoConfig, DiscoVoice
from disco_hook import (
    DiscoHook,
    extract_task_context,
    extract_user_message,
)


# ---------------------------------------------------------------------------
# Shared helpers
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
# Pure function tests
# ---------------------------------------------------------------------------

class TestExtractUserMessage:
    def test_finds_latest_user_message(self) -> None:
        messages: list[dict[str, object]] = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "reply"},
            {"role": "user", "content": "second"},
        ]
        assert extract_user_message(messages) == "second"

    def test_empty_messages(self) -> None:
        assert extract_user_message([]) == ""

    def test_no_user_message(self) -> None:
        messages: list[dict[str, object]] = [
            {"role": "system", "content": "sys"},
        ]
        assert extract_user_message(messages) == ""

    def test_skips_whitespace_only(self) -> None:
        messages: list[dict[str, object]] = [
            {"role": "user", "content": "real"},
            {"role": "user", "content": "   "},
        ]
        assert extract_user_message(messages) == "real"


class TestExtractTaskContext:
    def test_no_messages(self) -> None:
        assert extract_task_context([]) == "N/A"

    def test_no_system_message(self) -> None:
        msgs: list[dict[str, object]] = [{"role": "user", "content": "hi"}]
        assert extract_task_context(msgs) == "N/A"

    def test_system_message_present(self) -> None:
        msgs: list[dict[str, object]] = [
            {"role": "system", "content": "Some system content"},
        ]
        assert extract_task_context(msgs) == "See system prompt"

    def test_empty_system_content(self) -> None:
        msgs: list[dict[str, object]] = [
            {"role": "system", "content": ""},
        ]
        assert extract_task_context(msgs) == "N/A"


# ---------------------------------------------------------------------------
# DiscoHook passthrough tests (disco should NOT activate)
# ---------------------------------------------------------------------------

class TestDiscoHookPassthrough:
    """Tests where disco should NOT activate -- content passes through."""

    def test_none_content_returns_none(self) -> None:
        config = _make_config()
        hook = DiscoHook(
            config=config,
            llm_call=FakeLLMCall(),
            get_cognitive_state=lambda: "avoidance",
        )
        ctx = _make_context_with_state("avoidance")
        with patch.dict(os.environ, {"VOICE_DISCO_ENABLED": "true"}):
            result = hook.finalize_content(ctx, None)  # type: ignore[arg-type]
        assert result is None

    def test_baseline_state_skips_disco(self) -> None:
        config = _make_config()
        hook = DiscoHook(
            config=config,
            llm_call=FakeLLMCall(),
            get_cognitive_state=lambda: "baseline",
        )
        ctx = _make_context_with_state("baseline")
        with patch.dict(os.environ, {"VOICE_DISCO_ENABLED": "true"}):
            result = hook.finalize_content(ctx, "Hello!")  # type: ignore[arg-type]
        assert result == "Hello!"

    def test_focus_state_skips_disco(self) -> None:
        config = _make_config()
        hook = DiscoHook(
            config=config,
            llm_call=FakeLLMCall(),
            get_cognitive_state=lambda: "focus",
        )
        ctx = _make_context_with_state("focus")
        with patch.dict(os.environ, {"VOICE_DISCO_ENABLED": "true"}):
            result = hook.finalize_content(ctx, "Focused response")  # type: ignore[arg-type]
        assert result == "Focused response"

    def test_hyperfocus_state_skips_disco(self) -> None:
        config = _make_config()
        hook = DiscoHook(
            config=config,
            llm_call=FakeLLMCall(),
            get_cognitive_state=lambda: "hyperfocus",
        )
        ctx = _make_context_with_state("hyperfocus")
        with patch.dict(os.environ, {"VOICE_DISCO_ENABLED": "true"}):
            result = hook.finalize_content(ctx, "Deep work")  # type: ignore[arg-type]
        assert result == "Deep work"

    def test_env_var_disabled_skips_disco(self) -> None:
        config = _make_config()
        hook = DiscoHook(
            config=config,
            llm_call=FakeLLMCall(),
            get_cognitive_state=lambda: "avoidance",
        )
        ctx = _make_context_with_state("avoidance")
        with patch.dict(os.environ, {"VOICE_DISCO_ENABLED": "false"}):
            result = hook.finalize_content(ctx, "Main response")  # type: ignore[arg-type]
        assert result == "Main response"

    def test_env_var_missing_skips_disco(self) -> None:
        config = _make_config()
        hook = DiscoHook(
            config=config,
            llm_call=FakeLLMCall(),
            get_cognitive_state=lambda: "avoidance",
        )
        ctx = _make_context_with_state("avoidance")
        with patch.dict(os.environ, {}, clear=True):
            result = hook.finalize_content(ctx, "Main response")  # type: ignore[arg-type]
        assert result == "Main response"
