"""Hosted backend tests using ``httpx.MockTransport`` — no real network."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Coroutine, TypeVar

import httpx
import pytest

from transcription_backend import (
    GROQ_MODEL,
    GROQ_TRANSCRIPTIONS_URL,
    OPENAI_MODEL,
    OPENAI_TRANSCRIPTIONS_URL,
    GroqWhisperBackend,
    OpenAIWhisperBackend,
)

T = TypeVar("T")


def _run(coro: Coroutine[object, object, T]) -> T:
    return asyncio.run(coro)


def _write_audio_fixture(tmp_path: Path, name: str = "voice.ogg") -> Path:
    path = tmp_path / name
    path.write_bytes(b"\x4f\x67\x67\x53fake-ogg-bytes")
    return path


def _capturing_transport(
    captured: dict[str, object],
    response_text: str,
    status_code: int = 200,
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["method"] = request.method
        captured["authorization"] = request.headers.get("authorization", "")
        captured["body"] = request.content
        captured["content_type"] = request.headers.get("content-type", "")
        if status_code >= 400:
            return httpx.Response(status_code, json={"error": "fail"})
        return httpx.Response(status_code, json={"text": response_text})
    return httpx.MockTransport(handler)


# ---------------------------------------------------------------------------
# OpenAI backend
# ---------------------------------------------------------------------------

class TestOpenAIWhisperBackend:
    def test_post_url_and_model(self, tmp_path: Path) -> None:
        captured: dict[str, object] = {}
        transport = _capturing_transport(captured, "hello world")
        audio_path = _write_audio_fixture(tmp_path)
        backend = OpenAIWhisperBackend(api_key="sk-test", transport=transport)

        result = _run(backend.transcribe(audio_path))

        assert captured["url"] == OPENAI_TRANSCRIPTIONS_URL
        assert captured["method"] == "POST"
        body = captured["body"]
        assert isinstance(body, bytes)
        assert OPENAI_MODEL.encode() in body
        assert audio_path.name.encode() in body
        assert result.text == "hello world"
        assert result.confidence is None
        assert result.language is None
        assert result.duration_seconds is None
        assert result.backend_name == "openai_whisper"

    def test_authorization_header_carries_bearer(self, tmp_path: Path) -> None:
        captured: dict[str, object] = {}
        transport = _capturing_transport(captured, "ok")
        audio_path = _write_audio_fixture(tmp_path)
        backend = OpenAIWhisperBackend(api_key="sk-abcd1234", transport=transport)

        _run(backend.transcribe(audio_path))

        assert captured["authorization"] == "Bearer sk-abcd1234"

    def test_request_uses_multipart_content_type(self, tmp_path: Path) -> None:
        captured: dict[str, object] = {}
        transport = _capturing_transport(captured, "ok")
        audio_path = _write_audio_fixture(tmp_path)
        backend = OpenAIWhisperBackend(api_key="sk-test", transport=transport)

        _run(backend.transcribe(audio_path))

        content_type = captured["content_type"]
        assert isinstance(content_type, str)
        assert content_type.startswith("multipart/form-data")

    def test_missing_api_key_raises_runtime_error(self, tmp_path: Path) -> None:
        audio_path = _write_audio_fixture(tmp_path)
        backend = OpenAIWhisperBackend(api_key=None)

        with pytest.raises(RuntimeError) as excinfo:
            _run(backend.transcribe(audio_path))

        assert "OPENAI_API_KEY" in str(excinfo.value)

    def test_empty_api_key_raises_runtime_error(self, tmp_path: Path) -> None:
        audio_path = _write_audio_fixture(tmp_path)
        backend = OpenAIWhisperBackend(api_key="")

        with pytest.raises(RuntimeError):
            _run(backend.transcribe(audio_path))

    def test_missing_audio_file_raises_file_not_found(
        self, tmp_path: Path,
    ) -> None:
        missing = tmp_path / "ghost.ogg"
        backend = OpenAIWhisperBackend(api_key="sk-test")

        with pytest.raises(FileNotFoundError) as excinfo:
            _run(backend.transcribe(missing))

        assert str(missing) in str(excinfo.value)

    def test_4xx_raises_runtime_error_with_status_and_provider(
        self, tmp_path: Path,
    ) -> None:
        captured: dict[str, object] = {}
        transport = _capturing_transport(captured, "", status_code=401)
        audio_path = _write_audio_fixture(tmp_path)
        backend = OpenAIWhisperBackend(api_key="sk-test", transport=transport)

        with pytest.raises(RuntimeError) as excinfo:
            _run(backend.transcribe(audio_path))

        message = str(excinfo.value)
        assert "OpenAI" in message
        assert "401" in message

    def test_5xx_raises_runtime_error(self, tmp_path: Path) -> None:
        captured: dict[str, object] = {}
        transport = _capturing_transport(captured, "", status_code=502)
        audio_path = _write_audio_fixture(tmp_path)
        backend = OpenAIWhisperBackend(api_key="sk-test", transport=transport)

        with pytest.raises(RuntimeError) as excinfo:
            _run(backend.transcribe(audio_path))

        assert "502" in str(excinfo.value)

    def test_network_error_raises_runtime_error(self, tmp_path: Path) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("simulated network failure")

        transport = httpx.MockTransport(handler)
        audio_path = _write_audio_fixture(tmp_path)
        backend = OpenAIWhisperBackend(api_key="sk-test", transport=transport)

        with pytest.raises(RuntimeError) as excinfo:
            _run(backend.transcribe(audio_path))

        assert "OpenAI" in str(excinfo.value)
        assert "network" in str(excinfo.value).lower()


# ---------------------------------------------------------------------------
# Groq backend
# ---------------------------------------------------------------------------

class TestGroqWhisperBackend:
    def test_post_url_and_model(self, tmp_path: Path) -> None:
        captured: dict[str, object] = {}
        transport = _capturing_transport(captured, "hola")
        audio_path = _write_audio_fixture(tmp_path)
        backend = GroqWhisperBackend(api_key="gsk-test", transport=transport)

        result = _run(backend.transcribe(audio_path))

        assert captured["url"] == GROQ_TRANSCRIPTIONS_URL
        body = captured["body"]
        assert isinstance(body, bytes)
        assert GROQ_MODEL.encode() in body
        assert result.text == "hola"
        assert result.confidence is None
        assert result.backend_name == "groq_whisper"

    def test_missing_api_key_raises(self, tmp_path: Path) -> None:
        audio_path = _write_audio_fixture(tmp_path)
        backend = GroqWhisperBackend(api_key=None)

        with pytest.raises(RuntimeError) as excinfo:
            _run(backend.transcribe(audio_path))

        assert "GROQ_API_KEY" in str(excinfo.value)

    def test_4xx_raises_runtime_error_with_provider(self, tmp_path: Path) -> None:
        captured: dict[str, object] = {}
        transport = _capturing_transport(captured, "", status_code=429)
        audio_path = _write_audio_fixture(tmp_path)
        backend = GroqWhisperBackend(api_key="gsk-test", transport=transport)

        with pytest.raises(RuntimeError) as excinfo:
            _run(backend.transcribe(audio_path))

        message = str(excinfo.value)
        assert "Groq" in message
        assert "429" in message

    def test_authorization_header_uses_groq_key(self, tmp_path: Path) -> None:
        captured: dict[str, object] = {}
        transport = _capturing_transport(captured, "ok")
        audio_path = _write_audio_fixture(tmp_path)
        backend = GroqWhisperBackend(api_key="gsk-secret", transport=transport)

        _run(backend.transcribe(audio_path))

        assert captured["authorization"] == "Bearer gsk-secret"

    def test_payload_without_text_field_returns_empty_string(
        self, tmp_path: Path,
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=json.dumps({"other": "x"}).encode())

        transport = httpx.MockTransport(handler)
        audio_path = _write_audio_fixture(tmp_path)
        backend = GroqWhisperBackend(api_key="gsk-test", transport=transport)

        result = _run(backend.transcribe(audio_path))

        assert result.text == ""
        assert result.backend_name == "groq_whisper"
