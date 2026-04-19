"""Nanobot-ai tool wrappers for TaskStore CRUD operations.

Exposes five LLM-callable tools: create_task, list_tasks, get_task,
update_task, complete_task. Each tool delegates to a shared TaskStore
instance and returns LLM-readable string results.

Registration: call register_task_tools(registry, store) at startup.
There is no config.json.template mechanism for custom Python tools
in nanobot-ai v0.1.5 — registration is programmatic only.
"""

import logging
from datetime import datetime
from typing import Literal

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.schema import (
    ArraySchema,
    ObjectSchema,
    StringSchema,
    tool_parameters_schema,
)

from task_store import TaskStoreProtocol, TaskUpdate
from task_time_helpers import (
    format_task,
    format_task_list,
    get_user_timezone,
    parse_iso_date,
    resolve_due_date,
)

log = logging.getLogger(__name__)

TaskStatus = Literal["pending", "in_progress", "done"]
TaskPriority = Literal["low", "medium", "high"]


@tool_parameters(
    ObjectSchema(
        properties={
            "title": StringSchema("The task title — a short description of what needs to be done"),
            "priority": StringSchema(
                "Task priority level",
                enum=["low", "medium", "high"],
            ),
            "description": StringSchema(
                "Optional longer description with details about the task",
                nullable=True,
            ),
            "due_date": StringSchema(
                "Optional due date. Accepts ISO 8601 (e.g. '2025-12-31' or "
                "'2025-12-31T14:00:00Z') OR a natural-language phrase "
                "(e.g. 'tomorrow at 6pm', 'in 2 hours', 'next Friday'). "
                "Pass the user's phrase through as-is — the tool handles parsing.",
                nullable=True,
            ),
            "tags": ArraySchema(
                StringSchema("A tag label"),
                description="Optional list of tags for categorization",
            ),
        },
        required=["title", "priority"],
    ).to_json_schema()
)
class CreateTaskTool(Tool):
    def __init__(self, store: TaskStoreProtocol) -> None:
        self._store = store

    @property
    def name(self) -> str:
        return "create_task"

    @property
    def description(self) -> str:
        return (
            "Create a new task with a title, priority (low/medium/high), "
            "and optional description, due date, and tags."
        )

    async def execute(
        self,
        title: str,
        priority: str,
        description: str | None = None,
        due_date: str | None = None,
        tags: list[str] | None = None,
    ) -> str:
        parsed_due: datetime | None = None
        if due_date is not None:
            try:
                parsed_due = resolve_due_date(due_date, datetime.now(get_user_timezone()))
            except ValueError as exc:
                return f"Error: {exc}"

        task = self._store.create_task(
            title=title,
            priority=priority,  # type: ignore[arg-type]
            description=description,
            due_date=parsed_due,
            tags=tags or [],
        )
        return f"Task created:\n{format_task(task)}"


@tool_parameters(
    tool_parameters_schema(
        status=StringSchema(
            "Optional filter by status",
            enum=["pending", "in_progress", "done"],
            nullable=True,
        ),
    )
)
class ListTasksTool(Tool):
    def __init__(self, store: TaskStoreProtocol) -> None:
        self._store = store

    @property
    def name(self) -> str:
        return "list_tasks"

    @property
    def description(self) -> str:
        return (
            "List all tasks, optionally filtered by status "
            "(pending, in_progress, or done)."
        )

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, status: str | None = None) -> str:
        if status is not None:
            tasks = self._store.list_tasks_by_status(status)  # type: ignore[arg-type]
        else:
            tasks = self._store.list_tasks()
        return format_task_list(tasks)


@tool_parameters(
    tool_parameters_schema(
        task_id=StringSchema("The full hex ID of the task to retrieve"),
        required=["task_id"],
    )
)
class GetTaskTool(Tool):
    def __init__(self, store: TaskStoreProtocol) -> None:
        self._store = store

    @property
    def name(self) -> str:
        return "get_task"

    @property
    def description(self) -> str:
        return "Get the full details of a single task by its ID."

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, task_id: str) -> str:
        try:
            task = self._store.get_task(task_id)
        except KeyError:
            return (
                f"Error: Task not found: '{task_id}'. "
                f"The store contains {len(self._store.list_tasks())} task(s)."
            )
        return format_task(task)


@tool_parameters(
    ObjectSchema(
        properties={
            "task_id": StringSchema("The full hex ID of the task to update"),
            "title": StringSchema("New title for the task", nullable=True),
            "description": StringSchema("New description for the task", nullable=True),
            "status": StringSchema(
                "New status for the task",
                enum=["pending", "in_progress", "done"],
                nullable=True,
            ),
            "priority": StringSchema(
                "New priority for the task",
                enum=["low", "medium", "high"],
                nullable=True,
            ),
            "due_date": StringSchema(
                "New due date — ISO 8601 or natural-language phrase. Pass null to clear.",
                nullable=True,
            ),
            "tags": ArraySchema(
                StringSchema("A tag label"),
                description="New tags list (replaces existing tags)",
                nullable=True,
            ),
        },
        required=["task_id"],
    ).to_json_schema()
)
class UpdateTaskTool(Tool):
    def __init__(self, store: TaskStoreProtocol) -> None:
        self._store = store

    @property
    def name(self) -> str:
        return "update_task"

    @property
    def description(self) -> str:
        return (
            "Update one or more fields on an existing task. "
            "Only provide the fields you want to change."
        )

    async def execute(
        self,
        task_id: str,
        title: str | None = None,
        description: str | None = None,
        status: str | None = None,
        priority: str | None = None,
        due_date: str | None = None,
        tags: list[str] | None = None,
    ) -> str:
        parsed_due: datetime | None = None
        has_due_date = due_date is not None
        if due_date is not None:
            try:
                parsed_due = resolve_due_date(due_date, datetime.now(get_user_timezone()))
            except ValueError as exc:
                return f"Error: {exc}"

        updates = TaskUpdate(
            **({"title": title} if title is not None else {}),
            **({"description": description} if description is not None else {}),
            **({"status": status} if status is not None else {}),  # type: ignore[dict-item]
            **({"priority": priority} if priority is not None else {}),  # type: ignore[dict-item]
            **({"due_date": parsed_due} if has_due_date else {}),
            **({"tags": tags} if tags is not None else {}),
        )

        try:
            task = self._store.update_task(task_id, updates)
        except KeyError:
            return (
                f"Error: Task not found: '{task_id}'. "
                f"The store contains {len(self._store.list_tasks())} task(s)."
            )
        return f"Task updated:\n{format_task(task)}"


@tool_parameters(
    tool_parameters_schema(
        task_id=StringSchema("The full hex ID of the task to mark as done"),
        required=["task_id"],
    )
)
class CompleteTaskTool(Tool):
    def __init__(self, store: TaskStoreProtocol) -> None:
        self._store = store

    @property
    def name(self) -> str:
        return "complete_task"

    @property
    def description(self) -> str:
        return "Mark a task as done by its ID."

    async def execute(self, task_id: str) -> str:
        try:
            task = self._store.mark_complete(task_id)
        except KeyError:
            return (
                f"Error: Task not found: '{task_id}'. "
                f"The store contains {len(self._store.list_tasks())} task(s)."
            )
        return f"Task completed:\n{format_task(task)}"


def register_task_tools(registry: ToolRegistry, store: TaskStoreProtocol) -> int:
    """Register all task CRUD tools into a ToolRegistry.

    Call this at startup after constructing the ToolRegistry and TaskStore.
    Returns the number of tools registered.
    """
    tools: list[Tool] = [
        CreateTaskTool(store=store),
        ListTasksTool(store=store),
        GetTaskTool(store=store),
        UpdateTaskTool(store=store),
        CompleteTaskTool(store=store),
    ]
    for tool in tools:
        registry.register(tool)
    count = len(tools)
    log.info("Registered %d task tools: create, list, get, update, complete", count)
    return count
