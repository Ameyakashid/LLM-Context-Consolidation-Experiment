"""Backend-selection factory for the task store.

Returns a :class:`task_store.TaskStoreProtocol` — either the JSON
:class:`task_store.TaskStore` (default) or the Taskwarrior-backed
:class:`taskwarrior_store.TaskwarriorStore` when
``TASKWARRIOR_ENABLED=true`` is set in the environment.

Migration workflow:

1. Flip ``TASKWARRIOR_ENABLED=true`` in ``.env`` and install the ``task``
   CLI (``choco install task`` / ``brew install task`` /
   ``apt install taskwarrior``).
2. Run ``python scripts/migrate_json_to_taskwarrior.py`` once to import
   existing tasks from ``workspace/data/tasks.json`` into the Taskwarrior
   backend at ``workspace/data/taskwarrior/``.
3. Restart the bot. Consumers see the Taskwarrior backend transparently.
4. Rollback: set ``TASKWARRIOR_ENABLED=false`` and restart. The source
   JSON is never modified by the migration, so it remains canonical.

When the flag is on but the ``task`` binary is missing,
``TaskwarriorStore.__init__`` raises ``RuntimeError`` — this factory does
not silently fall back to JSON, because hiding a deployment problem
would cause two backends to diverge unnoticed.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from task_store import TaskStore, TaskStoreProtocol
from taskwarrior_setup import (
    is_taskwarrior_enabled,
    resolve_taskwarrior_data_dir,
)

DEFAULT_JSON_TASKS_FILENAME = "tasks.json"
DEFAULT_TASKWARRIOR_DIR_NAME = "taskwarrior"
DEFAULT_WORKSPACE_DATA_SUBPATH = ("workspace", "data")


def default_json_tasks_path(repo_root: Path) -> Path:
    """Return the canonical JSON tasks.json location for this repo."""
    return repo_root.joinpath(
        *DEFAULT_WORKSPACE_DATA_SUBPATH, DEFAULT_JSON_TASKS_FILENAME,
    )


def default_taskwarrior_data_dir(repo_root: Path) -> Path:
    """Return the canonical Taskwarrior data dir for this repo."""
    return repo_root.joinpath(
        *DEFAULT_WORKSPACE_DATA_SUBPATH, DEFAULT_TASKWARRIOR_DIR_NAME,
    )


def build_task_store(
    env: Mapping[str, str], repo_root: Path,
) -> TaskStoreProtocol:
    """Return the configured task store backend.

    When ``env["TASKWARRIOR_ENABLED"] == "true"`` (case-insensitive),
    constructs a :class:`TaskwarriorStore` at
    ``env["TASKWARRIOR_DATA_DIR"]`` (absolute) or
    ``repo_root/workspace/data/taskwarrior/``. Any missing ``task`` binary
    propagates as ``RuntimeError`` from the TaskwarriorStore constructor.

    Otherwise returns a :class:`TaskStore` pointed at
    ``repo_root/workspace/data/tasks.json``.
    """
    env_dict = dict(env)
    if is_taskwarrior_enabled(env_dict):
        from taskwarrior_store import TaskwarriorStore
        data_dir = resolve_taskwarrior_data_dir(
            env_dict, default_taskwarrior_data_dir(repo_root),
        )
        return TaskwarriorStore(data_dir=data_dir)
    json_path = default_json_tasks_path(repo_root)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    return TaskStore(storage_path=json_path)
