"""Whisper transcription backends behind a single async Protocol.

Three selectable backends — local ``faster-whisper``, OpenAI hosted,
Groq hosted — share one ``transcribe(audio_path) -> TranscriptionResult``
contract; chosen by ``TRANSCRIPTION_BACKEND`` env var.
"""

from __future__ import annotations

import asyncio
import importlib
import math
from dataclasses import dataclass
from pathlib import Path
from typing import (
    Callable,
    Iterable,
    Literal,
    Mapping,
    Protocol,
    Sequence,
    cast,
    runtime_checkable,
)

import httpx

BackendName = Literal["local_faster_whisper", "openai_whisper", "groq_whisper"]

LOW_CONFIDENCE_THRESHOLD: float = 0.4

OPENAI_TRANSCRIPTIONS_URL = "https://api.openai.com/v1/audio/transcriptions"
OPENAI_MODEL = "whisper-1"
GROQ_TRANSCRIPTIONS_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_MODEL = "whisper-large-v3"
HOSTED_TIMEOUT_SECONDS: float = 60.0

VALID_BACKEND_NAMES: tuple[str, ...] = ("local", "openai", "groq")


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    confidence: float | None
    language: str | None
    duration_seconds: float | None
    backend_name: BackendName


@runtime_checkable
class TranscriptionBackend(Protocol):
    async def transcribe(self, audio_path: Path) -> TranscriptionResult: ...


class _SegmentLike(Protocol):
    text: str
    avg_logprob: float
    no_speech_prob: float


class _TranscriptionInfoLike(Protocol):
    language: str
    duration: float


class _WhisperModelLike(Protocol):
    def transcribe(
        self,
        audio: str,
        *,
        vad_filter: bool = ...,
    ) -> tuple[Iterable[_SegmentLike], _TranscriptionInfoLike]: ...


_WhisperModelFactory = Callable[..., _WhisperModelLike]


def compute_confidence(segments: Sequence[_SegmentLike]) -> float:
    """Map per-segment Whisper logprobs to one ``[0.0, 1.0]`` confidence.

    Why: ``exp(avg_logprob)`` lifts faster-whisper's natural-log average
    token probability into linear ``[0, 1]`` space; multiplying by
    ``(1 - no_speech_prob)`` penalises silence-heavy segments. Empty
    input collapses to ``0.0`` (no evidence ⇒ lowest confidence).
    """
    if not segments:
        return 0.0
    per_segment = [
        max(0.0, min(1.0, math.exp(seg.avg_logprob))) * (1.0 - seg.no_speech_prob)
        for seg in segments
    ]
    average = sum(per_segment) / len(per_segment)
    return max(0.0, min(1.0, average))


def resolve_low_confidence_threshold(env: Mapping[str, str]) -> float:
    """Read ``WHISPER_LOW_CONFIDENCE_THRESHOLD`` from env, clamp to [0, 1]."""
    raw = env.get("WHISPER_LOW_CONFIDENCE_THRESHOLD")
    if raw is None or raw == "":
        return LOW_CONFIDENCE_THRESHOLD
    parsed = float(raw)
    return max(0.0, min(1.0, parsed))


def is_low_confidence(result: TranscriptionResult, threshold: float) -> bool:
    """Backends without a confidence signal pass through (never low)."""
    if result.confidence is None:
        return False
    return result.confidence < threshold


def _load_whisper_model_class() -> _WhisperModelFactory:
    """Lazy-import faster-whisper; raise RuntimeError with install hint."""
    try:
        module = importlib.import_module("faster_whisper")
    except ImportError as exc:
        raise RuntimeError(
            "faster-whisper is required for LocalFasterWhisperBackend. "
            "Install it with: pip install faster-whisper"
        ) from exc
    return cast(_WhisperModelFactory, module.WhisperModel)


class LocalFasterWhisperBackend:
    BACKEND_NAME: BackendName = "local_faster_whisper"

    def __init__(
        self,
        model_size: str = "tiny",
        compute_type: str = "default",
        device: str = "auto",
        model_factory: _WhisperModelFactory | None = None,
    ) -> None:
        self._model_size = model_size
        self._compute_type = compute_type
        self._device = device
        self._model_factory = model_factory
        self._model: _WhisperModelLike | None = None

    async def transcribe(self, audio_path: Path) -> TranscriptionResult:
        if not audio_path.exists():
            raise FileNotFoundError(
                f"Audio file not found for transcription: {audio_path}"
            )
        if self._model is None:
            factory = self._model_factory or _load_whisper_model_class()
            self._model = factory(
                self._model_size,
                device=self._device,
                compute_type=self._compute_type,
            )
        return await asyncio.to_thread(self._transcribe_sync, audio_path)

    def _transcribe_sync(self, audio_path: Path) -> TranscriptionResult:
        model = self._model
        if model is None:
            raise RuntimeError(
                "Internal error: LocalFasterWhisperBackend model "
                "not initialised before sync transcription call."
            )
        segments_iter, info = model.transcribe(str(audio_path), vad_filter=True)
        segments = list(segments_iter)
        text = "".join(seg.text for seg in segments).strip()
        return TranscriptionResult(
            text=text,
            confidence=compute_confidence(segments),
            language=info.language,
            duration_seconds=info.duration,
            backend_name=self.BACKEND_NAME,
        )


class _HostedWhisperBackend:
    """Shared form-multipart POST shape for OpenAI/Groq Whisper endpoints."""

    def __init__(
        self,
        api_key: str | None,
        api_url: str,
        model_name: str,
        backend_name: BackendName,
        api_key_env_var: str,
        provider_label: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._api_url = api_url
        self._model_name = model_name
        self._backend_name = backend_name
        self._api_key_env_var = api_key_env_var
        self._provider_label = provider_label
        self._transport = transport

    async def transcribe(self, audio_path: Path) -> TranscriptionResult:
        if not self._api_key:
            raise RuntimeError(
                f"{self._provider_label} transcription requires "
                f"{self._api_key_env_var} env var to be set."
            )
        if not audio_path.exists():
            raise FileNotFoundError(
                f"Audio file not found for transcription: {audio_path}"
            )
        text = await self._post_transcription(audio_path)
        return TranscriptionResult(
            text=text,
            confidence=None,
            language=None,
            duration_seconds=None,
            backend_name=self._backend_name,
        )

    async def _post_transcription(self, audio_path: Path) -> str:
        headers = {"Authorization": f"Bearer {self._api_key}"}
        if self._transport is not None:
            client = httpx.AsyncClient(
                timeout=HOSTED_TIMEOUT_SECONDS, transport=self._transport,
            )
        else:
            client = httpx.AsyncClient(timeout=HOSTED_TIMEOUT_SECONDS)
        async with client:
            with open(audio_path, "rb") as audio_file:
                files = {
                    "file": (audio_path.name, audio_file, "application/octet-stream"),
                }
                data = {"model": self._model_name}
                try:
                    response = await client.post(
                        self._api_url, headers=headers, files=files, data=data,
                    )
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    raise RuntimeError(
                        f"{self._provider_label} transcription failed "
                        f"with HTTP {exc.response.status_code} "
                        f"at {self._api_url}"
                    ) from exc
                except httpx.RequestError as exc:
                    raise RuntimeError(
                        f"{self._provider_label} transcription network "
                        f"error contacting {self._api_url}: {exc}"
                    ) from exc
        payload = response.json()
        if not isinstance(payload, dict):
            return ""
        text_value = payload.get("text", "")
        return text_value if isinstance(text_value, str) else ""


class OpenAIWhisperBackend(_HostedWhisperBackend):
    def __init__(
        self,
        api_key: str | None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(
            api_key=api_key,
            api_url=OPENAI_TRANSCRIPTIONS_URL,
            model_name=OPENAI_MODEL,
            backend_name="openai_whisper",
            api_key_env_var="OPENAI_API_KEY",
            provider_label="OpenAI",
            transport=transport,
        )


class GroqWhisperBackend(_HostedWhisperBackend):
    def __init__(
        self,
        api_key: str | None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(
            api_key=api_key,
            api_url=GROQ_TRANSCRIPTIONS_URL,
            model_name=GROQ_MODEL,
            backend_name="groq_whisper",
            api_key_env_var="GROQ_API_KEY",
            provider_label="Groq",
            transport=transport,
        )


def build_transcription_backend(env: Mapping[str, str]) -> TranscriptionBackend:
    backend_choice = env.get("TRANSCRIPTION_BACKEND", "local").strip().lower()
    if backend_choice == "local":
        return LocalFasterWhisperBackend(
            model_size=env.get("WHISPER_MODEL_SIZE", "tiny"),
            compute_type=env.get("WHISPER_COMPUTE_TYPE", "default"),
            device=env.get("WHISPER_DEVICE", "auto"),
        )
    if backend_choice == "openai":
        return OpenAIWhisperBackend(api_key=env.get("OPENAI_API_KEY"))
    if backend_choice == "groq":
        return GroqWhisperBackend(api_key=env.get("GROQ_API_KEY"))
    raise ValueError(
        f"Unknown TRANSCRIPTION_BACKEND value: {backend_choice!r}. "
        f"Valid options: {VALID_BACKEND_NAMES}"
    )
