"""Tests for CheckInScheduleStore — persistence, CRUD, and reload behavior."""

from datetime import date, time
from pathlib import Path

import pytest

from checkin_schedule import CheckInScheduleStore


class TestCheckInScheduleStoreCreate:
    """Verify store initialization and defaults."""

    def test_creates_defaults_on_missing_file(self, tmp_path: Path) -> None:
        store = CheckInScheduleStore(tmp_path / "schedules.json")
        entries = store.list_entries()
        assert len(entries) == 4

    def test_writes_file_on_init(self, tmp_path: Path) -> None:
        path = tmp_path / "schedules.json"
        CheckInScheduleStore(path)
        assert path.exists()

    def test_loads_existing_file(self, tmp_path: Path) -> None:
        path = tmp_path / "schedules.json"
        store1 = CheckInScheduleStore(path)
        store1.set_time("morning_plan", time(10, 0))
        store2 = CheckInScheduleStore(path)
        entry = store2.get_entry("morning_plan")
        assert entry.target_time == time(10, 0)


class TestCheckInScheduleStoreCRUD:
    """Verify store CRUD operations."""

    def test_get_entry(self, tmp_path: Path) -> None:
        store = CheckInScheduleStore(tmp_path / "schedules.json")
        entry = store.get_entry("morning_motivation")
        assert entry.type_id == "morning_motivation"

    def test_get_entry_not_found(self, tmp_path: Path) -> None:
        store = CheckInScheduleStore(tmp_path / "schedules.json")
        with pytest.raises(KeyError, match="not found"):
            store.get_entry("nonexistent")  # type: ignore[arg-type]

    def test_set_time(self, tmp_path: Path) -> None:
        store = CheckInScheduleStore(tmp_path / "schedules.json")
        result = store.set_time("morning_plan", time(10, 30))
        assert result.target_time == time(10, 30)
        assert store.get_entry("morning_plan").target_time == time(10, 30)

    def test_set_enabled_disable(self, tmp_path: Path) -> None:
        store = CheckInScheduleStore(tmp_path / "schedules.json")
        result = store.set_enabled("afternoon_check", False)
        assert not result.is_enabled

    def test_set_enabled_re_enable(self, tmp_path: Path) -> None:
        store = CheckInScheduleStore(tmp_path / "schedules.json")
        store.set_enabled("afternoon_check", False)
        result = store.set_enabled("afternoon_check", True)
        assert result.is_enabled

    def test_record_fired(self, tmp_path: Path) -> None:
        store = CheckInScheduleStore(tmp_path / "schedules.json")
        result = store.record_fired("morning_motivation", date(2026, 4, 10))
        assert result.last_run_date == date(2026, 4, 10)

    def test_get_due(self, tmp_path: Path) -> None:
        store = CheckInScheduleStore(tmp_path / "schedules.json")
        due = store.get_due(date(2026, 4, 10), time(9, 30))
        type_ids = {e.type_id for e in due}
        assert "morning_motivation" in type_ids
        assert "morning_plan" in type_ids

    def test_record_fired_prevents_re_due(self, tmp_path: Path) -> None:
        store = CheckInScheduleStore(tmp_path / "schedules.json")
        store.record_fired("morning_motivation", date(2026, 4, 10))
        due = store.get_due(date(2026, 4, 10), time(9, 30))
        type_ids = {e.type_id for e in due}
        assert "morning_motivation" not in type_ids


class TestCheckInScheduleStoreReload:
    """Verify reload and persistence round-trips."""

    def test_reload_reflects_external_changes(self, tmp_path: Path) -> None:
        path = tmp_path / "schedules.json"
        store1 = CheckInScheduleStore(path)
        store2 = CheckInScheduleStore(path)
        store2.set_time("evening_review", time(21, 0))
        store1.reload()
        assert store1.get_entry("evening_review").target_time == time(21, 0)

    def test_reload_missing_file_resets_defaults(self, tmp_path: Path) -> None:
        path = tmp_path / "schedules.json"
        store = CheckInScheduleStore(path)
        store.set_time("morning_plan", time(10, 0))
        path.unlink()
        store.reload()
        assert store.get_entry("morning_plan").target_time == time(9, 0)

    def test_persistence_survives_new_store_instance(self, tmp_path: Path) -> None:
        path = tmp_path / "schedules.json"
        store1 = CheckInScheduleStore(path)
        store1.record_fired("morning_plan", date(2026, 4, 10))
        store1.set_enabled("afternoon_check", False)
        store2 = CheckInScheduleStore(path)
        assert store2.get_entry("morning_plan").last_run_date == date(2026, 4, 10)
        assert not store2.get_entry("afternoon_check").is_enabled
