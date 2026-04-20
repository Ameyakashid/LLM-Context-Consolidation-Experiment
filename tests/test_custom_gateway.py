"""Tests for custom_gateway module: stores, paths, adapter, tool registration.

Hook-chain construction moved to hook_factory.py and is tested in
``test_hook_factory.py``; this file covers the remaining surface
(stores, path resolution, HookAdapter, tool registration).
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from hook_adapter import HookAdapter
from nanobot.agent.hook import AgentHook, AgentHookContext

from custom_gateway import (
    create_stores,
    register_all_tools,
    register_voice_tools_deferred,
    resolve_data_dir,
    resolve_states_path,
)


@pytest.fixture()
def tmp_data_dir(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return data_dir


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
        from task_store import TaskStoreProtocol
        assert isinstance(stores["task"], TaskStoreProtocol)


class TestResolveDataDir:
    def test_default_uses_parent_data_dir(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        result = resolve_data_dir(workspace)
        assert result == tmp_path / "data"

    def test_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        custom_dir = tmp_path / "custom"
        monkeypatch.setenv("ADHD_DATA_DIR", str(custom_dir))
        result = resolve_data_dir(tmp_path)
        assert result == custom_dir.resolve()

    def test_env_override_expands_tilde(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("ADHD_DATA_DIR", "~/adhd-data-test-dir")
        result = resolve_data_dir(tmp_path)
        assert str(result).startswith(str(Path.home()))
        assert "~" not in str(result)


class TestResolveStatesPath:
    def test_default_uses_workspace_subpath(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace_dir"
        result = resolve_states_path(workspace)
        assert result == workspace / "states.yaml"

    def test_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        custom_path = tmp_path / "my_states.yaml"
        monkeypatch.setenv("ADHD_STATES_PATH", str(custom_path))
        result = resolve_states_path(tmp_path)
        assert result == custom_path.resolve()

    def test_env_override_expands_tilde(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("ADHD_STATES_PATH", "~/adhd-states-test.yaml")
        result = resolve_states_path(tmp_path)
        assert str(result).startswith(str(Path.home()))
        assert "~" not in str(result)


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
        asyncio.run(adapter.before_iteration(context))


EXPECTED_NON_VOICE_TOOL_COUNT = 5 + 5 + 3


class TestRegisterAllTools:
    def test_returns_sum_of_per_registrar_counts(
        self, tmp_data_dir: Path,
    ) -> None:
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
        registry.get.return_value = MagicMock()
        count = register_voice_tools_deferred(registry)
        assert count == 1

    def test_returns_zero_when_no_message_tool(self) -> None:
        registry = MagicMock()
        registry.get.return_value = None
        count = register_voice_tools_deferred(registry)
        assert count == 0
