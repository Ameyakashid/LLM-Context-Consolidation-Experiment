"""Tests for hook_factory: SessionFlag, LLMCallableWrapper, create_hooks chain ordering."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest

from nanobot.agent.hook import AgentHook

from hook_factory import (
    HOOK_CHAIN_ORDER,
    LLMCallableWrapper,
    SessionFlag,
    create_hooks,
)
from custom_gateway import create_stores


@pytest.fixture()
def tmp_data_dir(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return data_dir


@pytest.fixture()
def states_yaml(tmp_path: Path) -> Path:
    """Write a minimal valid states.yaml for testing."""
    states_path = tmp_path / "workspace" / "states.yaml"
    states_path.parent.mkdir(parents=True, exist_ok=True)
    state_names = (
        "baseline", "focus", "hyperfocus", "avoidance", "overwhelm", "rsd",
    )
    states: dict[str, dict[str, object]] = {}
    for state_name in state_names:
        transitions = {s: 0.0 for s in state_names}
        transitions["baseline"] = 1.0
        states[state_name] = {
            "description": f"Test {state_name}",
            "detection_signals": [f"signal_{state_name}"],
            "response_style": [f"style_{state_name}"],
            "transitions": transitions,
        }
    import yaml
    states_path.write_text(yaml.dump({"states": states}), encoding="utf-8")
    return states_path


class TestSessionFlag:
    def test_default_is_false(self) -> None:
        flag = SessionFlag()
        assert flag.is_heartbeat is False

    def test_set_and_read(self) -> None:
        flag = SessionFlag()
        flag.is_heartbeat = True
        assert flag.is_heartbeat is True
        flag.is_heartbeat = False
        assert flag.is_heartbeat is False


class TestLLMCallableWrapper:
    def test_calls_provider_chat(self) -> None:
        provider = MagicMock()
        response = MagicMock()
        response.content = "baseline"
        provider.chat = AsyncMock(return_value=response)

        wrapper = LLMCallableWrapper(provider=provider, model="test-model")
        result = asyncio.run(wrapper("classify this message"))
        assert result == "baseline"
        provider.chat.assert_awaited_once()
        call_kwargs = provider.chat.call_args
        assert call_kwargs.kwargs["model"] == "test-model"
        assert call_kwargs.kwargs["max_tokens"] == 256

    def test_returns_empty_on_none_content(self) -> None:
        provider = MagicMock()
        response = MagicMock()
        response.content = None
        provider.chat = AsyncMock(return_value=response)

        wrapper = LLMCallableWrapper(provider=provider, model="test-model")
        result = asyncio.run(wrapper("test prompt"))
        assert result == ""


def _base_hooks(
    stores: dict[str, object],
    states_yaml: Path,
    tmp_data_dir: Path,
    **extra: object,
) -> list[AgentHook]:
    return create_hooks(
        stores=stores,
        states_path=states_yaml,
        state_file_path=tmp_data_dir / "state.json",
        provider=MagicMock(),
        model="test-model",
        session_flag=SessionFlag(),
        tz=ZoneInfo("UTC"),
        **extra,  # type: ignore[arg-type]
    )


class TestCreateHooks:
    def test_returns_five_hooks_without_calendar(
        self, tmp_data_dir: Path, states_yaml: Path,
    ) -> None:
        stores = create_stores(tmp_data_dir)
        hooks = _base_hooks(stores, states_yaml, tmp_data_dir)
        assert len(hooks) == 5

    def test_chain_order_without_calendar(
        self, tmp_data_dir: Path, states_yaml: Path,
    ) -> None:
        stores = create_stores(tmp_data_dir)
        hooks = _base_hooks(stores, states_yaml, tmp_data_dir)
        names = [h.hook_name for h in hooks]  # type: ignore[attr-defined]
        expected = [n for n in HOOK_CHAIN_ORDER if n != "CalendarContextHook"]
        assert names == expected

    def test_returns_six_hooks_with_calendar(
        self, tmp_data_dir: Path, states_yaml: Path,
    ) -> None:
        from calendar_cache import CalendarCache
        from calendar_mcp_client import CalendarMCPClient
        stores = create_stores(tmp_data_dir)
        hooks = _base_hooks(
            stores, states_yaml, tmp_data_dir,
            calendar_cache=CalendarCache(),
            calendar_client=CalendarMCPClient(),
        )
        assert len(hooks) == 6

    def test_chain_order_with_calendar(
        self, tmp_data_dir: Path, states_yaml: Path,
    ) -> None:
        from calendar_cache import CalendarCache
        from calendar_mcp_client import CalendarMCPClient
        stores = create_stores(tmp_data_dir)
        hooks = _base_hooks(
            stores, states_yaml, tmp_data_dir,
            calendar_cache=CalendarCache(),
            calendar_client=CalendarMCPClient(),
        )
        names = [h.hook_name for h in hooks]  # type: ignore[attr-defined]
        assert names == HOOK_CHAIN_ORDER

    def test_calendar_hook_is_after_scheduling_before_buffer(
        self, tmp_data_dir: Path, states_yaml: Path,
    ) -> None:
        from calendar_cache import CalendarCache
        from calendar_mcp_client import CalendarMCPClient
        stores = create_stores(tmp_data_dir)
        hooks = _base_hooks(
            stores, states_yaml, tmp_data_dir,
            calendar_cache=CalendarCache(),
            calendar_client=CalendarMCPClient(),
        )
        names = [h.hook_name for h in hooks]  # type: ignore[attr-defined]
        sched_idx = names.index("SchedulingHook")
        cal_idx = names.index("CalendarContextHook")
        buf_idx = names.index("BufferHook")
        assert sched_idx < cal_idx < buf_idx

    def test_all_hooks_are_agent_hook_instances(
        self, tmp_data_dir: Path, states_yaml: Path,
    ) -> None:
        stores = create_stores(tmp_data_dir)
        hooks = _base_hooks(stores, states_yaml, tmp_data_dir)
        for hook in hooks:
            assert isinstance(hook, AgentHook)
