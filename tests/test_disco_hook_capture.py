"""Tests for the DiscoHook on_comments capture seam (Cabinet voice buffer).

The capture must fire with the same comments that get prepended to chat, and
a default (None) sink must leave chat behavior exactly as before.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import patch

from disco_config import DiscoConfig, DiscoVoice
from disco_hook import DISCO_SEPARATOR, DiscoHook


def _voice(name: str, speaks: list[str]) -> DiscoVoice:
    return DiscoVoice(
        display_name=name, description="d", tone="t",
        speaks_when=speaks, example_lines=["x"],
    )


def _config() -> DiscoConfig:
    states = ["avoidance", "overwhelm", "rsd"]
    return DiscoConfig(
        enabled=True, activation_states=states, skip_intents=[],
        model="test/model", max_voices=3, first_voice="volition",
        voices={
            "volition": _voice("VOLITION", states),
            "empathy": _voice("EMPATHY", states),
            "logic": _voice("LOGIC", ["avoidance", "overwhelm"]),
        },
    )


@dataclass
class _Ctx:
    iteration: int = 1
    messages: list[dict[str, Any]] = field(default_factory=list)


def _ctx() -> _Ctx:
    return _Ctx(messages=[
        {"role": "system", "content": "soul"},
        {"role": "user", "content": "I can't start"},
    ])


class _FakeLLM:
    def __init__(self) -> None:
        self._n = 0

    async def __call__(self, prompt: str) -> str:
        self._n += 1
        if self._n == 1:
            return '{"comment": "Hold.", "difficulty": "Medium", "outcome": "Success", "next_voice": "empathy"}'
        if self._n == 2:
            return '{"comment": "Soft.", "difficulty": "Easy", "outcome": "Success", "next_voice": "logic"}'
        return '{"comment": "Three.", "difficulty": "Trivial", "outcome": "Success"}'


def test_on_comments_receives_fired_comments() -> None:
    captured: list[list[Any]] = []
    hook = DiscoHook(
        config=_config(),
        llm_call=_FakeLLM(),
        get_cognitive_state=lambda: "avoidance",
        on_comments=lambda comments: captured.append(comments),
    )
    with patch.dict(os.environ, {"VOICE_DISCO_ENABLED": "true"}):
        result = hook.finalize_content(_ctx(), "Main")  # type: ignore[arg-type]

    assert result is not None and "Main" in result          # chat unchanged
    assert len(captured) == 1
    fired = captured[0]
    assert [c.voice_name for c in fired] == ["volition", "empathy", "logic"]
    assert [c.comment for c in fired] == ["Hold.", "Soft.", "Three."]


def test_default_sink_none_preserves_behavior() -> None:
    hook = DiscoHook(
        config=_config(),
        llm_call=_FakeLLM(),
        get_cognitive_state=lambda: "avoidance",
    )
    with patch.dict(os.environ, {"VOICE_DISCO_ENABLED": "true"}):
        result = hook.finalize_content(_ctx(), "Main")  # type: ignore[arg-type]
    assert result is not None
    assert DISCO_SEPARATOR in result
    assert "Main" in result


def test_sink_error_does_not_break_chat() -> None:
    def boom(_comments: Any) -> None:
        raise RuntimeError("buffer write failed")

    hook = DiscoHook(
        config=_config(),
        llm_call=_FakeLLM(),
        get_cognitive_state=lambda: "avoidance",
        on_comments=boom,
    )
    with patch.dict(os.environ, {"VOICE_DISCO_ENABLED": "true"}):
        result = hook.finalize_content(_ctx(), "Main")  # type: ignore[arg-type]
    assert result is not None and "Main" in result  # chat survives sink error
