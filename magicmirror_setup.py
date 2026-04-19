"""MagicMirror² vendor/build/config-render helpers.

Isolated from ``setup_workspace.py`` so the 300-line cap holds and the
npm/subprocess surface has one obvious patch point for tests. The main
entry is ``build_magicmirror(repo_root, enabled)``; the render helper is
``render_magicmirror_config(repo_root, env)``. Both are idempotent and
flag-gated via ``is_magicmirror_enabled(env)``.
"""

import logging
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path

log = logging.getLogger(__name__)

MAGICMIRROR_WEBHOOK_TEMPLATE_NAMES: tuple[str, str, str] = (
    "state_change",
    "buffer_alert",
    "missed_checkin",
)

MODULE_NAMES: tuple[str, str, str] = (
    "MMM-WebHookAlerts",
    "MMM-Markdown",
    "MMM-pages",
)

DEFAULT_IP_WHITELIST_JSON = (
    '["127.0.0.1", "::1", "::ffff:127.0.0.1", '
    '"192.168.0.0/16", "10.0.0.0/8", "172.16.0.0/12"]'
)

MAGICMIRROR_CONFIG_VARS: dict[str, str] = {
    "MAGICMIRROR_HOST": "0.0.0.0",
    "MAGICMIRROR_PORT": "8080",
    "MAGICMIRROR_IP_WHITELIST_JSON": DEFAULT_IP_WHITELIST_JSON,
}


def is_magicmirror_enabled(env: Mapping[str, str]) -> bool:
    """Return True when the user has opted into the MagicMirror display."""
    return env.get("MAGICMIRROR_ENABLED", "false").strip().lower() == "true"


def detect_node_npm() -> str:
    """Return the resolved ``npm`` path. Raise if Node/npm is absent."""
    npm = shutil.which("npm")
    if npm is None:
        raise RuntimeError(
            "npm not found on PATH — MagicMirror requires Node.js ≥22.21.1. "
            "Install from https://nodejs.org and re-run setup_workspace.py, "
            "or set MAGICMIRROR_ENABLED=false to skip this step."
        )
    return npm


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


def _is_install_fresh(package_dir: Path) -> bool:
    """Return True when ``node_modules/`` is newer than ``package-lock.json``."""
    node_modules = package_dir / "node_modules"
    lock = package_dir / "package-lock.json"
    if not node_modules.is_dir():
        return False
    if not lock.exists():
        return True
    return node_modules.stat().st_mtime >= lock.stat().st_mtime


def _install_package(
    npm: str, package_dir: Path, extra_args: list[str]
) -> None:
    """Run ``npm install [extra_args]`` if the install is not already fresh."""
    if not package_dir.is_dir():
        raise FileNotFoundError(
            f"Vendored package directory missing at {package_dir}. "
            f"Expected the MagicMirror vendor drop to include it."
        )
    if _is_install_fresh(package_dir):
        log.info("npm install for %s is fresh; skipping", package_dir.name)
        return
    _run_npm(npm, ["install", *extra_args], package_dir)


def build_magicmirror(repo_root: Path, enabled: bool) -> None:
    """Install MagicMirror² core and the three vendored modules.

    Short-circuits when ``enabled`` is False. Otherwise requires ``npm``
    on PATH, runs ``npm install --ignore-scripts`` on the core (the
    ``--ignore-scripts`` flag defuses the upstream ``postinstall`` that
    runs ``git clean -df`` in a non-git tree), then ``npm install`` on
    each module under ``modules/``. Each package is skipped when its
    ``node_modules/`` is already newer than its ``package-lock.json``.
    """
    if not enabled:
        log.info("MAGICMIRROR_ENABLED=false — skipping MagicMirror build")
        return
    mm_root = repo_root / "magicmirror"
    if not mm_root.is_dir():
        raise FileNotFoundError(
            f"Vendored MagicMirror directory missing at {mm_root}. "
            f"Expected magicmirror/ to exist in the repo."
        )
    npm = detect_node_npm()
    _install_package(npm, mm_root, ["--ignore-scripts"])
    for module_name in MODULE_NAMES:
        _install_package(npm, mm_root / "modules" / module_name, [])


def render_magicmirror_config(
    repo_root: Path, env: Mapping[str, str]
) -> None:
    """Substitute placeholders in ``config.js.template`` and write ``config.js``.

    Reads ``magicmirror/config/config.js.template``, replaces the three
    ``${...}`` placeholders with values from ``env`` (falling back to
    :data:`MAGICMIRROR_CONFIG_VARS` defaults), and writes the resolved
    output to ``magicmirror/config/config.js``. The template stays under
    version control; the rendered file is gitignored.
    """
    config_dir = repo_root / "magicmirror" / "config"
    template_path = config_dir / "config.js.template"
    if not template_path.is_file():
        raise FileNotFoundError(
            f"MagicMirror config template missing at {template_path}. "
            f"Expected magicmirror/config/config.js.template in the repo."
        )
    raw = template_path.read_text(encoding="utf-8")
    for var_name, default in MAGICMIRROR_CONFIG_VARS.items():
        placeholder = f"${{{var_name}}}"
        if placeholder in raw:
            raw = raw.replace(placeholder, env.get(var_name, default))
    output_path = config_dir / "config.js"
    output_path.write_text(raw, encoding="utf-8")
    log.info("Rendered MagicMirror config -> %s", output_path)
