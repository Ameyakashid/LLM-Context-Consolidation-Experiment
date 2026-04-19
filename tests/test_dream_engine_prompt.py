"""Prompt-building tests for the Dream engine."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from dream_helpers import build_consolidation_prompt, sanitise_excerpt
from dream_types import MAX_PROMPT_CHARS, DreamInputBundle
from memory_store import MemoryEntry

FIXED_NOW = datetime(2026, 4, 20, 3, 0, tzinfo=timezone.utc)

REPO_ROOT = Path(__file__).resolve().parent.parent
DREAM_TEMPLATE = (REPO_ROOT / "workspace" / "templates" / "DREAM.md").read_text(
    encoding="utf-8",
)


def _entry(category: str, content: str, *, entry_id: str = "abc12345") -> MemoryEntry:
    return MemoryEntry(
        id=entry_id,
        category=category,  # type: ignore[arg-type]
        content=content,
        created_at=FIXED_NOW,
        metadata={},
    )


def _empty_bundle() -> DreamInputBundle:
    return DreamInputBundle(
        recent_memories=[],
        resolved_memories=[],
        session_excerpts=[],
        recent_tasks=[],
        current_energy_state=None,
    )


class TestTemplateTokensReplaced:
    def test_all_tokens_removed(self) -> None:
        prompt = build_consolidation_prompt(_empty_bundle(), DREAM_TEMPLATE)
        for token in (
            "<<RECENT_MEMORIES>>", "<<RESOLVED_MEMORIES>>", "<<RECENT_TASKS>>",
            "<<SESSION_EXCERPTS>>", "<<CURRENT_ENERGY_STATE>>",
        ):
            assert token not in prompt, f"{token} still present after render"

    def test_empty_bundle_shows_none_markers(self) -> None:
        prompt = build_consolidation_prompt(_empty_bundle(), DREAM_TEMPLATE)
        assert "(none)" in prompt
        assert "(unknown)" in prompt


class TestTemplateFiveCategories:
    def test_all_five_categories_named(self) -> None:
        prompt = build_consolidation_prompt(_empty_bundle(), DREAM_TEMPLATE)
        for category in (
            "commitment", "deadline", "blocker", "energy_state", "context_switch",
        ):
            assert category in prompt, f"{category} missing from prompt"

    def test_no_sixth_category_invented(self) -> None:
        prompt = build_consolidation_prompt(_empty_bundle(), DREAM_TEMPLATE)
        assert "priority" not in prompt
        assert "reminder" not in prompt


class TestTemplateBannedPhrases:
    def test_you_should_listed_as_banned(self) -> None:
        prompt = build_consolidation_prompt(_empty_bundle(), DREAM_TEMPLATE)
        assert "you should" in prompt.lower()

    def test_just_do_it_listed_as_banned(self) -> None:
        prompt = build_consolidation_prompt(_empty_bundle(), DREAM_TEMPLATE)
        assert "just do it" in prompt.lower()

    def test_try_harder_listed_as_banned(self) -> None:
        prompt = build_consolidation_prompt(_empty_bundle(), DREAM_TEMPLATE)
        assert "try harder" in prompt.lower()


class TestPromptRendersBundle:
    def test_recent_memories_injected(self) -> None:
        bundle = DreamInputBundle(
            recent_memories=[_entry("commitment", "write dream tests")],
            resolved_memories=[],
            session_excerpts=[],
            recent_tasks=[],
            current_energy_state=None,
        )
        prompt = build_consolidation_prompt(bundle, DREAM_TEMPLATE)
        assert "write dream tests" in prompt

    def test_energy_state_injected(self) -> None:
        bundle = DreamInputBundle(
            recent_memories=[],
            resolved_memories=[],
            session_excerpts=[],
            recent_tasks=[],
            current_energy_state="burnt out",
        )
        prompt = build_consolidation_prompt(bundle, DREAM_TEMPLATE)
        assert "burnt out" in prompt

    def test_session_excerpts_injected(self) -> None:
        bundle = DreamInputBundle(
            recent_memories=[],
            resolved_memories=[],
            session_excerpts=["chat about focus music"],
            recent_tasks=[],
            current_energy_state=None,
        )
        prompt = build_consolidation_prompt(bundle, DREAM_TEMPLATE)
        assert "chat about focus music" in prompt


class TestPromptSizeCap:
    def test_prompt_never_exceeds_max_chars(self) -> None:
        huge_excerpts = ["filler " * 200] * 200
        bundle = DreamInputBundle(
            recent_memories=[],
            resolved_memories=[],
            session_excerpts=huge_excerpts,
            recent_tasks=[],
            current_energy_state=None,
        )
        prompt = build_consolidation_prompt(bundle, DREAM_TEMPLATE)
        assert len(prompt) <= MAX_PROMPT_CHARS


class TestSanitiseExcerpt:
    def test_long_token_redacted(self) -> None:
        secret = "A" * 40
        cleaned = sanitise_excerpt(f"api key {secret} oops")
        assert "[REDACTED]" in cleaned
        assert secret not in cleaned

    def test_short_strings_pass_through(self) -> None:
        assert sanitise_excerpt("hello world") == "hello world"

    def test_whitespace_trimmed(self) -> None:
        assert sanitise_excerpt("  padded  ") == "padded"

    def test_length_capped_at_800(self) -> None:
        # Short words separated so the token-run regex doesn't collapse
        # the whole string into a single `[REDACTED]` span.
        out = sanitise_excerpt(("hi there " * 500).strip())
        assert len(out) == 800

    def test_excessive_newlines_collapsed(self) -> None:
        out = sanitise_excerpt("a\n\n\n\n\nb")
        assert "\n\n\n" not in out
