"""Locks the ``## Voice Input`` section added to SOUL.md in Task 19/sub-03.

The section teaches the LLM how to read the markers emitted by sub-02:
``[transcription: ...]``, ``(low confidence) ``,
``failed to process voice message`` and ``voice too long \u2014 limit``.
The tests below guard:

* heading position between ``## Fire Tablet Display`` and ``## Calendar``
* the six required ``### `` subheadings, in declared order
* every marker substring (em-dash sensitivity included)
* a soft line-count cap on the section body
* the project-wide banned-phrase roots
* every pre-existing ``## `` section's first three non-blank body lines
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SOUL_PATH = REPO_ROOT / "workspace" / "SOUL.md"

VOICE_INPUT_HEADING = "## Voice Input"
ANCHOR_BEFORE = "## Fire Tablet Display"
ANCHOR_AFTER = "## Calendar"

REQUIRED_SUBHEADINGS: tuple[str, ...] = (
    "### How Voice Input Arrives",
    "### When Transcription Is Low Confidence",
    "### ADHD Speech Is Valid",
    "### Voice + Tasks / Memory / Buffers",
    "### When Transcription Fails",
    "### When Voice Is Too Long",
)

REQUIRED_MARKERS: tuple[str, ...] = (
    "[transcription:",
    "(low confidence) ",
    "failed to process voice message",
    "voice too long \u2014 limit",
)

BANNED_ROOTS: tuple[str, ...] = (
    "you should",
    "just do it",
    "just focus",
    "it's easy",
    "it's simple",
    "why didn't you",
    "why can't you",
    "you forgot again",
    "try harder",
    "I already told you",
    "all you have to do",
)

MAX_SECTION_LINES = 65

# First three non-blank body lines per pre-existing ``## `` section, snapshotted
# at the start of sub-03. Drift here means a future task accidentally rewrote
# a body that sub-03 was supposed to leave alone. If the change was intentional,
# update the tuple with intent.
PRESERVED_SECTION_FIRST_LINES: dict[str, tuple[str, str, str]] = {
    "## Voice and Tone": (
        "- Direct and concise \u2014 no walls of text",
        "- Warm but not patronizing \u2014 treat the user as a capable adult who sometimes needs structure",
        "- Collaborative \u2014 use \"we/let's\" framing, not directives",
    ),
    "## Neuroaffirming Rules": (
        "### Never Say These",
        "The following patterns are banned. They trigger shame and guilt in ADHD brains. Do not use them or any close variation:",
        "- \"you should have\" / \"you should\"",
    ),
    "## ICNU Motivation Framework": (
        "When the user is stuck, avoidant, or struggling to initiate, use the ICNU channels to help unlock motivation. Pick the channel most likely to work based on context \u2014 do not apply all four at once.",
        "1. **Interest** \u2014 Connect the task to something the user genuinely cares about. \"This gets you closer to X.\"",
        "2. **Challenge** \u2014 Frame it as a game, puzzle, or competition with self. \"Can you knock this out in 15 minutes?\"",
    ),
    "## Communication Style": (
        "- Default to short messages (1-3 sentences)",
        "- Use bullet points for lists of 3+ items",
        "- Ask one question at a time, never multiple",
    ),
    "## Boundaries": (
        "- You manage tasks and scheduling, not therapy",
        "- If the user expresses distress beyond task management, acknowledge it and suggest professional support",
        "- You don't make decisions for the user \u2014 you present options and help them choose",
    ),
    "## Task Management": (
        "### When to Offer Task Creation",
        "- When the user mentions something they need to do, offer to capture it as a task",
        "- Do not create tasks silently \u2014 confirm with the user first",
    ),
    "## State-Aware Adaptation": (
        "The integration layer detects the user's cognitive state each message and injects a `[Current cognitive state: STATE_NAME]` marker into this prompt. Apply the matching rules below. The base personality above remains the foundation \u2014 state adaptations modify intensity and approach, not identity.",
        "### Baseline",
        "- Use the standard voice and tone defined above",
    ),
    "## Memory": (
        "The memory system lets you persist important information across conversations. You have three tools:",
        "- **save_memory** \u2014 Store a structured entry in one of five categories",
        "- **list_memories** \u2014 View active memory entries (optionally filtered by category)",
    ),
    "## Buffer System": (
        "Buffers track pre-loaded units of recurring obligations (rent, medication, subscriptions). They are a safety net \u2014 not a countdown. Always frame buffers as \"banked ahead\" rather than \"running out.\"",
        "### When to Mention Buffers",
        "- When a buffer drops to or below its alert threshold, mention it as a refill opportunity: \"Good time to top up [buffer name] \u2014 you have [N] left\"",
    ),
    "## Scheduled Check-Ins": (
        "The scheduling engine triggers proactive messages at configured times. Each check-in type has a specific purpose and tone. State-Aware Adaptation rules above still apply \u2014 the scheduling engine may modify, defer, or suppress check-ins based on the detected state.",
        "### Morning Motivation (08:00)",
        "- Open with a Volition quote or a brief reframe \u2014 remind the user they chose this",
    ),
    "## Voice Output": (
        "The speak tool lets you send voice messages via TTS. Voice is a supplement \u2014 text responses still appear alongside voice.",
        "### When to Use the Speak Tool",
        "- When the user explicitly asks (\"say that\", \"read it aloud\", \"voice message\")",
    ),
    "## Dashboard": (
        "A status dashboard runs alongside you on a Fire Tablet or browser. It shows the user's cognitive state, buffer levels, active tasks, check-in schedule, and recent activity. It auto-refreshes \u2014 the user does not need to interact with it.",
        "- You may reference the dashboard when relevant: \"Check your dashboard \u2014 your buffer levels are all green\"",
        "- Do not instruct the user to refresh the dashboard; it updates automatically",
    ),
    "## Fire Tablet Display": (
        "A second, glanceable surface runs on a Fire Tablet pointed at the MagicMirror\u00b2 server. It has three swipe pages \u2014 **Tasks**, **State + Buffers**, **Schedule** \u2014 plus toast alerts for state changes, buffer thresholds, and missed check-ins. The user does not interact with it; it is read-only by design.",
        "- You may mention it when a visual glance would help: \"Your buffer levels are on the mirror if you want a quick look\"",
        "- Do not tell the user to refresh the mirror \u2014 it auto-updates each heartbeat",
    ),
    "## Task Ledger": (
        "Your task store may be backed by Taskwarrior (the canonical ledger when `TASKWARRIOR_ENABLED=true`) or by a legacy JSON file (the fallback when the flag is off). Behaviour is identical from your perspective.",
        "- The `create_task`, `list_tasks`, `get_task`, `update_task`, and `complete_task` tools work the same way either way. Do not adjust how you call them based on which backend is active.",
        "- Do not surface the backend switch to the user unless they ask. The ledger is an implementation detail.",
    ),
    "## Pulse + Dream": (
        "Two background systems may be running depending on flags. You do not need to surface their mode to the user unless asked.",
        "- A \"Pulse-mode\" check-in is identical to a legacy check-in from your perspective. The same prompt block arrives under the same system heading; you answer it the same way. Do not reference \"Pulse\" unless the user asks.",
        "- `memory_store` rows with `metadata.source == \"dream_state\"` are summaries you wrote overnight during Dream State. Weight them the same as user-created memories, but do not fabricate provenance \u2014 say \"I summarised\" rather than \"I remembered\" if the distinction matters.",
    ),
    "## Calendar": (
        "You have three read-only calendar tools backed by the user's Google Calendar. You cannot create, move, or cancel events from these tools \u2014 the write-capable upstream tools are deliberately hidden.",
        "### Calendar Tools",
        "- **get_upcoming_events** \u2014 List events in the next N hours on the primary calendar. Default window: 12 hours. Use for \"what's next?\" questions",
    ),
    "## Disco Flavor Layer": (
        "A separate system sometimes prepends inner voice commentary before your main response. These voices are inspired by Disco Elysium -- they represent different cognitive aspects (Volition, Empathy, Logic, Inland Empire) that react to what the user said and what you responded.",
        "### What You Need to Know",
        "- The inner voice comments appear BEFORE your response in the final message sent to the user. They are formatted as italic lines with a skill check (e.g., *VOLITION [Medium: Success] -- \"comment\"*).",
    ),
}


def _read_soul() -> str:
    return SOUL_PATH.read_text(encoding="utf-8")


def _h2_headings(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith("## ")]


def _section_body(text: str, heading: str) -> str:
    lines = text.splitlines()
    try:
        start = lines.index(heading) + 1
    except ValueError as exc:
        raise AssertionError(
            f"SOUL.md missing required heading {heading!r}; "
            "Task 19/sub-03 must not delete pre-existing sections"
        ) from exc
    end = len(lines)
    for index in range(start, len(lines)):
        if lines[index].startswith("## "):
            end = index
            break
    return "\n".join(lines[start:end])


def _voice_input_body() -> str:
    return _section_body(_read_soul(), VOICE_INPUT_HEADING)


def _first_n_non_blank(body: str, count: int) -> tuple[str, ...]:
    non_blank = [line for line in body.splitlines() if line.strip()]
    return tuple(non_blank[:count])


class TestVoiceInputHeadingPresence:
    def test_heading_appears_exactly_once(self) -> None:
        assert _h2_headings(_read_soul()).count(VOICE_INPUT_HEADING) == 1

    def test_heading_positioned_between_anchors(self) -> None:
        headings = _h2_headings(_read_soul())
        before = headings.index(ANCHOR_BEFORE)
        voice = headings.index(VOICE_INPUT_HEADING)
        after = headings.index(ANCHOR_AFTER)
        assert before < voice < after


class TestVoiceInputSubheadings:
    @pytest.mark.parametrize("subheading", REQUIRED_SUBHEADINGS)
    def test_subheading_present(self, subheading: str) -> None:
        body = _voice_input_body()
        assert subheading in body, (
            f"Voice Input section missing subheading {subheading!r}"
        )

    def test_subheadings_appear_in_declared_order(self) -> None:
        body = _voice_input_body()
        positions = [body.index(sub) for sub in REQUIRED_SUBHEADINGS]
        assert positions == sorted(positions), (
            "Voice Input subheadings are out of order; sub-03 description "
            "mandates the declared sequence"
        )


class TestVoiceInputMarkers:
    @pytest.mark.parametrize("marker", REQUIRED_MARKERS)
    def test_marker_present_in_section(self, marker: str) -> None:
        body = _voice_input_body()
        assert marker in body, (
            f"Voice Input section missing marker {marker!r}; "
            "verify em-dashes are U+2014 and trailing spaces are intact"
        )

    def test_over_duration_marker_uses_em_dash(self) -> None:
        body = _voice_input_body()
        assert "voice too long \u2014 limit" in body
        assert "voice too long - limit" not in body
        assert "voice too long \u2013 limit" not in body


class TestVoiceInputBodyShape:
    def test_section_body_under_line_cap(self) -> None:
        body = _voice_input_body()
        line_count = len(body.splitlines())
        assert line_count <= MAX_SECTION_LINES, (
            f"Voice Input section body is {line_count} lines; "
            f"cap is {MAX_SECTION_LINES} (description AC #4)"
        )

    def test_section_starts_with_tldr_paragraph(self) -> None:
        body = _voice_input_body()
        non_blank = [line for line in body.splitlines() if line.strip()]
        assert non_blank, "Voice Input section body is empty"
        first = non_blank[0]
        assert "[transcription:" in first, (
            "Voice Input section's first non-blank line should be the TL;DR "
            "introducing the [transcription: ...] wrapper"
        )


class TestVoiceInputBannedPhrases:
    @pytest.mark.parametrize("phrase", BANNED_ROOTS)
    def test_section_avoids_banned_phrase(self, phrase: str) -> None:
        body = _voice_input_body().lower()
        assert phrase.lower() not in body, (
            f"Voice Input section contains banned phrase {phrase!r}; "
            "rewrite using neuroaffirming alternatives"
        )


class TestPreservedSections:
    @pytest.mark.parametrize(
        "heading", sorted(PRESERVED_SECTION_FIRST_LINES.keys()),
    )
    def test_first_three_body_lines_unchanged(self, heading: str) -> None:
        body = _section_body(_read_soul(), heading)
        first_three = _first_n_non_blank(body, 3)
        expected = PRESERVED_SECTION_FIRST_LINES[heading]
        assert first_three == expected, (
            f"Section {heading!r} drifted from sub-03 baseline. "
            "If the rewrite is intentional, update the snapshot."
        )
