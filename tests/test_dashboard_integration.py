"""Integration tests for dashboard startup, config endpoint, and end-to-end flow."""

import json
import os
import threading
import urllib.request
from datetime import date
from http.server import HTTPServer
from pathlib import Path

import pytest

from buffer_store import BufferStore
from cognitive_state_writer import write_cognitive_state
from dashboard_api import (
    DashboardConfig,
    create_dashboard_server,
    load_config_from_env,
    make_handler_class,
)
from task_store import TaskStore

import dashboard_api


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(dashboard_api, "_repo_root", lambda: tmp_path)
    monkeypatch.delenv("TASKWARRIOR_ENABLED", raising=False)
    d = tmp_path / "workspace" / "data"
    d.mkdir(parents=True)
    return d


@pytest.fixture()
def static_dir(tmp_path: Path) -> Path:
    d = tmp_path / "static"
    d.mkdir()
    (d / "index.html").write_text("<html><body>test</body></html>")
    return d


def _start_server(
    data_dir: Path, static_dir: Path, refresh_interval_ms: int = 30000
) -> tuple[HTTPServer, str]:
    handler = make_handler_class(data_dir, static_dir, refresh_interval_ms)
    server = HTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{port}"


@pytest.fixture()
def server_with_url(
    data_dir: Path, static_dir: Path
) -> tuple[str, Path, Path]:
    server, url = _start_server(data_dir, static_dir, 15000)
    yield url, data_dir, static_dir
    server.shutdown()


def _get(url: str) -> tuple[int, bytes, dict[str, str]]:
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req) as resp:
            headers = {k: resp.headers[k] for k in resp.headers}
            return resp.status, resp.read(), headers
    except urllib.error.HTTPError as exc:
        headers = {k: exc.headers[k] for k in exc.headers}
        return exc.code, exc.read(), headers


def _get_json(url: str) -> tuple[int, dict[str, object]]:
    status, body, _ = _get(url)
    return status, json.loads(body.decode("utf-8"))


# ---------------------------------------------------------------------------
# Config endpoint tests
# ---------------------------------------------------------------------------


class TestConfigEndpoint:
    def test_returns_refresh_interval(self, server_with_url: tuple[str, Path, Path]) -> None:
        url, _, _ = server_with_url
        status, body = _get_json(f"{url}/config")
        assert status == 200
        assert body["refresh_interval_ms"] == 15000

    def test_default_refresh_interval(self, data_dir: Path, static_dir: Path) -> None:
        server, url = _start_server(data_dir, static_dir)
        try:
            status, body = _get_json(f"{url}/config")
            assert status == 200
            assert body["refresh_interval_ms"] == 30000
        finally:
            server.shutdown()

    def test_config_has_cors_headers(self, server_with_url: tuple[str, Path, Path]) -> None:
        url, _, _ = server_with_url
        status, _, headers = _get(f"{url}/config")
        assert headers.get("Access-Control-Allow-Origin") == "*"


# ---------------------------------------------------------------------------
# DashboardConfig tests
# ---------------------------------------------------------------------------


class TestDashboardConfig:
    def test_refresh_interval_in_config(self) -> None:
        config = DashboardConfig(
            host="127.0.0.1",
            port=8085,
            data_dir=Path("data"),
            static_dir=Path("dashboard"),
            refresh_interval_ms=10000,
        )
        assert config.refresh_interval_ms == 10000

    def test_load_config_reads_refresh_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DASHBOARD_REFRESH_INTERVAL", "5000")
        config = load_config_from_env()
        assert config.refresh_interval_ms == 5000

    def test_load_config_default_refresh(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DASHBOARD_REFRESH_INTERVAL", raising=False)
        config = load_config_from_env()
        assert config.refresh_interval_ms == 30000


# ---------------------------------------------------------------------------
# Server creation tests
# ---------------------------------------------------------------------------


class TestServerCreation:
    def test_create_server_binds(self, data_dir: Path, static_dir: Path) -> None:
        config = DashboardConfig(
            host="127.0.0.1",
            port=0,
            data_dir=data_dir,
            static_dir=static_dir,
            refresh_interval_ms=30000,
        )
        server = create_dashboard_server(config)
        assert server.server_address[0] == "127.0.0.1"
        assert server.server_address[1] > 0
        server.server_close()

    def test_create_server_with_custom_config(self, data_dir: Path, static_dir: Path) -> None:
        config = DashboardConfig(
            host="127.0.0.1",
            port=0,
            data_dir=data_dir,
            static_dir=static_dir,
            refresh_interval_ms=60000,
        )
        server = create_dashboard_server(config)
        server.server_close()


# ---------------------------------------------------------------------------
# End-to-end flow: API + static serving in same server
# ---------------------------------------------------------------------------


class TestEndToEndFlow:
    def test_static_and_api_coexist(
        self, server_with_url: tuple[str, Path, Path]
    ) -> None:
        url, _, _ = server_with_url
        status_api, body_api = _get_json(f"{url}/tasks")
        assert status_api == 200
        assert "tasks" in body_api

        status_static, content, _ = _get(url)
        assert status_static == 200
        assert b"<html>" in content

    def test_api_reflects_store_changes(
        self, server_with_url: tuple[str, Path, Path]
    ) -> None:
        url, data_dir, _ = server_with_url
        _, body = _get_json(f"{url}/tasks")
        assert body["tasks"] == []

        store = TaskStore(data_dir / "tasks.json")
        store.create_task("New task", "high", None, None, [])
        _, body = _get_json(f"{url}/tasks")
        assert len(body["tasks"]) == 1
        assert body["tasks"][0]["title"] == "New task"

    def test_state_endpoint_with_persisted_state(
        self, server_with_url: tuple[str, Path, Path]
    ) -> None:
        url, data_dir, _ = server_with_url
        write_cognitive_state(data_dir / "cognitive_state.json", "focus", "baseline", False)
        _, body = _get_json(f"{url}/state")
        assert body["current"]["state"] == "focus"

    def test_buffers_endpoint_with_data(
        self, server_with_url: tuple[str, Path, Path]
    ) -> None:
        url, data_dir, _ = server_with_url
        store = BufferStore(data_dir / "buffers.json")
        store.create_buffer("Rent", 3, 4, 30, date(2026, 5, 1), 1)
        _, body = _get_json(f"{url}/buffers")
        assert len(body["buffers"]) == 1
        assert body["buffers"][0]["name"] == "Rent"


# ---------------------------------------------------------------------------
# Launcher module import test
# ---------------------------------------------------------------------------


class TestStartModule:
    def test_start_module_importable(self) -> None:
        import start
        assert hasattr(start, "main")
        assert hasattr(start, "run_dashboard")
