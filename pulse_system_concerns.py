"""Pulse system concerns — Dream concern store + composite + last-run helpers.

The Pulse engine accepts exactly one ``PulseStoreProtocol`` instance. To
fire both check-in concerns (sub-02) *and* the Dream concern from the
same Pulse loop, we wrap both stores in a :class:`CompositePulseStore`
that merges ``next_fire_time`` and ``claim_due_concerns`` across its
members.

:class:`DreamConcernStore` emits a single concern id (``"dream_state"``)
on its configured cron schedule. A last-run JSON file in
``workspace/data/`` records the last attempt so a restart that lands
inside the ``skip_window_hours`` window does not immediately re-fire a
Dream run. The file is gitignored via the existing ``workspace/data/``
rule.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from pulse_engine import PulseStoreProtocol
from pulse_schedule import ConcernId, ScheduleCron, next_fire_after

log = logging.getLogger(__name__)

DREAM_CONCERN_ID: str = "dream_state"
DEFAULT_DREAM_CRON: str = "0 3 * * *"
DEFAULT_SKIP_WINDOW_HOURS: int = 12


def is_dream_state_enabled(env: Mapping[str, str]) -> bool:
    """Return True when ``DREAM_STATE_ENABLED`` is the string ``"true"``.

    Matches the canonical truthy convention used by
    :func:`pulse_checkin_store.is_pulse_engine_enabled` and the four
    other setup flags: case-insensitive, whitespace-stripped, strict
    ``== "true"``.
    """
    return env.get("DREAM_STATE_ENABLED", "false").strip().lower() == "true"


def read_last_run(path: Path) -> datetime | None:
    """Return the recorded last-run UTC timestamp, or None if absent/invalid.

    An invalid/partial file returns None rather than raising — a corrupt
    state file should not break the Pulse loop. The caller treats None
    the same as "never ran".
    """
    if not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        log.warning(
            "dream_last_run unreadable at %s (%s); treating as never-run",
            path, exc,
        )
        return None
    stamp = data.get("last_run_utc") if isinstance(data, dict) else None
    if not isinstance(stamp, str):
        return None
    try:
        parsed = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def write_last_run(path: Path, when: datetime) -> None:
    """Atomically persist ``when`` (UTC) as the Dream's last-run timestamp.

    Raises ``ValueError`` on a naive datetime — the caller must supply a
    tz-aware UTC instant, matching the contract upstream of the engine.
    """
    if when.tzinfo is None:
        raise ValueError(
            "write_last_run requires a tz-aware datetime; got naive "
            f"{when!r}. Supply datetime.now(timezone.utc)."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {"last_run_utc": when.astimezone(timezone.utc).isoformat()},
        indent=2,
    )
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(payload, encoding="utf-8")
    tmp_path.replace(path)


def should_skip_catchup(
    last_run: datetime | None,
    now: datetime,
    skip_window_hours: int,
) -> bool:
    """Return True when ``now - last_run`` is inside the skip window.

    Used to suppress a catch-up Dream fire when the bot restarts shortly
    after a previous successful run. A ``last_run`` of None disables the
    skip (first-ever boot allowed to catch up).
    """
    if last_run is None:
        return False
    if now.tzinfo is None or last_run.tzinfo is None:
        raise ValueError(
            "should_skip_catchup requires tz-aware datetimes; "
            f"got now={now!r}, last_run={last_run!r}."
        )
    delta = now.astimezone(timezone.utc) - last_run.astimezone(timezone.utc)
    return delta < timedelta(hours=skip_window_hours)


def _default_now_provider() -> datetime:
    return datetime.now(timezone.utc)


class DreamConcernStore:
    """``PulseStoreProtocol`` for the single ``dream_state`` concern.

    ``next_fire_time`` returns the strictly-next cron slot in UTC, unless
    a Dream run was missed while the bot was offline *and* the skip
    window has elapsed since the last recorded run — in which case it
    returns ``now_utc`` so Pulse fires immediately on startup.

    ``claim_due_concerns(now)`` returns ``["dream_state"]`` when both:

    * the skip window has elapsed since ``last_run`` (or last_run is
      None), and
    * the cron's most recent slot on or before ``now`` is strictly after
      ``last_run`` (i.e. an unclaimed slot exists).
    """

    def __init__(
        self,
        cron_expr: str,
        tz: ZoneInfo,
        last_run_path: Path,
        skip_window_hours: int = DEFAULT_SKIP_WINDOW_HOURS,
        now_provider: Callable[[], datetime] = _default_now_provider,
    ) -> None:
        self._cron_expr = cron_expr
        self._tz = tz
        self._last_run_path = last_run_path
        self._skip_window_hours = skip_window_hours
        self._now_provider = now_provider

    async def next_fire_time(self) -> datetime | None:
        now_utc = self._now_utc()
        last_run = read_last_run(self._last_run_path)
        next_slot = next_fire_after(
            ScheduleCron(cron_expr=self._cron_expr), now_utc, self._tz,
        )
        if last_run is None:
            return next_slot
        if should_skip_catchup(last_run, now_utc, self._skip_window_hours):
            return next_slot
        first_after_last = next_fire_after(
            ScheduleCron(cron_expr=self._cron_expr), last_run, self._tz,
        )
        if first_after_last is not None and first_after_last <= now_utc:
            return now_utc
        return next_slot

    async def claim_due_concerns(self, now: datetime) -> list[ConcernId]:
        if now.tzinfo is None:
            raise ValueError(
                "DreamConcernStore.claim_due_concerns requires a tz-aware "
                f"datetime for `now`; got naive {now!r}."
            )
        now_utc = now.astimezone(timezone.utc)
        last_run = read_last_run(self._last_run_path)
        if should_skip_catchup(last_run, now_utc, self._skip_window_hours):
            return []
        baseline = (
            last_run if last_run is not None
            else now_utc - timedelta(days=7)
        )
        next_after_baseline = next_fire_after(
            ScheduleCron(cron_expr=self._cron_expr), baseline, self._tz,
        )
        if next_after_baseline is None:
            return []
        if next_after_baseline <= now_utc:
            return [ConcernId(DREAM_CONCERN_ID)]
        return []

    def _now_utc(self) -> datetime:
        produced = self._now_provider()
        if produced.tzinfo is None:
            raise ValueError(
                "DreamConcernStore.now_provider returned a naive datetime "
                f"({produced!r}); must return tz-aware UTC."
            )
        return produced.astimezone(timezone.utc)


class CompositePulseStore:
    """Merge multiple ``PulseStoreProtocol`` instances into one store.

    ``next_fire_time`` returns the minimum of its members' fire times
    (None members skipped). ``claim_due_concerns`` returns the
    concatenation of each member's claim list, preserving order — the
    ``stores`` list order defines firing priority when slots coincide.
    """

    def __init__(self, stores: list[PulseStoreProtocol]) -> None:
        if not stores:
            raise ValueError(
                "CompositePulseStore requires at least one member store."
            )
        self._stores = stores

    async def next_fire_time(self) -> datetime | None:
        times: list[datetime] = []
        for store in self._stores:
            fire_at = await store.next_fire_time()
            if fire_at is not None:
                times.append(fire_at)
        if not times:
            return None
        return min(times)

    async def claim_due_concerns(self, now: datetime) -> list[ConcernId]:
        claimed: list[ConcernId] = []
        for store in self._stores:
            claimed.extend(await store.claim_due_concerns(now))
        return claimed


__all__ = [
    "CompositePulseStore",
    "DEFAULT_DREAM_CRON",
    "DEFAULT_SKIP_WINDOW_HOURS",
    "DREAM_CONCERN_ID",
    "DreamConcernStore",
    "is_dream_state_enabled",
    "read_last_run",
    "should_skip_catchup",
    "write_last_run",
]
