"""Gateway runner: replicates stock nanobot gateway with ADHD hooks and tools."""

import asyncio
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from cabinet_flashcards import FlashcardPoolGenerator, flashcards_interval_from_env
from cabinet_news import NewsRefresher, news_settings_from_env
from cabinet_server import (
    is_cabinet_enabled,
    resolve_cabinet_feed_dir,
    resolve_wallpaper_dir,
)
from cabinet_wallpapers import WallpaperWatcher, wallpaper_interval_from_env
from calendar_cache import CalendarCache
from calendar_mcp_client import CalendarMCPClient
from cron_callback_setup import setup_cron_callback
from custom_gateway import (
    DEFAULT_STATE_FILE,
    SessionFlag,
    create_hooks,
    create_stores,
    register_all_tools,
    register_voice_tools_deferred,
    resolve_data_dir,
    resolve_states_path,
)
from gcal_setup import is_gcal_enabled
from pulse_checkin_dispatcher import PendingCheckinQueue
from pulse_checkin_store import is_pulse_engine_enabled
from pulse_gateway_setup import build_pulse_bundle
from pulse_system_concerns import is_dream_state_enabled
from voice_input_integration import setup_voice_input

log = logging.getLogger(__name__)


def run_gateway(workspace_arg: str | None, config_arg: str | None) -> int:
    """Replicate the stock gateway startup with our hooks and tools injected."""
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus
    from nanobot.channels.manager import ChannelManager
    from nanobot.cron.service import CronService
    from nanobot.session.manager import SessionManager
    from nanobot.cli.commands import _load_runtime_config, _make_provider, _migrate_cron_store
    from nanobot.config.paths import is_default_workspace
    from nanobot.utils.helpers import sync_workspace_templates

    config = _load_runtime_config(config_arg, workspace_arg)
    log.info("Starting custom gateway on port %d...", config.gateway.port)
    sync_workspace_templates(config.workspace_path)

    bus = MessageBus()
    provider = _make_provider(config)
    session_manager = SessionManager(config.workspace_path)

    if is_default_workspace(config.workspace_path):
        _migrate_cron_store(config)

    cron_store_path = config.workspace_path / "cron" / "jobs.json"
    cron = CronService(cron_store_path)

    tz_name = config.agents.defaults.timezone or "UTC"
    tz = ZoneInfo(tz_name)
    data_dir = resolve_data_dir(config.workspace_path)
    states_path = resolve_states_path(config.workspace_path)
    state_file_path = data_dir / DEFAULT_STATE_FILE

    session_flag = SessionFlag()
    repo_root = Path(__file__).resolve().parent
    stores = create_stores(data_dir, repo_root=repo_root, env=os.environ)

    env_map = dict(os.environ)
    gcal_enabled = is_gcal_enabled(env_map)
    calendar_cache = CalendarCache() if gcal_enabled else None
    calendar_client = CalendarMCPClient() if gcal_enabled else None
    pulse_queue = (
        PendingCheckinQueue() if is_pulse_engine_enabled(env_map) else None
    )
    cabinet_services: dict[str, object] = {}
    hooks = create_hooks(
        stores=stores,
        states_path=states_path,
        state_file_path=state_file_path,
        provider=provider,
        model=config.agents.defaults.model,
        session_flag=session_flag,
        tz=tz,
        workspace=config.workspace_path,
        calendar_cache=calendar_cache,
        calendar_client=calendar_client,
        repo_root=repo_root,
        env=env_map,
        pulse_pending_queue=pulse_queue,
        cabinet_services=cabinet_services,
        data_dir=data_dir,
    )
    cabinet_render_loop = cabinet_services.get("render_loop")
    cabinet_voice_generator = cabinet_services.get("voice_generator")
    cabinet_news: NewsRefresher | None = None
    cabinet_flashcards: FlashcardPoolGenerator | None = None
    cabinet_wallpapers: WallpaperWatcher | None = None
    if is_cabinet_enabled(env_map):
        news_query, news_max, news_interval = news_settings_from_env(env_map)
        cabinet_news = NewsRefresher(
            feed_dir=resolve_cabinet_feed_dir(repo_root),
            query=news_query, max_results=news_max, interval_s=news_interval,
        )
        fc_model = config.agents.defaults.model

        async def _flashcard_llm(prompt: str) -> str:
            resp = await provider.chat_with_retry(
                messages=[{"role": "user", "content": prompt}],
                model=fc_model, max_tokens=2000,
            )
            return resp.content or ""

        cabinet_flashcards = FlashcardPoolGenerator(
            llm_call=_flashcard_llm,
            feed_dir=resolve_cabinet_feed_dir(repo_root),
            pool_path=data_dir / "flashcard_pool.json",
            get_current_datetime=lambda: datetime.now(tz),
            interval_s=flashcards_interval_from_env(env_map),
        )
        cabinet_wallpapers = WallpaperWatcher(
            wallpaper_dir=resolve_wallpaper_dir(repo_root, env_map),
            interval_s=wallpaper_interval_from_env(env_map),
        )
    dream_kwargs = (
        _build_dream_kwargs(provider, config, repo_root, tz)
        if (pulse_queue is not None and is_dream_state_enabled(env_map))
        else {}
    )
    pulse_bundle = (
        build_pulse_bundle(
            hooks=hooks,
            stores=stores,
            env=env_map,
            tz=tz,
            pending_queue=pulse_queue,
            get_current_date=lambda: datetime.now(tz).date(),
            data_dir=data_dir,
            **dream_kwargs,
        )
        if pulse_queue is not None
        else None
    )

    agent = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=config.workspace_path,
        model=config.agents.defaults.model,
        max_iterations=config.agents.defaults.max_tool_iterations,
        context_window_tokens=config.agents.defaults.context_window_tokens,
        web_config=config.tools.web,
        context_block_limit=config.agents.defaults.context_block_limit,
        max_tool_result_chars=config.agents.defaults.max_tool_result_chars,
        provider_retry_mode=config.agents.defaults.provider_retry_mode,
        exec_config=config.tools.exec,
        cron_service=cron,
        restrict_to_workspace=config.tools.restrict_to_workspace,
        session_manager=session_manager,
        mcp_servers=config.tools.mcp_servers,
        channels_config=config.channels,
        timezone=tz_name,
        hooks=hooks,
    )

    if calendar_client is not None:
        calendar_client.set_registry(agent.tools)
    register_all_tools(agent.tools, stores, calendar_cache, calendar_client)
    register_voice_tools_deferred(agent.tools)

    setup_cron_callback(cron, agent, provider, bus)
    channels = ChannelManager(config, bus)
    setup_voice_input(env_map, channels.channels)
    heartbeat = _setup_heartbeat(
        config, agent, provider, session_manager, channels, bus, session_flag, tz_name,
    )
    _setup_dream(config, agent, cron, tz_name)
    log.info("Custom gateway ready: %d hooks", len(hooks))

    crashed = False

    async def run() -> None:
        nonlocal crashed
        try:
            await cron.start()
            await heartbeat.start()
            if cabinet_render_loop is not None:
                await cabinet_render_loop.start()
            if cabinet_voice_generator is not None:
                await cabinet_voice_generator.start()
            if cabinet_news is not None:
                await cabinet_news.start()
            if cabinet_flashcards is not None:
                await cabinet_flashcards.start()
            if cabinet_wallpapers is not None:
                await cabinet_wallpapers.start()
            if pulse_bundle is not None:
                pulse_bundle.start()
            await asyncio.gather(agent.run(), channels.start_all())
        except KeyboardInterrupt:
            log.info("Shutting down...")
        except Exception:
            log.exception("Gateway crashed unexpectedly")
            crashed = True
        finally:
            await agent.close_mcp()
            if cabinet_wallpapers is not None:
                await cabinet_wallpapers.stop()
            if cabinet_flashcards is not None:
                await cabinet_flashcards.stop()
            if cabinet_news is not None:
                await cabinet_news.stop()
            if cabinet_voice_generator is not None:
                await cabinet_voice_generator.stop()
            if cabinet_render_loop is not None:
                await cabinet_render_loop.stop()
            if pulse_bundle is not None:
                await pulse_bundle.stop()
            heartbeat.stop()
            cron.stop()
            agent.stop()
            await channels.stop_all()

    asyncio.run(run())
    return 1 if crashed else 0


def _pick_heartbeat_target(channels: "ChannelManager", session_manager: "SessionManager") -> tuple[str, str]:
    """Pick a routable channel/chat target for heartbeat messages."""
    enabled = set(channels.enabled_channels)
    for item in session_manager.list_sessions():
        key = item.get("key") or ""
        if ":" not in key:
            continue
        channel, chat_id = key.split(":", 1)
        if channel in {"cli", "system"}:
            continue
        if channel in enabled and chat_id:
            return channel, chat_id
    return "cli", "direct"


def _setup_heartbeat(
    config: "Config", agent: "AgentLoop", provider: "LLMProvider",
    session_manager: "SessionManager", channels: "ChannelManager", bus: "MessageBus",
    session_flag: SessionFlag, tz_name: str,
) -> "HeartbeatService":
    """Create the heartbeat service with session flag lifecycle management."""
    from nanobot.heartbeat.service import HeartbeatService

    async def _silent(*_args: object, **_kwargs: object) -> None: pass

    async def on_heartbeat_execute(tasks: str) -> str:
        channel, chat_id = _pick_heartbeat_target(channels, session_manager)
        session_flag.is_heartbeat = True
        try:
            resp = await agent.process_direct(
                tasks,
                session_key="heartbeat",
                channel=channel,
                chat_id=chat_id,
                on_progress=_silent,
            )
        finally:
            session_flag.is_heartbeat = False

        hb_cfg = config.gateway.heartbeat
        session = agent.sessions.get_or_create("heartbeat")
        session.retain_recent_legal_suffix(hb_cfg.keep_recent_messages)
        agent.sessions.save(session)
        return resp.content if resp else ""

    async def on_heartbeat_notify(response: str) -> None:
        from nanobot.bus.events import OutboundMessage
        channel, chat_id = _pick_heartbeat_target(channels, session_manager)
        if channel == "cli":
            return
        await bus.publish_outbound(
            OutboundMessage(channel=channel, chat_id=chat_id, content=response)
        )

    hb_cfg = config.gateway.heartbeat
    return HeartbeatService(
        workspace=config.workspace_path,
        provider=provider,
        model=agent.model,
        on_execute=on_heartbeat_execute,
        on_notify=on_heartbeat_notify,
        interval_s=hb_cfg.interval_s,
        enabled=hb_cfg.enabled,
        timezone=tz_name,
    )


def _setup_dream(
    config: "Config", agent: "AgentLoop", cron: "CronService", tz_name: str,
) -> None:
    """Register Dream system job on the cron service."""
    from nanobot.cron.types import CronJob, CronPayload
    dream_cfg = config.agents.defaults.dream
    if dream_cfg.model_override:
        agent.dream.model = dream_cfg.model_override
    agent.dream.max_batch_size = dream_cfg.max_batch_size
    agent.dream.max_iterations = dream_cfg.max_iterations
    cron.register_system_job(CronJob(
        id="dream", name="dream",
        schedule=dream_cfg.build_schedule(tz_name),
        payload=CronPayload(kind="system_event"),
    ))


def _build_dream_kwargs(
    provider: "LLMProvider", config: "Config", repo_root: Path, tz: ZoneInfo,
) -> dict[str, object]:
    template_path = repo_root / "workspace" / "templates" / "DREAM.md"
    prompt_template = template_path.read_text(encoding="utf-8")
    model_name = config.agents.defaults.model

    async def llm_caller(prompt: str, max_tokens: int) -> str:
        response = await provider.chat_with_retry(
            messages=[{"role": "user", "content": prompt}],
            model=model_name, max_tokens=max_tokens,
        )
        return response.content or ""

    return {
        "dream_prompt_template": prompt_template,
        "dream_llm_caller": llm_caller,
        "dream_clock": lambda: datetime.now(tz),
    }


def _parse_cli_args(args: list[str]) -> tuple[str | None, str | None]:
    """Parse --workspace/-w and --config/-c from argv."""
    workspace_val: str | None = None
    config_val: str | None = None
    idx = 0
    while idx < len(args):
        flag = args[idx]
        if flag in ("--workspace", "-w") and idx + 1 < len(args):
            workspace_val = args[idx + 1]
            idx += 2
        elif flag in ("--config", "-c") and idx + 1 < len(args):
            config_val = args[idx + 1]
            idx += 2
        else:
            idx += 1
    return workspace_val, config_val

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    w, c = _parse_cli_args(sys.argv[1:])
    run_gateway(w, c)
