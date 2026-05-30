"""Tests for cabinet_flashcards: parse, render, prompt, env, pool generator."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from cabinet_flashcards import (
    DEFAULT_FLASHCARDS_INTERVAL_S,
    FLASHCARD_CATEGORIES,
    FlashcardPoolGenerator,
    build_flashcard_prompt,
    flashcards_interval_from_env,
    parse_flashcards_json,
    render_flashcards_json,
)

_NOW = datetime(2026, 5, 29, 12, 0)


class TestParse:
    def test_valid_array(self) -> None:
        raw = '[{"cat":"SQL","front":"q","back":"a"}]'
        assert parse_flashcards_json(raw) == [{"cat": "SQL", "front": "q", "back": "a"}]

    def test_strips_fences(self) -> None:
        raw = '```json\n[{"cat":"SQL","front":"q","back":"a"}]\n```'
        assert len(parse_flashcards_json(raw)) == 1

    def test_malformed_returns_empty(self) -> None:
        assert parse_flashcards_json("not json") == []

    def test_non_list_returns_empty(self) -> None:
        assert parse_flashcards_json('{"cat":"x"}') == []

    def test_drops_incomplete_items(self) -> None:
        raw = '[{"cat":"SQL","front":"q","back":"a"},{"cat":"SQL","front":""}]'
        assert len(parse_flashcards_json(raw)) == 1


class TestRender:
    def test_wraps_in_cards_key(self) -> None:
        out = json.loads(render_flashcards_json([{"cat": "SQL", "front": "q", "back": "a"}]))
        assert out["cards"][0]["front"] == "q"

    def test_includes_generated_at(self) -> None:
        out = json.loads(render_flashcards_json([], "2026-05-29T12:00:00"))
        assert out["generated_at"] == "2026-05-29T12:00:00"


class TestPrompt:
    def test_mentions_category_and_count(self) -> None:
        p = build_flashcard_prompt("Statistics", 25)
        assert "Statistics" in p and "25" in p


class TestEnv:
    def test_default(self) -> None:
        assert flashcards_interval_from_env({}) == DEFAULT_FLASHCARDS_INTERVAL_S

    def test_parse(self) -> None:
        assert flashcards_interval_from_env({"CABINET_FLASHCARDS_S": "3600"}) == 3600.0

    def test_invalid(self) -> None:
        assert flashcards_interval_from_env({"CABINET_FLASHCARDS_S": "x"}) == DEFAULT_FLASHCARDS_INTERVAL_S


def _gen(tmp_path: Path, llm: Any) -> FlashcardPoolGenerator:
    return FlashcardPoolGenerator(
        llm_call=llm,
        feed_dir=tmp_path / "feeds",
        pool_path=tmp_path / "data" / "flashcard_pool.json",
        get_current_datetime=lambda: _NOW,
    )


class TestGenerator:
    def test_generates_across_categories(self, tmp_path: Path) -> None:
        async def llm(prompt: str) -> str:
            return '[{"cat":"X","front":"q","back":"a"},{"cat":"X","front":"q2","back":"a2"}]'

        asyncio.run(_gen(tmp_path, llm).generate_once())
        out = json.loads((tmp_path / "feeds" / "flashcards.json").read_text(encoding="utf-8"))
        assert len(out["cards"]) == 2 * len(FLASHCARD_CATEGORIES)
        # cache persisted too
        assert (tmp_path / "data" / "flashcard_pool.json").is_file()

    def test_falls_back_to_cache_on_failure(self, tmp_path: Path) -> None:
        pool_path = tmp_path / "data" / "flashcard_pool.json"
        pool_path.parent.mkdir(parents=True)
        pool_path.write_text(
            json.dumps({"cards": [{"cat": "SQL", "front": "old", "back": "a"}]}),
            encoding="utf-8",
        )

        async def boom(prompt: str) -> str:
            raise RuntimeError("LLM down")

        asyncio.run(_gen(tmp_path, boom).generate_once())
        out = json.loads((tmp_path / "feeds" / "flashcards.json").read_text(encoding="utf-8"))
        assert out["cards"][0]["front"] == "old"

    def test_no_write_on_failure_without_cache(self, tmp_path: Path) -> None:
        async def boom(prompt: str) -> str:
            raise RuntimeError("LLM down")

        asyncio.run(_gen(tmp_path, boom).generate_once())
        assert not (tmp_path / "feeds" / "flashcards.json").exists()


def test_file_line_budget() -> None:
    mod = Path(__file__).resolve().parents[1] / "cabinet_flashcards.py"
    assert len(mod.read_text(encoding="utf-8").splitlines()) <= 300
