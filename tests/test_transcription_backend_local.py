"""Local faster-whisper backend tests with WhisperModel mocked.

The model is dependency-injected via ``model_factory`` so the suite runs
offline without ``faster-whisper`` installed. The lazy-load failure path
is exercised by monkeypatching ``importlib.import_module``.
"""

from __future__ import annotations

import asyncio
import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import Coroutine, Iterable, TypeVar

import pytest

import transcription_backend
from transcription_backend import (
    LocalFasterWhisperBackend,
    TranscriptionResult,
    build_transcription_backend,
)

T = TypeVar("T")


def _run(coro: Coroutine[object, object, T]) -> T:
    return asyncio.run(coro)


@dataclass
class _FakeSegment:
    text: str
    avg_logprob: float
    no_speech_prob: float


@dataclass
class _FakeInfo:
    language: str
    duration: float


class _FakeModel:
    def __init__(self, segments: Iterable[_FakeSegment], info: _FakeInfo) -> None:
        self._segments = list(segments)
        self._info = info
        self.transcribe_calls: list[tuple[str, bool]] = []

    def transcribe(
        self, audio: str, *, vad_filter: bool = False,
    ) -> tuple[Iterable[_FakeSegment], _FakeInfo]:
        self.transcribe_calls.append((audio, vad_filter))
        return iter(self._segments), self._info


def _write_audio_fixture(tmp_path: Path) -> Path:
    path = tmp_path / "voice.wav"
    path.write_bytes(b"RIFFfake-wav-bytes")
    return path


# ---------------------------------------------------------------------------
# Constructor + factory + missing-file path (no model needed)
# ---------------------------------------------------------------------------

class TestLocalBackendNoModelNeeded:
    def test_missing_audio_file_raises_file_not_found(self, tmp_path: Path) -> None:
        backend = LocalFasterWhisperBackend()
        missing = tmp_path / "ghost.wav"

        with pytest.raises(FileNotFoundError) as excinfo:
            _run(backend.transcribe(missing))

        assert str(missing) in str(excinfo.value)

    def test_factory_returns_local_backend_with_env_overrides(self) -> None:
        env = {
            "TRANSCRIPTION_BACKEND": "local",
            "WHISPER_MODEL_SIZE": "small",
            "WHISPER_COMPUTE_TYPE": "int8",
            "WHISPER_DEVICE": "cpu",
        }
        backend = build_transcription_backend(env)
        assert isinstance(backend, LocalFasterWhisperBackend)
        assert backend._model_size == "small"
        assert backend._compute_type == "int8"
        assert backend._device == "cpu"

    def test_constructor_defaults(self) -> None:
        backend = LocalFasterWhisperBackend()
        assert backend._model_size == "tiny"
        assert backend._compute_type == "default"
        assert backend._device == "auto"


# ---------------------------------------------------------------------------
# Lazy-load failure path
# ---------------------------------------------------------------------------

class TestLazyLoadFailure:
    def test_runtime_error_when_faster_whisper_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        original_import = importlib.import_module

        def fake_import(name: str, package: str | None = None) -> object:
            if name == "faster_whisper":
                raise ImportError("simulated missing module")
            return original_import(name, package)

        monkeypatch.setattr(transcription_backend.importlib, "import_module", fake_import)

        backend = LocalFasterWhisperBackend()
        audio_path = _write_audio_fixture(tmp_path)

        with pytest.raises(RuntimeError) as excinfo:
            _run(backend.transcribe(audio_path))

        message = str(excinfo.value)
        assert "faster-whisper" in message
        assert "pip install" in message


# ---------------------------------------------------------------------------
# Mocked-model behavioural tests
# ---------------------------------------------------------------------------

class TestLocalBackendWithMockedModel:
    def test_transcribe_returns_text_language_duration(self, tmp_path: Path) -> None:
        info = _FakeInfo(language="en", duration=2.5)
        segments = [
            _FakeSegment(text="hello ", avg_logprob=-0.1, no_speech_prob=0.05),
            _FakeSegment(text="world", avg_logprob=-0.2, no_speech_prob=0.05),
        ]
        fake_model = _FakeModel(segments, info)

        backend = LocalFasterWhisperBackend(
            model_factory=lambda *args, **kwargs: fake_model,
        )
        audio_path = _write_audio_fixture(tmp_path)

        result = _run(backend.transcribe(audio_path))

        assert isinstance(result, TranscriptionResult)
        assert result.text == "hello world"
        assert result.language == "en"
        assert result.duration_seconds == 2.5
        assert result.backend_name == "local_faster_whisper"
        assert result.confidence is not None
        assert 0.0 <= result.confidence <= 1.0

    def test_model_constructed_once_across_two_transcriptions(
        self, tmp_path: Path,
    ) -> None:
        fake_model = _FakeModel(
            [_FakeSegment(text="ok", avg_logprob=-0.1, no_speech_prob=0.0)],
            _FakeInfo(language="en", duration=1.0),
        )
        constructions: list[tuple[object, ...]] = []

        def factory(*args: object, **kwargs: object) -> _FakeModel:
            constructions.append(args)
            return fake_model

        backend = LocalFasterWhisperBackend(model_factory=factory)
        audio_path = _write_audio_fixture(tmp_path)

        _run(backend.transcribe(audio_path))
        _run(backend.transcribe(audio_path))

        assert len(constructions) == 1
        assert len(fake_model.transcribe_calls) == 2

    def test_model_constructor_receives_size_compute_device(
        self, tmp_path: Path,
    ) -> None:
        captured: dict[str, object] = {}

        def factory(*args: object, **kwargs: object) -> _FakeModel:
            captured["args"] = args
            captured["kwargs"] = kwargs
            return _FakeModel([], _FakeInfo(language="en", duration=0.0))

        backend = LocalFasterWhisperBackend(
            model_size="small",
            compute_type="int8",
            device="cpu",
            model_factory=factory,
        )
        audio_path = _write_audio_fixture(tmp_path)

        _run(backend.transcribe(audio_path))

        assert captured["args"] == ("small",)
        kwargs = captured["kwargs"]
        assert isinstance(kwargs, dict)
        assert kwargs["device"] == "cpu"
        assert kwargs["compute_type"] == "int8"

    def test_transcribe_passes_vad_filter_true(self, tmp_path: Path) -> None:
        fake_model = _FakeModel(
            [_FakeSegment(text="ok", avg_logprob=-0.1, no_speech_prob=0.0)],
            _FakeInfo(language="en", duration=1.0),
        )
        backend = LocalFasterWhisperBackend(
            model_factory=lambda *args, **kwargs: fake_model,
        )
        audio_path = _write_audio_fixture(tmp_path)

        _run(backend.transcribe(audio_path))

        assert fake_model.transcribe_calls[0][1] is True

    def test_empty_segments_yield_empty_text_zero_confidence(
        self, tmp_path: Path,
    ) -> None:
        fake_model = _FakeModel([], _FakeInfo(language="en", duration=0.5))
        backend = LocalFasterWhisperBackend(
            model_factory=lambda *args, **kwargs: fake_model,
        )
        audio_path = _write_audio_fixture(tmp_path)

        result = _run(backend.transcribe(audio_path))

        assert result.text == ""
        assert result.confidence == 0.0
        assert result.duration_seconds == 0.5
