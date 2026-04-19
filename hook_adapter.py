"""Adapters bridging our custom hooks to nanobot-ai's AgentHook interface.

Our 5 hooks use a custom HookContext Protocol and do not extend AgentHook.
Nanobot's AgentLoop expects list[AgentHook] in its hooks= parameter.
These thin adapters inherit from AgentHook and delegate before_iteration()
to the wrapped hook, passing AgentHookContext directly (it satisfies our
HookContext Protocol since it has a .messages list).
"""

import logging
from typing import Protocol

from nanobot.agent.hook import AgentHook, AgentHookContext

log = logging.getLogger(__name__)


class BeforeIterationHook(Protocol):
    """Protocol matching all 5 of our custom hooks."""

    async def before_iteration(self, context: object) -> None: ...


class HookAdapter(AgentHook):
    """Generic adapter wrapping any hook with a before_iteration method.

    Passes the AgentHookContext directly to the wrapped hook. This works
    because AgentHookContext.messages is a list[dict[str, Any]] which
    satisfies our HookContext Protocol at runtime.
    """

    def __init__(self, hook: BeforeIterationHook, name: str) -> None:
        self._hook = hook
        self._name = name

    @property
    def hook_name(self) -> str:
        return self._name

    @property
    def wrapped(self) -> BeforeIterationHook:
        """Access the wrapped hook for inspection in tests."""
        return self._hook

    async def before_iteration(self, context: AgentHookContext) -> None:
        """Delegate to the wrapped hook's before_iteration."""
        # Swallow per-hook failures so one broken hook cannot crash the agent loop.
        try:
            await self._hook.before_iteration(context)
        except Exception:
            log.exception("Hook %s.before_iteration failed", self._name)
