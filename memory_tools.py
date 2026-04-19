"""Nanobot-ai tool wrappers for MemoryEntryStore operations.

Exposes three LLM-callable tools: save_memory, list_memories,
dismiss_memory. Each tool delegates to a shared MemoryEntryStore
instance and returns LLM-readable string results.

Registration: call register_memory_tools(registry, store) at startup.
"""

import logging

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.schema import (
    ObjectSchema,
    StringSchema,
    tool_parameters_schema,
)

from memory_store import MemoryEntry, MemoryEntryStore

log = logging.getLogger(__name__)

CATEGORY_ENUM = ["commitment", "deadline", "blocker", "energy_state", "context_switch"]


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def format_memory_entry(entry: MemoryEntry) -> str:
    """Format a single memory entry for LLM consumption."""
    lines = [
        f"[{entry.id[:8]}] {entry.category}: {entry.content}",
        f"  Created: {entry.created_at.isoformat()}",
    ]
    if entry.resolved_at is not None:
        lines.append(f"  Resolved: {entry.resolved_at.isoformat()}")
    if entry.metadata:
        pairs = ", ".join(f"{k}={v}" for k, v in entry.metadata.items())
        lines.append(f"  Metadata: {pairs}")
    return "\n".join(lines)


def format_memory_list(entries: list[MemoryEntry]) -> str:
    """Format multiple memory entries. Returns 'No active memories.' if empty."""
    if not entries:
        return "No active memories."
    return "\n\n".join(format_memory_entry(e) for e in entries)


# ---------------------------------------------------------------------------
# Tool classes
# ---------------------------------------------------------------------------

@tool_parameters(
    tool_parameters_schema(
        category=StringSchema(
            "Memory category",
            enum=CATEGORY_ENUM,
        ),
        content=StringSchema(
            "What to remember — the specific commitment, deadline, blocker, observation, or context switch",
        ),
        metadata=ObjectSchema(
            additional_properties={"type": "string"},
            description="Optional key-value metadata (e.g. due_date, task_id, source)",
            nullable=True,
        ),
        required=["category", "content"],
    )
)
class SaveMemoryTool(Tool):
    """Tool to save a structured memory entry."""

    def __init__(self, store: MemoryEntryStore) -> None:
        self._store = store

    @property
    def name(self) -> str:
        return "save_memory"

    @property
    def description(self) -> str:
        return (
            "Save a commitment, deadline, blocker, energy state observation, "
            "or context switch to persistent memory"
        )

    async def execute(
        self,
        category: str,
        content: str,
        metadata: dict[str, str] | None = None,
    ) -> str:
        entry = self._store.create_entry(
            category=category,  # type: ignore[arg-type]
            content=content,
            metadata=metadata or {},
        )
        return f"Memory saved:\n{format_memory_entry(entry)}"


@tool_parameters(
    tool_parameters_schema(
        category=StringSchema(
            "Optional filter by category",
            enum=CATEGORY_ENUM,
            nullable=True,
        ),
    )
)
class ListMemoriesTool(Tool):
    """Tool to list active memory entries."""

    def __init__(self, store: MemoryEntryStore) -> None:
        self._store = store

    @property
    def name(self) -> str:
        return "list_memories"

    @property
    def description(self) -> str:
        return "List active memory entries, optionally filtered by category"

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, category: str | None = None) -> str:
        if category is not None:
            entries = self._store.list_entries_by_category(category)  # type: ignore[arg-type]
        else:
            entries = self._store.list_active_entries()
        return format_memory_list(entries)


@tool_parameters(
    tool_parameters_schema(
        entry_id=StringSchema("The full hex ID of the memory entry to dismiss"),
        required=["entry_id"],
    )
)
class DismissMemoryTool(Tool):
    """Tool to dismiss (resolve) a memory entry by ID."""

    def __init__(self, store: MemoryEntryStore) -> None:
        self._store = store

    @property
    def name(self) -> str:
        return "dismiss_memory"

    @property
    def description(self) -> str:
        return "Dismiss (resolve) a memory entry by its ID when it is no longer relevant"

    async def execute(self, entry_id: str) -> str:
        try:
            entry = self._store.resolve_entry(entry_id)
        except KeyError:
            return (
                f"Error: Memory entry not found: '{entry_id}'. "
                "Use list_memories to see active entries."
            )
        return f"Memory dismissed:\n{format_memory_entry(entry)}"


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register_memory_tools(registry: ToolRegistry, store: MemoryEntryStore) -> int:
    """Register all memory tools into a ToolRegistry.

    Call this at startup after constructing the ToolRegistry and MemoryEntryStore.
    Returns the number of tools registered.
    Example:
        store = MemoryEntryStore(Path("~/.nanobot/workspace/memories.json"))
        register_memory_tools(loop.tools, store)
    """
    tools: list[Tool] = [
        SaveMemoryTool(store=store),
        ListMemoriesTool(store=store),
        DismissMemoryTool(store=store),
    ]
    for tool in tools:
        registry.register(tool)
    count = len(tools)
    log.info("Registered %d memory tools: save, list, dismiss", count)
    return count
