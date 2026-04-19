"""Taskwarrior feature-flag setup helpers.

Isolated from ``setup_workspace.py`` so the 300-line cap holds. The main
entry is :func:`build_taskwarrior`; the two env-parsing helpers
(:func:`is_taskwarrior_enabled`, :func:`resolve_taskwarrior_data_dir`) are
consumed from ``setup_workspace.setup_workspace()``.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

log = logging.getLogger(__name__)

TASKWARRIOR_INSTALL_HINTS: dict[str, str] = {
    "windows": "choco install task",
    "darwin": "brew install task",
    "linux": "apt install taskwarrior (Debian/Ubuntu) or dnf install task",
}


def is_taskwarrior_enabled(env: dict[str, str]) -> bool:
    """True when ``TASKWARRIOR_ENABLED=true`` (case-insensitive)."""
    return env.get("TASKWARRIOR_ENABLED", "").strip().lower() == "true"


def resolve_taskwarrior_data_dir(
    env: dict[str, str], default_data_dir: Path
) -> Path:
    """Resolve the Taskwarrior data directory from env or default."""
    override = env.get("TASKWARRIOR_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    return default_data_dir


def build_taskwarrior(data_dir: Path, enabled: bool, platform: str) -> None:
    """Create the Taskwarrior data dir when enabled; log install hint if
    the ``task`` binary is missing."""
    if not enabled:
        log.info("Taskwarrior disabled; skipping data dir creation.")
        return
    data_dir.mkdir(parents=True, exist_ok=True)
    log.info("Taskwarrior data dir ready at %s", data_dir)
    if shutil.which("task") is None:
        hint = TASKWARRIOR_INSTALL_HINTS.get(
            platform, TASKWARRIOR_INSTALL_HINTS["linux"]
        )
        log.warning(
            "Taskwarrior enabled but 'task' binary not on PATH. "
            "Install it with: %s",
            hint,
        )


def taskwarrior_data_dir_is_empty(data_dir: Path) -> bool:
    """True when the Taskwarrior data dir has no pending/completed tasks.

    The CLI writes ``pending.data`` and ``completed.data`` alongside
    ``undo.data`` / ``backlog.data``; a fresh dir with only housekeeping
    files reads as empty. Missing dir is also empty.
    """
    pending = data_dir / "pending.data"
    completed = data_dir / "completed.data"
    if not pending.exists() and not completed.exists():
        return True
    for path in (pending, completed):
        if path.exists() and path.stat().st_size > 0:
            return False
    return True


def warn_if_migration_needed(
    enabled: bool, json_path: Path, tw_data_dir: Path,
) -> bool:
    """Emit a ``log.warning`` when migration is required.

    Migration is needed when Taskwarrior is enabled, the legacy JSON
    ``tasks.json`` exists, and the Taskwarrior data dir is empty. Returns
    True when a warning was emitted (useful for tests).
    """
    if not enabled:
        return False
    if not json_path.exists():
        return False
    if not taskwarrior_data_dir_is_empty(tw_data_dir):
        return False
    log.warning(
        "workspace/data/tasks.json exists but Taskwarrior data dir is "
        "empty. Run python scripts/migrate_json_to_taskwarrior.py to "
        "import existing tasks (source JSON is not modified).",
    )
    return True
