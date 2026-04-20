"""One-shot generator for tests/fixtures/audio/hello_world.wav.

Two paths exist:

* ``--silent`` (default): emits 1.5 s of zero-PCM samples at 16 kHz mono
  16-bit. Output is ~48 KB and ships in the repo. The Whisper local-backend
  e2e test asserts ``result.text == ""`` against this fixture (silence
  short-circuits faster-whisper's VAD filter).

* ``--kokoro``: synthesises "hello world" via the project's existing
  Kokoro TTS engine, then resamples 24 kHz → 16 kHz with a stdlib
  decimating averager. Requires the Kokoro model files in
  ``~/.nanobot/models/kokoro/``; not run in CI.

This script is gated on ``__name__ == "__main__"`` and is NOT imported
anywhere — it exists so the fixture can be regenerated deterministically
if the cap or sample rate ever changes.
"""

from __future__ import annotations

import argparse
import io
import wave
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "audio" / "hello_world.wav"

TARGET_SAMPLE_RATE = 16000
TARGET_DURATION_SECONDS = 1.5
TARGET_SAMPLE_WIDTH_BYTES = 2
SIZE_CAP_BYTES = 50_000


def write_silent_wav(path: Path) -> int:
    """Write a 1.5 s silent mono 16-bit 16 kHz WAV; return byte size."""
    n_frames = int(TARGET_SAMPLE_RATE * TARGET_DURATION_SECONDS)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(TARGET_SAMPLE_WIDTH_BYTES)
        wf.setframerate(TARGET_SAMPLE_RATE)
        wf.writeframes(b"\x00\x00" * n_frames)
    return path.stat().st_size


def synthesize_kokoro_wav_bytes(text: str) -> bytes:
    """Return Kokoro TTS WAV bytes (24 kHz mono 16-bit) for the given text."""
    from tts_engine import DEFAULT_LANG, DEFAULT_SPEED, DEFAULT_VOICE, synthesize_speech
    return synthesize_speech(text, DEFAULT_VOICE, DEFAULT_SPEED, DEFAULT_LANG)


def downsample_24k_to_16k(int16_samples: list[int]) -> list[int]:
    """Stdlib-only 24 kHz → 16 kHz decimating averager.

    Why averaged decimation: 24/16 = 3/2, so every two output samples come
    from three input samples. Averaging triples then keeping two preserves
    the speech band (≤4 kHz at 16 kHz) without aliasing well enough for a
    Whisper test fixture; we are not chasing audio fidelity here.
    """
    output: list[int] = []
    triplet: list[int] = []
    for sample in int16_samples:
        triplet.append(sample)
        if len(triplet) == 3:
            average = sum(triplet) // 3
            output.append(triplet[0])
            output.append(average)
            triplet = []
    return output


def write_kokoro_resampled_wav(path: Path, text: str) -> int:
    """Synthesise via Kokoro, resample to 16 kHz, write WAV; return byte size."""
    raw_wav = synthesize_kokoro_wav_bytes(text)
    with wave.open(io.BytesIO(raw_wav), "rb") as src:
        if src.getframerate() != 24000:
            raise RuntimeError(
                "Kokoro emitted unexpected sample rate "
                f"{src.getframerate()} Hz; generator expects 24000 Hz."
            )
        frames = src.readframes(src.getnframes())
    int16_samples = [
        int.from_bytes(frames[i:i + 2], "little", signed=True)
        for i in range(0, len(frames), 2)
    ]
    resampled = downsample_24k_to_16k(int16_samples)
    payload = b"".join(
        sample.to_bytes(2, "little", signed=True) for sample in resampled
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(TARGET_SAMPLE_WIDTH_BYTES)
        wf.setframerate(TARGET_SAMPLE_RATE)
        wf.writeframes(payload)
    return path.stat().st_size


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("silent", "kokoro"),
        default="silent",
        help="Fixture generation mode. 'silent' is the default committed shape.",
    )
    parser.add_argument(
        "--text",
        default="hello world",
        help="Text to synthesise when --mode=kokoro.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=FIXTURE_PATH,
        help="Output WAV path.",
    )
    args = parser.parse_args()

    if args.mode == "silent":
        size = write_silent_wav(args.out)
    else:
        size = write_kokoro_resampled_wav(args.out, args.text)

    if size > SIZE_CAP_BYTES:
        raise SystemExit(
            f"Fixture exceeded {SIZE_CAP_BYTES} byte cap: {size} bytes at "
            f"{args.out}. Reduce duration or switch to --mode=silent."
        )
    print(f"wrote {args.out} ({size} bytes, mode={args.mode})")


if __name__ == "__main__":
    main()
