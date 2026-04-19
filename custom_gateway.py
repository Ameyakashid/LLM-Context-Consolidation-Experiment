"""Custom nanobot gateway initialization: stores, hooks, tools.

Creates all ADHD app data stores, hooks (in chain order), and tools.
The run_gateway() entrypoint in gateway_runner.py calls these functions
to wire everything into the nanobot AgentLoop.

Environment variables:
    ADHD_DATA_DIR — directory for store JSON files (default: data/)
    ADHD_STATES_PATH — path to states.yaml (default: workspace/states.yaml)
"""

import logging
import os
from datetime import date, time
from pathlib import Path
from zoneinfo import ZoneInfo

from nanobot.agent.hook import AgentHook
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.providers.base import LLMProvider

from buffer_hook import BufferHook
from buffer_store import BufferStore
from buffer_tools import register_buffer_tools
from checkin_schedule import CheckInScheduleStore
from cognitive_state_writer import write_cognitive_state
from disco_config import load_disco_config
from disco_hook import DiscoHook
from hook_adapter import HookAdapter
from memory_context import MemoryContextHook
from memory_store import MemoryEntryStore
from memory_tools import register_memory_tools
from scheduling_hook import SchedulingHook
from state_detection import StateName, load_state_config
from state_response_integration import StateResponseHook
from task_store import TaskStore
from task_tools import register_task_tools
from voice_tools import register_voice_tools
from voice_trigger_hook import VoiceHook

log = logging.getLogger(__name__)

HOOK_CHAIN_ORDER = [
    "StateResponseHook",
    "MemoryContextHook",
    "SchedulingHook",
    "BufferHook",
    "VoiceHook",
]

DISCO_HOOK_NAME = "DiscoHook"

DEFAULT_DATA_DIR = "data"
DEFAULT_STATES_FILENAME = "states.yaml"
DEFAULT_DISCO_VOICES_FILENAME = "disco_voices.yaml"
DEFAULT_MAX_MEMORY_ENTRIES = 20
DEFAULT_STATE_FILE = "cognitive_state.json"


class SessionFlag:
    """Mutable flag indicating whether the current iteration is a heartbeat.

    Set to True before heartbeat process_direct calls, cleared after.
    Three hooks read this via is_scheduled_session closures.
    """

    def __init__(self) -> None:
        self._is_heartbeat: bool = False

    @property
    def is_heartbeat(self) -> bool:
        return self._is_heartbeat

    @is_heartbeat.setter
    def is_heartbeat(self, value: bool) -> None:
        self._is_heartbeat = value


class LLMCallableWrapper:
    """Wraps nanobot's LLMProvider.chat into our LLMCallable Protocol.

    StateResponseHook expects async (str) -> str for state classification.
    This adapter calls the full provider.chat() with minimal parameters.
    """

    def __init__(self, provider: LLMProvider, model: str) -> None:
        self._provider = provider
        self._model = model

    async def __call__(self, prompt: str) -> str:
        messages = [{"role": "user", "content": prompt}]
        response = await self._provider.chat(
            messages=messages,
            model=self._model,
            max_tokens=256,
            temperature=0.1,
        )
        return response.content or ""


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


def create_hooks(
    stores: dict[str, object],
    states_path: Path,
    state_file_path: Path,
    provider: LLMProvider,
    model: str,
    session_flag: SessionFlag,
    tz: ZoneInfo,
    workspace: Path | None = None,
) -> list[AgentHook]:
    """Create the hook chain: 5 base hooks plus an optional DiscoHook.

    The 5 base hooks (see HOOK_CHAIN_ORDER) are wrapped in HookAdapter
    (before_iteration only). DiscoHook is appended only when
    disco_voices.yaml is present and parses cleanly; it extends
    AgentHook directly because it uses finalize_content.
    """
    state_config = load_state_config(states_path)
    llm_call = LLMCallableWrapper(provider=provider, model=model)

    task_store: TaskStore = stores["task"]  # type: ignore[assignment]
    buffer_store: BufferStore = stores["buffer"]  # type: ignore[assignment]
    memory_store: MemoryEntryStore = stores["memory"]  # type: ignore[assignment]
    schedule_store: CheckInScheduleStore = stores["schedule"]  # type: ignore[assignment]

    state_hook = StateResponseHook(
        config=state_config,
        llm_call=llm_call,
        state_writer=write_cognitive_state,
        state_file_path=state_file_path,
    )

    def get_cognitive_state() -> StateName:
        return state_hook.current_state  # type: ignore[return-value]

    def is_scheduled_session() -> bool:
        return session_flag.is_heartbeat

    def get_current_date() -> date:
        from datetime import datetime as dt
        return dt.now(tz).date()

    def get_current_time() -> time:
        from datetime import datetime as dt
        return dt.now(tz).timetz()

    memory_hook = MemoryContextHook(
        store=memory_store,
        max_entries=DEFAULT_MAX_MEMORY_ENTRIES,
    )

    scheduling_hook = SchedulingHook(
        schedule_store=schedule_store,
        task_store=task_store,
        memory_store=memory_store,
        is_scheduled_session=is_scheduled_session,
        get_cognitive_state=get_cognitive_state,
        get_current_date=get_current_date,
        get_current_time=get_current_time,
    )

    buffer_hook = BufferHook(
        buffer_store=buffer_store,
        is_scheduled_session=is_scheduled_session,
        get_current_date=get_current_date,
    )

    voice_hook = VoiceHook(
        is_scheduled_session=is_scheduled_session,
        get_cognitive_state=get_cognitive_state,
    )

    hooks: list[AgentHook] = [
        HookAdapter(hook=state_hook, name="StateResponseHook"),
        HookAdapter(hook=memory_hook, name="MemoryContextHook"),
        HookAdapter(hook=scheduling_hook, name="SchedulingHook"),
        HookAdapter(hook=buffer_hook, name="BufferHook"),
        HookAdapter(hook=voice_hook, name="VoiceHook"),
    ]

    # DiscoHook extends AgentHook directly -- not wrapped in HookAdapter
    disco_config_path = _resolve_disco_config_path(
        workspace=workspace, states_path=states_path
    )
    if disco_config_path.exists():
        try:
            disco_config = load_disco_config(disco_config_path)
            disco_hook = DiscoHook(
                config=disco_config,
                llm_call=llm_call,
                get_cognitive_state=get_cognitive_state,
            )
            hooks.append(disco_hook)
            log.info("DiscoHook loaded from %s", disco_config_path)
        except Exception:
            log.exception(
                "Failed to load disco config from %s; DiscoHook disabled",
                disco_config_path,
            )
    else:
        log.info(
            "Disco config not found at %s; DiscoHook disabled",
            disco_config_path,
        )

    return hooks


def _resolve_disco_config_path(
    workspace: Path | None,
    states_path: Path,
) -> Path:
    """Resolve path to disco_voices.yaml.

    Uses the workspace directory if provided, otherwise infers from
    the states_path parent (which is the workspace directory).
    """
    if workspace is not None:
        return workspace / DEFAULT_DISCO_VOICES_FILENAME
    return states_path.parent / DEFAULT_DISCO_VOICES_FILENAME


def register_all_tools(
    registry: ToolRegistry, stores: dict[str, object]
) -> int:
    """Register all non-voice custom tools on the agent's tool registry.

    Voice tools are registered separately via register_voice_tools_deferred
    because they need the MessageTool which is only available after
    AgentLoop construction.

    Returns the total count of tools registered, summed from each
    per-registrar function.
    """
    task_store: TaskStore = stores["task"]  # type: ignore[assignment]
    buffer_store: BufferStore = stores["buffer"]  # type: ignore[assignment]
    memory_store: MemoryEntryStore = stores["memory"]  # type: ignore[assignment]

    return (
        register_task_tools(registry, task_store)
        + register_buffer_tools(registry, buffer_store)
        + register_memory_tools(registry, memory_store)
    )


def register_voice_tools_deferred(registry: ToolRegistry) -> int:
    """Register voice tools after AgentLoop provides the MessageTool.

    Must be called after AgentLoop construction so agent.tools.get("message")
    returns the real MessageTool instance.

    Returns 1 (the count of voice tools registered), or 0 if MessageTool
    is not available.
    """
    message_tool = registry.get("message")
    if message_tool is None:
        log.warning(
            "MessageTool not found — voice tools will not be registered"
        )
        return 0
    register_voice_tools(registry, message_tool)
    return 1
