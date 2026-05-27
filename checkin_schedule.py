"""Check-in schedule data model and due-check engine for the ADHD assistant.

Provides a CheckInEntry model (Pydantic BaseModel) and a CheckInScheduleStore
that persists entries to a JSON file with atomic writes. Pure functions
determine which check-ins are due given the current time.

Four check-in types: morning_motivation, morning_plan, afternoon_check,
evening_review. Each has a configurable target time, staleness window,
enabled flag, and last-run date.
"""

import json
import logging
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

log = logging.getLogger(__name__)

CheckInType = Literal[
    "morning_motivation", "morning_plan", "afternoon_check", "evening_review"
]
ALL_CHECKIN_TYPES: frozenset[str] = frozenset(
    ["morning_motivation", "morning_plan", "afternoon_check", "evening_review"]
)

CHECKIN_DEFAULTS: dict[str, dict[str, str | int | bool]] = {
    "morning_motivation": {
        "display_name": "Morning Motivation",
        "target_time": "08:00",
        "staleness_minutes": 120,
        "is_enabled": True,
    },
    "morning_plan": {
        "display_name": "Morning Plan",
        "target_time": "09:00",
        "staleness_minutes": 120,
        "is_enabled": True,
    },
    "afternoon_check": {
        "display_name": "Afternoon Check",
        "target_time": "14:00",
        "staleness_minutes": 120,
        "is_enabled": True,
    },
    "evening_review": {
        "display_name": "Evening Review",
        "target_time": "20:00",
        "staleness_minutes": 120,
        "is_enabled": True,
    },
}


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

class CheckInEntry(BaseModel):
    """A single scheduled check-in in the ADHD assistant."""

    type_id: CheckInType
    display_name: str
    target_time: time
    staleness_minutes: int
    is_enabled: bool
    last_run_date: date | None = None


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def build_default_entries() -> list[CheckInEntry]:
    """Construct the 4 default check-in entries."""
    entries: list[CheckInEntry] = []
    for type_id, defaults in CHECKIN_DEFAULTS.items():
        hour, minute = str(defaults["target_time"]).split(":")
        entries.append(CheckInEntry(
            type_id=type_id,  # type: ignore[arg-type]
            display_name=str(defaults["display_name"]),
            target_time=time(int(hour), int(minute)),
            staleness_minutes=int(defaults["staleness_minutes"]),
            is_enabled=bool(defaults["is_enabled"]),
        ))
    return entries


def serialize_schedule(entries: list[CheckInEntry]) -> str:
    """Serialize check-in entries to JSON string."""
    data = {"checkins": [e.model_dump(mode="json") for e in entries]}
    return json.dumps(data, indent=2)


def deserialize_schedule(raw: str) -> list[CheckInEntry]:
    """Parse JSON string into a list of CheckInEntry."""
    data = json.loads(raw)
    if not isinstance(data, dict) or "checkins" not in data:
        raise ValueError(
            "Schedule JSON must have a top-level 'checkins' key. "
            f"Got keys: {list(data.keys()) if isinstance(data, dict) else type(data).__name__}"
        )
    return [CheckInEntry.model_validate(item) for item in data["checkins"]]


def is_checkin_due(
    entry: CheckInEntry,
    current_date: date,
    current_time: time,
) -> bool:
    """Determine if a single check-in is due right now.

    A check-in is due when:
    1. It is enabled
    2. It has not already run today
    3. Current time is at or past the target time
    4. Current time is within the staleness window (not too late)
    """
    if not entry.is_enabled:
        return False
    if entry.last_run_date == current_date:
        return False
    if current_time.replace(tzinfo=None) < entry.target_time.replace(tzinfo=None):
        return False
    # Schedule logic is wall-clock local; strip tzinfo so a naive/aware mix
    # (introduced when current_time carries a tz but target_time doesn't, or
    # vice versa) can't raise "can't subtract offset-naive and offset-aware".
    target_dt = datetime.combine(current_date, entry.target_time.replace(tzinfo=None))
    current_dt = datetime.combine(current_date, current_time.replace(tzinfo=None))
    elapsed = current_dt - target_dt
    if elapsed > timedelta(minutes=entry.staleness_minutes):
        return False
    return True


def get_due_checkins(
    entries: list[CheckInEntry],
    current_date: date,
    current_time: time,
) -> list[CheckInEntry]:
    """Return all check-ins that are currently due."""
    return [e for e in entries if is_checkin_due(e, current_date, current_time)]


def mark_checkin_fired(
    entry: CheckInEntry,
    fire_date: date,
) -> CheckInEntry:
    """Return a new CheckInEntry with last_run_date set to fire_date."""
    data = entry.model_dump(mode="json")
    data["last_run_date"] = fire_date.isoformat()
    return CheckInEntry.model_validate(data)


def update_entry_time(
    entry: CheckInEntry,
    new_time: time,
) -> CheckInEntry:
    """Return a new CheckInEntry with an updated target_time."""
    data = entry.model_dump(mode="json")
    data["target_time"] = new_time.isoformat()
    return CheckInEntry.model_validate(data)


def update_entry_enabled(
    entry: CheckInEntry,
    is_enabled: bool,
) -> CheckInEntry:
    """Return a new CheckInEntry with updated enabled flag."""
    data = entry.model_dump(mode="json")
    data["is_enabled"] = is_enabled
    return CheckInEntry.model_validate(data)


# ---------------------------------------------------------------------------
# CheckInScheduleStore
# ---------------------------------------------------------------------------

class CheckInScheduleStore:
    """CRUD operations over a JSON-persisted check-in schedule.

    Loads entries from disk on init (or creates defaults if file is missing).
    Every mutation writes through to disk atomically.
    """

    def __init__(self, storage_path: Path) -> None:
        self._storage_path = storage_path
        if storage_path.exists():
            raw = storage_path.read_text(encoding="utf-8")
            self._entries = deserialize_schedule(raw)
        else:
            self._entries = build_default_entries()
            self._save()

    def _save(self) -> None:
        content = serialize_schedule(self._entries)
        tmp_path = self._storage_path.with_suffix(".tmp")
        tmp_path.write_text(content, encoding="utf-8")
        tmp_path.replace(self._storage_path)

    def reload(self) -> None:
        """Re-read schedule from disk, discarding in-memory state."""
        if self._storage_path.exists():
            raw = self._storage_path.read_text(encoding="utf-8")
            self._entries = deserialize_schedule(raw)
        else:
            self._entries = build_default_entries()

    def _find_entry(self, type_id: CheckInType) -> int:
        """Return the index of the entry with the given type_id."""
        for idx, entry in enumerate(self._entries):
            if entry.type_id == type_id:
                return idx
        raise KeyError(
            f"Check-in type not found: '{type_id}'. "
            f"Store contains types: {[e.type_id for e in self._entries]}"
        )

    def get_entry(self, type_id: CheckInType) -> CheckInEntry:
        """Retrieve a check-in entry by type_id."""
        idx = self._find_entry(type_id)
        return self._entries[idx]

    def list_entries(self) -> list[CheckInEntry]:
        """Return all check-in entries."""
        return list(self._entries)

    def get_due(
        self,
        current_date: date,
        current_time: time,
    ) -> list[CheckInEntry]:
        """Return check-ins that are currently due."""
        return get_due_checkins(self._entries, current_date, current_time)

    def record_fired(
        self,
        type_id: CheckInType,
        fire_date: date,
    ) -> CheckInEntry:
        """Mark a check-in as having fired on the given date."""
        idx = self._find_entry(type_id)
        self._entries[idx] = mark_checkin_fired(self._entries[idx], fire_date)
        self._save()
        log.info("Recorded %s fired on %s", type_id, fire_date)
        return self._entries[idx]

    def set_time(
        self,
        type_id: CheckInType,
        new_time: time,
    ) -> CheckInEntry:
        """Update the target time for a check-in type."""
        idx = self._find_entry(type_id)
        self._entries[idx] = update_entry_time(self._entries[idx], new_time)
        self._save()
        log.info("Updated %s target time to %s", type_id, new_time)
        return self._entries[idx]

    def set_enabled(
        self,
        type_id: CheckInType,
        is_enabled: bool,
    ) -> CheckInEntry:
        """Enable or disable a check-in type."""
        idx = self._find_entry(type_id)
        self._entries[idx] = update_entry_enabled(
            self._entries[idx], is_enabled,
        )
        self._save()
        log.info("Set %s enabled=%s", type_id, is_enabled)
        return self._entries[idx]
