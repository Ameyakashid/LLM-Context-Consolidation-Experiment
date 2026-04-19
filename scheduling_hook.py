"""Scheduling integration hook for nanobot-ai heartbeat sessions.

Detects heartbeat-triggered sessions, evaluates due check-ins against the
current cognitive state, and injects check-in context into the system prompt
so the LLM generates personality-consistent proactive messages.

Uses Approach C (Hybrid): heartbeat as polling trigger, structured scheduling
logic as gate. The heartbeat service ticks every 30 minutes; this hook checks
what's due and decides whether to fire, modify, defer, or suppress.
"""

import logging
from datetime import date, time
from typing import TYPE_CHECKING, Callable

from checkin_schedule import CheckInScheduleStore, CheckInType
from hook_context import HookContext
from memory_store import MemoryEntryStore
from schedule_engine import (
    CheckInContext,
    ScheduleAction,
    assemble_checkin_context,
    evaluate_checkin,
)
from state_detection import StateName
from task_store import TaskStore

if TYPE_CHECKING:
    from pulse_checkin_dispatcher import PendingCheckinQueue

log = logging.getLogger(__name__)

CHECKIN_DISPLAY_NAMES: dict[str, str] = {
    "morning_motivation": "Morning Motivation",
    "morning_plan": "Morning Plan",
    "afternoon_check": "Afternoon Check",
    "evening_review": "Evening Review",
}


# ---------------------------------------------------------------------------
# Pure functions
# ---------------------------------------------------------------------------

def format_task_summary(context: CheckInContext) -> list[str]:
    """Format task and memory data from check-in context into summary lines."""
    lines: list[str] = []

    if context.pending_tasks:
        top = context.pending_tasks[0]
        lines.append(
            f"- {len(context.pending_tasks)} pending tasks "
            f'(top: "{top.title}")'
        )

    if context.in_progress_tasks:
        titles = [t.title for t in context.in_progress_tasks[:3]]
        lines.append(f"- In progress: {', '.join(titles)}")

    if context.completed_today_tasks:
        lines.append(
            f"- {len(context.completed_today_tasks)} completed today"
        )

    if context.overdue_tasks:
        lines.append(f"- {len(context.overdue_tasks)} overdue tasks")

    if context.deadline_memories:
        lines.append(
            f"- {len(context.deadline_memories)} upcoming deadlines"
        )

    if context.energy_memories:
        latest = context.energy_memories[0]
        lines.append(f'- Latest energy note: "{latest.content}"')

    return lines


def format_checkin_prompt(
    checkin_type: CheckInType,
    action: ScheduleAction,
    context: CheckInContext,
) -> str:
    """Format the check-in instruction block for system prompt injection."""
    display_name = CHECKIN_DISPLAY_NAMES[checkin_type]

    lines = [
        f"## Active Check-In: {display_name}",
        "",
        f"Action: {action.action} ({action.reason})",
    ]

    if action.modified_scope is not None:
        lines.append(f"Modified scope: {action.modified_scope}")

    task_lines = format_task_summary(context)
    if task_lines:
        lines.append("")
        lines.append("### Context")
        lines.extend(task_lines)

    lines.append("")
    lines.append(
        "Deliver this check-in now. Refer to the Scheduled Check-Ins "
        "section for tone and content guidance."
    )

    return "\n".join(lines)


def inject_checkin_into_prompt(
    system_content: str,
    checkin_block: str,
) -> str:
    """Append the check-in instruction block to the system prompt."""
    if not checkin_block:
        return system_content
    return system_content + "\n\n" + checkin_block


# ---------------------------------------------------------------------------
# Hook
# ---------------------------------------------------------------------------

class SchedulingHook:
    """Hook that evaluates and injects due check-ins in heartbeat sessions.

    Designed for nanobot-ai's AgentHook lifecycle. On before_iteration(),
    detects scheduled sessions, finds due check-ins, evaluates them against
    the current cognitive state, and enriches the system prompt with
    check-in instructions and context.

    Constructor callables decouple the hook from runtime concerns:
    - is_scheduled_session: returns True in heartbeat/cron sessions
    - get_cognitive_state: returns last-known state (baseline if unknown)
    - get_current_date/time: wall-clock in user's timezone

    Hook ordering: runs AFTER StateResponseHook and MemoryContextHook.
    """

    def __init__(
        self,
        schedule_store: CheckInScheduleStore,
        task_store: TaskStore,
        memory_store: MemoryEntryStore,
        is_scheduled_session: Callable[[], bool],
        get_cognitive_state: Callable[[], StateName],
        get_current_date: Callable[[], date],
        get_current_time: Callable[[], time],
        pulse_mode: bool = False,
        pending_queue: "PendingCheckinQueue | None" = None,
    ) -> None:
        self._schedule_store = schedule_store
        self._task_store = task_store
        self._memory_store = memory_store
        self._is_scheduled_session = is_scheduled_session
        self._get_cognitive_state = get_cognitive_state
        self._get_current_date = get_current_date
        self._get_current_time = get_current_time
        self._pulse_mode = pulse_mode
        self._pending_queue = pending_queue

    async def before_iteration(self, context: HookContext) -> None:
        """Evaluate due check-ins and inject into system prompt."""
        try:
            self._process(context)
        except Exception as exc:
            log.warning("Scheduling hook failed: %s", exc)

    def _process(self, context: HookContext) -> None:
        """Core scheduling logic, separated for testability."""
        messages = context.messages
        if not messages:
            return

        if not self._is_scheduled_session():
            return

        if messages[0].get("role") != "system":
            return

        if self._pulse_mode:
            self._drain_pending_queue(messages)
            return

        current_date = self._get_current_date()
        current_time = self._get_current_time()

        due_checkins = self._schedule_store.get_due(
            current_date, current_time
        )
        if not due_checkins:
            return

        cognitive_state = self._get_cognitive_state()

        # Process first due check-in only — one per heartbeat tick
        checkin = due_checkins[0]
        action = evaluate_checkin(checkin.type_id, cognitive_state)

        if action.action == "suppress":
            log.info(
                "Suppressed %s: %s", checkin.type_id, action.reason
            )
            self._schedule_store.record_fired(
                checkin.type_id, current_date
            )
            return

        if action.action == "defer":
            log.info(
                "Deferred %s: %s", checkin.type_id, action.reason
            )
            return

        # fire or modify — assemble context and inject prompt
        checkin_context = assemble_checkin_context(
            checkin.type_id,
            self._task_store,
            self._memory_store,
            current_date,
        )

        prompt_block = format_checkin_prompt(
            checkin.type_id, action, checkin_context
        )

        messages[0] = {
            **messages[0],
            "content": inject_checkin_into_prompt(
                messages[0]["content"], prompt_block
            ),
        }

        self._schedule_store.record_fired(checkin.type_id, current_date)
        log.info(
            "Fired %s (action=%s, state=%s)",
            checkin.type_id,
            action.action,
            cognitive_state,
        )

    def _drain_pending_queue(self, messages: list[dict[str, str]]) -> None:
        # Pulse-mode branch: the dispatcher has already evaluated state,
        # assembled context, and advanced ``last_run`` before enqueuing.
        # The hook's only responsibility here is prompt injection — one
        # pending check-in per heartbeat tick, matching the legacy "one
        # per tick" semantics.
        if self._pending_queue is None:
            return
        pending = self._pending_queue.drain_one()
        if pending is None:
            return
        messages[0] = {
            **messages[0],
            "content": inject_checkin_into_prompt(
                messages[0]["content"], pending.prompt_block,
            ),
        }
        log.info(
            "Fired %s (action=pulse-drain, fire_date=%s)",
            pending.checkin_type, pending.fire_date,
        )
