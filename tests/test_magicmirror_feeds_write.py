"""Atomic-write and feed-dir tests for the MagicMirror feed writer.

Renderer golden tests live in ``test_magicmirror_feeds_render.py``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from magicmirror_feeds import (
    SCHEDULE_FEED_FILENAME,
    STATE_BUFFERS_FEED_FILENAME,
    TASKS_FEED_FILENAME,
    resolve_feed_dir,
    write_feeds,
)


class TestResolveFeedDir:
    def test_points_at_markdown_subdir(self, tmp_path: Path) -> None:
        feed = resolve_feed_dir(tmp_path)
        assert feed == (
            tmp_path / "magicmirror" / "modules" / "MMM-Markdown" / "markdown"
        )

    def test_matches_repo_tree(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        feed = resolve_feed_dir(repo_root)
        assert feed.is_dir(), (
            f"Expected vendored MMM-Markdown markdown dir at {feed}"
        )


class TestWriteFeeds:
    def test_creates_three_files(self, tmp_path: Path) -> None:
        feed_dir = tmp_path / "feeds"
        write_feeds(feed_dir, "A\n", "B\n", "C\n")
        assert (feed_dir / TASKS_FEED_FILENAME).read_text(encoding="utf-8") == "A\n"
        assert (
            feed_dir / STATE_BUFFERS_FEED_FILENAME
        ).read_text(encoding="utf-8") == "B\n"
        assert (
            feed_dir / SCHEDULE_FEED_FILENAME
        ).read_text(encoding="utf-8") == "C\n"

    def test_creates_missing_parent_dir(self, tmp_path: Path) -> None:
        feed_dir = tmp_path / "nested" / "feeds"
        write_feeds(feed_dir, "a", "b", "c")
        assert feed_dir.is_dir()

    def test_overwrites_existing(self, tmp_path: Path) -> None:
        feed_dir = tmp_path / "feeds"
        feed_dir.mkdir()
        (feed_dir / TASKS_FEED_FILENAME).write_text("OLD", encoding="utf-8")
        write_feeds(feed_dir, "NEW\n", "x", "y")
        assert (
            feed_dir / TASKS_FEED_FILENAME
        ).read_text(encoding="utf-8") == "NEW\n"

    def test_no_tmp_leak_on_success(self, tmp_path: Path) -> None:
        feed_dir = tmp_path / "feeds"
        write_feeds(feed_dir, "a", "b", "c")
        leftover = [p for p in feed_dir.iterdir() if p.name.endswith(".tmp")]
        assert leftover == []

    def test_interrupted_write_leaves_prior_file_intact(
        self, tmp_path: Path
    ) -> None:
        feed_dir = tmp_path / "feeds"
        feed_dir.mkdir()
        (feed_dir / TASKS_FEED_FILENAME).write_text("OLD-A", encoding="utf-8")
        (feed_dir / STATE_BUFFERS_FEED_FILENAME).write_text(
            "OLD-B", encoding="utf-8"
        )
        (feed_dir / SCHEDULE_FEED_FILENAME).write_text("OLD-C", encoding="utf-8")
        real_write = Path.write_text

        def _flaky_write(self: Path, data: str, *args: Any, **kwargs: Any) -> int:
            if self.name == "state_buffers.tmp":
                raise OSError("simulated write failure")
            return real_write(self, data, *args, **kwargs)

        with patch.object(Path, "write_text", _flaky_write):
            with pytest.raises(OSError):
                write_feeds(feed_dir, "NEW-A", "NEW-B", "NEW-C")
        assert (
            feed_dir / TASKS_FEED_FILENAME
        ).read_text(encoding="utf-8") == "NEW-A"
        assert (
            feed_dir / STATE_BUFFERS_FEED_FILENAME
        ).read_text(encoding="utf-8") == "OLD-B"
        assert (
            feed_dir / SCHEDULE_FEED_FILENAME
        ).read_text(encoding="utf-8") == "OLD-C"

    def test_writes_utf8(self, tmp_path: Path) -> None:
        feed_dir = tmp_path / "feeds"
        write_feeds(feed_dir, "café — 🫖\n", "bufs", "sched")
        raw = (feed_dir / TASKS_FEED_FILENAME).read_bytes()
        assert raw == "café — 🫖\n".encode("utf-8")
