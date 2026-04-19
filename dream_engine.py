"""Dream State engine — orchestrator for one consolidation run.

Sits on top of the pure helpers in ``dream_helpers``. A fresh
:class:`DreamEngine` moves through ``IDLE → RUNNING → {COMPLETE, FAILED}``
exactly once per :meth:`run` call. The engine is inert until sub-05 wires
it into the Pulse concern pipeline — nothing in ``run_gateway`` or
``custom_gateway`` instantiates it today.

The 5-category write surface (``commitment`` / ``deadline`` / ``blocker`` /
``energy_state`` / ``context_switch``) is enforced in
:func:`dream_helpers.parse_consolidation_response`; this module just
drives the phases and applies the validated output to
:class:`MemoryEntryStore`.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path

from dream_helpers import (
    build_consolidation_prompt,
    estimate_per_run_cost_usd,
    gather_consolidation_context,
    parse_consolidation_response,
    sanitise_excerpt,
)
from dream_types import (
    CandidateInsight,
    DREAM_METADATA_SOURCE,
    DreamConsolidationOutput,
    DreamInputBundle,
    DreamParseError,
    DreamRunResult,
    DreamState,
    MAX_COMPLETION_TOKENS,
    MAX_CONTENT_CHARS,
    MAX_INSIGHTS_PER_RUN,
    MAX_PROMPT_CHARS,
    PRICE_TABLE,
)
from memory_store import MemoryEntryStore
from task_store import TaskStoreProtocol

log = logging.getLogger(__name__)


class DreamEngine:
    """Stateful orchestrator for one Dream run at a time.

    Constructor is keyword-only so sub-05's eventual wiring (nine injected
    dependencies) reads self-documentingly. The engine does not reset
    itself after :meth:`run` — sub-05 either instantiates a fresh engine
    per Pulse tick or calls :meth:`reset_state` explicitly.
    """

    estimated_cost_per_run_usd: float = 0.01

    def __init__(
        self,
        *,
        memory_store: MemoryEntryStore,
        task_store: TaskStoreProtocol,
        session_log_path: Path,
        llm_caller: Callable[[str, int], Awaitable[str]],
        clock: Callable[[], datetime],
        prompt_template: str,
        window_hours: int = 24,
        max_cost_usd_per_run: float = 0.01,
        model_name: str = "x-ai/grok-4.1-fast",
    ) -> None:
        _probe_clock(clock)
        self._memory_store = memory_store
        self._task_store = task_store
        self._session_log_path = session_log_path
        self._llm_caller = llm_caller
        self._clock = clock
        self._template = prompt_template
        self._window_hours = window_hours
        self._max_cost = max_cost_usd_per_run
        self._model = model_name
        self._state: DreamState = DreamState.IDLE

    def get_state(self) -> DreamState:
        return self._state

    def reset_state(self) -> None:
        """Return to IDLE so a used engine can be driven again."""
        self._state = DreamState.IDLE

    async def run(self) -> DreamRunResult:
        if self._state != DreamState.IDLE:
            raise RuntimeError(
                f"DreamEngine.run() requires state=IDLE, got {self._state.value}. "
                "Call reset_state() or construct a fresh engine."
            )
        self._state = DreamState.RUNNING
        prompt = ""
        response = ""
        try:
            bundle = gather_consolidation_context(
                self._memory_store, self._task_store,
                self._session_log_path, self._clock, self._window_hours,
            )
            prompt = build_consolidation_prompt(bundle, self._template)
            response = await self._llm_caller(prompt, MAX_COMPLETION_TOKENS)
            known_ids = frozenset(e.id for e in self._memory_store.list_entries())
            output = parse_consolidation_response(response, known_ids)
            created, resolved = self._apply(output)
        except Exception as exc:
            self._state = DreamState.FAILED
            log.warning("Dream run failed: %s: %s", type(exc).__name__, exc)
            return DreamRunResult(
                entries_created=0, entries_resolved=0,
                prompt_tokens_est=len(prompt) // 4,
                completion_tokens=len(response) // 4,
                state=self._state,
                error=f"{type(exc).__name__}: {exc}",
            )
        self._state = DreamState.COMPLETE
        log.info(
            "Dream run complete: created=%d resolved=%d prompt~=%d completion~=%d",
            created, resolved, len(prompt) // 4, len(response) // 4,
        )
        return DreamRunResult(
            entries_created=created, entries_resolved=resolved,
            prompt_tokens_est=len(prompt) // 4,
            completion_tokens=len(response) // 4,
            state=self._state, error=None,
        )

    def _apply(self, output: DreamConsolidationOutput) -> tuple[int, int]:
        """Write insights + resolves to the memory store, idempotently.

        Dedup key is ``(category, content)`` across current active entries —
        calling ``_apply`` twice in a row inserts each row only once.
        """
        run_at = self._clock().isoformat()
        active = self._memory_store.list_active_entries()
        existing_keys: set[tuple[str, str]] = {
            (e.category, e.content) for e in active
        }
        created = 0
        for insight in output.insights:
            key = (insight.category, insight.content)
            if key in existing_keys:
                continue
            metadata = dict(insight.metadata)
            metadata["source"] = DREAM_METADATA_SOURCE
            metadata["run_at"] = run_at
            metadata["supersedes"] = insight.supersedes_id
            self._memory_store.create_entry(insight.category, insight.content, metadata)
            existing_keys.add(key)
            created += 1
        resolved = 0
        for rid in output.resolves:
            try:
                self._memory_store.resolve_entry(rid)
                resolved += 1
            except KeyError:
                log.warning("Dream resolve skipped; id not in store: %s", rid)
        return created, resolved


def _probe_clock(clock: Callable[[], datetime]) -> None:
    probe = clock()
    if probe.tzinfo is None:
        raise ValueError(
            "DreamEngine clock must return tz-aware datetimes; "
            f"got naive {probe!r}. Use datetime.now(timezone.utc)."
        )


__all__ = [
    "CandidateInsight",
    "DREAM_METADATA_SOURCE",
    "DreamConsolidationOutput",
    "DreamEngine",
    "DreamInputBundle",
    "DreamParseError",
    "DreamRunResult",
    "DreamState",
    "MAX_COMPLETION_TOKENS",
    "MAX_CONTENT_CHARS",
    "MAX_INSIGHTS_PER_RUN",
    "MAX_PROMPT_CHARS",
    "PRICE_TABLE",
    "build_consolidation_prompt",
    "estimate_per_run_cost_usd",
    "gather_consolidation_context",
    "parse_consolidation_response",
    "sanitise_excerpt",
]
