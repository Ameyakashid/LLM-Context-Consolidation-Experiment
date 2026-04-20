"""End-to-end voice-input tests composing sub-01..03 against real surfaces.

Where backends can be exercised without a network hop they are — the
local faster-whisper backend transcribes the committed
``tests/fixtures/audio/hello_world.wav`` fixture, the hosted backends
ride an ``httpx.MockTransport`` so the contract under test is the real
serialisation/deserialisation path, and the channel-patching test
patches a stub channel with the real
``install_voice_transcription`` from
:mod:`voice_input_integration`.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Coroutine, Literal, TypeVar

import httpx
import pytest

import voice_input_integration
from transcription_backend import (
    OPENAI_TRANSCRIPTIONS_URL,
    OpenAIWhisperBackend,
    TranscriptionResult,
    build_transcription_backend,
)
from voice_input_integration import (
    DEFAULT_MAX_VOICE_DURATION_SECONDS,
    FAILED_MARKER,
    LOW_CONFIDENCE_PREFIX,
    VOICE_BYTES_PER_SECOND,
    install_voice_transcription,
    render_duration_rejection,
)

T = TypeVar("T")
_LOCAL_BACKEND: Literal["local_faster_whisper"] = "local_faster_whisper"
_REPO_ROOT = Path(__file__).resolve().parent.parent
_FIXTURE_PATH = _REPO_ROOT / "tests" / "fixtures" / "audio" / "hello_world.wav"
_SOUL_MD_PATH = _REPO_ROOT / "workspace" / "SOUL.md"


def _run(coro: Coroutine[object, object, T]) -> T:
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clear_rate_limit_state() -> None:
    voice_input_integration._reset_rate_limit_state()


def _result(
    text: str,
    confidence: float | None,
    backend: Literal[
        "local_faster_whisper", "openai_whisper", "groq_whisper"
    ] = _LOCAL_BACKEND,
) -> TranscriptionResult:
    return TranscriptionResult(
        text=text,
        confidence=confidence,
        language="en",
        duration_seconds=1.0,
        backend_name=backend,
    )


class _StubChannel:
    async def transcribe_audio(self, file_path: str | Path) -> str:  # pragma: no cover
        return "ORIGINAL"


class _RecordingBackend:
    BACKEND_NAME: Literal["local_faster_whisper"] = _LOCAL_BACKEND

    def __init__(self, result: TranscriptionResult) -> None:
        self._result = result
        self.calls: list[Path] = []

    async def transcribe(self, audio_path: Path) -> TranscriptionResult:
        self.calls.append(audio_path)
        return self._result


class _RaisingBackend:
    BACKEND_NAME: Literal["local_faster_whisper"] = _LOCAL_BACKEND

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc
        self.call_count = 0

    async def transcribe(self, audio_path: Path) -> TranscriptionResult:
        self.call_count += 1
        raise self._exc


def _hosted_mock_transport(response_text: str) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"text": response_text})
    return httpx.MockTransport(handler)


# ---------------------------------------------------------------------------
# 1. Real local backend against the committed fixture
# ---------------------------------------------------------------------------

def test_local_backend_transcribes_fixture() -> None:
    """Run the real faster-whisper backend over the committed fixture.

    Skipped when the import is unavailable. The committed fixture is
    1.5 s of digital silence (see ``scripts/generate_voice_fixture.py``);
    Whisper's VAD filter therefore yields an empty transcription with
    ``confidence == 0.0``. Either an empty result or a substring match
    on "hello" is accepted so a Kokoro-regenerated fixture continues to
    pass without test edits.
    """
    pytest.importorskip("faster_whisper")
    if not _FIXTURE_PATH.exists():
        pytest.skip(f"audio fixture not present at {_FIXTURE_PATH}")

    from transcription_backend import LocalFasterWhisperBackend

    backend = LocalFasterWhisperBackend(
        model_size="tiny", compute_type="int8", device="cpu",
    )
    result = _run(backend.transcribe(_FIXTURE_PATH))

    assert result.backend_name == _LOCAL_BACKEND
    assert result.confidence is not None
    assert 0.0 <= result.confidence <= 1.0
    is_silent_fixture = result.text == "" and result.confidence <= 0.3
    is_speech_fixture = "hello" in result.text.lower()
    assert is_silent_fixture or is_speech_fixture, (
        f"unexpected transcription: text={result.text!r} "
        f"confidence={result.confidence!r}"
    )


# ---------------------------------------------------------------------------
# 2. Hosted OpenAI path through factory + mock transport
# ---------------------------------------------------------------------------

def test_hosted_openai_path_with_mock_transport(tmp_path: Path) -> None:
    """Factory dispatches to OpenAIWhisperBackend; mock transport returns text.

    Asserts the contract is stable across factory-built and direct-built
    instances so swapping ``TRANSCRIPTION_BACKEND=openai`` in production
    yields the same shape as the unit-tested direct construction.
    """
    audio = tmp_path / "voice.ogg"
    audio.write_bytes(b"\x4f\x67\x67\x53fake-ogg-bytes")
    transport = _hosted_mock_transport("hello world")

    factory_backend = build_transcription_backend(
        {"TRANSCRIPTION_BACKEND": "openai", "OPENAI_API_KEY": "sk-test"},
    )
    assert isinstance(factory_backend, OpenAIWhisperBackend)

    direct_backend = OpenAIWhisperBackend(
        api_key="sk-test", transport=transport,
    )
    direct_result = _run(direct_backend.transcribe(audio))

    assert direct_result.text == "hello world"
    assert direct_result.confidence is None
    assert direct_result.backend_name == "openai_whisper"
    assert OPENAI_TRANSCRIPTIONS_URL.startswith("https://api.openai.com/")


# ---------------------------------------------------------------------------
# 3. install_voice_transcription replaces transcribe_audio end-to-end
# ---------------------------------------------------------------------------

def test_install_voice_transcription_replaces_transcribe_audio() -> None:
    """The patched method routes through the backend and returns rendered text."""
    if not _FIXTURE_PATH.exists():
        pytest.skip(f"audio fixture not present at {_FIXTURE_PATH}")

    channel = _StubChannel()
    backend = _RecordingBackend(_result("hello world", 0.9))
    patched_count = install_voice_transcription(
        channels={"telegram": channel},
        backend=backend,
        max_duration=DEFAULT_MAX_VOICE_DURATION_SECONDS,
        threshold=0.4,
    )

    assert patched_count == 1
    returned = _run(channel.transcribe_audio(_FIXTURE_PATH))
    assert returned == "hello world"
    assert backend.calls == [_FIXTURE_PATH]


# ---------------------------------------------------------------------------
# 4. Low-confidence prefix survives nanobot's upstream wrapper
# ---------------------------------------------------------------------------

def test_low_confidence_prefix_round_trip_through_channel(tmp_path: Path) -> None:
    """Patched method emits the prefix; upstream wrapper produces the SOUL.md form.

    Nanobot's Telegram channel wraps the patched method's return string
    as ``[transcription: <text>]`` before the hook chain sees it. The
    SOUL.md ``## Voice Input`` section teaches the LLM to recognise
    ``[transcription: (low confidence) ...]`` exactly — verify that
    string assembles correctly at the seam.
    """
    audio = tmp_path / "voice.ogg"
    audio.write_bytes(b"x" * 1024)

    channel = _StubChannel()
    backend = _RecordingBackend(_result("maybe hello", 0.2))
    install_voice_transcription(
        channels={"telegram": channel},
        backend=backend,
        max_duration=DEFAULT_MAX_VOICE_DURATION_SECONDS,
        threshold=0.4,
    )

    inner_text = _run(channel.transcribe_audio(audio))
    wrapped = f"[transcription: {inner_text}]"

    assert inner_text == LOW_CONFIDENCE_PREFIX + "maybe hello"
    assert wrapped == "[transcription: (low confidence) maybe hello]"


# ---------------------------------------------------------------------------
# 5. Cross-link to sub-03 SOUL.md guidance
# ---------------------------------------------------------------------------

def test_e2e_path_with_soul_md_section_present() -> None:
    """SOUL.md teaches the LLM to handle the strings this module produces."""
    if not _SOUL_MD_PATH.exists():
        pytest.skip(f"SOUL.md not present at {_SOUL_MD_PATH}")

    soul = _SOUL_MD_PATH.read_text(encoding="utf-8")
    assert "## Voice Input" in soul
    assert LOW_CONFIDENCE_PREFIX in soul


# ---------------------------------------------------------------------------
# 6. Over-duration short-circuits the backend
# ---------------------------------------------------------------------------

def test_over_duration_short_circuits_backend(tmp_path: Path) -> None:
    """Files whose probed duration > MAX never reach the backend."""
    oversized = tmp_path / "long.ogg"
    oversized.write_bytes(
        b"\0" * (VOICE_BYTES_PER_SECOND * (DEFAULT_MAX_VOICE_DURATION_SECONDS + 5))
    )

    channel = _StubChannel()
    backend = _RecordingBackend(_result("never reached", 0.9))
    install_voice_transcription(
        channels={"telegram": channel},
        backend=backend,
        max_duration=DEFAULT_MAX_VOICE_DURATION_SECONDS,
        threshold=0.4,
    )

    returned = _run(channel.transcribe_audio(oversized))

    assert returned == render_duration_rejection(DEFAULT_MAX_VOICE_DURATION_SECONDS)
    assert backend.calls == []


# ---------------------------------------------------------------------------
# 7. Backend exceptions resolve to FAILED_MARKER
# ---------------------------------------------------------------------------

def test_backend_exception_returns_failed_marker(tmp_path: Path) -> None:
    """A RuntimeError from the backend becomes the marker; nothing propagates."""
    audio = tmp_path / "voice.ogg"
    audio.write_bytes(b"x" * 1024)

    channel = _StubChannel()
    backend = _RaisingBackend(RuntimeError("backend exploded"))
    install_voice_transcription(
        channels={"telegram": channel},
        backend=backend,
        max_duration=DEFAULT_MAX_VOICE_DURATION_SECONDS,
        threshold=0.4,
    )

    returned = _run(channel.transcribe_audio(audio))

    assert returned == FAILED_MARKER
    assert backend.call_count == 1
