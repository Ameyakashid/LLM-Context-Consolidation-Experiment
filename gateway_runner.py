"""Gateway runner: replicates stock nanobot gateway with ADHD hooks and tools."""

import asyncio
import logging
import os
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

from calendar_cache import CalendarCache
from calendar_mcp_client import CalendarMCPClient
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
    stores = create_stores(data_dir)

    gcal_enabled = is_gcal_enabled(dict(os.environ))
    calendar_cache = CalendarCache() if gcal_enabled else None
    calendar_client = CalendarMCPClient() if gcal_enabled else None

    repo_root = Path(__file__).resolve().parent
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
        env=dict(os.environ),
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

    _setup_cron_callback(cron, agent, provider, bus)
    channels = ChannelManager(config, bus)
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
            await asyncio.gather(agent.run(), channels.start_all())
        except KeyboardInterrupt:
            log.info("Shutting down...")
        except Exception:
            log.exception("Gateway crashed unexpectedly")
            crashed = True
        finally:
            await agent.close_mcp()
            heartbeat.stop()
            cron.stop()
            agent.stop()
            await channels.stop_all()

    asyncio.run(run())
    return 1 if crashed else 0


def _setup_cron_callback(
    cron: "CronService", agent: "AgentLoop", provider: "LLMProvider", bus: "MessageBus",
) -> None:
    """Wire up the cron job callback on the agent."""
    from nanobot.cron.types import CronJob

    async def on_cron_job(job: CronJob) -> str | None:
        if job.name == "dream":
            try:
                await agent.dream.run()
                log.info("Dream cron job completed")
            except Exception:
                log.exception("Dream cron job failed")
            return None

        from nanobot.agent.tools.cron import CronTool
        from nanobot.agent.tools.message import MessageTool
        from nanobot.utils.evaluator import evaluate_response

        reminder_note = (
            "[Scheduled Task] Timer finished.\n\n"
            f"Task '{job.name}' has been triggered.\n"
            f"Scheduled instruction: {job.payload.message}"
        )
        cron_tool = agent.tools.get("cron")
        cron_token = None
        if isinstance(cron_tool, CronTool):
            cron_token = cron_tool.set_cron_context(True)
        try:
            resp = await agent.process_direct(
                reminder_note,
                session_key=f"cron:{job.id}",
                channel=job.payload.channel or "cli",
                chat_id=job.payload.to or "direct",
            )
        finally:
            if isinstance(cron_tool, CronTool) and cron_token is not None:
                cron_tool.reset_cron_context(cron_token)

        response = resp.content if resp else ""
        message_tool = agent.tools.get("message")
        if isinstance(message_tool, MessageTool) and message_tool._sent_in_turn:
            return response

        if job.payload.deliver and job.payload.to and response:
            should_notify = await evaluate_response(
                response, reminder_note, provider, agent.model,
            )
            if should_notify:
                from nanobot.bus.events import OutboundMessage
                await bus.publish_outbound(OutboundMessage(
                    channel=job.payload.channel or "cli",
                    chat_id=job.payload.to, content=response,
                ))
        return response

    cron.on_job = on_cron_job


def _pick_heartbeat_target(
    channels: "ChannelManager", session_manager: "SessionManager",
) -> tuple[str, str]:
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
