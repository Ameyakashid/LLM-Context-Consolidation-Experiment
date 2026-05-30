"""Pulse adapter over ``CheckInScheduleStore``.

Bridges the sub-01 ``PulseStoreProtocol`` contract to the existing
four-check-in schedule (``morning_motivation``, ``morning_plan``,
``afternoon_check``, ``evening_review``). Side-effect free query layer —
firing concerns and advancing ``last_run_date`` are the hook cutover's
job in sub-03.

Adapter invariants
------------------
* ``target_time`` has minute resolution. ``time(H, M, S>0)`` truncates to
  the minute when materialised into a cron expression — acceptable for
  the bot's ≥hourly cadence but surprising if future configs use seconds.
* Staleness is *not* duplicated here. The single source of truth is
  ``checkin_schedule.is_checkin_due``. If that predicate evolves, both
  the Pulse path and the legacy ``SchedulingHook`` path track it.
* ``claim_due_concerns`` is idempotent with respect to ``now`` — calling
  it twice with the same argument returns the same list without a store
  reload. The ``last_run_date`` advance lives in ``advance_last_run``,
  invoked by sub-03 after dispatch.

Retroactive firing within the staleness window
----------------------------------------------
``next_fire_time()`` returns ``now_utc`` when an entry is *already* due
(enabled, not run today, past target, within staleness). Pulse's
``_sleep_until_next`` treats that as a zero-sleep and runs
``claim_due_concerns`` on the same tick. This is how the legacy
heartbeat path catches "bot started at 09:30, morning_motivation was
due at 08:00, staleness 120 min" today — ``next_fire_time`` alone (which
only knows cron slots) would silently return tomorrow's 08:00 instead.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date, datetime, time, timezone
from typing import cast
from zoneinfo import ZoneInfo

from checkin_schedule import (
    ALL_CHECKIN_TYPES,
    CheckInEntry,
    CheckInScheduleStore,
    CheckInType,
    is_checkin_due,
)
from pulse_schedule import ConcernId, ScheduleCron, next_fire_after

CHECKIN_CONCERN_IDS: frozenset[str] = ALL_CHECKIN_TYPES


def is_pulse_engine_enabled(env: Mapping[str, str]) -> bool:
    """Return True when ``PULSE_ENGINE_ENABLED`` is the string ``"true"``.

    Matches the convention used by ``is_gcal_enabled`` /
    ``is_cabinet_enabled`` / ``is_syncall_enabled`` /
    ``is_taskwarrior_enabled``: case-insensitive, whitespace-stripped,
    strict ``== "true"`` — ``"1"``, ``"yes"``, ``"on"`` all resolve False.
    """
    return env.get("PULSE_ENGINE_ENABLED", "false").strip().lower() == "true"


def concern_id_to_checkin_type(concern_id: str) -> CheckInType | None:
    """Type-narrow a Pulse concern id into a ``CheckInType`` literal.

    Returns ``None`` for any id outside ``CHECKIN_CONCERN_IDS``.
    ``typing.cast`` performs no runtime check — the membership test is
    what proves the narrowing is sound.
    """
    if concern_id in CHECKIN_CONCERN_IDS:
        return cast(CheckInType, concern_id)
    return None


def advance_last_run(
    store: CheckInScheduleStore,
    checkin_type: CheckInType,
    today: date,
) -> None:
    """Record that ``checkin_type`` fired on ``today``.

    Thin spec-mandated seam over ``store.record_fired``. Sub-03 calls
    this after Pulse dispatches a concern; tests can assert the
    indirection pinch-point independently.
    """
    store.record_fired(checkin_type, today)


def _default_now_provider() -> datetime:
    return datetime.now(timezone.utc)


class PulseCheckinStore:
    """``PulseStoreProtocol`` adapter over ``CheckInScheduleStore``.

    Concerns are the four ``CheckInType`` literals. Scheduling derives
    from each entry's ``target_time`` evaluated in the user's timezone
    (sourced via DI, typically ``task_time_helpers.get_user_timezone()``
    resolved from ``NANOBOT_TIMEZONE``).

    ``now_provider`` defaults to ``datetime.now(timezone.utc)`` and is
    re-invoked on every call — tests inject a frozen clock.
    """

    def __init__(
        self,
        store: CheckInScheduleStore,
        tz: ZoneInfo,
        now_provider: Callable[[], datetime] = _default_now_provider,
    ) -> None:
        self._store = store
        self._tz = tz
        self._now_provider = now_provider

    async def next_fire_time(self) -> datetime | None:
        now_utc = self._now_utc()
        current_date, current_time = self._to_local(now_utc)
        candidates: list[datetime] = []
        for entry in self._store.list_entries():
            if not entry.is_enabled:
                continue
            candidate = self._candidate_for(
                entry, now_utc, current_date, current_time,
            )
            if candidate is not None:
                candidates.append(candidate)
        if not candidates:
            return None
        return min(candidates)

    async def claim_due_concerns(self, now: datetime) -> list[ConcernId]:
        if now.tzinfo is None:
            raise ValueError(
                "PulseCheckinStore.claim_due_concerns requires a tz-aware "
                f"datetime for `now`; got naive {now!r}. Pulse always "
                "supplies UTC — pass a datetime with an explicit tzinfo."
            )
        current_date, current_time = self._to_local(now)
        return [
            entry.type_id
            for entry in self._store.list_entries()
            if is_checkin_due(entry, current_date, current_time)
        ]

    def _now_utc(self) -> datetime:
        produced = self._now_provider()
        if produced.tzinfo is None:
            raise ValueError(
                "PulseCheckinStore.now_provider returned a naive datetime "
                f"({produced!r}); must return tz-aware UTC."
            )
        return produced.astimezone(timezone.utc)

    def _to_local(self, now_utc: datetime) -> tuple[date, time]:
        local = now_utc.astimezone(self._tz)
        return local.date(), local.time().replace(tzinfo=None)

    def _candidate_for(
        self,
        entry: CheckInEntry,
        now_utc: datetime,
        current_date: date,
        current_time: time,
    ) -> datetime | None:
        if is_checkin_due(entry, current_date, current_time):
            return now_utc
        cron_expr = f"{entry.target_time.minute} {entry.target_time.hour} * * *"
        return next_fire_after(ScheduleCron(cron_expr=cron_expr), now_utc, self._tz)


__all__ = [
    "CHECKIN_CONCERN_IDS",
    "PulseCheckinStore",
    "advance_last_run",
    "concern_id_to_checkin_type",
    "is_pulse_engine_enabled",
]
