"""Cost envelope tests for the Dream engine."""

from __future__ import annotations

import pytest

from dream_engine import DreamEngine
from dream_helpers import estimate_per_run_cost_usd
from dream_types import MAX_COMPLETION_TOKENS, MAX_PROMPT_CHARS, PRICE_TABLE


class TestPerRunBudget:
    def test_grok_pinned_model_under_one_cent(self) -> None:
        cost = estimate_per_run_cost_usd(
            prompt_chars=MAX_PROMPT_CHARS,
            completion_tokens=MAX_COMPLETION_TOKENS,
            model_name="x-ai/grok-4.1-fast",
        )
        assert cost <= 0.01, f"Grok per-run cost {cost:.6f} exceeds $0.01"

    def test_engine_class_constant_matches_cap(self) -> None:
        assert DreamEngine.estimated_cost_per_run_usd <= 0.01


class TestMonthlyBudget:
    def test_one_run_per_day_under_one_dollar_monthly(self) -> None:
        per_run = estimate_per_run_cost_usd(
            prompt_chars=MAX_PROMPT_CHARS,
            completion_tokens=MAX_COMPLETION_TOKENS,
            model_name="x-ai/grok-4.1-fast",
        )
        monthly = per_run * 30
        assert monthly <= 1.0, f"Monthly cost {monthly:.4f} exceeds $1"


class TestPriceTable:
    def test_contains_pinned_model(self) -> None:
        assert "x-ai/grok-4.1-fast" in PRICE_TABLE

    def test_contains_fallback_model(self) -> None:
        assert "openai/gpt-oss-120b" in PRICE_TABLE

    def test_each_entry_has_input_and_output(self) -> None:
        for name, prices in PRICE_TABLE.items():
            assert "input" in prices, f"{name} missing input price"
            assert "output" in prices, f"{name} missing output price"
            assert prices["input"] >= 0
            assert prices["output"] >= 0


class TestCostCalculation:
    def test_zero_usage_costs_zero(self) -> None:
        cost = estimate_per_run_cost_usd(
            prompt_chars=0, completion_tokens=0,
            model_name="x-ai/grok-4.1-fast",
        )
        assert cost == 0.0

    def test_gpt_oss_cheaper_than_grok(self) -> None:
        grok = estimate_per_run_cost_usd(model_name="x-ai/grok-4.1-fast")
        gpt_oss = estimate_per_run_cost_usd(model_name="openai/gpt-oss-120b")
        assert gpt_oss < grok

    def test_unknown_model_raises(self) -> None:
        with pytest.raises(ValueError, match="No price entry"):
            estimate_per_run_cost_usd(model_name="fake/model")

    def test_cost_scales_linearly_with_tokens(self) -> None:
        single = estimate_per_run_cost_usd(
            prompt_chars=4000, completion_tokens=200,
            model_name="x-ai/grok-4.1-fast",
        )
        double = estimate_per_run_cost_usd(
            prompt_chars=8000, completion_tokens=400,
            model_name="x-ai/grok-4.1-fast",
        )
        assert abs(double - 2 * single) < 1e-9
