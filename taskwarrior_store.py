"""Taskwarrior-backed task store — drop-in for TaskStore's public API.

Wraps the vendored tasklib (``vendor/tasklib/``) and the Taskwarrior CLI so
that callers of :class:`task_store.TaskStore` can swap to this backend
without signature changes. Each instance owns a ``data_dir`` under which
Taskwarrior writes ``pending.data``, ``completed.data``, etc.

The ``task`` binary must be installed separately on PATH; a missing binary
raises a structured RuntimeError at construct time so failures surface
before the first CRUD call rather than as a cryptic FileNotFoundError
from tasklib's ``task --version`` subprocess.

Key mappings:

- **id**: TaskWarrior's 36-char UUID (assigned at save time). The
  hex UUID from :func:`task_store.build_task` is discarded because
  tasklib's ``uuid`` field is read-only.
- **status**: TW has no ``in_progress``. We use a synthetic ``+started``
  tag; TW status is ``pending`` for both ``pending`` and ``in_progress``,
  ``completed`` for ``done``. Deleted rows are filtered out of all lists.
- **priority**: low↔L, medium↔M, high↔H (bi-directional, lossless).
- **description**: stored as the task's first annotation since tasklib
  without UDAs has no other lossless text field for it.
"""

from __future__ import annotations

import logging
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tasklib import Task as TWTask  # type: ignore[import-untyped]
from tasklib import TaskWarrior

from task_store import (
    Task,
    TaskPriority,
    TaskStatus,
    TaskUpdate,
    apply_updates,
    build_task,
)

log = logging.getLogger(__name__)

_OURS_TO_TW_PRIORITY: dict[TaskPriority, str] = {
    "low": "L",
    "medium": "M",
    "high": "H",
}
_TW_TO_OURS_PRIORITY: dict[str, TaskPriority] = {
    v: k for k, v in _OURS_TO_TW_PRIORITY.items()
}
_STARTED_TAG = "started"

_INSTALL_HINTS: dict[str, str] = {
    "win32": "choco install task",
    "darwin": "brew install task",
    "linux": "apt install taskwarrior (Debian/Ubuntu) or dnf install task",
}


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def _platform_install_hint() -> str:
    return _INSTALL_HINTS.get(sys.platform, _INSTALL_HINTS["linux"])


def _require_task_binary() -> None:
    if shutil.which("task") is not None:
        return
    raise RuntimeError(
        "Taskwarrior CLI ('task') not found on PATH. Install it with: "
        f"{_platform_install_hint()}. "
        "TaskwarriorStore cannot be constructed without it."
    )


def _ours_status_from_tw(tw_status: str, tw_tags: set[str]) -> TaskStatus:
    if tw_status == "completed":
        return "done"
    if _STARTED_TAG in tw_tags:
        return "in_progress"
    return "pending"


def _user_tags_from_tw(tw_tags: set[str]) -> list[str]:
    return sorted(t for t in tw_tags if t != _STARTED_TAG)


def _normalize_to_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        raise ValueError(
            f"Taskwarrior returned naive datetime {value!r}; expected "
            "tz-aware (tasklib's deserializer guarantees this on 2.5.1)."
        )
    return value.astimezone(timezone.utc)


def _extract_description(tw_task: Any) -> str | None:
    annotations = tw_task["annotations"] or []
    if not annotations:
        return None
    return str(annotations[0]["description"])


def tw_task_to_our_task(tw_task: Any) -> Task:
    """Convert a saved tasklib Task into our Pydantic Task."""
    tw_tags: set[str] = set(tw_task["tags"] or [])
    tw_priority_raw = tw_task["priority"] or ""
    priority = _TW_TO_OURS_PRIORITY.get(tw_priority_raw)
    if priority is None:
        raise ValueError(
            f"Unknown Taskwarrior priority {tw_priority_raw!r} on task "
            f"{tw_task['uuid']!r}. Expected one of "
            f"{sorted(_TW_TO_OURS_PRIORITY.keys())}."
        )
    entry = _normalize_to_utc(tw_task["entry"])
    modified = _normalize_to_utc(tw_task["modified"]) or entry
    if entry is None or modified is None:
        raise ValueError(
            f"Taskwarrior task {tw_task['uuid']!r} missing entry/modified "
            "timestamps; the CLI should always populate both on saved tasks."
        )
    return Task(
        id=str(tw_task["uuid"]),
        title=str(tw_task["description"]),
        description=_extract_description(tw_task),
        status=_ours_status_from_tw(str(tw_task["status"]), tw_tags),
        priority=priority,
        created_at=entry,
        updated_at=modified,
        due_date=_normalize_to_utc(tw_task["due"]),
        tags=_user_tags_from_tw(tw_tags),
    )


def apply_our_task_to_tw_task(our: Task, tw_task: Any) -> None:
    """Write our Task's mutable scalar fields onto a tasklib Task.

    Does not save, touch annotations (description), or transition status
    to ``done`` — those are side-effecting and live in TaskwarriorStore.
    """
    tw_task["description"] = our.title
    tw_task["priority"] = _OURS_TO_TW_PRIORITY[our.priority]
    tw_task["due"] = our.due_date
    tags_set = set(our.tags)
    if our.status == "in_progress":
        tags_set.add(_STARTED_TAG)
    tw_task["tags"] = tags_set


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

class TaskwarriorStore:
    """CRUD over the Taskwarrior CLI, matching :class:`TaskStore`'s API.

    Same 7 mutating/query methods + ``reload()`` as ``TaskStore`` — same
    signatures, same return types, same KeyError prefixes on misses.
    """

    def __init__(self, data_dir: Path) -> None:
        _require_task_binary()
        data_dir.mkdir(parents=True, exist_ok=True)
        self._data_dir = data_dir
        self._tw = TaskWarrior(
            data_location=str(data_dir),
            taskrc_location="/",
            create=True,
        )

    def _get_tw_task(self, task_id: str, error_prefix: str) -> Any:
        try:
            return self._tw.tasks.get(uuid=task_id)
        except TWTask.DoesNotExist as exc:
            raise KeyError(
                f"{error_prefix}: '{task_id}'. "
                "Not present in Taskwarrior database."
            ) from exc

    def create_task(
        self,
        title: str,
        priority: TaskPriority,
        description: str | None,
        due_date: datetime | None,
        tags: list[str],
    ) -> Task:
        """Create a new task and persist via the TW CLI."""
        our = build_task(title, priority, description, due_date, tags)
        tw_task = TWTask(self._tw)
        apply_our_task_to_tw_task(our, tw_task)
        tw_task.save()
        if description is not None:
            tw_task.add_annotation(description)
        result = tw_task_to_our_task(tw_task)
        log.info("Created task %s: %s", result.id[:8], result.title)
        return result

    def get_task(self, task_id: str) -> Task:
        """Retrieve a task by its Taskwarrior UUID."""
        tw_task = self._get_tw_task(task_id, "Task not found")
        return tw_task_to_our_task(tw_task)

    def list_tasks(self) -> list[Task]:
        """Return all non-deleted tasks — pending + completed."""
        pending = [tw_task_to_our_task(t) for t in self._tw.tasks.pending()]
        completed = [tw_task_to_our_task(t) for t in self._tw.tasks.completed()]
        return sorted(pending + completed, key=lambda t: t.created_at)

    def list_tasks_by_status(self, status: TaskStatus) -> list[Task]:
        """Return tasks filtered to the given ADHD status."""
        if status == "done":
            tasks = [tw_task_to_our_task(t) for t in self._tw.tasks.completed()]
        else:
            pending_all = [
                tw_task_to_our_task(t) for t in self._tw.tasks.pending()
            ]
            tasks = [t for t in pending_all if t.status == status]
        return sorted(tasks, key=lambda t: t.created_at)

    def update_task(self, task_id: str, updates: TaskUpdate) -> Task:
        """Apply partial updates and persist. Raises KeyError if missing."""
        tw_task = self._get_tw_task(task_id, "Task not found")
        existing = tw_task_to_our_task(tw_task)
        updated = apply_updates(existing, updates)

        apply_our_task_to_tw_task(updated, tw_task)
        tw_task.save()

        if existing.description != updated.description:
            for annotation in list(tw_task["annotations"] or []):
                tw_task.remove_annotation(annotation)
            if updated.description is not None:
                tw_task.add_annotation(updated.description)

        if existing.status != "done" and updated.status == "done":
            tw_task.done()

        result = tw_task_to_our_task(tw_task)
        log.info("Updated task %s", task_id[:8])
        return result

    def mark_complete(self, task_id: str) -> Task:
        """Mark a task as done (delegates to update_task for API symmetry)."""
        return self.update_task(task_id, TaskUpdate(status="done"))

    def delete_task(self, task_id: str) -> Task:
        """Remove a task via TW delete. Raises KeyError if missing."""
        tw_task = self._get_tw_task(task_id, "Cannot delete task")
        our_task = tw_task_to_our_task(tw_task)
        tw_task.delete()
        log.info("Deleted task %s: %s", our_task.id[:8], our_task.title)
        return our_task

    def reload(self) -> None:
        """Clear tasklib's lru_cache. Tasklib queries TW via subprocess on
        every filter call, so no further invalidation is needed."""
        self._tw.get_task.cache_clear()
