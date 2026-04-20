"""Pure unit tests for transcription_backend.py — no I/O, no network."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from transcription_backend import (
    LOW_CONFIDENCE_THRESHOLD,
    GroqWhisperBackend,
    LocalFasterWhisperBackend,
    OpenAIWhisperBackend,
    TranscriptionBackend,
    TranscriptionResult,
    build_transcription_backend,
    compute_confidence,
    is_low_confidence,
    resolve_low_confidence_threshold,
)


@dataclass
class FakeSegment:
    text: str = ""
    avg_logprob: float = 0.0
    no_speech_prob: float = 0.0


# ---------------------------------------------------------------------------
# compute_confidence
# ---------------------------------------------------------------------------

class TestComputeConfidence:
    def test_empty_segments_returns_zero(self) -> None:
        assert compute_confidence([]) == 0.0

    def test_perfect_segment_returns_one(self) -> None:
        seg = FakeSegment(avg_logprob=0.0, no_speech_prob=0.0)
        assert compute_confidence([seg]) == 1.0

    def test_pure_silence_returns_zero(self) -> None:
        seg = FakeSegment(avg_logprob=0.0, no_speech_prob=1.0)
        assert compute_confidence([seg]) == 0.0

    def test_specified_case_in_unit_range(self) -> None:
        seg = FakeSegment(avg_logprob=-0.1, no_speech_prob=0.05)
        result = compute_confidence([seg])
        assert 0.0 <= result <= 1.0
        assert result == pytest.approx(0.85956, rel=1e-3)

    def test_lower_logprob_lowers_confidence(self) -> None:
        good = FakeSegment(avg_logprob=-0.1, no_speech_prob=0.0)
        bad = FakeSegment(avg_logprob=-2.0, no_speech_prob=0.0)
        assert compute_confidence([good]) > compute_confidence([bad])

    def test_higher_no_speech_lowers_confidence(self) -> None:
        clear = FakeSegment(avg_logprob=-0.1, no_speech_prob=0.05)
        muddy = FakeSegment(avg_logprob=-0.1, no_speech_prob=0.5)
        assert compute_confidence([clear]) > compute_confidence([muddy])

    def test_extreme_positive_logprob_clamped(self) -> None:
        seg = FakeSegment(avg_logprob=10.0, no_speech_prob=0.0)
        assert compute_confidence([seg]) == 1.0

    def test_mean_across_two_segments(self) -> None:
        a = FakeSegment(avg_logprob=0.0, no_speech_prob=0.0)
        b = FakeSegment(avg_logprob=0.0, no_speech_prob=1.0)
        assert compute_confidence([a, b]) == 0.5

    def test_result_always_in_unit_interval(self) -> None:
        for logprob in (-5.0, -1.0, -0.5, -0.1, 0.0):
            for nsp in (0.0, 0.25, 0.5, 0.75, 1.0):
                seg = FakeSegment(avg_logprob=logprob, no_speech_prob=nsp)
                value = compute_confidence([seg])
                assert 0.0 <= value <= 1.0


# ---------------------------------------------------------------------------
# resolve_low_confidence_threshold
# ---------------------------------------------------------------------------

class TestResolveLowConfidenceThreshold:
    def test_default_when_unset(self) -> None:
        assert resolve_low_confidence_threshold({}) == LOW_CONFIDENCE_THRESHOLD

    def test_default_when_empty_string(self) -> None:
        env = {"WHISPER_LOW_CONFIDENCE_THRESHOLD": ""}
        assert resolve_low_confidence_threshold(env) == LOW_CONFIDENCE_THRESHOLD

    def test_parses_float(self) -> None:
        env = {"WHISPER_LOW_CONFIDENCE_THRESHOLD": "0.65"}
        assert resolve_low_confidence_threshold(env) == 0.65

    def test_clamps_above_one(self) -> None:
        env = {"WHISPER_LOW_CONFIDENCE_THRESHOLD": "5.0"}
        assert resolve_low_confidence_threshold(env) == 1.0

    def test_clamps_below_zero(self) -> None:
        env = {"WHISPER_LOW_CONFIDENCE_THRESHOLD": "-0.3"}
        assert resolve_low_confidence_threshold(env) == 0.0

    def test_invalid_float_raises(self) -> None:
        env = {"WHISPER_LOW_CONFIDENCE_THRESHOLD": "bogus"}
        with pytest.raises(ValueError):
            resolve_low_confidence_threshold(env)


# ---------------------------------------------------------------------------
# is_low_confidence
# ---------------------------------------------------------------------------

def _make_result(confidence: float | None) -> TranscriptionResult:
    return TranscriptionResult(
        text="hello",
        confidence=confidence,
        language="en",
        duration_seconds=1.0,
        backend_name="local_faster_whisper",
    )


class TestIsLowConfidence:
    def test_none_confidence_is_passthrough(self) -> None:
        assert is_low_confidence(_make_result(None), 0.4) is False

    def test_below_threshold_is_low(self) -> None:
        assert is_low_confidence(_make_result(0.3), 0.4) is True

    def test_at_threshold_is_not_low(self) -> None:
        assert is_low_confidence(_make_result(0.4), 0.4) is False

    def test_above_threshold_is_not_low(self) -> None:
        assert is_low_confidence(_make_result(0.9), 0.4) is False

    def test_zero_confidence_is_low(self) -> None:
        assert is_low_confidence(_make_result(0.0), 0.4) is True


# ---------------------------------------------------------------------------
# build_transcription_backend
# ---------------------------------------------------------------------------

class TestBuildTranscriptionBackend:
    def test_default_when_unset_returns_local(self) -> None:
        backend = build_transcription_backend({})
        assert isinstance(backend, LocalFasterWhisperBackend)

    def test_explicit_local_returns_local(self) -> None:
        backend = build_transcription_backend({"TRANSCRIPTION_BACKEND": "local"})
        assert isinstance(backend, LocalFasterWhisperBackend)

    def test_openai_returns_openai(self) -> None:
        env = {"TRANSCRIPTION_BACKEND": "openai", "OPENAI_API_KEY": "sk-test"}
        backend = build_transcription_backend(env)
        assert isinstance(backend, OpenAIWhisperBackend)

    def test_groq_returns_groq(self) -> None:
        env = {"TRANSCRIPTION_BACKEND": "groq", "GROQ_API_KEY": "gsk-test"}
        backend = build_transcription_backend(env)
        assert isinstance(backend, GroqWhisperBackend)

    def test_value_is_normalised_lower_with_whitespace(self) -> None:
        backend = build_transcription_backend({"TRANSCRIPTION_BACKEND": "  GROQ "})
        assert isinstance(backend, GroqWhisperBackend)

    def test_unknown_value_raises_value_error_listing_options(self) -> None:
        with pytest.raises(ValueError) as excinfo:
            build_transcription_backend({"TRANSCRIPTION_BACKEND": "azure"})
        message = str(excinfo.value)
        assert "azure" in message
        assert "local" in message
        assert "openai" in message
        assert "groq" in message

    def test_returned_backend_satisfies_protocol(self) -> None:
        backend = build_transcription_backend({})
        assert isinstance(backend, TranscriptionBackend)


# ---------------------------------------------------------------------------
# TranscriptionResult dataclass shape
# ---------------------------------------------------------------------------

class TestTranscriptionResult:
    def test_is_frozen(self) -> None:
        result = _make_result(0.5)
        with pytest.raises(Exception):
            result.text = "mutated"  # type: ignore[misc]

    def test_fields_match_spec(self) -> None:
        result = _make_result(0.5)
        assert result.text == "hello"
        assert result.confidence == 0.5
        assert result.language == "en"
        assert result.duration_seconds == 1.0
        assert result.backend_name == "local_faster_whisper"
