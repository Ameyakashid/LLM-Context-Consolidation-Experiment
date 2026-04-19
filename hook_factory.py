"""Hook chain construction for the custom nanobot gateway.

Factored out of ``custom_gateway.py`` to keep both files under the
300-line cap. :func:`create_hooks` owns the full chain build — it wires
every per-hook closure, inserts ``CalendarContextHook`` when the shared
cache+client are provided, appends ``MagicMirrorHook`` when the flag is
on, and tacks ``DiscoHook`` on last when its YAML config is present.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import date, datetime, time
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from nanobot.agent.hook import AgentHook
from nanobot.providers.base import LLMProvider

from buffer_hook import BufferHook
from buffer_store import BufferStore
from calendar_cache import CalendarCache
from calendar_hook import CalendarContextHook
from calendar_mcp_client import CalendarMCPClient
from checkin_schedule import CheckInScheduleStore
from cognitive_state_writer import write_cognitive_state
from disco_config import load_disco_config
from disco_hook import DiscoHook
from hook_adapter import HookAdapter
from magicmirror_feeds import resolve_feed_dir
from magicmirror_hook import MagicMirrorHook, build_webhook_base_url
from magicmirror_setup import is_magicmirror_enabled
from memory_context import MemoryContextHook
from memory_store import MemoryEntryStore
from scheduling_hook import SchedulingHook
from state_detection import StateName, load_state_config
from state_response_integration import StateResponseHook
from task_store import TaskStore
from voice_trigger_hook import VoiceHook

log = logging.getLogger(__name__)

HOOK_CHAIN_ORDER = [
    "StateResponseHook",
    "MemoryContextHook",
    "SchedulingHook",
    "CalendarContextHook",
    "BufferHook",
    "VoiceHook",
]
DISCO_HOOK_NAME = "DiscoHook"
DEFAULT_DISCO_VOICES_FILENAME = "disco_voices.yaml"
DEFAULT_MAX_MEMORY_ENTRIES = 20


class SessionFlag:
    """Mutable flag set True during heartbeat process_direct calls."""

    def __init__(self) -> None:
        self._is_heartbeat: bool = False

    @property
    def is_heartbeat(self) -> bool:
        return self._is_heartbeat

    @is_heartbeat.setter
    def is_heartbeat(self, value: bool) -> None:
        self._is_heartbeat = value


class LLMCallableWrapper:
    """Wraps nanobot's LLMProvider.chat into our LLMCallable Protocol."""

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


def create_hooks(
    stores: dict[str, object],
    states_path: Path,
    state_file_path: Path,
    provider: LLMProvider,
    model: str,
    session_flag: SessionFlag,
    tz: ZoneInfo,
    workspace: Path | None = None,
    calendar_cache: CalendarCache | None = None,
    calendar_client: CalendarMCPClient | None = None,
    repo_root: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> list[AgentHook]:
    """Create the hook chain: up to 6 base hooks plus optional Disco/MM.

    When ``calendar_cache`` and ``calendar_client`` are both provided,
    a ``CalendarContextHook`` is inserted at position 4 (after
    ``SchedulingHook``, before ``BufferHook``). When
    ``MAGICMIRROR_ENABLED=true`` in ``env`` and ``repo_root`` is
    provided, a ``MagicMirrorHook`` is appended after ``VoiceHook``
    (before any ``DiscoHook``). Base hooks are wrapped in
    ``HookAdapter``; DiscoHook extends ``AgentHook`` directly.
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
        return datetime.now(tz).date()

    def get_current_time() -> time:
        return datetime.now(tz).timetz()

    def get_current_datetime() -> datetime:
        return datetime.now(tz)

    memory_hook = MemoryContextHook(
        store=memory_store, max_entries=DEFAULT_MAX_MEMORY_ENTRIES,
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
    ]
    if calendar_cache is not None and calendar_client is not None:
        hooks.append(HookAdapter(
            hook=CalendarContextHook(
                cache=calendar_cache,
                client=calendar_client,
                is_scheduled_session=is_scheduled_session,
                get_cognitive_state=get_cognitive_state,
                get_current_datetime=get_current_datetime,
            ),
            name="CalendarContextHook",
        ))
    hooks.append(HookAdapter(hook=buffer_hook, name="BufferHook"))
    hooks.append(HookAdapter(hook=voice_hook, name="VoiceHook"))

    mm_hook = _maybe_build_magicmirror_hook(
        env=env,
        repo_root=repo_root,
        task_store=task_store,
        buffer_store=buffer_store,
        schedule_store=schedule_store,
        is_scheduled_session=is_scheduled_session,
        get_cognitive_state=get_cognitive_state,
        get_current_datetime=get_current_datetime,
    )
    if mm_hook is not None:
        hooks.append(HookAdapter(hook=mm_hook, name="MagicMirrorHook"))

    _append_disco_hook(hooks, workspace, states_path, llm_call,
                       get_cognitive_state)
    return hooks


def _append_disco_hook(
    hooks: list[AgentHook],
    workspace: Path | None,
    states_path: Path,
    llm_call: LLMCallableWrapper,
    get_cognitive_state: Callable[[], StateName],
) -> None:
    """Append DiscoHook in place when the YAML config is present."""
    base = workspace if workspace is not None else states_path.parent
    disco_config_path = base / DEFAULT_DISCO_VOICES_FILENAME
    if not disco_config_path.exists():
        log.info("DiscoHook disabled (no config at %s)", disco_config_path)
        return
    try:
        disco_hook = DiscoHook(
            config=load_disco_config(disco_config_path),
            llm_call=llm_call,
            get_cognitive_state=get_cognitive_state,
        )
        hooks.append(disco_hook)
        log.info("DiscoHook loaded from %s", disco_config_path)
    except Exception:
        log.exception("DiscoHook disabled (config error)")


def _maybe_build_magicmirror_hook(
    env: Mapping[str, str] | None,
    repo_root: Path | None,
    task_store: TaskStore,
    buffer_store: BufferStore,
    schedule_store: CheckInScheduleStore,
    is_scheduled_session: Callable[[], bool],
    get_cognitive_state: Callable[[], StateName],
    get_current_datetime: Callable[[], datetime],
) -> MagicMirrorHook | None:
    """Build the MagicMirror hook when the flag is on and deps are present.

    Returns ``None`` when ``MAGICMIRROR_ENABLED`` is missing/false or
    when ``repo_root`` was not supplied — flag-off path allocates no
    hook, starts no thread pool, and writes no feed files.
    """
    if env is None or repo_root is None:
        return None
    if not is_magicmirror_enabled(env):
        return None
    host = env.get("MAGICMIRROR_WEBHOOK_HOST", "127.0.0.1")
    port = env.get("MAGICMIRROR_WEBHOOK_PORT", "8080")
    return MagicMirrorHook(
        webhook_base_url=build_webhook_base_url(host, port),
        feed_dir=resolve_feed_dir(repo_root),
        task_store=task_store,
        buffer_store=buffer_store,
        schedule_store=schedule_store,
        is_scheduled_session=is_scheduled_session,
        get_cognitive_state=get_cognitive_state,
        get_current_datetime=get_current_datetime,
    )
