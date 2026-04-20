"""Locks the ``## Voice-Originated Inputs`` note added to HEARTBEAT.md in sub-03.

The note documents that voice transcripts are wrapped as ``[transcription: ...]``
before heartbeat hooks (state, memory, scheduling) run, and that
``VOICE_AUTO_ENABLED`` (Task 07) is orthogonal to voice INPUT.
The tests below guard:

* presence and ordering of the new ``## `` heading at the file end
* required substrings inside the new section
* a soft line-count cap
* every pre-existing ``## `` section's first three non-blank body lines
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HEARTBEAT_PATH = REPO_ROOT / "workspace" / "HEARTBEAT.md"

VOICE_INPUTS_HEADING = "## Voice-Originated Inputs"

REQUIRED_MARKERS: tuple[str, ...] = (
    "[transcription:",
    "VOICE_AUTO_ENABLED",
)

MAX_SECTION_LINES = 18

PRESERVED_SECTION_FIRST_LINES: dict[str, tuple[str, str, str]] = {
    "## Morning Motivation": (
        "- Time: 08:00",
        "- Purpose: Emotional warm-up \u2014 Volition quote, ICNU framing",
        "- Does not reference tasks",
    ),
    "## Morning Plan": (
        "- Time: 09:00",
        "- Purpose: Identify the day's top priority",
        "- Shows top 1-3 pending tasks and nearest deadline",
    ),
    "## Afternoon Check": (
        "- Time: 14:00",
        "- Purpose: Mid-day energy and progress check",
        "- Shows in-progress tasks and energy context",
    ),
    "## Evening Review": (
        "- Time: 20:00",
        "- Purpose: Celebrate completions, flag overdue, offer closure",
        "- Shows completed and overdue tasks",
    ),
    "## Morning Check-Ins See Today's Calendar": (
        "- Purpose: Inject today's events under `### Today's Calendar` in the system prompt during morning check-ins",
        "- Fires only for `morning_motivation` and `morning_plan`; other check-ins skip the injection",
        "- Controlled by the `GOOGLE_CALENDAR_ENABLED` env var \u2014 when disabled the hook does not run at all",
    ),
    "## Buffer Monitoring": (
        "- Purpose: Auto-decrement buffers on due dates, surface low-level alerts",
        "- Fires alongside check-ins during heartbeat cycles",
        "- Does not send a separate message \u2014 injects alerts into the active system prompt",
    ),
    "## Voice Output": (
        "- Purpose: Auto-voice check-ins and buffer alerts during heartbeat sessions",
        "- Controlled by `VOICE_AUTO_ENABLED` env var (set to `true` to enable)",
        "- When enabled, the voice hook injects a `## Voice Delivery` block into the system prompt",
    ),
}


def _read_heartbeat() -> str:
    return HEARTBEAT_PATH.read_text(encoding="utf-8")


def _h2_headings(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith("## ")]


def _section_body(text: str, heading: str) -> str:
    lines = text.splitlines()
    try:
        start = lines.index(heading) + 1
    except ValueError as exc:
        raise AssertionError(
            f"HEARTBEAT.md missing required heading {heading!r}; "
            "Task 19/sub-03 must not delete pre-existing sections"
        ) from exc
    end = len(lines)
    for index in range(start, len(lines)):
        if lines[index].startswith("## "):
            end = index
            break
    return "\n".join(lines[start:end])


def _voice_inputs_body() -> str:
    return _section_body(_read_heartbeat(), VOICE_INPUTS_HEADING)


def _first_n_non_blank(body: str, count: int) -> tuple[str, ...]:
    non_blank = [line for line in body.splitlines() if line.strip()]
    return tuple(non_blank[:count])


class TestVoiceInputsHeadingPresence:
    def test_heading_appears_exactly_once(self) -> None:
        assert _h2_headings(_read_heartbeat()).count(VOICE_INPUTS_HEADING) == 1

    def test_heading_is_last_section(self) -> None:
        headings = _h2_headings(_read_heartbeat())
        assert headings[-1] == VOICE_INPUTS_HEADING, (
            "## Voice-Originated Inputs should be appended as the final "
            "heartbeat section so existing sections retain their positions"
        )


class TestVoiceInputsMarkers:
    @pytest.mark.parametrize("marker", REQUIRED_MARKERS)
    def test_marker_present_in_section(self, marker: str) -> None:
        body = _voice_inputs_body()
        assert marker in body, (
            f"Voice-Originated Inputs section missing marker {marker!r}; "
            "description AC #5 requires both [transcription: and VOICE_AUTO_ENABLED"
        )

    def test_explicit_orthogonality_with_voice_auto_enabled(self) -> None:
        body = _voice_inputs_body().lower()
        assert "orthogonal" in body, (
            "Voice-Originated Inputs section must call out that "
            "VOICE_AUTO_ENABLED is orthogonal to voice INPUT"
        )


class TestVoiceInputsBodyShape:
    def test_section_body_under_line_cap(self) -> None:
        body = _voice_inputs_body()
        line_count = len(body.splitlines())
        assert line_count <= MAX_SECTION_LINES, (
            f"Voice-Originated Inputs section body is {line_count} lines; "
            f"cap is {MAX_SECTION_LINES} (description AC #5)"
        )

    def test_section_body_non_empty(self) -> None:
        body = _voice_inputs_body().strip()
        assert body, "Voice-Originated Inputs section body is empty"


class TestPreservedSections:
    @pytest.mark.parametrize(
        "heading", sorted(PRESERVED_SECTION_FIRST_LINES.keys()),
    )
    def test_first_three_body_lines_unchanged(self, heading: str) -> None:
        body = _section_body(_read_heartbeat(), heading)
        first_three = _first_n_non_blank(body, 3)
        expected = PRESERVED_SECTION_FIRST_LINES[heading]
        assert first_three == expected, (
            f"HEARTBEAT.md section {heading!r} drifted from sub-03 baseline. "
            "If the rewrite is intentional, update the snapshot."
        )
