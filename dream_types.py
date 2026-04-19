"""Types + constants for the Dream State engine.

Split out from ``dream_engine.py`` + ``dream_helpers.py`` so both consumers
stay under the 300-line cap (``_build/code-rules.md`` §Structure). The
pinned-model price table is here so the cost test can assert against it
without having to import the engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from memory_store import MemoryCategory, MemoryEntry
from task_store import Task

MAX_PROMPT_CHARS: int = 6000
MAX_COMPLETION_TOKENS: int = 800
MAX_CONTENT_CHARS: int = 200
MAX_INSIGHTS_PER_RUN: int = 10
DREAM_METADATA_SOURCE: str = "dream_state"

PRICE_TABLE: dict[str, dict[str, float]] = {
    "x-ai/grok-4.1-fast": {"input": 0.20, "output": 0.50},
    "openai/gpt-oss-120b": {"input": 0.04, "output": 0.04},
}


class DreamState(str, Enum):
    """Dream sub-state machine. Ported from TEMM1E ``ConscienceState::Dream``."""

    IDLE = "idle"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


class DreamParseError(ValueError):
    """Raised when the LLM response is not usable consolidation output."""


@dataclass(frozen=True)
class DreamInputBundle:
    recent_memories: list[MemoryEntry]
    resolved_memories: list[MemoryEntry]
    session_excerpts: list[str]
    recent_tasks: list[Task]
    current_energy_state: str | None


@dataclass(frozen=True)
class CandidateInsight:
    category: MemoryCategory
    content: str
    metadata: dict[str, str]
    supersedes_id: str


@dataclass(frozen=True)
class DreamConsolidationOutput:
    insights: list[CandidateInsight]
    resolves: list[str]
    dropped: list[tuple[str, str]]


@dataclass(frozen=True)
class DreamRunResult:
    entries_created: int
    entries_resolved: int
    prompt_tokens_est: int
    completion_tokens: int
    state: DreamState
    error: str | None


__all__ = [
    "CandidateInsight",
    "DREAM_METADATA_SOURCE",
    "DreamConsolidationOutput",
    "DreamInputBundle",
    "DreamParseError",
    "DreamRunResult",
    "DreamState",
    "MAX_COMPLETION_TOKENS",
    "MAX_CONTENT_CHARS",
    "MAX_INSIGHTS_PER_RUN",
    "MAX_PROMPT_CHARS",
    "PRICE_TABLE",
]
