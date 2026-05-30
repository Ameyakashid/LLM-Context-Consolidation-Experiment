"""LLM-generated study-card pool for the Cabinet's Codex mode.

The backend keeps a buffered pool (~180 cards across the data-analyst
categories) at ``cabinet/feeds/flashcards.json`` and a cache at
``data/flashcard_pool.json``. The frontend's refresh button resamples a
fresh random ~40 from the pool client-side (instant, read-only-safe) — so
"new set of 30/50" needs no tablet→PC call.

Generation is per-category via the app's LLM. Failures keep the last good
pool (loaded from the cache), so the Codex is never empty.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable

from magicmirror_feeds import write_flashcards_feed

log = logging.getLogger(__name__)

FLASHCARD_CATEGORIES: tuple[str, ...] = (
    "SQL", "Statistics", "Experiments", "Pandas", "Concepts", "Visualization",
)
DEFAULT_PER_CATEGORY = 30
DEFAULT_FLASHCARDS_INTERVAL_S = 21600.0  # 6h

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)

LLMCall = Callable[[str], Awaitable[str]]


def flashcards_interval_from_env(
    env: Mapping[str, str] | None, default: float = DEFAULT_FLASHCARDS_INTERVAL_S,
) -> float:
    """Read the regeneration cadence from ``CABINET_FLASHCARDS_S`` (default 6h)."""
    raw = (env or {}).get("CABINET_FLASHCARDS_S", "").strip()
    if not raw:
        return default
    try:
        val = float(raw)
    except ValueError:
        return default
    return val if val > 0 else default


def build_flashcard_prompt(category: str, n: int) -> str:
    """Prompt the LLM for ``n`` flashcards in one category as a JSON array."""
    return (
        f"You are writing study flashcards for a working data analyst.\n"
        f"Produce exactly {n} flashcards on the topic: {category}.\n"
        f'Return ONLY a JSON array, each item: '
        f'{{"cat": "{category}", "front": "<concise question>", '
        f'"back": "<1-3 sentence answer>"}}.\n'
        f"No prose, no markdown fences — just the JSON array."
    )


def _strip_fences(raw: str) -> str:
    s = (raw or "").strip()
    s = _FENCE_RE.sub("", s).strip()
    if not s.startswith("["):
        i, j = s.find("["), s.rfind("]")
        if i != -1 and j > i:
            s = s[i:j + 1]
    return s


def parse_flashcards_json(raw: str) -> list[dict]:
    """Parse an LLM response into validated ``{cat, front, back}`` cards."""
    try:
        data = json.loads(_strip_fences(raw))
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    cards: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        cat = str(item.get("cat", "")).strip()
        front = str(item.get("front", "")).strip()
        back = str(item.get("back", "")).strip()
        if cat and front and back:
            cards.append({"cat": cat, "front": front, "back": back})
    return cards


def render_flashcards_json(cards: list[dict], generated_at: str | None = None) -> str:
    """Serialize the pool the frontend fetches: ``{"cards": [...]}``."""
    payload: dict[str, object] = {"cards": cards}
    if generated_at:
        payload["generated_at"] = generated_at
    return json.dumps(payload, ensure_ascii=False)


class FlashcardPoolGenerator:
    """Async task that (re)builds the flashcard pool on a slow cadence."""

    def __init__(
        self,
        llm_call: LLMCall,
        feed_dir: Path,
        pool_path: Path,
        get_current_datetime: Callable[[], datetime],
        categories: tuple[str, ...] = FLASHCARD_CATEGORIES,
        per_category: int = DEFAULT_PER_CATEGORY,
        interval_s: float = DEFAULT_FLASHCARDS_INTERVAL_S,
    ) -> None:
        self._llm = llm_call
        self._feed_dir = feed_dir
        self._pool_path = pool_path
        self._now = get_current_datetime
        self._categories = categories
        self._per_category = per_category
        self._interval_s = interval_s
        self._task: asyncio.Task[None] | None = None

    def _load_cached(self) -> list[dict]:
        try:
            data = json.loads(self._pool_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        cards = data.get("cards") if isinstance(data, dict) else None
        return cards if isinstance(cards, list) else []

    def _persist_cache(self, cards: list[dict], generated_at: str) -> None:
        self._pool_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._pool_path.with_suffix(".tmp")
        tmp.write_text(
            render_flashcards_json(cards, generated_at),
            encoding="utf-8", newline="\n",
        )
        tmp.replace(self._pool_path)

    async def generate_once(self) -> None:
        """Regenerate the whole pool; on total failure, fall back to cache."""
        cards: list[dict] = []
        for category in self._categories:
            prompt = build_flashcard_prompt(category, self._per_category)
            try:
                raw = await self._llm(prompt)
            except Exception as exc:
                log.warning("Flashcard gen failed for %s: %s", category, exc)
                continue
            cards.extend(parse_flashcards_json(raw))
        if not cards:
            cards = self._load_cached()  # keep last good pool
            if not cards:
                return
        generated_at = self._now().isoformat()
        write_flashcards_feed(
            self._feed_dir, render_flashcards_json(cards, generated_at),
        )
        self._persist_cache(cards, generated_at)
        log.info("Flashcard pool regenerated (%d cards)", len(cards))

    async def _run(self) -> None:
        while True:
            try:
                await self.generate_once()
            except Exception as exc:  # never let the task die
                log.warning("Flashcard pool tick failed: %s", exc)
            await asyncio.sleep(self._interval_s)

    async def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run())
        log.info("Flashcard pool generator started (every %.0fs)", self._interval_s)

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
