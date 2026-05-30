"""Disco Elysium daisy chain engine for the ADHD assistant.

Orchestrates a 3-voice commentary chain: builds prompts, runs sequential
LLM calls, parses JSON responses, and formats the final output.
"""

import json
import logging
import re
from dataclasses import dataclass
from typing import Protocol

from disco_config import DiscoConfig, DiscoVoice

log = logging.getLogger(__name__)


class LLMCallable(Protocol):
    """Protocol for the async LLM call function injected into the engine."""
    async def __call__(self, prompt: str) -> str: ...


@dataclass(frozen=True)
class DiscoComment:
    """One voice's output from the daisy chain."""
    voice_name: str
    comment: str
    difficulty: str
    outcome: str
    next_voice: str | None


def build_voice_prompt(
    voice: DiscoVoice,
    context: dict[str, str],
    prior_comments: list[DiscoComment],
    available_voices: list[str],
    is_final: bool,
) -> str:
    """Build the full prompt for a single voice LLM call."""
    sections: list[str] = []

    sections.append(
        f"You are {voice.display_name} -- one of the inner voices "
        f"in an ADHD assistant.\n\n"
        f"{voice.description.strip()}\n\n"
        f"Your tone: {voice.tone.strip()}"
    )

    example_lines = "\n".join(f'- "{line}"' for line in voice.example_lines)
    sections.append(f"Example lines in your voice:\n{example_lines}")

    sections.append(
        f'The user said: "{context["user_message"]}"\n\n'
        f'The assistant responded: "{context["main_response"]}"\n\n'
        f'Current cognitive state: {context["cognitive_state"]}\n\n'
        f'Task context: {context["task_context"]}'
    )

    if prior_comments:
        prior_lines = "\n".join(
            f"- {c.voice_name.upper()} said: \"{c.comment}\""
            for c in prior_comments
        )
        sections.append(f"Previous voices have spoken:\n{prior_lines}")

    instructions = (
        "Respond with a brief observation (1-2 sentences max) in your voice.\n"
        "Choose a difficulty level from: Trivial, Easy, Medium, Challenging, "
        "Heroic, Legendary\n"
        "Choose an outcome: Success or Failure"
    )

    if is_final:
        json_example = (
            '{\n  "comment": "your observation here",\n'
            '  "difficulty": "Medium",\n  "outcome": "Success"\n}'
        )
    else:
        voices_list = ", ".join(available_voices)
        instructions += (
            f"\nAlso select the next voice to speak from: [{voices_list}]"
        )
        first = available_voices[0] if available_voices else ""
        json_example = (
            '{\n  "comment": "your observation here",\n'
            '  "difficulty": "Medium",\n  "outcome": "Success",\n'
            f'  "next_voice": "{first}"\n'
            '}'
        )

    sections.append(
        f"{instructions}\n\nRespond in this exact JSON format:\n{json_example}"
    )

    return "\n\n".join(sections)


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def _strip_fences(raw: str) -> str:
    """Strip markdown code fences Claude likes to wrap JSON in."""
    s = raw.strip()
    s = _FENCE_RE.sub("", s).strip()
    # If model returned multiple fenced blocks, try to extract the first {...}
    if not s.startswith("{"):
        i, j = s.find("{"), s.rfind("}")
        if i != -1 and j != -1 and j > i:
            s = s[i:j + 1]
    return s


def parse_voice_response(
    raw_response: str,
    voice_name: str,
    is_final: bool,
) -> DiscoComment:
    """Parse JSON from LLM response into a DiscoComment."""
    cleaned = _strip_fences(raw_response)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Voice '{voice_name}' returned malformed JSON: {raw_response!r}"
        ) from exc

    if not isinstance(data, dict):
        raise ValueError(
            f"Voice '{voice_name}' returned non-object JSON: {raw_response!r}"
        )

    comment = data.get("comment")
    if not comment or not isinstance(comment, str):
        raise ValueError(
            f"Voice '{voice_name}' response missing 'comment' field"
        )

    difficulty = data.get("difficulty")
    if not difficulty or not isinstance(difficulty, str):
        raise ValueError(
            f"Voice '{voice_name}' response missing 'difficulty' field"
        )

    outcome = data.get("outcome")
    if not outcome or not isinstance(outcome, str):
        raise ValueError(
            f"Voice '{voice_name}' response missing 'outcome' field"
        )

    next_voice: str | None = None
    if not is_final:
        next_voice = data.get("next_voice")
        if next_voice is not None and not isinstance(next_voice, str):
            next_voice = None

    return DiscoComment(
        voice_name=voice_name,
        comment=comment,
        difficulty=difficulty,
        outcome=outcome,
        next_voice=next_voice,
    )


def _resolve_next_voice(
    selected: str | None,
    already_spoken: set[str],
    available_voices: dict[str, DiscoVoice],
) -> str | None:
    """Resolve the next voice, falling back if selection is invalid."""
    if (
        selected is not None
        and selected in available_voices
        and selected not in already_spoken
    ):
        return selected

    for voice_key in available_voices:
        if voice_key not in already_spoken:
            if selected is not None:
                log.warning(
                    "Invalid next_voice '%s', falling back to '%s'",
                    selected, voice_key,
                )
            return voice_key
    return None


async def run_disco_chain(
    main_response: str,
    user_message: str,
    cognitive_state: str,
    task_context: str,
    config: DiscoConfig,
    llm_call: LLMCallable,
) -> list[DiscoComment]:
    """Run the 3-voice daisy chain, returning 0-3 DiscoComment objects."""
    context: dict[str, str] = {
        "user_message": user_message,
        "main_response": main_response,
        "cognitive_state": cognitive_state,
        "task_context": task_context,
    }

    comments: list[DiscoComment] = []
    already_spoken: set[str] = set()
    current_voice_key: str = config.first_voice

    for step in range(config.max_voices):
        is_final = step == config.max_voices - 1
        voice = config.voices.get(current_voice_key)

        if voice is None:
            log.error(
                "Voice '%s' not found in config at step %d. "
                "Stopping chain with %d comments.",
                current_voice_key, step, len(comments),
            )
            break

        available_for_next: list[str] = [
            key for key in config.voices
            if key not in already_spoken and key != current_voice_key
        ]

        prompt = build_voice_prompt(
            voice=voice,
            context=context,
            prior_comments=comments,
            available_voices=available_for_next,
            is_final=is_final,
        )

        try:
            raw_response = await llm_call(prompt)
        except Exception:
            log.exception(
                "LLM call failed for voice '%s' at step %d. "
                "Returning %d partial comments.",
                current_voice_key, step, len(comments),
            )
            break

        try:
            comment = parse_voice_response(
                raw_response=raw_response,
                voice_name=current_voice_key,
                is_final=is_final,
            )
        except ValueError:
            log.exception(
                "Failed to parse response from voice '%s' at step %d. "
                "Returning %d partial comments.",
                current_voice_key, step, len(comments),
            )
            break

        comments.append(comment)
        already_spoken.add(current_voice_key)

        if not is_final:
            next_key = _resolve_next_voice(
                selected=comment.next_voice,
                already_spoken=already_spoken,
                available_voices=config.voices,
            )
            if next_key is None:
                log.warning(
                    "No available voices remaining after step %d. "
                    "Returning %d comments.", step, len(comments),
                )
                break
            current_voice_key = next_key

    return comments


def format_disco_output(
    comments: list[DiscoComment],
    config: DiscoConfig,
) -> str:
    """Format disco comments, one italic line per voice.

    ``*VOICE [Difficulty: Outcome] \u2014 "comment"*``, lines joined by a single
    newline (no blank line) so callers can split the prepend on a ``\\n\\n``
    separator and recover the untouched main response.
    """
    if not comments:
        return ""
    lines: list[str] = []
    for comment in comments:
        if not comment.comment:
            continue
        voice = config.voices.get(comment.voice_name)
        display_name = voice.display_name if voice else comment.voice_name.upper()
        lines.append(
            f"*{display_name} [{comment.difficulty}: {comment.outcome}] "
            f'\u2014 "{comment.comment}"*'
        )
    return "\n".join(lines)
