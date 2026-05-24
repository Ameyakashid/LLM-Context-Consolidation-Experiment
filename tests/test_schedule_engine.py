"""Tests for state-aware scheduling logic — evaluate_checkin matrix."""

import pytest

from checkin_schedule import CheckInType
from schedule_engine import ScheduleAction, evaluate_checkin
from state_detection import StateName


# ---------------------------------------------------------------------------
# ScheduleAction model tests
# ---------------------------------------------------------------------------

class TestScheduleAction:
    def test_fire_action(self) -> None:
        action = ScheduleAction(action="fire", reason="test")
        assert action.action == "fire"
        assert action.modified_scope is None

    def test_modify_action_with_scope(self) -> None:
        action = ScheduleAction(
            action="modify", reason="test", modified_scope="reduced",
        )
        assert action.modified_scope == "reduced"

    def test_rejects_invalid_action(self) -> None:
        with pytest.raises(ValueError):
            ScheduleAction(action="explode", reason="bad")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Evaluate check-in — baseline and focus (fire everything)
# ---------------------------------------------------------------------------

ALL_CHECKIN_TYPES: list[CheckInType] = [
    "morning_motivation", "morning_plan", "afternoon_check", "evening_review",
]


class TestEvaluateBaselineFocus:
    @pytest.mark.parametrize("state", ["baseline", "focus"])
    @pytest.mark.parametrize("checkin_type", ALL_CHECKIN_TYPES)
    def test_fires_all_checkins(
        self, state: StateName, checkin_type: CheckInType,
    ) -> None:
        result = evaluate_checkin(checkin_type, state)
        assert result.action == "fire"


# ---------------------------------------------------------------------------
# Evaluate check-in — hyperfocus
# ---------------------------------------------------------------------------

class TestEvaluateHyperfocus:
    @pytest.mark.parametrize("checkin_type", [
        "morning_motivation", "morning_plan", "afternoon_check",
    ])
    def test_suppresses_non_critical(self, checkin_type: CheckInType) -> None:
        result = evaluate_checkin(checkin_type, "hyperfocus")
        assert result.action == "suppress"

    def test_fires_evening_review(self) -> None:
        result = evaluate_checkin("evening_review", "hyperfocus")
        assert result.action == "fire"


# ---------------------------------------------------------------------------
# Evaluate check-in — avoidance
# ---------------------------------------------------------------------------

class TestEvaluateAvoidance:
    def test_fires_morning_motivation_with_icnu(self) -> None:
        result = evaluate_checkin("morning_motivation", "avoidance")
        assert result.action == "fire"
        assert "ICNU" in result.reason

    def test_fires_evening_review(self) -> None:
        result = evaluate_checkin("evening_review", "avoidance")
        assert result.action == "fire"

    @pytest.mark.parametrize("checkin_type", [
        "morning_plan", "afternoon_check",
    ])
    def test_modifies_task_checkins(self, checkin_type: CheckInType) -> None:
        result = evaluate_checkin(checkin_type, "avoidance")
        assert result.action == "modify"
        assert result.modified_scope == "reduced"


# ---------------------------------------------------------------------------
# Evaluate check-in — overwhelm
# ---------------------------------------------------------------------------

class TestEvaluateOverwhelm:
    def test_fires_morning_motivation(self) -> None:
        result = evaluate_checkin("morning_motivation", "overwhelm")
        assert result.action == "fire"

    @pytest.mark.parametrize("checkin_type", [
        "morning_plan", "afternoon_check", "evening_review",
    ])
    def test_modifies_to_single_item(self, checkin_type: CheckInType) -> None:
        result = evaluate_checkin(checkin_type, "overwhelm")
        assert result.action == "modify"
        assert result.modified_scope == "single_item"


# ---------------------------------------------------------------------------
# Evaluate check-in — RSD
# ---------------------------------------------------------------------------

class TestEvaluateRsd:
    def test_fires_morning_motivation(self) -> None:
        result = evaluate_checkin("morning_motivation", "rsd")
        assert result.action == "fire"
        assert "emotional" in result.reason

    @pytest.mark.parametrize("checkin_type", [
        "morning_plan", "afternoon_check", "evening_review",
    ])
    def test_suppresses_task_checkins(self, checkin_type: CheckInType) -> None:
        result = evaluate_checkin(checkin_type, "rsd")
        assert result.action == "suppress"
