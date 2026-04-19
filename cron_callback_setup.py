"""Cron callback wiring extracted from ``gateway_runner.py``.

Extracted to keep ``gateway_runner.py`` under the 300-line cap once the
Pulse lifecycle setup (sub-03) is folded in.  No behaviour change — the
function body is copied verbatim.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus
    from nanobot.cron.service import CronService
    from nanobot.providers.base import LLMProvider

log = logging.getLogger(__name__)


def setup_cron_callback(
    cron: "CronService",
    agent: "AgentLoop",
    provider: "LLMProvider",
    bus: "MessageBus",
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


__all__ = ["setup_cron_callback"]
