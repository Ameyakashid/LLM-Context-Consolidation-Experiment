"""Rolling buffer of inner-voice lines for the Cabinet display.

"RAM for the voices": real LOGIC/EMPATHY/VOLITION lines are captured the
moment the Disco chain fires (and topped up in calm stretches), stored
newest-first, and the oldest fall off the end as new ones arrive — so the
mirror's drifting voice strip always has something real to show.

JSON-backed at ``data/voice_buffer.json`` (atomic tmp+rename). Pure-ish:
all I/O is confined to :meth:`_load` / :meth:`_persist`; the rotation,
dedup, aging, and top-up predicates are deterministic and unit-tested.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Sequence

log = logging.getLogger(__name__)

DEFAULT_CAPACITY = 24
DEFAULT_MAX_AGE = timedelta(hours=6)
DEFAULT_MIN_FRESH = 6


@dataclass(frozen=True)
class VoiceLine:
    """One inner-voice line. ``source`` is ``fired`` | ``topup`` | ``evergreen``."""

    who: str
    line: str
    created_at: datetime
    source: str = "topup"


def _key(line: VoiceLine) -> tuple[str, str]:
    return (line.who, line.line.strip())


def disco_comments_to_voice_lines(
    comments: Iterable[object], now: datetime, source: str = "fired",
) -> list[VoiceLine]:
    """Map ``DiscoComment``-like objects to :class:`VoiceLine` rows.

    Reads ``.voice_name`` / ``.comment`` by duck-typing so this module need
    not import the disco engine. ``volition`` → ``VOLITION`` etc.; empties
    are dropped.
    """
    out: list[VoiceLine] = []
    for comment in comments:
        text = (getattr(comment, "comment", "") or "").strip()
        if not text:
            continue
        who = str(getattr(comment, "voice_name", "") or "VOLITION").upper().replace("_", " ")
        out.append(VoiceLine(who=who, line=text, created_at=now, source=source))
    return out


class VoiceBuffer:
    """Newest-first rolling store of voice lines, JSON-backed + capped."""

    def __init__(
        self,
        path: Path,
        capacity: int = DEFAULT_CAPACITY,
        max_age: timedelta = DEFAULT_MAX_AGE,
    ) -> None:
        self._path = path
        self._capacity = capacity
        self._max_age = max_age
        self._lines: list[VoiceLine] = self._load()

    def _load(self) -> list[VoiceLine]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        out: list[VoiceLine] = []
        for item in data if isinstance(data, list) else []:
            try:
                out.append(VoiceLine(
                    who=str(item["who"]).upper(),
                    line=str(item["line"]),
                    created_at=datetime.fromisoformat(item["created_at"]),
                    source=str(item.get("source", "topup")),
                ))
            except (KeyError, TypeError, ValueError):
                continue
        return out

    def _persist(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = [
            {
                "who": vl.who,
                "line": vl.line,
                "created_at": vl.created_at.isoformat(),
                "source": vl.source,
            }
            for vl in self._lines
        ]
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8", newline="\n",
        )
        tmp.replace(self._path)

    def add(self, new_lines: Sequence[VoiceLine]) -> None:
        """Prepend ``new_lines`` (newest first), dedup by (who, line), cap, persist."""
        if not new_lines:
            return
        seen: set[tuple[str, str]] = set()
        deduped: list[VoiceLine] = []
        for vl in [*new_lines, *self._lines]:  # new entries win on dedup
            k = _key(vl)
            if k in seen:
                continue
            seen.add(k)
            deduped.append(vl)
        self._lines = deduped[: self._capacity]
        self._persist()

    def current(self, limit: int = 12) -> list[VoiceLine]:
        """Return the newest ``limit`` lines (what the mirror should rotate)."""
        return self._lines[:limit]

    def all_lines(self) -> list[VoiceLine]:
        return list(self._lines)

    def fresh_count(self, now: datetime) -> int:
        return sum(1 for vl in self._lines if (now - vl.created_at) <= self._max_age)

    def needs_topup(self, now: datetime, min_lines: int = DEFAULT_MIN_FRESH) -> bool:
        """True when fewer than ``min_lines`` un-aged lines remain."""
        return self.fresh_count(now) < min_lines

    def mark_aged(self, now: datetime) -> int:
        """Drop lines older than ``max_age``; persist if any removed. Returns count dropped."""
        kept = [vl for vl in self._lines if (now - vl.created_at) <= self._max_age]
        dropped = len(self._lines) - len(kept)
        if dropped:
            self._lines = kept
            self._persist()
        return dropped
