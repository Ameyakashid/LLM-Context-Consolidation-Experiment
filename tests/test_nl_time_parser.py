"""Tests for nl_time_parser — the natural-language time-phrase parser.

Ported from references/ReminderBot/tests/test_parser.py with tz-aware anchors,
plus new cases covering timezone preservation, naive rejection, empty/non-time
input, self-correction, Friday-on-Friday lock-in, precision detection, and
default-argument regression.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from nl_time_parser import ParseResult, parse_time_phrase


UTC = ZoneInfo("UTC")
LA = ZoneInfo("America/Los_Angeles")


def _saturday_midnight() -> datetime:
    return datetime(2025, 5, 31, 0, 0, tzinfo=UTC)


def _friday_noon() -> datetime:
    return datetime(2025, 5, 30, 12, 0, tzinfo=UTC)


class TestRelative:
    def test_next_week(self) -> None:
        result = parse_time_phrase("next week", _saturday_midnight())
        assert result is not None
        assert result.when.date() == datetime(2025, 6, 2).date()

    def test_in_a_day(self) -> None:
        result = parse_time_phrase("in a day", _saturday_midnight())
        assert result is not None
        assert result.when.date() == datetime(2025, 6, 1).date()

    def test_in_two_days(self) -> None:
        result = parse_time_phrase("in 2 days", _saturday_midnight())
        assert result is not None
        assert result.when.date() == datetime(2025, 6, 2).date()

    def test_in_a_month(self) -> None:
        result = parse_time_phrase("in a month", _saturday_midnight())
        assert result is not None
        assert result.when.date() == datetime(2025, 6, 30).date()

    def test_in_two_months(self) -> None:
        result = parse_time_phrase("in 2 months", _saturday_midnight())
        assert result is not None
        assert result.when.date() == datetime(2025, 7, 31).date()


class TestWeekdays:
    def test_next_tuesday(self) -> None:
        result = parse_time_phrase("next tuesday", _saturday_midnight())
        assert result is not None
        assert result.when.date() == datetime(2025, 6, 3).date()

    def test_tuesday(self) -> None:
        result = parse_time_phrase("tuesday", _saturday_midnight())
        assert result is not None
        assert result.when.date() == datetime(2025, 6, 3).date()

    def test_next_next_tuesday(self) -> None:
        result = parse_time_phrase("next next tuesday", _saturday_midnight())
        assert result is not None
        assert result.when.date() == datetime(2025, 6, 10).date()

    def test_next_week_tuesday(self) -> None:
        result = parse_time_phrase("next week tuesday", _saturday_midnight())
        assert result is not None
        assert result.when.date() == datetime(2025, 6, 3).date()

    def test_next_week_monday(self) -> None:
        result = parse_time_phrase("next week monday", _saturday_midnight())
        assert result is not None
        assert result.when.date() == datetime(2025, 6, 2).date()

    def test_monday_next_week(self) -> None:
        result = parse_time_phrase("monday next week", _saturday_midnight())
        assert result is not None
        assert result.when.date() == datetime(2025, 6, 2).date()

    def test_in_a_week_monday(self) -> None:
        result = parse_time_phrase("in a week monday", _saturday_midnight())
        assert result is not None
        assert result.when.date() == datetime(2025, 6, 9).date()

    def test_friday_on_a_friday_returns_same_date(self) -> None:
        # Behavior preserved from ReminderBot; clarification is sub-03's scope.
        now = _friday_noon()
        result = parse_time_phrase("friday", now)
        assert result is not None
        assert result.when.date() == now.date()

    def test_weekday_abbreviation_mon(self) -> None:
        result = parse_time_phrase("mon", _saturday_midnight())
        assert result is not None
        assert result.when.date() == datetime(2025, 6, 2).date()

    def test_weekday_abbreviation_tue(self) -> None:
        result = parse_time_phrase("tue", _saturday_midnight())
        assert result is not None
        assert result.when.date() == datetime(2025, 6, 3).date()


class TestTimeExtraction:
    def test_at_time_compact(self) -> None:
        result = parse_time_phrase("next day at 530", _saturday_midnight())
        assert result is not None
        assert result.when == datetime(2025, 6, 1, 5, 30, tzinfo=UTC)
        assert result.is_precise is True

    def test_at_time_space(self) -> None:
        result = parse_time_phrase("next day at 5 45", _saturday_midnight())
        assert result is not None
        assert result.when == datetime(2025, 6, 1, 5, 45, tzinfo=UTC)
        assert result.is_precise is True

    def test_at_time_colon_today(self) -> None:
        result = parse_time_phrase("at 6:30", _saturday_midnight())
        assert result is not None
        assert result.when == datetime(2025, 5, 31, 6, 30, tzinfo=UTC)
        assert result.is_precise is True

    def test_at_time_24h(self) -> None:
        result = parse_time_phrase("at 14:00", _saturday_midnight())
        assert result is not None
        assert result.when.hour == 14
        assert result.when.minute == 0
        assert result.is_precise is True

    def test_in_30_minutes_is_precise(self) -> None:
        now = datetime(2025, 5, 31, 10, 0, tzinfo=UTC)
        result = parse_time_phrase("in 30 minutes", now)
        assert result is not None
        assert result.when == now + timedelta(minutes=30)
        assert result.is_precise is True

    def test_in_2_hours_is_precise(self) -> None:
        now = datetime(2025, 5, 31, 10, 0, tzinfo=UTC)
        result = parse_time_phrase("in 2 hours", now)
        assert result is not None
        assert result.when == now + timedelta(hours=2)
        assert result.is_precise is True

    def test_in_days_is_not_precise(self) -> None:
        result = parse_time_phrase("in 2 days", _saturday_midnight())
        assert result is not None
        assert result.is_precise is False


class TestTimezone:
    def test_preserves_la_timezone_on_tomorrow(self) -> None:
        now = datetime(2025, 5, 31, 10, 0, tzinfo=LA)
        result = parse_time_phrase("tomorrow", now)
        assert result is not None
        assert result.when.tzinfo == LA
        assert result.when == now + timedelta(days=1)

    def test_preserves_utc_timezone_on_at(self) -> None:
        now = datetime(2025, 5, 31, 10, 0, tzinfo=UTC)
        result = parse_time_phrase("at 14:00", now)
        assert result is not None
        assert result.when.tzinfo == UTC

    def test_preserves_timezone_across_in_minutes(self) -> None:
        now = datetime(2025, 5, 31, 10, 0, tzinfo=LA)
        result = parse_time_phrase("in 15 minutes", now)
        assert result is not None
        assert result.when.tzinfo == LA

    def test_naive_now_raises_value_error(self) -> None:
        naive = datetime(2025, 5, 31)
        with pytest.raises(ValueError, match="timezone-aware"):
            parse_time_phrase("tomorrow", naive)


class TestRegressions:
    def test_empty_string_returns_none(self) -> None:
        assert parse_time_phrase("", _saturday_midnight()) is None

    def test_pure_non_time_text_returns_none(self) -> None:
        assert parse_time_phrase("call mum", _saturday_midnight()) is None

    def test_self_correcting_last_time_token_wins(self) -> None:
        # Acceptance criterion 8: "tomorrow no actually friday" resolves to
        # Friday, not to Sunday. The non-time words land in remaining_text.
        result = parse_time_phrase("tomorrow no actually friday", _saturday_midnight())
        assert result is not None
        assert result.when.date() == datetime(2025, 6, 6).date()
        assert "no" in result.remaining_text.split()
        assert "actually" in result.remaining_text.split()

    def test_returns_parseresult_instance(self) -> None:
        result = parse_time_phrase("tomorrow", _saturday_midnight())
        assert isinstance(result, ParseResult)

    def test_parseresult_is_frozen(self) -> None:
        result = parse_time_phrase("tomorrow", _saturday_midnight())
        assert result is not None
        with pytest.raises(Exception):
            result.when = datetime(2000, 1, 1, tzinfo=UTC)  # type: ignore[misc]

    def test_default_arg_footgun_removed(self) -> None:
        # Two calls with different `now` must produce `when` relative to that
        # `now`, proving no import-time datetime.now() default survives.
        t1 = datetime(2025, 5, 31, 10, 0, tzinfo=UTC)
        t2 = datetime(2025, 8, 15, 15, 0, tzinfo=UTC)
        r1 = parse_time_phrase("tomorrow", t1)
        r2 = parse_time_phrase("tomorrow", t2)
        assert r1 is not None and r2 is not None
        assert r1.when == t1 + timedelta(days=1)
        assert r2.when == t2 + timedelta(days=1)

    def test_task_text_before_time_token_preserved(self) -> None:
        result = parse_time_phrase("buy groceries tomorrow", _saturday_midnight())
        assert result is not None
        assert result.when.date() == datetime(2025, 6, 1).date()
        assert "buy" in result.remaining_text.split()
        assert "groceries" in result.remaining_text.split()
