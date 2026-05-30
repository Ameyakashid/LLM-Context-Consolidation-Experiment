"""WAV-to-OGG/Opus audio conversion for Telegram voice messages.

Telegram requires OGG/Opus format for voice messages (inline waveform).
Uses PyAV (pip-installable FFmpeg bindings) for conversion since OGG/Opus
encoding requires native code — not writable in pure Python.
"""

import io
import logging
import os
import tempfile
import time
from pathlib import Path

import av

log = logging.getLogger(__name__)

OPUS_BITRATE = 32_000
OPUS_SAMPLE_RATE = 48_000  # Opus runs at 48 kHz; Telegram voice notes are mono
VOICE_TEMP_PREFIX = "voice_"
STALE_VOICE_AGE_S = 120.0


def convert_wav_to_ogg(wav_bytes: bytes) -> bytes:
    """Convert WAV audio bytes to OGG/Opus bytes for Telegram voice messages.

    Args:
        wav_bytes: Raw WAV file bytes (mono, 16-bit PCM).

    Returns:
        OGG/Opus encoded audio bytes.

    Raises:
        ValueError: If wav_bytes is empty.
    """
    if not wav_bytes:
        raise ValueError("Cannot convert empty WAV data")

    input_buffer = io.BytesIO(wav_bytes)
    output_buffer = io.BytesIO()

    with av.open(input_buffer, mode="r") as input_container:
        input_stream = input_container.streams.audio[0]

        with av.open(output_buffer, mode="w", format="ogg") as output_container:
            # Telegram voice notes want mono OGG/Opus, and Opus runs at 48 kHz.
            # Kokoro emits 24 kHz mono, so resample explicitly — otherwise the
            # frame rate disagrees with the encoder and the audio plays back
            # wrong (or Telegram rejects the note).
            output_stream = output_container.add_stream(
                "libopus", rate=OPUS_SAMPLE_RATE,
            )
            output_stream.bit_rate = OPUS_BITRATE
            output_stream.layout = "mono"  # Telegram voice notes are mono
            resampler = av.AudioResampler(
                format="s16", layout="mono", rate=OPUS_SAMPLE_RATE,
            )

            def _mux(frame: object) -> None:
                for packet in output_stream.encode(frame):
                    output_container.mux(packet)

            for frame in input_container.decode(input_stream):
                frame.pts = None
                for resampled in resampler.resample(frame):
                    _mux(resampled)
            for resampled in resampler.resample(None):  # flush the resampler
                _mux(resampled)
            _mux(None)  # flush the encoder

    return output_buffer.getvalue()


def save_temp_ogg(ogg_bytes: bytes) -> Path:
    """Save OGG bytes to a temporary file and return its path.

    Caller is responsible for cleanup via cleanup_temp_file().

    Args:
        ogg_bytes: OGG/Opus encoded audio bytes.

    Returns:
        Path to the temporary .ogg file.

    Raises:
        ValueError: If ogg_bytes is empty.
    """
    if not ogg_bytes:
        raise ValueError("Cannot save empty OGG data")

    fd, path_str = tempfile.mkstemp(suffix=".ogg", prefix=VOICE_TEMP_PREFIX)
    os.close(fd)
    path = Path(path_str)
    try:
        path.write_bytes(ogg_bytes)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path


def cleanup_temp_file(path: Path) -> None:
    """Remove a temporary file, logging but not raising on failure."""
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        log.warning("Failed to clean up temp file %s: %s", path, exc)


def sweep_stale_voice_files(
    max_age_s: float = STALE_VOICE_AGE_S, now: float | None = None,
) -> int:
    """Delete leftover ``voice_*.ogg`` temp files older than ``max_age_s``.

    The voice note is sent asynchronously (the channel opens the file from a
    bus consumer *after* the tool returns), so we must NOT delete it inline —
    that races the send and leaves Telegram opening a vanished file. Instead
    each new ``speak`` sweeps the previous notes once they're safely past the
    send window. Never raises.
    """
    cutoff = (time.time() if now is None else now) - max_age_s
    tmp_dir = Path(tempfile.gettempdir())
    removed = 0
    try:
        candidates = list(tmp_dir.glob(f"{VOICE_TEMP_PREFIX}*.ogg"))
    except OSError:
        return 0
    for path in candidates:
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
                removed += 1
        except OSError:
            continue
    return removed
