"""Custom nanobot gateway initialization: stores, hooks, tools.

Creates all ADHD app data stores and tools; hook chain construction
lives in :mod:`hook_factory` and is re-exported here for back-compat.
The run_gateway() entrypoint in gateway_runner.py calls these functions
to wire everything into the nanobot AgentLoop.

Environment variables:
    ADHD_DATA_DIR — directory for store JSON files (default: data/)
    ADHD_STATES_PATH — path to states.yaml (default: workspace/states.yaml)
"""

import logging
import os
from pathlib import Path

from nanobot.agent.tools.registry import ToolRegistry

from buffer_store import BufferStore
from buffer_tools import register_buffer_tools
from calendar_cache import CalendarCache
from calendar_mcp_client import CalendarMCPClient
from calendar_tools import register_calendar_tools
from checkin_schedule import CheckInScheduleStore
from gcal_setup import is_gcal_enabled
from hook_factory import (
    DISCO_HOOK_NAME,
    HOOK_CHAIN_ORDER,
    LLMCallableWrapper,
    SessionFlag,
    create_hooks,
)
from memory_store import MemoryEntryStore
from memory_tools import register_memory_tools
from task_store import TaskStore
from task_tools import register_task_tools
from voice_tools import register_voice_tools

log = logging.getLogger(__name__)

DEFAULT_DATA_DIR = "data"
DEFAULT_STATES_FILENAME = "states.yaml"
DEFAULT_STATE_FILE = "cognitive_state.json"

__all__ = [
    "DEFAULT_DATA_DIR",
    "DEFAULT_STATES_FILENAME",
    "DEFAULT_STATE_FILE",
    "DISCO_HOOK_NAME",
    "HOOK_CHAIN_ORDER",
    "LLMCallableWrapper",
    "SessionFlag",
    "create_hooks",
    "create_stores",
    "register_all_tools",
    "register_voice_tools_deferred",
    "resolve_data_dir",
    "resolve_states_path",
]


def resolve_data_dir(workspace: Path) -> Path:
    """Resolve the data directory from env var or default.

    Default is workspace/../data (i.e. ~/.nanobot/data/) which matches the
    path created by setup_workspace.py.
    """
    env_dir = os.environ.get("ADHD_DATA_DIR")
    if env_dir:
        return Path(env_dir).resolve()
    return workspace.parent / DEFAULT_DATA_DIR


def resolve_states_path(workspace: Path) -> Path:
    """Resolve the states.yaml path from env var or default under workspace."""
    env_path = os.environ.get("ADHD_STATES_PATH")
    if env_path:
        return Path(env_path).resolve()
    return workspace / DEFAULT_STATES_FILENAME


def create_stores(data_dir: Path) -> dict[str, object]:
    """Initialize all 4 data stores, ensuring the data directory exists."""
    data_dir.mkdir(parents=True, exist_ok=True)
    return {
        "task": TaskStore(storage_path=data_dir / "tasks.json"),
        "buffer": BufferStore(storage_path=data_dir / "buffers.json"),
        "memory": MemoryEntryStore(storage_path=data_dir / "memories.json"),
        "schedule": CheckInScheduleStore(
            storage_path=data_dir / "checkins.json"
        ),
    }


def register_all_tools(
    registry: ToolRegistry,
    stores: dict[str, object],
    calendar_cache: CalendarCache | None = None,
    calendar_client: CalendarMCPClient | None = None,
) -> int:
    """Register all non-voice custom tools, returning the total count.

    Voice tools ship through ``register_voice_tools_deferred`` (they need
    the MessageTool AgentLoop constructs later). Calendar tools register
    only when ``GOOGLE_CALENDAR_ENABLED`` is on; when shared cache+client
    are provided the tools reuse them so the hook and the tools share
    one cache and one MCP dispatcher.
    """
    task_store: TaskStore = stores["task"]  # type: ignore[assignment]
    buffer_store: BufferStore = stores["buffer"]  # type: ignore[assignment]
    memory_store: MemoryEntryStore = stores["memory"]  # type: ignore[assignment]

    total = (
        register_task_tools(registry, task_store)
        + register_buffer_tools(registry, buffer_store)
        + register_memory_tools(registry, memory_store)
    )
    if is_gcal_enabled(dict(os.environ)):
        cache = calendar_cache or CalendarCache()
        client = calendar_client or CalendarMCPClient(registry=registry)
        total += register_calendar_tools(registry, cache, client)
    return total


def register_voice_tools_deferred(registry: ToolRegistry) -> int:
    """Register voice tools after AgentLoop provides the MessageTool.

    Returns 1 when the MessageTool is present, 0 otherwise.
    """
    message_tool = registry.get("message")
    if message_tool is None:
        log.warning(
            "MessageTool not found — voice tools will not be registered"
        )
        return 0
    register_voice_tools(registry, message_tool)
    return 1
