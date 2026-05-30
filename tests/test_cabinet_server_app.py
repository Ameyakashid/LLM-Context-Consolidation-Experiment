"""App-level tests for the Cabinet Starlette app via Starlette's TestClient.

Covers static serving, the no-store header, and the IP-whitelist 403 path.
No network: TestClient drives the ASGI app in-process.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from cabinet_server import build_cabinet_app, parse_ip_whitelist


def _make_static(tmp_path: Path) -> tuple[Path, Path]:
    static_dir = tmp_path / "cabinet"
    feeds = static_dir / "feeds"
    feeds.mkdir(parents=True)
    (static_dir / "index.html").write_text("<h1>The Cabinet</h1>", encoding="utf-8")
    (feeds / "tasks.md").write_text("## Active\n- **Do it** (high)\n", encoding="utf-8")
    wallpaper_dir = tmp_path / "cabinet" / "wallpapers"
    wallpaper_dir.mkdir(parents=True)
    return static_dir, wallpaper_dir


def test_serves_index_at_root(tmp_path: Path) -> None:
    static_dir, wall = _make_static(tmp_path)
    app = build_cabinet_app(static_dir, wall, [])
    with TestClient(app) as client:
        r = client.get("/")
        assert r.status_code == 200
        assert "The Cabinet" in r.text


def test_serves_feed_file(tmp_path: Path) -> None:
    static_dir, wall = _make_static(tmp_path)
    app = build_cabinet_app(static_dir, wall, [])
    with TestClient(app) as client:
        r = client.get("/feeds/tasks.md")
        assert r.status_code == 200
        assert "## Active" in r.text


def test_no_store_header_present(tmp_path: Path) -> None:
    static_dir, wall = _make_static(tmp_path)
    app = build_cabinet_app(static_dir, wall, [])
    with TestClient(app) as client:
        r = client.get("/feeds/tasks.md")
        assert "no-store" in r.headers.get("cache-control", "")


def test_missing_file_404(tmp_path: Path) -> None:
    static_dir, wall = _make_static(tmp_path)
    app = build_cabinet_app(static_dir, wall, [])
    with TestClient(app) as client:
        assert client.get("/feeds/does-not-exist.md").status_code == 404


def test_off_whitelist_client_forbidden(tmp_path: Path) -> None:
    static_dir, wall = _make_static(tmp_path)
    nets = parse_ip_whitelist('["127.0.0.1"]')
    app = build_cabinet_app(static_dir, wall, nets)
    with TestClient(app, client=("8.8.8.8", 12345)) as client:
        assert client.get("/").status_code == 403


def test_whitelisted_client_allowed(tmp_path: Path) -> None:
    static_dir, wall = _make_static(tmp_path)
    nets = parse_ip_whitelist('["127.0.0.1"]')
    app = build_cabinet_app(static_dir, wall, nets)
    with TestClient(app, client=("127.0.0.1", 12345)) as client:
        assert client.get("/").status_code == 200


def test_wallpapers_mount_404_when_empty(tmp_path: Path) -> None:
    static_dir, wall = _make_static(tmp_path)
    app = build_cabinet_app(static_dir, wall, [])
    with TestClient(app) as client:
        assert client.get("/wallpapers/manifest.json").status_code == 404


def test_file_line_budget() -> None:
    server = Path(__file__).resolve().parents[1] / "cabinet_server.py"
    lines = server.read_text(encoding="utf-8").splitlines()
    assert len(lines) <= 300, f"cabinet_server.py is {len(lines)} lines"


def test_no_platform_branches() -> None:
    server = Path(__file__).resolve().parents[1] / "cabinet_server.py"
    source = server.read_text(encoding="utf-8")
    assert "sys.platform" not in source
    assert "os.name" not in source
