"""Pure helpers for the Dream State engine.

Four spec-named helpers (``gather_consolidation_context``,
``build_consolidation_prompt``, ``parse_consolidation_response``,
``sanitise_excerpt``) plus a cost estimator. All side-effect free on
their inputs: the gather helper only reads stores; the other three are
plain transforms.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dream_types import (
    CandidateInsight,
    DREAM_METADATA_SOURCE,
    DreamConsolidationOutput,
    DreamInputBundle,
    DreamParseError,
    MAX_COMPLETION_TOKENS,
    MAX_CONTENT_CHARS,
    MAX_INSIGHTS_PER_RUN,
    MAX_PROMPT_CHARS,
    PRICE_TABLE,
)
from memory_store import ALL_CATEGORIES, MemoryEntry, MemoryEntryStore
from task_store import TaskStoreProtocol

log = logging.getLogger(__name__)


def sanitise_excerpt(text: str) -> str:
    """Scrub long token-like runs, collapse whitespace, cap length.

    Coarse filter only — apparent API-key shapes (32+ alnum chars)
    collapse to ``[REDACTED]`` so obvious secrets do not reach the prompt.
    """
    cleaned = re.sub(r"[A-Za-z0-9_\-]{32,}", "[REDACTED]", text.strip())
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned[:800]


def _is_dream_generated(entry: MemoryEntry) -> bool:
    return entry.metadata.get("source") == DREAM_METADATA_SOURCE


def gather_consolidation_context(
    memory_store: MemoryEntryStore,
    task_store: TaskStoreProtocol,
    session_log_path: Path,
    clock: Callable[[], datetime],
    window_hours: int = 24,
) -> DreamInputBundle:
    """Pure read over all four input stores. No LLM, no writes."""
    now = clock()
    if now.tzinfo is None:
        raise ValueError(
            "gather_consolidation_context requires a tz-aware clock; "
            f"got naive {now!r}."
        )
    cutoff = now - timedelta(hours=window_hours)
    entries = memory_store.list_entries()
    recent, resolved, energy = _bucket_entries(entries, cutoff)
    tasks = [t for t in task_store.list_tasks() if t.updated_at >= cutoff]
    return DreamInputBundle(
        recent_memories=recent,
        resolved_memories=resolved,
        session_excerpts=_read_session_excerpts(session_log_path, cutoff),
        recent_tasks=tasks,
        current_energy_state=energy,
    )


def _bucket_entries(
    entries: list[MemoryEntry], cutoff: datetime,
) -> tuple[list[MemoryEntry], list[MemoryEntry], str | None]:
    recent = [
        e for e in entries
        if e.resolved_at is None and e.created_at >= cutoff
        and not _is_dream_generated(e)
    ]
    resolved = [
        e for e in entries
        if e.resolved_at is not None and e.resolved_at >= cutoff
    ]
    energy = next(
        (e.content for e in entries
         if e.resolved_at is None and e.category == "energy_state"),
        None,
    )
    return recent, resolved, energy


def _read_session_excerpts(path: Path, cutoff: datetime) -> list[str]:
    if not path.exists():
        return []
    out: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        parsed = _parse_session_line(line, cutoff)
        if parsed is not None:
            out.append(parsed)
    return out


def _parse_session_line(line: str, cutoff: datetime) -> str | None:
    stripped = line.strip()
    if not stripped:
        return None
    try:
        obj = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    ts = obj.get("timestamp")
    content = obj.get("content")
    if not isinstance(ts, str) or not isinstance(content, str):
        return None
    try:
        parsed_ts = datetime.fromisoformat(ts)
    except ValueError:
        return None
    if parsed_ts.tzinfo is None:
        parsed_ts = parsed_ts.replace(tzinfo=timezone.utc)
    if parsed_ts < cutoff:
        return None
    return sanitise_excerpt(content)


def _cap_excerpts(excerpts: list[str], char_budget: int) -> list[str]:
    out: list[str] = []
    running = 0
    for ex in reversed(excerpts):
        size = len(ex) + 2
        if running + size > char_budget:
            break
        out.append(ex)
        running += size
    out.reverse()
    return out


def build_consolidation_prompt(bundle: DreamInputBundle, template: str) -> str:
    """Render the DREAM.md template. Uses ``<<TOKEN>>`` substitution, not
    ``str.format``, so embedded JSON schema braces pass through untouched."""
    mem_lines = _format_entry_lines(bundle.recent_memories)
    resolved_lines = _format_entry_lines(bundle.resolved_memories)
    task_lines = "\n".join(
        f"- {t.title} [{t.status}]" for t in bundle.recent_tasks
    ) or "(none)"
    capped = _cap_excerpts(bundle.session_excerpts, MAX_PROMPT_CHARS // 2)
    excerpt_block = "\n\n".join(capped) or "(none)"
    rendered = (template
        .replace("<<RECENT_MEMORIES>>", mem_lines)
        .replace("<<RESOLVED_MEMORIES>>", resolved_lines)
        .replace("<<RECENT_TASKS>>", task_lines)
        .replace("<<SESSION_EXCERPTS>>", excerpt_block)
        .replace(
            "<<CURRENT_ENERGY_STATE>>",
            bundle.current_energy_state or "(unknown)",
        )
    )
    return rendered[:MAX_PROMPT_CHARS]


def _format_entry_lines(entries: list[MemoryEntry]) -> str:
    return "\n".join(
        f"- id={e.id[:8]} cat={e.category} :: {e.content}" for e in entries
    ) or "(none)"


def parse_consolidation_response(
    response_text: str,
    known_memory_ids: frozenset[str],
) -> DreamConsolidationOutput:
    """Parse the LLM JSON output, validate categories + content + ids."""
    raw_insights, raw_resolves = _decode_response(response_text)
    insights: list[CandidateInsight] = []
    dropped: list[tuple[str, str]] = []
    for raw in raw_insights[:MAX_INSIGHTS_PER_RUN]:
        outcome = _validate_insight(raw)
        if isinstance(outcome, CandidateInsight):
            insights.append(outcome)
        else:
            dropped.append(outcome)
    resolves = _validate_resolves(raw_resolves, known_memory_ids, dropped)
    return DreamConsolidationOutput(
        insights=insights, resolves=resolves, dropped=dropped,
    )


def _decode_response(response_text: str) -> tuple[list[object], list[object]]:
    try:
        data = json.loads(response_text)
    except json.JSONDecodeError as exc:
        raise DreamParseError(
            f"Dream response is not valid JSON ({exc}); "
            f"first 200 chars: {response_text[:200]!r}"
        ) from exc
    if not isinstance(data, dict):
        raise DreamParseError(
            f"Dream response root must be a JSON object; got {type(data).__name__}."
        )
    raw_insights = data.get("insights")
    raw_resolves = data.get("entries_to_resolve")
    if not isinstance(raw_insights, list) or not isinstance(raw_resolves, list):
        raise DreamParseError(
            "Dream response needs top-level 'insights' and 'entries_to_resolve' "
            f"lists; got keys {list(data.keys())}."
        )
    return raw_insights, raw_resolves


def _validate_insight(raw: object) -> CandidateInsight | tuple[str, str]:
    snippet = json.dumps(raw, default=str)[:120]
    if not isinstance(raw, dict):
        return (snippet, "not_an_object")
    category = raw.get("category")
    content = raw.get("content")
    metadata = raw.get("metadata") or {}
    supersedes = raw.get("supersedes_id") or ""
    if category not in ALL_CATEGORIES:
        log.warning("Dream dropped insight (unknown category %r)", category)
        return (snippet, "unknown_category")
    if not isinstance(content, str) or not content.strip():
        return (snippet, "empty_content")
    if len(content) > MAX_CONTENT_CHARS:
        log.warning(
            "Dream dropped insight (oversize content, %d chars)", len(content),
        )
        return (snippet, "oversize_content")
    if not isinstance(metadata, dict):
        return (snippet, "non_dict_metadata")
    return CandidateInsight(
        category=category,
        content=content.strip(),
        metadata={str(k): _stringify(v) for k, v in metadata.items()},
        supersedes_id=str(supersedes) if supersedes else "",
    )


def _validate_resolves(
    raw_resolves: list[object],
    known_ids: frozenset[str],
    dropped: list[tuple[str, str]],
) -> list[str]:
    out: list[str] = []
    for rid in raw_resolves:
        if not isinstance(rid, str):
            dropped.append((repr(rid)[:120], "non_string_resolve_id"))
            continue
        if rid not in known_ids:
            dropped.append((rid, "phantom_id"))
            continue
        out.append(rid)
    return out


def _stringify(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return str(value)
    return json.dumps(value, default=str)


def estimate_per_run_cost_usd(
    prompt_chars: int = MAX_PROMPT_CHARS,
    completion_tokens: int = MAX_COMPLETION_TOKENS,
    model_name: str = "x-ai/grok-4.1-fast",
) -> float:
    """Upper-bound cost for one Dream run at the pinned model's price.
    4-chars/token rule on the input side; completion side is exact."""
    if model_name not in PRICE_TABLE:
        raise ValueError(
            f"No price entry for model {model_name!r}; known: {sorted(PRICE_TABLE)}"
        )
    prices = PRICE_TABLE[model_name]
    prompt_tokens = prompt_chars // 4
    return (
        prompt_tokens * prices["input"] / 1_000_000
        + completion_tokens * prices["output"] / 1_000_000
    )


__all__ = [
    "build_consolidation_prompt", "estimate_per_run_cost_usd",
    "gather_consolidation_context", "parse_consolidation_response",
    "sanitise_excerpt",
]
