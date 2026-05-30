"""Polled alert queue + evaluator for the Cabinet display.

The Cabinet is a static page, so overlay alerts are delivered by a polled
JSON queue instead of a socket push: the backend appends envelopes to
``cabinet/feeds/alerts.json`` (monotonic ids, last ~20 kept) and the page
polls every ~5s, firing each new id via ``window.MM.fireAlert`` and
de-duping by id.

:class:`AlertEvaluator` owns the per-day dedup that ``MagicMirrorHook`` used
to hold and runs inside the 30s render loop — so state changes, low buffers,
and missed check-ins surface within a poll cycle (not only on the heartbeat).
The three overlay mappers mirror the Cabinet's built-in demo voice.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path

from buffer_store import Buffer
from checkin_schedule import CheckInEntry

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pure detection predicates (relocated from the retired MagicMirrorHook)
# ---------------------------------------------------------------------------

def collect_alertable_buffers(buffers: list[Buffer]) -> list[Buffer]:
    """Return buffers at or below their alert threshold, sorted by name."""
    return sorted(
        [b for b in buffers if b.buffer_level <= b.alert_threshold],
        key=lambda b: b.name,
    )


def is_checkin_missed(
    entry: CheckInEntry, current_date: date, current_datetime: datetime,
) -> bool:
    """True when ``entry`` is enabled, past its staleness window, unrun today."""
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

ALERTS_FEED_FILENAME = "alerts.json"
DEFAULT_MAX_ALERTS = 20
ALERT_TYPES = ("state_change", "buffer_alert", "missed_checkin")


def _em(text: object) -> str:
    """Wrap text in the overlay's accent-emphasis span."""
    return f'<span class="em">{text}</span>'


def overlay_state_change(from_state: str, to_state: str) -> dict[str, str]:
    return {
        "title": "State Change",
        "message": f"from {_em(from_state)} to {_em(to_state)}",
    }


def overlay_buffer_alert(name: str, level: int, capacity: int) -> dict[str, str]:
    return {
        "title": "Buffer Low",
        "message": f"{_em(name)} at {level}/{capacity}. The body is asking.",
    }


def overlay_missed_checkin(name: str, target_hhmm: str) -> dict[str, str]:
    return {
        "title": "Missed Check-in",
        "message": f"{_em(name)} — target {target_hhmm}.",
    }


def trim_alerts(alerts: list[dict], max_alerts: int = DEFAULT_MAX_ALERTS) -> list[dict]:
    """Keep only the most recent ``max_alerts`` envelopes (oldest dropped)."""
    return alerts[-max_alerts:] if len(alerts) > max_alerts else list(alerts)


class AlertQueue:
    """JSON-backed, monotonic-id alert queue served at ``feeds/alerts.json``."""

    def __init__(self, path: Path, max_alerts: int = DEFAULT_MAX_ALERTS) -> None:
        self._path = path
        self._max = max_alerts
        self._alerts = self._load()
        self._next_id = max((a.get("id", 0) for a in self._alerts), default=0) + 1

    def _load(self) -> list[dict]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        alerts = data.get("alerts") if isinstance(data, dict) else None
        return alerts if isinstance(alerts, list) else []

    def _persist(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"alerts": self._alerts}, ensure_ascii=False),
            encoding="utf-8", newline="\n",
        )
        tmp.replace(self._path)

    def push(self, alert_type: str, payload: dict[str, str]) -> int:
        """Append an envelope, trim, persist; return its id."""
        alert_id = self._next_id
        self._next_id += 1
        self._alerts.append({"id": alert_id, "type": alert_type, "payload": payload})
        self._alerts = trim_alerts(self._alerts, self._max)
        self._persist()
        log.info("Cabinet alert queued: #%d %s", alert_id, alert_type)
        return alert_id

    def all(self) -> list[dict]:
        return list(self._alerts)


class AlertEvaluator:
    """Detects fire-worthy alerts each tick and enqueues overlays (per-day dedup)."""

    def __init__(self, queue: AlertQueue) -> None:
        self._q = queue
        self._last_state: str | None = None
        self._buffer_dispatched: set[tuple[str, date]] = set()
        self._missed_dispatched: set[tuple[str, date]] = set()

    def evaluate(
        self,
        now: datetime,
        state: str,
        buffers: list[Buffer],
        entries: list[CheckInEntry],
    ) -> None:
        self._eval_state(state)
        self._eval_buffers(now, buffers)
        self._eval_missed(now, entries)

    def _eval_state(self, state: str) -> None:
        # Prime on first observation (no overlay), then fire on each change.
        if self._last_state is None:
            self._last_state = state
            return
        if state == self._last_state:
            return
        self._q.push("state_change", overlay_state_change(self._last_state, state))
        self._last_state = state

    def _eval_buffers(self, now: datetime, buffers: list[Buffer]) -> None:
        today = now.date()
        for buf in collect_alertable_buffers(buffers):
            key = (buf.name, today)
            if key in self._buffer_dispatched:
                continue
            self._q.push(
                "buffer_alert",
                overlay_buffer_alert(buf.name, buf.buffer_level, buf.buffer_capacity),
            )
            self._buffer_dispatched.add(key)

    def _eval_missed(self, now: datetime, entries: list[CheckInEntry]) -> None:
        today = now.date()
        for entry in entries:
            if not is_checkin_missed(entry, today, now):
                continue
            key = (entry.type_id, today)
            if key in self._missed_dispatched:
                continue
            self._q.push(
                "missed_checkin",
                overlay_missed_checkin(
                    entry.display_name, entry.target_time.strftime("%H:%M"),
                ),
            )
            self._missed_dispatched.add(key)
