"""Launch custom nanobot gateway and dashboard server in one process.

Usage:
    python start.py

Starts the Telegram bot (custom gateway), the dashboard HTTP server,
and — when ``SYNCALL_ENABLED=true`` — the syncall Taskwarrior↔Google
Calendar sync daemon. Ctrl+C stops all three. The gateway runs in the
main thread via asyncio.run(); the dashboard runs in a daemon thread;
syncall runs as a child subprocess so its crashes stay isolated.
"""

import logging
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Mapping, NoReturn

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env", override=False)
except ImportError:
    pass

from cabinet_server import CabinetServer, launch_cabinet
from dashboard_api import create_dashboard_server, load_config_from_env
from gateway_runner import run_gateway
from syncall_setup import is_syncall_enabled

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
log = logging.getLogger("start")

SYNCALL_TERMINATE_TIMEOUT = 15.0


def run_dashboard(shutdown_event: threading.Event) -> None:
    """Run the dashboard HTTP server until shutdown_event is set."""
    config = load_config_from_env()
    server = create_dashboard_server(config)
    server.timeout = 1.0
    while not shutdown_event.is_set():
        server.handle_request()
    server.server_close()
    log.info("Dashboard server stopped")


def spawn_syncall_daemon(
    env: Mapping[str, str],
    popen: type[subprocess.Popen[bytes]] = subprocess.Popen,
) -> subprocess.Popen[bytes] | None:
    """Spawn the syncall daemon as a child process when the flag is on.

    Returns the ``Popen`` handle (or the stub ``popen`` returns under test)
    so callers can signal + join on shutdown. Returns ``None`` when the
    feature flag is off so the caller's shutdown path is a no-op.
    """
    if not is_syncall_enabled(env):
        return None
    repo_root = Path(__file__).resolve().parent
    log.info("SYNCALL_ENABLED=true — spawning syncall daemon")
    return popen(
        [sys.executable, "-m", "syncall_daemon"],
        cwd=str(repo_root),
    )


def stop_syncall_daemon(proc: subprocess.Popen[bytes] | None) -> None:
    """Politely terminate the syncall daemon and wait briefly."""
    if proc is None:
        return
    if proc.poll() is not None:
        log.info("Syncall daemon already exited with code %d", proc.returncode)
        return
    log.info("Stopping syncall daemon (PID %d)...", proc.pid)
    proc.terminate()
    try:
        proc.wait(timeout=SYNCALL_TERMINATE_TIMEOUT)
    except subprocess.TimeoutExpired:
        log.warning("Syncall daemon did not exit within %.0fs; killing",
                    SYNCALL_TERMINATE_TIMEOUT)
        proc.kill()
        proc.wait(timeout=5)


def spawn_cabinet(env: Mapping[str, str]) -> CabinetServer | None:
    """Flag-gated Cabinet static-server autostart wrapper.

    Returns ``None`` when ``CABINET_AUTOSTART_ENABLED`` is off so the
    shutdown path stays a no-op.
    """
    repo_root = Path(__file__).resolve().parent
    return launch_cabinet(repo_root, env)


def stop_cabinet(server: CabinetServer | None) -> None:
    """Stop the in-process Cabinet server; it goes down before syncall so
    the Fire Tablet disconnects cleanly first."""
    if server is None:
        return
    server.stop()


def main() -> NoReturn:
    shutdown_event = threading.Event()

    dashboard_thread = threading.Thread(
        target=run_dashboard,
        args=(shutdown_event,),
        daemon=True,
    )
    dashboard_thread.start()

    syncall_proc = spawn_syncall_daemon(os.environ)
    cabinet_server = spawn_cabinet(os.environ)

    log.info("Starting custom gateway...")
    try:
        exit_code = run_gateway(None, None)
    except KeyboardInterrupt:
        log.info("Interrupted, shutting down...")
        exit_code = 0
    except Exception:
        log.exception("Gateway raised an unexpected exception")
        exit_code = 1

    log.info("Gateway exited with code %d", exit_code)
    shutdown_event.set()
    stop_cabinet(cabinet_server)
    stop_syncall_daemon(syncall_proc)
    dashboard_thread.join(timeout=5)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
