"""Tests for the dashboard read-only HTTP API."""

import json
import threading
import urllib.request
from datetime import date, datetime, time, timezone
from http.server import HTTPServer
from pathlib import Path

import pytest

from buffer_store import BufferStore
from checkin_schedule import CheckInScheduleStore
from cognitive_state_writer import write_cognitive_state
from dashboard_api import (
    ACTIVITY_FEED_LIMIT,
    DashboardConfig,
    _build_activity_feed,
    dispatch_route,
    handle_activity,
    handle_buffers,
    handle_schedule,
    handle_state,
    handle_tasks,
    load_config_from_env,
    make_handler_class,
)
from memory_store import MemoryEntryStore
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
    return d


def _start_test_server(
    data_dir: Path, static_dir: Path
) -> tuple[HTTPServer, str]:
    """Start a server on an ephemeral port, return (server, base_url)."""
    handler_class = make_handler_class(data_dir, static_dir)
    server = HTTPServer(("127.0.0.1", 0), handler_class)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{port}"


@pytest.fixture()
def server_url(data_dir: Path, static_dir: Path) -> str:
    server, url = _start_test_server(data_dir, static_dir)
    yield url
    server.shutdown()


def _get_json(url: str) -> tuple[int, dict[str, object]]:
    """GET a URL and return (status_code, parsed_json)."""
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


# ---------------------------------------------------------------------------
# Pure handler tests (no server needed)
# ---------------------------------------------------------------------------


class TestHandleState:
    def test_returns_unknown_when_no_file(self, data_dir: Path) -> None:
        result = handle_state(data_dir / "cognitive_state.json")
        assert result["state"] == "unknown"
        assert result["history"] == []

    def test_returns_persisted_state(self, data_dir: Path) -> None:
        state_path = data_dir / "cognitive_state.json"
        write_cognitive_state(state_path, "focus", "baseline", False)
        result = handle_state(state_path)
        assert result["current"]["state"] == "focus"
        assert len(result["history"]) == 1


class TestHandleTasks:
    def test_returns_empty_when_no_file(self, data_dir: Path) -> None:
        result = handle_tasks(data_dir)
        assert result == {"tasks": []}

    def test_returns_active_tasks_only(self, data_dir: Path) -> None:
        store = TaskStore(data_dir / "tasks.json")
        store.create_task("Open task", "medium", None, None, [])
        done_task = store.create_task("Done task", "low", None, None, [])
        store.mark_complete(done_task.id)
        result = handle_tasks(data_dir)
        assert len(result["tasks"]) == 1
        assert result["tasks"][0]["title"] == "Open task"

    def test_excludes_done_tasks(self, data_dir: Path) -> None:
        store = TaskStore(data_dir / "tasks.json")
        t = store.create_task("Task", "high", None, None, [])
        store.mark_complete(t.id)
        result = handle_tasks(data_dir)
        assert result["tasks"] == []


class TestHandleBuffers:
    def test_returns_empty_when_no_file(self, data_dir: Path) -> None:
        result = handle_buffers(data_dir)
        assert result == {"buffers": []}

    def test_returns_all_buffers(self, data_dir: Path) -> None:
        store = BufferStore(data_dir / "buffers.json")
        store.create_buffer("Meds", 5, 10, 7, date(2026, 4, 15), 2)
        store.create_buffer("Laundry", 3, 5, 7, date(2026, 4, 12), 1)
        result = handle_buffers(data_dir)
        assert len(result["buffers"]) == 2
        names = {b["name"] for b in result["buffers"]}
        assert names == {"Meds", "Laundry"}


class TestHandleSchedule:
    def test_returns_empty_when_no_file(self, data_dir: Path) -> None:
        result = handle_schedule(data_dir)
        assert result == {"checkins": []}

    def test_returns_all_entries(self, data_dir: Path) -> None:
        store = CheckInScheduleStore(data_dir / "checkins.json")
        result = handle_schedule(data_dir)
        assert len(result["checkins"]) == 4


class TestHandleActivity:
    def test_returns_empty_when_no_stores(self, data_dir: Path) -> None:
        result = handle_activity(data_dir)
        assert result == {"activity": []}

    def test_includes_completed_tasks(self, data_dir: Path) -> None:
        store = TaskStore(data_dir / "tasks.json")
        t = store.create_task("Finish report", "high", None, None, [])
        store.mark_complete(t.id)
        result = handle_activity(data_dir)
        assert any(e["type"] == "task_completed" for e in result["activity"])

    def test_includes_buffer_updates(self, data_dir: Path) -> None:
        store = BufferStore(data_dir / "buffers.json")
        store.create_buffer("Meds", 5, 10, 7, date(2026, 4, 15), 2)
        result = handle_activity(data_dir)
        assert any(e["type"] == "buffer_update" for e in result["activity"])

    def test_includes_fired_checkins(self, data_dir: Path) -> None:
        store = CheckInScheduleStore(data_dir / "checkins.json")
        store.record_fired("morning_motivation", date(2026, 4, 10))
        result = handle_activity(data_dir)
        assert any(e["type"] == "checkin_fired" for e in result["activity"])

    def test_limits_feed_size(self, data_dir: Path) -> None:
        store = TaskStore(data_dir / "tasks.json")
        for i in range(ACTIVITY_FEED_LIMIT + 5):
            t = store.create_task(f"Task {i}", "low", None, None, [])
            store.mark_complete(t.id)
        result = handle_activity(data_dir)
        assert len(result["activity"]) == ACTIVITY_FEED_LIMIT


class TestDispatchRoute:
    def test_known_routes_return_results(self, data_dir: Path) -> None:
        for path in ["/state", "/tasks", "/buffers", "/schedule", "/activity"]:
            result = dispatch_route(path, data_dir)
            assert result is not None
            status, body = result
            assert status == 200

    def test_unknown_route_returns_none(self, data_dir: Path) -> None:
        assert dispatch_route("/unknown", data_dir) is None


# ---------------------------------------------------------------------------
# HTTP server integration tests
# ---------------------------------------------------------------------------


class TestHTTPEndpoints:
    def test_state_endpoint(self, data_dir: Path, server_url: str) -> None:
        status, body = _get_json(f"{server_url}/state")
        assert status == 200
        assert "state" in body or "current" in body

    def test_tasks_endpoint(self, data_dir: Path, server_url: str) -> None:
        status, body = _get_json(f"{server_url}/tasks")
        assert status == 200
        assert "tasks" in body

    def test_buffers_endpoint(self, data_dir: Path, server_url: str) -> None:
        status, body = _get_json(f"{server_url}/buffers")
        assert status == 200
        assert "buffers" in body

    def test_schedule_endpoint(self, data_dir: Path, server_url: str) -> None:
        status, body = _get_json(f"{server_url}/schedule")
        assert status == 200
        assert "checkins" in body

    def test_activity_endpoint(self, data_dir: Path, server_url: str) -> None:
        status, body = _get_json(f"{server_url}/activity")
        assert status == 200
        assert "activity" in body

    def test_unknown_endpoint_returns_404(
        self, data_dir: Path, server_url: str
    ) -> None:
        status, body = _get_json(f"{server_url}/nope")
        assert status == 404
        assert "error" in body

    def test_cors_headers_on_get(
        self, data_dir: Path, server_url: str
    ) -> None:
        req = urllib.request.Request(f"{server_url}/state")
        with urllib.request.urlopen(req) as resp:
            assert resp.headers["Access-Control-Allow-Origin"] == "*"
            assert "GET" in resp.headers["Access-Control-Allow-Methods"]

    def test_options_preflight(
        self, data_dir: Path, server_url: str
    ) -> None:
        req = urllib.request.Request(
            f"{server_url}/state", method="OPTIONS"
        )
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 204
            assert resp.headers["Access-Control-Allow-Origin"] == "*"

    def test_json_content_type(
        self, data_dir: Path, server_url: str
    ) -> None:
        req = urllib.request.Request(f"{server_url}/tasks")
        with urllib.request.urlopen(req) as resp:
            assert "application/json" in resp.headers["Content-Type"]

    def test_tasks_with_data(
        self, data_dir: Path, server_url: str
    ) -> None:
        store = TaskStore(data_dir / "tasks.json")
        store.create_task("Test task", "high", None, None, [])
        status, body = _get_json(f"{server_url}/tasks")
        assert status == 200
        assert len(body["tasks"]) == 1
        assert body["tasks"][0]["title"] == "Test task"


class TestLoadConfigFromEnv:
    def test_data_dir_expands_tilde(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DASHBOARD_DATA_DIR", "~/adhd-dashboard-test")
        config = load_config_from_env()
        assert str(config.data_dir).startswith(str(Path.home()))
        assert "~" not in str(config.data_dir)

    def test_static_dir_expands_tilde(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DASHBOARD_STATIC_DIR", "~/adhd-static-test")
        config = load_config_from_env()
        assert str(config.static_dir).startswith(str(Path.home()))
        assert "~" not in str(config.static_dir)
