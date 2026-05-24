"""Tests for voice trigger hook — pure functions."""

import pytest

from voice_trigger_hook import (
    build_voice_delivery_block,
    detect_buffer_alert_trigger,
    detect_checkin_trigger,
    inject_voice_block_into_prompt,
    is_voice_enabled,
    should_auto_voice,
)

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


# ---------------------------------------------------------------------------
# is_voice_enabled
# ---------------------------------------------------------------------------


class TestIsVoiceEnabled:

    def test_true_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VOICE_AUTO_ENABLED", "true")
        assert is_voice_enabled() is True

    def test_true_with_1(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VOICE_AUTO_ENABLED", "1")
        assert is_voice_enabled() is True

    def test_true_with_yes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VOICE_AUTO_ENABLED", "yes")
        assert is_voice_enabled() is True

    def test_true_case_insensitive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VOICE_AUTO_ENABLED", "TRUE")
        assert is_voice_enabled() is True

    def test_false_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("VOICE_AUTO_ENABLED", raising=False)
        assert is_voice_enabled() is False

    def test_false_with_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VOICE_AUTO_ENABLED", "")
        assert is_voice_enabled() is False

    def test_false_with_no(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VOICE_AUTO_ENABLED", "no")
        assert is_voice_enabled() is False

    def test_false_with_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VOICE_AUTO_ENABLED", "false")
        assert is_voice_enabled() is False


# ---------------------------------------------------------------------------
# should_auto_voice
# ---------------------------------------------------------------------------


class TestShouldAutoVoice:

    def test_baseline_checkin_allowed(self) -> None:
        assert should_auto_voice("baseline", "checkin") is True

    def test_avoidance_checkin_allowed(self) -> None:
        assert should_auto_voice("avoidance", "checkin") is True

    def test_focus_checkin_suppressed(self) -> None:
        assert should_auto_voice("focus", "checkin") is False

    def test_hyperfocus_checkin_suppressed(self) -> None:
        assert should_auto_voice("hyperfocus", "checkin") is False

    def test_overwhelm_checkin_suppressed(self) -> None:
        assert should_auto_voice("overwhelm", "checkin") is False

    def test_rsd_checkin_suppressed(self) -> None:
        assert should_auto_voice("rsd", "checkin") is False

    def test_baseline_buffer_allowed(self) -> None:
        assert should_auto_voice("baseline", "buffer_alert") is True

    def test_avoidance_buffer_suppressed(self) -> None:
        assert should_auto_voice("avoidance", "buffer_alert") is False

    def test_focus_buffer_suppressed(self) -> None:
        assert should_auto_voice("focus", "buffer_alert") is False

    def test_hyperfocus_buffer_suppressed(self) -> None:
        assert should_auto_voice("hyperfocus", "buffer_alert") is False

    def test_overwhelm_buffer_suppressed(self) -> None:
        assert should_auto_voice("overwhelm", "buffer_alert") is False

    def test_rsd_buffer_suppressed(self) -> None:
        assert should_auto_voice("rsd", "buffer_alert") is False

    def test_unknown_trigger_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown trigger_type"):
            should_auto_voice("baseline", "unknown_trigger")


# ---------------------------------------------------------------------------
# detect_checkin_trigger
# ---------------------------------------------------------------------------


class TestDetectCheckinTrigger:

    def test_detects_checkin_heading(self) -> None:
        content = SYSTEM_PROMPT + "\n\n" + CHECKIN_BLOCK
        assert detect_checkin_trigger(content) is True

    def test_no_checkin_heading(self) -> None:
        assert detect_checkin_trigger(SYSTEM_PROMPT) is False

    def test_empty_content(self) -> None:
        assert detect_checkin_trigger("") is False


# ---------------------------------------------------------------------------
# detect_buffer_alert_trigger
# ---------------------------------------------------------------------------


class TestDetectBufferAlertTrigger:

    def test_detects_buffer_heading(self) -> None:
        content = SYSTEM_PROMPT + "\n\n" + BUFFER_BLOCK
        assert detect_buffer_alert_trigger(content) is True

    def test_no_buffer_heading(self) -> None:
        assert detect_buffer_alert_trigger(SYSTEM_PROMPT) is False

    def test_empty_content(self) -> None:
        assert detect_buffer_alert_trigger("") is False


# ---------------------------------------------------------------------------
# build_voice_delivery_block
# ---------------------------------------------------------------------------


class TestBuildVoiceDeliveryBlock:

    def test_no_triggers_returns_empty(self) -> None:
        assert build_voice_delivery_block(False, False) == ""

    def test_checkin_only(self) -> None:
        result = build_voice_delivery_block(True, False)
        assert "## Voice Delivery" in result
        assert "Active Check-In" in result
        assert "Buffer Alert" not in result

    def test_buffer_only(self) -> None:
        result = build_voice_delivery_block(False, True)
        assert "## Voice Delivery" in result
        assert "Buffer Alert" in result
        assert "Active Check-In" not in result

    def test_both_triggers(self) -> None:
        result = build_voice_delivery_block(True, True)
        assert "Active Check-In" in result
        assert "Buffer Alert" in result

    def test_includes_speak_instruction(self) -> None:
        result = build_voice_delivery_block(True, False)
        assert "speak tool" in result

    def test_includes_no_markdown_instruction(self) -> None:
        result = build_voice_delivery_block(True, False)
        assert "No markdown" in result

    def test_includes_char_limit(self) -> None:
        result = build_voice_delivery_block(True, False)
        assert "500 characters" in result


# ---------------------------------------------------------------------------
# inject_voice_block_into_prompt
# ---------------------------------------------------------------------------


class TestInjectVoiceBlockIntoPrompt:

    def test_empty_block_returns_unchanged(self) -> None:
        result = inject_voice_block_into_prompt(SYSTEM_PROMPT, "")
        assert result == SYSTEM_PROMPT

    def test_appends_block(self) -> None:
        block = "## Voice Delivery\n\nSome instructions"
        result = inject_voice_block_into_prompt(SYSTEM_PROMPT, block)
        assert result.endswith(block)
        assert SYSTEM_PROMPT in result
        assert "\n\n## Voice Delivery" in result
