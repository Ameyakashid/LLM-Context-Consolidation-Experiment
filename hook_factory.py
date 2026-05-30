"""Hook chain construction for the custom nanobot gateway.

Factored out of ``custom_gateway.py`` to keep both files under the
300-line cap. :func:`create_hooks` owns the full chain build — it wires
every per-hook closure, inserts ``CalendarContextHook`` when the shared
cache+client are provided, appends ``MagicMirrorHook`` when the flag is
on, and tacks ``DiscoHook`` on last when its YAML config is present.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from datetime import date, datetime, time
from pathlib import Path
from typing import TYPE_CHECKING, Callable
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from pulse_checkin_dispatcher import PendingCheckinQueue

from nanobot.agent.hook import AgentHook
from nanobot.providers.base import LLMProvider

from buffer_hook import BufferHook
from buffer_store import BufferStore
from calendar_cache import CalendarCache
from calendar_hook import CalendarContextHook
from calendar_mcp_client import CalendarMCPClient
from checkin_schedule import CheckInScheduleStore
from cognitive_state_writer import write_cognitive_state
from disco_config import DiscoConfig, load_disco_config
from disco_hook import DiscoHook
from hook_adapter import HookAdapter
from cabinet_alerts import ALERTS_FEED_FILENAME, AlertEvaluator, AlertQueue
from cabinet_render_loop import CabinetRenderLoop, render_interval_from_env
from cabinet_server import is_cabinet_enabled, resolve_cabinet_feed_dir
from memory_context import MemoryContextHook
from memory_store import MemoryEntryStore
from scheduling_hook import SchedulingHook
from state_detection import StateName, load_state_config
from state_response_integration import StateResponseHook
from task_store import TaskStoreProtocol
from voice_buffer import VoiceBuffer, disco_comments_to_voice_lines
from voice_generator import VoiceTopUpGenerator, voice_topup_from_env
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
    """Wraps nanobot's LLMProvider.chat into our LLMCallable Protocol.

    Retries on transient failures. nanobot's provider returns the string
    ``"Error calling LLM: ..."`` (rather than raising) when the upstream
    request errors out — without a retry, a single OpenRouter connection
    blip silently kills the whole disco chain.
    """

    _MAX_ATTEMPTS = 3
    _BACKOFF_SECONDS = 0.8

    def __init__(self, provider: LLMProvider, model: str, max_tokens: int = 256) -> None:
        self._provider = provider
        self._model = model
        self._max_tokens = max_tokens

    async def __call__(self, prompt: str) -> str:
        messages = [{"role": "user", "content": prompt}]
        last = ""
        for attempt in range(1, self._MAX_ATTEMPTS + 1):
            try:
                response = await self._provider.chat(
                    messages=messages,
                    model=self._model,
                    max_tokens=self._max_tokens,
                    temperature=0.1,
                )
                content = response.content or ""
            except Exception as exc:
                content = f"Error calling LLM: {exc}"

            if content and not content.startswith("Error calling LLM"):
                return content

            last = content
            if attempt < self._MAX_ATTEMPTS:
                log.warning(
                    "LLM call failed (attempt %d/%d): %s — retrying",
                    attempt, self._MAX_ATTEMPTS, content[:80],
                )
                await asyncio.sleep(self._BACKOFF_SECONDS * attempt)
        return last


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
    pulse_pending_queue: "PendingCheckinQueue | None" = None,
    cabinet_services: dict[str, object] | None = None,
    data_dir: Path | None = None,
) -> list[AgentHook]:
    """Create the hook chain plus optional Cabinet services.

    When ``calendar_cache`` and ``calendar_client`` are both provided,
    a ``CalendarContextHook`` is inserted at position 4 (after
    ``SchedulingHook``, before ``BufferHook``). When the Cabinet is enabled
    (``CABINET_ENABLED``, fallback ``MAGICMIRROR_ENABLED``) and a
    ``cabinet_services`` dict is passed, this also constructs the
    ``CabinetRenderLoop`` (feeds + voices.md + alert evaluation) and, when a
    disco config + ``data_dir`` are present, the voice buffer + top-up
    generator — stashing them in ``cabinet_services`` for the runner to
    start/stop. Base hooks are wrapped in ``HookAdapter``; DiscoHook extends
    ``AgentHook`` directly and appends last.
    """
    state_config = load_state_config(states_path)
    llm_call = LLMCallableWrapper(provider=provider, model=model)

    task_store: TaskStoreProtocol = stores["task"]  # type: ignore[assignment]
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
        return state_hook.current_state

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
        pulse_mode=pulse_pending_queue is not None,
        pending_queue=pulse_pending_queue,
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

    cabinet_on = (
        cabinet_services is not None
        and repo_root is not None
        and env is not None
        and is_cabinet_enabled(env)
    )

    # Voice buffer shared by the render loop (writes voices.md), the disco
    # capture seam (stores fired lines), and the top-up generator.
    voice_buffer: VoiceBuffer | None = None
    on_comments: Callable[[list[object]], None] | None = None
    if cabinet_on and data_dir is not None:
        voice_buffer = VoiceBuffer(data_dir / "voice_buffer.json")
        buf = voice_buffer

        def on_comments(comments: list[object]) -> None:
            buf.add(disco_comments_to_voice_lines(comments, get_current_datetime()))

    if cabinet_on:
        feed_dir = resolve_cabinet_feed_dir(repo_root)  # type: ignore[arg-type]
        alert_evaluator = AlertEvaluator(AlertQueue(feed_dir / ALERTS_FEED_FILENAME))
        cabinet_services["render_loop"] = CabinetRenderLoop(  # type: ignore[index]
            feed_dir=feed_dir,
            task_store=task_store,
            buffer_store=buffer_store,
            schedule_store=schedule_store,
            get_cognitive_state=get_cognitive_state,
            get_current_datetime=get_current_datetime,
            interval_s=render_interval_from_env(env),
            voice_buffer=voice_buffer,
            alert_evaluator=alert_evaluator,
        )

    disco_cfg, disco_llm_call = _append_disco_hook(
        hooks, workspace, states_path, llm_call, get_cognitive_state,
        on_comments=on_comments,
    )

    if (
        cabinet_on and voice_buffer is not None
        and disco_cfg is not None and disco_llm_call is not None
    ):
        cabinet_services["voice_buffer"] = voice_buffer  # type: ignore[index]
        cabinet_services["voice_generator"] = VoiceTopUpGenerator(  # type: ignore[index]
            buffer=voice_buffer,
            config=disco_cfg,
            llm_call=disco_llm_call,
            task_store=task_store,
            buffer_store=buffer_store,
            get_cognitive_state=get_cognitive_state,
            get_current_datetime=get_current_datetime,
            interval_s=voice_topup_from_env(env),
        )
    return hooks


def _append_disco_hook(
    hooks: list[AgentHook],
    workspace: Path | None,
    states_path: Path,
    llm_call: LLMCallableWrapper,
    get_cognitive_state: Callable[[], StateName],
    on_comments: Callable[[list[object]], None] | None = None,
) -> tuple[DiscoConfig | None, LLMCallableWrapper | None]:
    """Append DiscoHook in place when the YAML config is present.

    Uses the disco_voices.yaml ``model:`` field for the voice LLM calls
    (separate from the main agent model). ``on_comments`` is forwarded to
    the hook so fired comments can be captured into the Cabinet voice buffer
    (chat output is unchanged). Returns ``(config, disco_llm_call)`` — both
    ``None`` when disco is disabled — so the caller can build the top-up
    generator on the same config + model.
    """
    base = workspace if workspace is not None else states_path.parent
    disco_config_path = base / DEFAULT_DISCO_VOICES_FILENAME
    if not disco_config_path.exists():
        log.info("DiscoHook disabled (no config at %s)", disco_config_path)
        return None, None
    try:
        disco_cfg = load_disco_config(disco_config_path)
        # Reasoning models (e.g. gpt-oss) spend output tokens on reasoning
        # before the JSON; 256 truncates the JSON mid-object. Give disco room.
        disco_llm_call = LLMCallableWrapper(
            provider=llm_call._provider,
            model=disco_cfg.model,
            max_tokens=2000,
        )
        log.info(
            "DiscoHook using model %s (main agent uses %s)",
            disco_cfg.model, llm_call._model,
        )
        disco_hook = DiscoHook(
            config=disco_cfg,
            llm_call=disco_llm_call,
            get_cognitive_state=get_cognitive_state,
            on_comments=on_comments,
        )
        hooks.append(disco_hook)
        log.info("DiscoHook loaded from %s", disco_config_path)
        return disco_cfg, disco_llm_call
    except Exception:
        log.exception("DiscoHook disabled (config error)")
        return None, None
