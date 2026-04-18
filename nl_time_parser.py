"""Pure natural-language time-phrase parser lifted from ReminderBot.

Takes free-form phrases like "next week tuesday at 6:30" plus a tz-aware
anchor datetime and returns a ParseResult with the resolved datetime, the
remaining non-time tokens, and whether an explicit clock time was given.

No imports from nanobot or project-internal modules. Stdlib plus
python-dateutil (relativedelta for month arithmetic) only.

Source: references/ReminderBot/parser.py (MIT). Ported line-by-line with
seven hardening changes tracked in _build/tasks/13-nl-time-parsing/sub-01/13-01i.md.
"""

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta

log = logging.getLogger(__name__)

_WEEKDAYS: tuple[str, ...] = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)

_NOT_A_WEEKDAY: int = -1


@dataclass(frozen=True)
class ParseResult:
    when: datetime
    remaining_text: str
    is_precise: bool


class _TokenStream:
    """Mutable cursor over lowercased tokens with three semantic flags.

    Flags are read by the top-level parser after the loop ends:
      precise   — clock time was set (at X, in N minutes/hours)
      any_info  — at least one time token was recognized
      weekday   — a weekday token triggered the next-week wrap path
    """

    def __init__(self, tokens: list[str]) -> None:
        self.tokens: list[str] = tokens
        self.pos: int = 0
        self.precise: bool = False
        self.any_info: bool = False
        self.weekday: bool = False

    def peek(self) -> str | None:
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return None

    def consume(self) -> str | None:
        token = self.peek()
        if token is not None:
            self.pos += 1
        return token


def parse_time_phrase(text: str, now: datetime) -> ParseResult | None:
    """Resolve a natural-language time phrase relative to `now`.

    Returns None when `text` contains no recognizable time token
    (empty input, or only task-text words like "call mum").

    Raises ValueError if `now` is a naive datetime — the caller must
    attach a tz-aware zoneinfo so results are unambiguous across DST
    and across the Windows↔Mac deployment boundary.
    """
    if now.tzinfo is None:
        raise ValueError(
            "parse_time_phrase requires a timezone-aware 'now' datetime; "
            "got naive. Attach zoneinfo.ZoneInfo(NANOBOT_TIMEZONE) before calling."
        )
    tokens = _TokenStream(text.lower().split())
    resolved, remaining = _parse_expression(tokens, now)
    if resolved is None:
        return None
    return ParseResult(
        when=resolved,
        remaining_text=remaining,
        is_precise=tokens.precise,
    )


def _parse_expression(
    tokens: _TokenStream, current_date: datetime
) -> tuple[datetime | None, str]:
    result_date = current_date
    non_tokens: list[str] = []

    while tokens.peek() is not None:
        token = tokens.consume()
        if token is None:
            break
        if token == "next":
            tokens.any_info = True
            result_date = _parse_next(tokens, result_date)
        elif token == "tomorrow":
            tokens.any_info = True
            result_date = result_date + timedelta(days=1)
        elif (weekday := _weekday_to_int(token)) != _NOT_A_WEEKDAY:
            tokens.any_info = True
            if _is_weekday_next_week(result_date, weekday):
                tokens.weekday = True
            result_date = _get_next_weekday(result_date, weekday)
        elif token == "in":
            tokens.any_info = True
            result_date = _parse_in(tokens, result_date)
        elif token == "at":
            tokens.any_info = True
            result_date = _parse_at(tokens, result_date)
        elif _str_to_int(token) is not None:
            tokens.any_info = True
            result_date = _parse_at(tokens, result_date, existing_token=token)
        else:
            non_tokens.append(token)

    resolved: datetime | None = result_date if tokens.any_info else None
    return resolved, " ".join(non_tokens)


def _parse_next(tokens: _TokenStream, current_date: datetime) -> datetime:
    token_next = tokens.consume()
    offset = 0
    while token_next == "next":
        token_next = tokens.consume()
        offset += 1
    if token_next is None:
        return current_date
    if token_next == "week":
        if tokens.weekday:
            return current_date + timedelta(weeks=offset)
        return (
            current_date
            + timedelta(days=7 - current_date.weekday())
            + timedelta(weeks=offset)
        )
    if token_next == "day":
        return current_date + timedelta(days=offset + 1)
    if token_next == "month":
        return current_date + relativedelta(months=offset + 1, day=1)
    target_weekday = _weekday_to_int(token_next)
    if target_weekday != _NOT_A_WEEKDAY:
        return _get_next_weekday(current_date, target_weekday) + timedelta(weeks=offset)
    return current_date


def _parse_in(tokens: _TokenStream, current_date: datetime) -> datetime:
    token_next = tokens.consume()
    if token_next == "a" or token_next == "an":
        token_next = tokens.consume()

    offset = 1
    if token_next is not None:
        parsed_offset = _str_to_int(token_next)
        if parsed_offset is not None:
            offset = parsed_offset
            token_next = tokens.consume()

    if token_next is None:
        return current_date

    if _matches_plural(token_next, "minute"):
        tokens.precise = True
        return current_date + timedelta(minutes=offset)
    if _matches_plural(token_next, "hour"):
        tokens.precise = True
        return current_date + timedelta(hours=offset)
    if _matches_plural(token_next, "day"):
        return current_date + timedelta(days=offset)
    if _matches_plural(token_next, "week"):
        if tokens.weekday:
            offset -= 1
        return current_date + timedelta(days=7 * offset)
    if _matches_plural(token_next, "month"):
        return current_date + relativedelta(months=offset)
    return current_date


def _parse_at(
    tokens: _TokenStream,
    current_date: datetime,
    existing_token: str | None = None,
) -> datetime:
    token_next = existing_token if existing_token is not None else tokens.consume()
    if token_next is None:
        return current_date
    if _str_to_int(token_next.replace(":", "")) is None:
        return current_date
    peeked = tokens.peek()
    if peeked is not None and _str_to_int(peeked) is not None:
        consumed = tokens.consume()
        if consumed is not None:
            token_next = token_next + consumed
    data = _str_to_hours_minutes(token_next)
    if data is None:
        return current_date
    hours, minutes = data
    tokens.precise = True
    return current_date.replace(hour=hours, minute=minutes)


def _weekday_to_int(day: str) -> int:
    if len(day) < 3:
        return _NOT_A_WEEKDAY
    for idx, test_day in enumerate(_WEEKDAYS):
        if day == test_day:
            return idx
        if day in test_day.replace("day", ""):
            return idx
    return _NOT_A_WEEKDAY


def _get_next_weekday(current_date: datetime, target_weekday: int) -> datetime:
    day_offset = (target_weekday - current_date.weekday() + 7) % 7
    return current_date + timedelta(days=day_offset)


def _is_weekday_next_week(current_date: datetime, target_weekday: int) -> bool:
    return target_weekday < current_date.weekday()


def _matches_plural(token: str, match: str) -> bool:
    return token == match or token[:-1] == match


def _str_to_int(token: str) -> int | None:
    try:
        return int(token)
    except ValueError:
        return None


_HHMM_COLON = re.compile(r"^(\d{1,2}):(\d{2})$")
_HHMM_COMPACT = re.compile(r"^(\d{1,2})(\d{2})$")
_HH_ONLY = re.compile(r"^(\d{1,2})$")


def _str_to_hours_minutes(time_str: str) -> tuple[int, int] | None:
    match_colon = _HHMM_COLON.match(time_str)
    if match_colon:
        return int(match_colon.group(1)), int(match_colon.group(2))
    match_compact = _HHMM_COMPACT.match(time_str)
    if match_compact:
        return int(match_compact.group(1)), int(match_compact.group(2))
    match_hour = _HH_ONLY.match(time_str)
    if match_hour:
        return int(match_hour.group(1)), 0
    return None
