"""Tests for the TTL + FIFO CalendarCache."""

from __future__ import annotations

import pytest

from calendar_cache import CalendarCache


class FakeClock:
    """Monotonic clock that advances by explicit ticks for deterministic TTL tests."""

    def __init__(self, start: float = 0.0) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


class TestCalendarCacheConstruction:
    def test_default_construction(self) -> None:
        cache = CalendarCache()
        assert cache.size == 0

    def test_zero_ttl_rejected(self) -> None:
        with pytest.raises(ValueError, match="ttl_seconds must be positive"):
            CalendarCache(ttl_seconds=0)

    def test_negative_ttl_rejected(self) -> None:
        with pytest.raises(ValueError, match="ttl_seconds must be positive"):
            CalendarCache(ttl_seconds=-1)

    def test_zero_max_entries_rejected(self) -> None:
        with pytest.raises(ValueError, match="max_entries must be positive"):
            CalendarCache(max_entries=0)

    def test_negative_max_entries_rejected(self) -> None:
        with pytest.raises(ValueError, match="max_entries must be positive"):
            CalendarCache(max_entries=-1)


class TestCalendarCacheReadWrite:
    def test_miss_returns_none(self) -> None:
        cache = CalendarCache()
        assert cache.get("never-set") is None

    def test_round_trip(self) -> None:
        cache = CalendarCache()
        cache.set("key", "payload")
        assert cache.get("key") == "payload"

    def test_overwrite_replaces_value(self) -> None:
        cache = CalendarCache()
        cache.set("key", "v1")
        cache.set("key", "v2")
        assert cache.get("key") == "v2"
        assert cache.size == 1

    def test_size_tracks_entries(self) -> None:
        cache = CalendarCache()
        cache.set("a", "1")
        cache.set("b", "2")
        assert cache.size == 2

    def test_clear_empties(self) -> None:
        cache = CalendarCache()
        cache.set("a", "1")
        cache.set("b", "2")
        cache.clear()
        assert cache.size == 0
        assert cache.get("a") is None


class TestCalendarCacheTTL:
    def test_entry_expires_after_ttl(self) -> None:
        clock = FakeClock()
        cache = CalendarCache(ttl_seconds=60, clock=clock)
        cache.set("key", "payload")
        clock.advance(61)
        assert cache.get("key") is None

    def test_entry_valid_within_ttl(self) -> None:
        clock = FakeClock()
        cache = CalendarCache(ttl_seconds=60, clock=clock)
        cache.set("key", "payload")
        clock.advance(59)
        assert cache.get("key") == "payload"

    def test_expired_entry_removed_on_read(self) -> None:
        clock = FakeClock()
        cache = CalendarCache(ttl_seconds=60, clock=clock)
        cache.set("key", "payload")
        clock.advance(61)
        cache.get("key")
        assert cache.size == 0

    def test_ttl_boundary_is_exclusive(self) -> None:
        clock = FakeClock()
        cache = CalendarCache(ttl_seconds=60, clock=clock)
        cache.set("key", "payload")
        clock.advance(60)
        assert cache.get("key") == "payload"


class TestCalendarCacheFIFO:
    def test_fifo_eviction_when_full(self) -> None:
        cache = CalendarCache(max_entries=3)
        cache.set("a", "1")
        cache.set("b", "2")
        cache.set("c", "3")
        cache.set("d", "4")
        assert cache.get("a") is None
        assert cache.get("b") == "2"
        assert cache.get("c") == "3"
        assert cache.get("d") == "4"
        assert cache.size == 3

    def test_overwrite_does_not_trigger_eviction(self) -> None:
        cache = CalendarCache(max_entries=2)
        cache.set("a", "1")
        cache.set("b", "2")
        cache.set("a", "new")
        assert cache.get("a") == "new"
        assert cache.get("b") == "2"
        assert cache.size == 2

    def test_oldest_first_evicted(self) -> None:
        cache = CalendarCache(max_entries=2)
        cache.set("a", "1")
        cache.set("b", "2")
        cache.set("c", "3")
        assert cache.get("a") is None
        assert cache.get("b") == "2"
        assert cache.get("c") == "3"
