"""Tests for MagicMirrorHook lifecycle (before_iteration paths).

Covers gating on ``is_scheduled_session``, one-shot state-change dispatch,
per-day buffer and missed-checkin dedup, feed-file refresh, and the
rate-limited error log when ``write_feeds`` fails.

All webhook sends are patched to capture-only (no real threads) so tests
are deterministic.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from buffer_store import Buffer
from checkin_schedule import CheckInEntry
from magicmirror_hook import MagicMirrorHook
from magicmirror_webhook import (
    BufferAlertPayload,
    MissedCheckinPayload,
    StateChangePayload,
)


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _buffer(
    name: str = "rent",
    level: int = 2,
    capacity: int = 4,
    threshold: int = 2,
) -> Buffer:
    now = datetime(2026, 4, 19, 10, 0)
    return Buffer(
        id=f"b-{name}",
        name=name,
        buffer_level=level,
        buffer_capacity=capacity,
        recurrence_interval_days=30,
        next_due_date=date(2026, 5, 1),
        alert_threshold=threshold,
        status="active",
        created_at=now,
        updated_at=now,
    )


def _entry(hour: int = 8, staleness: int = 120) -> CheckInEntry:
    return CheckInEntry(
        type_id="morning_motivation",
        display_name="Morning Motivation",
        target_time=time(hour, 0),
        staleness_minutes=staleness,
        is_enabled=True,
        last_run_date=None,
    )


class _FakeStore:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def list_tasks(self) -> list[Any]:
        return list(self._items)

    def list_active_buffers(self) -> list[Any]:
        return list(self._items)

    def list_entries(self) -> list[Any]:
        return list(self._items)


def _make_hook(
    tmp_path: Path,
    is_scheduled: bool = True,
    state: str = "baseline",
    buffers: list[Buffer] | None = None,
    entries: list[CheckInEntry] | None = None,
    now: datetime | None = None,
) -> MagicMirrorHook:
    return MagicMirrorHook(
        webhook_base_url="http://127.0.0.1:8080",
        feed_dir=tmp_path / "feeds",
        task_store=_FakeStore([]),  # type: ignore[arg-type]
        buffer_store=_FakeStore(buffers or []),  # type: ignore[arg-type]
        schedule_store=_FakeStore(entries or []),  # type: ignore[arg-type]
        is_scheduled_session=lambda: is_scheduled,
        get_cognitive_state=lambda: state,
        get_current_datetime=lambda: now or datetime(2026, 4, 19, 10, 0),
    )


class TestBeforeIterationGating:

    def test_noop_outside_heartbeat(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        sent: list[Any] = []
        monkeypatch.setattr(
            "magicmirror_hook.send_alert_async",
            lambda p, u: sent.append((p, u)),
        )
        hook = _make_hook(tmp_path, is_scheduled=False)
        _run(hook.before_iteration(MagicMock()))
        assert sent == []
        assert not (tmp_path / "feeds").exists()

    def test_outer_exception_is_swallowed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "magicmirror_hook.send_alert_async", lambda p, u: None,
        )
        hook = _make_hook(tmp_path)

        def explode() -> bool:
            raise RuntimeError("boom")

        hook._is_scheduled_session = explode
        _run(hook.before_iteration(MagicMock()))


class TestStateChangeDispatch:

    def test_first_call_primes_no_dispatch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        sent: list[StateChangePayload] = []
        monkeypatch.setattr(
            "magicmirror_hook.send_alert_async",
            lambda p, u: sent.append(p) if isinstance(
                p, StateChangePayload
            ) else None,
        )
        hook = _make_hook(tmp_path, state="baseline")
        _run(hook.before_iteration(MagicMock()))
        assert sent == []
        assert hook._last_dispatched_state == "baseline"

    def test_state_transition_dispatches_once(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        sent: list[StateChangePayload] = []
        monkeypatch.setattr(
            "magicmirror_hook.send_alert_async",
            lambda p, u: sent.append(p) if isinstance(
                p, StateChangePayload
            ) else None,
        )
        state_ref = {"value": "baseline"}
        hook = MagicMirrorHook(
            webhook_base_url="http://127.0.0.1:8080",
            feed_dir=tmp_path / "feeds",
            task_store=_FakeStore([]),  # type: ignore[arg-type]
            buffer_store=_FakeStore([]),  # type: ignore[arg-type]
            schedule_store=_FakeStore([]),  # type: ignore[arg-type]
            is_scheduled_session=lambda: True,
            get_cognitive_state=lambda: state_ref["value"],
            get_current_datetime=lambda: datetime(2026, 4, 19, 10, 0),
        )
        _run(hook.before_iteration(MagicMock()))
        state_ref["value"] = "flow"
        _run(hook.before_iteration(MagicMock()))
        _run(hook.before_iteration(MagicMock()))
        assert len(sent) == 1
        assert sent[0].from_state == "baseline"
        assert sent[0].to_state == "flow"


class TestBufferAlertDispatch:

    def test_only_alertable_buffers_dispatched(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        sent: list[BufferAlertPayload] = []
        monkeypatch.setattr(
            "magicmirror_hook.send_alert_async",
            lambda p, u: sent.append(p) if isinstance(
                p, BufferAlertPayload
            ) else None,
        )
        low = _buffer("rent", level=1, threshold=2)
        high = _buffer("milk", level=4, threshold=2)
        hook = _make_hook(tmp_path, buffers=[high, low])
        _run(hook.before_iteration(MagicMock()))
        assert [p.buffer_name for p in sent] == ["rent"]

    def test_same_day_dedup(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        sent: list[BufferAlertPayload] = []
        monkeypatch.setattr(
            "magicmirror_hook.send_alert_async",
            lambda p, u: sent.append(p) if isinstance(
                p, BufferAlertPayload
            ) else None,
        )
        low = _buffer("rent", level=1, threshold=2)
        hook = _make_hook(tmp_path, buffers=[low])
        _run(hook.before_iteration(MagicMock()))
        _run(hook.before_iteration(MagicMock()))
        assert len(sent) == 1


class TestMissedCheckinDispatch:

    def test_missed_checkin_dispatched_once_per_day(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        sent: list[MissedCheckinPayload] = []
        monkeypatch.setattr(
            "magicmirror_hook.send_alert_async",
            lambda p, u: sent.append(p) if isinstance(
                p, MissedCheckinPayload
            ) else None,
        )
        entry = _entry(hour=8, staleness=60)
        now = datetime(2026, 4, 19, 10, 0)
        hook = _make_hook(tmp_path, entries=[entry], now=now)
        _run(hook.before_iteration(MagicMock()))
        _run(hook.before_iteration(MagicMock()))
        assert len(sent) == 1
        assert sent[0].checkin_type == "morning_motivation"

    def test_non_missed_entry_is_ignored(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        sent: list[MissedCheckinPayload] = []
        monkeypatch.setattr(
            "magicmirror_hook.send_alert_async",
            lambda p, u: sent.append(p) if isinstance(
                p, MissedCheckinPayload
            ) else None,
        )
        entry = _entry(hour=8, staleness=240)
        now = datetime(2026, 4, 19, 9, 30)
        hook = _make_hook(tmp_path, entries=[entry], now=now)
        _run(hook.before_iteration(MagicMock()))
        assert sent == []


class TestFeedRefresh:

    def test_writes_three_feed_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "magicmirror_hook.send_alert_async", lambda p, u: None,
        )
        hook = _make_hook(tmp_path)
        _run(hook.before_iteration(MagicMock()))
        feed_dir = tmp_path / "feeds"
        assert (feed_dir / "tasks.md").exists()
        assert (feed_dir / "state_buffers.md").exists()
        assert (feed_dir / "schedule.md").exists()

    def test_refresh_failure_is_rate_limited(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "magicmirror_hook.send_alert_async", lambda p, u: None,
        )

        def broken(*_a: Any, **_k: Any) -> None:
            raise OSError("disk full")

        monkeypatch.setattr("magicmirror_hook.write_feeds", broken)
        hook = _make_hook(tmp_path)
        _run(hook.before_iteration(MagicMock()))
        assert hook._last_error_log_at is not None
