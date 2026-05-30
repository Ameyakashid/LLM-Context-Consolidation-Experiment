"""Tests for cabinet_alerts: overlay mappers, AlertQueue, AlertEvaluator."""

from __future__ import annotations

import json
from datetime import date, datetime, time
from pathlib import Path

from buffer_store import Buffer
from cabinet_alerts import (
    AlertEvaluator,
    AlertQueue,
    collect_alertable_buffers,
    is_checkin_missed,
    overlay_buffer_alert,
    overlay_missed_checkin,
    overlay_state_change,
    trim_alerts,
)
from checkin_schedule import CheckInEntry

_NOW = datetime(2026, 5, 29, 10, 0)


def _buffer(name: str = "rent", level: int = 1, capacity: int = 4, threshold: int = 2) -> Buffer:
    return Buffer(
        id=f"b-{name}", name=name, buffer_level=level, buffer_capacity=capacity,
        recurrence_interval_days=30, next_due_date=date(2026, 6, 1),
        alert_threshold=threshold, status="active", created_at=_NOW, updated_at=_NOW,
    )


def _entry(hour: int = 8, staleness: int = 60) -> CheckInEntry:
    return CheckInEntry(
        type_id="morning_motivation", display_name="Morning Motivation",
        target_time=time(hour, 0), staleness_minutes=staleness,
        is_enabled=True, last_run_date=None,
    )


class TestMappers:
    def test_state_change_emphasis(self) -> None:
        o = overlay_state_change("focus", "overwhelm")
        assert o["title"] == "State Change"
        assert '<span class="em">focus</span>' in o["message"]
        assert '<span class="em">overwhelm</span>' in o["message"]

    def test_buffer_alert_emphasis(self) -> None:
        o = overlay_buffer_alert("Nourishment", 3, 10)
        assert '<span class="em">Nourishment</span>' in o["message"]
        assert "3/10" in o["message"]

    def test_missed_checkin_emphasis(self) -> None:
        o = overlay_missed_checkin("Lunch + meds", "12:30")
        assert '<span class="em">Lunch + meds</span>' in o["message"]
        assert "12:30" in o["message"]


class TestTrim:
    def test_keeps_last_n(self) -> None:
        items = [{"id": i} for i in range(25)]
        kept = trim_alerts(items, 20)
        assert len(kept) == 20
        assert kept[0]["id"] == 5 and kept[-1]["id"] == 24


class TestAlertQueue:
    def test_push_monotonic_ids(self, tmp_path: Path) -> None:
        q = AlertQueue(tmp_path / "alerts.json")
        assert q.push("buffer_alert", {"x": "1"}) == 1
        assert q.push("state_change", {"x": "2"}) == 2

    def test_persists_envelope(self, tmp_path: Path) -> None:
        path = tmp_path / "alerts.json"
        AlertQueue(path).push("buffer_alert", {"title": "T", "message": "M"})
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["alerts"][0] == {
            "id": 1, "type": "buffer_alert", "payload": {"title": "T", "message": "M"},
        }

    def test_ids_continue_across_instances(self, tmp_path: Path) -> None:
        path = tmp_path / "alerts.json"
        AlertQueue(path).push("buffer_alert", {})
        assert AlertQueue(path).push("state_change", {}) == 2  # not 1

    def test_trims_to_max(self, tmp_path: Path) -> None:
        q = AlertQueue(tmp_path / "alerts.json", max_alerts=3)
        for _ in range(5):
            q.push("buffer_alert", {})
        assert len(q.all()) == 3


class TestAlertEvaluator:
    def test_state_primes_then_fires_on_change(self, tmp_path: Path) -> None:
        q = AlertQueue(tmp_path / "alerts.json")
        ev = AlertEvaluator(q)
        ev.evaluate(_NOW, "baseline", [], [])      # prime, no alert
        assert q.all() == []
        ev.evaluate(_NOW, "overwhelm", [], [])      # change -> fire
        assert [a["type"] for a in q.all()] == ["state_change"]
        ev.evaluate(_NOW, "overwhelm", [], [])      # same -> no fire
        assert len(q.all()) == 1

    def test_buffer_low_fires_once_per_day(self, tmp_path: Path) -> None:
        q = AlertQueue(tmp_path / "alerts.json")
        ev = AlertEvaluator(q)
        low = _buffer("rent", level=1, threshold=2)
        ev.evaluate(_NOW, "baseline", [low], [])
        ev.evaluate(_NOW, "baseline", [low], [])
        types = [a["type"] for a in q.all()]
        assert types.count("buffer_alert") == 1

    def test_only_alertable_buffers(self, tmp_path: Path) -> None:
        q = AlertQueue(tmp_path / "alerts.json")
        ev = AlertEvaluator(q)
        ev.evaluate(_NOW, "baseline", [_buffer("milk", level=4, threshold=2)], [])
        assert q.all() == []

    def test_missed_checkin_fires_once(self, tmp_path: Path) -> None:
        q = AlertQueue(tmp_path / "alerts.json")
        ev = AlertEvaluator(q)
        entry = _entry(hour=8, staleness=60)  # 08:00 + 60m < 10:00 now -> missed
        ev.evaluate(_NOW, "baseline", [], [entry])
        ev.evaluate(_NOW, "baseline", [], [entry])
        assert [a["type"] for a in q.all()] == ["missed_checkin"]


class TestPredicates:
    def test_collect_alertable_sorted(self) -> None:
        low = _buffer("rent", level=1, threshold=2)
        mid = _buffer("milk", level=1, threshold=2)
        high = _buffer("gas", level=4, threshold=2)  # 4 > 2 -> not alertable
        out = collect_alertable_buffers([low, high, mid])
        assert [b.name for b in out] == ["milk", "rent"]  # alertable, sorted by name

    def test_missed_when_past_staleness(self) -> None:
        entry = _entry(hour=8, staleness=60)  # 08:00 + 60m < 10:00
        assert is_checkin_missed(entry, _NOW.date(), _NOW) is True

    def test_not_missed_within_window(self) -> None:
        entry = _entry(hour=8, staleness=240)  # 08:00 + 240m > 10:00
        assert is_checkin_missed(entry, _NOW.date(), _NOW) is False

    def test_not_missed_if_run_today(self) -> None:
        entry = CheckInEntry(
            type_id="morning_motivation", display_name="M", target_time=time(8, 0),
            staleness_minutes=60, is_enabled=True, last_run_date=_NOW.date(),
        )
        assert is_checkin_missed(entry, _NOW.date(), _NOW) is False

    def test_not_missed_if_disabled(self) -> None:
        entry = CheckInEntry(
            type_id="morning_motivation", display_name="M", target_time=time(8, 0),
            staleness_minutes=60, is_enabled=False, last_run_date=None,
        )
        assert is_checkin_missed(entry, _NOW.date(), _NOW) is False


def test_file_line_budget() -> None:
    mod = Path(__file__).resolve().parents[1] / "cabinet_alerts.py"
    assert len(mod.read_text(encoding="utf-8").splitlines()) <= 300
