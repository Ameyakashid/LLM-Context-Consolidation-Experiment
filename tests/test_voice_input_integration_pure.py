"""Pure unit tests for voice_input_integration.py — no I/O, no network."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Coroutine, Literal, TypeVar

import httpx
import pytest

import voice_input_integration
from transcription_backend import TranscriptionResult
from voice_input_integration import (
    DEFAULT_MAX_VOICE_DURATION_SECONDS,
    ERROR_LOG_INTERVAL,
    FAILED_MARKER,
    LOW_CONFIDENCE_PREFIX,
    OVER_DURATION_MARKER_TEMPLATE,
    VOICE_BYTES_PER_SECOND,
    estimate_audio_duration_seconds,
    install_voice_transcription,
    is_voice_input_enabled,
    render_duration_rejection,
    render_transcription_text,
    resolve_max_voice_duration,
)

T = TypeVar("T")
_BACKEND_LITERAL: Literal["local_faster_whisper"] = "local_faster_whisper"


def _run(coro: Coroutine[object, object, T]) -> T:
    return asyncio.run(coro)


def _result(text: str, confidence: float | None) -> TranscriptionResult:
    return TranscriptionResult(
        text=text, confidence=confidence, language="en",
        duration_seconds=1.0, backend_name=_BACKEND_LITERAL,
    )


def _make_audio(tmp_path: Path, size_bytes: int = 1024) -> Path:
    path = tmp_path / "voice.ogg"
    path.write_bytes(b"x" * size_bytes)
    return path


@pytest.fixture(autouse=True)
def _clear_rate_limit_state() -> None:
    voice_input_integration._reset_rate_limit_state()


@pytest.mark.parametrize("raw,expected", [
    (None, False), ("true", True), ("TRUE", True), ("  true  ", True),
    ("false", False), ("1", False), ("yes", False), ("on", False),
])
def test_is_voice_input_enabled_matrix(raw: str | None, expected: bool) -> None:
    env: dict[str, str] = {} if raw is None else {"VOICE_INPUT_ENABLED": raw}
    assert is_voice_input_enabled(env) is expected


class TestResolveMaxVoiceDuration:
    def test_default_when_unset(self) -> None:
        assert resolve_max_voice_duration({}) == DEFAULT_MAX_VOICE_DURATION_SECONDS

    @pytest.mark.parametrize("raw", ["", "   "])
    def test_default_when_blank(self, raw: str) -> None:
        env = {"MAX_VOICE_DURATION_SECONDS": raw}
        assert resolve_max_voice_duration(env) == DEFAULT_MAX_VOICE_DURATION_SECONDS

    def test_override_positive(self) -> None:
        assert resolve_max_voice_duration({"MAX_VOICE_DURATION_SECONDS": "300"}) == 300

    @pytest.mark.parametrize("raw,expected", [("0", 1), ("-30", 1)])
    def test_clamps_non_positive_to_one(self, raw: str, expected: int) -> None:
        assert resolve_max_voice_duration({"MAX_VOICE_DURATION_SECONDS": raw}) == expected

    def test_non_int_raises(self) -> None:
        with pytest.raises(ValueError, match="must be an integer"):
            resolve_max_voice_duration({"MAX_VOICE_DURATION_SECONDS": "fast"})


class TestRenderTranscriptionText:
    def test_high_confidence_returns_raw_text(self) -> None:
        assert render_transcription_text(_result("hello world", 0.9), 0.4) == "hello world"

    def test_low_confidence_prefixes(self) -> None:
        assert render_transcription_text(_result("muffled", 0.2), 0.4) == LOW_CONFIDENCE_PREFIX + "muffled"

    def test_threshold_equality_is_not_low(self) -> None:
        assert render_transcription_text(_result("edge", 0.4), 0.4) == "edge"

    def test_none_confidence_passes_through(self) -> None:
        rendered = render_transcription_text(_result("hosted", None), 0.4)
        assert rendered == "hosted" and not rendered.startswith(LOW_CONFIDENCE_PREFIX)

    def test_collapses_internal_newlines(self) -> None:
        assert render_transcription_text(_result("line one\nline two", 0.9), 0.4) == "line one line two"

    def test_strips_whitespace(self) -> None:
        assert render_transcription_text(_result("  spaced  ", 0.9), 0.4) == "spaced"

    def test_low_confidence_collapses_whitespace(self) -> None:
        assert render_transcription_text(_result("a\n\n\nb", 0.1), 0.4) == LOW_CONFIDENCE_PREFIX + "a b"

    def test_empty_text_returns_empty(self) -> None:
        assert render_transcription_text(_result("", 0.9), 0.4) == ""


def test_render_duration_rejection_substitutes_seconds() -> None:
    assert render_duration_rejection(180) == "voice too long \u2014 limit 180s"
    assert "{seconds}" in OVER_DURATION_MARKER_TEMPLATE


class TestEstimateAudioDurationSeconds:
    def test_returns_size_over_byte_rate(self, tmp_path: Path) -> None:
        path = _make_audio(tmp_path, size_bytes=VOICE_BYTES_PER_SECOND * 10)
        assert estimate_audio_duration_seconds(path) == 10.0

    def test_zero_byte_file_returns_none(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.ogg"
        path.write_bytes(b"")
        assert estimate_audio_duration_seconds(path) is None

    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        assert estimate_audio_duration_seconds(tmp_path / "nope.ogg") is None


class _FakeChannel:
    async def transcribe_audio(self, file_path: str | Path) -> str:  # pragma: no cover
        return "ORIGINAL"


class _NoTranscribeChannel:
    pass


class _StubBackend:
    BACKEND_NAME: Literal["local_faster_whisper"] = "local_faster_whisper"

    def __init__(self, result: TranscriptionResult) -> None:
        self._result = result
        self.calls: list[Path] = []

    async def transcribe(self, audio_path: Path) -> TranscriptionResult:
        self.calls.append(audio_path)
        return self._result


class _RaisingBackend:
    BACKEND_NAME: Literal["local_faster_whisper"] = "local_faster_whisper"

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc
        self.call_count = 0

    async def transcribe(self, audio_path: Path) -> TranscriptionResult:
        self.call_count += 1
        raise self._exc


class TestInstallVoiceTranscription:
    def test_patches_each_channel_with_attr(self) -> None:
        channels = {"telegram": _FakeChannel(), "whatsapp": _FakeChannel()}
        backend = _StubBackend(_result("hi", 0.9))
        assert install_voice_transcription(channels, backend, 180, 0.4) == 2
        for channel in channels.values():
            assert "transcribe_audio" in channel.__dict__

    def test_skips_channel_without_attr(self) -> None:
        channels = {"plain": _NoTranscribeChannel(), "telegram": _FakeChannel()}
        backend = _StubBackend(_result("hi", 0.9))
        assert install_voice_transcription(channels, backend, 180, 0.4) == 1


class TestPatchedMethodBehaviour:
    def test_calls_backend_with_path_and_returns_text(self, tmp_path: Path) -> None:
        audio = _make_audio(tmp_path)
        channel = _FakeChannel()
        backend = _StubBackend(_result("hi", 0.9))
        install_voice_transcription({"telegram": channel}, backend, 180, 0.4)
        assert _run(channel.transcribe_audio(str(audio))) == "hi"
        assert backend.calls == [audio] and isinstance(backend.calls[0], Path)

    def test_low_confidence_prefixes_text(self, tmp_path: Path) -> None:
        audio = _make_audio(tmp_path)
        channel = _FakeChannel()
        backend = _StubBackend(_result("muffled", 0.1))
        install_voice_transcription({"telegram": channel}, backend, 180, 0.4)
        assert _run(channel.transcribe_audio(audio)) == LOW_CONFIDENCE_PREFIX + "muffled"

    def test_over_duration_skips_backend(self, tmp_path: Path) -> None:
        audio = _make_audio(tmp_path, size_bytes=VOICE_BYTES_PER_SECOND * 200)
        channel = _FakeChannel()
        backend = _StubBackend(_result("never reached", 0.9))
        install_voice_transcription({"telegram": channel}, backend, 180, 0.4)
        assert _run(channel.transcribe_audio(audio)) == render_duration_rejection(180)
        assert backend.calls == []

    @pytest.mark.parametrize("exc", [
        FileNotFoundError("no audio"),
        RuntimeError("model load failed"),
        httpx.RequestError("net down", request=httpx.Request("POST", "https://x/y")),
        httpx.HTTPStatusError(
            "500",
            request=httpx.Request("POST", "https://x/y"),
            response=httpx.Response(500),
        ),
    ])
    def test_caught_exceptions_become_failed_marker(
        self, tmp_path: Path, exc: BaseException,
    ) -> None:
        audio = _make_audio(tmp_path)
        channel = _FakeChannel()
        backend = _RaisingBackend(exc)
        install_voice_transcription({"telegram": channel}, backend, 180, 0.4)
        assert _run(channel.transcribe_audio(audio)) == FAILED_MARKER
        assert backend.call_count == 1

    def test_cancelled_error_propagates(self, tmp_path: Path) -> None:
        channel = _FakeChannel()
        backend = _RaisingBackend(asyncio.CancelledError())
        install_voice_transcription({"telegram": channel}, backend, 180, 0.4)
        with pytest.raises(asyncio.CancelledError):
            _run(channel.transcribe_audio(_make_audio(tmp_path)))

    def test_no_double_wrap_and_non_empty_failed_marker(self, tmp_path: Path) -> None:
        # Upstream wraps in [transcription: ...]; our return must never
        # start with that bracket (double-wrap) and must be non-empty
        # for the failure path (empty would drop to [voice: path]).
        assert FAILED_MARKER != ""
        channel = _FakeChannel()
        backend = _StubBackend(_result("hello world", 0.1))
        install_voice_transcription({"telegram": channel}, backend, 180, 0.4)
        assert not _run(channel.transcribe_audio(_make_audio(tmp_path))).startswith("[transcription:")


class _MutableClock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now = self.now + delta


def _install_failing(
    tmp_path: Path, clock: _MutableClock,
) -> tuple[_FakeChannel, Path]:
    channel = _FakeChannel()
    install_voice_transcription(
        {"telegram": channel}, _RaisingBackend(RuntimeError("boom")),
        180, 0.4, clock=clock,
    )
    return channel, _make_audio(tmp_path)


class TestRateLimitedWarn:
    def test_logs_first_failure(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture,
    ) -> None:
        clock = _MutableClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
        channel, audio = _install_failing(tmp_path, clock)
        with caplog.at_level(logging.WARNING, logger="voice_input_integration"):
            _run(channel.transcribe_audio(audio))
        warns = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warns) == 1 and "voice_input.backend_error" in warns[0].getMessage()

    def test_suppresses_within_interval(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture,
    ) -> None:
        clock = _MutableClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
        channel, audio = _install_failing(tmp_path, clock)
        with caplog.at_level(logging.WARNING, logger="voice_input_integration"):
            _run(channel.transcribe_audio(audio))
            clock.advance(timedelta(minutes=30))
            _run(channel.transcribe_audio(audio))
        assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1

    def test_emits_again_after_interval(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture,
    ) -> None:
        clock = _MutableClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
        channel, audio = _install_failing(tmp_path, clock)
        with caplog.at_level(logging.WARNING, logger="voice_input_integration"):
            _run(channel.transcribe_audio(audio))
            clock.advance(ERROR_LOG_INTERVAL + timedelta(seconds=1))
            _run(channel.transcribe_audio(audio))
        assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 2
