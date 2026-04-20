"""Gateway-integration tests for voice_input_integration.setup_voice_input.

Avoids constructing the full nanobot ``ChannelManager`` — passes a stub
channels dict directly to :func:`setup_voice_input`. The subprocess-
based test on AC #2 boots a fresh interpreter to assert that flag-OFF
boot does NOT pull ``faster_whisper`` into ``sys.modules``.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

import pytest

import voice_input_integration
from transcription_backend import TranscriptionBackend, TranscriptionResult
from voice_input_integration import setup_voice_input

REPO_ROOT = Path(__file__).resolve().parent.parent


class _FakeChannel:
    async def transcribe_audio(self, file_path: str | Path) -> str:  # pragma: no cover
        return "ORIGINAL"


class _StubBackend:
    BACKEND_NAME: Literal["local_faster_whisper"] = "local_faster_whisper"
    construction_count = 0

    def __init__(self) -> None:
        type(self).construction_count += 1
        self.calls: list[Path] = []

    async def transcribe(self, audio_path: Path) -> TranscriptionResult:  # pragma: no cover
        self.calls.append(audio_path)
        return TranscriptionResult(
            text="stub", confidence=0.9, language="en",
            duration_seconds=1.0, backend_name=self.BACKEND_NAME,
        )


@pytest.fixture(autouse=True)
def _clear_state() -> None:
    voice_input_integration._reset_rate_limit_state()
    _StubBackend.construction_count = 0


def _stub_builder(_env: Mapping[str, str]) -> TranscriptionBackend:
    return _StubBackend()


# ---------------------------------------------------------------------------
# Flag OFF
# ---------------------------------------------------------------------------

class TestFlagOff:
    def test_returns_zero_patches(self) -> None:
        channels: dict[str, object] = {"telegram": _FakeChannel()}
        assert setup_voice_input({}, channels) == 0

    def test_does_not_patch_channels(self) -> None:
        channel = _FakeChannel()
        channels: dict[str, object] = {"telegram": channel}
        original_method = type(channel).transcribe_audio
        setup_voice_input({}, channels)
        assert channel.transcribe_audio.__func__ is original_method  # type: ignore[attr-defined]

    def test_does_not_construct_backend(self) -> None:
        setup_voice_input(
            {"VOICE_INPUT_ENABLED": "false"},
            {"telegram": _FakeChannel()},
            backend_builder=_stub_builder,
        )
        assert _StubBackend.construction_count == 0

    def test_emits_no_ready_log(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        with caplog.at_level(logging.DEBUG, logger="voice_input_integration"):
            setup_voice_input({}, {"telegram": _FakeChannel()})
        ready_messages = [
            r for r in caplog.records if "voice_input.ready" in r.getMessage()
        ]
        assert ready_messages == []

    def test_emits_disabled_debug(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        with caplog.at_level(logging.DEBUG, logger="voice_input_integration"):
            setup_voice_input({}, {"telegram": _FakeChannel()})
        debugs = [
            r for r in caplog.records if "voice_input.disabled" in r.getMessage()
        ]
        assert len(debugs) == 1


# ---------------------------------------------------------------------------
# Flag ON
# ---------------------------------------------------------------------------

class TestFlagOn:
    def test_returns_patch_count(self) -> None:
        channels: dict[str, object] = {
            "telegram": _FakeChannel(),
            "whatsapp": _FakeChannel(),
        }
        env = {"VOICE_INPUT_ENABLED": "true"}
        assert setup_voice_input(env, channels, backend_builder=_stub_builder) == 2

    def test_replaces_transcribe_audio_attribute(self) -> None:
        channel = _FakeChannel()
        channels: dict[str, object] = {"telegram": channel}
        env = {"VOICE_INPUT_ENABLED": "true"}
        setup_voice_input(env, channels, backend_builder=_stub_builder)
        assert "transcribe_audio" in channel.__dict__

    def test_constructs_backend_lazily(self) -> None:
        channels: dict[str, object] = {"telegram": _FakeChannel()}
        env = {"VOICE_INPUT_ENABLED": "true"}
        setup_voice_input(env, channels, backend_builder=_stub_builder)
        # Backend constructor ran; transcribe() did NOT run (no audio
        # message processed). Lazy faster-whisper model load is therefore
        # not triggered.
        assert _StubBackend.construction_count == 1

    def test_logs_ready_exactly_once(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        env = {"VOICE_INPUT_ENABLED": "true"}
        with caplog.at_level(logging.INFO, logger="voice_input_integration"):
            setup_voice_input(
                env, {"telegram": _FakeChannel()},
                backend_builder=_stub_builder,
            )
        ready = [
            r for r in caplog.records if "voice_input.ready" in r.getMessage()
        ]
        assert len(ready) == 1

    def test_ready_log_carries_backend_and_threshold(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        env = {
            "VOICE_INPUT_ENABLED": "true",
            "MAX_VOICE_DURATION_SECONDS": "240",
            "WHISPER_LOW_CONFIDENCE_THRESHOLD": "0.55",
        }
        with caplog.at_level(logging.INFO, logger="voice_input_integration"):
            setup_voice_input(
                env, {"telegram": _FakeChannel()},
                backend_builder=_stub_builder,
            )
        message = caplog.records[-1].getMessage()
        assert "max_duration=240s" in message
        assert "threshold=0.55" in message
        assert "channels_patched=1" in message
        assert "backend=local_faster_whisper" in message

    def test_default_builder_used_when_no_seam(self) -> None:
        # Default builder selects a hosted backend (no API key needed at
        # construction time for "openai" — only at transcribe()). This
        # confirms the production code path runs without the seam.
        env = {
            "VOICE_INPUT_ENABLED": "true",
            "TRANSCRIPTION_BACKEND": "openai",
        }
        channels: dict[str, object] = {"telegram": _FakeChannel()}
        assert setup_voice_input(env, channels) == 1


# ---------------------------------------------------------------------------
# AC #2: faster_whisper not imported on flag-OFF boot.
# ---------------------------------------------------------------------------

_SUBPROCESS_PROBE = (
    "import sys\n"
    "import voice_input_integration as v\n"
    "v.setup_voice_input({'VOICE_INPUT_ENABLED': 'false'}, {})\n"
    "print('faster_whisper' in sys.modules)\n"
)


def _run_subprocess_probe(
    extra_env_lines: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", extra_env_lines + _SUBPROCESS_PROBE],
        capture_output=True, text=True, cwd=REPO_ROOT, timeout=60,
    )


class TestNoFasterWhisperImportWhenFlagOff:
    def test_importing_module_does_not_import_faster_whisper(self) -> None:
        result = _run_subprocess_probe()
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip().endswith("False"), result.stdout

    def test_setup_with_flag_off_does_not_import_faster_whisper(self) -> None:
        # Same probe as above; the call to setup_voice_input(...) is
        # already in _SUBPROCESS_PROBE and is the core AC #2 assertion.
        result = _run_subprocess_probe()
        assert result.returncode == 0, result.stderr
        assert "True" not in result.stdout
