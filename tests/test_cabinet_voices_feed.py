"""Tests for render_voices_markdown + write_voices_feed (Cabinet voices feed)."""

from __future__ import annotations

from pathlib import Path

from magicmirror_feeds import (
    VOICES_FEED_FILENAME,
    render_voices_markdown,
    write_voices_feed,
)


def test_renders_voices_section() -> None:
    md = render_voices_markdown([("logic", "Three remain."), ("empathy", "Breathe.")])
    assert md.startswith("## Voices\n")
    assert "- LOGIC — Three remain." in md  # em-dash matches Cabinet parser
    assert "- EMPATHY — Breathe." in md


def test_uppercases_speaker() -> None:
    md = render_voices_markdown([("volition", "Begin.")])
    assert "- VOLITION — Begin." in md


def test_empty_list_returns_empty_string() -> None:
    assert render_voices_markdown([]) == ""


def test_blank_lines_skipped_to_empty() -> None:
    assert render_voices_markdown([("logic", "   ")]) == ""


def test_write_voices_feed_atomic(tmp_path: Path) -> None:
    feed_dir = tmp_path / "feeds"
    md = render_voices_markdown([("logic", "x")])
    write_voices_feed(feed_dir, md)
    written = (feed_dir / VOICES_FEED_FILENAME).read_text(encoding="utf-8")
    assert written == md
    assert not list(feed_dir.glob("*.tmp"))  # no temp leak
