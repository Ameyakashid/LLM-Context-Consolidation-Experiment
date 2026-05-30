"""Static-file server for "The Cabinet" Fire-tablet display.

Replaces the MagicMirror² Node stack: serves the ``cabinet/`` folder over
the LAN via Starlette + uvicorn, enforcing the same loopback/RFC1918 IP
whitelist MagicMirror used and sending ``no-store`` headers. Runs as an
in-process daemon thread (:class:`CabinetServer`), spawned by ``start.py``
via :func:`launch_cabinet` when ``CABINET_AUTOSTART_ENABLED`` is true.

Config reads the ``CABINET_*`` env namespace, falling back to legacy
``MAGICMIRROR_*`` values for one release. The pure helpers carry no I/O
and are unit-tested directly.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import PlainTextResponse
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles

log = logging.getLogger(__name__)

IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network

CABINET_STOP_TIMEOUT_S = 10.0

# Mirror MagicMirror's default whitelist: loopback + RFC1918 LAN, nothing wider.
DEFAULT_IP_WHITELIST_JSON = (
    '["127.0.0.1", "::1", "::ffff:127.0.0.1", '
    '"192.168.0.0/16", "10.0.0.0/8", "172.16.0.0/12"]'
)


# ---------------------------------------------------------------------------
# Env helpers (CABINET_* with legacy MAGICMIRROR_* fallback)
# ---------------------------------------------------------------------------

def _cabinet_env(
    env: Mapping[str, str], key: str, *fallbacks: str, default: str
) -> str:
    """Return the first non-empty value among ``key`` then ``fallbacks``.

    Empty/whitespace is treated as unset (blank CABINET_* falls back to legacy).
    """
    for name in (key, *fallbacks):
        val = env.get(name)
        if val is not None and val.strip() != "":
            return val
    return default


def is_cabinet_enabled(env: Mapping[str, str]) -> bool:
    """Master switch: ``CABINET_ENABLED`` (fallback ``MAGICMIRROR_ENABLED``)."""
    raw = _cabinet_env(env, "CABINET_ENABLED", "MAGICMIRROR_ENABLED", default="false")
    return raw.strip().lower() == "true"


def is_cabinet_autostart_enabled(env: Mapping[str, str]) -> bool:
    """Runtime autostart: ``CABINET_AUTOSTART_ENABLED`` (fallback legacy)."""
    raw = _cabinet_env(
        env,
        "CABINET_AUTOSTART_ENABLED",
        "MAGICMIRROR_AUTOSTART_ENABLED",
        default="false",
    )
    return raw.strip().lower() == "true"


# ---------------------------------------------------------------------------
# Path resolvers
# ---------------------------------------------------------------------------

def resolve_cabinet_dir(repo_root: Path) -> Path:
    """Return the served static root (the tracked ``cabinet/`` folder)."""
    return repo_root / "cabinet"


def resolve_cabinet_feed_dir(repo_root: Path) -> Path:
    """Return the dir the backend writes feed files into (``cabinet/feeds``)."""
    return repo_root / "cabinet" / "feeds"


def resolve_wallpaper_dir(repo_root: Path, env: Mapping[str, str]) -> Path:
    """Return the local image folder served at ``/wallpapers``.

    Defaults to ``cabinet/wallpapers``; override via ``CABINET_WALLPAPER_DIR``.
    """
    override = _cabinet_env(env, "CABINET_WALLPAPER_DIR", default="").strip()
    if override:
        return Path(override).expanduser()
    return repo_root / "cabinet" / "wallpapers"


# ---------------------------------------------------------------------------
# IP whitelist (pure)
# ---------------------------------------------------------------------------

def parse_ip_whitelist(raw_json: str) -> list[IPNetwork]:
    """Parse a JSON array of IPs/CIDRs into networks (bare IP → /32 or /128).

    Malformed JSON / non-list → ``[]`` (allow-all); invalid entries skipped.
    """
    try:
        items = json.loads(raw_json)
    except (json.JSONDecodeError, TypeError):
        log.warning("Invalid IP whitelist JSON; treating as empty (allow all)")
        return []
    if not isinstance(items, list):
        return []
    networks: list[IPNetwork] = []
    for item in items:
        if not isinstance(item, str):
            continue
        try:
            networks.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            log.warning("Skipping invalid IP/CIDR in whitelist: %r", item)
    return networks


def client_ip_allowed(client_host: str, networks: Sequence[IPNetwork]) -> bool:
    """Return True when ``client_host`` falls in any whitelisted network.

    Empty whitelist allows everyone (loopback dev). IPv4-mapped IPv6 clients
    (``::ffff:a.b.c.d``) are unwrapped so they match IPv4 CIDRs.
    """
    if not networks:
        return True
    try:
        ip: ipaddress.IPv4Address | ipaddress.IPv6Address = ipaddress.ip_address(
            client_host
        )
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return any(ip.version == net.version and ip in net for net in networks)


# --- Middleware + app ---

class IPWhitelistMiddleware(BaseHTTPMiddleware):
    """Reject requests whose client IP is not in the configured whitelist."""

    def __init__(self, app, networks: Sequence[IPNetwork]) -> None:
        super().__init__(app)
        self._networks = list(networks)

    async def dispatch(self, request, call_next):
        client = request.client
        host = client.host if client is not None else ""
        if not client_ip_allowed(host, self._networks):
            log.warning("Rejected Cabinet request from non-whitelisted %s", host)
            return PlainTextResponse("Forbidden", status_code=403)
        return await call_next(request)


class NoStoreMiddleware(BaseHTTPMiddleware):
    """Stamp every response no-store so the tablet always re-polls feeds."""

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        return response


def build_cabinet_app(
    static_dir: Path, wallpaper_dir: Path, networks: Sequence[IPNetwork]
) -> Starlette:
    """Build the Starlette app serving the Cabinet + a /wallpapers mount.

    ``/wallpapers`` mounts before ``/`` (specific first). ``check_dir=False``
    lets the app build before dirs are populated. IP-whitelist is outermost.
    """
    routes = [
        Mount(
            "/wallpapers",
            app=StaticFiles(directory=str(wallpaper_dir), check_dir=False),
            name="wallpapers",
        ),
        Mount(
            "/",
            app=StaticFiles(directory=str(static_dir), html=True, check_dir=False),
            name="static",
        ),
    ]
    middleware = [
        Middleware(IPWhitelistMiddleware, networks=networks),
        Middleware(NoStoreMiddleware),
    ]
    return Starlette(routes=routes, middleware=middleware)


# ---------------------------------------------------------------------------
# Server lifecycle
# ---------------------------------------------------------------------------

class CabinetServer:
    """Single-use in-process uvicorn server on a daemon thread.

    Mirrors ``MagicMirrorProcess``: construct → ``start()`` (no-op if running)
    → ``stop()`` (set ``should_exit`` + join). Spent after ``stop()``.
    """

    def __init__(
        self,
        app: Starlette,
        host: str,
        port: int,
        config_factory=uvicorn.Config,
        server_factory=uvicorn.Server,
    ) -> None:
        self._app = app
        self._host = host
        self._port = port
        self._config_factory = config_factory
        self._server_factory = server_factory
        self._server = None
        self._thread: threading.Thread | None = None
        self._stopped = False

    def start(self) -> None:
        if self._stopped:
            raise RuntimeError(
                "CabinetServer.start called after stop; wrappers are single-use."
            )
        if self._thread is not None:
            return
        config = self._config_factory(
            self._app, host=self._host, port=self._port, log_level="warning"
        )
        self._server = self._server_factory(config)
        self._thread = threading.Thread(
            target=self._server.run, name="cabinet-server", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = CABINET_STOP_TIMEOUT_S) -> None:
        self._stopped = True
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()


def launch_cabinet(
    repo_root: Path,
    env: Mapping[str, str],
    server_factory: type[CabinetServer] = CabinetServer,
) -> CabinetServer | None:
    """Flag-gated factory for a running :class:`CabinetServer`.

    ``None`` when ``CABINET_AUTOSTART_ENABLED`` is off; raises ``RuntimeError``
    when on but ``cabinet/index.html`` is missing (frontend not deployed).
    """
    if not is_cabinet_autostart_enabled(env):
        return None
    static_dir = resolve_cabinet_dir(repo_root)
    index = static_dir / "index.html"
    if not index.is_file():
        raise RuntimeError(
            f"Cabinet frontend missing at {index} — the cabinet/ folder was "
            "not deployed. Run setup_workspace() first."
        )
    feed_dir = resolve_cabinet_feed_dir(repo_root)
    wallpaper_dir = resolve_wallpaper_dir(repo_root, env)
    feed_dir.mkdir(parents=True, exist_ok=True)
    wallpaper_dir.mkdir(parents=True, exist_ok=True)
    networks = parse_ip_whitelist(
        _cabinet_env(
            env,
            "CABINET_IP_WHITELIST_JSON",
            "MAGICMIRROR_IP_WHITELIST_JSON",
            default=DEFAULT_IP_WHITELIST_JSON,
        )
    )
    host = _cabinet_env(env, "CABINET_HOST", "MAGICMIRROR_HOST", default="0.0.0.0")
    port = int(_cabinet_env(env, "CABINET_PORT", "MAGICMIRROR_PORT", default="8080"))
    app = build_cabinet_app(static_dir, wallpaper_dir, networks)
    server = server_factory(app=app, host=host, port=port)
    server.start()
    log.info(
        "CABINET_AUTOSTART_ENABLED=true — Cabinet static server on %s:%d",
        host, port,
    )
    return server
