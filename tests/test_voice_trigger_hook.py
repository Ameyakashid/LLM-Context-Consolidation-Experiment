"""Tests for voice trigger hook — VoiceHook lifecycle tests."""

import asyncio
from unittest.mock import MagicMock

import pytest

from voice_trigger_hook import VoiceHook

SYSTEM_PROMPT = "# Soul\n\nYou are an assistant."

CHECKIN_BLOCK = (
    "## Active Check-In: Morning Motivation\n\n"
    "Action: fire (scheduled)\n\n"
    "Deliver this check-in now."
)

BUFFER_BLOCK = (
    "## Buffer Alerts\n\n"
    "- Rent: 1/4 (due 2026-04-10, every 30 days)"
)


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


def _make_context(system_content: str) -> MagicMock:
    ctx = MagicMock()
    ctx.messages = [{"role": "system", "content": system_content}]
    return ctx


def _make_hook(
    is_scheduled: bool,
    state: str = "baseline",
) -> VoiceHook:
    return VoiceHook(
        is_scheduled_session=lambda: is_scheduled,
        get_cognitive_state=lambda: state,
    )


# ---------------------------------------------------------------------------
# VoiceHook — guards
# ---------------------------------------------------------------------------


class TestVoiceHookGuards:

    def test_empty_messages_is_noop(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("VOICE_AUTO_ENABLED", "true")
        hook = _make_hook(is_scheduled=True)
        ctx = MagicMock()
        ctx.messages = []
        _run(hook.before_iteration(ctx))
        assert ctx.messages == []

    def test_not_scheduled_is_noop(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("VOICE_AUTO_ENABLED", "true")
        hook = _make_hook(is_scheduled=False)
        content = SYSTEM_PROMPT + "\n\n" + CHECKIN_BLOCK
        ctx = _make_context(content)
        _run(hook.before_iteration(ctx))
        assert "Voice Delivery" not in ctx.messages[0]["content"]

    def test_no_system_message_is_noop(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("VOICE_AUTO_ENABLED", "true")
        hook = _make_hook(is_scheduled=True)
        ctx = MagicMock()
        ctx.messages = [{"role": "user", "content": "hello"}]
        _run(hook.before_iteration(ctx))
        assert "Voice Delivery" not in ctx.messages[0]["content"]

    def test_voice_disabled_is_noop(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("VOICE_AUTO_ENABLED", raising=False)
        hook = _make_hook(is_scheduled=True)
        content = SYSTEM_PROMPT + "\n\n" + CHECKIN_BLOCK
        ctx = _make_context(content)
        _run(hook.before_iteration(ctx))
        assert "Voice Delivery" not in ctx.messages[0]["content"]

    def test_exception_caught_and_logged(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("VOICE_AUTO_ENABLED", "true")
        hook = _make_hook(is_scheduled=True)
        ctx = MagicMock()
        ctx.messages = None  # will cause TypeError in _process
        _run(hook.before_iteration(ctx))  # should not raise


# ---------------------------------------------------------------------------
# VoiceHook — trigger injection
# ---------------------------------------------------------------------------


class TestVoiceHookInjection:

    def test_checkin_trigger_injects_voice_block(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("VOICE_AUTO_ENABLED", "true")
        hook = _make_hook(is_scheduled=True, state="baseline")
        content = SYSTEM_PROMPT + "\n\n" + CHECKIN_BLOCK
        ctx = _make_context(content)
        _run(hook.before_iteration(ctx))
        assert "## Voice Delivery" in ctx.messages[0]["content"]
        assert "Active Check-In" in ctx.messages[0]["content"]

    def test_buffer_trigger_injects_voice_block(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("VOICE_AUTO_ENABLED", "true")
        hook = _make_hook(is_scheduled=True, state="baseline")
        content = SYSTEM_PROMPT + "\n\n" + BUFFER_BLOCK
        ctx = _make_context(content)
        _run(hook.before_iteration(ctx))
        assert "## Voice Delivery" in ctx.messages[0]["content"]
        assert "Buffer Alert" in ctx.messages[0]["content"]

    def test_both_triggers_inject_combined_block(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("VOICE_AUTO_ENABLED", "true")
        hook = _make_hook(is_scheduled=True, state="baseline")
        content = SYSTEM_PROMPT + "\n\n" + CHECKIN_BLOCK + "\n\n" + BUFFER_BLOCK
        ctx = _make_context(content)
        _run(hook.before_iteration(ctx))
        result = ctx.messages[0]["content"]
        assert "Active Check-In" in result
        assert "Buffer Alert" in result

    def test_no_triggers_is_noop(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("VOICE_AUTO_ENABLED", "true")
        hook = _make_hook(is_scheduled=True, state="baseline")
        ctx = _make_context(SYSTEM_PROMPT)
        _run(hook.before_iteration(ctx))
        assert "Voice Delivery" not in ctx.messages[0]["content"]


# ---------------------------------------------------------------------------
# VoiceHook — state suppression
# ---------------------------------------------------------------------------


class TestVoiceHookStateSuppression:

    def test_hyperfocus_suppresses_checkin(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("VOICE_AUTO_ENABLED", "true")
        hook = _make_hook(is_scheduled=True, state="hyperfocus")
        content = SYSTEM_PROMPT + "\n\n" + CHECKIN_BLOCK
        ctx = _make_context(content)
        _run(hook.before_iteration(ctx))
        assert "Voice Delivery" not in ctx.messages[0]["content"]

    def test_focus_suppresses_buffer(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("VOICE_AUTO_ENABLED", "true")
        hook = _make_hook(is_scheduled=True, state="focus")
        content = SYSTEM_PROMPT + "\n\n" + BUFFER_BLOCK
        ctx = _make_context(content)
        _run(hook.before_iteration(ctx))
        assert "Voice Delivery" not in ctx.messages[0]["content"]

    def test_avoidance_allows_checkin_suppresses_buffer(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("VOICE_AUTO_ENABLED", "true")
        hook = _make_hook(is_scheduled=True, state="avoidance")
        content = SYSTEM_PROMPT + "\n\n" + CHECKIN_BLOCK + "\n\n" + BUFFER_BLOCK
        ctx = _make_context(content)
        _run(hook.before_iteration(ctx))
        result = ctx.messages[0]["content"]
        voice_section = result.split("## Voice Delivery")[1]
        assert "Active Check-In" in voice_section
        assert "Buffer Alert" not in voice_section

    def test_overwhelm_suppresses_all(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("VOICE_AUTO_ENABLED", "true")
        hook = _make_hook(is_scheduled=True, state="overwhelm")
        content = SYSTEM_PROMPT + "\n\n" + CHECKIN_BLOCK + "\n\n" + BUFFER_BLOCK
        ctx = _make_context(content)
        _run(hook.before_iteration(ctx))
        assert "Voice Delivery" not in ctx.messages[0]["content"]

    def test_rsd_suppresses_all(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("VOICE_AUTO_ENABLED", "true")
        hook = _make_hook(is_scheduled=True, state="rsd")
        content = SYSTEM_PROMPT + "\n\n" + CHECKIN_BLOCK + "\n\n" + BUFFER_BLOCK
        ctx = _make_context(content)
        _run(hook.before_iteration(ctx))
        assert "Voice Delivery" not in ctx.messages[0]["content"]
