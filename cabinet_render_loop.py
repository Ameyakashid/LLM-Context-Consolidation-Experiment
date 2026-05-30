"""Background render loop that keeps the Cabinet feeds fresh.

Decoupled from the ~30-min heartbeat: an asyncio task re-renders the
tasks / state+buffers / schedule feeds from the live stores every
``interval_s`` (default 30s) so the wall display tracks reality within a
poll cycle. Pure rendering only — no LLM, no network. Each tick is wrapped
so a render error is swallowed + rate-limited (1 WARNING/hr) and never
kills the loop.

The loop reuses the same renderers + atomic writer the heartbeat hook used
(:mod:`magicmirror_feeds`); ``MagicMirrorHook`` no longer writes feeds.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from cabinet_alerts import AlertEvaluator

from buffer_store import BufferStore
from checkin_schedule import CheckInScheduleStore
from magicmirror_feeds import (
    render_schedule_markdown,
    render_state_buffers_markdown,
    render_tasks_markdown,
    render_voices_markdown,
    write_feeds,
    write_voices_feed,
)
from state_detection import StateName
from task_store import TaskStoreProtocol
from voice_buffer import VoiceBuffer

log = logging.getLogger(__name__)

DEFAULT_RENDER_INTERVAL_S = 30.0
ERROR_LOG_INTERVAL = timedelta(hours=1)


def render_interval_from_env(
    env: Mapping[str, str] | None,
    default: float = DEFAULT_RENDER_INTERVAL_S,
) -> float:
    """Return the render interval from ``CABINET_RENDER_S`` (default 30s).

    Blank/invalid/non-positive values fall back to ``default``.
    """
    raw = (env or {}).get("CABINET_RENDER_S", "").strip()
    if not raw:
        return default
    try:
        val = float(raw)
    except ValueError:
        return default
    return val if val > 0 else default


class CabinetRenderLoop:
    """Re-renders the three live feeds on a fixed cadence, off the heartbeat.

    ``get_current_datetime`` must return a tz-aware ``datetime`` in
    ``NANOBOT_TIMEZONE`` (:func:`render_schedule_markdown` strips the zone
    before combining with naive ``entry.target_time``).
    """

    def __init__(
        self,
        feed_dir: Path,
        task_store: TaskStoreProtocol,
        buffer_store: BufferStore,
        schedule_store: CheckInScheduleStore,
        get_cognitive_state: Callable[[], StateName],
        get_current_datetime: Callable[[], datetime],
        interval_s: float = DEFAULT_RENDER_INTERVAL_S,
        voice_buffer: VoiceBuffer | None = None,
        alert_evaluator: "AlertEvaluator | None" = None,
    ) -> None:
        self._feed_dir = feed_dir
        self._task_store = task_store
        self._buffer_store = buffer_store
        self._schedule_store = schedule_store
        self._get_cognitive_state = get_cognitive_state
        self._get_current_datetime = get_current_datetime
        self._interval_s = interval_s
        self._voice_buffer = voice_buffer
        self._alert_evaluator = alert_evaluator
        self._task: asyncio.Task[None] | None = None
        self._last_error_log_at: datetime | None = None

    def render_once(self, now: datetime) -> None:
        """Render and atomically write the feed files for ``now``.

        Always writes tasks/state/schedule; also writes ``voices.md`` from
        the voice buffer when one is wired in.
        """
        tasks = self._task_store.list_tasks()
        buffers = self._buffer_store.list_active_buffers()
        entries = self._schedule_store.list_entries()
        state = self._get_cognitive_state()
        write_feeds(
            self._feed_dir,
            render_tasks_markdown(tasks, now),
            render_state_buffers_markdown(state, buffers, now),
            render_schedule_markdown(entries, now),
        )
        if self._voice_buffer is not None:
            voices = [(vl.who, vl.line) for vl in self._voice_buffer.current()]
            write_voices_feed(self._feed_dir, render_voices_markdown(voices))
        if self._alert_evaluator is not None:
            self._alert_evaluator.evaluate(now, state, buffers, entries)

    def tick(self) -> None:
        """Run one render, swallowing + rate-limiting any error."""
        try:
            self.render_once(self._get_current_datetime())
        except Exception as exc:  # never let a render error kill the loop
            self._log_error(exc)

    async def _run(self) -> None:
        while True:
            self.tick()
            await asyncio.sleep(self._interval_s)

    async def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run())
        log.info(
            "Cabinet render loop started (every %.0fs) -> %s",
            self._interval_s, self._feed_dir,
        )

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def _log_error(self, exc: Exception) -> None:
        now = self._get_current_datetime()
        if (
            self._last_error_log_at is not None
            and (now - self._last_error_log_at) < ERROR_LOG_INTERVAL
        ):
            return
        log.warning(
            "Cabinet render loop tick failed (rate-limited 1/hr): %s", exc,
        )
        self._last_error_log_at = now
