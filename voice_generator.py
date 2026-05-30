"""Background top-up generator for the Cabinet inner-voice buffer.

Keeps the :class:`voice_buffer.VoiceBuffer` non-empty in calm stretches so
the mirror always shows *real* disco-voiced lines (not the client-side
generic fallback). On a slow cadence (~90 min) it ages the buffer and, when
it runs low, generates fresh context-aware lines via the Disco chain and
blends in a few evergreen lines as a guaranteed floor.

Fired lines (captured live in :mod:`disco_hook`) take priority; this only
fills the gaps. LLM failures degrade gracefully to evergreen-only.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from datetime import datetime
from typing import Callable

from buffer_store import BufferStore
from checkin_schedule import CheckInScheduleStore
from disco_config import DiscoConfig
from disco_engine import LLMCallable, run_disco_chain
from task_store import TaskStoreProtocol
from voice_buffer import VoiceBuffer, VoiceLine, disco_comments_to_voice_lines

log = logging.getLogger(__name__)

DEFAULT_TOPUP_INTERVAL_S = 5400.0  # 90 min
DEFAULT_MIN_FRESH = 6

# Evergreen lines: timeless, in-voice, never go stale. The guaranteed floor
# so the strip is never empty even if the LLM is unreachable.
EVERGREEN_LINES: tuple[tuple[str, str], ...] = (
    ("VOLITION", "Stand. Pick the thing in large letters. Begin badly if you must."),
    ("VOLITION", "Hold the line. One thing, then we breathe."),
    ("EMPATHY", "Whatever this hour holds, you needn't hold it gracefully."),
    ("EMPATHY", "You are allowed to do this slowly."),
    ("LOGIC", "A finite list. Finite lists end."),
    ("LOGIC", "The next step is smaller than the whole of it."),
)


def voice_topup_from_env(
    env: Mapping[str, str] | None, default: float = DEFAULT_TOPUP_INTERVAL_S,
) -> float:
    """Read the top-up cadence from ``CABINET_VOICE_TOPUP_S`` (default 90min)."""
    raw = (env or {}).get("CABINET_VOICE_TOPUP_S", "").strip()
    if not raw:
        return default
    try:
        val = float(raw)
    except ValueError:
        return default
    return val if val > 0 else default


def build_topup_snapshot(
    tasks: list[object], buffers: list[object], state: str,
) -> str:
    """A short situation summary the voices can react to (context-aware seed)."""
    active = [t for t in tasks if getattr(t, "status", "") in ("pending", "in_progress")]
    low = [
        b for b in buffers
        if getattr(b, "buffer_level", 99) <= getattr(b, "alert_threshold", 0)
    ]
    parts = [f"Cognitive state: {state}.", f"{len(active)} active obligation(s)."]
    if low:
        names = ", ".join(getattr(b, "name", "?") for b in low)
        parts.append(f"Running low: {names}.")
    return " ".join(parts)


class VoiceTopUpGenerator:
    """Async task that refills the voice buffer when it runs low."""

    def __init__(
        self,
        buffer: VoiceBuffer,
        config: DiscoConfig,
        llm_call: LLMCallable,
        task_store: TaskStoreProtocol,
        buffer_store: BufferStore,
        get_cognitive_state: Callable[[], str],
        get_current_datetime: Callable[[], datetime],
        interval_s: float = DEFAULT_TOPUP_INTERVAL_S,
        min_lines: int = DEFAULT_MIN_FRESH,
        evergreen: tuple[tuple[str, str], ...] = EVERGREEN_LINES,
    ) -> None:
        self._buffer = buffer
        self._config = config
        self._llm_call = llm_call
        self._task_store = task_store
        self._buffer_store = buffer_store
        self._get_cognitive_state = get_cognitive_state
        self._now = get_current_datetime
        self._interval_s = interval_s
        self._min_lines = min_lines
        self._evergreen = evergreen
        self._task: asyncio.Task[None] | None = None

    def _evergreen_lines(self, now: datetime) -> list[VoiceLine]:
        return [
            VoiceLine(who=who, line=line, created_at=now, source="evergreen")
            for who, line in self._evergreen
        ]

    async def _generate_llm(self, now: datetime) -> list[VoiceLine]:
        state = self._get_cognitive_state()
        tasks = self._task_store.list_tasks()
        buffers = self._buffer_store.list_active_buffers()
        snapshot = build_topup_snapshot(tasks, buffers, state)
        comments = await run_disco_chain(
            main_response=snapshot,
            user_message="(an ambient moment — reflect on where things stand)",
            cognitive_state=state,
            task_context=snapshot,
            config=self._config,
            llm_call=self._llm_call,
        )
        return disco_comments_to_voice_lines(comments, now, source="topup")

    async def generate_once(self) -> None:
        """Age the buffer; if low, blend fresh LLM lines + evergreen and store."""
        now = self._now()
        self._buffer.mark_aged(now)
        if not self._buffer.needs_topup(now, self._min_lines):
            return
        new_lines: list[VoiceLine] = []
        try:
            new_lines = await self._generate_llm(now)
        except Exception as exc:  # LLM/network failure -> evergreen-only
            log.warning("Voice top-up LLM generation failed: %s", exc)
        # Evergreen always included as the floor (deduped by the buffer).
        new_lines = new_lines + self._evergreen_lines(now)
        self._buffer.add(new_lines)
        log.info("Voice buffer topped up (+%d candidate lines)", len(new_lines))

    async def _run(self) -> None:
        while True:
            try:
                await self.generate_once()
            except Exception as exc:  # never let the task die
                log.warning("Voice top-up tick failed: %s", exc)
            await asyncio.sleep(self._interval_s)

    async def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run())
        log.info("Voice top-up generator started (every %.0fs)", self._interval_s)

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()
