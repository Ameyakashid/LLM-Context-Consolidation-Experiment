"""Tests for ``pulse_system_concerns`` — Dream concern store + composite.

Covers:

* ``is_dream_state_enabled`` truthy convention (``"true"`` only).
* ``read_last_run`` / ``write_last_run`` round-trip + atomic write.
* ``should_skip_catchup`` windowing.
* ``DreamConcernStore.next_fire_time`` — fresh bot, inside window,
  outside window with missed slot, invalid cron.
* ``DreamConcernStore.claim_due_concerns`` — skip inside window, fire
  outside window, tz-aware required.
* ``CompositePulseStore`` — merges fire times + claim lists, empty
  members rejected.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from pulse_system_concerns import (
    CompositePulseStore,
    DEFAULT_DREAM_CRON,
    DREAM_CONCERN_ID,
    DreamConcernStore,
    is_dream_state_enabled,
    read_last_run,
    should_skip_catchup,
    write_last_run,
)


UTC = timezone.utc
NYC = ZoneInfo("America/New_York")


def _run(coro: object) -> object:
    return asyncio.run(coro)  # type: ignore[arg-type]


class TestIsDreamStateEnabled:
    def test_missing_defaults_false(self) -> None:
        assert is_dream_state_enabled({}) is False

    def test_true_string_enables(self) -> None:
        assert is_dream_state_enabled({"DREAM_STATE_ENABLED": "true"}) is True

    def test_case_insensitive(self) -> None:
        assert is_dream_state_enabled({"DREAM_STATE_ENABLED": "TRUE"}) is True
        assert is_dream_state_enabled({"DREAM_STATE_ENABLED": "True"}) is True

    def test_whitespace_stripped(self) -> None:
        assert is_dream_state_enabled({"DREAM_STATE_ENABLED": "  true  "}) is True

    def test_alternate_truthy_rejected(self) -> None:
        for value in ("1", "yes", "on", "y"):
            assert is_dream_state_enabled({"DREAM_STATE_ENABLED": value}) is False


class TestLastRunIO:
    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        assert read_last_run(tmp_path / "absent.json") is None

    def test_round_trip(self, tmp_path: Path) -> None:
        path = tmp_path / "dream_last_run.json"
        when = datetime(2026, 4, 19, 3, 0, tzinfo=UTC)
        write_last_run(path, when)
        assert read_last_run(path) == when

    def test_atomic_write_no_tmp_leftover(self, tmp_path: Path) -> None:
        path = tmp_path / "dream_last_run.json"
        write_last_run(path, datetime(2026, 4, 19, 3, 0, tzinfo=UTC))
        assert path.exists()
        assert not path.with_suffix(".tmp").exists()

    def test_naive_datetime_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="tz-aware"):
            write_last_run(tmp_path / "x.json", datetime(2026, 4, 19, 3, 0))

    def test_corrupt_json_returns_none(self, tmp_path: Path) -> None:
        path = tmp_path / "dream_last_run.json"
        path.write_text("not json", encoding="utf-8")
        assert read_last_run(path) is None

    def test_missing_key_returns_none(self, tmp_path: Path) -> None:
        path = tmp_path / "dream_last_run.json"
        path.write_text('{"something_else": "x"}', encoding="utf-8")
        assert read_last_run(path) is None

    def test_parent_dir_created(self, tmp_path: Path) -> None:
        nested = tmp_path / "data" / "dream_last_run.json"
        write_last_run(nested, datetime(2026, 4, 19, 3, 0, tzinfo=UTC))
        assert nested.exists()


class TestShouldSkipCatchup:
    def test_none_last_run_never_skips(self) -> None:
        now = datetime(2026, 4, 19, 12, 0, tzinfo=UTC)
        assert should_skip_catchup(None, now, 12) is False

    def test_inside_window_skips(self) -> None:
        now = datetime(2026, 4, 19, 12, 0, tzinfo=UTC)
        last = now - timedelta(hours=6)
        assert should_skip_catchup(last, now, 12) is True

    def test_outside_window_does_not_skip(self) -> None:
        now = datetime(2026, 4, 19, 12, 0, tzinfo=UTC)
        last = now - timedelta(hours=13)
        assert should_skip_catchup(last, now, 12) is False

    def test_naive_raises(self) -> None:
        with pytest.raises(ValueError):
            should_skip_catchup(
                datetime(2026, 4, 19, 0, 0),
                datetime(2026, 4, 19, 12, 0, tzinfo=UTC),
                12,
            )


class TestDreamConcernStoreNextFire:
    def _store(
        self, tmp_path: Path, now: datetime, cron: str = DEFAULT_DREAM_CRON,
    ) -> DreamConcernStore:
        return DreamConcernStore(
            cron_expr=cron,
            tz=NYC,
            last_run_path=tmp_path / "dream_last_run.json",
            now_provider=lambda: now,
        )

    def test_fresh_bot_returns_next_slot(self, tmp_path: Path) -> None:
        now = datetime(2026, 4, 19, 20, 0, tzinfo=UTC)
        store = self._store(tmp_path, now)
        fire_at = _run(store.next_fire_time())
        assert isinstance(fire_at, datetime)
        assert fire_at > now  # type: ignore[operator]

    def test_inside_skip_window_returns_next_slot_strictly_after_now(
        self, tmp_path: Path,
    ) -> None:
        now = datetime(2026, 4, 19, 10, 0, tzinfo=UTC)
        write_last_run(
            tmp_path / "dream_last_run.json", now - timedelta(hours=4),
        )
        store = self._store(tmp_path, now)
        fire_at = _run(store.next_fire_time())
        assert fire_at is not None
        assert fire_at > now  # type: ignore[operator]

    def test_outside_skip_window_with_missed_slot_fires_now(
        self, tmp_path: Path,
    ) -> None:
        now = datetime(2026, 4, 19, 20, 0, tzinfo=UTC)
        write_last_run(
            tmp_path / "dream_last_run.json", now - timedelta(hours=48),
        )
        store = self._store(tmp_path, now)
        fire_at = _run(store.next_fire_time())
        assert fire_at == now

    def test_invalid_cron_returns_none(self, tmp_path: Path) -> None:
        now = datetime(2026, 4, 19, 20, 0, tzinfo=UTC)
        store = self._store(tmp_path, now, cron="garbage cron")
        assert _run(store.next_fire_time()) is None


class TestDreamConcernStoreClaim:
    def _store(
        self, tmp_path: Path, now: datetime,
    ) -> DreamConcernStore:
        return DreamConcernStore(
            cron_expr=DEFAULT_DREAM_CRON,
            tz=NYC,
            last_run_path=tmp_path / "dream_last_run.json",
            now_provider=lambda: now,
        )

    def test_fresh_bot_claims_when_slot_passed(self, tmp_path: Path) -> None:
        now = datetime(2026, 4, 19, 12, 0, tzinfo=UTC)
        store = self._store(tmp_path, now)
        claimed = _run(store.claim_due_concerns(now))
        assert claimed == [DREAM_CONCERN_ID]

    def test_inside_skip_window_does_not_claim(self, tmp_path: Path) -> None:
        now = datetime(2026, 4, 19, 12, 0, tzinfo=UTC)
        write_last_run(
            tmp_path / "dream_last_run.json", now - timedelta(hours=6),
        )
        store = self._store(tmp_path, now)
        assert _run(store.claim_due_concerns(now)) == []

    def test_outside_window_with_missed_slot_claims(self, tmp_path: Path) -> None:
        now = datetime(2026, 4, 19, 20, 0, tzinfo=UTC)
        write_last_run(
            tmp_path / "dream_last_run.json", now - timedelta(hours=48),
        )
        store = self._store(tmp_path, now)
        assert _run(store.claim_due_concerns(now)) == [DREAM_CONCERN_ID]

    def test_naive_now_rejected(self, tmp_path: Path) -> None:
        store = self._store(tmp_path, datetime(2026, 4, 19, 20, 0, tzinfo=UTC))
        with pytest.raises(ValueError, match="tz-aware"):
            _run(store.claim_due_concerns(datetime(2026, 4, 19, 20, 0)))


class TestCompositePulseStore:
    def test_empty_stores_rejected(self) -> None:
        with pytest.raises(ValueError, match="at least one"):
            CompositePulseStore([])

    def test_next_fire_time_picks_minimum(self) -> None:
        class Fixed:
            def __init__(self, fire_at: datetime | None) -> None:
                self._fire_at = fire_at

            async def next_fire_time(self) -> datetime | None:
                return self._fire_at

            async def claim_due_concerns(
                self, now: datetime,
            ) -> list[str]:
                return []

        earlier = datetime(2026, 4, 19, 8, 0, tzinfo=UTC)
        later = datetime(2026, 4, 19, 12, 0, tzinfo=UTC)
        composite = CompositePulseStore([Fixed(later), Fixed(earlier)])  # type: ignore[list-item]
        assert _run(composite.next_fire_time()) == earlier

    def test_next_fire_time_all_none_returns_none(self) -> None:
        class Empty:
            async def next_fire_time(self) -> datetime | None:
                return None

            async def claim_due_concerns(
                self, now: datetime,
            ) -> list[str]:
                return []

        composite = CompositePulseStore([Empty(), Empty()])  # type: ignore[list-item]
        assert _run(composite.next_fire_time()) is None

    def test_claim_merges_lists_in_order(self) -> None:
        class Stub:
            def __init__(self, ids: list[str]) -> None:
                self._ids = ids

            async def next_fire_time(self) -> datetime | None:
                return None

            async def claim_due_concerns(
                self, now: datetime,
            ) -> list[str]:
                return list(self._ids)

        composite = CompositePulseStore(
            [Stub(["morning_motivation"]), Stub(["dream_state"])],  # type: ignore[list-item]
        )
        now = datetime(2026, 4, 19, 20, 0, tzinfo=UTC)
        claimed = _run(composite.claim_due_concerns(now))
        assert claimed == ["morning_motivation", "dream_state"]
