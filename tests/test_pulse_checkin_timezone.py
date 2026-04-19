"""Timezone correctness for ``PulseCheckinStore.next_fire_time``.

Wall-clock ``target_time`` must survive DST — the same 08:00 local that
fires on March 7 must also fire on March 8 after spring-forward, just
one hour earlier in UTC. Ports the Rust Pulse's DST fidelity claim into
the adapter layer.

2026 DST boundaries used:
* ``America/Los_Angeles`` spring-forward: 2026-03-08 02:00 PST → 03:00 PDT.
  Wall-clock 08:00 → UTC 16:00 (PST) pre-DST, UTC 15:00 (PDT) post-DST.
* ``America/Los_Angeles`` fall-back: 2026-11-01 02:00 PDT → 01:00 PST.
  Wall-clock 08:00 → UTC 15:00 (PDT) pre-fallback, UTC 16:00 (PST) post.
* ``Europe/London`` spring-forward: 2026-03-29 01:00 UTC → 02:00 BST.
  Confirms tz is actually threaded (different boundary date than LA).
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypeVar
from zoneinfo import ZoneInfo

from checkin_schedule import ALL_CHECKIN_TYPES, CheckInScheduleStore
from pulse_checkin_store import PulseCheckinStore

LA = ZoneInfo("America/Los_Angeles")
LONDON = ZoneInfo("Europe/London")
UTC = timezone.utc

_T = TypeVar("_T")


def _run(coro: Coroutine[Any, Any, _T]) -> _T:
    return asyncio.run(coro)


def _frozen_now(moment: datetime):  # type: ignore[no-untyped-def]
    def provider() -> datetime:
        return moment

    return provider


def _make_single_entry_store(
    tmp_path: Path, keep: str = "morning_motivation",
) -> CheckInScheduleStore:
    store = CheckInScheduleStore(tmp_path / "schedules.json")
    for type_id in ALL_CHECKIN_TYPES:
        if type_id != keep:
            store.set_enabled(type_id, False)  # type: ignore[arg-type]
    return store


class TestSpringForwardLosAngeles:
    def test_day_before_dst_fires_at_16_utc(self, tmp_path: Path) -> None:
        """2026-03-07 — still PST. 08:00 local = 16:00 UTC."""
        store = _make_single_entry_store(tmp_path)
        # 2026-03-07 05:00 UTC == 2026-03-06 21:00 PST.
        now = datetime(2026, 3, 7, 5, 0, tzinfo=UTC)
        adapter = PulseCheckinStore(store, LA, now_provider=_frozen_now(now))
        assert _run(adapter.next_fire_time()) == datetime(2026, 3, 7, 16, 0, tzinfo=UTC)

    def test_day_of_dst_fires_at_15_utc(self, tmp_path: Path) -> None:
        """2026-03-08 is the spring-forward day; by 08:00 we are in PDT.
        08:00 PDT = 15:00 UTC."""
        store = _make_single_entry_store(tmp_path)
        # 2026-03-08 05:00 UTC == 2026-03-07 21:00 PST, before the spring.
        now = datetime(2026, 3, 8, 5, 0, tzinfo=UTC)
        adapter = PulseCheckinStore(store, LA, now_provider=_frozen_now(now))
        assert _run(adapter.next_fire_time()) == datetime(2026, 3, 8, 15, 0, tzinfo=UTC)

    def test_day_after_dst_fires_at_15_utc(self, tmp_path: Path) -> None:
        """2026-03-09 — first full PDT day. 08:00 PDT = 15:00 UTC."""
        store = _make_single_entry_store(tmp_path)
        # 2026-03-09 09:00 UTC == 02:00 PDT.
        now = datetime(2026, 3, 9, 9, 0, tzinfo=UTC)
        adapter = PulseCheckinStore(store, LA, now_provider=_frozen_now(now))
        assert _run(adapter.next_fire_time()) == datetime(2026, 3, 9, 15, 0, tzinfo=UTC)


class TestFallBackLosAngeles:
    def test_last_pdt_day_fires_at_15_utc(self, tmp_path: Path) -> None:
        """2026-10-31 — still PDT. 08:00 PDT = 15:00 UTC."""
        store = _make_single_entry_store(tmp_path)
        now = datetime(2026, 10, 31, 5, 0, tzinfo=UTC)  # 22:00 PDT previous day
        adapter = PulseCheckinStore(store, LA, now_provider=_frozen_now(now))
        assert _run(adapter.next_fire_time()) == datetime(2026, 10, 31, 15, 0, tzinfo=UTC)

    def test_fallback_day_fires_at_16_utc(self, tmp_path: Path) -> None:
        """2026-11-01 is fall-back day; by 08:00 we are in PST.
        08:00 PST = 16:00 UTC."""
        store = _make_single_entry_store(tmp_path)
        now = datetime(2026, 11, 1, 5, 0, tzinfo=UTC)  # 22:00 PDT previous day
        adapter = PulseCheckinStore(store, LA, now_provider=_frozen_now(now))
        assert _run(adapter.next_fire_time()) == datetime(2026, 11, 1, 16, 0, tzinfo=UTC)

    def test_day_after_fallback_fires_at_16_utc(self, tmp_path: Path) -> None:
        """2026-11-02 — first full PST day. 08:00 PST = 16:00 UTC."""
        store = _make_single_entry_store(tmp_path)
        now = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)  # 01:00 PST
        adapter = PulseCheckinStore(store, LA, now_provider=_frozen_now(now))
        assert _run(adapter.next_fire_time()) == datetime(2026, 11, 2, 16, 0, tzinfo=UTC)


class TestEuropeLondonDstDiffers:
    def test_london_dst_boundary_differs_from_la(self, tmp_path: Path) -> None:
        """2026-03-29 — London BST begins, LA already on PDT since 03-08.
        Proves the ``tz`` argument is actually threaded through.
        """
        store = _make_single_entry_store(tmp_path)
        # 2026-03-29 03:00 UTC == 04:00 BST (post-transition) in London.
        now = datetime(2026, 3, 29, 3, 0, tzinfo=UTC)
        adapter = PulseCheckinStore(store, LONDON, now_provider=_frozen_now(now))
        # 08:00 BST = 07:00 UTC.
        assert _run(adapter.next_fire_time()) == datetime(2026, 3, 29, 7, 0, tzinfo=UTC)

    def test_london_pre_dst_is_gmt(self, tmp_path: Path) -> None:
        """2026-03-28 — London still GMT. 08:00 GMT = 08:00 UTC."""
        store = _make_single_entry_store(tmp_path)
        now = datetime(2026, 3, 28, 5, 0, tzinfo=UTC)  # 05:00 GMT
        adapter = PulseCheckinStore(store, LONDON, now_provider=_frozen_now(now))
        assert _run(adapter.next_fire_time()) == datetime(2026, 3, 28, 8, 0, tzinfo=UTC)
