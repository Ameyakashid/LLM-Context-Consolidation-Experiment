"""Google Calendar MCP setup helpers.

Isolated from ``setup_workspace.py`` so the 300-line cap holds and the
npm/subprocess surface has one obvious patch point for tests. The main
entry is ``build_google_calendar_mcp(mcp_dir, enabled, data_dir)``; the
two pure helpers are consumed from ``setup_workspace.setup_workspace()``.
"""

import logging
import shutil
import subprocess
from pathlib import Path
from typing import cast

log = logging.getLogger(__name__)


def is_gcal_enabled(env: dict[str, str]) -> bool:
    """Return True when the user has opted into Google Calendar MCP."""
    return env.get("GOOGLE_CALENDAR_ENABLED", "false").strip().lower() == "true"


def strip_gcal_mcp_server(config: dict[str, object]) -> dict[str, object]:
    """Return a copy of ``config`` with the google-calendar MCP entry removed.

    The template always carries the entry so the JSON stays self-describing;
    when the feature flag is off, the resolved config written to disk must
    not reference the MCP server or nanobot will try to spawn a missing
    build.
    """
    tools = cast(dict[str, object], config["tools"])
    mcp_servers = cast(dict[str, object], tools["mcpServers"])
    filtered = {k: v for k, v in mcp_servers.items() if k != "google-calendar"}
    new_tools: dict[str, object] = {**tools}
    if filtered:
        new_tools["mcpServers"] = filtered
    else:
        del new_tools["mcpServers"]
    return {**config, "tools": new_tools}


def _ensure_private_dir(path: Path) -> None:
    """Create ``path`` and best-effort chmod 0700. Windows silently ignores."""
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except (NotImplementedError, OSError):
        log.info("Could not chmod %s to 0o700 on this platform", path)


def _run_npm(npm: str, npm_args: list[str], cwd: Path) -> None:
    """Run ``npm <args>`` in ``cwd`` and route output through logging."""
    log.info("Running npm %s in %s", " ".join(npm_args), cwd)
    try:
        result = subprocess.run(
            [npm, *npm_args],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except subprocess.CalledProcessError as err:
        raise RuntimeError(
            f"npm {' '.join(npm_args)} failed in {cwd} "
            f"(exit {err.returncode}). stderr: {err.stderr or '(empty)'}"
        ) from err
    stdout = (result.stdout or "").strip()
    if stdout:
        log.info("%s", stdout)


def build_google_calendar_mcp(
    mcp_dir: Path, enabled: bool, data_dir: Path
) -> None:
    """Build the vendored Google Calendar MCP when the feature flag is on.

    Short-circuits when ``enabled`` is False. Otherwise requires ``npm``
    on PATH, runs ``npm install`` + ``npm run build`` inside ``mcp_dir``,
    and creates ``data_dir`` with 0700 permissions for token storage.
    Re-runs are a no-op when ``build/index.js`` is newer than
    ``package.json``.
    """
    if not enabled:
        log.info("GOOGLE_CALENDAR_ENABLED=false — skipping MCP build")
        return
    if not mcp_dir.is_dir():
        raise FileNotFoundError(
            f"Vendored MCP directory missing at {mcp_dir}. "
            f"Expected mcp/google-calendar/ to exist in the repo."
        )
    npm = shutil.which("npm")
    if npm is None:
        raise RuntimeError(
            "npm not found on PATH — Google Calendar MCP requires Node.js. "
            "Install from https://nodejs.org and re-run setup_workspace.py, "
            "or set GOOGLE_CALENDAR_ENABLED=false to skip this step."
        )
    package_json = mcp_dir / "package.json"
    build_entry = mcp_dir / "build" / "index.js"
    if (
        build_entry.exists()
        and build_entry.stat().st_mtime >= package_json.stat().st_mtime
    ):
        log.info("Google Calendar MCP build is fresh; skipping npm")
    else:
        _run_npm(npm, ["install"], mcp_dir)
        _run_npm(npm, ["run", "build"], mcp_dir)
    _ensure_private_dir(data_dir)
