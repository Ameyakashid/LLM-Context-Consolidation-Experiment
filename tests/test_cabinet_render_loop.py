"""Tests for CabinetRenderLoop: rendering, error-swallowing, lifecycle, env."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from cabinet_render_loop import (
    DEFAULT_RENDER_INTERVAL_S,
    CabinetRenderLoop,
    render_interval_from_env,
)

_NOW = datetime(2026, 4, 19, 10, 0)


class _Store:
    def __init__(self, items: list[Any] | None = None, raises: bool = False) -> None:
        self._items = items or []
        self._raises = raises

    def list_tasks(self) -> list[Any]:
        if self._raises:
            raise RuntimeError("store boom")
        return list(self._items)

    def list_active_buffers(self) -> list[Any]:
        return list(self._items)

    def list_entries(self) -> list[Any]:
        return list(self._items)


def _make_loop(tmp_path: Path, *, raises: bool = False, interval_s: float = 30.0) -> CabinetRenderLoop:
    return CabinetRenderLoop(
        feed_dir=tmp_path / "feeds",
        task_store=_Store(raises=raises),  # type: ignore[arg-type]
        buffer_store=_Store(),  # type: ignore[arg-type]
        schedule_store=_Store(),  # type: ignore[arg-type]
        get_cognitive_state=lambda: "baseline",
        get_current_datetime=lambda: _NOW,
        interval_s=interval_s,
    )


class TestRenderOnce:
    def test_writes_three_feed_files(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        loop.render_once(_NOW)
        feed_dir = tmp_path / "feeds"
        assert (feed_dir / "tasks.md").read_text(encoding="utf-8").startswith("## Active")
        sb = (feed_dir / "state_buffers.md").read_text(encoding="utf-8")
        assert "## Cognitive state: baseline" in sb
        sched = (feed_dir / "schedule.md").read_text(encoding="utf-8")
        assert "## Check-in schedule" in sched


class TestVoicesFeed:
    def test_writes_voices_md_from_buffer(self, tmp_path: Path) -> None:
        from datetime import timedelta

        from voice_buffer import VoiceBuffer, VoiceLine

        buf = VoiceBuffer(tmp_path / "vb.json")
        buf.add([VoiceLine(who="LOGIC", line="Three remain.", created_at=_NOW)])
        loop = CabinetRenderLoop(
            feed_dir=tmp_path / "feeds",
            task_store=_Store(),  # type: ignore[arg-type]
            buffer_store=_Store(),  # type: ignore[arg-type]
            schedule_store=_Store(),  # type: ignore[arg-type]
            get_cognitive_state=lambda: "baseline",
            get_current_datetime=lambda: _NOW,
            voice_buffer=buf,
        )
        loop.render_once(_NOW)
        voices = (tmp_path / "feeds" / "voices.md").read_text(encoding="utf-8")
        assert "## Voices" in voices
        assert "- LOGIC — Three remain." in voices

    def test_no_voices_file_without_buffer(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)  # no voice_buffer
        loop.render_once(_NOW)
        assert not (tmp_path / "feeds" / "voices.md").exists()


class TestAlertEvaluation:
    def test_render_once_pushes_buffer_alert(self, tmp_path: Path) -> None:
        from datetime import date

        from buffer_store import Buffer
        from cabinet_alerts import AlertEvaluator, AlertQueue

        low = Buffer(
            id="b", name="rent", buffer_level=1, buffer_capacity=4,
            recurrence_interval_days=30, next_due_date=date(2026, 6, 1),
            alert_threshold=2, status="active", created_at=_NOW, updated_at=_NOW,
        )
        queue = AlertQueue(tmp_path / "feeds" / "alerts.json")
        loop = CabinetRenderLoop(
            feed_dir=tmp_path / "feeds",
            task_store=_Store(),  # type: ignore[arg-type]
            buffer_store=_Store([low]),  # type: ignore[arg-type]
            schedule_store=_Store(),  # type: ignore[arg-type]
            get_cognitive_state=lambda: "baseline",
            get_current_datetime=lambda: _NOW,
            alert_evaluator=AlertEvaluator(queue),
        )
        loop.render_once(_NOW)
        assert [a["type"] for a in queue.all()] == ["buffer_alert"]


class TestTickErrorHandling:
    def test_store_exception_swallowed_and_logged(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.WARNING, logger="cabinet_render_loop")
        loop = _make_loop(tmp_path, raises=True)
        loop.tick()  # must not raise
        assert loop._last_error_log_at is not None
        assert any("tick failed" in r.getMessage() for r in caplog.records)

    def test_error_log_rate_limited(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.WARNING, logger="cabinet_render_loop")
        loop = _make_loop(tmp_path, raises=True)
        loop.tick()
        loop.tick()  # same fixed clock -> within 1hr -> suppressed
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1


class TestLifecycle:
    def test_start_renders_then_stop(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path, interval_s=1000.0)

        async def scenario() -> bool:
            await loop.start()
            await asyncio.sleep(0.05)  # let the first tick run
            running = loop.is_running()
            await loop.stop()
            return running

        running = asyncio.run(scenario())
        assert running is True
        assert (tmp_path / "feeds" / "tasks.md").exists()
        assert loop.is_running() is False

    def test_stop_without_start_is_noop(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        asyncio.run(loop.stop())
        assert loop.is_running() is False


class TestRenderIntervalFromEnv:
    def test_default_when_blank(self) -> None:
        assert render_interval_from_env({}) == DEFAULT_RENDER_INTERVAL_S

    def test_default_when_none(self) -> None:
        assert render_interval_from_env(None) == DEFAULT_RENDER_INTERVAL_S

    def test_parses_value(self) -> None:
        assert render_interval_from_env({"CABINET_RENDER_S": "15"}) == 15.0

    def test_invalid_falls_back(self) -> None:
        assert render_interval_from_env({"CABINET_RENDER_S": "abc"}) == DEFAULT_RENDER_INTERVAL_S

    def test_non_positive_falls_back(self) -> None:
        assert render_interval_from_env({"CABINET_RENDER_S": "0"}) == DEFAULT_RENDER_INTERVAL_S


def test_file_line_budget() -> None:
    mod = Path(__file__).resolve().parents[1] / "cabinet_render_loop.py"
    assert len(mod.read_text(encoding="utf-8").splitlines()) <= 300
