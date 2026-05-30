"""Tests for voice_generator: env cadence, snapshot, top-up + evergreen floor."""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

import voice_generator
from voice_buffer import VoiceBuffer
from voice_generator import (
    DEFAULT_TOPUP_INTERVAL_S,
    EVERGREEN_LINES,
    VoiceTopUpGenerator,
    build_topup_snapshot,
    voice_topup_from_env,
)

_NOW = datetime(2026, 5, 29, 12, 0)


class _Comment:
    def __init__(self, voice_name: str, comment: str) -> None:
        self.voice_name = voice_name
        self.comment = comment


class _Store:
    def __init__(self, items: list[Any] | None = None) -> None:
        self._items = items or []

    def list_tasks(self) -> list[Any]:
        return list(self._items)

    def list_active_buffers(self) -> list[Any]:
        return list(self._items)


def _make_gen(tmp_path: Path) -> tuple[VoiceTopUpGenerator, VoiceBuffer]:
    buf = VoiceBuffer(tmp_path / "vb.json")
    gen = VoiceTopUpGenerator(
        buffer=buf,
        config=object(),  # run_disco_chain is monkeypatched in tests
        llm_call=lambda p: "",  # unused (patched)
        task_store=_Store(),  # type: ignore[arg-type]
        buffer_store=_Store(),  # type: ignore[arg-type]
        get_cognitive_state=lambda: "focus",
        get_current_datetime=lambda: _NOW,
    )
    return gen, buf


class TestEnvCadence:
    def test_default(self) -> None:
        assert voice_topup_from_env({}) == DEFAULT_TOPUP_INTERVAL_S

    def test_parses(self) -> None:
        assert voice_topup_from_env({"CABINET_VOICE_TOPUP_S": "600"}) == 600.0

    def test_invalid_falls_back(self) -> None:
        assert voice_topup_from_env({"CABINET_VOICE_TOPUP_S": "x"}) == DEFAULT_TOPUP_INTERVAL_S


class TestSnapshot:
    def test_mentions_state_and_counts(self) -> None:
        snap = build_topup_snapshot([], [], "overwhelm")
        assert "overwhelm" in snap
        assert "0 active" in snap


class TestGenerateOnce:
    def test_fills_with_llm_and_evergreen(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def fake_chain(**_kwargs: Any) -> list[Any]:
            return [_Comment("logic", "Three remain."), _Comment("empathy", "Breathe.")]

        monkeypatch.setattr(voice_generator, "run_disco_chain", fake_chain)
        gen, buf = _make_gen(tmp_path)
        asyncio.run(gen.generate_once())
        lines = {vl.line for vl in buf.all_lines()}
        assert "Three remain." in lines           # context-aware LLM line
        assert buf.fresh_count(_NOW) >= len(EVERGREEN_LINES)  # evergreen floor present

    def test_llm_failure_degrades_to_evergreen(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def boom(**_kwargs: Any) -> list[Any]:
            raise RuntimeError("openrouter down")

        monkeypatch.setattr(voice_generator, "run_disco_chain", boom)
        gen, buf = _make_gen(tmp_path)
        asyncio.run(gen.generate_once())
        assert buf.fresh_count(_NOW) == len(EVERGREEN_LINES)  # never empty

    def test_skips_when_buffer_full(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        called = {"n": 0}

        async def fake_chain(**_kwargs: Any) -> list[Any]:
            called["n"] += 1
            return []

        monkeypatch.setattr(voice_generator, "run_disco_chain", fake_chain)
        gen, buf = _make_gen(tmp_path)
        asyncio.run(gen.generate_once())  # fills (evergreen >= min)
        n_after_first = called["n"]
        asyncio.run(gen.generate_once())  # should be a no-op now
        assert called["n"] == n_after_first


def test_file_line_budget() -> None:
    mod = Path(__file__).resolve().parents[1] / "voice_generator.py"
    assert len(mod.read_text(encoding="utf-8").splitlines()) <= 300
