"""MagicMirror² dispatch hook for heartbeat sessions.

Runs after ``VoiceHook``, before ``DiscoHook``. On each heartbeat tick:
dispatches ``state_change`` / ``buffer_alert`` / ``missed_checkin``
webhooks to MMM-WebHookAlerts (per-day in-memory dedup) and rewrites
the three MMM-Markdown feed files atomically. Webhook sends are
fire-and-forget via :func:`send_alert_async`, which never raises on
transport failure. Feed refresh failures are caught and rate-limited
(1 WARNING per hour per hook instance) so a disk-full or render error
cannot crash the agent loop.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

from buffer_store import Buffer, BufferStore
from checkin_schedule import CheckInEntry, CheckInScheduleStore
from hook_context import HookContext
from magicmirror_feeds import (
    render_schedule_markdown,
    render_state_buffers_markdown,
    render_tasks_markdown,
    write_feeds,
)
from magicmirror_webhook import (
    BufferAlertPayload,
    MissedCheckinPayload,
    StateChangePayload,
    send_alert_async,
)
from state_detection import StateName
from task_store import TaskStoreProtocol

log = logging.getLogger(__name__)

ERROR_LOG_INTERVAL = timedelta(hours=1)
_BUFFER_ALERT_MESSAGE_FMT = (
    "{name} is at {level} of {capacity}. Refill soon."
)
_STATE_CHANGE_MESSAGE_FMT = "Cognitive state: {from_state} → {to_state}."
_MISSED_CHECKIN_MESSAGE_FMT = (
    "{display_name} was due at {target_time} and did not fire."
)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def build_webhook_base_url(host: str, port: str) -> str:
    """Return ``http://<host>:<port>`` — the base URL for MM webhooks."""
    return f"http://{host}:{port}"


def is_checkin_missed(
    entry: CheckInEntry,
    current_date: date,
    current_datetime: datetime,
) -> bool:
    """Return True when ``entry`` is enabled, past its staleness window,
    and has not already fired today.

    Mirrors the inverse of :func:`checkin_schedule.is_checkin_due`:
    ``is_checkin_due`` filters out entries past staleness; this predicate
    detects exactly those entries (so the display can surface them).
    """
    if not entry.is_enabled:
        return False
    if entry.last_run_date == current_date:
        return False
    target_dt = datetime.combine(current_date, entry.target_time)
    current_naive = (
        current_datetime.replace(tzinfo=None)
        if current_datetime.tzinfo is not None
        else current_datetime
    )
    elapsed = current_naive - target_dt
    return elapsed > timedelta(minutes=entry.staleness_minutes)


def format_state_change_message(
    from_state: StateName, to_state: StateName,
) -> str:
    """Render the ``message`` field of a StateChangePayload."""
    return _STATE_CHANGE_MESSAGE_FMT.format(
        from_state=from_state, to_state=to_state,
    )


def format_buffer_alert_message(buffer: Buffer) -> str:
    """Render the ``message`` field of a BufferAlertPayload."""
    return _BUFFER_ALERT_MESSAGE_FMT.format(
        name=buffer.name,
        level=buffer.buffer_level,
        capacity=buffer.buffer_capacity,
    )


def format_missed_checkin_message(entry: CheckInEntry) -> str:
    """Render the ``message`` field of a MissedCheckinPayload."""
    return _MISSED_CHECKIN_MESSAGE_FMT.format(
        display_name=entry.display_name,
        target_time=entry.target_time.strftime("%H:%M"),
    )


def should_log_error(
    last_log_at: datetime | None, now: datetime,
) -> bool:
    """Return True when the caller may emit the next rate-limited WARNING."""
    if last_log_at is None:
        return True
    return (now - last_log_at) >= ERROR_LOG_INTERVAL


def collect_alertable_buffers(buffers: list[Buffer]) -> list[Buffer]:
    """Return buffers at or below their alert threshold, sorted by name."""
    return sorted(
        [b for b in buffers if b.buffer_level <= b.alert_threshold],
        key=lambda b: b.name,
    )


# ---------------------------------------------------------------------------
# Hook
# ---------------------------------------------------------------------------

class MagicMirrorHook:
    """Fires MagicMirror webhooks and refreshes feed files each heartbeat.

    Construct only when ``MAGICMIRROR_ENABLED=true``. Outside of
    heartbeat sessions this hook is a no-op (gated on
    ``is_scheduled_session``). In-memory dedup (last-dispatched state,
    per-day sets for buffers and missed check-ins) resets on restart; a
    single duplicate alert after restart is the accepted tradeoff for
    avoiding disk-backed dedup.

    ``get_current_datetime`` must return a tz-aware ``datetime`` in
    ``NANOBOT_TIMEZONE`` — :func:`render_schedule_markdown` strips the
    zone before combining with naive ``entry.target_time``.
    """

    def __init__(
        self,
        webhook_base_url: str,
        feed_dir: Path,
        task_store: TaskStoreProtocol,
        buffer_store: BufferStore,
        schedule_store: CheckInScheduleStore,
        is_scheduled_session: Callable[[], bool],
        get_cognitive_state: Callable[[], StateName],
        get_current_datetime: Callable[[], datetime],
    ) -> None:
        self._webhook_base_url = webhook_base_url
        self._feed_dir = feed_dir
        self._task_store = task_store
        self._buffer_store = buffer_store
        self._schedule_store = schedule_store
        self._is_scheduled_session = is_scheduled_session
        self._get_cognitive_state = get_cognitive_state
        self._get_current_datetime = get_current_datetime
        self._last_dispatched_state: StateName | None = None
        self._missed_dispatched: set[tuple[str, date]] = set()
        self._buffer_dispatched: set[tuple[str, date]] = set()
        self._last_error_log_at: datetime | None = None

    async def before_iteration(self, context: HookContext) -> None:
        """Dispatch pending webhooks and refresh feeds; never raises."""
        try:
            self._process(context)
        # Broad except by design: a hook exception must not crash the
        # agent loop. HookAdapter already logs + swallows, but the
        # per-step handlers below give us rate-limited context.
        except Exception as exc:
            self._log_error("MagicMirror hook outer", exc)

    def _process(self, context: HookContext) -> None:
        if not self._is_scheduled_session():
            return
        now = self._get_current_datetime()
        self._dispatch_state_change(now)
        self._dispatch_buffer_alerts(now)
        self._dispatch_missed_checkins(now)
        self._refresh_feeds(now)

    def _dispatch_state_change(self, now: datetime) -> None:
        current = self._get_cognitive_state()
        if self._last_dispatched_state is None:
            self._last_dispatched_state = current
            return
        if current == self._last_dispatched_state:
            return
        from_state: StateName = self._last_dispatched_state
        payload = StateChangePayload(
            message=format_state_change_message(from_state, current),
            from_state=from_state,
            to_state=current,
            timestamp=now,
        )
        send_alert_async(payload, self._webhook_base_url)
        self._last_dispatched_state = current
        log.info(
            "MagicMirror state_change dispatched: %s → %s",
            from_state, current,
        )

    def _dispatch_buffer_alerts(self, now: datetime) -> None:
        try:
            active = self._buffer_store.list_active_buffers()
        except Exception as exc:
            self._log_error("buffer_store.list_active_buffers", exc)
            return
        today = now.date()
        for buffer in collect_alertable_buffers(active):
            key = (buffer.name, today)
            if key in self._buffer_dispatched:
                continue
            payload = BufferAlertPayload(
                message=format_buffer_alert_message(buffer),
                buffer_name=buffer.name,
                current_level=buffer.buffer_level,
                capacity=buffer.buffer_capacity,
                threshold=buffer.alert_threshold,
                timestamp=now,
            )
            send_alert_async(payload, self._webhook_base_url)
            self._buffer_dispatched.add(key)
            log.info(
                "MagicMirror buffer_alert dispatched: %s %d/%d",
                buffer.name, buffer.buffer_level, buffer.buffer_capacity,
            )

    def _dispatch_missed_checkins(self, now: datetime) -> None:
        try:
            entries = self._schedule_store.list_entries()
        except Exception as exc:
            self._log_error("schedule_store.list_entries", exc)
            return
        today = now.date()
        for entry in entries:
            if not is_checkin_missed(entry, today, now):
                continue
            key = (entry.type_id, today)
            if key in self._missed_dispatched:
                continue
            due_at = datetime.combine(today, entry.target_time)
            payload = MissedCheckinPayload(
                message=format_missed_checkin_message(entry),
                checkin_type=entry.type_id,
                due_at=due_at,
                detected_at=now,
            )
            send_alert_async(payload, self._webhook_base_url)
            self._missed_dispatched.add(key)
            log.info(
                "MagicMirror missed_checkin dispatched: %s",
                entry.type_id,
            )

    def _refresh_feeds(self, now: datetime) -> None:
        try:
            tasks = self._task_store.list_tasks()
            buffers = self._buffer_store.list_active_buffers()
            entries = self._schedule_store.list_entries()
            state = self._get_cognitive_state()
            tasks_md = render_tasks_markdown(tasks, now)
            state_buffers_md = render_state_buffers_markdown(
                state, buffers, now,
            )
            schedule_md = render_schedule_markdown(entries, now)
            write_feeds(
                self._feed_dir, tasks_md, state_buffers_md, schedule_md,
            )
        except Exception as exc:
            self._log_error("refresh_feeds", exc)

    def _log_error(self, scope: str, exc: Exception) -> None:
        now = self._get_current_datetime()
        if not should_log_error(self._last_error_log_at, now):
            return
        log.warning(
            "MagicMirror hook %s failed (rate-limited 1/hr): %s",
            scope, exc,
        )
        self._last_error_log_at = now
