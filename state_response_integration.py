"""Nanobot-ai hook that connects cognitive state detection to response behavior.

On each message, detects the user's cognitive state via LLM classification
and injects a state indicator into the system prompt. SOUL.md contains
per-state response rules that the LLM applies based on this indicator.
"""

import logging
from pathlib import Path
from typing import Callable

from hook_context import HookContext
from state_detection import (
    DetectionResult,
    LLMCallable,
    StateConfig,
    StateName,
    detect_state,
)

StateWriterFn = Callable[[Path, str, str, bool], object]

log = logging.getLogger(__name__)

STATE_INDICATOR_PREFIX = "[Current cognitive state: "
STATE_INDICATOR_SUFFIX = "]"

BASELINE_STATE: StateName = "baseline"


def build_state_indicator(state_name: str) -> str:
    """Build the state indicator string injected into the system prompt."""
    return f"{STATE_INDICATOR_PREFIX}{state_name}{STATE_INDICATOR_SUFFIX}"


def extract_latest_user_message(messages: list[dict[str, str]]) -> str | None:
    """Find the most recent user message in the conversation history."""
    for message in reversed(messages):
        if message.get("role") == "user":
            content = message.get("content", "")
            if content.strip():
                return content
    return None


def inject_state_into_prompt(
    system_content: str, state_name: str
) -> str:
    """Inject or replace the state indicator in the system prompt.

    Places the indicator on the line after '## State-Aware Adaptation'.
    If an existing indicator is present, replaces it.
    """
    indicator = build_state_indicator(state_name)
    section_heading = "## State-Aware Adaptation"

    # Remove any existing indicator
    lines = system_content.split("\n")
    cleaned_lines: list[str] = [
        line for line in lines
        if not line.strip().startswith(STATE_INDICATOR_PREFIX)
    ]

    # Find the section heading and insert indicator after it
    result_lines: list[str] = []
    inserted = False
    for line in cleaned_lines:
        result_lines.append(line)
        if not inserted and line.strip() == section_heading:
            result_lines.append("")
            result_lines.append(indicator)
            inserted = True

    if not inserted:
        # Section heading not found — append at end as fallback
        result_lines.append("")
        result_lines.append(indicator)

    return "\n".join(result_lines)


class StateResponseHook:
    """Hook that detects cognitive state and injects it into the system prompt.

    Designed for nanobot-ai's AgentHook lifecycle. Call before_iteration()
    before each LLM call to update the system prompt with the current state.

    State persists in-memory across messages. Resets to baseline on restart.
    """

    def __init__(
        self,
        config: StateConfig,
        llm_call: LLMCallable,
        state_writer: StateWriterFn | None = None,
        state_file_path: Path | None = None,
    ) -> None:
        self._config = config
        self._llm_call = llm_call
        self._state_writer = state_writer
        self._state_file_path = state_file_path
        self._current_state: StateName = BASELINE_STATE

    @property
    def current_state(self) -> StateName:
        return self._current_state

    async def before_iteration(self, context: HookContext) -> None:
        """Detect state from the latest user message, inject into system prompt."""
        messages = context.messages
        if not messages:
            return

        user_message = extract_latest_user_message(messages)
        if user_message is None:
            return

        detection = await self._detect_with_fallback(user_message)
        self._current_state = detection.detected_state

        if self._state_writer is not None and self._state_file_path is not None:
            self._state_writer(
                self._state_file_path,
                detection.detected_state,
                detection.previous_state,
                detection.is_transition_blocked,
            )

        # System prompt is always messages[0]
        if messages[0].get("role") == "system":
            messages[0] = {
                **messages[0],
                "content": inject_state_into_prompt(
                    messages[0]["content"], self._current_state
                ),
            }

    async def _detect_with_fallback(
        self, message: str
    ) -> DetectionResult:
        """Run state detection, falling back to baseline on any error."""
        try:
            return await detect_state(
                message, self._current_state, self._config, self._llm_call
            )
        except Exception as exc:
            log.warning(
                "State detection failed, falling back to %s: %s",
                BASELINE_STATE,
                exc,
            )
            return DetectionResult(
                previous_state=self._current_state,
                detected_state=BASELINE_STATE,
                is_transition_blocked=False,
            )
