"""Tests for cabinet_wallpapers: scan, manifest render, staleness, watcher."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from cabinet_wallpapers import (
    DEFAULT_WATCH_INTERVAL_S,
    WallpaperWatcher,
    manifest_is_stale,
    render_manifest_json,
    scan_wallpapers,
    wallpaper_interval_from_env,
)


def _img(wall: Path, name: str) -> Path:
    wall.mkdir(parents=True, exist_ok=True)
    p = wall / name
    p.write_bytes(b"\x89PNG\r\n")  # token bytes; content irrelevant to scanning
    return p


class TestScan:
    def test_sorted_and_titled(self, tmp_path: Path) -> None:
        _img(tmp_path, "02-emberfall.png")
        _img(tmp_path, "01-nightfall.png")
        entries = scan_wallpapers(tmp_path)
        assert [e["file"] for e in entries] == ["01-nightfall.png", "02-emberfall.png"]
        assert entries[0]["title"] == "Nightfall"   # leading "01-" stripped, title-cased

    def test_ignores_non_images(self, tmp_path: Path) -> None:
        _img(tmp_path, "a.png")
        (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
        assert [e["file"] for e in scan_wallpapers(tmp_path)] == ["a.png"]

    def test_empty_dir(self, tmp_path: Path) -> None:
        assert scan_wallpapers(tmp_path) == []


class TestRender:
    def test_manifest_shape(self) -> None:
        out = json.loads(render_manifest_json([{"file": "a.png", "title": "A"}], 30000))
        assert out["intervalMs"] == 30000
        assert out["wallpapers"][0] == {"file": "a.png", "title": "A"}


class TestStaleness:
    def test_missing_manifest_with_images_is_stale(self, tmp_path: Path) -> None:
        _img(tmp_path, "a.png")
        assert manifest_is_stale(tmp_path, tmp_path / "manifest.json") is True

    def test_missing_manifest_empty_folder_not_stale(self, tmp_path: Path) -> None:
        tmp_path.mkdir(exist_ok=True)
        assert manifest_is_stale(tmp_path, tmp_path / "manifest.json") is False

    def test_count_mismatch_is_stale(self, tmp_path: Path) -> None:
        _img(tmp_path, "a.png")
        _img(tmp_path, "b.png")
        m = tmp_path / "manifest.json"
        m.write_text(render_manifest_json([{"file": "a.png", "title": "A"}]), encoding="utf-8")
        assert manifest_is_stale(tmp_path, m) is True

    def test_in_sync_not_stale(self, tmp_path: Path) -> None:
        _img(tmp_path, "a.png")
        m = tmp_path / "manifest.json"
        # write manifest AFTER the image so its mtime is newer
        time.sleep(0.01)
        m.write_text(render_manifest_json(scan_wallpapers(tmp_path)), encoding="utf-8")
        # nudge manifest mtime to be safely newest
        os.utime(m, (time.time() + 1, time.time() + 1))
        assert manifest_is_stale(tmp_path, m) is False


class TestWatcher:
    def test_refresh_once_writes_manifest(self, tmp_path: Path) -> None:
        _img(tmp_path, "01-nightfall.png")
        watcher = WallpaperWatcher(wallpaper_dir=tmp_path)
        assert watcher.refresh_once() is True
        data = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
        assert data["wallpapers"][0]["file"] == "01-nightfall.png"

    def test_refresh_once_noop_when_in_sync(self, tmp_path: Path) -> None:
        _img(tmp_path, "a.png")
        watcher = WallpaperWatcher(wallpaper_dir=tmp_path)
        assert watcher.refresh_once() is True   # first build
        assert watcher.refresh_once() is False  # already in sync


class TestEnv:
    def test_default(self) -> None:
        assert wallpaper_interval_from_env({}) == DEFAULT_WATCH_INTERVAL_S

    def test_parse(self) -> None:
        assert wallpaper_interval_from_env({"CABINET_WALLPAPER_S": "120"}) == 120.0


def test_file_line_budget() -> None:
    mod = Path(__file__).resolve().parents[1] / "cabinet_wallpapers.py"
    assert len(mod.read_text(encoding="utf-8").splitlines()) <= 300
