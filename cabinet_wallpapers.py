"""Wallpaper manifest builder for the Cabinet screensaver.

The user drops images into a local folder (``CABINET_WALLPAPER_DIR``, served
at ``/wallpapers``); this watcher regenerates ``manifest.json`` whenever the
folder changes, so new images appear and removed ones drop out. The frontend
cross-fades slowly through whatever the manifest lists (manual Wallpaper mode
— no idle auto-engage).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Mapping
from pathlib import Path

log = logging.getLogger(__name__)

MANIFEST_FILENAME = "manifest.json"
DEFAULT_INTERVAL_MS = 30000
DEFAULT_WATCH_INTERVAL_S = 60.0
_IMAGE_EXTS = {".png", ".jpg", ".jpeg"}
_LEADING_NUM_RE = re.compile(r"^\d+[-_\s]*")
_SEP_RE = re.compile(r"[-_]+")


def wallpaper_interval_from_env(
    env: Mapping[str, str] | None, default: float = DEFAULT_WATCH_INTERVAL_S,
) -> float:
    """Read the folder-watch cadence from ``CABINET_WALLPAPER_S`` (default 60s)."""
    raw = (env or {}).get("CABINET_WALLPAPER_S", "").strip()
    if not raw:
        return default
    try:
        val = float(raw)
    except ValueError:
        return default
    return val if val > 0 else default


def _list_images(wallpaper_dir: Path) -> list[Path]:
    try:
        entries = [
            p for p in wallpaper_dir.iterdir()
            if p.is_file() and p.suffix.lower() in _IMAGE_EXTS
        ]
    except OSError:
        return []
    return sorted(entries, key=lambda p: p.name.lower())


def _title_from_stem(stem: str) -> str:
    s = _LEADING_NUM_RE.sub("", stem)          # drop a leading "01-" / "02_"
    s = _SEP_RE.sub(" ", s).strip()
    return s.title() if s else stem


def scan_wallpapers(wallpaper_dir: Path) -> list[dict]:
    """Return ordered ``{file, title}`` entries for the images in the folder."""
    return [
        {"file": p.name, "title": _title_from_stem(p.stem)}
        for p in _list_images(wallpaper_dir)
    ]


def render_manifest_json(
    entries: list[dict], interval_ms: int = DEFAULT_INTERVAL_MS,
) -> str:
    """Serialize the manifest the frontend's Wallpaper mode reads."""
    return json.dumps(
        {"intervalMs": interval_ms, "wallpapers": entries}, ensure_ascii=False,
    )


def manifest_is_stale(wallpaper_dir: Path, manifest_path: Path) -> bool:
    """True when the manifest is missing or out of sync with the folder."""
    images = _list_images(wallpaper_dir)
    if not manifest_path.exists():
        return bool(images)  # nothing to do for an empty folder
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        listed = data.get("wallpapers", []) if isinstance(data, dict) else []
    except (OSError, json.JSONDecodeError):
        return True
    if len(listed) != len(images):
        return True  # an image was added or removed
    manifest_mtime = manifest_path.stat().st_mtime
    return any(p.stat().st_mtime > manifest_mtime for p in images)


def _write_manifest(manifest_path: Path, content: str) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = manifest_path.with_suffix(".tmp")
    tmp.write_text(content, encoding="utf-8", newline="\n")
    tmp.replace(manifest_path)


class WallpaperWatcher:
    """Async task that rebuilds ``manifest.json`` when the folder changes."""

    def __init__(
        self,
        wallpaper_dir: Path,
        interval_s: float = DEFAULT_WATCH_INTERVAL_S,
        interval_ms: int = DEFAULT_INTERVAL_MS,
    ) -> None:
        self._dir = wallpaper_dir
        self._manifest = wallpaper_dir / MANIFEST_FILENAME
        self._interval_s = interval_s
        self._interval_ms = interval_ms
        self._task: asyncio.Task[None] | None = None

    def refresh_once(self) -> bool:
        """Rewrite the manifest if stale. Returns True when it was rewritten."""
        if not manifest_is_stale(self._dir, self._manifest):
            return False
        _write_manifest(
            self._manifest,
            render_manifest_json(scan_wallpapers(self._dir), self._interval_ms),
        )
        log.info("Wallpaper manifest rebuilt for %s", self._dir)
        return True

    async def _run(self) -> None:
        while True:
            try:
                self.refresh_once()
            except Exception as exc:  # never let the task die
                log.warning("Wallpaper watcher tick failed: %s", exc)
            await asyncio.sleep(self._interval_s)

    async def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run())
        log.info("Wallpaper watcher started (every %.0fs)", self._interval_s)

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
