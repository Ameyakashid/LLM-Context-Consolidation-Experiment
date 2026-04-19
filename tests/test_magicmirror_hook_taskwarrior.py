"""MagicMirror's ``tasks.md`` feed serves Taskwarrior data when the flag is on.

Proves the "data source switch" the spec calls out: no code path change,
just inject a ``TaskwarriorStore`` and the feed now contains TW-backed
tasks byte-identical to :func:`magicmirror_feeds.render_tasks_markdown`.
"""

from __future__ import annotations

import asyncio
import shutil
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

if shutil.which("task") is None:
    pytest.skip(
        "Taskwarrior CLI not installed — skipping MagicMirror+TW hook tests.",
        allow_module_level=True,
    )

pytest.importorskip("tasklib")

from buffer_store import BufferStore  # noqa: E402
from checkin_schedule import CheckInScheduleStore  # noqa: E402
from magicmirror_feeds import render_tasks_markdown  # noqa: E402
from magicmirror_hook import MagicMirrorHook  # noqa: E402
from taskwarrior_store import TaskwarriorStore  # noqa: E402


FIXED_NOW = datetime(2026, 4, 19, 10, 0, tzinfo=timezone.utc)


def _run(coro: object) -> None:
    asyncio.run(coro)  # type: ignore[arg-type]


def _build_hook(
    tmp_path: Path, task_store: TaskwarriorStore,
) -> tuple[MagicMirrorHook, Path]:
    feed_dir = tmp_path / "feeds"
    buffer_store = BufferStore(storage_path=tmp_path / "buffers.json")
    schedule_store = CheckInScheduleStore(
        storage_path=tmp_path / "checkins.json",
    )
    hook = MagicMirrorHook(
        webhook_base_url="http://127.0.0.1:8080",
        feed_dir=feed_dir,
        task_store=task_store,
        buffer_store=buffer_store,
        schedule_store=schedule_store,
        is_scheduled_session=lambda: True,
        get_cognitive_state=lambda: "baseline",
        get_current_datetime=lambda: FIXED_NOW,
    )
    return hook, feed_dir


class TestTaskwarriorFeedRefresh:
    def test_tasks_md_matches_render_of_taskwarrior_store(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "magicmirror_hook.send_alert_async", lambda payload, url: None,
        )
        tw_store = TaskwarriorStore(data_dir=tmp_path / "tw")
        tw_store.create_task("TW-only task", "high", None, None, [])

        hook, feed_dir = _build_hook(tmp_path, tw_store)
        _run(hook.before_iteration(MagicMock()))

        written = (feed_dir / "tasks.md").read_text(encoding="utf-8")
        expected = render_tasks_markdown(tw_store.list_tasks(), FIXED_NOW)
        assert written == expected

    def test_new_task_appears_in_next_refresh(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "magicmirror_hook.send_alert_async", lambda payload, url: None,
        )
        tw_store = TaskwarriorStore(data_dir=tmp_path / "tw")
        hook, feed_dir = _build_hook(tmp_path, tw_store)
        _run(hook.before_iteration(MagicMock()))

        tw_store.create_task("added between ticks", "low", None, None, [])
        _run(hook.before_iteration(MagicMock()))

        written = (feed_dir / "tasks.md").read_text(encoding="utf-8")
        assert "added between ticks" in written
