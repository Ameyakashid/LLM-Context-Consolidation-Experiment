"""TTL + FIFO cache for Google Calendar MCP tool responses.

Shared across the three calendar tools in ``calendar_tools``. Keyed by
canonical-JSON strings built from (tool_name, normalized_arguments).
Values are the raw upstream string payload (JSON from the MCP server or
a structured-error envelope) — the cache is payload-agnostic.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable

DEFAULT_TTL_SECONDS = 60
DEFAULT_MAX_ENTRIES = 128

Clock = Callable[[], float]


class CalendarCache:
    """Thread-unsafe TTL+FIFO cache. Safe under asyncio single-threaded use.

    TTL is enforced on read: expired entries are deleted and treated as a
    miss. FIFO eviction runs on insert when ``size`` exceeds
    ``max_entries``, dropping the oldest entry first.
    """

    def __init__(
        self,
        *,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        clock: Clock | None = None,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError(
                f"ttl_seconds must be positive, got {ttl_seconds}"
            )
        if max_entries <= 0:
            raise ValueError(
                f"max_entries must be positive, got {max_entries}"
            )
        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries
        self._clock: Clock = clock if clock is not None else time.monotonic
        self._entries: OrderedDict[str, tuple[float, str]] = OrderedDict()

    def get(self, key: str) -> str | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        inserted_at, value = entry
        if self._clock() - inserted_at > self._ttl_seconds:
            del self._entries[key]
            return None
        return value

    def set(self, key: str, value: str) -> None:
        if key in self._entries:
            del self._entries[key]
        self._entries[key] = (self._clock(), value)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)

    def clear(self) -> None:
        self._entries.clear()

    @property
    def size(self) -> int:
        return len(self._entries)
