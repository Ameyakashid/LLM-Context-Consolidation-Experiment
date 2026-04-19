"""Nanobot-ai tool wrappers for BufferStore operations.

Exposes five LLM-callable tools: create_buffer, list_buffers,
get_buffer_status, refill_buffer, manual_decrement. Each tool
delegates to a shared BufferStore instance and returns
LLM-readable string results.

Registration: call register_buffer_tools(registry, store) at startup.
"""

import logging
from datetime import date

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.schema import (
    IntegerSchema,
    StringSchema,
    tool_parameters_schema,
)

from buffer_store import Buffer, BufferStore

log = logging.getLogger(__name__)

STATUS_ENUM = ["active", "paused", "archived"]


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def format_buffer(buffer: Buffer) -> str:
    """Format a single buffer for LLM consumption."""
    days_until_due = (buffer.next_due_date - date.today()).days
    lines = [
        f"[{buffer.id[:8]}] {buffer.name}",
        f"  Level: {buffer.buffer_level}/{buffer.buffer_capacity}",
        f"  Status: {buffer.status}",
        f"  Next due: {buffer.next_due_date.isoformat()} ({days_until_due} days)",
        f"  Recurrence: every {buffer.recurrence_interval_days} days",
        f"  Alert threshold: {buffer.alert_threshold}",
    ]
    if buffer.buffer_level <= buffer.alert_threshold:
        lines.append("  ⚠ Below alert threshold")
    return "\n".join(lines)


def format_buffer_list(buffers: list[Buffer]) -> str:
    """Format multiple buffers. Returns 'No buffers found.' if empty."""
    if not buffers:
        return "No buffers found."
    return "\n\n".join(format_buffer(b) for b in buffers)


# ---------------------------------------------------------------------------
# Tool classes
# ---------------------------------------------------------------------------

@tool_parameters(
    tool_parameters_schema(
        name=StringSchema("Name for this buffer (e.g. 'Rent', 'Medication refill')"),
        capacity=IntegerSchema(
            description="Maximum units this buffer can hold (e.g. 4 for 4 weeks of rent)",
            minimum=1,
        ),
        recurrence_interval_days=IntegerSchema(
            description="Days between each obligation (e.g. 7 for weekly, 30 for monthly)",
            minimum=1,
        ),
        next_due_date=StringSchema(
            "Next date this obligation is due, in ISO format (e.g. '2026-05-01')",
        ),
        alert_threshold=IntegerSchema(
            description="Alert when buffer level drops to or below this value (default: 1)",
            minimum=0,
            nullable=True,
        ),
        buffer_level=IntegerSchema(
            description="Initial buffer level — defaults to capacity (full buffer) if not provided",
            minimum=0,
            nullable=True,
        ),
        required=["name", "capacity", "recurrence_interval_days", "next_due_date"],
    )
)
class CreateBufferTool(Tool):
    """Tool to create a new buffer for a recurring obligation."""

    def __init__(self, store: BufferStore) -> None:
        self._store = store

    @property
    def name(self) -> str:
        return "create_buffer"

    @property
    def description(self) -> str:
        return (
            "Create a buffer for a recurring obligation. Pre-loads units "
            "so the user has a safety margin before running out."
        )

    async def execute(
        self,
        name: str,
        capacity: int,
        recurrence_interval_days: int,
        next_due_date: str,
        alert_threshold: int | None = None,
        buffer_level: int | None = None,
    ) -> str:
        try:
            parsed_date = date.fromisoformat(next_due_date)
        except ValueError:
            return (
                f"Error: Invalid date format: '{next_due_date}'. "
                "Expected ISO date (e.g. '2026-05-01')."
            )

        resolved_threshold = alert_threshold if alert_threshold is not None else 1
        resolved_level = buffer_level if buffer_level is not None else capacity

        try:
            buffer = self._store.create_buffer(
                name=name,
                buffer_level=resolved_level,
                buffer_capacity=capacity,
                recurrence_interval_days=recurrence_interval_days,
                next_due_date=parsed_date,
                alert_threshold=resolved_threshold,
            )
        except ValueError as exc:
            return f"Error: {exc}"
        return f"Buffer created:\n{format_buffer(buffer)}"


@tool_parameters(
    tool_parameters_schema(
        status=StringSchema(
            "Optional filter by status",
            enum=STATUS_ENUM,
            nullable=True,
        ),
    )
)
class ListBuffersTool(Tool):
    """Tool to list buffers, optionally filtered by status."""

    def __init__(self, store: BufferStore) -> None:
        self._store = store

    @property
    def name(self) -> str:
        return "list_buffers"

    @property
    def description(self) -> str:
        return "List buffers with current levels and status, optionally filtered by status"

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, status: str | None = None) -> str:
        if status is not None:
            all_buffers = self._store.list_buffers()
            buffers = [b for b in all_buffers if b.status == status]
        else:
            buffers = self._store.list_active_buffers()
        return format_buffer_list(buffers)


@tool_parameters(
    tool_parameters_schema(
        buffer_id=StringSchema("The full hex ID of the buffer to retrieve"),
        required=["buffer_id"],
    )
)
class GetBufferStatusTool(Tool):
    """Tool to get detailed status of a single buffer."""

    def __init__(self, store: BufferStore) -> None:
        self._store = store

    @property
    def name(self) -> str:
        return "get_buffer_status"

    @property
    def description(self) -> str:
        return "Get detailed status of a single buffer: level, capacity, next due date, days until due"

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, buffer_id: str) -> str:
        try:
            buffer = self._store.get_buffer(buffer_id)
        except KeyError:
            return (
                f"Error: Buffer not found: '{buffer_id}'. "
                "Use list_buffers to see available buffers."
            )
        return format_buffer(buffer)


@tool_parameters(
    tool_parameters_schema(
        buffer_id=StringSchema("The full hex ID of the buffer to refill"),
        units=IntegerSchema(
            description="Number of units to add to the buffer",
            minimum=1,
        ),
        required=["buffer_id", "units"],
    )
)
class RefillBufferTool(Tool):
    """Tool to add units to a buffer."""

    def __init__(self, store: BufferStore) -> None:
        self._store = store

    @property
    def name(self) -> str:
        return "refill_buffer"

    @property
    def description(self) -> str:
        return "Add units to a buffer (capped at capacity). Use when the user restocks an obligation."

    async def execute(self, buffer_id: str, units: int) -> str:
        try:
            buffer = self._store.refill(buffer_id, units)
        except KeyError:
            return (
                f"Error: Buffer not found: '{buffer_id}'. "
                "Use list_buffers to see available buffers."
            )
        except ValueError as exc:
            return f"Error: {exc}"
        return f"Buffer refilled:\n{format_buffer(buffer)}"


@tool_parameters(
    tool_parameters_schema(
        buffer_id=StringSchema("The full hex ID of the buffer to decrement"),
        required=["buffer_id"],
    )
)
class ManualDecrementTool(Tool):
    """Tool to manually decrement a buffer by 1 unit."""

    def __init__(self, store: BufferStore) -> None:
        self._store = store

    @property
    def name(self) -> str:
        return "manual_decrement"

    @property
    def description(self) -> str:
        return (
            "Decrement a buffer by 1 unit and advance the due date. "
            "Use when an obligation is fulfilled outside the auto schedule."
        )

    async def execute(self, buffer_id: str) -> str:
        try:
            buffer = self._store.decrement(buffer_id)
        except KeyError:
            return (
                f"Error: Buffer not found: '{buffer_id}'. "
                "Use list_buffers to see available buffers."
            )
        except ValueError as exc:
            return f"Error: {exc}"
        return f"Buffer decremented:\n{format_buffer(buffer)}"


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register_buffer_tools(registry: ToolRegistry, store: BufferStore) -> int:
    """Register all buffer tools into a ToolRegistry.

    Call this at startup after constructing the ToolRegistry and BufferStore.
    Returns the number of tools registered.
    Example:
        store = BufferStore(Path("~/.nanobot/workspace/buffers.json"))
        register_buffer_tools(loop.tools, store)
    """
    tools: list[Tool] = [
        CreateBufferTool(store=store),
        ListBuffersTool(store=store),
        GetBufferStatusTool(store=store),
        RefillBufferTool(store=store),
        ManualDecrementTool(store=store),
    ]
    for tool in tools:
        registry.register(tool)
    count = len(tools)
    log.info("Registered %d buffer tools: create, list, get_status, refill, manual_decrement", count)
    return count
