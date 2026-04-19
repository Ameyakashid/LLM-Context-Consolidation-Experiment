"""Tests for voice_tools module — SpeakTool and register_voice_tools."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from voice_tools import MAX_TEXT_LENGTH, SpeakTool, register_voice_tools


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


def _make_speak_tool() -> tuple[SpeakTool, AsyncMock]:
    """Create a SpeakTool with a mock MessageTool."""
    mock_message_tool = MagicMock()
    mock_message_tool.execute = AsyncMock(return_value="Message sent")
    tool = SpeakTool(message_tool=mock_message_tool)
    return tool, mock_message_tool.execute


# ---------------------------------------------------------------------------
# SpeakTool properties
# ---------------------------------------------------------------------------


class TestSpeakToolProperties:
    def test_name(self) -> None:
        tool, _ = _make_speak_tool()
        assert tool.name == "speak"

    def test_description_mentions_voice(self) -> None:
        tool, _ = _make_speak_tool()
        assert "voice" in tool.description.lower()

    def test_description_mentions_max_length(self) -> None:
        tool, _ = _make_speak_tool()
        assert str(MAX_TEXT_LENGTH) in tool.description

    def test_has_parameters_schema(self) -> None:
        tool, _ = _make_speak_tool()
        params = tool.parameters
        assert "properties" in params
        assert "text" in params["properties"]


# ---------------------------------------------------------------------------
# SpeakTool.execute — error paths
# ---------------------------------------------------------------------------


class TestSpeakToolErrors:
    def test_empty_text_returns_error(self) -> None:
        tool, mock_execute = _make_speak_tool()
        result = _run(tool.execute(text=""))
        assert "Error" in result
        mock_execute.assert_not_called()

    def test_whitespace_only_returns_error(self) -> None:
        tool, mock_execute = _make_speak_tool()
        result = _run(tool.execute(text="   \n\t  "))
        assert "Error" in result
        mock_execute.assert_not_called()

    @patch("voice_tools.synthesize_speech", side_effect=FileNotFoundError("model missing"))
    def test_tts_unavailable_returns_error(self, _mock_synth: MagicMock) -> None:
        tool, mock_execute = _make_speak_tool()
        result = _run(tool.execute(text="hello"))
        assert "Error" in result
        assert "TTS engine unavailable" in result
        mock_execute.assert_not_called()

    @patch("voice_tools.synthesize_speech", side_effect=ValueError("bad input"))
    def test_synthesis_value_error_returns_error(self, _mock_synth: MagicMock) -> None:
        tool, mock_execute = _make_speak_tool()
        result = _run(tool.execute(text="hello"))
        assert "Error" in result
        mock_execute.assert_not_called()

    @patch("voice_tools.synthesize_speech", return_value=b"fakewav")
    @patch("voice_tools.convert_wav_to_ogg", side_effect=RuntimeError("codec fail"))
    def test_conversion_failure_returns_error(
        self, _mock_conv: MagicMock, _mock_synth: MagicMock
    ) -> None:
        tool, mock_execute = _make_speak_tool()
        result = _run(tool.execute(text="hello"))
        assert "Error" in result
        assert "Audio conversion failed" in result
        mock_execute.assert_not_called()


# ---------------------------------------------------------------------------
# SpeakTool.execute — happy path
# ---------------------------------------------------------------------------


class TestSpeakToolHappyPath:
    @patch("voice_tools.cleanup_temp_file")
    @patch("voice_tools.save_temp_ogg", return_value=Path("/tmp/voice_abc.ogg"))
    @patch("voice_tools.convert_wav_to_ogg", return_value=b"OggSfakedata")
    @patch("voice_tools.synthesize_speech", return_value=b"WAVfakedata")
    def test_full_pipeline_calls_message_tool(
        self,
        mock_synth: MagicMock,
        mock_convert: MagicMock,
        mock_save: MagicMock,
        mock_cleanup: MagicMock,
    ) -> None:
        tool, mock_execute = _make_speak_tool()
        result = _run(tool.execute(text="Hello world"))

        mock_synth.assert_called_once()
        mock_convert.assert_called_once_with(b"WAVfakedata")
        mock_save.assert_called_once_with(b"OggSfakedata")
        mock_execute.assert_called_once()
        mock_cleanup.assert_called_once_with(Path("/tmp/voice_abc.ogg"))
        assert result == "Message sent"

    @patch("voice_tools.cleanup_temp_file")
    @patch("voice_tools.save_temp_ogg", return_value=Path("/tmp/voice_abc.ogg"))
    @patch("voice_tools.convert_wav_to_ogg", return_value=b"OggSfakedata")
    @patch("voice_tools.synthesize_speech", return_value=b"WAVfakedata")
    def test_sends_ogg_path_as_media(
        self,
        _mock_synth: MagicMock,
        _mock_convert: MagicMock,
        _mock_save: MagicMock,
        _mock_cleanup: MagicMock,
    ) -> None:
        tool, mock_execute = _make_speak_tool()
        _run(tool.execute(text="Hello"))

        call_kwargs = mock_execute.call_args
        assert str(Path("/tmp/voice_abc.ogg")) in call_kwargs.kwargs.get(
            "media", call_kwargs.args[1] if len(call_kwargs.args) > 1 else []
        )

    @patch("voice_tools.cleanup_temp_file")
    @patch("voice_tools.save_temp_ogg", return_value=Path("/tmp/voice_abc.ogg"))
    @patch("voice_tools.convert_wav_to_ogg", return_value=b"OggSfakedata")
    @patch("voice_tools.synthesize_speech", return_value=b"WAVfakedata")
    def test_uses_default_voice_and_speed(
        self,
        mock_synth: MagicMock,
        _mock_convert: MagicMock,
        _mock_save: MagicMock,
        _mock_cleanup: MagicMock,
    ) -> None:
        tool, _ = _make_speak_tool()
        _run(tool.execute(text="Test"))

        call_kwargs = mock_synth.call_args.kwargs
        assert call_kwargs["voice"] == "af_heart"
        assert call_kwargs["speed"] == 1.0

    @patch("voice_tools.cleanup_temp_file")
    @patch("voice_tools.save_temp_ogg", return_value=Path("/tmp/voice_abc.ogg"))
    @patch("voice_tools.convert_wav_to_ogg", return_value=b"OggSfakedata")
    @patch("voice_tools.synthesize_speech", return_value=b"WAVfakedata")
    def test_custom_voice_and_speed(
        self,
        mock_synth: MagicMock,
        _mock_convert: MagicMock,
        _mock_save: MagicMock,
        _mock_cleanup: MagicMock,
    ) -> None:
        tool, _ = _make_speak_tool()
        _run(tool.execute(text="Test", voice="am_adam", speed=1.5))

        call_kwargs = mock_synth.call_args.kwargs
        assert call_kwargs["voice"] == "am_adam"
        assert call_kwargs["speed"] == 1.5


# ---------------------------------------------------------------------------
# Text truncation
# ---------------------------------------------------------------------------


class TestTextTruncation:
    @patch("voice_tools.cleanup_temp_file")
    @patch("voice_tools.save_temp_ogg", return_value=Path("/tmp/voice_abc.ogg"))
    @patch("voice_tools.convert_wav_to_ogg", return_value=b"OggSfakedata")
    @patch("voice_tools.synthesize_speech", return_value=b"WAVfakedata")
    def test_long_text_is_truncated(
        self,
        mock_synth: MagicMock,
        _mock_convert: MagicMock,
        _mock_save: MagicMock,
        _mock_cleanup: MagicMock,
    ) -> None:
        long_text = "A" * (MAX_TEXT_LENGTH + 200)
        tool, _ = _make_speak_tool()
        _run(tool.execute(text=long_text))

        synthesized_text = mock_synth.call_args.kwargs["text"]
        assert len(synthesized_text) == MAX_TEXT_LENGTH

    @patch("voice_tools.cleanup_temp_file")
    @patch("voice_tools.save_temp_ogg", return_value=Path("/tmp/voice_abc.ogg"))
    @patch("voice_tools.convert_wav_to_ogg", return_value=b"OggSfakedata")
    @patch("voice_tools.synthesize_speech", return_value=b"WAVfakedata")
    def test_text_at_limit_not_truncated(
        self,
        mock_synth: MagicMock,
        _mock_convert: MagicMock,
        _mock_save: MagicMock,
        _mock_cleanup: MagicMock,
    ) -> None:
        exact_text = "B" * MAX_TEXT_LENGTH
        tool, _ = _make_speak_tool()
        _run(tool.execute(text=exact_text))

        synthesized_text = mock_synth.call_args.kwargs["text"]
        assert len(synthesized_text) == MAX_TEXT_LENGTH


# ---------------------------------------------------------------------------
# Temp file cleanup on send failure
# ---------------------------------------------------------------------------


class TestTempFileCleanup:
    @patch("voice_tools.cleanup_temp_file")
    @patch("voice_tools.save_temp_ogg", return_value=Path("/tmp/voice_abc.ogg"))
    @patch("voice_tools.convert_wav_to_ogg", return_value=b"OggSfakedata")
    @patch("voice_tools.synthesize_speech", return_value=b"WAVfakedata")
    def test_cleanup_on_send_failure(
        self,
        _mock_synth: MagicMock,
        _mock_convert: MagicMock,
        _mock_save: MagicMock,
        mock_cleanup: MagicMock,
    ) -> None:
        tool, mock_execute = _make_speak_tool()
        mock_execute.side_effect = RuntimeError("send failed")

        with pytest.raises(RuntimeError, match="send failed"):
            _run(tool.execute(text="hello"))

        mock_cleanup.assert_called_once_with(Path("/tmp/voice_abc.ogg"))


# ---------------------------------------------------------------------------
# register_voice_tools
# ---------------------------------------------------------------------------


class TestRegisterVoiceTools:
    def test_registers_speak_tool(self) -> None:
        mock_registry = MagicMock()
        mock_message_tool = MagicMock()

        count = register_voice_tools(mock_registry, mock_message_tool)

        assert count == 1
        mock_registry.register.assert_called_once()
        registered_tool = mock_registry.register.call_args[0][0]
        assert isinstance(registered_tool, SpeakTool)
        assert registered_tool.name == "speak"
