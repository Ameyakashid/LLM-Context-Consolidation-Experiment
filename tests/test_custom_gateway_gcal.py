"""Tests for the google-calendar branch of custom_gateway.register_all_tools."""

from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.agent.tools.registry import ToolRegistry

from calendar_tools import CALENDAR_TOOL_NAMES
from custom_gateway import create_stores, register_all_tools


GCAL_FLAG = "GOOGLE_CALENDAR_ENABLED"
EXPECTED_BASE_COUNT = 5 + 5 + 3
EXPECTED_WITH_GCAL_COUNT = EXPECTED_BASE_COUNT + 3


@pytest.fixture()
def tmp_stores(tmp_path: Path) -> dict[str, object]:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return create_stores(data_dir)


class TestRegisterAllToolsFeatureFlag:
    def test_flag_unset_skips_calendar_tools(
        self, tmp_stores: dict[str, object], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(GCAL_FLAG, raising=False)
        registry = ToolRegistry()
        count = register_all_tools(registry, tmp_stores)
        assert count == EXPECTED_BASE_COUNT
        for name in CALENDAR_TOOL_NAMES:
            assert not registry.has(name)

    def test_flag_false_skips_calendar_tools(
        self, tmp_stores: dict[str, object], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(GCAL_FLAG, "false")
        registry = ToolRegistry()
        count = register_all_tools(registry, tmp_stores)
        assert count == EXPECTED_BASE_COUNT

    def test_flag_true_registers_calendar_tools(
        self, tmp_stores: dict[str, object], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(GCAL_FLAG, "true")
        registry = ToolRegistry()
        count = register_all_tools(registry, tmp_stores)
        assert count == EXPECTED_WITH_GCAL_COUNT
        for name in CALENDAR_TOOL_NAMES:
            assert registry.has(name), f"Missing calendar tool: {name}"

    def test_flag_true_mixed_case_registers(
        self, tmp_stores: dict[str, object], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(GCAL_FLAG, "TRUE")
        registry = ToolRegistry()
        count = register_all_tools(registry, tmp_stores)
        assert count == EXPECTED_WITH_GCAL_COUNT

    def test_all_previously_registered_tools_still_present(
        self, tmp_stores: dict[str, object], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(GCAL_FLAG, "true")
        registry = ToolRegistry()
        register_all_tools(registry, tmp_stores)
        for name in (
            "create_task",
            "list_tasks",
            "create_buffer",
            "save_memory",
        ):
            assert registry.has(name)
