"""Tests for custom_gateway module: store init, hook ordering, tool registration, adapter wrapping."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest

from hook_adapter import HookAdapter
from nanobot.agent.hook import AgentHook, AgentHookContext

from custom_gateway import (
    HOOK_CHAIN_ORDER,
    LLMCallableWrapper,
    SessionFlag,
    create_hooks,
    create_stores,
    register_all_tools,
    register_voice_tools_deferred,
    resolve_data_dir,
    resolve_states_path,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

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
    # Minimal valid config with all 6 states
    states: dict[str, dict[str, object]] = {}
    for state_name in ("baseline", "focus", "hyperfocus", "avoidance", "overwhelm", "rsd"):
        transitions = {s: 0.0 for s in ("baseline", "focus", "hyperfocus", "avoidance", "overwhelm", "rsd")}
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


# ---------------------------------------------------------------------------
# SessionFlag
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Store initialization
# ---------------------------------------------------------------------------

class TestCreateStores:
    def test_creates_data_directory(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "new_data"
        assert not data_dir.exists()
        stores = create_stores(data_dir)
        assert data_dir.exists()
        assert "task" in stores
        assert "buffer" in stores
        assert "memory" in stores
        assert "schedule" in stores

    def test_four_stores_returned(self, tmp_data_dir: Path) -> None:
        stores = create_stores(tmp_data_dir)
        assert len(stores) == 4

    def test_stores_create_files_on_use(self, tmp_data_dir: Path) -> None:
        stores = create_stores(tmp_data_dir)
        # Stores create files lazily on first write, but TaskStore creates on init
        from task_store import TaskStore
        assert isinstance(stores["task"], TaskStore)


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

class TestResolveDataDir:
    def test_default_uses_parent_data_dir(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        result = resolve_data_dir(workspace)
        assert result == tmp_path / "data"

    def test_env_override(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        custom_dir = tmp_path / "custom"
        monkeypatch.setenv("ADHD_DATA_DIR", str(custom_dir))
        result = resolve_data_dir(tmp_path)
        assert result == custom_dir.resolve()


class TestResolveStatesPath:
    def test_default_uses_workspace_subpath(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace_dir"
        result = resolve_states_path(workspace)
        assert result == workspace / "states.yaml"

    def test_env_override(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        custom_path = tmp_path / "my_states.yaml"
        monkeypatch.setenv("ADHD_STATES_PATH", str(custom_path))
        result = resolve_states_path(tmp_path)
        assert result == custom_path.resolve()


# ---------------------------------------------------------------------------
# Hook ordering
# ---------------------------------------------------------------------------

class TestCreateHooks:
    def test_returns_five_hooks(
        self, tmp_data_dir: Path, states_yaml: Path,
    ) -> None:
        stores = create_stores(tmp_data_dir)
        provider = MagicMock()
        session_flag = SessionFlag()
        hooks = create_hooks(
            stores=stores,
            states_path=states_yaml,
            state_file_path=tmp_data_dir / "state.json",
            provider=provider,
            model="test-model",
            session_flag=session_flag,
            tz=ZoneInfo("UTC"),
        )
        assert len(hooks) == 5

    def test_correct_chain_order(
        self, tmp_data_dir: Path, states_yaml: Path,
    ) -> None:
        stores = create_stores(tmp_data_dir)
        provider = MagicMock()
        session_flag = SessionFlag()
        hooks = create_hooks(
            stores=stores,
            states_path=states_yaml,
            state_file_path=tmp_data_dir / "state.json",
            provider=provider,
            model="test-model",
            session_flag=session_flag,
            tz=ZoneInfo("UTC"),
        )
        names = [h.hook_name for h in hooks]  # type: ignore[attr-defined]
        assert names == HOOK_CHAIN_ORDER

    def test_all_hooks_are_agent_hook_instances(
        self, tmp_data_dir: Path, states_yaml: Path,
    ) -> None:
        stores = create_stores(tmp_data_dir)
        provider = MagicMock()
        session_flag = SessionFlag()
        hooks = create_hooks(
            stores=stores,
            states_path=states_yaml,
            state_file_path=tmp_data_dir / "state.json",
            provider=provider,
            model="test-model",
            session_flag=session_flag,
            tz=ZoneInfo("UTC"),
        )
        for hook in hooks:
            assert isinstance(hook, AgentHook)



# ---------------------------------------------------------------------------
# Adapter wrapping
# ---------------------------------------------------------------------------

class TestHookAdapter:
    def test_is_agent_hook(self) -> None:
        mock_hook = AsyncMock()
        adapter = HookAdapter(hook=mock_hook, name="TestHook")
        assert isinstance(adapter, AgentHook)

    def test_delegates_before_iteration(self) -> None:
        mock_hook = AsyncMock()
        adapter = HookAdapter(hook=mock_hook, name="TestHook")
        context = MagicMock(spec=AgentHookContext)
        asyncio.run(adapter.before_iteration(context))
        mock_hook.before_iteration.assert_awaited_once_with(context)

    def test_exposes_wrapped_hook(self) -> None:
        mock_hook = AsyncMock()
        adapter = HookAdapter(hook=mock_hook, name="TestHook")
        assert adapter.wrapped is mock_hook

    def test_hook_name_property(self) -> None:
        mock_hook = AsyncMock()
        adapter = HookAdapter(hook=mock_hook, name="MyHook")
        assert adapter.hook_name == "MyHook"

    def test_swallows_hook_exception(self) -> None:
        mock_hook = AsyncMock()
        mock_hook.before_iteration.side_effect = RuntimeError("boom")
        adapter = HookAdapter(hook=mock_hook, name="CrashHook")
        context = MagicMock(spec=AgentHookContext)
        # Should not raise
        asyncio.run(adapter.before_iteration(context))


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

EXPECTED_NON_VOICE_TOOL_COUNT = 5 + 5 + 3


class TestRegisterAllTools:
    def test_returns_sum_of_per_registrar_counts(self, tmp_data_dir: Path) -> None:
        stores = create_stores(tmp_data_dir)
        registry = MagicMock(spec=["register"])
        count = register_all_tools(registry, stores)
        assert count == EXPECTED_NON_VOICE_TOOL_COUNT

    def test_registers_on_registry(self, tmp_data_dir: Path) -> None:
        stores = create_stores(tmp_data_dir)
        registry = MagicMock(spec=["register"])
        register_all_tools(registry, stores)
        assert registry.register.call_count == EXPECTED_NON_VOICE_TOOL_COUNT


class TestRegisterVoiceToolsDeferred:
    def test_returns_one_when_message_tool_exists(self) -> None:
        registry = MagicMock()
        registry.get.return_value = MagicMock()  # mock MessageTool
        count = register_voice_tools_deferred(registry)
        assert count == 1

    def test_returns_zero_when_no_message_tool(self) -> None:
        registry = MagicMock()
        registry.get.return_value = None
        count = register_voice_tools_deferred(registry)
        assert count == 0


# ---------------------------------------------------------------------------
# LLMCallableWrapper
# ---------------------------------------------------------------------------

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
