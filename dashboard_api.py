"""Read-only HTTP API serving dashboard data from existing stores.

Endpoints (all GET):
  /state    — current cognitive state
  /tasks    — active tasks (non-done)
  /buffers  — all buffers with levels
  /schedule — check-in schedule
  /activity — recent activity feed

Uses stdlib http.server — no external dependencies.
"""

import json
import logging
import os
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from buffer_store import BufferStore
from checkin_schedule import CheckInScheduleStore
from cognitive_state_writer import read_cognitive_state
from task_store_factory import build_task_store

log = logging.getLogger(__name__)


def _repo_root() -> Path:
    """Return the repo root — the directory containing dashboard_api.py."""
    return Path(__file__).resolve().parent

ACTIVITY_FEED_LIMIT = 20


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DashboardConfig:
    """Configuration for the dashboard HTTP server."""

    host: str
    port: int
    data_dir: Path
    static_dir: Path
    refresh_interval_ms: int


def load_config_from_env() -> DashboardConfig:
    """Read dashboard configuration from environment variables.

    ``DASHBOARD_DATA_DIR`` and ``DASHBOARD_STATIC_DIR`` pass through
    ``Path.expanduser`` so the Mac-block ``.env.example`` entries
    (e.g. ``~/Library/Application Support/...``) resolve correctly.
    """
    return DashboardConfig(
        host=os.environ.get("DASHBOARD_HOST", "0.0.0.0"),
        port=int(os.environ.get("DASHBOARD_PORT", "8085")),
        data_dir=Path(os.environ.get("DASHBOARD_DATA_DIR", "data")).expanduser(),
        static_dir=Path(os.environ.get("DASHBOARD_STATIC_DIR", "dashboard")).expanduser(),
        refresh_interval_ms=int(os.environ.get("DASHBOARD_REFRESH_INTERVAL", "30000")),
    )


# ---------------------------------------------------------------------------
# Route handlers — pure functions returning JSON-serializable dicts
# ---------------------------------------------------------------------------

def handle_state(state_path: Path) -> dict[str, object]:
    """Return current cognitive state from persisted file."""
    state_file = read_cognitive_state(state_path)
    if state_file is None:
        return {"state": "unknown", "history": []}
    return state_file.model_dump(mode="json")


def handle_tasks(data_dir: Path) -> dict[str, object]:
    """Return active (non-done) tasks."""
    store = build_task_store(env=os.environ, repo_root=_repo_root())
    active = [
        t for t in store.list_tasks() if t.status != "done"
    ]
    return {"tasks": [t.model_dump(mode="json") for t in active]}


def handle_buffers(data_dir: Path) -> dict[str, object]:
    """Return all buffers."""
    store_path = data_dir / "buffers.json"
    if not store_path.exists():
        return {"buffers": []}
    store = BufferStore(store_path)
    return {"buffers": [b.model_dump(mode="json") for b in store.list_buffers()]}


def handle_schedule(data_dir: Path) -> dict[str, object]:
    """Return check-in schedule entries."""
    store_path = data_dir / "checkins.json"
    if not store_path.exists():
        return {"checkins": []}
    store = CheckInScheduleStore(store_path)
    return {
        "checkins": [e.model_dump(mode="json") for e in store.list_entries()]
    }


def _build_activity_feed(data_dir: Path) -> list[dict[str, object]]:
    """Assemble recent activity from store timestamps."""
    events: list[dict[str, object]] = []

    store = build_task_store(env=os.environ, repo_root=_repo_root())
    for task in store.list_tasks():
        if task.status == "done":
            events.append({
                "type": "task_completed",
                "title": task.title,
                "at": task.updated_at.isoformat(),
            })

    buffers_path = data_dir / "buffers.json"
    if buffers_path.exists():
        store = BufferStore(buffers_path)
        for buffer in store.list_buffers():
            events.append({
                "type": "buffer_update",
                "name": buffer.name,
                "level": buffer.buffer_level,
                "capacity": buffer.buffer_capacity,
                "at": buffer.updated_at.isoformat(),
            })

    checkins_path = data_dir / "checkins.json"
    if checkins_path.exists():
        sched = CheckInScheduleStore(checkins_path)
        for entry in sched.list_entries():
            if entry.last_run_date is not None:
                events.append({
                    "type": "checkin_fired",
                    "name": entry.display_name,
                    "at": entry.last_run_date.isoformat(),
                })

    events.sort(key=lambda e: str(e.get("at", "")), reverse=True)
    return events[:ACTIVITY_FEED_LIMIT]


def handle_activity(data_dir: Path) -> dict[str, object]:
    """Return recent activity feed."""
    return {"activity": _build_activity_feed(data_dir)}


# ---------------------------------------------------------------------------
# Static file serving
# ---------------------------------------------------------------------------

STATIC_CONTENT_TYPES: dict[str, str] = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
}


def resolve_static_file(
    static_dir: Path, request_path: str
) -> tuple[bytes, str] | None:
    """Map a request path to a static file. Returns (content, content_type) or None."""
    clean = request_path.lstrip("/")
    if clean == "":
        clean = "index.html"
    resolved_root = static_dir.resolve()
    file_path = (static_dir / clean).resolve()
    if not file_path.is_relative_to(resolved_root):
        return None
    if not file_path.is_file():
        return None
    content_type = STATIC_CONTENT_TYPES.get(file_path.suffix)
    if content_type is None:
        return None
    return file_path.read_bytes(), content_type

def dispatch_route(
    path: str, data_dir: Path
) -> tuple[int, dict[str, object]] | None:
    """Route a request path to the appropriate handler. Returns (status, body)."""
    if path == "/state":
        return HTTPStatus.OK, handle_state(data_dir / "cognitive_state.json")
    if path == "/tasks":
        return HTTPStatus.OK, handle_tasks(data_dir)
    if path == "/buffers":
        return HTTPStatus.OK, handle_buffers(data_dir)
    if path == "/schedule":
        return HTTPStatus.OK, handle_schedule(data_dir)
    if path == "/activity":
        return HTTPStatus.OK, handle_activity(data_dir)
    return None


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}


def make_handler_class(
    data_dir: Path, static_dir: Path, refresh_interval_ms: int = 30000
) -> type[BaseHTTPRequestHandler]:
    """Create a request handler class bound to data and static directories."""

    class DashboardHandler(BaseHTTPRequestHandler):
        def _send_cors_headers(self) -> None:
            for key, value in CORS_HEADERS.items():
                self.send_header(key, value)

        def _send_json(
            self, status: int, body: dict[str, object]
        ) -> None:
            payload = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(payload)

        def _send_static(self, content: bytes, content_type: str) -> None:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(content)

        def do_OPTIONS(self) -> None:
            self.send_response(HTTPStatus.NO_CONTENT)
            self._send_cors_headers()
            self.end_headers()

        def do_GET(self) -> None:
            if self.path == "/config":
                self._send_json(
                    HTTPStatus.OK,
                    {"refresh_interval_ms": refresh_interval_ms},
                )
                return
            result = dispatch_route(self.path, data_dir)
            if result is not None:
                status, body = result
                self._send_json(status, body)
                return
            static = resolve_static_file(static_dir, self.path)
            if static is not None:
                content, content_type = static
                self._send_static(content, content_type)
                return
            self._send_json(
                HTTPStatus.NOT_FOUND,
                {"error": f"Unknown endpoint: {self.path}"},
            )

        def log_message(self, format: str, *args: object) -> None:
            log.debug(format, *args)

    return DashboardHandler


def create_dashboard_server(config: DashboardConfig) -> HTTPServer:
    """Create an HTTPServer configured for the dashboard API."""
    handler_class = make_handler_class(
        config.data_dir, config.static_dir, config.refresh_interval_ms,
    )
    server = HTTPServer((config.host, config.port), handler_class)
    log.info(
        "Dashboard API listening on %s:%d (data: %s)",
        config.host, config.port, config.data_dir,
    )
    return server


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    cfg = load_config_from_env()
    srv = create_dashboard_server(cfg)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.server_close()
