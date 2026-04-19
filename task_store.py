"""Task data model and persistent JSON storage for the ADHD assistant.

Provides a Task model (Pydantic BaseModel) and a TaskStore class that
persists tasks to a JSON file with atomic writes. All CRUD operations
write through to disk immediately.
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

TaskStatus = Literal["pending", "in_progress", "done"]
TaskPriority = Literal["low", "medium", "high"]

ALL_STATUSES: frozenset[str] = frozenset(["pending", "in_progress", "done"])
ALL_PRIORITIES: frozenset[str] = frozenset(["low", "medium", "high"])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class Task(BaseModel):
    """A single task in the ADHD assistant's task management system."""

    id: str
    title: str
    description: str | None = None
    status: TaskStatus
    priority: TaskPriority
    created_at: datetime
    updated_at: datetime
    due_date: datetime | None = None
    tags: list[str] = Field(default_factory=list)


class TaskUpdate(BaseModel):
    """Fields that can be changed on an existing task.

    Only fields explicitly set are applied — unset fields are ignored
    via model_dump(exclude_unset=True).
    """

    title: str | None = None
    description: str | None = None
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    due_date: datetime | None = None
    tags: list[str] | None = None


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def generate_task_id() -> str:
    """Return a collision-safe hex task ID."""
    return uuid.uuid4().hex


def build_task(
    title: str,
    priority: TaskPriority,
    description: str | None,
    due_date: datetime | None,
    tags: list[str],
) -> Task:
    """Construct a new Task with generated ID and UTC timestamps."""
    now = datetime.now(timezone.utc)
    return Task(
        id=generate_task_id(),
        title=title,
        description=description,
        status="pending",
        priority=priority,
        created_at=now,
        updated_at=now,
        due_date=due_date,
        tags=list(tags),
    )


def apply_updates(task: Task, updates: TaskUpdate) -> Task:
    """Return a new Task with the specified fields changed."""
    changes = updates.model_dump(exclude_unset=True)
    if not changes:
        return task
    current = task.model_dump(mode="json")
    current.update(changes)
    current["updated_at"] = datetime.now(timezone.utc)
    return Task.model_validate(current)


def serialize_tasks(tasks: dict[str, Task]) -> str:
    """Serialize task dict to JSON string."""
    data = {"tasks": [t.model_dump(mode="json") for t in tasks.values()]}
    return json.dumps(data, indent=2)


def deserialize_tasks(raw: str) -> dict[str, Task]:
    """Parse JSON string into a task dict keyed by ID."""
    data = json.loads(raw)
    if not isinstance(data, dict) or "tasks" not in data:
        raise ValueError(
            "Task store JSON must have a top-level 'tasks' key. "
            f"Got keys: {list(data.keys()) if isinstance(data, dict) else type(data).__name__}"
        )
    result: dict[str, Task] = {}
    for entry in data["tasks"]:
        task = Task.model_validate(entry)
        result[task.id] = task
    return result


# ---------------------------------------------------------------------------
# TaskStore
# ---------------------------------------------------------------------------

class TaskStore:
    """CRUD operations over a JSON-persisted task collection.

    Loads tasks from disk on init. Every mutation writes through to disk
    atomically (write to .tmp, then rename).
    """

    def __init__(self, storage_path: Path) -> None:
        self._storage_path = storage_path
        self._tasks: dict[str, Task] = {}
        if storage_path.exists():
            raw = storage_path.read_text(encoding="utf-8")
            self._tasks = deserialize_tasks(raw)

    def _save(self) -> None:
        content = serialize_tasks(self._tasks)
        tmp_path = self._storage_path.with_suffix(".tmp")
        tmp_path.write_text(content, encoding="utf-8")
        tmp_path.replace(self._storage_path)

    def reload(self) -> None:
        """Re-read tasks from disk, discarding in-memory state."""
        if self._storage_path.exists():
            raw = self._storage_path.read_text(encoding="utf-8")
            self._tasks = deserialize_tasks(raw)
        else:
            self._tasks = {}

    def create_task(
        self,
        title: str,
        priority: TaskPriority,
        description: str | None,
        due_date: datetime | None,
        tags: list[str],
    ) -> Task:
        """Create a new task and persist it."""
        task = build_task(title, priority, description, due_date, tags)
        self._tasks[task.id] = task
        self._save()
        log.info("Created task %s: %s", task.id[:8], task.title)
        return task

    def get_task(self, task_id: str) -> Task:
        """Retrieve a task by ID. Raises KeyError if not found."""
        task = self._tasks.get(task_id)
        if task is None:
            raise KeyError(
                f"Task not found: '{task_id}'. "
                f"Store contains {len(self._tasks)} task(s)."
            )
        return task

    def list_tasks(self) -> list[Task]:
        """Return all tasks."""
        return list(self._tasks.values())

    def list_tasks_by_status(self, status: TaskStatus) -> list[Task]:
        """Return tasks filtered to the given status."""
        return [t for t in self._tasks.values() if t.status == status]

    def update_task(self, task_id: str, updates: TaskUpdate) -> Task:
        """Apply partial updates to an existing task. Returns the new task."""
        existing = self.get_task(task_id)
        updated = apply_updates(existing, updates)
        self._tasks[updated.id] = updated
        self._save()
        log.info("Updated task %s", task_id[:8])
        return updated

    def mark_complete(self, task_id: str) -> Task:
        """Mark a task as done."""
        return self.update_task(task_id, TaskUpdate(status="done"))

    def delete_task(self, task_id: str) -> Task:
        """Remove a task from the store. Returns the deleted task."""
        if task_id not in self._tasks:
            raise KeyError(
                f"Cannot delete task '{task_id}': not found. "
                f"Store contains {len(self._tasks)} task(s)."
            )
        task = self._tasks.pop(task_id)
        self._save()
        log.info("Deleted task %s: %s", task_id[:8], task.title)
        return task


# ---------------------------------------------------------------------------
# Protocol — shared contract for both JSON and Taskwarrior backends
# ---------------------------------------------------------------------------

@runtime_checkable
class TaskStoreProtocol(Protocol):
    """The 8-method contract consumers depend on.

    Both :class:`TaskStore` (JSON) and
    :class:`taskwarrior_store.TaskwarriorStore` satisfy this structurally.
    Consumers (tools, hooks, dashboard handlers) should annotate with this
    Protocol so either backend can be injected.
    """

    def create_task(
        self,
        title: str,
        priority: TaskPriority,
        description: str | None,
        due_date: datetime | None,
        tags: list[str],
    ) -> Task: ...

    def get_task(self, task_id: str) -> Task: ...

    def list_tasks(self) -> list[Task]: ...

    def list_tasks_by_status(self, status: TaskStatus) -> list[Task]: ...

    def update_task(self, task_id: str, updates: TaskUpdate) -> Task: ...

    def mark_complete(self, task_id: str) -> Task: ...

    def delete_task(self, task_id: str) -> Task: ...

    def reload(self) -> None: ...
