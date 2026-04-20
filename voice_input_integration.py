"""Voice-input integration: patch channel ``transcribe_audio`` at gateway startup.

For each channel with a ``transcribe_audio`` method we swap that method
for one that routes the audio file through the sub-01
:class:`~transcription_backend.TranscriptionBackend` factory. The patched
method enforces a file-size-derived duration ceiling before invoking the
backend, returns a ``(low confidence) `` prefix INSIDE the text — so
nanobot's own ``[transcription: ...]`` wrapper renders
``[transcription: (low confidence) ...]`` as seen by the LLM — and
converts the four specific sub-01 exceptions to a non-empty
:data:`FAILED_MARKER` so upstream short-circuits into
``[transcription: failed to process voice message]`` rather than
dropping the message to ``[voice: /path/...]``.

Feature-gated on ``VOICE_INPUT_ENABLED=true``; defaults OFF so flag-OFF
boot never triggers a ``faster_whisper`` import (the local backend
lazy-loads it only on the first ``transcribe()`` call, which cannot
fire unless :func:`setup_voice_input` was invoked).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from transcription_backend import (
    TranscriptionBackend,
    TranscriptionResult,
    build_transcription_backend,
    is_low_confidence,
    resolve_low_confidence_threshold,
)

log = logging.getLogger(__name__)

LOW_CONFIDENCE_PREFIX: str = "(low confidence) "
FAILED_MARKER: str = "failed to process voice message"
OVER_DURATION_MARKER_TEMPLATE: str = "voice too long \u2014 limit {seconds}s"

DEFAULT_MAX_VOICE_DURATION_SECONDS: int = 180
MAX_VOICE_DURATION_SECONDS: int = DEFAULT_MAX_VOICE_DURATION_SECONDS

# ~16 kbps OGG Opus ceiling. ``st_size / VOICE_BYTES_PER_SECOND`` over-
# estimates seconds on higher-bitrate or dense files so duration rejection
# errs toward rejection rather than acceptance — mutagen / ffmpeg-probe
# would be accurate but adds a dependency for a 2-line heuristic.
VOICE_BYTES_PER_SECOND: int = 2048

ERROR_LOG_INTERVAL: timedelta = timedelta(hours=1)


Clock = Callable[[], datetime]
AsyncTranscribe = Callable[[str | Path], Awaitable[str]]


def _default_clock() -> datetime:
    return datetime.now(tz=timezone.utc)


def is_voice_input_enabled(env: Mapping[str, str]) -> bool:
    """Return True when ``VOICE_INPUT_ENABLED`` equals the string ``"true"``.

    Matches the project's canonical ``is_<feature>_enabled`` idiom
    (see :func:`pulse_checkin_store.is_pulse_engine_enabled`):
    case-insensitive, whitespace-stripped, strict ``== "true"`` —
    ``"1"``, ``"yes"`` and ``"on"`` all resolve False. Defaults to False
    so the flag-OFF boot path never imports faster-whisper.
    """
    return env.get("VOICE_INPUT_ENABLED", "false").strip().lower() == "true"


def resolve_max_voice_duration(env: Mapping[str, str]) -> int:
    """Return the configured voice-message duration ceiling, in seconds.

    Reads ``MAX_VOICE_DURATION_SECONDS`` from env, clamps to ``>= 1``.
    Missing / blank env yields :data:`DEFAULT_MAX_VOICE_DURATION_SECONDS`.
    Non-integer values raise :class:`ValueError` naming the offending
    raw string — no silent fallback.
    """
    raw = env.get("MAX_VOICE_DURATION_SECONDS")
    if raw is None or raw.strip() == "":
        return DEFAULT_MAX_VOICE_DURATION_SECONDS
    try:
        parsed = int(raw)
    except ValueError as exc:
        raise ValueError(
            "MAX_VOICE_DURATION_SECONDS must be an integer; "
            f"got {raw!r}"
        ) from exc
    return max(1, parsed)


def render_transcription_text(
    result: TranscriptionResult, threshold: float,
) -> str:
    """Return transcription text, prefixed with ``(low confidence) `` when low.

    Whitespace (including Whisper's newline-per-segment output) collapses
    to single spaces so the upstream ``[transcription: ...]`` wrap stays
    on one line. ``None`` confidence passes through unprefixed (hosted
    backends cannot emit a confidence signal — over-marking would be
    incorrect).
    """
    cleaned = " ".join(result.text.split())
    if is_low_confidence(result, threshold):
        return LOW_CONFIDENCE_PREFIX + cleaned
    return cleaned


def render_duration_rejection(max_seconds: int) -> str:
    """Return the over-duration marker with the configured ceiling substituted."""
    return OVER_DURATION_MARKER_TEMPLATE.format(seconds=max_seconds)


def estimate_audio_duration_seconds(audio_path: Path) -> float | None:
    """Return a file-stat-based duration estimate, in seconds, or None.

    Divides ``st_size`` by :data:`VOICE_BYTES_PER_SECOND`. Returns
    ``None`` when the file cannot be stat'd OR when it is zero bytes.
    ``None`` callers must proceed WITHOUT rejecting (the backend will
    still process the file).
    """
    try:
        size_bytes = audio_path.stat().st_size
    except OSError:
        return None
    if size_bytes <= 0:
        return None
    return size_bytes / VOICE_BYTES_PER_SECOND


_last_error_log_at: dict[str, datetime] = {}


def _reset_rate_limit_state() -> None:
    """Test seam: clear the module-level rate-limit state."""
    _last_error_log_at.clear()


def _should_warn_backend_error(channel_name: str, now: datetime) -> bool:
    last = _last_error_log_at.get(channel_name)
    if last is None:
        return True
    return (now - last) >= ERROR_LOG_INTERVAL


def _record_backend_error_logged(channel_name: str, now: datetime) -> None:
    _last_error_log_at[channel_name] = now


def _build_patched_transcribe(
    backend: TranscriptionBackend,
    max_duration: int,
    threshold: float,
    channel_name: str,
    clock: Clock,
) -> AsyncTranscribe:
    async def transcribe_audio(file_path: str | Path) -> str:
        path = file_path if isinstance(file_path, Path) else Path(file_path)
        duration = estimate_audio_duration_seconds(path)
        if duration is not None and duration > max_duration:
            return render_duration_rejection(max_duration)
        try:
            result = await backend.transcribe(path)
        except (
            FileNotFoundError,
            RuntimeError,
            httpx.RequestError,
            httpx.HTTPStatusError,
        ) as exc:
            now = clock()
            if _should_warn_backend_error(channel_name, now):
                log.warning(
                    "voice_input.backend_error channel=%s exc=%s "
                    "(rate-limited 1/hr)",
                    channel_name, exc,
                )
                _record_backend_error_logged(channel_name, now)
            return FAILED_MARKER
        return render_transcription_text(result, threshold)

    return transcribe_audio


def install_voice_transcription(
    channels: Mapping[str, object],
    backend: TranscriptionBackend,
    max_duration: int,
    threshold: float,
    clock: Clock | None = None,
) -> int:
    """Patch each channel's ``transcribe_audio`` with our backend-driven override.

    The swap lands on the instance ``__dict__`` (not the class), so
    neighbouring nanobot installations are unaffected. Channels without
    a ``transcribe_audio`` attribute are skipped. Returns the number of
    channels patched.
    """
    effective_clock: Clock = clock if clock is not None else _default_clock
    patch_count = 0
    for channel_name, channel in channels.items():
        if not hasattr(channel, "transcribe_audio"):
            continue
        new_fn = _build_patched_transcribe(
            backend=backend,
            max_duration=max_duration,
            threshold=threshold,
            channel_name=channel_name,
            clock=effective_clock,
        )
        setattr(channel, "transcribe_audio", new_fn)
        patch_count += 1
    return patch_count


def _resolve_backend_label(backend: TranscriptionBackend) -> str:
    label = getattr(backend, "BACKEND_NAME", None)
    if isinstance(label, str) and label:
        return label
    return type(backend).__name__


def setup_voice_input(
    env: Mapping[str, str],
    channels: Mapping[str, object],
    *,
    backend_builder: Callable[[Mapping[str, str]], TranscriptionBackend] | None = None,
) -> int:
    """Gateway entry point. Feature-flag-gated, single-call surface.

    Returns the count of patched channels (0 when the flag is OFF).
    ``backend_builder`` is a test seam; production leaves it ``None``
    and the module defaults to
    :func:`transcription_backend.build_transcription_backend`.
    """
    if not is_voice_input_enabled(env):
        log.debug("voice_input.disabled")
        return 0
    builder = (
        backend_builder
        if backend_builder is not None
        else build_transcription_backend
    )
    backend = builder(env)
    max_duration = resolve_max_voice_duration(env)
    threshold = resolve_low_confidence_threshold(env)
    patched = install_voice_transcription(
        channels=channels,
        backend=backend,
        max_duration=max_duration,
        threshold=threshold,
    )
    log.info(
        "voice_input.ready backend=%s max_duration=%ds "
        "threshold=%.2f channels_patched=%d",
        _resolve_backend_label(backend), max_duration, threshold, patched,
    )
    return patched
