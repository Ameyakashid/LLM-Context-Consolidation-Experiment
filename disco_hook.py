"""Disco Elysium hook for nanobot-ai: inner voice commentary on responses.

Extends AgentHook directly (not via HookAdapter) because it uses
finalize_content() to transform the assistant's response -- a different
lifecycle method than the 5 existing before_iteration hooks.

When the cognitive state is avoidance/overwhelm/rsd and disco is enabled,
runs a 3-voice daisy chain via the disco engine and prepends formatted
commentary to the assistant's response.
"""

import asyncio
import concurrent.futures
import logging
from typing import Callable

from nanobot.agent.hook import AgentHook, AgentHookContext

from disco_config import DiscoConfig, should_activate_disco
from disco_engine import LLMCallable, format_disco_output, run_disco_chain
from state_detection import StateName

log = logging.getLogger(__name__)

DISCO_CHAIN_TIMEOUT_SECONDS = 15
DISCO_SEPARATOR = "\n\n"


# ---------------------------------------------------------------------------
# Pure functions
# ---------------------------------------------------------------------------

def extract_user_message(messages: list[dict[str, object]]) -> str:
    """Find the most recent user message in the conversation history."""
    for message in reversed(messages):
        if message.get("role") == "user":
            content = message.get("content", "")
            if isinstance(content, str) and content.strip():
                return content
    return ""


def extract_task_context(messages: list[dict[str, object]]) -> str:
    """Extract minimal task context from the system prompt.

    Returns the first 200 characters of any task-related content in the
    system prompt, or 'N/A' if no system prompt is found.
    """
    if not messages:
        return "N/A"
    first = messages[0]
    if first.get("role") != "system":
        return "N/A"
    content = first.get("content", "")
    if not isinstance(content, str):
        return "N/A"
    return "See system prompt" if content else "N/A"


# ---------------------------------------------------------------------------
# Hook
# ---------------------------------------------------------------------------

class DiscoHook(AgentHook):
    """Hook that prepends Disco Elysium inner voice commentary to responses.

    Uses finalize_content() (synchronous) to transform the assistant's
    response. The async disco chain runs in a worker thread with its own
    event loop to avoid blocking the main async loop.

    Constructor callables decouple the hook from runtime concerns:
    - get_cognitive_state: returns last-known StateName from StateResponseHook
    - on_comments: optional sink for fired comments (the Cabinet voice buffer).
      Called with the raw ``list[DiscoComment]`` whenever the chain fires;
      defaults to a no-op so chat behavior is unchanged.
    """

    def __init__(
        self,
        config: DiscoConfig,
        llm_call: LLMCallable,
        get_cognitive_state: Callable[[], StateName],
        on_comments: Callable[[list[object]], None] | None = None,
    ) -> None:
        self._config = config
        self._llm_call = llm_call
        self._get_cognitive_state = get_cognitive_state
        self._on_comments = on_comments

    def finalize_content(
        self,
        context: AgentHookContext,
        content: str | None,
    ) -> str | None:
        """Prepend disco commentary if activation conditions are met.

        Called synchronously by nanobot's CompositeHook pipeline after the
        LLM generates a response. Bridges to async via a thread pool.
        """
        if content is None:
            log.info("[disco] finalize_content called with content=None, skipping")
            return content

        state = self._get_cognitive_state()
        will_fire = should_activate_disco(state=state, intent=None, config=self._config)
        log.info("[disco] state=%s will_fire=%s activation_states=%s", state, will_fire, self._config.activation_states)

        if not will_fire:
            return content

        user_message = extract_user_message(context.messages)
        task_context = extract_task_context(context.messages)
        log.info("[disco] running chain for state=%s user_msg=%r", state, user_message[:80])

        try:
            comments = self._run_chain_sync(
                main_response=content,
                user_message=user_message,
                cognitive_state=state,
                task_context=task_context,
            )
        except Exception:
            log.exception("Disco chain failed; returning original content")
            return content

        log.info("[disco] chain returned %d comments", len(comments))
        if not comments:
            return content

        # Capture fired comments for the Cabinet voice buffer (chat unchanged).
        if self._on_comments is not None:
            try:
                self._on_comments(comments)
            except Exception:
                log.exception("[disco] on_comments sink failed (ignored)")

        disco_text = format_disco_output(comments, self._config)
        if not disco_text:
            log.info("[disco] format_disco_output returned empty, skipping")
            return content

        log.info("[disco] PREPENDING %d voice comments to response", len(comments))
        return disco_text + DISCO_SEPARATOR + content

    def _run_chain_sync(
        self,
        main_response: str,
        user_message: str,
        cognitive_state: str,
        task_context: str,
    ) -> list[object]:
        """Run the async disco chain synchronously via a worker thread.

        Creates a fresh event loop in the worker thread to avoid
        interfering with the main async loop.
        """
        config = self._config
        llm_call = self._llm_call

        def _worker() -> list[object]:
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(
                    run_disco_chain(
                        main_response=main_response,
                        user_message=user_message,
                        cognitive_state=cognitive_state,
                        task_context=task_context,
                        config=config,
                        llm_call=llm_call,
                    )
                )
            finally:
                loop.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_worker)
            return future.result(timeout=DISCO_CHAIN_TIMEOUT_SECONDS)
