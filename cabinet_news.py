"""News puller for the Cabinet's Gazette feed.

The PC pulls headlines via ``ddgs`` (DuckDuckGo), sanitizes + de-dups them,
and writes ``cabinet/feeds/news.md`` in the Gazette grammar the frontend's
``modes.js`` parser reads. The Fire tablet only ever reads that local file —
it never reaches the internet (the loopback/LAN safety posture is preserved).

The network call runs off the event loop (``asyncio.to_thread``); failures
keep the last good ``news.md`` (the frontend also has a built-in fallback).
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
from collections.abc import Mapping
from pathlib import Path

from magicmirror_feeds import write_news_feed

log = logging.getLogger(__name__)

DEFAULT_NEWS_QUERY = "world news"
DEFAULT_NEWS_MAX = 8
DEFAULT_NEWS_INTERVAL_S = 3600.0
DEFAULT_NEWS_TIMELIMIT = "d"  # last day

_TAG_RE = re.compile(r"<[^>]+>")


def strip_html(text: str) -> str:
    """Strip HTML tags and unescape entities from a snippet."""
    return html.unescape(_TAG_RE.sub("", text or "")).strip()


def dedup_articles(items: list[dict]) -> list[dict]:
    """Drop duplicate articles by (title, url), preserving order."""
    seen: set[tuple[str, str]] = set()
    out: list[dict] = []
    for art in items:
        key = (
            str(art.get("title", "")).strip().lower(),
            str(art.get("url", "")).strip(),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(art)
    return out


def render_news_markdown(articles: list[dict]) -> str:
    """Render the Gazette grammar: ``## title`` / ``*source · date*`` / body.

    Returns ``""`` when there are no usable articles so the frontend keeps
    its built-in fallback dispatches.
    """
    blocks: list[str] = []
    for art in articles:
        title = strip_html(str(art.get("title", "")))
        if not title:
            continue
        meta_bits = [
            str(art.get(k, "")).strip()
            for k in ("source", "date")
            if str(art.get(k, "")).strip()
        ]
        body = strip_html(str(art.get("body", "")))
        lines = [f"## {title}"]
        if meta_bits:
            lines.append(f"*{' · '.join(meta_bits)}*")
        if body:
            lines.append(body)
        blocks.append("\n".join(lines))
    if not blocks:
        return ""
    return "\n\n".join(blocks) + "\n"


def fetch_news(
    query: str,
    max_results: int = DEFAULT_NEWS_MAX,
    timelimit: str = DEFAULT_NEWS_TIMELIMIT,
) -> list[dict]:
    """Fetch headlines via ddgs; never raises (returns ``[]`` on any failure)."""
    try:
        from ddgs import DDGS

        return list(
            DDGS().news(query, max_results=max_results, timelimit=timelimit)
        )
    except Exception as exc:  # network / ratelimit / import — degrade to empty
        log.warning("Cabinet news fetch failed: %s", exc)
        return []


def news_settings_from_env(
    env: Mapping[str, str] | None,
) -> tuple[str, int, float]:
    """Resolve (query, max_results, interval_s) from CABINET_NEWS_* env vars."""
    e = env or {}
    query = (e.get("CABINET_NEWS_QUERY") or "").strip() or DEFAULT_NEWS_QUERY
    raw_max = (e.get("CABINET_NEWS_MAX") or "").strip()
    try:
        max_results = int(raw_max) if raw_max else DEFAULT_NEWS_MAX
    except ValueError:
        max_results = DEFAULT_NEWS_MAX
    raw_int = (e.get("CABINET_NEWS_S") or "").strip()
    try:
        interval = float(raw_int) if raw_int else DEFAULT_NEWS_INTERVAL_S
    except ValueError:
        interval = DEFAULT_NEWS_INTERVAL_S
    if interval <= 0:
        interval = DEFAULT_NEWS_INTERVAL_S
    return query, max_results, interval


class NewsRefresher:
    """Async task that refreshes ``news.md`` on a slow cadence (~hourly)."""

    def __init__(
        self,
        feed_dir: Path,
        query: str = DEFAULT_NEWS_QUERY,
        max_results: int = DEFAULT_NEWS_MAX,
        interval_s: float = DEFAULT_NEWS_INTERVAL_S,
        timelimit: str = DEFAULT_NEWS_TIMELIMIT,
    ) -> None:
        self._feed_dir = feed_dir
        self._query = query
        self._max = max_results
        self._interval_s = interval_s
        self._timelimit = timelimit
        self._task: asyncio.Task[None] | None = None

    async def refresh_once(self) -> None:
        """Pull → sanitize → dedup → write. Keeps last good file on empty."""
        articles = await asyncio.to_thread(
            fetch_news, self._query, self._max, self._timelimit
        )
        md = render_news_markdown(dedup_articles(articles))
        if md:
            write_news_feed(self._feed_dir, md)
            log.info("Cabinet news refreshed (%d articles)", len(articles))

    async def _run(self) -> None:
        while True:
            try:
                await self.refresh_once()
            except Exception as exc:  # never let the task die
                log.warning("Cabinet news refresh tick failed: %s", exc)
            await asyncio.sleep(self._interval_s)

    async def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run())
        log.info("Cabinet news refresher started (every %.0fs)", self._interval_s)

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
