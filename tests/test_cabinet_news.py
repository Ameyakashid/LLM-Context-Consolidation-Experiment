"""Tests for cabinet_news: sanitize, dedup, Gazette render, fetch, refresher.

No network: ddgs is monkeypatched. Verifies output matches the modes.js
Gazette parser contract (## headline / *meta* / body).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

import cabinet_news
from cabinet_news import (
    DEFAULT_NEWS_INTERVAL_S,
    DEFAULT_NEWS_MAX,
    DEFAULT_NEWS_QUERY,
    NewsRefresher,
    dedup_articles,
    fetch_news,
    news_settings_from_env,
    render_news_markdown,
    strip_html,
)


class TestStripHtml:
    def test_removes_tags_and_unescapes(self) -> None:
        assert strip_html("<b>Tom &amp; Jerry</b>") == "Tom & Jerry"

    def test_handles_none(self) -> None:
        assert strip_html("") == ""


class TestDedup:
    def test_dedups_by_title_and_url(self) -> None:
        items = [
            {"title": "A", "url": "u1"},
            {"title": "A", "url": "u1"},
            {"title": "B", "url": "u2"},
        ]
        assert len(dedup_articles(items)) == 2


class TestRender:
    def test_gazette_grammar(self) -> None:
        md = render_news_markdown([
            {"title": "Observatory reopens", "source": "Science", "date": "2h ago",
             "body": "<p>Volunteers reground the lens.</p>"},
        ])
        assert "## Observatory reopens" in md
        assert "*Science · 2h ago*" in md
        assert "Volunteers reground the lens." in md

    def test_empty_when_no_articles(self) -> None:
        assert render_news_markdown([]) == ""

    def test_skips_titleless(self) -> None:
        assert render_news_markdown([{"body": "no title"}]) == ""


class TestFetch:
    def test_fetch_uses_ddgs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import ddgs

        class _FakeDDGS:
            def news(self, query: str, **kwargs: Any) -> list[dict]:
                return [{"title": query, "body": "b", "source": "S", "date": "1h"}]

        # fetch_news does `from ddgs import DDGS` at call time -> patch the module attr
        monkeypatch.setattr(ddgs, "DDGS", _FakeDDGS)
        out = fetch_news("space", max_results=1)
        assert out and out[0]["title"] == "space"

    def test_fetch_failure_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import ddgs

        class _Boom:
            def news(self, *a: Any, **k: Any) -> list[dict]:
                raise RuntimeError("ratelimited")

        monkeypatch.setattr(ddgs, "DDGS", _Boom)
        assert fetch_news("x") == []


class TestEnvSettings:
    def test_defaults(self) -> None:
        q, m, s = news_settings_from_env({})
        assert (q, m, s) == (DEFAULT_NEWS_QUERY, DEFAULT_NEWS_MAX, DEFAULT_NEWS_INTERVAL_S)

    def test_overrides(self) -> None:
        q, m, s = news_settings_from_env({
            "CABINET_NEWS_QUERY": "space", "CABINET_NEWS_MAX": "3", "CABINET_NEWS_S": "600",
        })
        assert (q, m, s) == ("space", 3, 600.0)

    def test_bad_values_fall_back(self) -> None:
        _, m, s = news_settings_from_env({"CABINET_NEWS_MAX": "x", "CABINET_NEWS_S": "0"})
        assert (m, s) == (DEFAULT_NEWS_MAX, DEFAULT_NEWS_INTERVAL_S)


class TestRefresher:
    def test_refresh_once_writes_news_md(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import ddgs

        class _FakeDDGS:
            def news(self, query: str, **kwargs: Any) -> list[dict]:
                return [{"title": "Lead", "source": "Desk", "date": "now", "body": "Body."}]

        monkeypatch.setattr(ddgs, "DDGS", _FakeDDGS)
        ref = NewsRefresher(feed_dir=tmp_path / "feeds", query="q")
        asyncio.run(ref.refresh_once())
        out = (tmp_path / "feeds" / "news.md").read_text(encoding="utf-8")
        assert "## Lead" in out and "*Desk · now*" in out

    def test_refresh_keeps_last_good_on_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import ddgs

        class _EmptyDDGS:
            def news(self, *a: Any, **k: Any) -> list[dict]:
                return []

        monkeypatch.setattr(ddgs, "DDGS", _EmptyDDGS)
        feed_dir = tmp_path / "feeds"
        feed_dir.mkdir()
        (feed_dir / "news.md").write_text("## Old\n", encoding="utf-8")
        asyncio.run(NewsRefresher(feed_dir=feed_dir, query="q").refresh_once())
        assert (feed_dir / "news.md").read_text(encoding="utf-8") == "## Old\n"


def test_file_line_budget() -> None:
    mod = Path(__file__).resolve().parents[1] / "cabinet_news.py"
    assert len(mod.read_text(encoding="utf-8").splitlines()) <= 300
